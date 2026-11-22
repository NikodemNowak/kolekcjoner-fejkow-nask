"""Input coverage notes for assignments: say "za mało danych" instead of a confident "new".

A bare URL (or domain) of a page that is not in the base carries only `url.domain` and
`url.schema` (plus tracking parameters). When none of these values occur in the base, the
assign path answers "new" with score 0.00, which reads as "this is a new campaign" although
the system simply had nothing to compare (audit 03: 21 of 24 URL-only misses are a variant on
a new domain, unlinkable offline). The decision literal stays "new" (data contract); this
module adds `Assignment.flags = ["insufficient_data"]` for the UI to show
"Za mało danych" and, when cheap, the base cases whose URL path shape is similar as
zero-weight review evidence. Pure functions, no network.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Assignment, Evidence, Feature

INSUFFICIENT_DATA = "insufficient_data"
"""`Assignment.flags` / `Case.flags` value; Polish UI label: "Za mało danych"."""

URL_ONLY_LOCATORS = frozenset({"url", "input"})
"""Locators of features the pipeline derives from a typed URL itself (no fetched content)."""

SCHEMA_MIN_SIMILARITY = 0.5
SCHEMA_MIN_SHARED = 2
MAX_SCHEMA_NOTES = 3
GENERIC_PARAMS = frozenset({"fbclid", "gclid", "ttclid", "msclkid", "igshid"})
"""Click ids and `utm_*` are on every ad URL, so they say nothing about a kit."""


def _comparable(features: Sequence[Feature]) -> list[Feature]:
    return [
        f for f in features if (spec := FEATURES.get(f.name)) is not None and spec.kind != "info"
    ]


def is_url_only(features: Sequence[Feature]) -> bool:
    """True when every comparable feature of a case comes from the typed URL alone."""
    comparable = _comparable(features)
    return bool(comparable) and all(f.locator in URL_ONLY_LOCATORS for f in comparable)


def schema_tokens(schema: str) -> set[str]:
    """Path segments and parameter names of a `url_schema` value, as a comparable set."""
    path, _, query = schema.partition("?")
    segments = {f"/{s}" for s in path.split("/") if s}
    params = {
        f"?{p}"
        for p in query.split("&")
        if p and p.lower() not in GENERIC_PARAMS and not p.lower().startswith("utm_")
    }
    return segments | params


def schema_similarity(a: str, b: str) -> float:
    """Jaccard similarity of two URL schemas' path segments and non-generic parameter names.

    Fewer than `SCHEMA_MIN_SHARED` shared tokens count as 0 (one shared "/" segment or one
    parameter is coincidence).
    """
    left, right = schema_tokens(a), schema_tokens(b)
    shared = len(left & right)
    if shared < SCHEMA_MIN_SHARED:
        return 0.0
    return shared / len(left | right)


def schema_notes(
    new_features: Sequence[Feature], base_features: Sequence[Feature]
) -> list[Evidence]:
    """Zero-weight evidence: base cases whose URL schema resembles the new URL's schema.

    A shared path shape or parameter set (e.g. `/{id}/landing?fbclid&utm_source`) hints at
    the same kit, but it is weak (generic CMS paths repeat across unrelated sites), so the
    notes never change the score; they tell the analyst which known cases to look at.
    """
    mine = {f.value for f in new_features if f.name == "url.schema" and f.value}
    if not mine:
        return []
    by_case: dict[str, set[str]] = defaultdict(set)
    for f in base_features:
        if f.name == "url.schema" and f.value:
            by_case[f.case_id].add(f.value)
    rows: list[tuple[float, str, str]] = []
    for case, schemas in by_case.items():
        best = max(((schema_similarity(m, s), s) for m in mine for s in schemas), default=(0.0, ""))
        if best[0] >= SCHEMA_MIN_SIMILARITY:
            rows.append((best[0], case, best[1]))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [
        Evidence(
            family="infra",
            tier="context",
            kind="url.schema",
            value=f"{sim:.2f}",
            detail=(
                f"Podobny kształt adresu jak w sprawie {case}: {schema} "
                f"(podobieństwo {sim:.0%}; tylko wskazówka, nie wpływa na wynik)"
            ),
            weight=0.0,
            artifacts=[case],
        )
        for sim, case, schema in rows[:MAX_SCHEMA_NOTES]
    ]


def annotate_coverage(
    assignments: Sequence[Assignment],
    new_features: Sequence[Feature],
    base_features: Sequence[Feature],
) -> list[Assignment]:
    """Flag URL-only "new" answers whose URL values are all unseen in the base.

    Returns copies; the decision, score and campaign are unchanged. A flagged assignment gets
    `flags=["insufficient_data"]` and up to `MAX_SCHEMA_NOTES` schema notes as evidence.
    """
    by_case: dict[str, list[Feature]] = defaultdict(list)
    for f in new_features:
        by_case[f.case_id].append(f)
    known = {(f.name, f.value) for f in _comparable(base_features)}
    out = []
    for item in assignments:
        features = by_case.get(item.case_id, [])
        comparable = _comparable(features)
        # Nothing to compare (an empty text file, a bare URL never seen in the base).
        if item.decision == "new" and (
            not comparable
            or (is_url_only(features) and not any((f.name, f.value) in known for f in comparable))
        ):
            item = item.model_copy(
                update={
                    "flags": [*item.flags, INSUFFICIENT_DATA],
                    "evidence": [*item.evidence, *schema_notes(features, base_features)],
                }
            )
        out.append(item)
    return out
