"""B2e: URL-only inputs on an unseen domain are flagged "insufficient_data", not just "new"."""

from __future__ import annotations

from fakecollector.core.schemas import Assignment, Feature
from fakecollector.graph.coverage import (
    INSUFFICIENT_DATA,
    annotate_coverage,
    is_url_only,
    schema_notes,
    schema_similarity,
)


def _f(case: str, name: str, value: str, locator: str = "url") -> Feature:
    return Feature(case_id=case, artifact_id=f"{case}-a", name=name, value=value, locator=locator)


def _new(case: str, decision: str = "new") -> Assignment:
    return Assignment(
        case_id=case,
        decision=decision,
        campaign_id=None,
        score=0.0,
        margin=0.0,  # type: ignore[arg-type]
        comparable=[],
        evidence=[],
    )


BASE = [
    _f("B:1", "url.domain", "znana-strona.example", "page"),
    _f("B:1", "url.schema", "/{id}/landing?ad_id&adset_id&utm_source", "page"),
    _f("B:2", "url.schema", "/?utm_campaign&utm_source&fbclid", "page"),
]


def test_url_on_unseen_domain_is_insufficient_data() -> None:
    new = [
        _f("U:1", "url.domain", "nowa-strona.example"),
        _f("U:1", "url.schema", "/{id}/landing?ad_id&adset_id&utm_medium"),
    ]
    (out,) = annotate_coverage([_new("U:1")], new, BASE)
    assert out.decision == "new" and out.flags == [INSUFFICIENT_DATA]
    assert [e.artifacts for e in out.evidence] == [["B:1"]]  # schema hint, B:2 shares only utm
    assert all(e.weight == 0.0 for e in out.evidence)


def test_known_domain_or_content_is_not_flagged() -> None:
    known = [_f("U:2", "url.domain", "znana-strona.example")]
    with_content = [
        _f("U:3", "url.domain", "nowa-strona.example"),
        _f("U:3", "img.pdq", "0" * 64, ""),
    ]
    out = annotate_coverage([_new("U:2"), _new("U:3")], [*known, *with_content], BASE)
    assert [a.flags for a in out] == [[], []]


def test_review_or_existing_is_never_flagged() -> None:
    new = [_f("U:4", "url.domain", "nowa-strona.example")]
    assert annotate_coverage([_new("U:4", "review")], new, BASE)[0].flags == []


def test_url_only_needs_comparable_features() -> None:
    assert not is_url_only([])
    assert not is_url_only([_f("U:5", "text.ocr", "x", "")])  # info only, from an image


def test_schema_similarity_ignores_generic_tracking() -> None:
    assert schema_similarity("/?utm_source&fbclid", "/?utm_campaign&fbclid&gclid") == 0.0
    assert schema_similarity("/a/b?ad_id", "/a/b?ad_id") == 1.0
    assert schema_notes([_f("U:6", "url.domain", "x.example")], BASE) == []
