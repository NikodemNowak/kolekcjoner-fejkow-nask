"""Perceptual image hashes: `img.phash` (64-bit DCT hash) and `img.pdq` (256-bit PDQ).

Both hashes survive recompression, resizing and small edits, so they link re-uploaded ad
creatives and content images across cases when the bytes (and thus sha256) differ. For
screenshots and ad creatives the creative regions found by `extractors/regions.py` are hashed
too (`locator="crop=x,y,w,h"`), because a whole-screenshot hash mostly describes UI chrome and
fails when the same creative turns up in a different feed frame
(measured in `docs/robustness-vision.md`).

PDQ and pHash are not crop-invariant: a 2 % residual crop already drops PDQ similarity below
the 0.85 band (median 0.83 after resize + JPEG q50), and a re-submitted screenshot cropped 6 %
per side lands at 0.57-0.69. Screenshots and ad creatives therefore also get a small fixed set
of crop views (`crop_views`): symmetric centre crops every 3 % up to 15 % per side and top/bottom
trims of 5 % and 10 % (status bar / navigation bar removed). Because both sides of a pair carry
the views and fusion keeps the best pair, any symmetric re-crop of 0-15 % per side lands within
~1 % of some view pair.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors._media import is_image
from fakecollector.extractors.regions import Region, crops

logger = logging.getLogger(__name__)

MIN_SIDE = 120
"""Smaller images are icons, pixels and buttons: they collide across unrelated sites."""

MAX_PIXELS = 60_000_000
"""Decompression-bomb guard; a full-page phone screenshot is ~3 Mpx."""

HASH_SIDE = 512

IMAGE_ROLES = frozenset({"screenshot", "ad_creative", "landing_asset"})
GRAPHIC_FLAT_SHARE = 2 / 3
"""Landing assets that are mostly flat colour are graphics, not photos (see `is_graphic`)."""

REGION_ROLES = frozenset({"screenshot", "ad_creative"})
"""Roles whose images may frame a creative; landing assets are the pictures themselves."""
SKIP_SUFFIXES = frozenset({".svg", ".svgz", ".ico"})

CENTRE_CROPS = (0.03, 0.06, 0.09, 0.12, 0.15)
"""Symmetric crop per side; 3 % steps keep every 0-15 % re-crop within ~1.5 % of a view."""
EDGE_TRIMS = (0.05, 0.10)
"""Top-only and bottom-only trims: phone screenshots re-cropped without status or nav bar."""
MIN_VIEW_SIDE = 64

try:
    import pdqhash

    _HAS_PDQ = True
except ImportError:  # optional dependency; pHash alone is enough for the fast profile
    _HAS_PDQ = False


def load_image(path: Path) -> Image.Image | None:
    """Open an image as upright RGB, or return None (with a warning) if it cannot be read.

    Animated GIF/WebP use the first frame, EXIF rotation is applied and transparency is
    flattened onto white, because ad creatives and logos are usually shown on white pages.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as im:
                if im.width * im.height > MAX_PIXELS:
                    logger.warning("image too large, skipped: %s", path.name)
                    return None
                im.seek(0)
                im.load()
                return to_rgb(ImageOps.exif_transpose(im))
    except (
        OSError,
        UnidentifiedImageError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        logger.warning("cannot read image %s: %s", path.name, exc)
        return None


def to_rgb(im: Image.Image) -> Image.Image:
    """Convert any PIL mode to RGB, compositing transparency onto white."""
    if im.mode == "RGB":
        return im.copy()
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, rgba).convert("RGB")
    if im.mode in ("I;16", "I;16B", "I;16L", "I"):
        # 16-bit PNGs would saturate in a plain convert; rescale to 8 bit first.
        arr = np.asarray(im, dtype=np.float64)
        span = max(float(arr.max() - arr.min()), 1.0)
        return Image.fromarray(((arr - arr.min()) / span * 255).astype(np.uint8)).convert("RGB")
    return im.convert("RGB")


def big_enough(im: Image.Image, min_side: int = MIN_SIDE) -> bool:
    """Return True when both sides reach `min_side` pixels."""
    return im.width >= min_side and im.height >= min_side


def flat_share(im: Image.Image) -> float:
    """Share of pixels without local contrast (grey gradient < 2 at 256 px)."""
    g = np.asarray(im.convert("L").resize((256, 256), Image.Resampling.BILINEAR), dtype=np.float32)
    grad = np.abs(np.diff(g, axis=1))[:-1] + np.abs(np.diff(g, axis=0))[:, :-1]
    return float(np.mean(grad < 2))


def is_graphic(im: Image.Image) -> bool:
    """True for flat renders (UI mock-ups, banners, charts, badges) rather than photos.

    Such landing-page graphics are reusable stock of scam kits and shared across unrelated
    campaigns (measured: two byte-identical fake banking-app mock-ups linked two campaigns;
    flat share 0.72 and 0.77 versus <= 0.6 for every same-campaign shared asset). Exact reuse
    is still caught by `asset.sha256`; only the perceptual signals skip them.
    """
    return flat_share(im) > GRAPHIC_FLAT_SHARE


