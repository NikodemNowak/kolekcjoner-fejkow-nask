"""Undecodable file names must never leak surrogates into ids, meta or locators."""

import os
from pathlib import Path

import pytest

from fakecollector.extractors.asset import AssetExtractor
from fakecollector.ingest.casefolder import load_corpus
from fakecollector.ingest.normalize import display_text


def _odd(parent: Path, raw: bytes) -> Path:
    path = Path(os.fsdecode(os.fsencode(parent) + b"/" + raw))
    try:
        path.mkdir(parents=True) if not raw.endswith(b".png") else path.write_bytes(b"x" * 2048)
    except OSError:
        pytest.skip("filesystem rejects non-UTF-8 names")
    return path


def test_display_text_is_utf8_safe() -> None:
    raw = os.fsdecode(b"napa\xff\xe5.png")
    shown = display_text(raw)
    shown.encode("utf-8")  # must not raise
    assert shown == "napa\\xff\\xe5.png"
    assert display_text("zwykła_nazwa.png") == "zwykła_nazwa.png"


def test_ids_meta_and_locators_are_encodable(tmp_path: Path) -> None:
    case_dir = _odd(tmp_path, b"sprawa_\xff")
    files = case_dir / "Strona_files"
    files.mkdir()
    (case_dir / "Strona.html").write_text("<html></html>")
    _odd(files, b"napa\xff\xe5.png")
    cases, arts = load_corpus(tmp_path, "T")
    texts = [cases[0].id] + [v for a in arts for v in a.meta.values()] + [a.case_id for a in arts]
    for a in arts:
        if AssetExtractor().supports(a):
            texts += [f.locator for f in AssetExtractor().extract(a, [])]
    for text in texts:
        text.encode("utf-8")
    assert all(a.path.exists() for a in arts)  # real paths still open the files
