from __future__ import annotations

from itertools import combinations
from pathlib import Path

from fakecollector.evaluation.gold import load_gold


def test_disputed_campaign_can_be_loaded_strict_or_lenient(tmp_path: Path) -> None:
    gold_path = tmp_path / "gold.csv"
    gold_path.write_text(
        "case_id,campaign,operator,toolkit,note\n"
        "B:p5,D,O4,aio-kit;order-lander,Disputed\n"
        "M:3,D,O4,,Disputed\n"
        "M:5,,,,Missing campaign label\n",
        encoding="utf-8",
    )

    strict = load_gold(gold_path)
    lenient = load_gold(gold_path, strict=False)

    assert strict["B:p5"].campaign == strict["M:3"].campaign == "D"
    assert lenient["B:p5"].campaign == "S:B:p5"
    assert lenient["M:3"].campaign == "S:M:3"
    assert lenient["M:3"].operator == "O4"
    assert lenient["B:p5"].toolkit == ["aio-kit", "order-lander"]
    assert lenient["B:p5"].note == "Disputed"
    assert strict["M:5"] == lenient["M:5"]
    assert strict["M:5"].operator is None
    assert strict["M:5"].campaign == "S:M:5"


def test_real_gold_covers_documented_cases_and_pairs() -> None:
    gold_path = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "gold_labels.csv"
    strict = load_gold(gold_path)
    lenient = load_gold(gold_path, strict=False)

    assert len(strict) == 25
    assert sum(label.campaign.startswith("S:") for label in strict.values()) == 11
    assert sum(label.campaign.startswith("S:") for label in lenient.values()) == 13
    assert sum(a.campaign == b.campaign for a, b in combinations(strict.values(), 2)) == 19
    assert sum(a.campaign == b.campaign for a, b in combinations(lenient.values(), 2)) == 18
    assert {label.operator for label in strict.values()} == {None, "O1", "O2", "O3", "O4"}
    assert {toolkit for label in strict.values() for toolkit in label.toolkit} == {
        "aio-kit",
        "order-lander",
    }
