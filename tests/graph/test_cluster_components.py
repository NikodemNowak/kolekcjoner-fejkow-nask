from __future__ import annotations

import sys
from itertools import combinations
from random import Random

import pytest

from fakecollector.core.schemas import Edge
from fakecollector.graph.cluster import cluster
from fakecollector.graph.config import EdgeConfig


def _edge(src: str, dst: str, score: float) -> Edge:
    return Edge(
        src=src,
        dst=dst,
        score=score,
        operator_link=False,
        signals={},
        comparable=[],
        evidence=[],
    )


def test_extra_cases_sharing_one_domain_do_not_split_campaign(cfg: EdgeConfig) -> None:
    clique = [f"clique-{i}" for i in range(6)]
    extras = ["extra-a", "extra-b"]
    edges = [_edge(a, b, 1.0) for a, b in combinations(clique, 2)]
    # Each extra case has just one domain-based edge into the clique.
    edges += [_edge(clique[-1], extra, 0.9) for extra in extras]

    campaigns = cluster(clique + extras, edges, cfg)

    assert any(set(clique).issubset(campaign.case_ids) for campaign in campaigns)


@pytest.mark.parametrize("missing_leiden", [False, True])
def test_two_dense_groups_one_weak_bridge_still_split_when_giant(
    cfg: EdgeConfig, monkeypatch: pytest.MonkeyPatch, missing_leiden: bool
) -> None:
    left = [f"left-{i}" for i in range(4)]
    right = [f"right-{i}" for i in range(4)]
    edges = [_edge(a, b, 0.8) for group in (left, right) for a, b in combinations(group, 2)]
    edges.append(_edge(left[-1], right[0], cfg.tau))

    assert [campaign.case_ids for campaign in cluster(left + right, edges, cfg)] == [left + right]

    guarded = cfg.model_copy(update={"giant_min_size": 6, "giant_cohesion": 0.85})
    if missing_leiden:
        monkeypatch.setitem(sys.modules, "leidenalg", None)
    campaigns = cluster(left + right, edges, guarded)

    assert [campaign.case_ids for campaign in campaigns] == [left, right]
    assert all(campaign.flags == ["giant_split"] for campaign in campaigns)
    assert all(campaign.cohesion == 0.8 for campaign in campaigns)


def test_components_are_deterministic(cfg: EdgeConfig) -> None:
    cases = ["a", "b", "c", "d", "e", "isolated"]
    edges = [
        _edge("a", "b", 1.0),
        _edge("b", "c", cfg.tau),
        _edge("c", "d", cfg.tau - 0.01),
        _edge("d", "e", 1.0),
    ]
    expected = cluster(cases, edges, cfg)

    assert [campaign.case_ids for campaign in expected] == [
        ["a", "b", "c"],
        ["d", "e"],
        ["isolated"],
    ]
    rng = Random(7)
    rng.shuffle(cases)
    rng.shuffle(edges)

    assert cluster(cases, edges, cfg) == expected


def test_component_mixing_two_operators_is_partitioned(cfg: EdgeConfig) -> None:
    left = [f"left-{i}" for i in range(4)]
    right = [f"right-{i}" for i in range(4)]
    edges = [_edge(a, b, 1.0) for group in (left, right) for a, b in combinations(group, 2)]
    # One multi-story capture (e.g. a cloaked case) links the two campaigns above tau.
    edges.append(_edge(left[0], right[0], 0.7))
    by_operator = {case: "O-left" for case in left} | {case: "O-right" for case in right}

    merged = cluster(left + right, edges, cfg)
    split = cluster(left + right, edges, cfg, by_operator)

    assert [c.case_ids for c in merged] == [sorted(left + right)]
    assert sorted(c.case_ids for c in split) == [sorted(left), sorted(right)]
    assert all("operator_split" in c.flags for c in split)


def test_component_with_one_operator_is_not_partitioned(cfg: EdgeConfig) -> None:
    clique = [f"clique-{i}" for i in range(6)]
    extras = ["extra-a", "extra-b"]
    edges = [_edge(a, b, 1.0) for a, b in combinations(clique, 2)]
    edges += [_edge(clique[-1], extra, 0.9) for extra in extras]
    by_operator = {case: "O-1" for case in clique}

    campaigns = cluster(clique + extras, edges, cfg, by_operator)

    assert [c.case_ids for c in campaigns] == [sorted(clique + extras)]
