"""Impersonated-brand detection (`brand.impersonated`) from SigLIP2 vectors.

Scoring, per brand b and image part (full image, header band or tile):
    score_b = P_zs(b) * clip((cos_logo(b) - mean_b' cos_logo(b')) / LOGO_MARGIN_SCALE, 0, 1)
where P_zs is SigLIP's sigmoid probability for the prompt "the <brand> logo" and cos_logo is
the cosine to the nearest reference logo view (`data/logos/refs.npz`). Subtracting the mean
over brands cancels the "plain white tile looks like every logo" effect, and the zero-shot
factor kills look-alike UI (blue bars matched "WP" at P = 0.9 on their own). A brand is
emitted only when both factors pick the same brand and the score clears `THRESHOLD`.

Calibration (858 crops from both corpora, labelled
by eye): the highest false positive scored 0.54 (a TVP2 logo read as TVN24), true TVN24 logos
scored 0.64-1.00, so THRESHOLD = 0.6 (precision first; small in-ad logos are missed).
Extending the set to 34 brands (banks, news media incl. TVP/Polsat and the "as seen on" US
networks, state bodies, marketplaces, crypto) kept every earlier detection, removed the one
earlier false positive (a blue bar read as WP) and added only correct TVP/Polsat logo hits.
"""

from __future__ import annotations

import logging
import os
from functools import cache
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REFS_PATH = Path(os.environ.get("LOGO_REFS", "data/logos/refs.npz"))
THRESHOLD = 0.6
LOGO_MARGIN_SCALE = 0.1

BRAND_NAMES: dict[str, str] = {
    "gazeta_pl": "Gazeta.pl",
    "tvn24": "TVN24",
    "onet": "Onet",
    "wp": "WP Wirtualna Polska",
    "inpost": "InPost",
    "pko_bp": "PKO Bank Polski",
    "pekao": "Bank Pekao",
    "nbp": "NBP Narodowy Bank Polski",
    "app_store": "Apple App Store",
    "google_play": "Google Play",
    "facebook": "Facebook",
    "allegro": "Allegro",
    "mbank": "mBank",
    "ing": "ING Bank",
    "santander": "Santander Bank",
    "millennium": "Bank Millennium",
    "alior": "Alior Bank",
    "bnp_paribas": "BNP Paribas",
    "interia": "Interia",
    "polsat": "Polsat",
    "tvp": "TVP Telewizja Polska",
    "rzeczpospolita": "Rzeczpospolita",
    "business_insider": "Business Insider",
    "forbes": "Forbes",
    "zus": "ZUS",
    "orlen": "Orlen",
    "pge": "PGE",
    "olx": "OLX",
    "revolut": "Revolut",
    "binance": "Binance",
    "fox_news": "Fox News",
    "nbc": "NBC",
    "cnn": "CNN",
    "bbc": "BBC",
}
"""Brand slug -> name used in the zero-shot prompt. "Website header" prompts were tried and
dropped: they fire on any blue-and-white page chrome."""


@cache
def _refs() -> tuple[np.ndarray, np.ndarray] | None:
    """Reference logo vectors and their brand slugs, or None when the set is not built."""
    if not REFS_PATH.exists():
        logger.warning("no logo reference set at %s; only zero-shot brand matching", REFS_PATH)
        return None
    data = np.load(REFS_PATH)
    return data["vectors"].astype(np.float32), data["slugs"]


@cache
def _prompts() -> tuple[np.ndarray, float, float]:
    """Prompt vectors (rows follow BRAND_NAMES) and SigLIP's logit scale/bias."""
    from fakecollector.extractors.image_embed import _model, embed_texts

    vecs = embed_texts([f"the {name} logo" for name in BRAND_NAMES.values()])
    model = _model()[0]
    scale = float(model.logit_scale.detach().float().exp().cpu())
    bias = float(model.logit_bias.detach().float().cpu())
    return vecs, scale, bias


def brand_scores(vec: np.ndarray) -> dict[str, float]:
    """Combined per-brand score (0..1) for one unit vector; 0 where the two factors disagree."""
    slugs = list(BRAND_NAMES)
    pvecs, scale, bias = _prompts()
    zs = 1.0 / (1.0 + np.exp(-(pvecs @ vec * scale + bias)))
    refs = _refs()
    if refs is None:
        # Without references only a very confident zero-shot hit is trusted.
        return {s: float(p) if p >= 0.95 else 0.0 for s, p in zip(slugs, zs, strict=True)}
    sims = refs[0] @ vec
    logo = np.array([sims[refs[1] == s].max() if (refs[1] == s).any() else -1.0 for s in slugs])
    margin = np.clip((logo - logo.mean()) / LOGO_MARGIN_SCALE, 0.0, 1.0)
    if int(np.argmax(zs)) != int(np.argmax(logo)):
        return dict.fromkeys(slugs, 0.0)
    return {s: float(z * m) for s, z, m in zip(slugs, zs, margin, strict=True)}


def match_brands(parts: dict[str, np.ndarray]) -> list[tuple[str, float, str]]:
    """Return `(slug, score, locator)` per brand found in any part (strongest part wins).

    `parts` maps a locator ("" = full image, "header", "tile x,y,side") to a unit vector.
    """
    found: dict[str, tuple[float, str]] = {}
    for locator, vec in parts.items():
        try:
            scores = brand_scores(vec)
        except Exception:  # brand context is optional; it must never fail a batch
            logger.warning("brand matching failed", exc_info=True)
            return []
        slug, score = max(scores.items(), key=lambda kv: kv[1])
        if score >= THRESHOLD and score > found.get(slug, (-1.0, ""))[0]:
            found[slug] = (score, locator)
    return [(slug, score, loc) for slug, (score, loc) in found.items()]
