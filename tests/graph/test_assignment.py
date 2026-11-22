from __future__ import annotations

from math import sqrt

import pytest

from fakecollector.graph.analyze import analyze
from fakecollector.graph.assign import assign, cluster_new
from fakecollector.graph.config import EdgeConfig

from .test_graph import feat


def test_assign_variant_new_and_review() -> None:
    base_features = [
        feat("base", "ids.kit_landing", "landing"),
        feat("base", "ids.fb_pixel", "pixel"),
        feat("base", "kit.sdk", "sdk"),
        feat("base", "infra.ip", "104.16.1.2"),
        feat("base", "person.public_figure", "person"),
        feat("review-base", "text.bge", vector=[1, 0]),
        feat("operator-peer", "ids.fb_pixel", "pixel"),
        feat("operator-peer", "url.domain", "peer.example"),
    ]
    base = analyze(base_features)
    campaign_by_case = {case: c.id for c in base.campaigns for case in c.case_ids}
    result = {
        item.case_id: item
        for item in assign(
            [
                feat("variant", "ids.kit_landing", "landing"),
                feat("variant", "kit.sdk", "sdk"),
                feat("unrelated", "infra.ip", "104.16.1.2"),
                feat("unrelated", "person.public_figure", "person"),
                feat("pixel-only", "ids.fb_pixel", "pixel"),
                feat("borderline", "text.bge", vector=[0.9, sqrt(1 - 0.9**2)]),
            ],
            base,
            base_features,
            new_case_ids=["empty"],
        )
    }
    assert result["variant"].decision == "existing"
    assert result["variant"].campaign_id == campaign_by_case["base"]
    assert result["variant"].duplicate_of is None
    assert result["variant"].toolkits == ["Toolkit:sdk"]
    assert result["variant"].comparable == ["ids", "template"]
    assert result["unrelated"].decision == "new"
    assert result["unrelated"].operator_id is None
    assert result["pixel-only"].decision == "new"
    assert result["pixel-only"].operator_id == base.operators["base"]
    assert result["borderline"].decision == "review"
    assert result["borderline"].campaign_id == campaign_by_case["review-base"]
    assert result["borderline"].evidence[0].value == "cos 0.90"
    assert result["empty"].decision == "new"


def test_assign_exact_duplicate() -> None:
    base_features = [
        feat("base", "text.raw", "base text", artifact="raw"),
        feat("base", "text.bge", vector=[1, 0], artifact="body"),
        feat("base", "text.bge", vector=[1, 0], artifact="body"),
    ]
    base = analyze(base_features, ["empty-base"])
    results = assign(
        [
            feat("artifact-copy", "text.raw", "different text", artifact="raw"),
            feat("artifact-copy", "ids.fb_pixel", "pixel", artifact="body"),
            feat("features-copy", "text.bge", vector=[1, 0]),
            feat("features-copy", "text.raw", "unrelated informational text"),
            feat("features-copy", "text.bge", vector=[1, 0]),
            feat("partial", "text.raw", "base text", artifact="raw"),
            feat("partial", "text.bge", vector=[1, 0]),
        ],
        base,
        base_features,
        new_case_ids=["empty-new"],
    )
    for result in (results[0], results[2]):
        assert result.decision == "existing"
        assert result.duplicate_of == "base"
        assert result.campaign_id == base.campaigns[0].id
        assert result.score == 1
    assert results[1].case_id == "empty-new"
    assert results[1].decision == "new"
    assert results[3].case_id == "partial"
    assert results[3].duplicate_of is None


def test_assign_does_not_renumber_base_campaigns() -> None:
    base_features = [feat("z-base", "ids.kit_landing", "known")]
    base = analyze(base_features)
    snapshot = base.model_dump()
    new_features = [
        feat("a-variant", "ids.kit_landing", "known"),
        feat("a-variant", "url.domain", "variant.example"),
    ]
    (result,) = assign(new_features, base, base_features)
    assert result.campaign_id == base.campaigns[0].id
    assert result.decision == "existing"
    assert base.model_dump() == snapshot


