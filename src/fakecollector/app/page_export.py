"""Prepare and download analysis exports."""

from __future__ import annotations

import logging

import streamlit as st

from fakecollector.app import pl, state
from fakecollector.app.exports import prepare_export
from fakecollector.export import FORMATS
from fakecollector.store import RunStore

logger = logging.getLogger(__name__)


def render() -> None:
    """Prepare a selected export from the current analysis and offer it for download."""
    st.header(pl.PAGE_EXPORT)
    run = state.run_dir()
    if not state.has_graph(run):
        st.info(pl.NO_RUN)
        return
    assert run is not None
    st.caption(pl.EXPORT_DATA_NOTICE)
    format_name = st.selectbox(
        pl.EXPORT_FORMAT,
        ["report", "json", *FORMATS],
        format_func=lambda value: pl.EXPORT_FORMAT_NAMES[value],
    )
    key = (str(run.resolve()), (run / state.GRAPH_FILE).stat().st_mtime_ns, format_name)
    if st.button(pl.EXPORT_PREPARE):
        st.session_state.pop("prepared_export", None)
        st.session_state.pop("prepared_export_key", None)
        try:
            with st.spinner(pl.EXPORT_RUNNING):
                st.session_state["prepared_export"] = prepare_export(RunStore(run), format_name)
                st.session_state["prepared_export_key"] = key
        except Exception:
            logger.exception("Export preparation failed")
            st.error(pl.EXPORT_FAILED)
    if st.session_state.get("prepared_export_key") == key:
        result = st.session_state["prepared_export"]
        st.download_button(
            pl.EXPORT_DOWNLOAD, data=result.content, file_name=result.filename, mime=result.mime
        )


render()
