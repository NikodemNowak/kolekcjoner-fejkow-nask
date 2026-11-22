from __future__ import annotations

import logging
import sys
from itertools import combinations
from math import log, sqrt
from random import Random

import pytest

from fakecollector.core.schemas import Edge, Entity, Evidence, Feature
from fakecollector.graph import blocking
from fakecollector.graph.analyze import analyze
from fakecollector.graph.blocking import candidate_pairs
from fakecollector.graph.cluster import attach_operators, cluster, operators, toolkits
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import build_entities
from fakecollector.graph.fusion import build_edges, edges_for, fuse, slot_signals
from fakecollector.graph.signals import build_context, pair_signals


def feat(
    case: str,
    name: str,
    value: str = "",
    *,
    artifact: str | None = None,
    locator: str = "",
    vector: list[float] | None = None,
) -> Feature:
    return Feature(
        case_id=case,
        artifact_id=artifact or f"{case}-capture",
        name=name,
        value=value,
        locator=locator,
        vector=vector,
    )


def test_kit_landing_edge_has_polish_evidence(cfg: EdgeConfig) -> None:
    features = [feat(case, "ids.kit_landing", "landing-test", artifact=case) for case in ("a", "b")]
    entities, links = build_entities(features, cfg=cfg)
    (edge,) = build_edges(features, entities, links, cfg)
    assert edge.score == pytest.approx(0.97)
    assert edge.evidence[0].detail == "Wspólny identyfikator strony zestawu: landing-test"
    assert edge.evidence[0].artifacts == ["a", "b"]
    assert edges_for("b", features, entities, links, cfg) == [edge]
    assert edges_for("missing", features, entities, links, cfg) == []


def test_kit_landing_alone_links_large_campaign(cfg: EdgeConfig) -> None:
    case_ids = [f"case-{i:02d}" for i in range(25)]
    members = case_ids[:6]
    features = [feat(case, "ids.kit_landing", "landing-test") for case in members]
    features += [feat(case, "url.domain", f"{case}.example") for case in case_ids[6:]]
    entities, links = build_entities(features, cfg=cfg)
    edges = build_edges(features, entities, links, cfg)
    assert [(edge.src, edge.dst) for edge in edges] == list(combinations(members, 2))
    assert [edge.score for edge in edges] == pytest.approx([0.97 * 0.75] * len(edges))
    assert sorted(c.case_ids for c in cluster(case_ids, edges, cfg)) == [
        members,
        *[[case] for case in case_ids[6:]],
    ]


def test_stoplisted_cdn_ip_gives_no_edge(cfg: EdgeConfig) -> None:
    features = [feat(case, "infra.ip", "192.0.2.5") for case in ("a", "b")]
    entities, links = build_entities(features, stoplist={"192.0.2.0/24"}, cfg=cfg)
    assert entities == [
        Entity(id="IP:192.0.2.5", type="IP", value="192.0.2.5", tier="operator", df=2, stop=True)
    ]
    assert build_edges(features, entities, links, cfg) == []


def test_default_stoplist_blocks_cdn_ip_and_platform_host() -> None:
    features = [
        feat(case, name, value)
        for case in ("a", "b")
        for name, value in (
            ("infra.ip", "104.16.1.2"),
            ("infra.host_3p", "connect.facebook.net"),
            ("url.domain", "connect.facebook.net"),
            ("url.outlink_domain", "connect.facebook.net"),
            ("infra.redirect_hop", "connect.facebook.net"),
            ("infra.endpoint", "POST connect.facebook.net:443/events"),
        )
    ]
    result = analyze(features)
    assert len(result.entities) == 6
    assert all(entity.stop for entity in result.entities)
    assert result.edges == []
    assert result.operators == {}
    enabled = analyze(features, cfg=EdgeConfig(use_default_stoplist=False))
    assert not any(entity.stop for entity in enabled.entities)
    assert len(enabled.edges) == 1


