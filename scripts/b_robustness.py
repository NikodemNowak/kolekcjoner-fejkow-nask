"""Robustness of the image signals to new-variant transformations (synthetic, from corpus images).

Every corpus image (≥ 120 px, from a `b_extract_all.py` run) is the gallery. A sample of them
is transformed the way a new variant arrives (crop, rescale, JPEG, aspect change, pasted into a
fake feed post, "Sponsorowane" header overlay, phone-screenshot downscale + sharpen; horizontal
flip as a negative control) and used as a query. For pHash, PDQ and SigLIP, with and without
creative-region crops (and SigLIP multi-crop), it measures retrieval recall@1 / @5 of the
original among all gallery images and the score of (variant, original) versus unrelated pairs.
Optionally re-ranks the SigLIP top-k with `local_match` (SIFT / ORB + RANSAC).

Only numbers go to stdout and to the markdown; no corpus content, no file names. Images are
read from disk only; nothing is fetched.

Usage:
    PYTHONPATH=src python scripts/b_robustness.py [--run data/runs/b_vision]
        [--md docs/robustness-vision.md] [--originals 150] [--seed 0] [--local-k 10]
        [--no-siglip] [--no-local] [--title "..."]
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
PHASH_T, PDQ_T, SIG_LO, SIG_HI = 8, 31, 0.80, 0.908
"""Current fusion anchors (b_eval / registry): near-dup Hamming and SigLIP lo / hi."""

TRANSFORMS = (
    "crop",
    "scale",
    "jpeg",
    "aspect",
    "header",
    "screenshot",
    "feed",
    "feed_phone",
    "flip",
)
CONTROL = "flip"


# ----------------------------------------------------------------- synthetic transformations


def _jpeg(im: Image.Image, q: int) -> Image.Image:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except (OSError, TypeError):
        return ImageFont.load_default()


def _words(rng: np.random.Generator, n: int) -> str:
    syl = ["po", "lsk", "ra", "ma", "ni", "ek", "zy", "ta", "wo", "do", "ki", "sze", "la", "ba"]
    return " ".join(
        "".join(rng.choice(syl, size=int(rng.integers(1, 4)))) for _ in range(n)
    ).capitalize()


def _blob(rng: np.random.Generator, w: int, h: int) -> Image.Image:
    """A synthetic picture for the next post in the feed (not from the corpus)."""
    base = rng.integers(0, 255, (max(2, h // 32), max(2, w // 32), 3), dtype=np.uint8)
    return Image.fromarray(base).resize((w, h), Image.Resampling.BICUBIC)


def feed_frame(creative: Image.Image, rng: np.random.Generator, dark: bool = False) -> Image.Image:
    """Paste a creative into a fake feed post (status bar, header, text, link bar, next post)."""
    w = 720
    cw = w
    ch = max(40, round(creative.height * cw / creative.width))
    ch = min(ch, 1400)
    creative = creative.resize((cw, ch), Image.Resampling.BILINEAR)
    bg, ink, sub, bar = (
        ((36, 37, 38), (228, 230, 235), (176, 179, 184), (58, 59, 60))
        if dark
        else ((255, 255, 255), (5, 5, 5), (101, 103, 107), (240, 242, 245))
    )
    n_lines = int(rng.integers(1, 5))
    top = 48 + 72 + 110 + 34 * n_lines + 20
    height = top + ch + 120 + 70 + 300
    canvas = Image.new("RGB", (w, height), bg)
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, w, 48), fill=(0, 0, 0) if not dark else (24, 25, 26))
    d.text(
        (20, 12),
        f"{int(rng.integers(7, 23))}:{int(rng.integers(10, 59))}",
        fill=(255,) * 3,
        font=_font(22),
    )
    d.rectangle((0, 48, w, 120), fill=bg)
    d.text((20, 66), "facebook", fill=(8, 102, 255), font=_font(36))
    d.ellipse((20, 140, 100, 220), fill=tuple(int(c) for c in rng.integers(40, 200, 3)))
    d.text((116, 148), _words(rng, 2), fill=ink, font=_font(26))
    d.text((116, 184), "Sponsorowane · ⌂", fill=sub, font=_font(22))
    for i in range(n_lines):
        d.text((20, 240 + 34 * i), _words(rng, 7), fill=ink, font=_font(26))
    canvas.paste(creative, (0, top))
    y = top + ch
    d.rectangle((0, y, w, y + 120), fill=bar)
    d.text((20, y + 14), _words(rng, 1).upper() + ".PL", fill=sub, font=_font(22))
    d.text((20, y + 48), _words(rng, 4), fill=ink, font=_font(28))
    d.rounded_rectangle((w - 230, y + 34, w - 20, y + 90), 8, fill=(228, 230, 235))
    d.text((w - 210, y + 48), "Dowiedz się więcej", fill=ink, font=_font(20))
    d.text((20, y + 140), "Lubię to!    Komentarz    Udostępnij", fill=sub, font=_font(24))
    canvas.paste(_blob(rng, w, 260), (0, y + 210))
    return canvas


def transform(name: str, im: Image.Image, rng: np.random.Generator) -> Image.Image:
    """One synthetic new-variant transformation of `im` (parameters drawn from `rng`)."""
    w, h = im.size
    if name == "crop":  # remove 5-30 % of the area, random position
        keep = float(np.sqrt(1 - rng.uniform(0.05, 0.30)))
        kw, kh = max(16, round(w * keep)), max(16, round(h * keep))
        x0, y0 = int(rng.integers(0, w - kw + 1)), int(rng.integers(0, h - kh + 1))
        return im.crop((x0, y0, x0 + kw, y0 + kh))
    if name == "scale":
        s = rng.uniform(0.5, 1.5)
        return im.resize((max(16, round(w * s)), max(16, round(h * s))), Image.Resampling.BICUBIC)
    if name == "jpeg":
        return _jpeg(im, int(rng.integers(40, 71)))
    if name == "aspect":
        s = rng.choice([rng.uniform(0.75, 0.9), rng.uniform(1.1, 1.33)])
        return im.resize((max(16, round(w * s)), h), Image.Resampling.BICUBIC)
    if name == "header":  # "Sponsorowane" bar drawn over the top 12 %
        out = im.copy()
        bh = max(24, round(h * 0.12))
        overlay = Image.new("RGB", (w, bh), (255, 255, 255))
        d = ImageDraw.Draw(overlay)
        fs = max(10, bh // 3)
        d.ellipse((6, 4, bh - 4, bh - 4), fill=(66, 103, 178))
        d.text((bh + 6, 2), _words(rng, 2), fill=(5, 5, 5), font=_font(fs))
        d.text((bh + 6, 2 + fs + 2), "Sponsorowane", fill=(101, 103, 107), font=_font(fs))
        out.paste(Image.blend(im.crop((0, 0, w, bh)), overlay, 0.9), (0, 0))
        return out
    if name == "screenshot":  # phone capture: downscale, sharpen, status + nav bars, PNG-like
        s = rng.uniform(0.45, 0.75)
        small = im.resize((max(16, round(w * s)), max(16, round(h * s))), Image.Resampling.BILINEAR)
        small = small.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=2))
        bar = max(12, small.height // 25)
        out = Image.new("RGB", (small.width, small.height + 2 * bar), (0, 0, 0))
        out.paste(small, (0, bar))
        ImageDraw.Draw(out).text((4, 1), "12:34", fill=(255,) * 3, font=_font(max(8, bar - 4)))
        return out
    if name == "feed":
        return feed_frame(im, rng, dark=bool(rng.random() < 0.3))
    if name == "feed_phone":  # feed post captured on a phone and re-shared: smaller + JPEG
        fr = feed_frame(im, rng, dark=bool(rng.random() < 0.3))
        s = rng.uniform(0.5, 0.75)
        fr = fr.resize((round(fr.width * s), round(fr.height * s)), Image.Resampling.BILINEAR)
        return _jpeg(fr, int(rng.integers(50, 76)))
    if name == "flip":
        return ImageOps.mirror(im)
    raise ValueError(name)


# ----------------------------------------------------------------- descriptors


@dataclass
class Desc:
    """All descriptors of one image (whole image first, then extra views)."""

    phash: list[np.ndarray] = field(default_factory=list)  # bit rows
    pdq: list[np.ndarray] = field(default_factory=list)
    sig: dict[str, np.ndarray] = field(default_factory=dict)  # mode -> (k, 768)
    n_regions: int = 0


def _bits(hex_: str) -> np.ndarray:
    return np.unpackbits(np.frombuffer(bytes.fromhex(hex_), dtype=np.uint8))


def multicrop(im: Image.Image) -> list[Image.Image]:
    """Center 80 % plus four 60 % corner tiles."""
    w, h = im.size
    out = [im.crop((w // 10, h // 10, w - w // 10, h - h // 10))]
    tw, th = round(w * 0.6), round(h * 0.6)
    out += [im.crop((x, y, x + tw, y + th)) for x in (0, w - tw) for y in (0, h - th)]
    return out


def describe(im: Image.Image, siglip: Callable[[list[Image.Image]], np.ndarray] | None) -> Desc:
    """Hashes for whole + region crops; SigLIP vectors for whole, regions and multi-crop."""
    from fakecollector.extractors.image_hash import hash_features
    from fakecollector.extractors.regions import crops

    region_imgs = [c for _, c in crops(im)]
    d = Desc(n_regions=len(region_imgs))
    for view in [im, *region_imgs]:
        feats = {f.name: f.value for f in hash_features(view, "", "")}
        d.phash.append(_bits(feats["img.phash"]))
        d.pdq.append(_bits(feats["img.pdq"]))
    if siglip is not None:
        mc = multicrop(im)
        vecs = siglip([im, *region_imgs, *mc])
        k = 1 + len(region_imgs)
        d.sig["whole"] = vecs[:1]
        d.sig["regions"] = vecs[:k]
        d.sig["multicrop"] = np.concatenate([vecs[:1], vecs[k:]])
    return d


@dataclass
class Gallery:
    """Stacked gallery descriptors with owner indices, per method and mode."""

    rows: dict[str, np.ndarray]  # key -> (m, dim) matrix
    owner: dict[str, np.ndarray]  # key -> (m,) gallery index
    n: int


def stack(descs: list[Desc]) -> Gallery:
    """Stack per-image descriptor lists into matrices for vectorised scoring."""
    rows: dict[str, list[np.ndarray]] = defaultdict(list)
    owner: dict[str, list[int]] = defaultdict(list)
    for i, d in enumerate(descs):
        for name, lst in (("phash", d.phash), ("pdq", d.pdq)):
            rows[f"{name}/whole"].append(lst[0][None])
            owner[f"{name}/whole"].append(i)
            rows[f"{name}/regions"].append(np.stack(lst))
            owner[f"{name}/regions"] += [i] * len(lst)
        for mode, v in d.sig.items():
            rows[f"siglip/{mode}"].append(v)
            owner[f"siglip/{mode}"] += [i] * len(v)
    return Gallery(
        {k: np.concatenate(v).astype(np.float32) for k, v in rows.items()},
        {k: np.asarray(v) for k, v in owner.items()},
        len(descs),
    )


def scores(q: Desc, g: Gallery, key: str) -> np.ndarray:
    """Per-gallery-image best score (higher = more similar; hashes as -Hamming)."""
    method, mode = key.split("/")
    if method == "siglip":
        qv = q.sig[mode]
        sims = qv @ g.rows[key].T
        best = sims.max(axis=0)
        out = np.full(g.n, -1.0, dtype=np.float32)
        np.maximum.at(out, g.owner[key], best)
        return out
    lst = q.phash if method == "phash" else q.pdq
    qb = np.stack(lst if mode == "regions" else lst[:1]).astype(np.float32)
    gb = g.rows[key]
    dist = qb @ (1 - gb).T + (1 - qb) @ gb.T
    best = -dist.min(axis=0)
    out = np.full(g.n, -1e9, dtype=np.float32)
    np.maximum.at(out, g.owner[key], best)
    return out


THRESH = {"phash": -PHASH_T, "pdq": -PDQ_T, "siglip": SIG_HI}


# ----------------------------------------------------------------- main


def _load_gallery(run: Path) -> list[tuple[str, str, Path, frozenset[str]]]:
    """Unique hashed images of a run: (artifact id, role, path, campaign labels of its cases)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from b_eval import load_gold

    gold = load_gold()
    feats = pl.read_parquet(run / "features.parquet")
    arts = pl.read_parquet(run / "artifacts.parquet")
    ids = set(
        feats.filter((pl.col("name") == "img.phash") & (pl.col("locator") == ""))[
            "artifact_id"
        ].to_list()
    )
    labels: dict[str, set[str]] = defaultdict(set)
    first: dict[str, tuple[str, Path]] = {}
    for aid, role, path, case in arts.select("id", "role", "path", "case_id").iter_rows():
        if aid in ids:
            first.setdefault(aid, (role, Path(path)))
            labels[aid].add(gold.get(case, case))
    return [(a, *first[a], frozenset(labels[a])) for a in sorted(first)]


