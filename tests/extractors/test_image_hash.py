"""Tests for perceptual image hashes (synthetic images only)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from fakecollector.core.schemas import Artifact
from fakecollector.extractors.image_hash import ImageHashExtractor, hamming, load_image


def _scene(seed: int, size: tuple[int, int] = (480, 320)) -> Image.Image:
    """A deterministic 'ad-like' picture: gradient background plus random shapes and bars."""
    rng = np.random.default_rng(seed)
    w, h = size
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    base = (rng.random(3) * x + rng.random(3) * y) * 200
    im = Image.fromarray(np.broadcast_to(base, (h, w, 3)).astype(np.uint8))
    draw = ImageDraw.Draw(im)
    for _ in range(12):
        x0, y0 = int(rng.integers(0, w - 40)), int(rng.integers(0, h - 40))
        x1, y1 = x0 + int(rng.integers(30, w // 2)), y0 + int(rng.integers(30, h // 2))
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        if rng.random() < 0.5:
            draw.ellipse((x0, y0, x1, y1), fill=color)
        else:
            draw.rectangle((x0, y0, x1, y1), fill=color)
    return im


def _artifact(path: Path, role: str = "landing_asset") -> Artifact:
    return Artifact(
        id="0" * 16,
        case_id="T:1",
        kind="image",
        role=role,
        path=path,
        size=path.stat().st_size,
    )


def _phash(path: Path) -> str:
    feats = ImageHashExtractor().extract(_artifact(path, "ad_creative"), [])
    return next(f.value for f in feats if f.name == "img.phash")


def test_jpeg_recompression_keeps_phash(tmp_path: Path) -> None:
    im = _scene(1)
    im.save(tmp_path / "a.png")
    im.save(tmp_path / "b.jpg", quality=60)
    assert hamming(_phash(tmp_path / "a.png"), _phash(tmp_path / "b.jpg")) <= 8


def test_different_images_are_far(tmp_path: Path) -> None:
    _scene(1).save(tmp_path / "a.png")
    _scene(2).save(tmp_path / "b.png")
    assert hamming(_phash(tmp_path / "a.png"), _phash(tmp_path / "b.png")) > 20


def test_pdq_emitted_with_quality(tmp_path: Path) -> None:
    pytest.importorskip("pdqhash")
    _scene(3).save(tmp_path / "a.png")
    feats = ImageHashExtractor().extract(_artifact(tmp_path / "a.png", "ad_creative"), [])
    pdq = [f for f in feats if f.name == "img.pdq" and f.locator == ""]
    assert len(pdq) == 1 and len(pdq[0].value) == 64 and 0.0 < pdq[0].confidence <= 1.0


def test_corrupt_file_gives_no_features(tmp_path: Path) -> None:
    path = tmp_path / "broken.jpg"
    buf = io.BytesIO()
    _scene(4).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue()[:200])  # truncated JPEG
    assert ImageHashExtractor().extract(_artifact(path), []) == []
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"\x89PNG not really an image")
    assert ImageHashExtractor().extract(_artifact(junk), []) == []


def test_tiny_icon_skipped(tmp_path: Path) -> None:
    _scene(5, (64, 64)).save(tmp_path / "icon.png")
    assert ImageHashExtractor().extract(_artifact(tmp_path / "icon.png"), []) == []


def test_svg_not_supported(tmp_path: Path) -> None:
    path = tmp_path / "logo.svg"
    path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    ext = ImageHashExtractor()
    assert not ext.supports(_artifact(path))
    assert ext.extract(_artifact(path), []) == []


def test_rgba_palette_and_animated_inputs(tmp_path: Path) -> None:
    rgba = _scene(6).convert("RGBA")
    rgba.putalpha(128)
    rgba.save(tmp_path / "rgba.png")
    _scene(6).convert("P", palette=Image.Palette.ADAPTIVE).save(tmp_path / "pal.gif")
    frames = [_scene(6), _scene(7)]
    frames[0].save(tmp_path / "anim.webp", save_all=True, append_images=frames[1:])
    frames[0].save(tmp_path / "anim.gif", save_all=True, append_images=frames[1:])
    ref = _phash(tmp_path / "rgba.png")
    for name in ("pal.gif", "anim.webp", "anim.gif"):
        im = load_image(tmp_path / name)
        assert im is not None and im.mode == "RGB"
        assert len(_phash(tmp_path / name)) == 16
    # Palette quantisation and the first animation frame stay close to the source picture.
    assert hamming(_phash(tmp_path / "pal.gif"), _phash(tmp_path / "anim.webp")) <= 8
    assert len(ref) == 16


def test_exif_rotation_applied(tmp_path: Path) -> None:
    im = _scene(8)
    upright = tmp_path / "upright.jpg"
    im.save(upright, quality=95)
    rotated = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 CW to display": stored pixels are turned the other way
    im.transpose(Image.Transpose.ROTATE_90).save(rotated, quality=95, exif=exif)
    loaded = load_image(rotated)
    assert loaded is not None and loaded.size == im.size
    assert hamming(_phash(upright), _phash(rotated)) <= 8


def test_hamming_length_mismatch() -> None:
    assert hamming("ff00", "0f00") == 4
    with pytest.raises(ValueError):
        hamming("ff", "ffff")


def _ui_mockup() -> Image.Image:
    """A flat render: white app screen with cards and text, like a fake banking app."""
    im = Image.new("RGB", (400, 800), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    draw.rectangle((0, 0, 400, 90), fill=(220, 30, 40))
    draw.rounded_rectangle((20, 120, 380, 260), 12, fill=(240, 240, 240))
    for i in range(12):
        draw.text((30, 300 + 35 * i), f"Transakcja #{i:04d}   +{i * 37},00 PLN", fill=(20, 20, 20))
    return im


def _photo(seed: int) -> Image.Image:
    """`_scene` with sensor-like noise, so it has texture everywhere like a photo."""
    rng = np.random.default_rng(seed)
    base = np.asarray(_scene(seed), dtype=np.int16)
    noisy = np.clip(base + rng.integers(-20, 20, (*base.shape[:2], 1)), 0, 255)
    return Image.fromarray(noisy.astype(np.uint8))


def test_flat_landing_graphic_is_not_hashed(tmp_path: Path) -> None:
    _ui_mockup().save(tmp_path / "mock.png")
    assert ImageHashExtractor().extract(_artifact(tmp_path / "mock.png"), []) == []


def test_flat_screenshot_is_still_hashed(tmp_path: Path) -> None:
    _ui_mockup().save(tmp_path / "shot.png")
    feats = ImageHashExtractor().extract(_artifact(tmp_path / "shot.png", "screenshot"), [])
    assert any(f.name == "img.phash" for f in feats)


def test_photo_like_landing_asset_is_hashed(tmp_path: Path) -> None:
    _photo(3).save(tmp_path / "photo.png")
    assert ImageHashExtractor().extract(_artifact(tmp_path / "photo.png"), [])


def _degrade(im: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    """Re-submission: crop (left, top, right, bottom shares), resize 0.7x, JPEG q50."""
    w, h = im.size
    left, top, right, bottom = box
    im = im.crop((round(w * left), round(h * top), w - round(w * right), h - round(h * bottom)))
    im = im.resize((int(im.width * 0.7), int(im.height * 0.7)), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=50)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def _best_pdq(a: Path, b: Path, role: str = "screenshot", whole_only: bool = False) -> float:
    def pdqs(path: Path) -> list[str]:
        feats = ImageHashExtractor().extract(_artifact(path, role), [])
        return [
            f.value for f in feats if f.name == "img.pdq" and (f.locator == "" or not whole_only)
        ]

    return max(1 - hamming(x, y) / 256 for x in pdqs(a) for y in pdqs(b))


@pytest.mark.parametrize(
    "box",
    [(0.06, 0.06, 0.06, 0.06), (0.10, 0.10, 0.10, 0.10), (0.14, 0.14, 0.14, 0.14), (0, 0.08, 0, 0)],
)
def test_recropped_screenshot_still_matches_pdq(tmp_path: Path, box: tuple[float, ...]) -> None:
    """Audit 03: a 6 % crop + resize + JPEG q50 drops whole-image PDQ to 0.57-0.69 (< 0.85)."""
    pytest.importorskip("pdqhash")
    shot = _photo(21).resize((720, 1280))
    shot.save(tmp_path / "orig.png")
    _degrade(shot, box).save(tmp_path / "probe.jpg")  # type: ignore[arg-type]
    assert _best_pdq(tmp_path / "orig.png", tmp_path / "probe.jpg", whole_only=True) < 0.85
    assert _best_pdq(tmp_path / "orig.png", tmp_path / "probe.jpg") >= 0.85


def test_crop_views_do_not_link_unrelated_images(tmp_path: Path) -> None:
    pytest.importorskip("pdqhash")
    for seed in (31, 32):
        _photo(seed).resize((720, 1280)).save(tmp_path / f"{seed}.png")
    assert _best_pdq(tmp_path / "31.png", tmp_path / "32.png") < 0.85


def test_crop_views_only_for_screenshots_and_creatives(tmp_path: Path) -> None:
    _photo(5).save(tmp_path / "p.png")
    asset = ImageHashExtractor().extract(_artifact(tmp_path / "p.png"), [])
    shot = ImageHashExtractor().extract(_artifact(tmp_path / "p.png", "screenshot"), [])
    assert {f.locator for f in asset} == {""}
    crops = {f.locator for f in shot} - {""}
    assert len(crops) >= 9 and all(loc.startswith("crop=") for loc in crops)
    assert shot[0].locator == "" and shot[0].name == "img.phash"
