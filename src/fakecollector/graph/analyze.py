"""Top-level campaign analysis: build entities and edges, cluster cases, label campaigns.

The `analyze` function is the single entry point combining the graph steps into an
`Analysis` result.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from fakecollector.core.schemas import Campaign, Edge, Entity, Feature
from fakecollector.graph.cluster import (
    attach_operators,
    attach_toolkits,
    cluster,
    label_campaigns,
    operators,
    toolkits,
)
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import build_entities
from fakecollector.graph.fusion import build_edges


class Analysis(BaseModel):
    """Hold the case graph and its campaign, operator, and toolkit memberships."""

    case_ids: list[str]
    entities: list[Entity]
    links: list[tuple[str, str, str]]
    edges: list[Edge]
    campaigns: list[Campaign]
    operators: dict[str, str]
    toolkits: dict[str, list[str]]


def analyze(
    features: Sequence[Feature],
    case_ids: Sequence[str] | None = None,
    cfg: EdgeConfig | None = None,
) -> Analysis:
    """Build a deterministic campaign graph, including cases without features."""
    cfg = cfg or EdgeConfig()
    ids = sorted(set(case_ids or ()).union(feature.case_id for feature in features))
    entities, links = build_entities(features, cfg=cfg, case_ids=ids)
    edges = build_edges(features, entities, links, cfg, case_ids=ids)
    by_operator = operators(ids, entities, links)
    campaigns = cluster(ids, edges, cfg, by_operator)
    by_toolkit = toolkits(ids, entities, links)
    attach_operators(campaigns, by_operator)
    attach_toolkits(campaigns, by_toolkit)
    label_campaigns(campaigns, features)
    return Analysis(
        case_ids=ids,
        entities=entities,
        links=links,
        edges=edges,
        campaigns=campaigns,
        operators=by_operator,
        toolkits=by_toolkit,
    )
