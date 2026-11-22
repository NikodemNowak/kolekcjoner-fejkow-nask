"""Tests for SigLIP2 embeddings (need model weights; marked gpu)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fakecollector.core.schemas import Artifact
from tests.extractors.test_image_hash import _scene

pytestmark = pytest.mark.gpu


@pytest.fixture(scope="module")
def embed():  # type: ignore[no-untyped-def]
    pytest.importorskip("transformers")
    from fakecollector.extractors import image_embed

    yield image_embed
    image_embed.release()


def test_vector_is_unit_norm_768(embed, tmp_path: Path) -> None:
    path = tmp_path / "shot.png"
    _scene(1, (640, 960)).save(path)
    art = Artifact(
        id="1" * 16,
        case_id="T:1",
        kind="image",
        role="screenshot",
        path=path,
        size=path.stat().st_size,
    )
    feats = embed.SiglipExtractor().extract_batch([art], [[]])[0]
    vec = np.array(next(f.vector for f in feats if f.name == "img.siglip"))
    assert vec.shape == (768,)
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-3


def test_framed_creative_gets_a_region_vector(embed, tmp_path: Path) -> None:
    from tests.extractors.test_regions import _feed, _textured

    creative = _textured(30)
    path = tmp_path / "feed.png"
    _feed(creative).save(path)
    art = Artifact(
        id="2" * 16,
        case_id="T:1",
        kind="image",
        role="screenshot",
        path=path,
        size=path.stat().st_size,
    )
    feats = [f for f in embed.SiglipExtractor().extract(art, []) if f.name == "img.siglip"]
    assert feats[0].locator == ""
    crops = [f for f in feats if f.locator.startswith("crop=")]
    assert crops
    ref = embed.embed_images([creative])[0]
    best_crop = max(float(ref @ np.array(f.vector)) for f in crops)
    assert best_crop > float(ref @ np.array(feats[0].vector))
    assert best_crop >= 0.95


def test_resized_image_is_near_identical(embed) -> None:
    im = _scene(2, (800, 600))
    vecs = embed.embed_images([im, im.resize((400, 300)), _scene(9, (800, 600))])
    assert float(vecs[0] @ vecs[1]) >= 0.95
    assert float(vecs[0] @ vecs[2]) < float(vecs[0] @ vecs[1])


def test_tiny_and_corrupt_inputs_skipped(embed, tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.png"
    _scene(3, (100, 100)).save(tiny)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"\xff\xd8\xff garbage")
    arts = [
        Artifact(
            id=str(i) * 16,
            case_id="T:1",
            kind="image",
            role="landing_asset",
            path=p,
            size=p.stat().st_size,
        )
        for i, p in enumerate([tiny, bad])
    ]
    assert embed.SiglipExtractor().extract_batch(arts, [[], []]) == [[], []]


def test_text_tower_shape(embed) -> None:
    vecs = embed.embed_texts(["the gazeta.pl logo", "a photo of a cat"])
    assert vecs.shape == (2, 768)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-3)