def test_vector_knn_links_paraphrase_but_not_unrelated(cfg: EdgeConfig) -> None:
    cfg = cfg.model_copy(update={"knn_k": 1})
    # At or above the text hi anchor (0.9) the signal saturates at its weight 0.5, which is
    # exactly what the 0.5 campaign gate (C5) requires.
    cosine = 0.91
    features = [
        feat("a", "text.bge", vector=[1, 0, 0], artifact="text-a", locator="from:text.raw"),
        feat("a", "text.bge", vector=[0, 0, -1]),
        feat("b", "text.bge", vector=[cosine, sqrt(1 - cosine**2), 0], artifact="text-b"),
        feat("c", "text.bge", vector=[0, 1, 0]),
        feat("d", "text.bge", vector=[0, 0, 0]),
        feat("e", "text.bge", vector=[1, 0]),
        feat("f", "img.siglip", vector=[1, 0, 0]),
    ]
    assert candidate_pairs([], [], features, cfg) == {("a", "b")}
    result = analyze(features, cfg=cfg)
    (edge,) = result.edges
    assert (edge.src, edge.dst) == ("a", "b")
    assert edge.comparable == ["text"]
    assert edge.score == pytest.approx(0.5 * min(1.0, (cosine - 0.75) / 0.15))
    assert result == analyze(list(reversed(features)), cfg=cfg)
    (evidence,) = edge.evidence
    assert evidence.artifacts == ["text-a#from:text.raw", "text-b"]
    assert evidence.tier == "campaign"
    assert evidence.value == f"cos {cosine:.2f}"
    assert evidence.detail.startswith("Podobne znaczenie tekstu")
    assert all(len(campaign.case_ids) == 1 for campaign in result.campaigns)


def test_independent_vector_families_create_campaign_edge() -> None:
    features = [
        feat("a", "text.bge", vector=[2, 0]),
        feat("b", "text.bge", vector=[3, 0]),
        feat("a", "img.siglip", vector=[0, 1]),
        feat("b", "img.siglip", vector=[sqrt(1 - 0.965**2), 0.965]),
    ]
    assert analyze(features[:2]).edges[0].score == pytest.approx(0.5)
    result = analyze(features)
    (edge,) = result.edges
    assert edge.comparable == ["image", "text"]
    assert edge.signals == pytest.approx({"image": 0.45 * (0.965 - 0.9) / 0.07, "text": 0.5})
    assert [campaign.case_ids for campaign in result.campaigns] == [["a", "b"]]


def test_screenshot_only_case_cannot_attach_through_a_hub() -> None:
    hub_cases = ["a", "b", "c", *(f"shot-{i:02d}" for i in range(48))]
    features = [feat(case, "img.phash", "be" * 8) for case in hub_cases]
    features += [feat(case, "ids.kit_landing", "landing") for case in ("a", "b", "c")]
    result = analyze(features, ["empty"])
    assert [c.case_ids for c in result.campaigns] == [
        ["a", "b", "c"],
        ["empty"],
        *([case] for case in hub_cases[3:]),
    ]
    assert all(edge.comparable == ["ids", "image"] for edge in result.edges)


def test_siglip_below_new_anchor_contributes_no_evidence(cfg: EdgeConfig) -> None:
    cosine = 0.89
    a = feat("a", "img.siglip", vector=[1, 0])
    b = feat("b", "img.siglip", vector=[cosine, sqrt(1 - cosine**2)])
    assert pair_signals([a], [b], build_context([a, b], [], cfg)) == {}


@pytest.mark.parametrize(
    ("distance", "description"),
    [
        (0, "Identyczny skrót obrazu (odległość 0/256)"),
        (2, "Podobny skrót obrazu (odległość 2/256)"),
    ],
)
def test_image_evidence_describes_hamming_distance_without_redundant_h(
    cfg: EdgeConfig, distance: int, description: str
) -> None:
    left = feat("a", "img.pdq", "0" * 64)
    right = feat("b", "img.pdq", f"{(1 << distance) - 1:064x}")
    _, (evidence,) = pair_signals([left], [right], build_context([left, right], [], cfg))["image"]
    assert evidence.detail == description
    assert evidence.value == f"H {distance}/256"


def test_title_minhash_does_not_claim_whole_page_text(cfg: EdgeConfig) -> None:
    left = feat("a", "text.minhash", vector=[1.0] * cfg.num_perm, locator="title")
    right = feat("b", "text.minhash", vector=[1.0] * cfg.num_perm, locator="title")
    _, (evidence,) = pair_signals([left], [right], build_context([left, right], [], cfg))["text"]
    assert "fragment" in evidence.detail.lower()
    assert "treść tekstu" not in evidence.detail.lower()


