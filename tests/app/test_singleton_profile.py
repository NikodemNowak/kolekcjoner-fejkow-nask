from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from streamlit.testing.v1 import AppTest

from fakecollector.app import pl
from fakecollector.cli import APP_FILE
from fakecollector.config import get_settings
from fakecollector.core.schemas import Campaign, Case, Trait
from fakecollector.graph.analyze import Analysis
from fakecollector.report.build import build_report
from fakecollector.store import RunStore


def test_singleton_profile_is_not_presented_as_shared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trait = Trait(
        entity_type="Domain",
        value="fictional.example",
        tier="campaign",
        coverage=1,
        lift=1,
        kind="constant",
        why="Ta sama domena występuje w wielu zgłoszeniach.",
    )
    campaign = Campaign(
        id="C1", operator_id=None, case_ids=["a"], label="Example", traits=[trait], cohesion=1
    )
    graph = Analysis(
        case_ids=["a"],
        entities=[],
        links=[],
        edges=[],
        campaigns=[campaign],
        operators={},
        toolkits={},
    )
    store = RunStore(tmp_path / "run")
    store.write_cases([Case(id="a", corpus="fixture", path=tmp_path)], [])
    store.save_graph(graph)
    soup = BeautifulSoup(build_report(store).read_text(), "html.parser")
    text = soup.get_text(" ")
    assert pl.SINGLETON_PROFILE in text
    assert "fictional[.]example" in text
    assert trait.why not in text

    monkeypatch.setenv("APP_RUN_DIR", str(store.run_dir))
    get_settings.cache_clear()
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    at.switch_page(str(Path(APP_FILE).parent / "page_campaign.py")).run()
    assert not at.exception
    assert pl.SINGLETON_PROFILE in [heading.value for heading in at.subheader]
    assert trait.why not in at.dataframe[1].value.to_string()
    get_settings.cache_clear()
