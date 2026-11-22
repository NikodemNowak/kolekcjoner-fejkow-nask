"""Pack and unpack the content-addressed feature cache for private sharing inside the team.

The archive holds `features/<extractor>/v<version>/<id[:2]>/<id>.{json,npy}` and
`keyframes/<video id>/*` exactly as laid out under the cache root, plus a `MANIFEST.json`.
It contains organizer-derived data (OCR and ASR text): never commit or publish it.
Unpacking only accepts regular files and directories under those two top-level folders.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

TOP_LEVEL = ("features", "keyframes")
MANIFEST_NAME = "MANIFEST.json"


def keyframe_ids(cache_root: Path, video_ids: Iterable[str]) -> set[str]:
    """Artifact ids of the cached keyframes of the given videos (from their manifests)."""
    out: set[str] = set()
    for vid in video_ids:
        manifest = cache_root / "keyframes" / vid / "manifest.json"
        try:
            frames = json.loads(manifest.read_text())["frames"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out |= {f["id"] for f in frames if isinstance(f, dict) and "id" in f}
    return out


def collect_entries(cache_root: Path, artifact_ids: set[str] | None = None) -> list[Path]:
    """Relative paths of complete cache entries, optionally only for `artifact_ids`.

    A feature entry is kept when its `.json` exists (written last, so it marks completeness);
    temporary files are skipped. Keyframe folders are keyed by the video's artifact id.
    """
    out: list[Path] = []
    feats = cache_root / "features"
    if feats.is_dir():
        for meta in sorted(feats.glob("*/*/*/*.json")):
            if artifact_ids is not None and meta.stem not in artifact_ids:
                continue
            npy = meta.with_suffix(".npy")
            if npy.is_file():  # vectors before the json, which marks a complete entry
                out.append(npy.relative_to(cache_root))
            out.append(meta.relative_to(cache_root))
    frames = cache_root / "keyframes"
    if frames.is_dir():
        for vdir in sorted(p for p in frames.iterdir() if p.is_dir()):
            if artifact_ids is not None and vdir.name not in artifact_ids:
                continue
            if not (vdir / "manifest.json").is_file():
                continue
            out += [
                f.relative_to(cache_root)
                for f in sorted(vdir.iterdir())
                if f.is_file() and not f.name.endswith(".tmp")
            ]
    return out


def summarize(entries: Iterable[Path]) -> dict[str, Any]:
    """Counts per extractor and cache version, plus keyframe videos and frames."""
    extractors: dict[str, dict[str, int]] = {}
    videos: set[str] = set()
    frames = 0
    files = 0
    for rel in entries:
        files += 1
        parts = rel.parts
        if parts[0] == "features" and rel.suffix == ".json" and len(parts) == 5:
            by_ver = extractors.setdefault(parts[1], {})
            by_ver[parts[2]] = by_ver.get(parts[2], 0) + 1
        elif parts[0] == "keyframes" and len(parts) == 3:
            videos.add(parts[1])
            frames += rel.suffix == ".jpg"
    return {
        "files": files,
        "extractors": {k: dict(sorted(v.items())) for k, v in sorted(extractors.items())},
        "keyframes": {"videos": len(videos), "frames": frames},
    }


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Hex sha256 of a file, read in chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def write_archive(
    cache_root: Path, entries: list[Path], archive: Path, manifest: dict[str, Any]
) -> None:
    """Write a gzip tarball of `entries` (relative to `cache_root`) with `MANIFEST.json`."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = archive.with_name(archive.name + ".tmp")
    with tarfile.open(tmp, "w:gz") as tar:
        data = json.dumps(manifest, indent=2, sort_keys=True).encode()
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for rel in entries:
            tar.add(cache_root / rel, arcname=rel.as_posix(), recursive=False)
    tmp.replace(archive)


def is_safe_member(member: tarfile.TarInfo) -> bool:
    """Accept only regular files/directories under a known top-level folder (or the manifest)."""
    if not (member.isfile() or member.isdir()):
        return False
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return False
    if member.name == MANIFEST_NAME:
        return True
    return path.parts[0] in TOP_LEVEL and len(path.parts) >= 2


def extract_archive(archive: Path, cache_root: Path, overwrite: bool = False) -> dict[str, int]:
    """Unpack an archive into `cache_root`; returns counts of written, kept and rejected files.

    Existing files are kept unless `overwrite` (entries are content-addressed, so an existing
    file with the same path already holds the same features).
    """
    counts = {"written": 0, "kept": 0, "rejected": 0}
    cache_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            if not is_safe_member(member):
                counts["rejected"] += 1
                continue
            if member.isdir() or member.name == MANIFEST_NAME:
                continue
            dest = cache_root / member.name
            if dest.exists() and not overwrite:
                counts["kept"] += 1
                continue
            src = tar.extractfile(member)
            if src is None:
                counts["rejected"] += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            with src, tmp.open("wb") as fh:
                while block := src.read(1 << 20):
                    fh.write(block)
            tmp.replace(dest)
            counts["written"] += 1
    return counts


def read_manifest(archive: Path) -> dict[str, Any] | None:
    """The `MANIFEST.json` embedded in an archive, or None."""
    with tarfile.open(archive, "r:*") as tar:
        try:
            member = tar.getmember(MANIFEST_NAME)
        except KeyError:
            return None
        fh = tar.extractfile(member)
        if fh is None:
            return None
        data: dict[str, Any] = json.loads(fh.read())
        return data
