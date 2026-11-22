"""Assignment explanations: one line per trace, and the closest campaign for new/review."""

from __future__ import annotations

from fakecollector.core.schemas import Evidence
from fakecollector.graph.analyze import analyze
from fakecollector.graph.assign import NEAREST_KIND, assign, dedupe_evidence

from .test_graph import feat


def _ev(weight: float, artifact: str, detail: str = "Wspólny wzorzec nagłówka: x") -> Evidence:
    return Evidence(
        family="text",
        tier="campaign",
        kind="text.headline_tpl",
        value="x",
        detail=detail,
        weight=weight,
        artifacts=[artifact],
    )


def test_same_trace_from_several_members_is_one_line() -> None:
    lines = dedupe_evidence([_ev(0.4, "a"), _ev(0.6, "b"), _ev(0.5, "c", "Inny nagłówek")])
    assert [(e.detail, e.weight, e.artifacts) for e in lines] == [
        ("Wspólny wzorzec nagłówka: x", 0.6, ["a", "b"]),
        ("Inny nagłówek", 0.5, ["c"]),
    ]


def test_assignment_evidence_has_no_duplicate_lines() -> None:
    members = ("x1", "x2", "x3")
    base_features = [feat(case, "ids.kit_landing", "kit-x") for case in members]
    base_features += [
        feat(case, "text.headline_tpl", "pilne wiadomości z kraju") for case in members
    ]
    base_features += [feat("y", "url.domain", "other.test")]
    base = analyze(base_features)
    (result,) = assign(
        [feat("new", "text.headline_tpl", "pilne wiadomości z kraju")], base, base_features
    )
    details = [item.detail for item in result.evidence]
    assert len(details) == len(set(details))


def test_new_answer_names_closest_campaign_and_gap_to_tau() -> None:
    base_features = [
        *(feat(case, "ids.kit_landing", "kit-x") for case in ("x1", "x2")),
        *(feat(case, "person.public_figure", "osoba-testowa") for case in ("x1", "x2")),
        feat("y", "url.domain", "other.test"),
    ]
    base = analyze(base_features)
    (result,) = assign([feat("new", "person.public_figure", "osoba-testowa")], base, base_features)
    assert result.decision == "new"
    (note,) = [item for item in result.evidence if item.kind == NEAREST_KIND]
    assert note.weight == 0.0
    assert note.value == next(c.id for c in base.campaigns if "x1" in c.case_ids)
    assert note.detail.startswith("Najbliższa kampania:")
    assert "poniżej progu τ = 0.60" in note.detail
    assert f"{0.6 - result.score:.2f}" in note.detail
