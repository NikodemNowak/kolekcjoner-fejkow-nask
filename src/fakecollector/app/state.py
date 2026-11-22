"""Which run the app shows, and cached access to it (one place for all pages)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

from fakecollector.config import get_settings
from fakecollector.core.schemas import Case, Feature
from fakecollector.graph.analyze import Analysis
from fakecollector.store import RunStore

GRAPH_FILE = "graph.json"


def run_dir() -> Path | None:
    """`fakecollector app <run>` passes `--run <dir>`; otherwise `APP_RUN_DIR`."""
    if "active_run_dir" in st.session_state:
        return Path(st.session_state["active_run_dir"])
    args = sys.argv[1:]
    if "--run" in args and args.index("--run") + 1 < len(args):
        return Path(args[args.index("--run") + 1])
    return get_settings().run_dir


def has_graph(path: Path | None) -> bool:
    """True when the run has been analysed."""
    return path is not None and (path / GRAPH_FILE).exists()


@st.cache_resource
def _analysis(path: str, stamp: float) -> Analysis:
    # `stamp` (graph.json mtime) is part of the cache key, so a committed upload reloads.
    return RunStore(Path(path)).load_graph()


def analysis(path: Path) -> Analysis:
    """The run's graph, reloaded whenever the run changes."""
    return _analysis(str(path), (path / GRAPH_FILE).stat().st_mtime)


@st.cache_resource
def _cases(path: str, stamp: float) -> list[Case]:
    return RunStore(Path(path)).cases()


def cases(path: Path) -> list[Case]:
    """Return cases, refreshed when their persisted table changes."""
    table = path / "cases.parquet"
    return _cases(str(path), table.stat().st_mtime if table.exists() else 0.0)


@st.cache_resource
def _features(path: str, stamp: float) -> list[Feature]:
    return RunStore(Path(path)).features()


def features(path: Path) -> list[Feature]:
    """Return scalar features, refreshed when their persisted table changes."""
    table = path / "features.parquet"
    return _features(str(path), table.stat().st_mtime if table.exists() else 0.0)
