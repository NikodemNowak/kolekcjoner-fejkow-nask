from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image
from pytest import LogCaptureFixture

from fakecollector.app import pl
from fakecollector.core.schemas import Artifact, Campaign, Case, Edge, Entity, Evidence, Trait
from fakecollector.graph.analyze import Analysis
from fakecollector.report.build import build_report
from fakecollector.store import RunStore


def test_report_profiles_evidence_thumbnails_and_escapes_input(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    image = tmp_path / "screen.png"
    Image.new("RGB", (160, 120), "white").save(image)
    cases = [
        Case(id="F:a", corpus="fixture", path=tmp_path),
        Case(id="F:b", corpus="fixture", path=tmp_path, duplicate_of="F:a"),
    ]
    artifacts = [
        Artifact(
            id="image-a",
            case_id="F:a",
            kind="image",
            role="screenshot",
            path=image,
            size=image.stat().st_size,
        ),
        Artifact(
            id="missing",
            case_id="F:b",
            kind="image",
            role="screenshot",
            path=tmp_path / "missing.png",
            size=0,
        ),
    ]
    trait = Trait(
        entity_type="Domain",
        value="sub.site.example",
        tier="operator",
        coverage=1,
        lift=2,
        kind="constant",
        why="Wspólny adres sub.site.example",
    )
    campaign = Campaign(
        id="C1",
        operator_id="O1",
        case_ids=["F:a", "F:b"],
        label="<script>alert(1)</script>",
        traits=[trait],
        cohesion=0.8,
    )
    evidence = Evidence(
        family="ids",
        tier="campaign",
        kind="ids.kit_landing",
        value="id",
        detail="Wspólny ślad sub.site.example",
        weight=0.8,
        artifacts=["image-a:pixel"],
    )
    edge = Edge(
        src="F:a",
        dst="F:b",
        score=0.8,
        operator_link=True,
        signals={"ids": 0.8},
        comparable=["ids"],
        evidence=[evidence],
    )
    entity = Entity(
        id="Domain:sub.site.example", type="Domain", value="sub.site.example", tier="operator", df=2
    )
    graph = Analysis(
        case_ids=["F:a", "F:b"],
        entities=[entity],
        links=[("F:a", entity.id, "image-a"), ("F:b", entity.id, "missing")],
        edges=[edge],
        campaigns=[campaign],
        operators={"F:a": "O1", "F:b": "O1"},
        toolkits={"F:a": ["T1"], "F:b": ["T1"]},
    )
    store = RunStore(tmp_path / "run")
    store.write_cases(cases, artifacts)
    store.save_graph(graph)
    path = build_report(store)
    text = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(text, "html.parser")
    summary = pl.REPORT_SUMMARY.format(cases=2, unique=1, campaigns=1, operators=1)
    assert summary in soup.get_text(" ")
    assert "sub[.]site[.]example" in text and "sub.site.example" not in text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
    assert any(image.get("src", "").startswith("data:image/") for image in soup.find_all("img"))
    assert pl.REPORT_PROFILE in text and pl.REPORT_EVIDENCE in text
    assert "Wspólny adres sub[.]site[.]example" in text
    assert "image-a:pixel" in text
    assert "O1" in text and "T1" in text
    assert not soup.select("script[src], link[href], img[src^='http']")
    assert (store.run_dir / "campaigns.json").is_file()
    assert "Thumbnail skipped" in caplog.text
    assert pl.REPORT_DATA_NOTICE in soup.get_text(" ")
