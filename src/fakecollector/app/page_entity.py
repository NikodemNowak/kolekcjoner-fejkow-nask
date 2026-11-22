"""Find cases associated with a selected graph entity."""

from __future__ import annotations

from collections import defaultdict

import streamlit as st

from fakecollector.app import pl, state
from fakecollector.app.display import display_campaign_label, display_value
from fakecollector.core.registry import FEATURES
from fakecollector.graph.entities import entity_type_for
from fakecollector.report.graph import defang


def render() -> None:
    """Find cases, artifacts and feature locators for a selected trace."""
    st.header(pl.PAGE_ENTITY)
    run = state.run_dir()
    if not state.has_graph(run):
        st.info(pl.NO_RUN)
        return
    assert run is not None
    graph = state.analysis(run)
    entities = {entity.id: entity for entity in graph.entities}
    if not entities:
        st.info(pl.ENTITY_NONE)
        return
    selected = st.selectbox(
        pl.ENTITY_SELECT,
        sorted(entities),
        format_func=lambda key: (
            f"{pl.ENTITY_KIND.get(entities[key].type, pl.ENTITY_OTHER)}: "
            f"{defang(display_value(entities[key].type, entities[key].value))}"
        ),
    )
    entity = entities[selected]
    if entity.stop:
        st.info(pl.ENTITY_STOPPED)
    sources: dict[str, set[str]] = defaultdict(set)
    for case, entity_id, artifact in graph.links:
        if entity_id == selected:
            sources[case].add(artifact)
    locators: dict[str, set[str]] = defaultdict(set)
    for feature in state.features(run):
        spec = FEATURES.get(feature.name)
        if (
            spec is not None
            and feature.case_id in sources
            and feature.artifact_id in sources[feature.case_id]
            and feature.value == entity.value
            and entity_type_for(feature.name, spec) == entity.type
            and feature.locator
        ):
            locators[feature.case_id].add(feature.locator)
    campaign_by_case = {
        case: display_campaign_label(campaign.label)
        for campaign in graph.campaigns
        for case in campaign.case_ids
    }
    st.dataframe(
        [
            {
                pl.CAMPAIGN_CASE: case,
                pl.OVERVIEW_TABLE["label"]: campaign_by_case.get(case, ""),
                pl.REPORT_ARTIFACTS: ", ".join(sorted(artifacts)),
                pl.ENTITY_LOCATORS: ", ".join(sorted(locators[case])),
            }
            for case, artifacts in sorted(sources.items())
        ],
        use_container_width=True,
        hide_index=True,
    )


render()
