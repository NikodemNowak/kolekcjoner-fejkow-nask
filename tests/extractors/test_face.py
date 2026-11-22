"""Tests for the public-figure face extractor (Task 6)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fakecollector.core.schemas import Artifact
from fakecollector.extractors.face import (
    Face,
    FaceConfig,
    FaceDB,
    FaceExtractor,
    decode_image,
)

REFS = Path("data/faces/refs")
DB_PATH = Path("data/faces/db.npz")


def _unit(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


class FakeEmbedder:
    """Returns pre-set faces for every image."""

    def __init__(self, faces: list[Face]) -> None:
        self.faces = faces
        self.calls = 0

    def embed(self, images: list[np.ndarray]) -> list[list[Face]]:
        self.calls += len(images)
        return [list(self.faces) for _ in images]


def _db(rng: np.random.Generator) -> tuple[FaceDB, np.ndarray]:
    a, b = _unit(rng.normal(size=512)), _unit(rng.normal(size=512))
    db = FaceDB(
        slugs=["person-a", "person-b"],
        centroids=np.stack([a, b]),
        embeddings=np.stack([a, b]),
        owners=np.array([0, 1]),
    )
    return db, a


def _artifact(tmp_path: Path, data: bytes, name: str = "shot.png") -> Artifact:
    path = tmp_path / name
    path.write_bytes(data)
    return Artifact(
        id="0" * 16, case_id="T:1", kind="image", role="screenshot", path=path, size=len(data)
    )


def _png(h: int = 300, w: int = 300) -> bytes:
    import cv2

    img = np.full((h, w, 3), 200, np.uint8)
    cv2.rectangle(img, (40, 40), (200, 120), (30, 60, 90), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def test_matched_face_emits_public_figure(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    db, a = _db(rng)
    face = Face(bbox=(10, 20, 80, 90), det_score=0.9, embedding=a)
    ext = FaceExtractor(FaceConfig(), embedder=FakeEmbedder([face]), db=db)
    feats = ext.extract(_artifact(tmp_path, _png()), [])
    assert [(f.name, f.value, f.locator) for f in feats] == [
        ("person.public_figure", "person-a", "bbox=10,20,80,90")
    ]
    assert feats[0].confidence == pytest.approx(1.0, abs=1e-4)
    assert feats[0].vector is None  # embeddings never leave the extractor


def test_unmatched_tiny_and_low_score_faces_are_dropped(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    db, a = _db(rng)
    faces = [
        Face(bbox=(0, 0, 20, 20), det_score=0.95, embedding=a),  # tiny
        Face(bbox=(0, 0, 90, 90), det_score=0.5, embedding=a),  # low detection score
        Face(bbox=(0, 0, 90, 90), det_score=0.9, embedding=_unit(rng.normal(size=512))),
    ]
    ext = FaceExtractor(FaceConfig(), embedder=FakeEmbedder(faces), db=db)
    assert ext.extract(_artifact(tmp_path, _png()), []) == []


def test_small_face_needs_the_stricter_score(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    db, a = _db(rng)
    noise = rng.normal(size=512)
    other = _unit(noise - (noise @ a) * a)
    weak = _unit(0.45 * a + np.sqrt(1 - 0.45**2) * other)  # cosine 0.45 to person-a
    assert float(weak @ a) == pytest.approx(0.45, abs=1e-3)
    sure = Face(bbox=(0, 0, 30, 30), det_score=0.9, embedding=a)
    unsure_small = Face(bbox=(100, 0, 30, 30), det_score=0.9, embedding=weak)
    cfg = FaceConfig()
    ext = FaceExtractor(cfg, embedder=FakeEmbedder([sure]), db=db)
    assert [f.value for f in ext.extract(_artifact(tmp_path, _png()), [])] == ["person-a"]
    ext = FaceExtractor(cfg, embedder=FakeEmbedder([unsure_small]), db=db)
    assert ext.extract(_artifact(tmp_path, _png()), []) == []
    big_weak = Face(bbox=(0, 0, 90, 90), det_score=0.9, embedding=weak)
    ext = FaceExtractor(cfg, embedder=FakeEmbedder([big_weak]), db=db)
    assert [f.value for f in ext.extract(_artifact(tmp_path, _png()), [])] == ["person-a"]


def test_small_image_and_corrupt_bytes_yield_nothing(tmp_path: Path) -> None:
    rng = np.random.default_rng(2)
    db, a = _db(rng)
    fake = FakeEmbedder([Face(bbox=(0, 0, 90, 90), det_score=0.9, embedding=a)])
    ext = FaceExtractor(FaceConfig(), embedder=fake, db=db)
    assert ext.extract(_artifact(tmp_path, _png(100, 100), "small.png"), []) == []
    assert ext.extract(_artifact(tmp_path, b"\x89PNG\r\n\x1a\ngarbage", "bad.png"), []) == []
    assert ext.extract(_artifact(tmp_path, b"", "empty.jpg"), []) == []
    assert fake.calls == 0
    assert decode_image(b"not an image") is None


def test_missing_db_disables_signal(tmp_path: Path) -> None:
    cfg = FaceConfig(db_path=tmp_path / "missing.npz")
    ext = FaceExtractor(cfg, embedder=FakeEmbedder([]))
    assert ext.extract(_artifact(tmp_path, _png()), []) == []


def test_db_roundtrip(tmp_path: Path) -> None:
    db, a = _db(np.random.default_rng(3))
    db.ref_sha256 = ["x", "y"]
    db.save(tmp_path / "db.npz")
    back = FaceDB.load(tmp_path / "db.npz")
    assert back.slugs == db.slugs and back.ref_sha256 == ["x", "y"]
    assert back.match(a)[0] == "person-a"


@pytest.mark.gpu
def test_no_face_image_real_model(tmp_path: Path) -> None:
    db, _ = _db(np.random.default_rng(4))
    ext = FaceExtractor(FaceConfig(), db=db)
    assert ext.extract(_artifact(tmp_path, _png(400, 600)), []) == []


@pytest.mark.gpu
def test_tiny_face_ignored_real_model(tmp_path: Path) -> None:
    import cv2

    photo = _reference_photos()[0]
    img = decode_image(photo.read_bytes())
    assert img is not None
    small = cv2.resize(img, (60, int(60 * img.shape[0] / img.shape[1])))
    canvas = np.full((400, 400, 3), 255, np.uint8)
    canvas[10 : 10 + small.shape[0], 10 : 10 + small.shape[1]] = small[:390]
    ok, buf = cv2.imencode(".png", canvas)
    assert ok
    ext = FaceExtractor(FaceConfig(db_path=DB_PATH))
    assert ext.extract(_artifact(tmp_path, buf.tobytes()), []) == []


def _reference_photos() -> list[Path]:
    if not DB_PATH.is_file() or not REFS.is_dir():
        pytest.skip("reference DB not built (scripts/fetch_face_refs.py, build_face_db.py)")
    photos = sorted((REFS / "tomasz-sekielski").glob("*.jpg"))
    if len(photos) < 2:
        pytest.skip("need two reference photos of one person")
    return photos


@pytest.mark.gpu
def test_two_photos_same_person_same_slug(tmp_path: Path) -> None:
    photos = _reference_photos()
    ext = FaceExtractor(FaceConfig(db_path=DB_PATH))
    embs = []
    for photo in photos[:2]:
        img = decode_image(photo.read_bytes())
        assert img is not None
        faces = [f for f in ext.embedder.embed([img])[0] if f.det_score >= 0.6]
        embs.append(max(faces, key=lambda f: f.size).embedding)
    assert float(embs[0] @ embs[1]) >= 0.45
    feats = [ext.extract(_artifact(tmp_path, p.read_bytes(), p.name), []) for p in photos[:2]]
    assert [f[0].value for f in feats] == ["tomasz-sekielski", "tomasz-sekielski"]
    assert all(f[0].confidence >= 0.45 for f in feats)


def test_portrait_reports_face_share_without_identity(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    db, _ = _db(rng)
    stranger = Face(bbox=(30, 30, 200, 225), det_score=0.9, embedding=_unit(rng.normal(size=512)))
    ext = FaceExtractor(FaceConfig(), embedder=FakeEmbedder([stranger]), db=db)
    feats = ext.extract(_artifact(tmp_path, _png()), [])
    assert [(f.name, f.value, f.vector) for f in feats] == [("img.face_share", "0.50", None)]


class CropEmbedder:
    """No face at screenshot scale; a matched face once the region is upscaled."""

    def __init__(self, face: Face) -> None:
        self.face = face
        self.shapes: list[tuple[int, ...]] = []

    def embed(self, images: list[np.ndarray]) -> list[list[Face]]:
        self.shapes += [img.shape for img in images]
        return [[] if len(self.shapes) == 1 else [self.face] for _ in images]


def _feed_png() -> bytes:
    import cv2

    img = np.full((600, 400, 3), 255, np.uint8)  # white feed frame
    noise = np.random.default_rng(5).integers(0, 255, (300, 360, 3), dtype=np.uint8)
    img[150:450, 20:380] = noise  # the creative picture
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def test_small_face_in_creative_region_matched_after_upscale(tmp_path: Path) -> None:
    rng = np.random.default_rng(4)
    db, a = _db(rng)
    fake = CropEmbedder(Face(bbox=(100, 80, 60, 70), det_score=0.9, embedding=a))
    ext = FaceExtractor(FaceConfig(), embedder=fake, db=db)
    feats = ext.extract(_artifact(tmp_path, _feed_png()), [])
    assert [(f.name, f.value) for f in feats] == [("person.public_figure", "person-a")]
    region, _, box = feats[0].locator.partition(" x2 bbox=")
    rx, ry, _rw, _rh = (int(v) for v in region.removeprefix("crop=").split(","))
    # The box is in whole-image pixels: region offset + crop box / 2.
    assert box == f"{rx + 50},{ry + 40},30,35"
    _whole, crop = fake.shapes
    assert crop[0] > 1.5 * 300 and crop[1] > 1.5 * 360  # region enlarged about x2
