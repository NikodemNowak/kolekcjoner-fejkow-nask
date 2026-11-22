from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from fakecollector.app import pl
from fakecollector.cli import APP_FILE, _run
from fakecollector.config import get_settings
from fakecollector.core.schemas import Assignment, Evidence
from fakecollector.store import RunStore

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "cases"
PAGES = Path(APP_FILE).parent


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("run")
    mp = pytest.MonkeyPatch()
    mp.setenv("FEATURE_CACHE", str(out / "cache"))
    get_settings.cache_clear()
    _run([FIXTURES], out / "run", "fast", 0)
    mp.undo()
    return out / "run"


@pytest.fixture
def app_env(fixture_run: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_RUN_DIR", str(fixture_run))
    monkeypatch.setenv("FEATURE_CACHE", str(fixture_run.parent / "cache"))
    get_settings.cache_clear()
    yield fixture_run
    get_settings.cache_clear()


def test_links_page_shows_per_family_table(app_env: Path) -> None:
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.switch_page(str(PAGES / "page_links.py")).run()
    assert not at.exception
    assert at.header[0].value == pl.PAGE_LINKS
    assert at.dataframe, "the first case in the list has links, so a table is shown"
    columns = list(at.dataframe[0].value.columns)
    assert pl.FAMILY_NAMES["ids"] in columns and pl.LINKS_COLUMNS["score"] in columns


def test_add_page_assigns_a_url_and_adds_it_to_the_run(app_env: Path) -> None:
    before = len(RunStore(app_env).cases())
    at = AppTest.from_file(str(APP_FILE), default_timeout=120).run()
    assert at.header[0].value == pl.PAGE_ADD  # first page
    at.text_input[0].input("https://fixture-alpha.click/?clickid=nowy123")
    at.button[0].click().run()
    assert not at.exception
    decisions = set(pl.ASSIGNMENT_DECISIONS.values())
    shown = [m.value for m in [*at.success, *at.warning, *at.info]]
    assert any(any(d in text for d in decisions) for text in shown), shown
    assert len(RunStore(app_env).cases()) == before + 1


def test_empty_submit_asks_for_input(app_env: Path) -> None:
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.button[0].click().run()
    assert at.warning[0].value == pl.ADD_EMPTY


def test_add_page_displays_insufficient_data_and_schema_hint(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = Assignment(
        case_id="U:test",
        decision="new",
        campaign_id=None,
        score=0,
        margin=0,
        comparable=["infra"],
        flags=["insufficient_data"],
        evidence=[
            Evidence(
                family="infra",
                tier="context",
                kind="url.schema",
                value="0.75",
                detail="Podobny kształt adresu: wskazówka",
                weight=0,
                artifacts=["T:1"],
            )
        ],
    )
    monkeypatch.setattr("fakecollector.pipeline.assign_new", lambda *args, **kwargs: [answer])
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.text_input[0].input("https://synthetic.example/path")
    at.button[0].click().run()
    assert not at.exception
    assert any(pl.ADD_INSUFFICIENT_DATA in item.value for item in at.warning)
    assert not any(pl.ASSIGNMENT_DECISIONS["new"] in item.value for item in at.info)
    assert pl.ADD_HINTS in [item.value for item in at.subheader]
    assert any("Podobny kształt adresu" in item.value for item in at.markdown)


def test_add_page_real_unseen_url_is_not_called_new_pattern(app_env: Path) -> None:
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.text_input[0].input("https://unknown.synthetic.invalid/unique-shape?custom=unique")
    at.button[0].click().run()
    assert not at.exception
    assert any(pl.ADD_INSUFFICIENT_DATA in item.value for item in at.warning)
    assert not any(pl.ASSIGNMENT_DECISIONS["new"] in item.value for item in at.info)


def test_overview_shows_campaigns_and_can_filter_by_operator(app_env: Path) -> None:
    graph = RunStore(app_env).load_graph()
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.switch_page(str(PAGES / "page_overview.py")).run()
    assert not at.exception
    assert at.header[0].value == pl.PAGE_OVERVIEW
    assert int(at.metric[0].value) == len(graph.case_ids)
    assert len(at.dataframe[0].value) == len(graph.campaigns)
    if graph.operators:
        operator = next(iter(graph.operators.values()))
        at.multiselect[0].set_value([operator]).run()
        expected = sum(
            any(graph.operators.get(case) == operator for case in campaign.case_ids)
            for campaign in graph.campaigns
        )
        assert len(at.dataframe[0].value) == expected


def test_overview_analyzes_folder_in_new_run(app_env: Path) -> None:
    before = RunStore(app_env).load_graph()
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.switch_page(str(PAGES / "page_overview.py")).run()
    at.text_input[0].input(str(FIXTURES))
    at.button[0].click().run(timeout=120)
    assert not at.exception
    new_run = Path(at.session_state["active_run_dir"])
    assert new_run != app_env
    assert len(RunStore(new_run).cases()) > 0
    assert (new_run / "report.html").exists()
    assert RunStore(app_env).load_graph() == before


def test_campaign_page_shows_members_and_profile(app_env: Path) -> None:
    graph = RunStore(app_env).load_graph()
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.switch_page(str(PAGES / "page_campaign.py")).run()
    assert not at.exception
    assert at.header[0].value == pl.PAGE_CAMPAIGN
    assert at.selectbox[0].value == graph.campaigns[0].id
    assert at.dataframe
    members = at.dataframe[0].value[pl.CAMPAIGN_CASE]
    assert set(members) == set(graph.campaigns[0].case_ids)
    if len(graph.campaigns) > 1:
        campaign = graph.campaigns[1]
        at.selectbox[0].select(campaign.id).run()
        assert not at.exception
        assert set(at.dataframe[0].value[pl.CAMPAIGN_CASE]) == set(campaign.case_ids)


def test_entity_pivot_finds_cases_and_artifacts(app_env: Path) -> None:
    graph = RunStore(app_env).load_graph()
    assert graph.entities
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.switch_page(str(PAGES / "page_entity.py")).run()
    assert not at.exception
    assert at.header[0].value == pl.PAGE_ENTITY
    entity_id = at.selectbox[0].value
    expected = {case for case, entity, _ in graph.links if entity == entity_id}
    assert set(at.dataframe[0].value[pl.CAMPAIGN_CASE]) == expected
    for case in expected:
        sources = at.dataframe[0].value.set_index(pl.CAMPAIGN_CASE).loc[case, pl.REPORT_ARTIFACTS]
        assert any(
            artifact in sources for c, e, artifact in graph.links if c == case and e == entity_id
        )


def test_export_page_prepares_selected_format(app_env: Path) -> None:
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.switch_page(str(PAGES / "page_export.py")).run()
    assert not at.exception
    assert at.header[0].value == pl.PAGE_EXPORT
    at.selectbox[0].select("ioc-csv")
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state["prepared_export"].filename == "ioc-csv.zip"
