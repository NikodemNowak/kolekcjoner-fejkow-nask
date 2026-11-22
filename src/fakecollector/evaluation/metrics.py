"""Clustering metrics computed from the predicted/gold contingency counts."""

from __future__ import annotations

from collections import Counter
from typing import NamedTuple


class PRF(NamedTuple):
    """Precision, recall and their harmonic mean."""

    precision: float
    recall: float
    f1: float


def _contingency(
    predicted: dict[str, str], gold: dict[str, str]
) -> tuple[Counter[str], Counter[str], Counter[tuple[str, str]]]:
    if predicted.keys() != gold.keys():
        raise ValueError("Predicted and gold partitions must cover the same case IDs")
    return (
        Counter(predicted.values()),
        Counter(gold.values()),
        Counter((label, gold[case_id]) for case_id, label in predicted.items()),
    )


def _prf(precision: float, recall: float) -> PRF:
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return PRF(precision, recall, f1)


def _pairs(size: int) -> int:
    return size * (size - 1) // 2


def pairwise(predicted: dict[str, str], gold: dict[str, str]) -> PRF:
    """Measure same-cluster pairs, with perfect agreement when both pair sets are empty."""
    rows, cols, cells = _contingency(predicted, gold)
    predicted_pairs = sum(map(_pairs, rows.values()))
    gold_pairs = sum(map(_pairs, cols.values()))
    true_pairs = sum(map(_pairs, cells.values()))
    if predicted_pairs == gold_pairs == 0:
        return PRF(1.0, 1.0, 1.0)
    precision = true_pairs / predicted_pairs if predicted_pairs else 0.0
    recall = true_pairs / gold_pairs if gold_pairs else 0.0
    return _prf(precision, recall)


def bcubed(predicted: dict[str, str], gold: dict[str, str]) -> PRF:
    """Average each case's cluster overlap precision and recall, including the case itself."""
    rows, cols, cells = _contingency(predicted, gold)
    if not gold:
        return PRF(1.0, 1.0, 1.0)
    precision = sum(count**2 / rows[row] for (row, _), count in cells.items()) / len(gold)
    recall = sum(count**2 / cols[col] for (_, col), count in cells.items()) / len(gold)
    return _prf(precision, recall)


def adjusted_rand_index(predicted: dict[str, str], gold: dict[str, str]) -> float:
    """Measure pair agreement adjusted for chance at fixed cluster sizes."""
    rows, cols, cells = _contingency(predicted, gold)
    total = _pairs(len(gold))
    predicted_pairs = sum(map(_pairs, rows.values()))
    gold_pairs = sum(map(_pairs, cols.values()))
    true_pairs = sum(map(_pairs, cells.values()))
    expected_numerator = predicted_pairs * gold_pairs
    numerator = 2 * (true_pairs * total - expected_numerator)
    denominator = (predicted_pairs + gold_pairs) * total - 2 * expected_numerator
    return numerator / denominator if denominator else 1.0


def compression(cases: int, unique: int, campaigns: int, operators: int) -> str:
    """Format the Polish report-to-operator compression headline."""
    return (
        f"{cases} zgłoszeń → {unique} unikatowych → {campaigns} kampanii → {operators} operatorów"
    )
