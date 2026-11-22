from __future__ import annotations

from hashlib import sha256
from itertools import combinations

import pytest

from fakecollector.core.schemas import Feature
from fakecollector.graph.analyze import analyze
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import build_entities
from fakecollector.graph.fusion import build_edges

_CASE_IDS = [f"case-{i:02d}" for i in range(25)]


def _shared_features(name: str, value: str, count: int) -> list[Feature]:
    return [
        Feature(case_id=case_id, artifact_id=f"{case_id}-capture", name=name, value=value)
        for case_id in _CASE_IDS[:count]
    ]


@pytest.mark.parametrize(
    ("name", "value", "count"),
    [
        pytest.param("ids.kit_landing", "landing-test", 8, id="kit-landing"),
        pytest.param("ids.ad_library", "ad-test", 4, id="ad-library"),
    ],
)
def test_high_df_campaign_key_still_links(name: str, value: str, count: int) -> None:
    result = analyze(_shared_features(name, value, count), case_ids=_CASE_IDS)

    members = _CASE_IDS[:count]
    assert [(edge.src, edge.dst) for edge in result.edges] == list(combinations(members, 2))
    assert [campaign.case_ids for campaign in result.campaigns] == [
        members,
        *[[case_id] for case_id in _CASE_IDS[count:]],
    ]
    (entity,) = result.entities
    assert entity.df == count
    assert not entity.stop


def test_high_df_platform_domain_stays_stoplisted() -> None:
    features = _shared_features("url.domain", "cdn.jsdelivr.net", 8)
    result = analyze(features, case_ids=_CASE_IDS)

    (entity,) = result.entities
    assert entity.df == 8
    assert entity.stop
    assert result.edges == []

    enabled = analyze(features, case_ids=_CASE_IDS, cfg=EdgeConfig(use_default_stoplist=False))
    assert not enabled.entities[0].stop
    assert len(enabled.edges) == 28


@pytest.mark.parametrize("entry", ["landing-test", "KitLanding:landing-test"])
def test_high_df_campaign_key_respects_explicit_stoplist(entry: str) -> None:
    features = _shared_features("ids.kit_landing", "landing-test", 8)
    entities, links = build_entities(features, stoplist={entry}, case_ids=_CASE_IDS)

    (entity,) = entities
    assert entity.df == 8
    assert entity.stop
    assert build_edges(features, entities, links, EdgeConfig(), case_ids=_CASE_IDS) == []


def test_high_df_operator_key_is_stopped() -> None:
    result = analyze(_shared_features("ids.gtag", "tag-test", 8), case_ids=_CASE_IDS)

    (entity,) = result.entities
    assert entity.df == 8
    assert entity.stop
    assert result.operators == {}


def test_high_df_library_asset_is_stopped() -> None:
    library_hash = sha256(b"synthetic shared library").hexdigest()
    result = analyze(_shared_features("asset.sha256", library_hash, 12), case_ids=_CASE_IDS)

    (entity,) = result.entities
    assert entity.df == 12
    assert entity.stop
    assert result.edges == []


def test_screenshot_only_cases_do_not_dilute_document_frequency() -> None:
    shots = [
        Feature(
            case_id=f"shot-{i:03d}",
            artifact_id=f"shot-{i:03d}-img",
            name="image.phash",
            value=f"{i:016x}",
        )
        for i in range(300)
    ]
    features = [*_shared_features("ids.gtag", "tag-test", 8), *shots]
    for case_id in _CASE_IDS[8:]:  # the rest of the HAR corpus has other tags
        features.append(Feature(case_id=case_id, artifact_id="a", name="ids.gtag", value=case_id))
    case_ids = [*_CASE_IDS, *(f.case_id for f in shots)]
    entities, _ = build_entities(features, case_ids=case_ids)

    shared = next(e for e in entities if e.df == 8)
    assert shared.stop


def test_imitated_brand_domain_read_by_ocr_is_stopped() -> None:
    features = [
        Feature(case_id=case, artifact_id=f"{case}-a", name="ocr.domain", value=value)
        for case in ("a", "b")
        for value in ("gazeta.pl", "scam-host.example")
    ]
    entities, _ = build_entities(features)
    stopped = {entity.value: entity.stop for entity in entities}
    assert stopped == {"gazeta.pl": True, "scam-host.example": False}
