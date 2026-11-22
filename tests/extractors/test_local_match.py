"""Tests for local-feature pair verification (synthetic images only; needs OpenCV)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageOps

from tests.extractors.test_regions import _feed, _textured

pytest.importorskip("cv2")

from fakecollector.core.schemas import Feature
from fakecollector.extractors.local_match import (
    MIN_INLIERS,
    describe,
    local_match,
    match_features,
    siglip_candidates,
    verify_siglip_candidates,
)


def _jpeg(im: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


@pytest.mark.parametrize("detector", ["sift", "orb"])
def test_pasted_creative_is_found_in_screenshot(detector: str) -> None:
    creative = _textured(11, (600, 400))
    shot = _feed(creative.resize((420, 280)), at=(30, 240))
    shot = _jpeg(shot.resize((shot.width * 3 // 4, shot.height * 3 // 4)), 60)
    m = local_match(creative, shot, detector=detector)  # type: ignore[arg-type]
    assert m.homography_ok
    assert m.inliers >= MIN_INLIERS


@pytest.mark.parametrize("detector", ["sift", "orb"])
def test_unrelated_images_give_few_inliers(detector: str) -> None:
    m = local_match(_textured(12), _textured(13), detector=detector)  # type: ignore[arg-type]
    assert not m.homography_ok
    assert m.inliers < MIN_INLIERS


def test_crop_of_creative_matches() -> None:
    creative = _textured(14, (640, 480))
    crop = creative.crop((60, 40, 560, 420))
    assert local_match(crop, creative).homography_ok


def test_mirror_is_not_a_homography_match() -> None:
    creative = _textured(15)
    assert not local_match(creative, ImageOps.mirror(creative)).homography_ok


def test_described_features_are_reusable_and_symmetric() -> None:
    a, b = _textured(16), _jpeg(_textured(16), 50)
    fa, fb = describe(a), describe(b)
    assert match_features(fa, fb).homography_ok
    assert match_features(fb, fa).homography_ok


def test_shared_thin_strip_alone_is_not_verified() -> None:
    strip = _textured(18, (600, 300)).crop((0, 0, 600, 40))
    a, b = _textured(19, (600, 600)), _textured(20, (600, 600))
    a.paste(strip, (0, 0))
    b.paste(strip, (0, 0))
    m = local_match(a, b)
    assert m.inliers >= MIN_INLIERS  # the strip itself matches ...
    assert not m.homography_ok  # ... but covers too little of either image


def test_blank_image_does_not_crash() -> None:
    blank = Image.new("RGB", (300, 300), (255, 255, 255))
    assert local_match(blank, _textured(17)) == (0, False)


def _siglip(case: str, artifact: str, vector: list[float]) -> Feature:
    return Feature(case_id=case, artifact_id=artifact, name="img.siglip", value="", vector=vector)


def test_siglip_candidates_keep_best_pair_above_gate() -> None:
    new = [_siglip("U:1", "n", [1.0, 0.0]), _siglip("U:1", "n", [0.6, 0.8])]
    base = [
        _siglip("B:1", "b1", [0.95, 0.312]),  # cos 0.95 with the whole view
        _siglip("B:2", "b2", [0.0, 1.0]),  # cos 0.80 with the crop view, below the gate
    ]
    rows = siglip_candidates(new, base)
    assert [(a, b, c) for a, b, c, _ in rows] == [("n", "b1", "B:1")]
    assert rows[0][3] == pytest.approx(0.95, abs=0.01)


def test_verify_siglip_candidates_separates_recrop_from_lookalike(tmp_path: Path) -> None:
    """A re-cropped, recompressed creative verifies; a SigLIP look-alike does not."""
    creative = _textured(41, (640, 480))
    probe = _jpeg(creative.crop((40, 30, 600, 450)).resize((392, 294)), 50)
    lookalike = _textured(42, (640, 480))
    paths = {}
    for name, im in {"probe": probe, "orig": creative, "other": lookalike}.items():
        paths[name] = tmp_path / f"{name}.png"
        im.save(paths[name])
    new = [_siglip("U:1", "probe", [1.0, 0.0])]
    base = [_siglip("B:1", "orig", [0.97, 0.243]), _siglip("B:2", "other", [0.9, 0.436])]
    pairs = verify_siglip_candidates(new, base, paths)
    by_case = {p.base_case: p for p in pairs}
    assert by_case["B:1"].homography_ok and by_case["B:1"].inliers >= MIN_INLIERS
    assert not by_case["B:2"].homography_ok


def test_verify_skips_missing_files() -> None:
    new = [_siglip("U:1", "probe", [1.0, 0.0])]
    base = [_siglip("B:1", "orig", [1.0, 0.0])]
    assert verify_siglip_candidates(new, base, {}) == []
