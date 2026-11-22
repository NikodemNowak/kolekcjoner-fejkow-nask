import io
import json
import zipfile
from pathlib import Path

import pytest

from fakecollector.app.exports import prepare_export
from fakecollector.cli import _run
from fakecollector.store import RunStore

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "cases"


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> RunStore:
    run = tmp_path_factory.mktemp("exports") / "run"
    _run([FIXTURES], run, "fast", 0)
    return RunStore(run)


def test_report_and_json_use_current_analysis_without_writing_to_run(store: RunStore) -> None:
    before = {path.relative_to(store.run_dir) for path in store.run_dir.rglob("*")}
    report = prepare_export(store, "report")
    assert report.mime == "text/html"
    assert b"<!doctype html>" in report.content
    graph = prepare_export(store, "json")
    assert set(json.loads(graph.content)["case_ids"]) == set(store.load_graph().case_ids)
    assert {path.relative_to(store.run_dir) for path in store.run_dir.rglob("*")} == before


@pytest.mark.parametrize("format_name", ["neo4j", "gexf", "graphml", "ioc-csv", "dataset"])
def test_export_zip_contains_files_for_selected_format(store: RunStore, format_name: str) -> None:
    result = prepare_export(store, format_name)
    assert result.mime == "application/zip"
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        names = archive.namelist()
        assert names
        assert all(name.startswith(format_name + "/") and ".." not in name for name in names)
        assert archive.testzip() is None
