from datetime import UTC, datetime
from pathlib import Path

from fakecollector.core.schemas import Artifact, Case, Edge, Evidence, Feature


def test_case_round_trips_through_json() -> None:
    case = Case(
        id="M:61",
        corpus="M",
        path=Path("data/x/61"),
        landing_urls=["https://example.org/a"],
        captured_at=datetime(2026, 11, 21, tzinfo=UTC),
        flags=["cloaking_suspected"],
    )
    assert Case.model_validate_json(case.model_dump_json()) == case


def test_defaults_are_not_shared_between_instances() -> None:
    a = Case(id="B:p1", corpus="B", path=None)
    b = Case(id="B:p2", corpus="B", path=None)
    a.flags.append("capture_error")
    assert b.flags == []


def test_artifact_and_feature_keep_provenance() -> None:
    art = Artifact(
        id="0123456789abcdef",
        case_id="B:p1",
        kind="har",
        role="network",
        path=Path("a.har"),
        size=10,
    )
    feat = Feature(
        case_id=art.case_id,
        artifact_id=art.id,
        name="ids.fb_pixel",
        value="123",
        locator="entry[0].request.url",
    )
    assert feat.artifact_id == art.id
    assert feat.vector is None


def test_edge_holds_signals_for_several_families() -> None:
    ev = Evidence(
        family="ids",
        tier="campaign",
        kind="ids.kit_landing",
        value="x",
        detail="ten sam landing",
        weight=0.97,
    )
    edge = Edge(
        src="B:p1",
        dst="B:p7",
        score=0.99,
        operator_link=True,
        signals={"ids": 0.97, "asset": 0.8, "text": 0.9},
        comparable=["ids", "asset", "text", "image"],
        evidence=[ev],
    )
    restored = Edge.model_validate_json(edge.model_dump_json())
    assert set(restored.signals) == {"ids", "asset", "text"}
    assert "image" in restored.comparable
