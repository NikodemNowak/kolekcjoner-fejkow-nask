"""Benchmark the Workstream B (vision/video) pipeline on both corpora.

Three runs of the full B profile, each in its own process so the device choice and model
caches start clean:

* **GPU cold**: empty temporary feature cache and keyframe dir (every model runs);
* **GPU warm**: the same cache again (should do zero model work);
* **CPU cold**: `FAKECOLLECTOR_DEVICE=cpu`, a fresh empty cache (ASR follows the CPU default).

Per stage it reports wall time, images/s, features and peak GPU memory
(`torch.cuda.max_memory_allocated`; n/a for ONNX Runtime / CTranslate2 stages), then checks that
CPU features equal GPU features (pHash, PDQ, face slugs, OCR domains exactly; SigLIP cosine
>= 0.999). Writes `docs/benchmark-vision.md` (numbers only, never corpus text).

With `--cpu-cases N` the CPU run covers a deterministic subset of N cases and each stage's
time is extrapolated to the full corpus by its unique-image count (stated in the report).

Usage:
    PYTHONPATH=src python scripts/benchmark_vision.py [--cpu-cases N] [--skip-cpu]
        [--out docs/benchmark-vision.md]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TORCH_STAGES = {"image_siglip", "ocr"}  # stages whose GPU memory torch can see
OTHER_RUNTIME = {"face": "ORT", "asr": "CT2"}


# --------------------------------------------------------------------------- worker


def worker(args: argparse.Namespace) -> int:
    """Run the pipeline once in this process and write `bench.json` plus the run directory."""
    os.environ["FAKECOLLECTOR_DEVICE"] = args.device
    from fakecollector.dev.run_b import (
        DEFAULT_CORPORA,
        FeatureCache,
        StageStats,
        library_versions,
        resolve_stages,
        run_pipeline,
        write_run,
    )
    from fakecollector.models import device

    peaks: dict[str, int | None] = {}
    torch_mod: Any = None
    try:
        import torch

        if device() == "cuda":
            torch_mod = torch
    except ImportError:
        pass

    def start(stage: str) -> None:
        if torch_mod is not None:
            torch_mod.cuda.synchronize()
            torch_mod.cuda.reset_peak_memory_stats()

    def end(stats: StageStats) -> None:
        if torch_mod is None:
            peaks[stats.name] = None
            return
        torch_mod.cuda.synchronize()
        peaks[stats.name] = int(torch_mod.cuda.max_memory_allocated())

    cache = FeatureCache(args.cache_dir)
    corpora = [(ROOT / root, corpus) for root, corpus in DEFAULT_CORPORA]
    cases = {c for c in args.cases.split(",") if c} or None
    t0 = time.perf_counter()
    result = run_pipeline(corpora, resolve_stages(None), cache, args.cache_dir, cases, start, end)
    total = time.perf_counter() - t0
    meta = {"pipeline": "b_vision_bench", "device": device(), "total_seconds": round(total, 2)}
    write_run(result, args.run_out, {**meta, "versions": {"libraries": library_versions()}})
    videos = {a.id for a in result.artifacts if a.kind == "video"}
    hashed = next((s.unique for s in result.stages if s.name == "image_hash"), 0)
    bench = {
        **meta,
        "cases": len({a.case_id for a in result.artifacts}),
        "artifacts": len(result.artifacts),
        "unique_images": hashed,
        "keyframes": sum(1 for a in result.artifacts if a.parent_id in videos),
        "features": len(result.features),
        "cache_hits": cache.hits,
        "cache_misses": cache.misses,
        "stages": [{**vars(s), "peak_gpu_bytes": peaks.get(s.name)} for s in result.stages],
    }
    (args.run_out / "bench.json").write_text(json.dumps(bench, indent=2))
    return 0


# --------------------------------------------------------------------------- driver


def run_mode(
    name: str, dev: str, cache_dir: Path, run_out: Path, cases: list[str] | None
) -> dict[str, Any]:
    """Spawn one worker process and return its `bench.json` plus the outer wall time."""
    env = {**os.environ, "FAKECOLLECTOR_DEVICE": dev}
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--device",
        dev,
        "--cache-dir",
        str(cache_dir),
        "--run-out",
        str(run_out),
        "--cases",
        ",".join(cases or []),
    ]
    print(f"[{name}] running on {dev}" + (f", {len(cases)} cases" if cases else ""), flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, text=True, check=False)
    wall = time.perf_counter() - t0
    errors = [ln for ln in proc.stderr.splitlines() if " ERROR " in ln or "Traceback" in ln]
    warnings = sum(1 for ln in proc.stderr.splitlines() if " WARNING " in ln)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:])
        raise SystemExit(f"[{name}] worker failed with exit code {proc.returncode}")
    bench: dict[str, Any] = json.loads((run_out / "bench.json").read_text())
    bench.update(name=name, wall_seconds=round(wall, 2), errors=errors, warnings=warnings)
    print(f"[{name}] done in {wall:.1f} s ({warnings} warnings, {len(errors)} errors)", flush=True)
    return bench


def load_features(run_dir: Path) -> tuple[list[tuple[str, str, str]], dict[str, Any], set[str]]:
    """Read `(artifact_id, name, value)` rows, SigLIP vectors and artifact ids of a run."""
    import numpy as np
    import pyarrow.parquet as pq

    from fakecollector.dev.bench import first_vectors

    feats = pq.read_table(run_dir / "features.parquet", columns=["artifact_id", "name", "value"])
    rows = list(
        zip(*(feats.column(c).to_pylist() for c in ("artifact_id", "name", "value")), strict=True)
    )
    arts = set(pq.read_table(run_dir / "artifacts.parquet", columns=["id"]).column(0).to_pylist())
    vec_path = run_dir / "vectors" / "img.siglip.npy"
    vectors: dict[str, Any] = {}
    if vec_path.exists():
        ids = pq.read_table(run_dir / "vectors" / "img.siglip.index.parquet")["artifact_id"]
        vectors = first_vectors(ids.to_pylist(), np.load(vec_path))
    return rows, vectors, arts


def equality(gpu_dir: Path, cpu_dir: Path) -> list[Any]:
    """Compare CPU features against GPU features over the artifacts the CPU run covered."""
    from fakecollector.dev.bench import (
        EXACT_FEATURES,
        INFO_FEATURES,
        VECTOR_FEATURES,
        compare_values,
        compare_vectors,
        value_sets,
    )

    g_rows, g_vec, _ = load_features(gpu_dir)
    c_rows, c_vec, universe = load_features(cpu_dir)
    g_sets, c_sets = value_sets(g_rows, universe), value_sets(c_rows, universe)
    out = [compare_values(g_sets, c_sets, n) for n in EXACT_FEATURES]
    for name, thr in VECTOR_FEATURES.items():
        out.append(
            compare_vectors(
                {k: v for k, v in g_vec.items() if k in universe},
                {k: v for k, v in c_vec.items() if k in universe},
                name,
                thr,
            )
        )
    out += [compare_values(g_sets, c_sets, n, required=False) for n in INFO_FEATURES]
    return out


def hardware() -> dict[str, str]:
    """GPU, CPU and RAM description (no host names)."""
    info = {"os": platform.platform(terse=True), "python": platform.python_version()}
    try:
        import torch

        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            info["gpu"] = f"{p.name}, {p.total_memory / 2**30:.0f} GiB, CUDA {torch.version.cuda}"
    except ImportError:
        pass
    cpu = platform.processor() or "cpu"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    info["cpu"] = f"{cpu}, {os.cpu_count()} logical cores"
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        kb = int(meminfo.read_text().split()[1])
        info["ram"] = f"{kb / 2**20:.0f} GiB"
    return info


def stage_rows(bench: dict[str, Any], full: dict[str, Any] | None = None) -> list[list[str]]:
    """Table rows for one run; with `full` (the GPU cold run) also an extrapolated time."""
    from fakecollector.dev.bench import extrapolate, fmt, rate

    full_by = {s["name"]: s for s in full["stages"]} if full else {}
    rows = []
    for s in bench["stages"]:
        name = s["name"]
        if name == "scan":
            continue
        peak = s.get("peak_gpu_bytes")
        if bench["device"] != "cuda":
            mem = "–"
        elif name in TORCH_STAGES and peak is not None:
            mem = f"{peak / 2**20:.0f}"
        else:
            mem = f"n/a ({OTHER_RUNTIME[name]})" if name in OTHER_RUNTIME else "–"
        # Keyframes: frames per second of decoding; below 0.1 s a rate is only rounding noise.
        unit = s["features"] if name == "keyframes" else s["computed"]
        speed = rate(unit, s["seconds"]) if s["seconds"] >= 0.1 else None
        row = [
            name if s["version"] != "skipped" else f"{name} (off)",
            fmt(s["unique"]),
            fmt(s["computed"]),
            fmt(s["cached"]),
            fmt(s["features"]),
            fmt(s["seconds"]),
            fmt(speed),
            mem,
        ]
        if full is not None:
            f = full_by.get(name)
            est = extrapolate(s["seconds"], s["unique"], f["unique"]) if f else None
            row.append(fmt(est))
        rows.append(row)
    return rows


def render(
    runs: dict[str, dict[str, Any]],
    eq: list[Any],
    hw: dict[str, str],
    cpu_subset: list[str] | None,
) -> str:
    """Build `docs/benchmark-vision.md` (numbers and stage names only)."""
    from fakecollector.dev.bench import fmt, markdown_table

    gpu = runs["gpu_cold"]
    lines = [
        "# Vision pipeline benchmark (Workstream B, `full` profile)",
        "",
        "Generated by `scripts/benchmark_vision.py` on "
        f"{time.strftime('%Y-%m-%d')}. Stages: keyframes, image_hash (pHash + PDQ), "
        "image_siglip (SigLIP2 + brand crops), face (InsightFace buffalo_l), ocr (easyocr "
        "pl+en), ad_library, asr (faster-whisper). Numbers only; no corpus content.",
        "",
        "## Hardware",
        "",
        *[f"- **{k}**: {v}" for k, v in hw.items()],
        "",
        "## Corpora",
        "",
        f"Both corpora (NASK backup + mentor): {gpu['cases']} cases, {gpu['artifacts']} "
        f"artifacts including {gpu['keyframes']} video keyframes, {gpu['unique_images']} "
        "unique images (screenshots, landing images and keyframes) for the image stages.",
        "",
        "## Summary",
        "",
    ]
    summary = []
    labels = {"gpu_cold": "GPU cold", "gpu_warm": "GPU warm (cache)", "cpu_cold": "CPU cold"}
    for key, run in runs.items():
        note = ""
        if key == "cpu_cold" and cpu_subset:
            note = f" (subset {run['cases']} cases)"
        summary.append(
            [
                labels[key] + note,
                run["device"],
                fmt(run["cases"]),
                fmt(run["features"]),
                fmt(run["total_seconds"]),
                fmt(run["wall_seconds"]),
                fmt(run["cache_hits"]),
                fmt(sum(s["computed"] for s in run["stages"] if s["name"] != "keyframes")),
                fmt(len(run["errors"])),
            ]
        )
    lines.append(
        markdown_table(
            [
                "Run",
                "Device",
                "Cases",
                "Features",
                "Pipeline s",
                "Process wall s",
                "Cache hits",
                "Model calls",
                "Errors",
            ],
            summary,
        )
    )
    if cpu_subset and "cpu_cold" in runs:
        cpu = runs["cpu_cold"]
        est = sum(float(r[-1]) for r in stage_rows(cpu, gpu) if r[-1] != "–")
        lines += [
            "",
            f"The CPU run covered a deterministic subset of {len(cpu_subset)} cases (smallest "
            f"sha256 of the case id) because the full CPU run exceeds 25 min; extrapolated "
            f"full-corpus CPU time by unique images per stage: **≈ {est / 60:.0f} min**.",
        ]
    lines += [
        "",
        "Pipeline s = time inside `run_pipeline` (scan, keyframes, extractors incl. model "
        "loading); process wall s adds interpreter start and imports. Model calls = unique "
        "artifacts computed (0 means every feature came from the cache).",
    ]
    for key, run in runs.items():
        headers = [
            "Stage",
            "Unique",
            "Computed",
            "Cached",
            "Features",
            "Seconds",
            "Images/s",
            "Peak GPU MiB",
        ]
        full = gpu if key == "cpu_cold" and cpu_subset else None
        if full:
            headers.append("Full-corpus s (extrap.)")
        lines += ["", f"## {labels[key]}", "", markdown_table(headers, stage_rows(run, full))]
    lines += [
        "",
        "Images/s = computed unique artifacts per second (frames decoded for keyframes, videos "
        "for asr; – when the stage took < 0.1 s). Peak "
        "GPU memory is `torch.cuda.max_memory_allocated` per stage; InsightFace (ONNX Runtime) "
        "and faster-whisper (CTranslate2) allocate outside torch, so they show n/a.",
    ]
    if eq:
        rows = [
            [
                e.name,
                e.rule,
                fmt(e.artifacts),
                fmt(e.equal),
                fmt(e.min_cosine, 6) if e.min_cosine is not None else "–",
                ("yes" if e.ok else "NO") if e.required else ("yes" if e.ok else "info"),
            ]
            for e in eq
        ]
        passed = all(e.ok for e in eq if e.required)
        lines += [
            "",
            "## CPU features vs GPU features",
            "",
            "Compared per unique artifact over the artifacts of the CPU run. Required: exact "
            "pHash, PDQ, face slugs and OCR domains; SigLIP cosine ≥ 0.999 (GPU runs FP16, CPU "
            "FP32). OCR text, advertiser and brand rows are informational.",
            "",
            markdown_table(["Feature", "Rule", "Artifacts", "Equal", "Min cosine", "Pass"], rows),
            "",
            f"**Result: {'PASS' if passed else 'FAIL'}.**",
        ]
    asr = next((s for s in runs.get("cpu_cold", {}).get("stages", []) if s["name"] == "asr"), None)
    if asr is not None and asr["version"] == "skipped":
        lines += [
            "",
            "ASR is off on CPU by default (`FAKECOLLECTOR_ASR=1` forces it with the `small` "
            "model); every other stage of the `full` profile ran on CPU.",
        ]
    return "\n".join(lines) + "\n"


def summary(runs: dict[str, dict[str, Any]], eq: list[Any]) -> None:
    """Print a short console summary."""
    for key, run in runs.items():
        print(
            f"{key:9} device={run['device']:4} cases={run['cases']:3} "
            f"features={run['features']:5} pipeline={run['total_seconds']:7.1f}s "
            f"wall={run['wall_seconds']:7.1f}s hits={run['cache_hits']:4} "
            f"errors={len(run['errors'])}"
        )
    for e in eq:
        extra = f" min_cos={e.min_cosine}" if e.min_cosine is not None else ""
        print(f"  {e.name:22} {e.rule:11} {e.equal}/{e.artifacts}{extra}")


def driver(args: argparse.Namespace) -> int:
    """Run the three modes, compare features and write the report."""
    from fakecollector.dev.bench import subset_cases

    work = Path(tempfile.mkdtemp(prefix="bench_vision_", dir=args.workdir))
    runs: dict[str, dict[str, Any]] = {}
    eq: list[Any] = []
    cpu_subset: list[str] | None = None
    load_start = os.getloadavg()[0]
    try:
        gpu_cache = work / "cache_gpu"
        runs["gpu_cold"] = run_mode("gpu_cold", "cuda", gpu_cache, work / "gpu_cold", None)
        runs["gpu_warm"] = run_mode("gpu_warm", "cuda", gpu_cache, work / "gpu_warm", None)
        if not args.skip_cpu:
            if args.cpu_cases > 0:
                import pyarrow.parquet as pq

                ids = pq.read_table(work / "gpu_cold" / "artifacts.parquet", columns=["case_id"])
                cpu_subset = subset_cases(ids.column(0).to_pylist(), args.cpu_cases)
            runs["cpu_cold"] = run_mode(
                "cpu_cold", "cpu", work / "cache_cpu", work / "cpu_cold", cpu_subset
            )
            eq = equality(work / "gpu_cold", work / "cpu_cold")
        hw = hardware()
        # Other agents share this machine; the load shows how far CPU timings are inflated.
        hw["load average (1 min)"] = (
            f"{load_start:.1f} at start, {os.getloadavg()[0]:.1f} at end "
            f"on {os.cpu_count()} logical cores"
        )
        report = render(runs, eq, hw, cpu_subset)
        args.out.write_text(report)
        (work / "runs.json").write_text(json.dumps(runs, indent=2))
        summary(runs, eq)
        print(f"report -> {args.out}")
    finally:
        if args.keep:
            print(f"kept work dir {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return 0


def main() -> int:
    """Parse flags and dispatch to the driver or a worker."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "benchmark-vision.md")
    parser.add_argument("--cpu-cases", type=int, default=0, help="CPU subset size (0 = all)")
    parser.add_argument("--skip-cpu", action="store_true")
    parser.add_argument("--keep", action="store_true", help="keep temporary caches and runs")
    parser.add_argument("--workdir", type=Path, default=None, help="parent of the temp dir")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--device", default="auto", help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--run-out", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--cases", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    return worker(args) if args.worker else driver(args)


if __name__ == "__main__":
    sys.exit(main())
