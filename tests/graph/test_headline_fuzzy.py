"""Fuzzy headline matching: a re-worded or OCR-garbled copy of a known headline template."""

from __future__ import annotations

import pytest

from fakecollector.core.schemas import Feature
from fakecollector.core.text import headline_content, headline_template
from fakecollector.graph.blocking import candidate_pairs
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import build_entities
from fakecollector.graph.signals import build_context, pair_signals

KNOWN = "«Wiem, co się stało»: atak na Jana Kowalskiego, prezesa Firmy Testowej — Portal.pl"
# The same story as OCR reads it off a phone screenshot: no quotes, a typo, no site suffix.
GARBLED = "Wiem; co się stałow: atak na Jana Kowalskiego, prezesa Firmy Testowej"
OTHER = "Nowa wystawa fotografii przyrodniczej otwarta w sobotę w muzeum"


def _tpl(case: str, title: str) -> Feature:
    template = headline_template(title, ["Jan Kowalski"])
    assert template is not None
    return Feature(case_id=case, artifact_id=f"{case}-a", name="text.headline_tpl", value=template)


def _signals(features: list[Feature], cfg: EdgeConfig, a: str = "a", b: str = "b") -> dict:
    entities, _ = build_entities(features, cfg=cfg)
    ctx = build_context(features, entities, cfg)
    left = [f for f in features if f.case_id == a]
    right = [f for f in features if f.case_id == b]
    return {
        item.kind: item for _, items in pair_signals(left, right, ctx).values() for item in items
    }


def test_headline_content_drops_placeholders_and_short_templates() -> None:
    assert headline_content("atak na {PERSON} prezesa {NUM} firmy") == "atak na prezesa firmy"
    assert headline_content("wiem kto strzelałw: zamach na") == "wiem kto strzelalw zamach na"
    assert headline_content("app store {PERSON}") is None  # shared by unrelated pages


def test_garbled_copy_of_known_headline_is_campaign_evidence(cfg: EdgeConfig) -> None:
    features = [_tpl("a", KNOWN), _tpl("b", GARBLED), _tpl("c", OTHER)]
    item = _signals(features, cfg)["text.headline_fuzzy"]
    assert item.tier == "campaign"
    assert item.family == "text"
    assert item.weight >= cfg.min_campaign_evidence  # a near-copy can anchor a link
    assert item.detail.startswith("Zbliżony nagłówek")
    assert "text.headline_fuzzy" not in _signals(features, cfg, "a", "c")


def test_identical_template_is_left_to_the_exact_key(cfg: EdgeConfig) -> None:
    features = [_tpl("a", KNOWN), _tpl("b", KNOWN), _tpl("c", OTHER)]
    kinds = _signals(features, cfg)
    assert "text.headline_tpl" in kinds
    assert "text.headline_fuzzy" not in kinds


def test_fuzzy_weight_grows_with_similarity(cfg: EdgeConfig) -> None:
    near = [_tpl("a", KNOWN), _tpl("b", GARBLED)]
    exactish = [_tpl("a", KNOWN), _tpl("b", KNOWN.replace("«", "").replace("»", " !"))]
    low = _signals(near, cfg)["text.headline_fuzzy"].weight
    high = (
        _signals(exactish, cfg).get("text.headline_tpl")
        or _signals(exactish, cfg)["text.headline_fuzzy"]
    )
    assert low <= high.weight <= 0.6 + 1e-9


def test_threshold_blocks_loosely_related_headlines() -> None:
    cfg = EdgeConfig(headline_fuzzy_threshold=0.99)
    features = [_tpl("a", KNOWN), _tpl("b", GARBLED)]
    assert "text.headline_fuzzy" not in _signals(features, cfg)


def test_fuzzy_headlines_are_blocking_candidates(cfg: EdgeConfig) -> None:
    features = [_tpl("a", KNOWN), _tpl("b", GARBLED), _tpl("c", OTHER)]
    entities, links = build_entities(features, cfg=cfg)
    pairs = candidate_pairs(entities, links, features, cfg)
    assert ("a", "b") in pairs
    assert ("a", "c") not in pairs and ("b", "c") not in pairs
    assert candidate_pairs(entities, links, features, cfg, case_id="c") == set()


def test_registry_row_is_never_a_feature() -> None:
    from fakecollector.core.registry import FEATURES

    spec = FEATURES["text.headline_fuzzy"]
    assert spec.kind == "fuzzy" and spec.source == "text.headline_tpl"
    assert spec.weight == pytest.approx(FEATURES["text.headline_tpl"].weight)


def test_null_uses_only_pairs_from_different_campaigns(cfg: EdgeConfig) -> None:
    from fakecollector.evaluation.calibration import headline_fuzzy_null

    features = [_tpl("a", KNOWN), _tpl("b", GARBLED), _tpl("c", OTHER)]
    same = headline_fuzzy_null(features, {"a": "C1", "b": "C1", "c": "C2"}, cfg)
    assert len(same) == 2  # a-c and b-c; the a-b pair is within one campaign
    assert same.max() < cfg.headline_fuzzy_threshold
    split = headline_fuzzy_null(features, {"a": "C1", "b": "C3", "c": "C2"}, cfg)
    assert len(split) == 3 and split.max() >= cfg.headline_fuzzy_threshold


def test_per_headline_max_null_keeps_one_score_per_headline(cfg: EdgeConfig) -> None:
    from fakecollector.evaluation.calibration import headline_fuzzy_null

    features = [_tpl("a", KNOWN), _tpl("b", GARBLED), _tpl("c", OTHER)]
    best = headline_fuzzy_null(
        features, {"a": "C1", "b": "C1", "c": "C2"}, cfg, per_headline_max=True
    )
    assert len(best) == 3  # c's best is the closer of a and b
    assert best.max() < cfg.headline_fuzzy_threshold


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Kliknij tutajj i kontynuuj", "Kliknij tutaj i kontynuuj"),
        (
            "przykladprofil przykladprofil konto parodystyczne",
            "przykladprofil przykladprofil konto parodystyczne nowe",
        ),
        ("Smutny dzień dla kraju: żegnamy", "To bardzo smutny dzień dla całego kraju, żegnaj"),
    ],
)
def test_generic_or_short_shared_content_is_not_fuzzy_evidence(
    cfg: EdgeConfig, left: str, right: str
) -> None:
    features = [_tpl("a", left), _tpl("b", right), _tpl("c", OTHER)]
    assert "text.headline_fuzzy" not in _signals(features, cfg)


def test_generic_exact_headline_is_context_only(cfg: EdgeConfig) -> None:
    features = [_tpl("a", "Witaj w Janie Kowalskim"), _tpl("b", "Witaj w Janie Kowalskim")]
    features.append(_tpl("c", OTHER))
    item = _signals(features, cfg)["text.headline_tpl"]
    assert item.tier == "context"
    assert item.weight <= cfg.tier_caps["context"]
    specific = _signals([_tpl("a", KNOWN), _tpl("b", KNOWN), _tpl("c", OTHER)], cfg)
    assert specific["text.headline_tpl"].tier == "campaign"
