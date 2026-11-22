"""Tests for packing and unpacking the shared feature cache (synthetic entries only)."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from fakecollector.dev.cache_share import (
    collect_entries,
    extract_archive,
    is_safe_member,
    keyframe_ids,
    read_manifest,
    summarize,
    write_archive,
)


def _cache(root: Path) -> Path:
    for ext, ver, aid, npy in (
        ("image_hash", "v1-pdq", "aa11", False),
        ("image_siglip", "v1-x", "aa11", True),
        ("ocr", "v1", "bb22", False),
    ):
        d = root / "features" / ext / ver / aid[:2]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{aid}.json").write_text("[]")
        if npy:
            (d / f"{aid}.npy").write_bytes(b"npy")
    (root / "features" / "ocr" / "v1" / "bb" / "bb22.json.tmp").write_text("partial")
    kf = root / "keyframes" / "vid1"
    kf.mkdir(parents=True)
    (kf / "t=000.0s.jpg").write_bytes(b"jpg")
    frames = [{"file": "t=000.0s.jpg", "t": "0.0", "id": "kf01"}]
    (kf / "manifest.json").write_text(json.dumps({"version": 1, "max": 40, "frames": frames}))
    (root / "keyframes" / "broken").mkdir()  # no manifest: never exported
    return root


def test_collect_entries_filters_by_artifact_ids(tmp_path: Path) -> None:
    root = _cache(tmp_path / "c")
    all_entries = collect_entries(root)
    names = [p.as_posix() for p in all_entries]
    assert "features/image_siglip/v1-x/aa/aa11.npy" in names
    assert names.index("features/image_siglip/v1-x/aa/aa11.npy") < names.index(
        "features/image_siglip/v1-x/aa/aa11.json"
    )
    assert not any(n.endswith(".tmp") or "broken" in n for n in names)
    only = {p.as_posix() for p in collect_entries(root, {"bb22", "vid1"})}
    assert only == {
        "features/ocr/v1/bb/bb22.json",
        "keyframes/vid1/manifest.json",
        "keyframes/vid1/t=000.0s.jpg",
    }


def test_keyframe_ids_reads_manifests(tmp_path: Path) -> None:
    root = _cache(tmp_path / "c")
    assert keyframe_ids(root, ["vid1", "missing", "broken"]) == {"kf01"}


def test_summarize_counts_entries(tmp_path: Path) -> None:
    root = _cache(tmp_path / "c")
    stats = summarize(collect_entries(root))
    assert stats["extractors"] == {
        "image_hash": {"v1-pdq": 1},
        "image_siglip": {"v1-x": 1},
        "ocr": {"v1": 1},
    }
    assert stats["keyframes"] == {"videos": 1, "frames": 1}


def test_archive_round_trip(tmp_path: Path) -> None:
    src = _cache(tmp_path / "src")
    entries = collect_entries(src)
    archive = tmp_path / "out" / "cache.tar.gz"
    write_archive(src, entries, archive, {"format": 1})
    assert read_manifest(archive) == {"format": 1}
    dst = tmp_path / "dst"
    counts = extract_archive(archive, dst)
    assert counts == {"written": len(entries), "kept": 0, "rejected": 0}
    for rel in entries:
        assert (dst / rel).read_bytes() == (src / rel).read_bytes()
    again = extract_archive(archive, dst)
    assert again["kept"] == len(entries)
    assert again["written"] == 0


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("features/ocr/v1/bb/bb22.json", True),
        ("MANIFEST.json", True),
        ("../evil", False),
        ("/etc/passwd", False),
        ("features/../../evil", False),
        ("other/file", False),
        ("features", False),
    ],
)
def test_is_safe_member_paths(name: str, ok: bool) -> None:
    info = tarfile.TarInfo(name)
    assert is_safe_member(info) is ok


def test_extract_rejects_links_and_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        link = tarfile.TarInfo("features/x/v1/aa/link.json")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
        evil = tarfile.TarInfo("../evil.txt")
        evil.size = 1
        tar.addfile(evil, io.BytesIO(b"x"))
    counts = extract_archive(archive, tmp_path / "dst")
    assert counts == {"written": 0, "kept": 0, "rejected": 2}
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "dst" / "features" / "x" / "v1" / "aa" / "link.json").exists()