def _pct(xs: list[float] | np.ndarray, q: float) -> float:
    return float(np.percentile(xs, q)) if len(xs) else float("nan")


def _fmt_score(method: str, v: float) -> str:
    return f"{-v:.0f}" if method != "siglip" else f"{v:.3f}"


def main() -> int:
    """Build variants, score every method, write the markdown table."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, default=ROOT / "data" / "runs" / "b_vision")
    ap.add_argument("--md", type=Path, default=ROOT / "docs" / "robustness-vision.md")
    ap.add_argument("--originals", type=int, default=150)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--local-k", type=int, default=10)
    ap.add_argument("--no-siglip", action="store_true")
    ap.add_argument("--no-local", action="store_true")
    args = ap.parse_args()

    from fakecollector.extractors.image_hash import big_enough, load_image

    siglip = None
    if not args.no_siglip:
        from fakecollector.extractors.image_embed import embed_images

        siglip = embed_images
    local = None
    if not args.no_local:
        from fakecollector.extractors import local_match as local

    rng = np.random.default_rng(args.seed)
    t0 = time.perf_counter()
    entries = _load_gallery(args.run)
    images: list[Image.Image] = []
    camp: list[frozenset[str]] = []
    for _, _, path, labels in entries:
        im = load_image(path)
        if im is not None and big_enough(im):
            images.append(im)
            camp.append(labels)
    descs = [describe(im, siglip) for im in images]
    g = stack(descs)
    keys = [k for k in g.rows if not k.startswith("siglip") or siglip is not None]
    print(
        f"gallery: {g.n} images, {sum(d.n_regions > 0 for d in descs)} with regions "
        f"({time.perf_counter() - t0:.1f}s)"
    )

    # Equivalents: near-identical gallery items (same picture uploaded twice) count as hits.
    pdq_whole = g.rows["pdq/whole"]
    d_pdq = pdq_whole @ (1 - pdq_whole).T + (1 - pdq_whole) @ pdq_whole.T
    equiv = [set(np.nonzero(d_pdq[i] <= 20)[0].tolist()) | {i} for i in range(g.n)]

    gal_local: dict[str, list[object]] = {}
    if local is not None:
        for det in ("sift", "orb"):
            gal_local[det] = [local.describe(im, det) for im in images]  # type: ignore[arg-type]

    pick = rng.permutation(g.n)[: args.originals]
    ranks: dict[tuple[str, str], list[int]] = defaultdict(list)
    pos: dict[tuple[str, str], list[float]] = defaultdict(list)
    neg: dict[str, list[float]] = defaultdict(list)
    neg_top: dict[tuple[str, str], list[float]] = defaultdict(list)
    loc: dict[tuple[str, str], list[tuple[int, bool, int, bool, bool]]] = defaultdict(list)
    t_local = 0.0
    for qi, oi in enumerate(pick):
        for tname in TRANSFORMS:
            qim = transform(tname, images[oi], rng)
            qd = describe(qim, siglip)
            eq = equiv[oi]
            mask = np.ones(g.n, dtype=bool)
            mask[list(eq)] = False
            for key in keys:
                s = scores(qd, g, key)
                best_eq = max(s[j] for j in eq)
                rank = int((s[mask] >= best_eq).sum())  # ties are not hits
                ranks[(key, tname)].append(rank)
                pos[(key, tname)].append(float(s[oi]))
                if tname != CONTROL:
                    neg[key] += rng.choice(
                        s[mask], size=min(20, int(mask.sum())), replace=False
                    ).tolist()
                    neg_top[(key, tname)].append(float(s[mask].max()))
                if local is not None and key == "siglip/regions":
                    tl = time.perf_counter()
                    top = np.argsort(-s)[: args.local_k]
                    for det in ("sift", "orb"):
                        qf = local.describe(qim, det)  # type: ignore[arg-type]
                        res = [local.match_features(qf, gal_local[det][j]) for j in top]
                        ok = [j for j, r in zip(top, res, strict=True) if r.homography_ok]
                        ok.sort(key=lambda j: -res[list(top).index(j)].inliers)
                        rest = [j for j in top if j not in ok]
                        order = ok + rest + [j for j in np.argsort(-s) if j not in set(top)]
                        new_rank = next(r for r, j in enumerate(order) if j in eq)
                        orig = local.match_features(qf, gal_local[det][oi])
                        wrong = [
                            bool(camp[j] & camp[oi])
                            for j, r in zip(top, res, strict=True)
                            if j not in eq and r.homography_ok
                        ]
                        loc[(det, tname)].append(
                            (
                                new_rank,
                                orig.homography_ok,
                                orig.inliers,
                                any(wrong),
                                not all(wrong),
                            )
                        )
                    t_local += time.perf_counter() - tl
        if (qi + 1) % 25 == 0:
            print(f"  {qi + 1}/{len(pick)} originals ({time.perf_counter() - t0:.0f}s)")

    labels = {
        "phash/whole": "pHash",
        "phash/regions": "pHash +regions",
        "pdq/whole": "PDQ",
        "pdq/regions": "PDQ +regions",
        "siglip/whole": "SigLIP",
        "siglip/regions": "SigLIP +regions",
        "siglip/multicrop": "SigLIP multi-crop",
    }
    cols = [k for k in labels if k in keys]
    loc_cols = [d for d in ("sift", "orb") if any(k[0] == d for k in loc)]
    head = [labels[k] for k in cols] + [
        f"SigLIP +regions → {d.upper()} top-{args.local_k}" for d in loc_cols
    ]

    def rec(rs: list[int], k: int) -> str:
        return f"{np.mean(np.asarray(rs) < k):.2f}"

    lines = [
        "# Robustness of the image signals to new variants",
        "",
        f"Gallery: {g.n} corpus images (≥ 120 px) from `{args.run.name}`; "
        f"{sum(d.n_regions > 0 for d in descs)} of them yield creative regions. "
        f"Queries: {len(pick)} originals × {len(TRANSFORMS)} synthetic transformations "
        f"(seed {args.seed}). A hit is the original or a near-identical gallery copy (PDQ ≤ 20). "
        "Hash scores are Hamming distances (lower = closer); SigLIP is cosine. "
        "`+regions` adds creative-region crops on both sides (best pair counts). "
        "Generated by `scripts/b_robustness.py`; numbers only.",
        "",
        "## Recall@1 / recall@5 of the original among all gallery images",
        "",
        "| Transform | " + " | ".join(head) + " |",
        "|---|" + "---:|" * len(head),
    ]
    for t in TRANSFORMS:
        cells = [f"{rec(ranks[(k, t)], 1)} / {rec(ranks[(k, t)], 5)}" for k in cols]
        cells += [
            f"{rec([r[0] for r in loc[(d, t)]], 1)} / {rec([r[0] for r in loc[(d, t)]], 5)}"
            for d in loc_cols
        ]
        name = f"{t} (control)" if t == CONTROL else t
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    allt = [t for t in TRANSFORMS if t != CONTROL]
    cells = [
        f"{rec([r for t in allt for r in ranks[(k, t)]], 1)} / "
        f"{rec([r for t in allt for r in ranks[(k, t)]], 5)}"
        for k in cols
    ]
    cells += [
        f"{rec([r[0] for t in allt for r in loc[(d, t)]], 1)} / "
        f"{rec([r[0] for t in allt for r in loc[(d, t)]], 5)}"
        for d in loc_cols
    ]
    lines.append("| **all but flip** | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Score of (variant, original) vs unrelated pairs (all transforms but flip)",
        "",
        "Pass = share of pairs within the current anchor (pHash ≤ 8, PDQ ≤ 31, SigLIP ≥ 0.908; "
        "SigLIP ≥ 0.8 in brackets). Hardest negative = best-scoring wrong gallery image per query.",
        "",
        "| Signal | pos median | pos p10 | neg p99 | hardest neg median | pos pass | neg pass "
        "| hardest neg pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for k in cols:
        method = k.split("/")[0]
        p = np.asarray([v for t in allt for v in pos[(k, t)]])
        n = np.asarray(neg[k])
        hn = np.asarray([v for t in allt for v in neg_top[(k, t)]])
        th = THRESH[method]

        def pas(x: np.ndarray, th: float = th) -> str:
            return f"{np.mean(x >= th):.2f}"

        extra = (
            (
                f" ({np.mean(p >= SIG_LO):.2f})",
                f" ({np.mean(n >= SIG_LO):.3f})",
                f" ({np.mean(hn >= SIG_LO):.2f})",
            )
            if method == "siglip"
            else ("", "", "")
        )
        lines.append(
            f"| {labels[k]} | {_fmt_score(method, float(np.median(p)))} "
            f"| {_fmt_score(method, _pct(p, 10))} "
            f"| {_fmt_score(method, _pct(n, 99))} | {_fmt_score(method, float(np.median(hn)))} "
            f"| {pas(p)}{extra[0]} | {np.mean(n >= th):.3f}{extra[1]} | {pas(hn)}{extra[2]} |"
        )
    if loc_cols:
        lines += [
            "",
            "## Local-feature verification (`local_match`) of the SigLIP +regions "
            f"top-{args.local_k}",
            "",
            "A wrong candidate is any non-equivalent gallery image; *same campaign* means it "
            "shares a case or gold campaign with the original (another screenshot of the same "
            "page, a sibling creative), *other* means it does not.",
            "",
            "| Detector | Transform | original verified | original inliers (median) "
            "| wrong verified, same campaign | wrong verified, other campaign |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for d in loc_cols:
            for t in [*TRANSFORMS, "all but flip"]:
                rows = (
                    [r for tt in allt for r in loc[(d, tt)]] if t == "all but flip" else loc[(d, t)]
                )
                if not rows:
                    continue
                arr = np.asarray(rows, dtype=np.float64)
                lines.append(
                    f"| {d.upper()} | {t} | {arr[:, 1].mean():.2f} | {np.median(arr[:, 2]):.0f} "
                    f"| {arr[:, 3].mean():.2f} | {arr[:, 4].mean():.2f} |"
                )
        lines.append("")
        lines.append(
            f"Local matching time: {t_local:.0f} s for {len(pick) * len(TRANSFORMS)} queries × "
            f"top-{args.local_k} × 2 detectors (query description included)."
        )
    lines.append("")
    report = "\n".join(lines)
    print(report)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(report)
    print(f"total {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
