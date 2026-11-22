from __future__ import annotations

import pytest

from fakecollector.graph.analyze import analyze
from fakecollector.graph.assign import assign
from fakecollector.graph.config import EdgeConfig

from .test_graph import feat


def test_siglip_and_person_alone_do_not_link() -> None:
    base_features = [
        feat("a", "img.siglip", vector=[1, 0]),
        feat("a", "person.public_figure", "person"),
    ]
    new_features = [
        feat("b", "img.siglip", vector=[2, 0]),
        feat("b", "person.public_figure", "person"),
    ]
    features = base_features + new_features
    (edge,) = analyze(features, cfg=EdgeConfig(min_campaign_evidence=0.3)).edges
    assert edge.signals == pytest.approx({"image": 0.45, "person": 0.35})
    assert edge.score > EdgeConfig().tau

    batch = analyze(features)
    assert batch.edges == []
    assert [campaign.case_ids for campaign in batch.campaigns] == [["a"], ["b"]]

    base = analyze(base_features)
    (result,) = assign(new_features, base, base_features)
    assert result.decision == "review"
    assert result.score == pytest.approx(edge.score)
