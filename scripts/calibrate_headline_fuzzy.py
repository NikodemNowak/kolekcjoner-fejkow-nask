"""Derive the fuzzy-headline threshold from a run, label-free (no gold labels read).

Null: token-set ratios between headline templates of cases that the run's own clustering
put in different campaigns, pairwise and as each headline's best unrelated match. Prints
quantiles; EdgeConfig.headline_fuzzy_threshold is the q99.5 of the per-headline maxima.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from fakecollector.evaluation.calibration import headline_fuzzy_null
from fakecollector.store import RunStore


def main() -> None:
    """Print the null distribution of fuzzy headline scores for one run directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    store = RunStore(args.run_dir)
    campaigns = store.load_graph().campaigns
    by_case = {case: campaign.id for campaign in campaigns for case in campaign.case_ids}
    features = store.features(["text.headline_tpl"])
    for label, per_max in (("pairwise", False), ("per-headline max", True)):
        null = headline_fuzzy_null(features, by_case, per_headline_max=per_max)
        if not null.size:
            print(f"{label}: no unrelated template pairs")
            continue
        quantiles = ", ".join(
            f"q{q * 100:g} {np.quantile(null, q):.3f}" for q in (0.9, 0.99, 0.995)
        )
        print(f"{label}: n {null.size}, max {null.max():.3f}, {quantiles}")


if __name__ == "__main__":
    main()
