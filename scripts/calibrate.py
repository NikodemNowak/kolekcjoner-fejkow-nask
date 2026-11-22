"""Report label-free similarity-anchor calibration for a pipeline run."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterator
from pathlib import Path

from pydantic import TypeAdapter

from fakecollector.evaluation.calibration import CalibrationReport, PositiveSummary, calibrate
from fakecollector.extractors._text import read_text
from fakecollector.store import RunStore

logger = logging.getLogger(__name__)
_ROBUSTNESS = TypeAdapter(dict[str, PositiveSummary])


def _html_sources(store: RunStore) -> Iterator[str]:
    artifacts = sorted(store.artifacts(), key=lambda item: (item.case_id, item.id, item.path))
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        key = (artifact.case_id, artifact.id)
        path = artifact.path
        if artifact.kind != "html" or artifact.role != "landing_page" or key in seen:
            continue
        try:
            if path.anchor.startswith(("\\\\", "//")) or not path.is_file():
                continue
            if source := read_text(path):
                seen.add(key)
                yield source
        except OSError as exc:
            logger.warning("Skipping unavailable HTML source (%s)", type(exc).__name__)


def _format(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def _markdown(report: CalibrationReport) -> str:
    lines = [
        "# Similarity anchor calibration",
        "",
        f"Cases: {report.cases_n}. Pseudo-count: {report.n0}. Perturbation seed: {report.seed}.",
        "",
        "| Feature | Pairs | Prior lo / hi | Null n / max / q99 / q99.5 | Synthetic n / p10 |"
        " Proposed lo / hi | Verdict |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name, row in report.features.items():
        prior = f"{_format(row.prior_lo)} / {_format(row.prior_hi)}"
        null = (
            f"{row.null_n} / {_format(row.null_max)} / {_format(row.null_q99)} / "
            f"{_format(row.null_q995)}"
        )
        synthetic = (
            f"{row.synthetic_n} / {_format(row.synthetic_p10)}"
            if row.synthetic_p10 is not None
            else "0 / not measured"
        )
        proposed = f"{_format(row.proposed_lo)} / {_format(row.proposed_hi)}"
        lines.append(
            f"| `{name}` | {row.pairs_n} | {prior} | {null} | {synthetic} | {proposed} |"
            f" {row.verdict} |"
        )

    lines.extend(
        [
            "",
            "Each feature is scored on all comparable case pairs before blocking and fusion. "
            "A pair enters its null set when it shares no active campaign-tier key and no other "
            "family produces graph evidence at the current priors. Asset scores use the graph's "
            "IDF-weighted containment over active hashes before the minimum-shared-files rule. "
            "The null set is a proxy for unrelated pairs and can include real matches.",
            "",
            "Synthetic positives compare originals to one seeded variant per distinct text source, "
            "HTML artifact or eligible case asset set. Text variants drop 10–30% of tokens and "
            "swap numbers and likely names. Local HTML from the artifact table is parsed offline "
            "for block removal and CSS class renaming. Asset variants lose 30–70% of unique files "
            "(rounded to whole files). A retained subset with an active hash has containment 1. "
            "BGE has no synthetic embedding measurement.",
            "",
            "The measured lower anchor is the greater of the prior and null q99.5. The measured "
            "upper anchor is synthetic p10. Each is averaged with its prior using its own sample "
            "count `n` and prior pseudo-count `n0`, as `(n * measured + n0 * prior) / (n + n0)`. "
            "Missing measurements retain their priors. The verdict uses the lower anchor alone. "
            "The scoring interval requires an upper anchor greater than its lower anchor.",
            "",
            "## Image robustness input",
            "",
            "Pass `--robustness` a JSON object keyed by `phash/regions`, `pdq/regions`, and "
            "`siglip/regions`. Each available mode has `n` and `p10` from the pooled original-pair "
            "scores across the `scripts/b_robustness.py` transforms, excluding the flip control. "
            "That script currently writes Markdown. Export the count and percentile from the "
            "original-pair scores it uses to build the table, before display rounding. Hash scores "
            "are negative Hamming distances, converted to `1 + p10 / bits`. SigLIP uses cosine.",
            "",
            "```json",
            "{",
            '  "phash/regions": {"n": 1200, "p10": -16},',
            '  "siglip/regions": {"n": 1200, "p10": 0.82}',
            "}",
            "```",
            "",
            "## Reproducing the checked-in report",
            "",
            "The checked-in numbers come from the synthetic fixture run. Regenerate them on the "
            "real corpora on the GPU box and keep those outputs with that run.",
            "",
            "```sh",
            "uv run fakecollector demo --fixtures --out runs/calibration-fixtures",
            "uv run python scripts/calibrate.py runs/calibration-fixtures",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    """Read a run directory and write calibration statistics in Markdown and JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--robustness", type=Path)
    parser.add_argument("--n0", type=int, default=200)
    parser.add_argument("--out", type=Path, default=Path("docs/calibration.md"))
    parser.add_argument("--json", type=Path, help="JSON output (default: <run>/calibration.json)")
    args = parser.parse_args()
    if args.n0 < 0:
        parser.error("--n0 must be nonnegative")
    if not (args.run / "features.parquet").is_file():
        parser.error("run directory must contain features.parquet")
    json_path = args.json or args.run / "calibration.json"
    if args.out.resolve() == json_path.resolve():
        parser.error("Markdown and JSON need distinct output paths")

    store = RunStore(args.run)
    try:
        image_summary = (
            _ROBUSTNESS.validate_json(args.robustness.read_bytes()) if args.robustness else None
        )
        report = calibrate(
            store.all_features(),
            case_ids=[case.id for case in store.cases()],
            html_sources=_html_sources(store),
            image_summary=image_summary,
            n0=args.n0,
        )
        for path, content in (
            (args.out, _markdown(report)),
            (json_path, report.model_dump_json(indent=2) + "\n"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
