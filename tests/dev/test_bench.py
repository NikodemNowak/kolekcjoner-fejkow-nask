"""Tests for the pure vision-benchmark helpers (no models)."""

from __future__ import annotations

import numpy as np

from fakecollector.dev.bench import (
    compare_values,
    compare_vectors,
    extrapolate,
    first_vectors,
    fmt,
    markdown_table,
    rate,
    subset_cases,
    value_sets,
)


def test_value_sets_dedupes_by_artifact_and_respects_universe() -> None:
    rows = [("a", "img.phash", "x"), ("a", "img.phash", "x"), ("b", "img.phash", "y")]
    sets = value_sets(rows)
    assert sets == {"img.phash": {"a": frozenset({"x"}), "b": frozenset({"y"})}}
    assert value_sets(rows, universe={"b"}) == {"img.phash": {"b": frozenset({"y"})}}


def test_compare_values_counts_missing_side_as_unequal() -> None:
    gpu = value_sets([("a", "url.domain", "x.pl"), ("b", "url.domain", "y.pl")])
    cpu = value_sets([("a", "url.domain", "x.pl")])
    eq = compare_values(gpu, cpu, "url.domain")
    assert (eq.artifacts, eq.equal, eq.ok, eq.rule) == (2, 1, False, "exact")


def test_compare_values_absent_feature_is_trivially_equal() -> None:
    eq = compare_values({}, {}, "person.public_figure")
    assert eq.artifacts == 0
    assert eq.ok


def test_compare_vectors_threshold_and_min_cosine() -> None:
    v = np.array([1.0, 0.0])
    near = np.array([1.0, 0.01])
    far = np.array([0.0, 1.0])
    eq = compare_vectors({"a": v, "b": v}, {"a": near, "b": far}, "img.siglip", 0.999)
    assert eq.artifacts == 2
    assert eq.equal == 1
    assert eq.min_cosine == 0.0
    assert not eq.ok


def test_compare_vectors_missing_artifact_fails() -> None:
    eq = compare_vectors({"a": np.ones(3)}, {}, "img.siglip", 0.999)
    assert (eq.artifacts, eq.equal, eq.min_cosine) == (1, 0, None)


def test_first_vectors_keeps_first_occurrence() -> None:
    vecs = np.array([[1.0], [2.0], [3.0]])
    out = first_vectors(["a", "a", "b"], vecs, universe={"a"})
    assert list(out) == ["a"]
    assert out["a"][0] == 1.0


def test_rate_and_extrapolate() -> None:
    assert rate(10, 2.0) == 5.0
    assert rate(0, 2.0) is None
    assert rate(5, 0.0) is None
    assert extrapolate(10.0, 5, 20) == 40.0
    assert extrapolate(3.0, 0, 0) == 3.0


def test_subset_cases_is_deterministic_and_order_free() -> None:
    ids = [f"B:p{i}" for i in range(1, 16)]
    first = subset_cases(ids, 5)
    assert first == subset_cases(list(reversed(ids)) + ids, 5)
    assert len(first) == 5
    assert set(first) <= set(ids)
    assert subset_cases(ids, 0) == sorted(ids)


def test_markdown_table_and_fmt() -> None:
    table = markdown_table(["a", "b"], [[fmt(1), fmt(2.345, 2)], [fmt(None), "x"]])
    assert table.splitlines() == ["| a | b |", "|---|---:|", "| 1 | 2.35 |", "| – | x |"]
