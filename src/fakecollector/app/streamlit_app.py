"""Streamlit analyst app: entry point and page navigation (Task 4)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from fakecollector.app import pl, state

HERE = Path(__file__).parent
PAGES = [
    st.Page(HERE / "page_add.py", title=pl.PAGE_ADD, url_path="dodaj"),
    st.Page(HERE / "page_links.py", title=pl.PAGE_LINKS, url_path="powiazania"),
    st.Page(HERE / "page_overview.py", title=pl.PAGE_OVERVIEW, url_path="przeglad"),
    st.Page(HERE / "page_campaign.py", title=pl.PAGE_CAMPAIGN, url_path="kampania"),
    st.Page(HERE / "page_entity.py", title=pl.PAGE_ENTITY, url_path="slady"),
    st.Page(HERE / "page_export.py", title=pl.PAGE_EXPORT, url_path="eksport"),
]


def render() -> None:
    """Title, run status and the page navigation."""
    st.set_option("client.toolbarMode", "minimal")
    st.set_page_config(page_title=pl.TITLE, layout="wide")
    st.title(pl.TITLE)
    st.caption(pl.SUBTITLE)
    if not state.has_graph(state.run_dir()):
        st.info(pl.NO_RUN)
        return
    st.navigation(PAGES).run()


render()
