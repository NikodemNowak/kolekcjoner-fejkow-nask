"""Fuses per-pair signals into weighted edges between cases.

Combines signal scores into a single edge score, applies the campaign gate, and emits
the edges consumed by clustering.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping
from math import prod

from fakecollector.core.registry import FEATURES, FeatureSpec
from fakecollector.core.schemas import Edge, Entity, Evidence, Feature
from fakecollector.graph.blocking import CasePair, candidate_pairs
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import EntityLink
from fakecollector.graph.signals import (
    build_context,
    comparable_families,
    evidence_order,
    pair_signals,
)


def fuse(signals: Mapping[str, float], cfg: EdgeConfig) -> float:
    """Compute noisy-OR over probabilities, clipped to the unit interval."""
    score = 1.0 - prod(1.0 - p for _, p in sorted(signals.items()))
    return max(0.0, min(1.0, score))


def slot_signals(evidence: Collection[Evidence]) -> dict[str, float]:
    """Pool corroborating evidence by tier so its cap holds across families."""
    slots: dict[str, float] = {}
    for item in evidence:
        slot = item.family if item.tier == "campaign" else item.tier
        slots[slot] = max(slots.get(slot, 0.0), item.weight)
    return slots


def passes_campaign_gate(edge: Edge, cfg: EdgeConfig) -> bool:
    """Require campaign evidence that can anchor a confirmed link."""
    # Comparable but unrelated text makes a shared template evidence of a kit.
    template_needs_text = "text" in edge.comparable and "text" not in edge.signals
    return any(
        item.tier == "campaign"
        and item.weight >= cfg.min_campaign_evidence
        and not (template_needs_text and item.family == "template")
        for item in edge.evidence
    )


def build_edges(
    features: Collection[Feature],
    entities: Collection[Entity],
    links: Collection[EntityLink],
    cfg: EdgeConfig,
    registry: Mapping[str, FeatureSpec] = FEATURES,
    *,
    case_ids: Collection[str] = (),
    pairs: Collection[CasePair] | None = None,
) -> list[Edge]:
    """Project candidate pairs into campaign and review edges, with review scores below tau."""
    return _build_edges(features, entities, links, cfg, registry, case_ids=case_ids, pairs=pairs)


def edges_for(
    case_id: str,
    features: Collection[Feature],
    entities: Collection[Entity],
    links: Collection[EntityLink],
    cfg: EdgeConfig,
    registry: Mapping[str, FeatureSpec] = FEATURES,
    *,
    case_ids: Collection[str] = (),
    pairs: Collection[CasePair] | None = None,
    keep_subthreshold: bool = False,
) -> list[Edge]:
    """Score incident pairs, optionally retaining all comparable pairs for assignment."""
    return _build_edges(
        features,
        entities,
        links,
        cfg,
        registry,
        case_id=case_id,
        case_ids=case_ids,
        pairs=pairs,
        keep_subthreshold=keep_subthreshold,
    )


def _build_edges(
    features: Collection[Feature],
    entities: Collection[Entity],
    links: Collection[EntityLink],
    cfg: EdgeConfig,
    registry: Mapping[str, FeatureSpec],
    *,
    case_id: str | None = None,
    case_ids: Collection[str] = (),
    pairs: Collection[CasePair] | None = None,
    keep_subthreshold: bool = False,
) -> list[Edge]:
    ctx = build_context(features, entities, cfg, registry, case_ids=case_ids)
    by_case: dict[str, list[Feature]] = defaultdict(list)
    for feature in features:
        if feature.name in registry:
            by_case[feature.case_id].append(feature)

    operator_entities = {
        entity.id for entity in entities if entity.tier == "operator" and not entity.stop
    }
    operators_by_case: dict[str, set[str]] = defaultdict(set)
    for linked_case, entity_id, _ in links:
        if entity_id in operator_entities:
            operators_by_case[linked_case].add(entity_id)

    edges: list[Edge] = []
    if pairs is None:
        pairs = candidate_pairs(
            entities, links, features, cfg, registry, case_id=case_id, case_ids=case_ids
        )
    for src, dst in sorted(pairs):
        if case_id is not None and case_id not in (src, dst):
            continue
        a, b = by_case[src], by_case[dst]
        contributions = pair_signals(a, b, ctx)
        evidence = [item for _, items in contributions.values() for item in items]
        comparable = comparable_families(a, b, registry)
        if not comparable:
            continue
        score = fuse(slot_signals(evidence), cfg)
        edge = Edge(
            src=src,
            dst=dst,
            score=score,
            operator_link=not operators_by_case[src].isdisjoint(operators_by_case[dst]),
            signals={family: p for family, (p, _) in contributions.items()},
            comparable=comparable,
            evidence=sorted(evidence, key=evidence_order),
        )
        if not keep_subthreshold:
            if not passes_campaign_gate(edge, cfg):
                continue
            if score < cfg.tau and (len(comparable) > 2 or score < cfg.tau - cfg.review_band):
                continue
        edges.append(edge)
    return edges
