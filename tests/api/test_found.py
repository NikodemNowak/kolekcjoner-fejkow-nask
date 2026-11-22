"""Tests for what a verdict says it recognised (`Verdict.found`, `Verdict.similar`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from fakecollector.api.assign import verdict
from fakecollector.api.found import CaseTraces, case_traces, similarity_text
from fakecollector.api.views import RunData
from fakecollector.cli import _run
from fakecollector.config import get_settings
from fakecollector.core.schemas import Artifact, Assignment, Feature

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "cases"


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> RunData:
    out = tmp_path_factory.mktemp("run")
    mp = pytest.MonkeyPatch()
    mp.setenv("FEATURE_CACHE", str(out / "cache"))
    get_settings.cache_clear()
    _run([FIXTURES], out / "run", "fast", 0)
    mp.undo()
    get_settings.cache_clear()
    return RunData(out / "run")


def _new_case(tmp_path: Path) -> tuple[list[Feature], list[Artifact]]:
    image = tmp_path / "ad.png"
    Image.new("RGB", (400, 300), (120, 90, 60)).save(image)
    art = Artifact(id="n1", case_id="U:new", kind="image", role="screenshot", path=image, size=1)
    feats = [
        Feature(
            case_id="U:new",
            artifact_id="n1",
            name="person.public_figure",
            value="rafal-brzoska",
            confidence=0.8213,
            locator="bbox=100,80,60,70",
        ),
        Feature(
            case_id="U:new",
            artifact_id="n1",
            name="person.mentioned",
            value="daniel-obajtek",
            locator="from:text.ocr „Obajtkiem”",
        ),
        Feature(case_id="U:new", artifact_id="n1", name="ocr.domain", value="scam.example"),
        Feature(case_id="U:new", artifact_id="n1", name="ocr.headline", value="Pilne: Obajtek"),
        Feature(case_id="U:new", artifact_id="n1", name="brand.logo", value="tvn24"),
    ]
    return feats, [art]


def _answer() -> Assignment:
    return Assignment(
        case_id="U:new",
        decision="new",
        campaign_id=None,
        score=0.0,
        margin=0.0,
        comparable=["person"],
        evidence=[],
    )


def test_found_lists_persons_by_face_and_by_text_separately(data: RunData, tmp_path: Path) -> None:
    feats, arts = _new_case(tmp_path)
    card = verdict(_answer(), data, feats, arts)
    assert card.decision == "new"
    face, text = card.found.persons
    assert (face.slug, face.method, face.similarity_text) == ("rafal-brzoska", "face", "0,82")
    assert face.crop and face.crop.startswith("data:image/jpeg;base64,")
    assert (text.slug, text.method, text.matched) == ("daniel-obajtek", "text", "Obajtkiem")
    assert text.similarity is None and text.crop is None
    assert card.found.domains == ["scam[.]example"]
    assert card.found.headline == "Pilne: Obajtek"
    assert [(b.slug, b.method) for b in card.found.brands] == [("tvn24", "logo")]
    assert "Rozpoznano: Rafał Brzoska (twarz, podobieństwo 0,82)" in card.plain
    assert "Daniel Obajtek (wzmianka w tekście)" in card.plain


def test_shared_person_is_a_lead_not_a_link(data: RunData, tmp_path: Path) -> None:
    feats, arts = _new_case(tmp_path)
    base_case = next(iter(data.campaign_of))
    campaign = data.campaign_of[base_case]
    data.__dict__["case_traces"] = {base_case: CaseTraces(names={"daniel-obajtek"})}
    try:
        card = verdict(_answer(), data, feats, arts)
    finally:
        del data.__dict__["case_traces"]
    assert card.decision == "new" and card.campaign is None
    (similar,) = card.similar
    assert similar.campaign.id == campaign.id and similar.score == 0.0
    assert similar.traces == ["ta sama osoba: Daniel Obajtek (wzmianka w tekście)"]
    text = next(p for p in card.found.persons if p.method == "text")
    assert [c.id for c in text.campaigns] == [campaign.id] and text.reports == 1
    assert "występuje też w kampanii" in card.plain and "nie dowód" in card.plain


def test_verdict_without_features_stays_backward_compatible(data: RunData) -> None:
    card = verdict(_answer(), data)
    assert card.found.persons == [] and card.similar == []
    assert "Rozpoznano" not in card.plain


def test_case_traces_read_names_from_old_runs_text() -> None:
    feats = [
        Feature(case_id="C:1", artifact_id="a", name="text.ocr", value="Brzoska i Obajtek"),
        Feature(case_id="C:1", artifact_id="a", name="person.public_figure", value="x-y"),
        Feature(case_id="C:1", artifact_id="a", name="url.domain", value="a.example"),
    ]
    traces = case_traces(feats)["C:1"]
    assert {"rafal-brzoska", "daniel-obajtek"} <= traces.names
    assert traces.faces == {"x-y": 1.0} and traces.domains == {"a.example"}
    assert traces.persons >= {"x-y", "rafal-brzoska"}


def test_similarity_uses_polish_decimal_comma() -> None:
    assert similarity_text(0.8213) == "0,82"


def test_named_persons_show_up_in_case_and_campaign_views(data: RunData) -> None:
    base_case = next(iter(data.campaign_of))
    campaign = data.campaign_of[base_case]
    data.__dict__["case_traces"] = {base_case: CaseTraces(names={"daniel-obajtek"})}
    try:
        detail = data.case_detail(base_case)
        assert detail is not None
        named = [r for r in detail.recognised if r.method == "text"]
        assert [(r.name, r.kind, r.members) for r in named] == [("Daniel Obajtek", "person", [0])]
        in_campaign = data.campaign_recognised(campaign)
        assert any(r.method == "text" and r.name == "Daniel Obajtek" for r in in_campaign)
    finally:
        del data.__dict__["case_traces"]


def test_brands_named_in_text() -> None:
    from fakecollector.api.found import brands_in_text

    assert brands_in_text("Glapiński wyszedł ze studia TVN24, a InPostem…") == ["tvn24", "inpost"]
    assert brands_in_text("onetowy kolor i zusammen") == []
