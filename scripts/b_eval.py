"""Evaluate Workstream B signals alone against the gold campaign labels.

Reads a `b_extract_all.py` run directory and, for every pair of gold cases, checks which
B-only signals fire: pHash / PDQ near-duplicates (frequent images excluded), SigLIP max
cross-case screenshot cosine, shared public figures, brands, advertisers, Ad Library ids and
OCR domains. Prints per-signal precision / recall, SigLIP cosine distributions (positive vs
negative pairs, with suggested `lo` / `hi` anchors) and cross-corpus links, and writes the same
to `docs/results-vision.md`. Only numbers, signal names and case ids are printed: no corpus text.

Usage:
    PYTHONPATH=src python scripts/b_eval.py [--run data/runs/b_vision]
        [--md docs/results-vision.md] [--label "GPU warm"]
        [--timings "GPU cold=path/run.json" ...]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
PHASH_MAX = 8
PDQ_MAX = 31
MAX_DF = 0.3
DOMAIN_STOP = frozenset(
    {
        "facebook.com",
        "instagram.com",
        "google.com",
        "youtube.com",
        "fb.com",
        "fb.me",
        "messenger.com",
        "whatsapp.com",
        "apple.com",
        "play.google.com",
        "t.co",
        "twitter.com",
        "x.com",
        "tiktok.com",
        "wp.pl",
        "onet.pl",
        "gazeta.pl",
        "tvn24.pl",
    }
)
"""Platforms and the impersonated news brands themselves: shared by unrelated scams."""

Pair = tuple[str, str]


def load_gold() -> dict[str, str]:
    """Case id -> campaign label; from `data/fixtures/gold_labels.csv` or the DATA.md table."""
    csv_path = ROOT / "data" / "fixtures" / "gold_labels.csv"
    if csv_path.exists():
        with csv_path.open() as fh:
            return {r["case_id"]: r["campaign"] or r["case_id"] for r in csv.DictReader(fh)}
    text = (ROOT / "docs" / "DATA.md").read_text()
    section = text.split("## 5. Gold labels", 1)[1].split("\n## ", 1)[0]
    gold: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "Campaign" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        ids = re.findall(r"\b[BM]:\w+", cells[1])
        label = re.match(r"\*\*(\w+)\*\*", cells[0])
        for cid in ids:
            gold[cid] = label.group(1) if label else cid  # singletons get their own label
    return gold


def pair(a: str, b: str) -> Pair:
    """Ordered case pair."""
    return (a, b) if a < b else (b, a)


def _hex_bits(values: Iterable[str]) -> np.ndarray:
    """Hex hashes -> (n, bits) uint8 0/1 matrix."""
    rows = [np.unpackbits(np.frombuffer(bytes.fromhex(v), dtype=np.uint8)) for v in values]
    return np.stack(rows) if rows else np.zeros((0, 0), dtype=np.uint8)


def near_dup_pairs(feats: pl.DataFrame, name: str, max_dist: int, n_cases: int) -> dict[Pair, int]:
    """Case pairs sharing a near-duplicate image (Hamming <= max_dist), frequent images excluded.

    An image is excluded when near-duplicates of it occur in more than `MAX_DF` of the cases
    (logos, app-store badges, platform chrome).
    """
    sub = feats.filter(pl.col("name") == name)
    if sub.height == 0:
        return {}
    bits = _hex_bits(sub["value"].to_list()).astype(np.float32)
    dist = bits @ (1 - bits).T + (1 - bits) @ bits.T
    close = dist <= max_dist
    cases = np.array(sub["case_id"].to_list())
    uniq, inv = np.unique(cases, return_inverse=True)
    onehot = np.zeros((len(cases), len(uniq)), dtype=bool)
    onehot[np.arange(len(cases)), inv] = True
    df = (close.astype(np.int32) @ onehot.astype(np.int32) > 0).sum(axis=1)
    keep = df <= MAX_DF * n_cases
    out: dict[Pair, int] = defaultdict(int)
    ii, jj = np.nonzero(np.triu(close & keep[:, None] & keep[None, :], k=1))
    for i, j in zip(ii.tolist(), jj.tolist(), strict=True):
        if cases[i] != cases[j]:
            out[pair(cases[i], cases[j])] += 1
    return dict(out)


def siglip_max(run: Path, arts: pl.DataFrame, roles: set[str]) -> dict[Pair, float]:
    """Max SigLIP cosine over cross-case image pairs restricted to `roles`."""
    npy = run / "vectors" / "img.siglip.npy"
    if not npy.exists():
        return {}
    vecs = np.load(npy)
    idx = pl.read_parquet(run / "vectors" / "img.siglip.index.parquet")
    role = dict(zip(arts["id"].to_list(), arts["role"].to_list(), strict=True))
    rows = [
        (r, c)
        for r, c, a in idx.select("row", "case_id", "artifact_id").iter_rows()
        if role.get(a) in roles
    ]
    by_case: dict[str, list[int]] = defaultdict(list)
    for r, c in rows:
        by_case[c].append(r)
    sims = vecs @ vecs.T
    out: dict[Pair, float] = {}
    for a, b in combinations(sorted(by_case), 2):
        out[pair(a, b)] = float(sims[np.ix_(by_case[a], by_case[b])].max())
    return out


def shared_values(
    feats: pl.DataFrame, name: str, stop: frozenset[str] = frozenset()
) -> dict[Pair, int]:
    """Case pairs sharing any value of feature `name` -> number of shared values."""
    by_case: dict[str, set[str]] = defaultdict(set)
    for c, v in feats.filter(pl.col("name") == name).select("case_id", "value").iter_rows():
        if v and v not in stop:
            by_case[c].add(v)
    out: dict[Pair, int] = {}
    for a, b in combinations(sorted(by_case), 2):
        if n := len(by_case[a] & by_case[b]):
            out[pair(a, b)] = n
    return out


def suggest_anchors(pos: list[float], neg: list[float]) -> tuple[float, float]:
    """`lo` = 95th percentile of negatives; `hi` = just above the highest negative.

    Precision first: full weight only where no negative pair reached; capped below 1.
    """
    if not neg:
        return 0.5, 0.9
    lo = float(np.percentile(neg, 95))
    hi = min(max(float(max(neg)) + 0.01, lo + 0.05), 0.99)
    return round(lo, 3), round(hi, 3)


def _stats(xs: list[float]) -> str:
    if not xs:
        return "n=0"
    q = np.percentile(xs, [0, 25, 50, 75, 100])
    return f"n={len(xs)} min={q[0]:.3f} q1={q[1]:.3f} med={q[2]:.3f} q3={q[3]:.3f} max={q[4]:.3f}"


def main() -> int:
    """Compute the per-signal table and write the markdown report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=ROOT / "data" / "runs" / "b_vision")
    parser.add_argument("--md", type=Path, default=ROOT / "docs" / "results-vision.md")
    parser.add_argument("--label", default="current run", help="label of --run in the timings")
    parser.add_argument(
        "--timings",
        nargs="*",
        default=[],
        metavar="LABEL=RUN_JSON",
        help="extra run.json files whose stage timings join the timings table",
    )
    args = parser.parse_args()

    gold = load_gold()
    feats = pl.read_parquet(args.run / "features.parquet")
    arts = pl.read_parquet(args.run / "artifacts.parquet")
    run_meta = json.loads((args.run / "run.json").read_text())
    cases = sorted(gold)
    n = len(cases)
    all_pairs = [pair(a, b) for a, b in combinations(cases, 2)]
    positives = {p for p in all_pairs if gold[p[0]] == gold[p[1]]}
    lenient_pos = {p for p in positives if gold[p[0]] != "D"}
    feats = feats.filter(pl.col("case_id").is_in(cases))

    sig = siglip_max(args.run, arts, {"screenshot"})
    pos_cos = [sig[p] for p in positives if p in sig]
    neg_cos = [v for p, v in sig.items() if p not in positives and p in set(all_pairs)]
    lo, hi = suggest_anchors(pos_cos, neg_cos)

    signals: dict[str, set[Pair]] = {
        f"img.phash ≤{PHASH_MAX}": set(near_dup_pairs(feats, "img.phash", PHASH_MAX, n)),
        f"img.pdq ≤{PDQ_MAX}": set(near_dup_pairs(feats, "img.pdq", PDQ_MAX, n)),
        f"img.siglip ≥ lo {lo}": {p for p, v in sig.items() if v >= lo},
        f"img.siglip ≥ hi {hi}": {p for p, v in sig.items() if v >= hi},
        "person.public_figure": set(shared_values(feats, "person.public_figure")),
        "brand.impersonated": set(shared_values(feats, "brand.impersonated")),
        "ad.advertiser": set(shared_values(feats, "ad.advertiser")),
        "ids.ad_library": set(shared_values(feats, "ids.ad_library")),
        "ids.advertiser_page": set(shared_values(feats, "ids.advertiser_page")),
        "url.domain (OCR, stop-listed)": set(shared_values(feats, "url.domain", DOMAIN_STOP)),
    }
    strong = [k for k in signals if not k.startswith("img.siglip ≥ lo") and "brand" not in k]
    signals["union (all but siglip-lo, brand)"] = set().union(*(signals[k] for k in strong))
    signals = {k: v & set(all_pairs) for k, v in signals.items()}

    def coverage(name: str) -> int:
        return feats.filter(pl.col("name") == name)["case_id"].n_unique()

    lines = [
        "# Workstream B signals vs gold campaign labels",
        "",
        f"Run `{args.run.relative_to(ROOT) if args.run.is_relative_to(ROOT) else args.run}` "
        f"(device {run_meta.get('device')}, {run_meta['counts']['artifacts']} artifacts, "
        f"{run_meta['counts']['keyframes']} keyframes). Universe: {n} gold cases, "
        f"{len(all_pairs)} pairs, {len(positives)} positive (strict; {len(lenient_pos)} lenient, "
        "without disputed D). Generated by `scripts/b_eval.py`; numbers and case ids only.",
        "",
        "| Signal | Fires | TP | FP | Precision | Recall (strict) | Recall (lenient) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, fired in signals.items():
        tp, fp = len(fired & positives), len(fired - positives)
        prec = f"{tp / (tp + fp):.2f}" if fired else "–"
        rec_l = len(fired & lenient_pos) / max(len(lenient_pos), 1)
        lines.append(
            f"| {name} | {len(fired)} | {tp} | {fp} | {prec} | {tp / len(positives):.2f} "
            f"| {rec_l:.2f} |"
        )
    cov = {
        k: coverage(k)
        for k in (
            "img.phash",
            "img.siglip",
            "person.public_figure",
            "brand.impersonated",
            "ad.advertiser",
            "ids.ad_library",
            "url.domain",
            "text.ocr",
            "text.asr",
        )
    }
    lines += [
        "",
        "Cases with each feature: " + ", ".join(f"`{k}` {v}" for k, v in cov.items()) + ".",
        "",
        "## SigLIP max cross-case screenshot cosine (screenshots + video keyframes)",
        "",
        f"- positive pairs: {_stats(pos_cos)}",
        f"- negative pairs: {_stats(neg_cos)}",
        f"- suggested anchors: **lo = {lo}** (95th percentile of negatives), "
        f"**hi = {hi}** (just above the highest negative)",
        f"- positive pairs without a comparable screenshot on both sides: "
        f"{len(positives) - len(pos_cos)}",
        "",
        "## Positive pairs and the B signals that fire",
        "",
        "| Pair | Campaign | SigLIP | Signals |",
        "|---|---|---:|---|",
    ]
    exact = [k for k in signals if "union" not in k and "≥ lo" not in k]
    for p in sorted(positives):
        hits = [k.split(" ")[0] for k in exact if p in signals[k]]
        s = f"{sig[p]:.3f}" if p in sig else "–"
        lines.append(f"| {p[0]} – {p[1]} | {gold[p[0]]} | {s} | {', '.join(hits) or '–'} |")
    lines += ["", "## Cross-corpus links (B ↔ M) from B signals", ""]
    cross = [p for p in all_pairs if p[0][0] != p[1][0] and any(p in signals[k] for k in exact)]
    if cross:
        lines += ["| Pair | Gold | SigLIP | Signals |", "|---|---|---:|---|"]
        for p in sorted(cross, key=lambda q: (q not in positives, q)):
            hits = [k.split(" ")[0] for k in exact if p in signals[k]]
            g = f"same ({gold[p[0]]})" if p in positives else "different"
            s = f"{sig[p]:.3f}" if p in sig else "–"
            lines.append(f"| {p[0]} – {p[1]} | {g} | {s} | {', '.join(hits)} |")
    else:
        lines.append("None.")
    runs = [(args.label, run_meta)] + [
        (label, json.loads(Path(path).read_text()))
        for label, _, path in (t.partition("=") for t in args.timings)
    ]
    names = list(dict.fromkeys(st["name"] for _, m in runs for st in m.get("stages", [])))
    lines += [
        "",
        "## Extraction timings (seconds)",
        "",
        "| Run | Device | Cases | " + " | ".join(names) + " | Total |",
        "|---|---|---:|" + "---:|" * (len(names) + 1),
    ]
    for label, m in runs:
        secs = {st["name"]: st["seconds"] for st in m.get("stages", [])}
        cells = " | ".join(f"{secs[k]:.1f}" if k in secs else "–" for k in names)
        cache = "cache off" if m.get("cache") is None else "cache on"
        lines.append(
            f"| {label} | {m.get('device')}, {cache} | {m['counts']['cases']} | {cells} "
            f"| {m.get('total_seconds', 0):.1f} |"
        )
    lines.append("")
    report = "\n".join(lines)
    print(report)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
