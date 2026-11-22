import csv
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from fakecollector.app import pl
from fakecollector.app.display import (
    display_campaign_label,
    display_description,
    display_evidence,
    display_value,
)
from fakecollector.core.schemas import Campaign, Case, Edge, Entity, Evidence, Trait
from fakecollector.graph.analyze import Analysis
from fakecollector.report.build import build_report
from fakecollector.report.graph import build_entity_graph
from fakecollector.store import RunStore


def test_person_display_names_match_reference_set() -> None:
    path = Path(__file__).resolve().parents[2] / "refs" / "faces.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        expected = {row["person_slug"]: row["display_name"] for row in csv.DictReader(handle)}
    assert expected == pl.PERSON_DISPLAY_NAMES


def test_display_names_are_contextual_and_keep_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(pl.PERSON_DISPLAY_NAMES, "fictional-person", "Fikcyjna Osoba")
    assert display_value("Person", "fictional-person") == "Fikcyjna Osoba"
    assert display_value("Brand", "gazeta_pl") == "Gazeta.pl"
    assert display_value("Domain", "fictional-person") == "fictional-person"
    assert display_value("Person", "unknown-person") == "unknown-person"
    evidence = Evidence(
        family="person",
        tier="context",
        kind="person.public_figure",
        value="fictional-person",
        detail="Osoba: fictional-person",
        weight=0.2,
        artifacts=[],
    )
    assert display_evidence(evidence) == "Osoba: Fikcyjna Osoba"
    assert evidence.value == "fictional-person"
    assert display_campaign_label("fictional-person · Rozmowa z {PERSON}") == "Rozmowa z [osoba]"
    assert display_campaign_label("Inna etykieta · szczegóły") == "Inna etykieta · szczegóły"
    assert display_description("Person", "fictional-person, fictional-person-other") == (
        "Fikcyjna Osoba, fictional-person-other"
    )


def test_report_and_entity_graph_use_display_names_without_mutating_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(pl.PERSON_DISPLAY_NAMES, "fictional-person", "Fikcyjna Osoba")
    trait = Trait(
        entity_type="Person",
        value="fictional-person",
        tier="context",
        coverage=1,
        lift=1,
        kind="constant",
        why="Wspólny wizerunek",
    )
    campaign = Campaign(
        id="C1", operator_id=None, case_ids=["a", "b"], label="test", traits=[trait], cohesion=1
    )
    item = Evidence(
        family="person",
        tier="context",
        kind="person.public_figure",
        value="fictional-person",
        detail="Osoba: fictional-person",
        weight=0.2,
    )
    edge = Edge(
        src="a",
        dst="b",
        score=0.8,
        operator_link=False,
        signals={"person": 0.2},
        comparable=["person"],
        evidence=[item],
    )
    entity = Entity(
        id="Person:fictional-person", type="Person", value="fictional-person", tier="context", df=2
    )
    graph = Analysis(
        case_ids=["a", "b"],
        entities=[entity],
        links=[("a", entity.id, "x"), ("b", entity.id, "y")],
        edges=[edge],
        campaigns=[campaign],
        operators={},
        toolkits={},
    )
    store = RunStore(tmp_path / "run")
    store.write_cases(
        [Case(id="a", corpus="fixture", path=None), Case(id="b", corpus="fixture", path=None)], []
    )
    store.save_graph(graph)
    assert "Fikcyjna Osoba" in {node.label for node in build_entity_graph(graph).nodes}
    text = BeautifulSoup(build_report(store).read_text(), "html.parser").get_text(" ")
    assert "Fikcyjna Osoba" in text
    assert "fictional-person" not in text
    assert store.load_graph() == graph
