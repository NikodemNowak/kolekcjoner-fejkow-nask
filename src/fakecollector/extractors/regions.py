"""Creative-region extraction: find the picture(s) inside a screenshot.

A new variant of a known ad often arrives as a phone or feed screenshot: the creative sits
in a frame of UI chrome (status bar, "Sponsorowane" header, post text, link bar, buttons).
Whole-image hashes and embeddings then compare mostly chrome. This module finds the dense
picture blocks inside such a frame so the vision extractors can describe them on their own.

Method (numpy + scipy only, so the base install has it): estimate the frame background from
the border, mark pixels that differ from it, keep areas where such pixels are dense (text
lines are sparse ink on the background and drop out), close small gaps, fill holes, and keep
large, textured, mostly-filled connected components. Pure function, no I/O.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
from PIL import Image
from scipy import ndimage

WORK_SIDE = 384
"""Long side of the analysis raster; plenty for blocks that are >= 6 % of the screen."""

BG_TOLERANCE = 28
"""Max per-channel distance (0..255) for a pixel to count as frame background."""

MIN_BORDER_BG = 0.45
"""Share of border pixels that must match the background; else the image is full-bleed."""

DENSITY = 0.6
"""Min share of foreground pixels in a window for picture content (text stays well below)."""

MIN_AREA = 0.06
MAX_AREA = 0.85
"""Region area bounds as a share of the image; bigger regions add nothing over the whole."""

FRAME_BORDER_BG = 0.8
"""Border share in the background colour above which a block is a plain panel."""

FRAME_SHARE = 0.6
"""A block whose inner blocks cover less than this share of it is a frame, not a picture."""

MIN_FILL = 0.55
MIN_STD = 18.0
MIN_SIDE_PX = 64
MAX_REGIONS = 3


class Region(NamedTuple):
    """A crop box in original pixel coordinates."""

    x: int
    y: int
    w: int
    h: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        """PIL crop box `(left, top, right, bottom)`."""
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    @property
    def locator(self) -> str:
        """Feature locator string, `crop=x,y,w,h`."""
        return f"crop={self.x},{self.y},{self.w},{self.h}"


def _background(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    """Most common (quantised) border colour and the share of border pixels that match it."""
    h, w, _ = rgb.shape
    ring = max(2, min(h, w) // 50)
    border = np.concatenate(
        [
            rgb[:ring].reshape(-1, 3),
            rgb[-ring:].reshape(-1, 3),
            rgb[:, :ring].reshape(-1, 3),
            rgb[:, -ring:].reshape(-1, 3),
        ]
    ).astype(np.int16)
    q = border // 16
    keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    mode = vals[int(np.argmax(counts))]
    members = border[keys == mode]
    bg = np.median(members, axis=0)
    share = float(np.mean(np.abs(border - bg).max(axis=1) <= BG_TOLERANCE))
    return bg, share


def _is_frame(im: Image.Image) -> bool:
    """True when the border of `im` is one uniform colour (a panel, not a picture)."""
    small = im.convert("RGB")
    small.thumbnail((WORK_SIDE, WORK_SIDE), Image.Resampling.BILINEAR)
    return _background(np.asarray(small, dtype=np.int16))[1] >= FRAME_BORDER_BG


def _blocks(im: Image.Image) -> list[Region]:
    """Dense, textured, mostly-filled blocks on a uniform frame (no upper size bound)."""
    if im.width < MIN_SIDE_PX or im.height < MIN_SIDE_PX:
        return []
    scale = WORK_SIDE / max(im.size)
    small = im.convert("RGB")
    if scale < 1:
        small = small.resize(
            (max(1, round(im.width * scale)), max(1, round(im.height * scale))),
            Image.Resampling.BILINEAR,
        )
    else:
        scale = 1.0
    rgb = np.asarray(small, dtype=np.int16)
    bg, share = _background(rgb)
    if share < MIN_BORDER_BG:
        return []
    fg = np.abs(rgb - bg).max(axis=2) > BG_TOLERANCE
    short = min(fg.shape)
    win = max(5, short // 25)
    dense = ndimage.uniform_filter(fg.astype(np.float32), size=win) >= DENSITY
    dense = ndimage.binary_closing(dense, structure=np.ones((3, 3)), iterations=max(1, win // 3))
    dense = ndimage.binary_fill_holes(dense)
    labels, n = ndimage.label(dense)
    if n == 0:
        return []
    gray = rgb.mean(axis=2)
    total = fg.size
    found: list[Region] = []
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        ys, xs = sl
        if (ys.stop - ys.start) * (xs.stop - xs.start) < MIN_AREA * total:
            continue
        if float(np.mean(labels[sl] == idx)) < MIN_FILL:
            continue
        if float(gray[sl].std()) < MIN_STD:  # flat colour bars (app header, buttons)
            continue
        x0, y0 = int(xs.start / scale), int(ys.start / scale)
        x1 = min(im.width, int(np.ceil(xs.stop / scale)))
        y1 = min(im.height, int(np.ceil(ys.stop / scale)))
        if min(x1 - x0, y1 - y0) >= MIN_SIDE_PX:
            found.append(Region(x0, y0, x1 - x0, y1 - y0))
    return found


def content_regions(im: Image.Image, max_regions: int = MAX_REGIONS) -> list[Region]:
    """Dense picture blocks inside a framed screenshot, largest first.

    A block that is itself a frame (an "ad details" dialog or a post card on a dimmed page:
    its own blocks cover less than `FRAME_SHARE` of it) is replaced by the blocks inside it,
    one level deep, so the result is the creative rather than the dialog chrome around it.
    A plain panel with nothing but text on it (a browser bar, a text card) is dropped.
    Returns `[]` for full-bleed images (no uniform frame), for frames that hold only text,
    and when the only block covers almost the whole image (the whole-image features already
    describe it).
    """
    total = im.width * im.height
    out: list[Region] = []
    for block in _blocks(im):
        crop = im.crop(block.box)
        inner = [Region(block.x + r.x, block.y + r.y, r.w, r.h) for r in _blocks(crop)]
        if inner and sum(r.w * r.h for r in inner) < FRAME_SHARE * block.w * block.h:
            out += inner
        elif inner or not _is_frame(crop):
            out.append(block)
        # else: a plain panel with only text on it (browser bar, text card): chrome, dropped
    out = [r for r in out if MIN_AREA * total <= r.w * r.h <= MAX_AREA * total]
    out.sort(key=lambda r: -r.w * r.h)
    return out[:max_regions]


def crops(im: Image.Image, max_regions: int = MAX_REGIONS) -> list[tuple[str, Image.Image]]:
    """`(locator, crop)` pairs for every content region of `im`."""
    return [(r.locator, im.crop(r.box)) for r in content_regions(im, max_regions)]