def test_domain_evidence_uses_polish_name(cfg: EdgeConfig) -> None:
    features = [feat(case, "url.domain", "synthetic.example") for case in ("a", "b")]
    entities, links = build_entities(features, cfg=cfg)
    (edge,) = build_edges(features, entities, links, cfg)
    assert "domena" in edge.evidence[0].detail.lower()
    assert "url.domain" not in edge.evidence[0].detail


@pytest.mark.parametrize(("name", "bits", "distance"), [("img.phash", 64, 8), ("img.pdq", 256, 38)])
def test_hash_banding_verifies_distances_at_the_anchor(
    cfg: EdgeConfig, name: str, bits: int, distance: int
) -> None:
    a = feat("a", name, "0" * (bits // 4))
    for flips in (distance, distance + 1):
        b = feat("b", name, f"{(1 << flips) - 1:0{bits // 4}x}")
        expected = {("a", "b")} if flips == distance else set()
        assert candidate_pairs([], [], [a, b], cfg) == expected


@pytest.mark.parametrize(
    ("phash", "pdq", "expected"),
    [(4, None, "img.phash"), (20, None, None), (2, 100, None), (2, 6, "img.pdq")],
)
def test_hash_evidence_uses_the_best_cross_pair_and_prefers_pdq(
    cfg: EdgeConfig, phash: int, pdq: int | None, expected: str | None
) -> None:
    a = [feat("a", "img.phash", "f" * 16), feat("a", "img.phash", "0" * 16, artifact="a-best")]
    b = [feat("b", "img.phash", f"{(1 << phash) - 1:016x}")]
    a.append(feat("a", "img.pdq", "0" * 64))
    if pdq is not None:
        b.append(feat("b", "img.pdq", f"{(1 << pdq) - 1:064x}"))
    ctx = build_context(a + b, [], cfg)
    scores = pair_signals(a, b, ctx)
    assert candidate_pairs([], [], a + b, cfg) == ({("a", "b")} if expected else set())
    if expected:
        _, (evidence,) = scores["image"]
        assert evidence.kind == expected
        if expected == "img.phash":
            assert evidence.value == f"H {phash}/64"
            assert evidence.artifacts == ["a-best", "b-capture"]
        else:
            assert evidence.value == f"H {pdq}/256"
            assert evidence.artifacts == ["a-capture", "b-capture"]
    else:
        assert scores == {}


def test_invalid_hashes_are_skipped_at_debug_level(
    cfg: EdgeConfig, caplog: pytest.LogCaptureFixture
) -> None:
    a = [feat("a", "img.phash", value) for value in ("f" * 15, "g" * 16, "+" + "0" * 15)]
    b = [feat("b", "img.phash", "0" * 16)]
    with caplog.at_level(logging.DEBUG):
        assert candidate_pairs([], [], a + b, cfg) == set()
        assert pair_signals(a, b, build_context(a + b, [], cfg)) == {}
    assert "Invalid img.phash hash" in caplog.text


def test_hash_banding_finds_near_duplicate_in_random_hashes(
    cfg: EdgeConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    random = Random(23)
    hashes = [random.getrandbits(64) for _ in range(200)]
    hashes[-1] = hashes[0] ^ sum(1 << bit for bit in (2, 11, 21, 31, 41, 51))
    features = [feat(f"{i:03}", "img.phash", f"{value:016x}") for i, value in enumerate(hashes)]
    checks = 0
    distance = blocking.hash_distance

    def count_distance(a: int, b: int) -> int:
        nonlocal checks
        checks += 1
        return distance(a, b)

    monkeypatch.setattr(blocking, "hash_distance", count_distance)
    assert candidate_pairs([], [], features, cfg) == {("000", "199")}
    assert 0 < checks < len(features) * (len(features) - 1) // 2
    assert candidate_pairs([], [], list(reversed(features)), cfg, case_id="199") == {("000", "199")}


def test_campaign_labels_use_headline_and_person_or_class_keywords() -> None:
    features = [
        feat("a", "person.public_figure", "Jan Kowalski"),
        feat("a", "text.headline_tpl", "wywiad z {PERSON}"),
        feat("b", "text.raw", "apteka apteka suplement zdrowie"),
        feat("c", "text.raw", "lokata lokata oszczędności giełda"),
    ]
    result = analyze(features)
    assert [campaign.label for campaign in result.campaigns] == [
        "wywiad z [osoba]",
        "apteka, suplement, zdrowie",
        "lokata, giełda, oszczędności",
    ]


def test_campaign_label_prefers_page_title_and_does_not_guess_masked_person() -> None:
    features = [
        feat("a", "person.public_figure", "uncertain-person"),
        feat("a", "text.headline_tpl", "sponsorowane obserwuj", locator="from:text.ocr"),
        feat("a", "text.headline_tpl", "rozmowa z {PERSON}", locator="from:html.title"),
        feat("a", "text.raw", "nowy program oszczędnościowy"),
    ]
    [campaign] = analyze(features).campaigns
    assert campaign.label == "rozmowa z [osoba]"
    assert "uncertain-person" not in campaign.label


def test_campaign_label_filters_ocr_chrome_and_stopwords() -> None:
    features = [
        feat("a", "text.headline_tpl", "sponsorowane polub obserwuj", locator="from:text.ocr"),
        feat("a", "text.ocr", "sponsorowane zobacz więcej the you inwestycja inwestycja zysk"),
    ]
    [campaign] = analyze(features).campaigns
    assert "inwestycja" in campaign.label
    assert "sponsorowane" not in campaign.label
    assert "zobacz" not in campaign.label
    assert "the" not in campaign.label


def test_campaign_label_can_use_explicit_ocr_headline() -> None:
    features = [
        feat("a", "text.ocr", "Sponsorowane treść oferty"),
        feat("a", "ocr.headline", "Nowa oferta dla klientów"),
        feat("a", "text.headline_tpl", "nowa oferta dla klientów", locator="from:text.ocr"),
    ]
    [campaign] = analyze(features).campaigns
    assert campaign.label == "nowa oferta dla klientów"


def test_high_df_asset_gives_no_edge(cfg: EdgeConfig) -> None:
    features = [feat(str(i), "asset.sha256", "a" * 64) for i in range(4)]
    features += [feat(str(i), "text.raw", "synthetic text") for i in range(4, 11)]
    entities, links = build_entities([*features, features[0]], cfg=cfg)
    assert entities[0].df == 4
    assert entities[0].stop
    assert len(links) == 4
    assert build_edges(features, entities, links, cfg) == []


def test_landing_domain_and_outlink_do_not_share_entity(cfg: EdgeConfig) -> None:
    features = [
        feat("a", "url.domain", "landing.example"),
        feat("b", "url.outlink_domain", "landing.example"),
    ]
    entities, links = build_entities(features, cfg=cfg)
    assert candidate_pairs(entities, links, features, cfg) == set()


def test_set_signal_weights_rare_assets_and_ignores_stopped_assets(cfg: EdgeConfig) -> None:
    shared, stopped = "a" * 64, "b" * 64
    a = [
        feat("a", "asset.sha256", shared),
        feat("a", "asset.sha256", "c" * 64),
        feat("a", "asset.sha256", stopped),
    ]
    b = [
        feat("b", "asset.sha256", shared),
        feat("b", "asset.sha256", shared, artifact="b-extra"),
        feat("b", "asset.sha256", "d" * 64),
        feat("b", "asset.sha256", stopped),
    ]
    features = a + b + [feat(case, "text.raw", "synthetic") for case in ("c", "d")]
    entities, _ = build_entities(features, stoplist={f"Asset:{stopped}"}, cfg=cfg)
    strength, evidence = pair_signals(a, b, build_context(features, entities, cfg))["asset"]
    containment = log(5 / 2) / (log(5 / 2) + log(5))
    assert strength == pytest.approx(0.9 * (containment - 0.15) / (0.6 - 0.15))
    assert [item.value for item in evidence] == [shared]
    assert evidence[0].artifacts == ["a-capture", "b-capture", "b-extra"]


def test_operator_ids_do_not_merge_campaigns(cfg: EdgeConfig) -> None:
    groups = [[f"{group}-{i}" for i in range(3)] for group in ("a", "b")]
    case_ids = groups[0] + groups[1]
    features = [
        feature
        for group, cases in enumerate(groups)
        for case in cases
        for feature in (
            feat(case, "ids.fb_pixel", "pixel-test"),
            feat(case, "asset.sha256", str(group) * 64),
            feat(case, "text.minhash", vector=[float(group)] * cfg.num_perm),
        )
    ]
    entities, links = build_entities(features, cfg=cfg)
    edges = build_edges(features, entities, links, cfg)
    campaigns = cluster(case_ids, edges, cfg)
    assert sorted(campaign.case_ids for campaign in campaigns) == groups
    by_case = operators(case_ids, entities, links)
    assert set(by_case) == set(case_ids)
    assert len(set(by_case.values())) == 1
    assert all(edge.operator_link for edge in edges)
    assert all(edge.src[0] == edge.dst[0] for edge in edges)


def test_a_and_b_share_operator_but_stay_separate(cfg: EdgeConfig) -> None:
    groups = [[f"{group}-{i}" for i in range(3)] for group in ("a", "b")]
    case_ids = groups[0] + groups[1]
    features = [
        feature
        for group, cases in enumerate(groups)
        for case in cases
        for feature in (
            feat(case, "ids.kit_tenant", "tenant-test"),
            feat(case, "ids.fb_pixel", "pixel-test"),
            feat(case, "infra.endpoint", "collector.example/submit"),
            feat(case, "brand.impersonated", "brand-test"),
            feat(case, "asset.sha256", str(group) * 64),
            feat(case, "text.minhash", vector=[float(group)] * cfg.num_perm),
            feat(
                case,
                "html.css_minhash",
                vector=[0.0] * 77 + [float(group + 1)] * (cfg.num_perm - 77),
            ),
        )
    ]
    # Background cases keep corroborating keys below the document-frequency stop limit.
    features += [feat(f"background-{i}", "text.raw", f"synthetic text {i}") for i in range(34)]
    entities, links = build_entities(features, cfg=cfg)
    assert (groups[0][0], groups[1][0]) in candidate_pairs(entities, links, features, cfg)
    edges = build_edges(features, entities, links, cfg)
    assert [(edge.src, edge.dst) for edge in edges] == [
        pair for group in groups for pair in combinations(group, 2)
    ]
    assert sorted(c.case_ids for c in cluster(case_ids, edges, cfg)) == groups
    by_case = operators(case_ids, entities, links)
    assert set(by_case) == set(case_ids)
    assert len(set(by_case.values())) == 1


def test_corroboration_without_campaign_evidence_gives_no_edge(cfg: EdgeConfig) -> None:
    features = [
        feat(case, name, value)
        for case in ("a", "b")
        for name, value in (
            ("ids.fb_pixel", "pixel-test"),
            ("brand.impersonated", "brand-test"),
            ("url.schema", "/{id}"),
        )
    ]
    entities, links = build_entities(features, cfg=cfg)
    assert build_edges(features, entities, links, cfg) == []


def test_fuse_rules(cfg: EdgeConfig) -> None:
    features = [
        feat(case, name, value)
        for case in ("a", "b")
        for name, value in (
            ("ids.kit_landing", "landing-test"),
            ("ids.fb_pixel", "px"),
            ("ids.gtag", "gt"),
            ("infra.endpoint", "collector.example/submit"),
            ("url.schema", "/{id}"),
            ("kit.sdk", "sdk-test"),
            ("person.public_figure", "person-test"),
            ("text.topic", "topic-test"),
            ("text.headline_tpl", "szokujące wyznanie znanego prezentera telewizji"),
        )
    ]
    entities, links = build_entities(features, cfg=cfg)
    (edge,) = build_edges(features, entities, links, cfg)
    assert edge.signals == pytest.approx(
        {"ids": 0.97, "infra": 0.4, "template": 0.25, "person": 0.35, "text": 0.6}
    )
    slots = slot_signals(edge.evidence)
    assert slots == pytest.approx(
        {"ids": 0.97, "text": 0.6, "operator": 0.4, "toolkit": 0.25, "context": 0.35}
    )
    assert edge.score == pytest.approx(1 - 0.03 * 0.4 * 0.6 * 0.75 * 0.65)
    assert edge.score == fuse(slots, cfg)


def test_worked_checks_from_plan(cfg: EdgeConfig) -> None:
    operator_only = [feat(case, "ids.fb_pixel", "px") for case in ("a", "b")]
    entities, links = build_entities(operator_only, cfg=cfg)
    assert build_edges(operator_only, entities, links, cfg) == []

    matching = [
        *operator_only,
        feat("a", "asset.sha256", "a" * 64),
        feat("b", "asset.sha256", "a" * 64),
        feat("a", "text.minhash", vector=[1.0] * cfg.num_perm),
        feat("b", "text.minhash", vector=[1.0] * 72 + [2.0] * (cfg.num_perm - 72)),
        feat("a", "text.headline_tpl", "szokujące wyznanie znanego prezentera telewizji"),
        feat("b", "text.headline_tpl", "szokujące wyznanie znanego prezentera telewizji"),
    ]
    entities, links = build_entities(matching, cfg=cfg)
    (edge,) = build_edges(matching, entities, links, cfg)
    assert edge.signals == pytest.approx({"ids": 0.4, "asset": 0.9, "text": 0.6})
    assert edge.score > 0.9

    a, b = ([feat(case, "person.public_figure", "person-test")] for case in ("a", "b"))
    entities, _ = build_entities(a + b, cfg=cfg)
    _, person = pair_signals(a, b, build_context(a + b, entities, cfg))["person"]
    assert fuse(slot_signals(person), cfg) < cfg.tau
    # Semantic text enters the worked example as evidence because vector scoring is pending.
    semantic = Evidence(
        family="text", tier="campaign", kind="text.bge", value="", detail="", weight=0.5
    )
    (operator,) = (item for item in edge.evidence if item.tier == "operator")
    score = fuse(slot_signals([*person, semantic, operator]), cfg)
    assert score == pytest.approx(0.805)
    assert score > cfg.tau


def test_operator_families_alone_do_not_create_campaign_edge(cfg: EdgeConfig) -> None:
    features = [
        feat(case, name, value)
        for case in ("a", "b")
        for name, value in (
            ("ids.fb_pixel", "px"),
            ("infra.endpoint", "collector.example/submit"),
        )
    ]
    entities, links = build_entities(features, cfg=cfg)
    contributions = pair_signals(features[:2], features[2:], build_context(features, entities, cfg))
    assert {family: weight for family, (weight, _) in contributions.items()} == pytest.approx(
        {"ids": 0.4, "infra": 0.4}
    )
    assert slot_signals([item for _, items in contributions.values() for item in items]) == {
        "operator": 0.4
    }
    assert build_edges(features, entities, links, cfg) == []
    assert len(set(operators(["a", "b"], entities, links).values())) == 1


def dense_groups() -> tuple[list[list[str]], list[Edge]]:
    groups = [[f"{group}-{i}" for i in range(10)] for group in ("a", "b")]
    edges = [make_edge(a, b, 0.95) for group in groups for a, b in combinations(group, 2)]
    edges.append(make_edge(groups[0][0], groups[1][0], 0.6))
    return groups, edges


def make_edge(a: str, b: str, score: float) -> Edge:
    return Edge(
        src=a, dst=b, score=score, operator_link=False, signals={}, comparable=[], evidence=[]
    )


def test_two_dense_groups_one_bridge(cfg: EdgeConfig) -> None:
    groups, edges = dense_groups()
    assert [
        c.case_ids
        for c in cluster(
            groups[0] + groups[1],
            edges,
            cfg.model_copy(update={"giant_min_size": 19, "giant_cohesion": 0.95}),
        )
    ] == groups


def test_single_weak_signal_stays_singleton(cfg: EdgeConfig) -> None:
    features = [feat(case, "person.public_figure", "person-test") for case in ("a", "b")]
    entities, links = build_entities(features, cfg=cfg)
    edges = build_edges(features, entities, links, cfg)
    assert edges == []
    assert sorted(c.case_ids for c in cluster(["a", "b", "c"], edges, cfg)) == [["a"], ["b"], ["c"]]


def test_absent_family_is_not_penalised(cfg: EdgeConfig) -> None:
    features = [
        feat("a", "img.phash", "ab" * 8),
        feat("b", "img.phash", "ab" * 8),
        feat("a", "person.public_figure", "person-test"),
        feat("b", "person.public_figure", "person-test"),
        feat("a", "infra.endpoint", "collector.example/collect"),
        feat("a", "text.raw", "synthetic A"),
        feat("b", "text.raw", "synthetic B"),
    ]
    entities, links = build_entities(features, cfg=cfg)
    (edge,) = build_edges(features, entities, links, cfg)
    assert edge.comparable == ["image", "person"]
    assert edge.score == pytest.approx(fuse({"image": 0.8, "context": 0.35}, cfg))


def test_deterministic_campaign_ids(cfg: EdgeConfig) -> None:
    groups, edges = dense_groups()
    case_ids = groups[0] + groups[1] + ["solo"]
    result = cluster(case_ids, edges, cfg)
    Random(7).shuffle(case_ids)
    Random(11).shuffle(edges)
    assert cluster(case_ids, edges, cfg) == result


def test_unknown_feature_name_is_ignored(cfg: EdgeConfig, caplog: pytest.LogCaptureFixture) -> None:
    features = [feat(case, "unknown.name", "unknown-value") for case in ("a", "b")]
    with caplog.at_level(logging.WARNING):
        entities, links = build_entities(features, cfg=cfg)
        assert build_edges(features, entities, links, cfg) == []
    assert "unknown.name" in caplog.text
    assert "unknown-value" not in caplog.text


@pytest.mark.parametrize("missing_leiden", [False, True])
def test_louvain_fallback_matches_on_clear_groups(
    cfg: EdgeConfig, monkeypatch: pytest.MonkeyPatch, missing_leiden: bool
) -> None:
    groups, edges = dense_groups()
    expected = cluster(groups[0] + groups[1], edges, cfg)
    if missing_leiden:
        monkeypatch.setitem(sys.modules, "leidenalg", None)
    else:
        cfg = cfg.model_copy(update={"cluster_algo": "louvain"})
    assert cluster(groups[0] + groups[1], edges, cfg) == expected


def test_minhash_lsh_and_best_cross_pair(cfg: EdgeConfig) -> None:
    features = [
        feat("a", "text.minhash", artifact="a1", vector=[1.0] * cfg.num_perm),
        feat("a", "text.minhash", artifact="a2", vector=[2.0] * cfg.num_perm),
        feat("b", "text.minhash", artifact="b1", vector=[2.0] * cfg.num_perm),
        feat("c", "text.minhash", vector=[3.0] * cfg.num_perm),
        feat("d", "html.dom_minhash", vector=[2.0] * cfg.num_perm),
    ]
    assert candidate_pairs([], [], features, cfg) == {("a", "b")}
    (edge,) = build_edges(features, [], [], cfg)
    assert edge.signals == pytest.approx({"text": 0.85})
    assert edge.evidence[0].artifacts == ["a2", "b1"]


def test_dom_tier_changes_at_campaign_anchor(cfg: EdgeConfig) -> None:
    a = feat("a", "html.dom_minhash", vector=[1.0] * cfg.num_perm)
    b = feat("b", "html.dom_minhash", vector=[1.0] * 108 + [2.0] * (cfg.num_perm - 108))
    low = pair_signals([a], [b], build_context([a, b], [], cfg))["template"]
    assert low[0] == 0.25
    assert low[1][0].tier == "toolkit"
    b.vector = [1.0] * cfg.num_perm
    high = pair_signals([a], [b], build_context([a, b], [], cfg))["template"]
    assert high[0] == 0.5
    assert high[1][0].tier == "campaign"


def test_review_edge_survives_scoring_but_not_clustering(cfg: EdgeConfig) -> None:
    cfg = cfg.model_copy(update={"min_campaign_evidence": 0.5})
    features = [
        feature
        for case in ("a", "b")
        for feature in (
            feat(case, "html.dom_minhash", vector=[1.0] * cfg.num_perm),
            feat(case, "person.public_figure", f"person-{case}"),
        )
    ]
    entities, links = build_entities(features, cfg=cfg)
    (edge,) = build_edges(features, entities, links, cfg)
    assert edge.score == pytest.approx(0.5)
    assert sorted(c.case_ids for c in cluster(["a", "b"], [edge], cfg)) == [["a"], ["b"]]
    stricter = cfg.model_copy(update={"min_campaign_evidence": 0.51})
    assert build_edges(features, entities, links, stricter) == []
    features += [feat("a", "img.phash", "a"), feat("b", "img.phash", "b")]
    entities, links = build_entities(features, cfg=cfg)
    assert build_edges(features, entities, links, cfg) == []


def test_operator_union_and_overlapping_toolkits(cfg: EdgeConfig) -> None:
    features: list[Feature] = [
        feat(case, name, value)
        for name, value, cases in (
            ("ids.fb_pixel", "px-one", "ab"),
            ("infra.endpoint", "collector.example/submit", "bc"),
            ("ids.gtag", "gt-two", "de"),
            ("kit.sdk", "sdk-x", "ab"),
            ("url.schema", "/{id}", "bc"),
        )
        for case in cases
    ]
    entities, links = build_entities(features, cfg=cfg)
    case_ids = list("abcdef")
    by_case = operators(case_ids, entities, links)
    assert by_case["a"] == by_case["b"] == by_case["c"]
    assert by_case["d"] == by_case["e"] != by_case["a"]
    assert "f" not in by_case
    assert len(toolkits(case_ids, entities, links)["b"]) == 2
    campaigns = cluster(case_ids, [make_edge("a", "d", 1), make_edge("b", "f", 1)], cfg)
    attach_operators(campaigns, by_case)
    by_members = {tuple(c.case_ids): c for c in campaigns}
    assert by_members["a", "d"].flags == ["mixed_operator"]
    assert by_members["a", "d"].operator_id is None
    assert by_members["b", "f"].operator_id == by_case["b"]


def test_giant_guard_flags_second_partition(cfg: EdgeConfig) -> None:
    cfg = cfg.model_copy(update={"tau": 0.3, "resolution": 0.01})
    cases = [f"case-{i:02d}" for i in range(51)]
    groups = [cases[:26], cases[26:]]
    edges = [make_edge(a, b, 0.4) for group in groups for a, b in combinations(group, 2)]
    edges += [make_edge(cases[i], cases[26 + i], 0.4) for i in range(4)]
    unguarded = cfg.model_copy(update={"giant_min_size": 51})
    assert [c.case_ids for c in cluster(cases, edges, unguarded)] == [cases]
    campaigns = cluster(cases, edges, cfg)
    assert [c.case_ids for c in campaigns] == groups
    assert all(c.flags == ["giant_split"] for c in campaigns)


def test_identical_template_with_unrelated_text_gives_no_edge(cfg: EdgeConfig) -> None:
    features = [
        feat("a", "html.dom_minhash", vector=[1.0] * cfg.num_perm),
        feat("b", "html.dom_minhash", vector=[1.0] * cfg.num_perm),
        feat("a", "text.minhash", vector=[1.0] * cfg.num_perm),
        feat("b", "text.minhash", vector=[2.0] * cfg.num_perm),
        feat("a", "ids.fb_pixel", "px"),
        feat("b", "ids.fb_pixel", "px"),
    ]
    entities, links = build_entities(features, cfg=cfg)
    assert build_edges(features, entities, links, cfg) == []


def test_identical_template_anchors_edge_when_text_is_not_comparable(cfg: EdgeConfig) -> None:
    features = [
        feat("a", "html.dom_minhash", vector=[1.0] * cfg.num_perm),
        feat("b", "html.dom_minhash", vector=[1.0] * cfg.num_perm),
        feat("a", "text.minhash", vector=[1.0] * cfg.num_perm),
    ]
    entities, links = build_entities(features, cfg=cfg)
    (edge,) = build_edges(features, entities, links, cfg)
    assert "text" not in edge.comparable


def test_single_shared_common_file_is_not_campaign_evidence(cfg: EdgeConfig) -> None:
    kit = "k" * 64
    features = [feat(case, "asset.sha256", kit) for case in ("a", "b", "c")]
    features += [feat(case, "asset.sha256", case * 64) for case in ("a", "b", "c")]
    features += [feat(case, "url.domain", f"{case}.example") for case in "defghij"]
    entities, links = build_entities(features, cfg=cfg)
    assert build_edges(features, entities, links, cfg) == []


def test_single_shared_rare_file_still_counts(cfg: EdgeConfig) -> None:
    rare = "r" * 64
    features = [feat(case, "asset.sha256", rare) for case in ("a", "b")]
    features += [feat(case, "url.domain", f"{case}.example") for case in "cdefgh"]
    entities, links = build_entities(features, cfg=cfg)
    (edge,) = build_edges(features, entities, links, cfg)
    assert edge.signals["asset"] > 0.6
