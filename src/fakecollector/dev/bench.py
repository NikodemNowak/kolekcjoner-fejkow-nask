"""Pure helpers for the vision benchmark (`scripts/benchmark_vision.py`): no models, no I/O.

CPU and GPU runs must produce the same evidence: hashes, face slugs and OCR domains exactly,
SigLIP vectors up to FP16-vs-FP32 noise (cosine >= 0.999).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

# Features whose values must match exactly between devices (they become graph entities).
EXACT_FEATURES = ("img.phash", "img.pdq", "person.public_figure", "url.domain")
# Reported for information only: OCR text and zero-shot brand scores may drift by a character
# or a threshold crossing without changing any decision the pipeline depends on.
INFO_FEATURES = ("ad.advertiser", "brand.impersonated", "text.ocr")
VECTOR_FEATURES: Mapping[str, float] = {"img.siglip": 0.999}


@dataclass(frozen=True)
class Equality:
    """Agreement of one feature between two runs, counted over artifacts."""

    name: str
    rule: str
    artifacts: int
    equal: int
    required: bool
    min_cosine: float | None = None

    @property
    def ok(self) -> bool:
        """True when every compared artifact agrees."""
        return self.equal == self.artifacts


def value_sets(
    rows: Iterable[tuple[str, str, str]], universe: set[str] | None = None
) -> dict[str, dict[str, frozenset[str]]]:
    """Group `(artifact_id, name, value)` rows into `name -> artifact_id -> {values}`.

    Rows are deduplicated by artifact id because identical bytes in several cases carry the
    same features; `universe` restricts the artifacts considered (subset runs).
    """
    acc: dict[str, dict[str, set[str]]] = {}
    for aid, name, value in rows:
        if universe is not None and aid not in universe:
            continue
        acc.setdefault(name, {}).setdefault(aid, set()).add(value)
    return {n: {a: frozenset(v) for a, v in by.items()} for n, by in acc.items()}


def compare_values(
    a: Mapping[str, Mapping[str, frozenset[str]]],
    b: Mapping[str, Mapping[str, frozenset[str]]],
    name: str,
    required: bool = True,
) -> Equality:
    """Exact per-artifact value-set equality of feature `name` (absent counts as empty)."""
    fa, fb = a.get(name, {}), b.get(name, {})
    ids = set(fa) | set(fb)
    equal = sum(1 for i in ids if fa.get(i, frozenset()) == fb.get(i, frozenset()))
    return Equality(name=name, rule="exact", artifacts=len(ids), equal=equal, required=required)


def compare_vectors(
    a: Mapping[str, np.ndarray], b: Mapping[str, np.ndarray], name: str, threshold: float
) -> Equality:
    """Cosine agreement of per-artifact vectors; an artifact present in one run only fails."""
    ids = set(a) | set(b)
    equal = 0
    worst: float | None = None
    for i in ids:
        if i not in a or i not in b:
            continue
        va, vb = np.asarray(a[i], dtype=np.float64), np.asarray(b[i], dtype=np.float64)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        cos = float(va @ vb / denom) if denom > 0 else 0.0
        worst = cos if worst is None else min(worst, cos)
        equal += cos >= threshold
    return Equality(
        name=name,
        rule=f"cos>={threshold}",
        artifacts=len(ids),
        equal=equal,
        required=True,
        min_cosine=None if worst is None else round(worst, 6),
    )


def first_vectors(
    artifact_ids: Sequence[str], vectors: np.ndarray, universe: set[str] | None = None
) -> dict[str, np.ndarray]:
    """Map artifact id to its vector row (first occurrence wins; rows align with ids)."""
    out: dict[str, np.ndarray] = {}
    for aid, vec in zip(artifact_ids, vectors, strict=True):
        if (universe is None or aid in universe) and aid not in out:
            out[aid] = vec
    return out


def rate(items: int, seconds: float) -> float | None:
    """Items per second, or None when nothing was computed or no time was measured."""
    if items <= 0 or seconds <= 0:
        return None
    return items / seconds


def extrapolate(seconds: float, done: int, total: int) -> float:
    """Linear extrapolation of a stage's time from `done` processed items to `total`."""
    if done <= 0:
        return seconds if total <= 0 else 0.0
    return seconds * total / done


def subset_cases(case_ids: Iterable[str], n: int) -> list[str]:
    """Deterministic, name-independent subset: the `n` cases with the smallest sha256(id)."""
    ids = sorted(set(case_ids), key=lambda c: hashlib.sha256(c.encode()).hexdigest())
    return sorted(ids[:n]) if n > 0 else sorted(ids)


def fmt(x: float | int | None, digits: int = 1) -> str:
    """Format a number for a Markdown table; None becomes an en dash."""
    if x is None:
        return "–"
    if isinstance(x, int):
        return str(x)
    return f"{x:.{digits}f}"


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render a Markdown table; columns after the first are right-aligned."""
    align = ["---"] + ["---:"] * (len(headers) - 1)
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(align) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)
