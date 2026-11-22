"""SigLIP look-alikes (headshots, stock photos) need near-identity or another family."""

from __future__ import annotations

from math import sqrt

import pytest

from fakecollector.core.schemas import Evidence, Feature
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import build_entities
from fakecollector.graph.signals import build_context, pair_signals, siglip_usable


def _vec(cos: float) -> list[float]:
    return [cos, sqrt(1 - cos * cos), 0.0, 0.0]


def _img(case: str, cos: float, artifact: str = "", confidence: float = 1.0) -> Feature:
    return Feature(
        case_id=case,
        artifact_id=artifact or f"{case}-img",
        name="img.siglip",
        value="",
        vector=_vec(cos),
        confidence=confidence,
    )


def _evidence(features: list[Feature], cfg: EdgeConfig) -> dict[str, Evidence]:
    entities, _ = build_entities(features, cfg=cfg)
    ctx = build_context(features, entities, cfg, case_ids=["a", "b", "c", "d"])
    left = [f for f in features if f.case_id == "a"]
    right = [f for f in features if f.case_id == "b"]
    return {
        item.kind: item for _, items in pair_signals(left, right, ctx).values() for item in items
    }


def test_lookalike_image_alone_is_context(cfg: EdgeConfig) -> None:
    item = _evidence([_img("a", 1.0), _img("b", 0.95)], cfg)["img.siglip"]
    assert item.tier == "context"
    assert item.weight <= cfg.tier_caps["context"]


def test_near_identical_image_alone_stays_campaign(cfg: EdgeConfig) -> None:
    item = _evidence([_img("a", 1.0), _img("b", 0.99)], cfg)["img.siglip"]
    assert item.tier == "campaign"


def test_other_family_corroborates_lookalike_image(cfg: EdgeConfig) -> None:
    domain = [
        Feature(case_id=case, artifact_id=f"{case}-url", name="url.domain", value="x.test")
        for case in ("a", "b")
    ]
    item = _evidence([_img("a", 1.0), _img("b", 0.95), *domain], cfg)["img.siglip"]
    assert item.tier == "campaign"


def test_portrait_images_are_not_compared(cfg: EdgeConfig) -> None:
    share = Feature(case_id="b", artifact_id="b-img", name="img.face_share", value="0.55")
    assert "img.siglip" not in _evidence([_img("a", 1.0), _img("b", 0.99), share], cfg)
    small = share.model_copy(update={"value": "0.25"})
    assert "img.siglip" in _evidence([_img("a", 1.0), _img("b", 0.99), small], cfg)
    assert siglip_usable([share, _img("b", 0.9)], cfg) == [share]


def test_cloaked_variant_images_count_less(cfg: EdgeConfig) -> None:
    full = _evidence([_img("a", 1.0), _img("b", 0.99)], cfg)["img.siglip"].weight
    cloaked = _evidence([_img("a", 1.0), _img("b", 0.99, confidence=0.5)], cfg)["img.siglip"]
    assert cloaked.weight == pytest.approx(full / 2)