def usable(im: Image.Image | None, role: str) -> bool:
    """Gate for every image signal: readable, >= `MIN_SIDE`, and no flat landing graphic."""
    if im is None or not big_enough(im):
        return False
    return not (role == "landing_asset" and is_graphic(im))


def phash_hex(im: Image.Image) -> str:
    """64-bit perceptual hash as 16 hex characters."""
    return str(imagehash.phash(im))


def pdq_hex(im: Image.Image) -> tuple[str, float] | None:
    """256-bit PDQ hash as 64 hex characters plus PDQ quality in 0..1, or None without pdqhash."""
    if not _HAS_PDQ:
        return None
    bits, quality = pdqhash.compute(np.ascontiguousarray(np.asarray(im, dtype=np.uint8)))
    return np.packbits(bits.astype(np.uint8)).tobytes().hex(), float(quality) / 100.0


def hamming(a_hex: str, b_hex: str) -> int:
    """Hamming distance between two equal-length hex hashes."""
    if len(a_hex) != len(b_hex):
        raise ValueError("hashes differ in length")
    return (int(a_hex, 16) ^ int(b_hex, 16)).bit_count()


def hash_features(
    im: Image.Image, case_id: str, artifact_id: str, locator: str = ""
) -> list[Feature]:
    """Compute pHash (+ PDQ) features for an already loaded RGB image (also used for keyframes)."""
    # Both hashes look at <= 64 px internally; shrinking first makes phone screenshots ~10x
    # cheaper and keeps hashes identical for every caller, since all go through this function.
    if max(im.size) > HASH_SIDE:
        im = im.copy()
        im.thumbnail((HASH_SIDE, HASH_SIDE), Image.Resampling.BILINEAR)
    feats = [
        Feature(
            case_id=case_id,
            artifact_id=artifact_id,
            name="img.phash",
            value=phash_hex(im),
            locator=locator,
        )
    ]
    pdq = pdq_hex(im)
    if pdq is not None:
        feats.append(
            Feature(
                case_id=case_id,
                artifact_id=artifact_id,
                name="img.pdq",
                value=pdq[0],
                confidence=pdq[1],
                locator=locator,
            )
        )
    return feats


def crop_views(im: Image.Image) -> list[Region]:
    """Fixed crop boxes that make whole-image hashes survive 5-15 % re-crops (see module doc)."""
    w, h = im.size
    boxes: list[Region] = []
    for f in CENTRE_CROPS:
        dx, dy = round(w * f), round(h * f)
        boxes.append(Region(dx, dy, w - 2 * dx, h - 2 * dy))
    for f in EDGE_TRIMS:
        dy = round(h * f)
        boxes += [Region(0, dy, w, h - dy), Region(0, 0, w, h - dy)]
    return [b for b in boxes if min(b.w, b.h) >= MIN_VIEW_SIDE]


def hash_views(im: Image.Image, role: str) -> list[tuple[str, Image.Image]]:
    """Return `(locator, image)` pairs to hash, whole image first (`locator=""`).

    Screenshots and ad creatives add the creative regions and the fixed crop views
    (`locator="crop=x,y,w,h"` in original pixels for both). Landing assets: whole only.
    """
    views: list[tuple[str, Image.Image]] = [("", im)]
    if role in REGION_ROLES:
        views += crops(im)
        seen = {locator for locator, _ in views}
        views += [(b.locator, im.crop(b.box)) for b in crop_views(im) if b.locator not in seen]
    return views


class ImageHashExtractor(BaseExtractor):
    """pHash and PDQ for screenshots, ad creatives and landing-page photos ≥ 120 px.

    Screenshots and ad creatives also get one pHash/PDQ pair per creative region and per
    fixed crop view (`locator="crop=x,y,w,h"`, see `hash_views`); the whole-image pair always
    comes first with `locator=""`.
    """

    name = "image_hash"
    version = 3
    stage = 1
    requires = "base"

    def supports(self, artifact: Artifact) -> bool:
        """Images in a visual role; vector formats and icons are skipped."""
        return (
            is_image(artifact)
            and artifact.role in IMAGE_ROLES
            and artifact.path.suffix.lower() not in SKIP_SUFFIXES
        )

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Hash one image; unreadable or tiny images give `[]`."""
        if not self.supports(artifact):
            return []
        im = load_image(artifact.path)
        if im is None or not usable(im, artifact.role):
            return []
        try:
            feats: list[Feature] = []
            for locator, view in hash_views(im, artifact.role):
                feats += hash_features(view, artifact.case_id, artifact.id, locator)
            return feats
        except Exception:  # one bad image must not stop the pipeline
            logger.warning("hashing failed for %s", artifact.path.name, exc_info=True)
            return []
