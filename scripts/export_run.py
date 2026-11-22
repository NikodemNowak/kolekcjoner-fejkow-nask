"""Ingest case folders, extract features, analyse, profile campaigns and write exports.

Stand-in for `fakecollector run` + `fakecollector export` until the pipeline CLI lands:
    PYTHONPATH=src python scripts/export_run.py data/nask_backup data/nask_mentor \
        --corpus-prefix B --corpus-prefix M --out data/exports/dev
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from time import perf_counter

from fakecollector.core.schemas import Artifact, Case
from fakecollector.evaluation.runner import extract_features_for_eval
from fakecollector.export import FORMATS, export_all
from fakecollector.graph.analyze import analyze
from fakecollector.graph.profile import fill_traits, rotating_summary
from fakecollector.ingest.casefolder import load_corpus


def main() -> None:
    """Run the end-to-end export from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dirs", nargs="+", type=Path, metavar="CASE_DIR")
    parser.add_argument(
        "--corpus-prefix",
        action="append",
        help="Repeat once per input root in order. Defaults to each root's directory name.",
    )
    parser.add_argument("--out", required=True, type=Path, help="Export directory")
    parser.add_argument(
        "--format",
        default=",".join(FORMATS),
        help=f"Comma-separated subset of {','.join(FORMATS)}",
    )
    parser.add_argument("--top", type=int, default=3, help="Campaign profiles to print")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    prefixes = args.corpus_prefix or [path.resolve().name for path in args.case_dirs]
    if len(prefixes) != len(args.case_dirs):
        parser.error("Provide one --corpus-prefix per case directory")
    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    if unknown := sorted(set(formats) - set(FORMATS)):
        parser.error(f"Unknown format(s): {', '.join(unknown)}")

    start = perf_counter()
    cases: list[Case] = []
    artifacts: list[Artifact] = []
    for path, prefix in zip(args.case_dirs, prefixes, strict=True):
        loaded_cases, loaded_artifacts = load_corpus(path, prefix)
        cases.extend(loaded_cases)
        artifacts.extend(loaded_artifacts)
    features, _ = extract_features_for_eval(artifacts)
    analysis = fill_traits(analyze(features, case_ids=[case.id for case in cases]))
    written = export_all(analysis, features, args.out, formats, cases, artifacts)
    elapsed = perf_counter() - start

    print(
        f"{len(cases)} cases, {len(features)} features, {len(analysis.entities)} entities, "
        f"{len(analysis.edges)} edges, {len(analysis.campaigns)} campaigns, "
        f"{len(set(analysis.operators.values()))} operators in {elapsed:.1f} s"
    )
    ranked = sorted(analysis.campaigns, key=lambda c: (-len(c.case_ids), c.id))
    for campaign in ranked[: args.top]:
        print(f"\n{campaign.id} ({len(campaign.case_ids)}): {', '.join(campaign.case_ids)}")
        print(f"  rotating: {rotating_summary(campaign.traits) or '-'}")
        for trait in campaign.traits:
            if trait.kind == "constant":
                print(
                    f"  constant {trait.tier:<8} {trait.entity_type:<14} {trait.value[:60]:<60} "
                    f"cov {trait.coverage:.2f} lift {trait.lift:.1f}"
                )
    for name, paths in written.items():
        size = sum(path.stat().st_size for path in paths)
        print(f"{name}: {len(paths)} files, {size / 1024:.1f} KiB")


if __name__ == "__main__":
    main()