def test_cluster_new_groups_new_cases() -> None:
    base_features = [
        feat("base", "ids.kit_landing", "known"),
        feat("base", "ids.fb_pixel", "pixel"),
        feat("peer", "ids.fb_pixel", "pixel"),
    ]
    base = analyze(base_features)
    new_features = [
        feat("a", "ids.kit_landing", "unknown"),
        feat("b", "ids.kit_landing", "unknown"),
        feat("a", "ids.fb_pixel", "pixel"),
        feat("a", "ids.kit_tenant", "tenant"),
        feat("b", "ids.kit_tenant", "tenant"),
        feat("c", "ids.kit_landing", "known"),
        feat("c", "url.domain", "different.example"),
    ]
    assignments = assign(new_features, base, base_features, new_case_ids=["zero"])
    campaigns = cluster_new(assignments, new_features, base, base_features)
    assert [campaign.case_ids for campaign in campaigns] == [["a", "b"], ["zero"]]
    assert campaigns[0].operator_id == base.operators["base"]
    assert campaigns[0].flags == []
    assert base.campaigns[0].id not in {campaign.id for campaign in campaigns}


def test_single_strong_edge_into_large_campaign_is_existing() -> None:
    cfg = EdgeConfig(tau_assign=0.95)
    base_features = [feat(case, "ids.kit_landing", "known") for case in ("a", "b", "c")]
    base_features.append(feat("a", "asset.sha256", "a" * 64))
    base = analyze(base_features, cfg=cfg)
    (campaign,) = base.campaigns
    assert campaign.case_ids == ["a", "b", "c"]
    (result,) = assign([feat("new", "asset.sha256", "a" * 64)], base, base_features, cfg)
    assert result.decision == "existing"
    assert result.campaign_id == campaign.id
    assert result.score == pytest.approx(0.9)
    assert result.duplicate_of is None


def test_url_with_campaign_domain_is_existing_or_review() -> None:
    base_features = [
        feature
        for case in ("a", "b", "c")
        for feature in (
            feat(case, "ids.kit_landing", "shared-landing"),
            feat(case, "url.domain", f"{case}.example"),
        )
    ]
    base = analyze(base_features)
    (campaign,) = base.campaigns
    # Represent a URL-only input by the domain extracted from its URL.
    (result,) = assign([feat("new", "url.domain", "a.example")], base, base_features)
    assert result.decision in {"existing", "review"}
    assert result.campaign_id == campaign.id
    assert result.duplicate_of is None


def test_assign_reviews_subthreshold_campaign_evidence() -> None:
    cosine = 0.825
    base_features = [feat("base", "text.bge", vector=[1, 0])]
    base = analyze(base_features)
    (result,) = assign(
        [feat("new", "text.bge", vector=[cosine, sqrt(1 - cosine**2)])],
        base,
        base_features,
    )
    assert result.decision == "review"
    assert result.campaign_id == base.campaigns[0].id
    assert result.score == pytest.approx(0.25)


def test_assign_reviews_high_ungated_score() -> None:
    base_features = [
        feat("base", "ids.fb_pixel", "pixel"),
        feat("base", "person.public_figure", "person"),
        feat("base", "url.domain", "base.example"),
    ]
    base = analyze(base_features)
    (result,) = assign(
        [feat("new", "ids.fb_pixel", "pixel"), feat("new", "person.public_figure", "person")],
        base,
        base_features,
    )
    assert result.decision == "review"
    assert result.campaign_id == base.campaigns[0].id
    assert result.score == pytest.approx(0.61)


def test_assign_shared_pixel_is_new_with_known_operator() -> None:
    base_features = [feat("base", "ids.fb_pixel", "pixel")]
    base = analyze(base_features)
    (result,) = assign([feat("new", "ids.fb_pixel", "pixel")], base, base_features)
    assert result.decision == "new"
    assert result.campaign_id is None
    assert result.operator_id is not None
    assert result.duplicate_of is None


@pytest.mark.parametrize(
    ("rival_feature", "rival_value", "margin"),
    [("ids.ad_library", "ad", 0.0), ("url.domain", "b.example", 0.07)],
)
def test_assign_reviews_close_competing_campaigns(
    rival_feature: str, rival_value: str, margin: float
) -> None:
    base_features = [
        feat("a", "ids.kit_landing", "landing"),
        feat("b", rival_feature, rival_value),
    ]
    base = analyze(base_features)
    new_features = [
        feat("new", "ids.kit_landing", "landing"),
        feat("new", rival_feature, rival_value),
    ]
    (result,) = assign(new_features, base, base_features)
    assert result.decision == "review"
    assert result.score == pytest.approx(0.97)
    assert result.margin == pytest.approx(margin)
    expected = base.campaigns[0].id if margin else min(c.id for c in base.campaigns)
    assert result.campaign_id == expected


