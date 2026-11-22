"""Page "Powiązania": every way one ad links to the others, one family at a time."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from fakecollector.app import pl, state
from fakecollector.app.display import display_campaign_label
from fakecollector.app.group_evidence import group_evidence
from fakecollector.app.links import FAMILY_COLOURS, FAMILY_ORDER, linked_subgraph, neighbour_rows
from fakecollector.graph.analyze import Analysis
from fakecollector.report.graph import GraphLabels, render_graph


def _render_group_evidence(graph: Analysis, case_id: str) -> None:
    shared = group_evidence(graph)
    table = []
    for tier, groups in shared.items():
        for group, evidence in groups.items():
            for item in evidence:
                if not any(source.case_id == case_id for source in item.sources):
                    continue
                table.append(
                    {
                        pl.GROUP_EVIDENCE: f"{pl.GROUP_LABELS[tier]}: {group}",
                        pl.GROUP_TRACE: (
                            f"{pl.GROUP_ENTITY_NAMES.get(item.entity_type, pl.GROUP_TRACE)}: "
                            f"{item.value}"
                        ),
                        pl.GROUP_CASES: "; ".join(
                            f"{source.case_id} ({', '.join(source.artifacts)})"
                            for source in item.sources
                        ),
                    }
                )
    if table:
        st.subheader(pl.GROUP_EVIDENCE)
        st.dataframe(table, use_container_width=True, hide_index=True)


def render() -> None:
    """Pick a case → per-family multigraph and a neighbour table with filters."""
    st.header(pl.PAGE_LINKS)
    run = state.run_dir()
    if not state.has_graph(run):
        st.info(pl.NO_RUN)
        return
    assert run is not None
    graph = state.analysis(run)
    st.write(pl.LINKS_INTRO)
    label = {cid: display_campaign_label(c.label) for c in graph.campaigns for cid in c.case_ids}
    linked = {e.src for e in graph.edges} | {e.dst for e in graph.edges}
    options = sorted(graph.case_ids, key=lambda c: (c not in linked, c))
    if not options:
        st.info(pl.LINKS_NONE)
        return
    names = pl.FAMILY_NAMES
    left, mid, right = st.columns([2, 2, 1])
    case_id = left.selectbox(
        pl.LINKS_CASE, options, format_func=lambda c: f"{c} · {label.get(c, '')}".rstrip(" ·")
    )
    families = mid.multiselect(
        pl.LINKS_FAMILIES,
        list(FAMILY_ORDER),
        format_func=lambda f: names.get(f, f),
        placeholder=pl.FILTER_ALL,
    )
    min_families = right.slider(pl.LINKS_MIN, 1, len(FAMILY_ORDER), 1)
    rows = neighbour_rows(graph, case_id, families=families or None, min_families=min_families)
    st.markdown(
        " ".join(
            f"<span style='color:{FAMILY_COLOURS[f]}'>■</span> {names[f]}" for f in FAMILY_ORDER
        ),
        unsafe_allow_html=True,
    )
    if not rows:
        st.info(pl.LINKS_NONE)
        _render_group_evidence(graph, case_id)
        return
    subgraph = linked_subgraph(graph, case_id, rows, families=families or None)
    labels = GraphLabels(
        case_view=pl.REPORT_CASE_GRAPH,
        entity_view=pl.REPORT_ENTITY_GRAPH,
        evidence=pl.REPORT_EVIDENCE,
        family_names=pl.FAMILY_NAMES,
        tier_names=pl.REPORT_TIERS,
    )
    components.html(
        render_graph(subgraph, labels, focus=case_id, compact=True), height=760, scrolling=False
    )
    cols = pl.LINKS_COLUMNS
    table = []
    for row in rows:
        record: dict[str, object] = {
            cols["case"]: row.case_id,
            cols["campaign"]: row.campaign_label,
            cols["score"]: round(row.score, 2),
            cols["families"]: len(row.fired),
            cols["operator"]: pl.YES if row.operator_link else "",
        }
        for family in FAMILY_ORDER:
            value = row.per_family.get(family)
            record[names[family]] = pl.LINKS_NO_DATA if value is None else round(value, 2)
        record[cols["evidence"]] = " · ".join(row.evidence)
        table.append(record)
    st.dataframe(table, use_container_width=True, hide_index=True)
    _render_group_evidence(graph, case_id)


render()
