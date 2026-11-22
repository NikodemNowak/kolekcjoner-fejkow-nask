"""Data behind the "Powiązania" page: how one case links to others, family by family.

Pure functions over an `Analysis`, so the page stays thin and the logic is unit-tested.
A family that both sides could not provide is "no data" (None), never 0: absent is not
dissimilar.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import get_args

from fakecollector.app.display import display_campaign_label, display_evidence
from fakecollector.core.schemas import Edge, Family
from fakecollector.graph.analyze import Analysis

FAMILY_ORDER: tuple[Family, ...] = get_args(Family)

# Colour-blind safe (Okabe-Ito), one per family, used by the graph and the table legend.
FAMILY_COLOURS: dict[str, str] = {
    "ids": "#D55E00",
    "infra": "#CC79A7",
    "asset": "#E69F00",
    "template": "#0072B2",
    "image": "#009E73",
    "text": "#56B4E9",
    "person": "#000000",
    "meta": "#F0E442",
}
MAX_EVIDENCE = 3


@dataclass
class NeighbourRow:
    """One case linked to the selected case."""

    case_id: str
    score: float
    campaign_label: str
    operator_link: bool
    fired: list[str]  # families with a positive signal, in FAMILY_ORDER
    per_family: dict[str, float | None] = field(default_factory=dict)  # None = no data
    evidence: list[str] = field(default_factory=list)  # Polish details, strongest first


def _other(edge: Edge, case_id: str) -> str | None:
    if edge.src == case_id:
        return edge.dst
    if edge.dst == case_id:
        return edge.src
    return None


def neighbour_rows(
    analysis: Analysis,
    case_id: str,
    families: Collection[str] | None = None,
    min_families: int = 1,
) -> list[NeighbourRow]:
    """Linked cases of `case_id`, most families first, then by fused score.

    Args:
        analysis: The run's graph.
        case_id: The selected case.
        families: Keep only links where at least one of these families fired.
        min_families: Keep only links where at least this many families fired.
    """
    label = {cid: display_campaign_label(c.label) for c in analysis.campaigns for cid in c.case_ids}
    rows = []
    for edge in analysis.edges:
        other = _other(edge, case_id)
        if other is None:
            continue
        comparable = set(edge.comparable)
        # Only families both sides could provide count: a signal outside `comparable` is
        # "no data", never evidence (absent is not dissimilar, and not similar either).
        fired: list[str] = [
            f for f in FAMILY_ORDER if f in comparable and edge.signals.get(f, 0.0) > 0.0
        ]
        if len(fired) < min_families or (families and not set(fired) & set(families)):
            continue
        per_family: dict[str, float | None] = {
            f: (edge.signals.get(f, 0.0) if f in comparable else None) for f in FAMILY_ORDER
        }
        evidence = [display_evidence(e) for e in sorted(edge.evidence, key=lambda e: -e.weight)]
        rows.append(
            NeighbourRow(
                case_id=other,
                score=edge.score,
                campaign_label=label.get(other, ""),
                operator_link=edge.operator_link,
                fired=fired,
                per_family=per_family,
                evidence=evidence[:MAX_EVIDENCE],
            )
        )
    rows.sort(key=lambda r: (-len(r.fired), -r.score, r.case_id))
    return rows


def linked_subgraph(
    analysis: Analysis,
    case_id: str,
    rows: list[NeighbourRow],
    families: Collection[str] | None = None,
) -> Analysis:
    """Build a graph of the selected case and visible direct neighbours."""
    neighbors = {row.case_id for row in rows}
    selected = {case_id, *neighbors}
    edges = []
    for edge in analysis.edges:
        if _other(edge, case_id) not in neighbors:
            continue
        if families:
            edge = edge.model_copy(
                update={
                    "signals": {
                        key: value for key, value in edge.signals.items() if key in families
                    },
                    "comparable": [key for key in edge.comparable if key in families],
                    "evidence": [item for item in edge.evidence if item.family in families],
                }
            )
        edges.append(edge)
    links = [link for link in analysis.links if link[0] in selected]
    cases_by_entity: dict[str, set[str]] = {}
    for case, entity, _ in links:
        cases_by_entity.setdefault(entity, set()).add(case)
    entities = [
        entity.model_copy(update={"df": len(cases_by_entity[entity.id])})
        for entity in analysis.entities
        if entity.id in cases_by_entity
    ]
    return analysis.model_copy(
        update={
            "case_ids": sorted(selected),
            "edges": edges,
            "links": links,
            "entities": entities,
        }
    )
