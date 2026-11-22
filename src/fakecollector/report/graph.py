"""Build safe, self-contained graph views for reports and analyst interfaces."""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from typing import Literal, get_args

from jinja2 import Environment, select_autoescape
from pydantic import BaseModel, Field

from fakecollector.app.display import display_evidence, display_value
from fakecollector.app.links import FAMILY_COLOURS
from fakecollector.core.schemas import Family, Tier
from fakecollector.graph.analyze import Analysis

_DOMAIN = re.compile(r"(?i)\b([a-z0-9-]+(?:\.[a-z0-9-]+)*)(\.)([a-z][a-z0-9-]{1,62})\b")


def defang(value: str) -> str:
    """Make domain-like strings non-clickable without changing their displayed meaning."""
    return _DOMAIN.sub(lambda match: f"{match[1].replace('.', '[.]')}[.]{match[3]}", value)


def _node_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", "backslashreplace")).hexdigest()
    return f"{kind}:{digest}"


def _short_label(value: str) -> str:
    return value if len(value) <= 32 else value[:31] + "…"


_HEX_RUN = re.compile(r"\b[0-9a-f]{16,}\b", re.I)


def _entity_label(value: str) -> str:
    """Hashes and long IDs shortened to their first characters; the tooltip keeps all."""
    return _short_label(_HEX_RUN.sub(lambda m: m[0][:10] + "…", value))


# Node fills: light colours, so they never look like the family edge colours (Okabe-Ito).
CAMPAIGN_FILLS = (
    "#93c5fd",
    "#fca5a5",
    "#86efac",
    "#fde68a",
    "#c4b5fd",
    "#f9a8d4",
    "#a5f3fc",
    "#d9f99d",
    "#fed7aa",
    "#bfdbfe",
)
SINGLETON_FILL = "#e5e7eb"


def campaign_fills(analysis: Analysis) -> dict[str, str]:
    """Case id -> node fill: one colour per multi-case campaign (largest first), grey alone."""
    ranked = sorted(
        (c for c in analysis.campaigns if len(c.case_ids) > 1),
        key=lambda c: (-len(c.case_ids), c.id),
    )
    fills = {
        case: CAMPAIGN_FILLS[i % len(CAMPAIGN_FILLS)]
        for i, campaign in enumerate(ranked)
        for case in campaign.case_ids
    }
    return {case: fills.get(case, SINGLETON_FILL) for case in analysis.case_ids}


class GraphNode(BaseModel):
    """A case or entity in a graph view."""

    id: str
    label: str
    full_label: str
    kind: Literal["case", "entity"]
    tier: Tier | None = None
    fill: str = SINGLETON_FILL  # campaign colour of a case node
    linked: bool = False  # a case with at least one drawn edge (singletons are drawn small)
    focus: bool = False  # the case the analyst selected (centre of the ego view)
    df: int = 0  # number of cases sharing an entity (node size)


class GraphLink(BaseModel):
    """One visual edge with evidence and an optional signal family."""

    id: str
    source: str
    target: str
    family: Family | None = None
    score: float | None = None
    evidence: list[str] = Field(default_factory=list)


class GraphData(BaseModel):
    """Nodes and edges for one interactive view."""

    nodes: list[GraphNode]
    edges: list[GraphLink]


class GraphLabels(BaseModel):
    """Localized labels supplied by the calling interface."""

    case_view: str
    entity_view: str
    evidence: str
    family_names: dict[str, str] = Field(default_factory=dict)
    tier_names: dict[str, str] = Field(default_factory=dict)


def build_case_graph(analysis: Analysis, focus: str | None = None) -> GraphData:
    """Return one edge per fired, comparable signal family."""
    fills = campaign_fills(analysis)
    linked = {edge.src for edge in analysis.edges} | {edge.dst for edge in analysis.edges}
    nodes = [
        GraphNode(
            id=_node_id("case", case),
            label=_short_label(defang(case)),
            full_label=defang(case),
            kind="case",
            fill=fills[case],
            linked=case in linked,
            focus=case == focus,
        )
        for case in analysis.case_ids
    ]
    edges: list[GraphLink] = []
    for edge in analysis.edges:
        for family, score in sorted(edge.signals.items()):
            if family not in edge.comparable or score <= 0:
                continue
            edges.append(
                GraphLink(
                    id=f"case-edge:{len(edges)}",
                    source=_node_id("case", edge.src),
                    target=_node_id("case", edge.dst),
                    family=family,
                    score=score,
                    evidence=[
                        defang(display_evidence(item))
                        for item in edge.evidence
                        if item.family == family
                    ],
                )
            )
    return GraphData(nodes=nodes, edges=edges)


def build_entity_graph(analysis: Analysis, focus: str | None = None) -> GraphData:
    """Return case-to-entity edges for shared, non-stopped entities."""
    active = {
        entity.id: entity for entity in analysis.entities if entity.df >= 2 and not entity.stop
    }
    fills = campaign_fills(analysis)
    with_entities = {case for case, entity, _ in analysis.links if entity in active}
    nodes = [
        GraphNode(
            id=_node_id("case", case),
            label=_short_label(defang(case)),
            full_label=defang(case),
            kind="case",
            fill=fills[case],
            linked=case in with_entities,
            focus=case == focus,
        )
        for case in analysis.case_ids
        # Cases sharing nothing are already visible in the case view; here they are noise.
        if case in with_entities or case == focus
    ]
    nodes.extend(
        GraphNode(
            id=_node_id("entity", entity.id),
            label=_entity_label(defang(display_value(entity.type, entity.value))),
            full_label=defang(display_value(entity.type, entity.value)),
            kind="entity",
            tier=entity.tier,
            df=entity.df,
        )
        for entity in active.values()
    )
    pairs = sorted({(case, entity) for case, entity, _ in analysis.links if entity in active})
    edges = [
        GraphLink(
            id=f"entity-edge:{index}",
            source=_node_id("case", case),
            target=_node_id("entity", entity),
        )
        for index, (case, entity) in enumerate(pairs)
    ]
    return GraphData(nodes=nodes, edges=edges)


def render_graph(
    analysis: Analysis, labels: GraphLabels, focus: str | None = None, compact: bool = False
) -> str:
    """Render both graph views with vendored JavaScript and no network access.

    Args:
        analysis: The (sub)graph to draw.
        labels: Localized UI strings.
        focus: A case to put in the centre (ego view of one case and its neighbours).
        compact: Embedded in a page that has its own family filter and legend.
    """
    package = files("fakecollector.report")
    template = package.joinpath("templates", "graph.html.j2").read_text(encoding="utf-8")
    library = package.joinpath("static", "cytoscape.min.js").read_text(encoding="utf-8")
    data = {
        "cases": build_case_graph(analysis, focus).model_dump(mode="json"),
        "entities": build_entity_graph(analysis, focus).model_dump(mode="json"),
    }
    payload = (
        json.dumps(data, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    environment = Environment(autoescape=select_autoescape(default=True))
    return environment.from_string(template).render(
        labels=labels,
        graph_data=payload,
        family_names=json.dumps(labels.family_names, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026"),
        library=library,
        families=get_args(Family),
        family_colours=FAMILY_COLOURS,
        focused=focus is not None,
        compact=compact,
    )
