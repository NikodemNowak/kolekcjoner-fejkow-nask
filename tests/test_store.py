import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np

from fakecollector.core.schemas import Artifact, Case, Feature
from fakecollector.graph.analyze import analyze
from fakecollector.store import FeatureCache, RunStore


def test_feature_cache_round_trip_and_rebinds_provenance(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    feature = Feature(case_id="first", artifact_id="old", name="img.test", value="x", vector=[0.5])
    cache.put("a" * 64, "vision", 1, [feature])

    result = cache.get("a" * 64, "vision", 1, case_id="second", artifact_id="new")
    assert result == [feature.model_copy(update={"case_id": "second", "artifact_id": "new"})]
    assert cache.get("a" * 64, "vision", 2, case_id="second", artifact_id="new") is None
    assert cache.get("a" * 64, "other", 1, case_id="second", artifact_id="new") is None


def test_cache_distinguishes_empty_result_from_miss(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    cache.put("b" * 64, "empty", 1, [])
    assert cache.get("b" * 64, "empty", 1, case_id="case", artifact_id="id") == []
    assert cache.get("c" * 64, "empty", 1, case_id="case", artifact_id="id") is None


def test_corrupt_cache_is_a_miss(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    cache.put("d" * 64, "extractor", 1, [])
    next(tmp_path.rglob("*.json")).write_text("not json")
    assert cache.get("d" * 64, "extractor", 1, case_id="case", artifact_id="id") is None


def test_store_round_trips_cases_and_artifacts(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    case = Case(
        id="synthetic:1",
        corpus="synthetic",
        path=tmp_path / "input",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        landing_urls=["https://example.invalid"],
        flags=["cloaking_suspected"],
    )
    artifact = Artifact(
        id="abc",
        case_id=case.id,
        kind="html",
        role="landing_page",
        path=tmp_path / "input" / "page.html",
        page="page_1",
        size=123,
        meta={"source": "fixture"},
    )
    store.write_cases([case], [artifact])

    reopened = RunStore(tmp_path / "run")
    assert reopened.cases() == [case]
    assert reopened.artifacts() == [artifact]
    assert reopened.artifacts(case.id) == [artifact]
    assert reopened.artifacts("missing") == []
    assert (tmp_path / "run" / "cases.parquet").is_file()
    assert (tmp_path / "run" / "artifacts.parquet").is_file()
    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT id, landing_urls FROM read_parquet(?)",
            [str(tmp_path / "run" / "cases.parquet")],
        ).fetchall()
    assert rows == [(case.id, case.landing_urls)]


def test_store_preserves_non_utf8_file_paths(tmp_path: Path) -> None:
    path = tmp_path / os.fsdecode(b"sample-\xff.html")
    path.write_text("synthetic", encoding="utf-8")
    store = RunStore(tmp_path / "run")
    case = Case(id="synthetic:case", corpus="synthetic", path=path)
    artifact = Artifact(
        id="abc", case_id=case.id, kind="html", role="landing_page", path=path, size=9
    )
    store.write_cases([case], [artifact])
    assert store.cases()[0].path == path
    assert store.artifacts()[0].path == path
    assert store.artifacts()[0].path.read_text() == "synthetic"


def test_store_writes_empty_tables_and_replaces_existing_data(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    assert store.cases() == []
    assert store.artifacts() == []
    store.write_cases([Case(id="one", corpus="fixture", path=None)], [])
    store.write_cases([], [])
    assert store.cases() == []
    assert store.artifacts() == []


def test_feature_and_graph_round_trip(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    items = [
        Feature(case_id="A", artifact_id="x", name="text.minhash", value="", vector=[1.0, 2.0]),
        Feature(case_id="B", artifact_id="y", name="text.minhash", value="", vector=[3.0, 4.0]),
        Feature(case_id="A", artifact_id="x", name="ids.kit_landing", value="landing"),
    ]
    store.add_features(items, "test", 1)
    assert store.features() == [item.model_copy(update={"vector": None}) for item in items]
    assert store.all_features() == items
    ids, vectors = store.vectors("text.minhash")
    assert ids == ["A", "B"]
    np.testing.assert_array_equal(vectors, [[1, 2], [3, 4]])
    assert store.features(["ids.kit_landing"]) == [items[2]]
    graph = analyze(items, ["A", "B", "C"])
    store.save_graph(graph)
    assert RunStore(tmp_path / "run").load_graph() == graph
    store.save_graph(graph.entities, graph.links, graph.edges, graph.campaigns)
    assert RunStore(tmp_path / "run").load_graph() == graph
