from __future__ import annotations

import pytest

from fakecollector.evaluation.metrics import adjusted_rand_index, bcubed, compression, pairwise

GOLD = {"a": "A", "b": "A", "c": "B", "d": "B"}


def test_perfect_partitions_agree_even_with_different_label_names() -> None:
    predicted = {"a": "1", "b": "1", "c": "2", "d": "2"}

    assert tuple(pairwise(predicted, GOLD)) == (1.0, 1.0, 1.0)
    assert tuple(bcubed(predicted, GOLD)) == (1.0, 1.0, 1.0)
    assert adjusted_rand_index(predicted, GOLD) == 1.0


def test_all_in_one_cluster() -> None:
    predicted = dict.fromkeys(GOLD, "A")

    assert tuple(pairwise(predicted, GOLD)) == pytest.approx((1 / 3, 1, 1 / 2))
    assert tuple(bcubed(predicted, GOLD)) == pytest.approx((1 / 2, 1, 2 / 3))
    assert adjusted_rand_index(predicted, GOLD) == 0.0


def test_all_singletons() -> None:
    predicted = {case: case for case in GOLD}

    assert tuple(pairwise(predicted, GOLD)) == (0.0, 0.0, 0.0)
    assert tuple(bcubed(predicted, GOLD)) == pytest.approx((1, 1 / 2, 2 / 3))
    assert adjusted_rand_index(predicted, GOLD) == 0.0
    assert tuple(pairwise(predicted, predicted)) == (1.0, 1.0, 1.0)
    assert adjusted_rand_index(predicted, predicted) == 1.0


def test_crossed_pairs_have_negative_adjusted_rand_index() -> None:
    predicted = {"a": "1", "b": "2", "c": "1", "d": "2"}

    assert adjusted_rand_index(predicted, GOLD) == -0.5


def test_compression() -> None:
    assert compression(25, 24, 16, 4) == (
        "25 zgłoszeń → 24 unikatowych → 16 kampanii → 4 operatorów"
    )
