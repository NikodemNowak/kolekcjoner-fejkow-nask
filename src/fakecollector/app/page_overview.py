"""Overview of campaigns and a local folder analysis entry point."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import streamlit as st

from fakecollector.app import pl, state
from fakecollector.app.display import display_campaign_label, display_value

logger = logging.getLogger(__name__)


def render() -> None:
    """Show run totals, campaign filters and local analysis controls."""
    st.header(pl.PAGE_OVERVIEW)
    run = state.run_dir()
    if not state.has_graph(run):
        st.info(pl.NO_RUN)
        return
    assert run is not None
    graph = state.analysis(run)
    cases = state.cases(run)
    st.caption(pl.OVERVIEW_ACTIVE_RUN.format(path=run))
    metrics = st.columns(4)
    metrics[0].metric(pl.OVERVIEW_CASES, len(graph.case_ids))
    metrics[1].metric(pl.OVERVIEW_UNIQUE, sum(not case.duplicate_of for case in cases))
    metrics[2].metric(pl.OVERVIEW_CAMPAIGNS, len(graph.campaigns))
    metrics[3].metric(pl.OVERVIEW_OPERATORS, len(set(graph.operators.values())))

    persons = {entity.id: entity.value for entity in graph.entities if entity.type == "Person"}
    people_by_case: dict[str, set[str]] = {}
    for case, entity, _ in graph.links:
        if entity in persons:
            people_by_case.setdefault(case, set()).add(persons[entity])
    columns = st.columns(3)
    operators = columns[0].multiselect(
        pl.OVERVIEW_FILTER_OPERATOR,
        sorted(set(graph.operators.values())),
        placeholder=pl.FILTER_ALL,
    )
    toolkits = columns[1].multiselect(
        pl.OVERVIEW_FILTER_TOOLKIT,
        sorted({x for values in graph.toolkits.values() for x in values}),
        placeholder=pl.FILTER_ALL,
    )
    people = columns[2].multiselect(
        pl.OVERVIEW_FILTER_PERSON,
        sorted(set(persons.values())),
        format_func=lambda value: display_value("Person", value),
        placeholder=pl.FILTER_ALL,
    )
    rows = []
    for campaign in graph.campaigns:
        group_operators = {graph.operators[c] for c in campaign.case_ids if c in graph.operators}
        group_toolkits = {x for c in campaign.case_ids for x in graph.toolkits.get(c, [])}
        group_people = {x for c in campaign.case_ids for x in people_by_case.get(c, set())}
        if (
            (operators and not group_operators.intersection(operators))
            or (toolkits and not group_toolkits.intersection(toolkits))
            or (people and not group_people.intersection(people))
        ):
            continue
        rows.append(
            {
                pl.OVERVIEW_TABLE["id"]: campaign.id,
                pl.OVERVIEW_TABLE["label"]: display_campaign_label(campaign.label),
                pl.OVERVIEW_TABLE["members"]: len(campaign.case_ids),
                pl.OVERVIEW_TABLE["operator"]: ", ".join(sorted(group_operators)),
                pl.OVERVIEW_TABLE["toolkits"]: ", ".join(sorted(group_toolkits)),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.form("overview_run"):
        folder = st.text_input(pl.OVERVIEW_FOLDER)
        submitted = st.form_submit_button(pl.OVERVIEW_RUN)
    if submitted:
        path = Path(folder).expanduser()
        if not folder.strip() or not path.is_dir():
            st.warning(pl.OVERVIEW_INVALID)
            return
        try:
            from fakecollector.cli import _run

            target = Path(tempfile.mkdtemp(prefix="analysis-", dir=run.parent))
            with st.spinner(pl.OVERVIEW_RUNNING):
                _run([path], target, "fast", 0)
            st.session_state["active_run_dir"] = str(target)
            st.rerun()
        except Exception:
            logger.exception("Folder analysis failed")
            st.error(pl.OVERVIEW_FAILED)


render()
