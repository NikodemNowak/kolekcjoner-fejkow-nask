"""SigLIP2 image embeddings (`img.siglip`) and impersonated-brand detection (`brand.impersonated`).

One batched GPU pass per artifact batch embeds the full image and, for screenshots and ad
creatives, the header crop (top 20 %, because fake news pages copy the header of the site they
imitate) plus overlapping square tiles (brand bugs such as "tvn24" sit small in a corner of an
ad picture and vanish when the whole screenshot is squashed to 224 px). The full image and
every creative region (`extractors/regions.py`, `locator="crop=x,y,w,h"`) become `img.siglip`
rows, so a creative re-shared inside another feed frame is compared picture to picture; the
header and tiles only feed the brand matcher in `extractors/brand.py`.
"""

from __future__ import annotations

import logging
from functools import cache
from typing import Any

import numpy as np
from PIL import Image

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors._media import is_image
from fakecollector.extractors.image_hash import (
    IMAGE_ROLES,
    REGION_ROLES,
    SKIP_SUFFIXES,
    big_enough,
    load_image,
    usable,
)
from fakecollector.extractors.regions import crops as region_crops
from fakecollector.models import device

logger = logging.getLogger(__name__)

MODEL_ID = "google/siglip2-base-patch16-224"
DIM = 768
BATCH = 64
HEADER_FRACTION = 0.2
HEADER_ROLES = frozenset({"screenshot", "ad_creative"})
MAX_TILES = 24
CLOAKED_TRUST = 0.5
"""Confidence of SigLIP rows from page variants flagged `cloaking_suspected` (one of them
is a decoy page with stock photos that look like anything); scales their evidence."""


@cache
def _model() -> tuple[Any, Any, str]:
    """Load SigLIP2 once (FP16 on GPU, FP32 on CPU)."""
    import torch
    from transformers import AutoModel, AutoProcessor

    dev = device()
    dtype = torch.float16 if dev == "cuda" else torch.float32
    model = AutoModel.from_pretrained(MODEL_ID, dtype=dtype).to(dev).eval()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    logger.info("loaded %s on %s", MODEL_ID, dev)
    return model, processor, dev


def _as_tensor(out: Any) -> Any:
    """Unwrap features: transformers 5 returns a ModelOutput, v4 a plain tensor."""
    return out if hasattr(out, "float") and not hasattr(out, "pooler_output") else out.pooler_output


