"""Evaluate clustering and open-set assignment against a labeled case corpus."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from fakecollector.evaluation.runner import evaluate

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def main() -> None:
    """Run evaluation from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dirs", nargs="+", type=Path, metavar="CASE_DIR")
    parser.add_argument("--gold", required=True, type=Path, help="Gold-label CSV")
    parser.add_argument(
        "--corpus-prefix",
        action="append",
        help="Repeat once per input root in order. Defaults to each root's directory name.",
    )
    parser.add_argument("--out", required=True, type=Path, help="Markdown report path")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        evaluate(
            args.case_dirs,
            args.gold,
            args.out,
            corpus_prefixes=args.corpus_prefix,
            fixture_run=all(path.resolve().is_relative_to(FIXTURE_ROOT) for path in args.case_dirs),
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(args.out)


if __name__ == "__main__":
    main()
