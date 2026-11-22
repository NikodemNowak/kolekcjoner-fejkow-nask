"""GEXF (Gephi) and GraphML (yEd, Cytoscape) export of the case-entity graph via NetworkX."""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from fakecollector.export._common import (
    TIER_COLOURS,
    campaign_by_case,
    campaign_colours,
    entity_families,
)
from fakecollector.graph.analyze import Analysis


def _rgb(hex_colour: str) -> dict[str, float]:
    value = hex_colour.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return {"r": r, "g": g, "b": b, "a": 1.0}


def build_graph(analysis: Analysis, *, min_df: int = 2, viz: bool = False) -> nx.Graph:
    """Build an undirected graph of cases, shared entities, HAS and SIMILAR edges.

    Args:
        analysis: The analysed run.
        min_df: Keep entities seen in at least this many cases (1 keeps every entity).
        viz: Add GEXF `viz` colour/size attributes (GraphML cannot store them).

    Returns:
        A NetworkX graph whose attributes are plain strings and numbers.
    """
    graph = nx.Graph()
    by_case = campaign_by_case(analysis)
    colours = campaign_colours(analysis)
    for case_id in analysis.case_ids:
        campaign = by_case.get(case_id)
        colour = colours[campaign.id] if campaign else "#9E9E9E"
        attrs: dict[str, object] = {
            "label": case_id,
            "kind": "Case",
            "tier": "",
            "family": "",
            "campaign": campaign.id if campaign else "",
            "campaign_label": campaign.label if campaign else "",
            "operator": analysis.operators.get(case_id, ""),
            "colour": colour,
            "df": 1,
            "stop": False,
        }
        if viz:
            attrs["viz"] = {"color": _rgb(colour), "size": 12.0}
        graph.add_node(case_id, **attrs)

    families = entity_families()
    keep = {e.id: e for e in analysis.entities if e.df >= min_df}
    for entity in keep.values():
        colour = TIER_COLOURS.get(entity.tier, "#757575")
        attrs = {
            "label": f"{entity.type}: {entity.value}"[:120],
            "kind": entity.type,
            "tier": entity.tier,
            "family": families.get(entity.type, ""),
            "campaign": "",
            "campaign_label": "",
            "operator": "",
            "colour": colour,
            "df": entity.df,
            "stop": entity.stop,
        }
        if viz:
            attrs["viz"] = {"color": _rgb(colour), "size": 4.0 + entity.df}
        graph.add_node(entity.id, **attrs)
    for case_id, entity_id, _ in analysis.links:
        if entity_id in keep and case_id in graph:
            entity = keep[entity_id]
            graph.add_edge(
                case_id,
                entity_id,
                kind="HAS",
                weight=1.0,
                family=families.get(entity.type, ""),
                tier=entity.tier,
            )
    for edge in analysis.edges:
        fired = sorted(edge.signals, key=lambda f: -edge.signals[f])
        graph.add_edge(
            edge.src,
            edge.dst,
            kind="SIMILAR",
            weight=round(edge.score, 4),
            family=fired[0] if fired else "",
            tier="operator" if edge.operator_link else "campaign",
        )
    return graph


def export_gexf(analysis: Analysis, out_dir: Path, *, min_df: int = 2) -> Path:
    """Write `graph.gexf` for Gephi; nodes carry tier, family, campaign and colour."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "graph.gexf"
    nx.write_gexf(build_graph(analysis, min_df=min_df, viz=True), path)
    return path


def export_graphml(analysis: Analysis, out_dir: Path, *, min_df: int = 2) -> Path:
    """Write `graph.graphml` with the same nodes and attributes as the GEXF export."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "graph.graphml"
    nx.write_graphml(build_graph(analysis, min_df=min_df), path)
    return path
