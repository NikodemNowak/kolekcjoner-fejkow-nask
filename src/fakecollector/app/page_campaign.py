"""Campaign membership, shared traits and traceable evidence."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from fakecollector.app import pl, state
from fakecollector.app.display import (
    display_campaign_label,
    display_description,
    display_evidence,
    display_value,
)
from fakecollector.report.graph import GraphLabels, render_graph


def render() -> None:
    """Display one campaign and the evidence linking its cases."""
    st.header(pl.PAGE_CAMPAIGN)
    run = state.run_dir()
    if not state.has_graph(run):
        st.info(pl.NO_RUN)
        return
    assert run is not None
    graph = state.analysis(run)
    if not graph.campaigns:
        st.info(pl.CAMPAIGN_NO_CAMPAIGNS)
        return
    campaigns = {campaign.id: campaign for campaign in graph.campaigns}
    selected = st.selectbox(
        pl.CAMPAIGN_SELECT,
        list(campaigns),
        format_func=lambda campaign_id: (
            f"{display_campaign_label(campaigns[campaign_id].label)} · {campaign_id}"
        ),
    )
    campaign = campaigns[selected]
    cases = {case.id: case for case in state.cases(run)}
    members = set(campaign.case_ids)
    st.subheader(pl.REPORT_MEMBERS)
    st.dataframe(
        [
            {
                pl.CAMPAIGN_CASE: case_id,
                pl.CAMPAIGN_DUPLICATE: cases[case_id].duplicate_of if case_id in cases else None,
            }
            for case_id in campaign.case_ids
        ],
        use_container_width=True,
        hide_index=True,
    )
    singleton = len(campaign.case_ids) == 1
    st.subheader(pl.SINGLETON_PROFILE if singleton else pl.REPORT_PROFILE)
    if campaign.traits:
        st.dataframe(
            [
                {
                    pl.CAMPAIGN_TRAIT: display_value(trait.entity_type, trait.value),
                    pl.CAMPAIGN_TYPE: (
                        pl.SINGLETON_TRAIT
                        if singleton
                        else pl.REPORT_TRAIT_CONSTANT
                        if trait.kind == "constant"
                        else pl.REPORT_TRAIT_ROTATING
                    ),
                    pl.REPORT_COVERAGE: round(trait.coverage, 2),
                    pl.REPORT_LIFT: round(trait.lift, 2),
                    pl.CAMPAIGN_WHY: ""
                    if singleton
                    else display_description(trait.entity_type, trait.why),
                }
                for trait in campaign.traits
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(pl.SINGLETON_NO_TRAITS if singleton else pl.REPORT_NO_TRAITS)
    edges = [edge for edge in graph.edges if edge.src in members and edge.dst in members]
    st.subheader(pl.REPORT_EVIDENCE)
    evidence = [
        {
            pl.CAMPAIGN_FROM: edge.src,
            pl.CAMPAIGN_TO: edge.dst,
            pl.CAMPAIGN_FAMILY: pl.FAMILY_NAMES.get(item.family, item.family),
            pl.REPORT_EVIDENCE: display_evidence(item),
            pl.REPORT_CONFIDENCE: item.weight,
            pl.REPORT_ARTIFACTS: ", ".join(item.artifacts),
        }
        for edge in edges
        for item in edge.evidence
    ]
    if evidence:
        st.dataframe(evidence, use_container_width=True, hide_index=True)
    else:
        st.info(pl.REPORT_NO_EVIDENCE)
    links = [link for link in graph.links if link[0] in members]
    entity_cases: dict[str, set[str]] = {}
    for case, entity, _ in links:
        entity_cases.setdefault(entity, set()).add(case)
    subset = graph.model_copy(
        update={
            "case_ids": campaign.case_ids,
            "edges": edges,
            "links": links,
            "entities": [
                entity.model_copy(update={"df": len(entity_cases.get(entity.id, set()))})
                for entity in graph.entities
                if entity.id in entity_cases
            ],
        }
    )
    labels = GraphLabels(
        case_view=pl.REPORT_CASE_GRAPH,
        entity_view=pl.REPORT_ENTITY_GRAPH,
        evidence=pl.REPORT_EVIDENCE,
        family_names=pl.FAMILY_NAMES,
        tier_names=pl.REPORT_TIERS,
    )
    components.html(render_graph(subset, labels), height=680, scrolling=True)


render()
