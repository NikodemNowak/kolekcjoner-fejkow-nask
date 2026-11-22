from pathlib import Path

from bs4 import BeautifulSoup
from pytest import MonkeyPatch
from streamlit.testing.v1 import AppTest

from fakecollector.app import pl
from fakecollector.app.group_evidence import group_evidence
from fakecollector.cli import APP_FILE
from fakecollector.config import get_settings
from fakecollector.core.schemas import Case, Entity
from fakecollector.graph.analyze import Analysis
from fakecollector.report.build import build_report
from fakecollector.store import RunStore


def test_shared_evidence_survives_run_storage_and_excludes_non_links(tmp_path: Path) -> None:
    graph = Analysis(
        case_ids=["a", "b", "c", "d"],
        entities=[
            Entity(id="Pixel:123", type="Pixel", value="123", tier="operator", df=2),
            Entity(id="Host:h", type="Host", value="h", tier="operator", df=2),
            Entity(id="Kit:k", type="Kit", value="k", tier="toolkit", df=2),
            Entity(
                id="Host:stopped", type="Host", value="stopped", tier="operator", df=2, stop=True
            ),
            Entity(id="Pixel:single", type="Pixel", value="single", tier="operator", df=1),
        ],
        links=[
            ("a", "Pixel:123", "a1"),
            ("b", "Pixel:123", "b1"),
            ("b", "Host:h", "b2"),
            ("c", "Host:h", "c1"),
            ("a", "Kit:k", "a2"),
            ("d", "Kit:k", "d1"),
            ("a", "Host:stopped", "a3"),
            ("b", "Host:stopped", "b3"),
            ("a", "Pixel:single", "a4"),
        ],
        edges=[],
        campaigns=[],
        operators={"a": "O1", "b": "O1", "c": "O1"},
        toolkits={"a": ["Kit:k"], "d": ["Kit:k"]},
    )
    store = RunStore(tmp_path)
    store.save_graph(graph)
    groups = group_evidence(store.load_graph())
    operator = groups["operator"]["O1"]
    assert [(item.value, [source.case_id for source in item.sources]) for item in operator] == [
        ("h", ["b", "c"]),
        ("123", ["a", "b"]),
    ]
    assert operator[1].sources[0].artifacts == ["a1"]
    assert [source.case_id for source in groups["toolkit"]["Kit:k"][0].sources] == ["a", "d"]


def test_report_and_app_show_operator_evidence_without_campaign_edges(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    graph = Analysis(
        case_ids=["a", "b"],
        entities=[
            Entity(id="Tracker:123", type="Tracker", value="123", tier="operator", df=2),
            Entity(id="Kit:shared", type="Kit", value="shared", tier="toolkit", df=2),
        ],
        links=[
            ("a", "Tracker:123", "source-a"),
            ("b", "Tracker:123", "source-b"),
            ("a", "Kit:shared", "kit-a"),
            ("b", "Kit:shared", "kit-b"),
        ],
        edges=[],
        campaigns=[],
        operators={"a": "O1", "b": "O1"},
        toolkits={"a": ["Kit:shared"], "b": ["Kit:shared"]},
    )
    store = RunStore(tmp_path)
    store.write_cases(
        [
            Case(id="a", corpus="fixture", path=tmp_path),
            Case(id="b", corpus="fixture", path=tmp_path),
        ],
        [],
    )
    store.save_graph(graph)
    text = BeautifulSoup(build_report(store).read_text(), "html.parser").get_text(" ")
    assert "Identyfikator śledzący: 123" in text
    assert "a (source-a)" in text and "b (source-b)" in text
    assert "a (kit-a)" in text and "b (kit-b)" in text

    monkeypatch.setenv("APP_RUN_DIR", str(tmp_path))
    get_settings.cache_clear()
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.switch_page(str(Path(APP_FILE).parent / "page_links.py")).run()
    assert not at.exception
    assert at.subheader[0].value == pl.GROUP_EVIDENCE
    rows = at.dataframe[0].value
    assert any("123" in item for item in rows[pl.GROUP_TRACE])
    assert any("source-a" in item for item in rows[pl.GROUP_CASES])
    assert any("kit-a" in item for item in rows[pl.GROUP_CASES])
    get_settings.cache_clear()
