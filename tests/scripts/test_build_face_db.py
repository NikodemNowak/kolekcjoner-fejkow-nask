"""Tests for the reference-photo consistency check in `scripts/build_face_db.py`."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np

from fakecollector.extractors.face import Face

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_face_db.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_face_db", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _face(v: np.ndarray, size: int = 100) -> Face:
    return Face(bbox=(0, 0, size, size), det_score=0.9, embedding=v / np.linalg.norm(v))


def test_wrong_person_photo_is_dropped() -> None:
    rng = np.random.default_rng(0)
    person, other = rng.normal(size=512), rng.normal(size=512)
    photos = [(f"p{i}", [_face(person + 0.3 * rng.normal(size=512))]) for i in range(4)]
    photos.append(("wrong", [_face(other)]))
    embs, shas, notes = _module()._person_embeddings(photos)
    assert shas == ["p0", "p1", "p2", "p3"]
    assert len(embs) == 4
    assert notes and "dropped" in notes[0]


def test_group_photo_picks_the_matching_face() -> None:
    rng = np.random.default_rng(1)
    person, other = rng.normal(size=512), rng.normal(size=512)
    photos = [(f"p{i}", [_face(person + 0.3 * rng.normal(size=512))]) for i in range(3)]
    target = person + 0.3 * rng.normal(size=512)
    photos.append(("group", [_face(other, size=300), _face(target, size=80)]))
    embs, shas, _ = _module()._person_embeddings(photos)
    assert "group" in shas
    assert float(embs[shas.index("group")] @ (target / np.linalg.norm(target))) > 0.99


def test_outlier_among_three_photos_is_dropped() -> None:
    rng = np.random.default_rng(2)
    person, other = rng.normal(size=512), rng.normal(size=512)
    photos = [(f"p{i}", [_face(person + 0.3 * rng.normal(size=512))]) for i in range(2)]
    photos.append(("wrong", [_face(other)]))
    _, shas, notes = _module()._person_embeddings(photos)
    assert shas == ["p0", "p1"]
    assert notes and "wrong" in notes[0]
