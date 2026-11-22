"""Tests for creative-region extraction (synthetic screenshots only)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from fakecollector.extractors.image_hash import ImageHashExtractor, hamming
from fakecollector.extractors.regions import Region, content_regions, crops
from tests.extractors.test_image_hash import _artifact, _scene


def _textured(seed: int, size: tuple[int, int] = (480, 320)) -> Image.Image:
    """`_scene` plus fine random texture, like a photo."""
    rng = np.random.default_rng(seed + 1000)
    base = np.asarray(_scene(seed, size), dtype=np.int16)
    noise = rng.integers(-25, 25, base.shape[:2])[..., None]
    return Image.fromarray(np.clip(base + noise, 0, 255).astype(np.uint8))


def _feed(
    creative: Image.Image, at: tuple[int, int] = (20, 260), dark: bool = False
) -> Image.Image:
    """A fake feed screenshot: plain background, text lines, avatar, creative, link bar."""
    bg = (36, 37, 38) if dark else (255, 255, 255)  # Facebook card colours
    ink = (228, 230, 235) if dark else (20, 20, 20)
    w = creative.width + 2 * at[0]
    canvas = Image.new("RGB", (w, at[1] + creative.height + 300), bg)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((20, 30, 80, 90), fill=(66, 103, 178))
    draw.text((95, 40), "Strona Testowa", fill=ink)
    draw.text((95, 62), "Sponsorowane", fill=(120, 120, 120))
    for i in range(5):
        draw.text((20, 120 + 22 * i), "Lorem ipsum dolor sit amet consectetur " * 2, fill=ink)
    canvas.paste(creative, at)
    y = at[1] + creative.height
    draw.rectangle((0, y, w, y + 70), fill=(240, 242, 245) if not dark else (58, 59, 60))
    draw.text((20, y + 15), "PRZYKLAD.PL", fill=(100, 100, 100))
    draw.text((20, y + 110), "Lubie to   Komentarz   Udostepnij", fill=ink)
    return canvas


def _iou(a: Region, b: Region) -> float:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    return inter / (a.w * a.h + b.w * b.h - inter)


def test_finds_creative_in_light_feed() -> None:
    shot = _feed(_textured(1))
    regions = content_regions(shot)
    assert regions, "no region found"
    assert _iou(regions[0], Region(20, 260, 480, 320)) > 0.9


def test_finds_creative_in_dark_feed() -> None:
    shot = _feed(_textured(2), dark=True)
    regions = content_regions(shot)
    assert regions
    assert _iou(regions[0], Region(20, 260, 480, 320)) > 0.9


def test_full_bleed_picture_has_no_regions() -> None:
    assert content_regions(_textured(3)) == []


def test_text_only_frame_has_no_regions() -> None:
    page = Image.new("RGB", (600, 900), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    for i in range(30):
        draw.text((20, 20 + 28 * i), "Tekst artykulu bez obrazka, linia " * 2, fill=(0, 0, 0))
    assert content_regions(page) == []


def test_flat_colour_bar_is_ignored() -> None:
    page = Image.new("RGB", (600, 900), (255, 255, 255))
    ImageDraw.Draw(page).rectangle((0, 300, 600, 500), fill=(24, 119, 242))
    assert content_regions(page) == []


def test_dialog_on_dimmed_page_yields_the_creative_not_the_dialog() -> None:
    page = Image.new("RGB", (720, 1500), (90, 90, 90))  # dimmed page behind a modal
    dialog = _feed(_textured(7, (600, 400)), at=(30, 260))
    page.paste(dialog, (0, 200))
    regions = content_regions(page)
    assert regions
    assert _iou(regions[0], Region(30, 460, 600, 400)) > 0.9


def test_crops_carry_locator_and_match_box() -> None:
    shot = _feed(_textured(4))
    out = crops(shot)
    assert out
    locator, crop = out[0]
    x, y, w, h = (int(v) for v in locator.removeprefix("crop=").split(","))
    assert crop.size == (w, h)
    assert shot.crop((x, y, x + w, y + h)).tobytes() == crop.tobytes()


def test_two_creatives_found_largest_first() -> None:
    canvas = Image.new("RGB", (700, 1300), (255, 255, 255))
    canvas.paste(_textured(5, (600, 400)), (50, 100))
    canvas.paste(_textured(6, (400, 300)), (150, 800))
    regions = content_regions(canvas)
    assert len(regions) == 2
    assert _iou(regions[0], Region(50, 100, 600, 400)) > 0.9
    assert _iou(regions[1], Region(150, 800, 400, 300)) > 0.9


def test_hash_extractor_adds_region_hashes_for_screenshots(tmp_path: Path) -> None:
    creative = _textured(21)
    creative.save(tmp_path / "creative.png")
    _feed(creative).save(tmp_path / "shot.png")
    ext = ImageHashExtractor()
    shot = ext.extract(_artifact(tmp_path / "shot.png", "screenshot"), [])
    whole = [f for f in shot if f.name == "img.phash" and f.locator == ""]
    region = [f for f in shot if f.name == "img.phash" and f.locator.startswith("crop=")]
    assert len(whole) == 1
    assert region
    ref = next(
        f.value
        for f in ext.extract(_artifact(tmp_path / "creative.png"), [])
        if f.name == "img.phash"
    )
    # The framed creative matches the bare one only through its region hash.
    assert hamming(region[0].value, ref) <= 8
    assert hamming(whole[0].value, ref) > 8


def test_hash_extractor_skips_regions_for_landing_assets(tmp_path: Path) -> None:
    _feed(_textured(22, (480, 800))).save(tmp_path / "asset.png")  # mostly photo, not flat
    feats = ImageHashExtractor().extract(_artifact(tmp_path / "asset.png"), [])
    assert feats
    assert all(f.locator == "" for f in feats)


def test_text_panel_on_dimmed_page_is_dropped() -> None:
    page = Image.new("RGB", (720, 1500), (90, 90, 90))
    bar = Image.new("RGB", (720, 180), (255, 255, 255))
    draw = ImageDraw.Draw(bar)
    draw.text((300, 60), "www.example.com", fill=(0, 0, 0))
    draw.ellipse((20, 50, 80, 110), outline=(0, 0, 0), width=4)
    page.paste(bar, (0, 0))
    assert content_regions(page) == []
