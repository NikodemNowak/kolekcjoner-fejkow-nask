from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from random import Random

import pytest

from fakecollector.core.schemas import Feature
from fakecollector.evaluation.calibration import (
    PositiveSummary,
    anchor_verdict,
    calibrate,
    perturb_text,
    summarize_anchors,
)
from fakecollector.pipeline import extract, ingest
from fakecollector.store import RunStore

ROOT = Path(__file__).resolve().parents[2]


def _feature(case: str, name: str, value: str) -> Feature:
    return Feature(case_id=case, artifact_id=case, name=name, value=value)


def test_null_excludes_campaign_keys_even_within_the_measured_family() -> None:
    # The headline key is in the same family as the MinHash under calibration.
    features = [_feature(case, "text.headline_tpl", "shared") for case in ("a", "b")] + [
        _feature(case, "text.minhash", "").model_copy(update={"vector": [value] * 128})
        for case, value in (("a", 1.0), ("b", 1.0), ("c", 2.0))
    ]
    summary = calibrate(features, case_ids=["a", "b", "c"]).features["text.minhash"]
    assert summary.pairs_n == 3
    assert (summary.null_n, summary.null_max) == (2, 0.0)


def test_null_excludes_other_families_and_keeps_stopped_campaign_keys() -> None:
    features = (
        # A platform domain on the default stop-list: campaign keys are no longer stopped by
        # batch share (PR #37), so the stop-list is what makes this shared key inactive.
        [_feature(case, "url.domain", "facebook.com") for case in "abcd"]
        + [
            _feature(case, "img.phash", value)
            for case, value in (("a", "0" * 16), ("b", "0" * 16), ("c", "f" * 16))
        ]
        + [
            _feature(case, "text.minhash", "").model_copy(update={"vector": [value] * 128})
            for case, value in (("a", 1.0), ("b", 1.0), ("c", 2.0))
        ]
    )
    report = calibrate(features, case_ids=list("abcd"))
    assert (report.features["text.minhash"].null_n, report.features["text.minhash"].null_max) == (
        2,
        0.0,
    )
    assert report.features["img.phash"].null_n == 2


@pytest.mark.parametrize(
    ("name", "values", "vectors", "expected"),
    [
        ("asset.sha256", ("first", "second"), (None, None), 0.0),
        ("img.pdq", ("0" * 64, "f" * 64), (None, None), 0.0),
        ("img.phash", ("0" * 16, "f" * 16), (None, None), 0.0),
        ("img.siglip", ("", ""), ([2.0, 0.0], [-3.0, 0.0]), -1.0),
        ("text.bge", ("", ""), ([2.0, 0.0], [-3.0, 0.0]), -1.0),
    ],
)
def test_null_keeps_raw_scores_below_the_prior(
    name: str,
    values: tuple[str, str],
    vectors: tuple[list[float] | None, list[float] | None],
    expected: float,
) -> None:
    features = [
        _feature(case, name, value).model_copy(update={"vector": vector})
        for case, value, vector in zip("ab", values, vectors, strict=True)
    ]
    row = calibrate(features).features[name]
    assert (row.pairs_n, row.null_n, row.null_max) == (1, 1, expected)


def test_anchor_quantiles_and_shrinkage() -> None:
    row = summarize_anchors(0.3, 0.7, 3, [0.0, 0.8], PositiveSummary(n=3, p10=0.4), n0=2)
    assert row.null_n == 2
    assert row.null_max == 0.8
    assert row.null_q99 == pytest.approx(0.792)
    assert row.null_q995 == pytest.approx(0.796)
    assert row.proposed_lo == pytest.approx((2 * 0.796 + 2 * 0.3) / 4)
    assert row.proposed_hi == pytest.approx((3 * 0.4 + 2 * 0.7) / 5)

    lower_null = summarize_anchors(0.3, 0.7, 1, [0.1], None, n0=0)
    assert lower_null.proposed_lo == 0.3
    assert lower_null.proposed_hi == 0.7
    empty = summarize_anchors(0.3, 0.7, 0, [], None, n0=0)
    assert empty.null_q995 is None
    assert (empty.proposed_lo, empty.proposed_hi) == (0.3, 0.7)


def test_anchor_verdict_uses_lower_anchor() -> None:
    assert anchor_verdict(0.3, 0.3) == "more conservative"
    assert anchor_verdict(0.3, 0.4) == "more conservative"
    assert anchor_verdict(0.3, 0.2) == "less conservative — keep prior"


def test_text_perturbation_is_seeded() -> None:
    source = "Anna Nowak bought 1234 red apples and 5678 yellow pears at a crowded market"
    first = perturb_text(source, Random(7))
    assert first == perturb_text(source, Random(7))
    assert first != perturb_text(source, Random(8))
    assert 10 <= len(first.split()) <= 13
    assert not {"Anna", "Nowak", "1234", "5678"}.intersection(first.split())
    assert any(word.isdecimal() for word in first.split())


def test_script_calibrates_fixture_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "fixture-run")
    ingest([ROOT / "data/fixtures/cases"], store)
    extract(store, "fast")
    report = tmp_path / "report" / "calibration.md"
    summary = store.run_dir / "calibration.json"
    command = [sys.executable, "scripts/calibrate.py", str(store.run_dir), "--out", str(report)]
    subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)

    assert "synthetic fixture run" in report.read_text(encoding="utf-8")
    results = json.loads(summary.read_text(encoding="utf-8"))
    rows = results["features"]
    assert len(rows) == 8
    assert rows["asset.sha256"]["synthetic_p10"] == 1.0
    assert rows["text.minhash"]["synthetic_n"] > 0
    assert rows["html.dom_minhash"]["synthetic_n"] > 0
    assert rows["img.phash"]["synthetic_p10"] is None
    assert rows["img.siglip"]["null_max"] is None

    robustness = tmp_path / "robustness.json"
    robustness.write_text(
        json.dumps(
            {"phash/regions": {"n": 10, "p10": -16}, "siglip/regions": {"n": 8, "p10": 0.8}}
        ),
        encoding="utf-8",
    )
    custom_json = tmp_path / "report" / "custom.json"
    subprocess.run(
        [*command, "--robustness", str(robustness), "--n0", "10", "--json", str(custom_json)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    measured = json.loads(custom_json.read_text(encoding="utf-8"))
    assert measured["n0"] == 10
    assert measured["features"]["img.phash"]["synthetic_p10"] == 0.75
    assert measured["features"]["img.siglip"]["synthetic_p10"] == 0.8
