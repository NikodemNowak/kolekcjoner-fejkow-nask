from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_evaluate_script_on_fixtures(tmp_path: Path) -> None:
    pytest.importorskip("fakecollector.graph.analyze")
    out = tmp_path / "results.md"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate.py",
            "data/fixtures/cases",
            "--gold",
            "data/fixtures/gold_labels_fixtures.csv",
            "--corpus-prefix",
            "F",
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = out.read_text(encoding="utf-8")
    assert "Fixture run" in report
    assert "6 zgłoszeń" in report
    assert all(section in report for section in ("Campaign", "Operator", "Open-set", "Ablation"))
    assert report.index("### Ablation\n") < report.index("### Ablation by input type\n")
    assert all(
        f"| {name} |" in report
        for name in ("screenshot_only", "har_only", "html_only", "video_only", "all")
    )
    assert "Calibration used the" in report
    assert "| Campaign | 1.000 | 1.000 | 1.000 |" in report
    assert result.stdout.strip() == str(out)