def test_assign_breaks_tied_maxima_by_comparable_mean() -> None:
    cfg = EdgeConfig()
    base_features = [
        feat("a", "text.minhash", vector=[1.0] * cfg.num_perm),
        feat("b", "text.minhash", vector=[1.0] * cfg.num_perm),
        feat("c", "text.minhash", vector=[2.0] * cfg.num_perm),
        feat("d", "text.minhash", vector=[2.0] * cfg.num_perm),
        feat("a", "url.domain", "a.example"),
        feat("c", "url.domain", "c.example"),
        feat("d", "url.domain", "d.example"),
    ]
    base = analyze(base_features, cfg=cfg)
    preferred, other = base.campaigns
    assert preferred.id > other.id
    (result,) = assign(
        [
            feat("new", "url.domain", "a.example"),
            feat("new", "url.domain", "c.example"),
        ],
        base,
        base_features,
        cfg,
    )
    assert result.decision == "review"
    assert result.campaign_id == preferred.id
    assert result.score == pytest.approx(0.9)
    assert result.margin == 0


def test_assign_compares_base_cases_even_when_new_cases_are_closer_neighbours() -> None:
    cfg = EdgeConfig(knn_k=1)
    base_features = [feat("base", "text.bge", vector=[1, 0])]
    new_features = [
        feat("new-a", "text.bge", vector=[0.9, sqrt(1 - 0.9**2)]),
        feat("new-b", "text.bge", vector=[0.91, sqrt(1 - 0.91**2)]),
    ]
    base = analyze(base_features, cfg=cfg)
    results = assign(new_features, base, base_features, cfg)
    assert [result.decision for result in results] == ["review", "review"]
    assert all(result.campaign_id == base.campaigns[0].id for result in results)


def test_assign_recomputes_stop_status_on_combined_corpus() -> None:
    base_features = [
        *(feat(case, "infra.endpoint", "collector.example/post") for case in ("a", "b", "c")),
        *(feat(case, "asset.sha256", "shared") for case in ("a", "b", "c")),
    ]
    base = analyze(base_features)
    assert base.operators["a"] == base.operators["b"]
    (result,) = assign(
        [
            feat("new", "infra.endpoint", "collector.example/post"),
            feat("new", "asset.sha256", "shared"),
            feat("new", "text.topic", "new-story"),
        ],
        base,
        base_features,
    )
    assert result.decision == "new"
    assert result.operator_id is None
    assert result.evidence == []


def test_strong_link_into_campaign_of_another_operator_is_review() -> None:
    # Campaign X (a, b) runs under pixel px-x; case z belongs to operator px-y.
    base_features = [
        *(feat(case, "ids.kit_landing", "landing-x") for case in ("a", "b")),
        *(feat(case, "ids.fb_pixel", "px-x") for case in ("a", "b")),
        feat("z", "ids.fb_pixel", "px-y"),
        feat("z", "url.domain", "z-only.example"),
    ]
    base = analyze(base_features)
    campaign_x = next(c for c in base.campaigns if c.case_ids == ["a", "b"])
    assert campaign_x.operator_id is not None
    # The new capture repeats campaign X's landing (a cloaked, multi-story page) but its
    # tracker ties it to z's operator.
    new = [feat("new", "ids.kit_landing", "landing-x"), feat("new", "ids.fb_pixel", "px-y")]
    (result,) = assign(new, base, base_features)
    assert result.campaign_id == campaign_x.id
    assert result.operator_id is not None and result.operator_id != campaign_x.operator_id
    assert result.decision == "review"


def test_strong_link_with_same_operator_stays_existing() -> None:
    base_features = [
        *(feat(case, "ids.kit_landing", "landing-x") for case in ("a", "b")),
        *(feat(case, "ids.fb_pixel", "px-x") for case in ("a", "b")),
    ]
    base = analyze(base_features)
    (campaign,) = base.campaigns
    new = [feat("new", "ids.kit_landing", "landing-x"), feat("new", "ids.fb_pixel", "px-x")]
    (result,) = assign(new, base, base_features)
    assert result.decision == "existing"
    assert result.campaign_id == campaign.id
