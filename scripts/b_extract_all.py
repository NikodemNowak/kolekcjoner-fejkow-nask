"""Run every Workstream B extractor over both corpora into `data/runs/b_vision/`.

Prints one line per stage (inputs, cache hits, computed, features, seconds); never corpus text.

Usage:
    PYTHONPATH=src python scripts/b_extract_all.py [--device auto|cpu|cuda] [--no-cache]
        [--only image_hash,image_siglip,face,ocr,ad_library,asr] [--cases B:p1,M:3]
        [--out data/runs/b_vision]
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Parse flags, run the pipeline, write the run directory."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--no-cache", action="store_true", help="ignore and do not fill the cache")
    parser.add_argument("--only", default="", help="comma-separated extractor names")
    parser.add_argument("--cases", default="", help="comma-separated case ids (subset run)")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "runs" / "b_vision")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Must be set before any extractor asks `fakecollector.models.device()` (it is cached).
    os.environ["FAKECOLLECTOR_DEVICE"] = args.device

    from fakecollector.dev.run_b import (
        DEFAULT_CORPORA,
        FeatureCache,
        default_cache_root,
        library_versions,
        resolve_stages,
        run_pipeline,
        write_run,
    )
    from fakecollector.models import device

    stages = resolve_stages(args.only)
    cache_root = default_cache_root()
    cache = None if args.no_cache else FeatureCache(cache_root)
    if args.no_cache:
        keyframe_dir = args.out / "keyframes_nocache"
        shutil.rmtree(keyframe_dir, ignore_errors=True)
    else:
        keyframe_dir = cache_root
    corpora = [(ROOT / root, corpus) for root, corpus in DEFAULT_CORPORA]
    cases = {c.strip() for c in args.cases.split(",") if c.strip()} or None

    t0 = time.perf_counter()
    result = run_pipeline(corpora, stages, cache, keyframe_dir, cases)
    total = time.perf_counter() - t0
    meta = {
        "pipeline": "b_vision",
        "device": device(),
        "device_flag": args.device,
        "stages_selected": stages,
        "cache": None if cache is None else str(cache_root),
        "cases_filter": sorted(cases) if cases else None,
        "total_seconds": round(total, 2),
        "versions": {
            **{s.name: s.version for s in result.stages},
            "libraries": library_versions(),
        },
    }
    write_run(result, args.out, meta)

    print(f"device={device()} stages={','.join(stages)} cache={'off' if cache is None else 'on'}")
    print(f"{'stage':12} {'inputs':>7} {'unique':>7} {'cached':>7} {'computed':>8} "
          f"{'features':>8} {'seconds':>8}")  # fmt: skip
    for s in result.stages:
        print(f"{s.name:12} {s.inputs:7} {s.unique:7} {s.cached:7} {s.computed:8} "
              f"{s.features:8} {s.seconds:8.1f}")  # fmt: skip
    n_cases = len({a.case_id for a in result.artifacts})
    print(f"total {total:.1f} s; {n_cases} cases, {len(result.artifacts)} artifacts, "
          f"{len(result.features)} features -> {args.out}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