def _normalise(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    out: np.ndarray = (x / np.maximum(norms, 1e-12)).astype(np.float32)
    return out


def embed_images(images: list[Image.Image], batch_size: int = BATCH) -> np.ndarray:
    """Embed RGB images with SigLIP2; returns an L2-normalised `(n, 768)` float32 array."""
    if not images:
        return np.zeros((0, DIM), dtype=np.float32)
    import torch

    model, processor, dev = _model()
    out: list[np.ndarray] = []
    for i in range(0, len(images), batch_size):
        batch = [im.convert("RGB") for im in images[i : i + batch_size]]
        pixels = processor(images=batch, return_tensors="pt")["pixel_values"]
        with torch.inference_mode():
            feats = model.get_image_features(pixel_values=pixels.to(dev, model.dtype))
        out.append(_as_tensor(feats).float().cpu().numpy())
    return _normalise(np.concatenate(out))


def embed_texts(texts: list[str], batch_size: int = BATCH) -> np.ndarray:
    """Embed texts with the SigLIP2 text tower (for zero-shot prompts); L2-normalised."""
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    import torch

    model, processor, dev = _model()
    out: list[np.ndarray] = []
    for i in range(0, len(texts), batch_size):
        # SigLIP was trained on lower-cased text padded to 64 tokens; other settings degrade it.
        batch = [t.lower() for t in texts[i : i + batch_size]]
        tok = processor(
            text=batch,
            padding="max_length",
            max_length=64,
            truncation=True,
            return_tensors="pt",
        )
        with torch.inference_mode():
            feats = model.get_text_features(**{k: v.to(dev) for k, v in tok.items()})
        out.append(_as_tensor(feats).float().cpu().numpy())
    return _normalise(np.concatenate(out))


def release() -> None:
    """Drop the cached model and free GPU memory (the GPU is shared with other extractors)."""
    _model.cache_clear()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def header_crop(im: Image.Image, fraction: float = HEADER_FRACTION) -> Image.Image:
    """Top `fraction` of a screenshot, where a cloned news site keeps its logo bar."""
    return im.crop((0, 0, im.width, max(1, int(im.height * fraction))))


def brand_crops(im: Image.Image) -> list[tuple[str, Image.Image]]:
    """Header band plus overlapping square tiles (side = half the short edge, stride = side/2)."""
    crops: list[tuple[str, Image.Image]] = []
    if im.height * HEADER_FRACTION >= 40:
        crops.append(("header", header_crop(im)))
    side = min(im.width, im.height) // 2
    if side < 60:
        return crops
    step = side // 2
    for y in range(0, im.height - side + 1, step):
        for x in range(0, im.width - side + 1, step):
            if len(crops) > MAX_TILES:
                return crops
            crops.append((f"tile {x},{y},{side}", im.crop((x, y, x + side, y + side))))
    return crops


class SiglipExtractor(BaseExtractor):
    """SigLIP2 vectors for screenshots, ad creatives and content images; brand matches on top."""

    name = "image_siglip"
    version = 4
    stage = 2
    requires = "ml"

    def supports(self, artifact: Artifact) -> bool:
        """Raster images in a visual role."""
        return (
            is_image(artifact)
            and artifact.role in IMAGE_ROLES
            and artifact.path.suffix.lower() not in SKIP_SUFFIXES
        )

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Single-artifact path; delegates to the batched one."""
        return self.extract_batch([artifact], [prior])[0]

    def extract_batch(
        self, artifacts: list[Artifact], priors: list[list[Feature]]
    ) -> list[list[Feature]]:
        """Embed all usable images in GPU batches; unreadable or tiny ones give `[]`."""
        results: list[list[Feature]] = [[] for _ in artifacts]
        crops: list[Image.Image] = []
        owners: list[tuple[int, str]] = []  # (artifact index, locator; "" = full image)
        brand_only: set[int] = set()  # flat landing graphics: logos still feed brand matching
        for i, art in enumerate(artifacts):
            if not self.supports(art):
                continue
            im = load_image(art.path)
            if im is None or not big_enough(im):
                continue
            if not usable(im, art.role):
                brand_only.add(i)
            crops.append(im)
            owners.append((i, ""))
            if art.role in REGION_ROLES:
                for locator, crop in region_crops(im):
                    crops.append(crop)
                    owners.append((i, locator))
            if art.role in HEADER_ROLES:
                for locator, crop in brand_crops(im):
                    crops.append(crop)
                    owners.append((i, locator))
        if not crops:
            return results
        try:
            vecs = embed_images(crops)
        except Exception:  # a model failure degrades to "no vision", never a crash
            logger.warning("SigLIP embedding failed for %d images", len(crops), exc_info=True)
            return results

        by_art: dict[int, dict[str, np.ndarray]] = {}
        for (i, part), vec in zip(owners, vecs, strict=True):
            by_art.setdefault(i, {})[part] = vec
        for i, parts in by_art.items():
            art = artifacts[i]
            trust = CLOAKED_TRUST if art.meta.get("cloaking_suspected") else 1.0
            for locator, vec in parts.items():
                if i not in brand_only and (locator == "" or locator.startswith("crop=")):
                    results[i].append(
                        Feature(
                            case_id=art.case_id,
                            artifact_id=art.id,
                            name="img.siglip",
                            value="",
                            vector=[float(x) for x in vec],
                            confidence=trust,
                            locator=locator,
                        )
                    )
            # Creative regions join the weak (placement-unknown) group: a logo bug inside the
            # picture counts only when the page or its OCR masthead claims the same brand.
            # (SigLIP sees 224 px, so the crops need no upscaling.)
            results[i] += brand_features(art, parts, _rule_brands(priors[i]))
        return results


def _rule_brands(prior: list[Feature]) -> set[str]:
    """Brands the case claims: title suffix, site-name meta (`brand_rules`), OCR masthead."""
    return {
        f.value
        for f in prior
        if f.name == "brand.impersonated"
        and f.locator in {"title", "ocr:header"} | _SITE_META_LOCATORS
    }


_SITE_META_LOCATORS = frozenset(
    f"meta[{key}]" for key in ("og:site_name", "application-name", "apple-mobile-web-app-title")
)


def brand_features(art: Artifact, parts: dict[str, np.ndarray], claimed: set[str]) -> list[Feature]:
    """Logo matches as `brand.impersonated` only where they show impersonation.

    A logo in the header band (or filling a whole screenshot) is the page dressing up as
    that brand. A logo elsewhere is often an "as seen on TVN24" trust badge that unrelated
    supplement landers share, so it counts as impersonation only when the page's own title
    or site-name meta names the same brand (`claimed`). Otherwise a whole logo image on the
    landing page becomes context-only `brand.logo`, and a tile match (a small, unplaced
    part of a screenshot, where blue UI bars once read as WP) is dropped.
    """
    from fakecollector.extractors.brand import match_brands

    strong = {
        k: v for k, v in parts.items() if k == "header" or (k == "" and art.role in HEADER_ROLES)
    }
    weak = {k: v for k, v in parts.items() if k not in strong}
    out: dict[str, Feature] = {}
    for group, matches in (("strong", match_brands(strong)), ("weak", match_brands(weak))):
        for slug, score, locator in matches:
            if group == "strong" or slug in claimed:
                name = "brand.impersonated"
            elif locator == "":
                name = "brand.logo"
            else:
                continue
            if slug in out and (out[slug].name == "brand.impersonated" or name == "brand.logo"):
                continue
            out[slug] = Feature(
                case_id=art.case_id,
                artifact_id=art.id,
                name=name,
                value=slug,
                confidence=round(score, 4),
                locator=locator,
            )
    return list(out.values())
