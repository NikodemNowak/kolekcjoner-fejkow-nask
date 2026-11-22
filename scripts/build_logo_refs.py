"""Download the brand-logo reference set from Wikimedia Commons and precompute SigLIP2 vectors.

Reads `refs/logos.csv` (brand_slug, source_url, license), resolves each Commons file page to a
500 px PNG rendering via the MediaWiki API (SVGs are rasterised by Commons, so no local SVG
renderer is needed), saves it to `data/logos/<brand>/` and writes `data/logos/refs.npz` with
one vector per (logo, view). Only Commons is contacted; nothing from the corpus is fetched.

Usage: PYTHONPATH=src python scripts/build_logo_refs.py [--update-licenses] [--skip-download]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
import urllib.parse
from functools import cache
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "refs" / "logos.csv"
OUT_DIR = ROOT / "data" / "logos"
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "fakecollector-logo-refs/0.1 (scam-ad campaign research tool; reference logos)"
THUMB_WIDTH = 500  # a standard Commons thumbnail step; odd widths are throttled

log = logging.getLogger("build_logo_refs")


@cache
def _client() -> httpx.Client:
    # Wikimedia's media servers rate-limit HTTP/1.1 clients far harder than HTTP/2 ones.
    return httpx.Client(http2=True, headers={"User-Agent": USER_AGENT}, timeout=60)


def _get(url: str, tries: int = 6) -> bytes:
    """GET with Commons' Retry-After honoured (the API rate-limits bursts with HTTP 429)."""
    for attempt in range(tries):
        resp = _client().get(url)
        if resp.status_code not in (429, 503) or attempt == tries - 1:
            resp.raise_for_status()
            return resp.content
        wait = int(resp.headers.get("Retry-After") or 0) or 5 * 2**attempt
        if wait > 120:  # long penalty: give up on this file, a rerun picks it up later
            resp.raise_for_status()
        log.info("rate limited, waiting %d s", wait)
        time.sleep(wait)
    raise RuntimeError("unreachable")


def _title(source_url: str) -> str:
    return "File:" + urllib.parse.unquote(source_url.rsplit("File:", 1)[1]).replace("_", " ")


def resolve(titles: list[str]) -> dict[str, dict[str, str]]:
    """Map Commons file titles to {thumb, license, artist}; missing files are left out."""
    info: dict[str, dict[str, str]] = {}
    for i in range(0, len(titles), 40):
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": str(THUMB_WIDTH),
            "titles": "|".join(titles[i : i + 40]),
        }
        data = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))
        norm = {n["to"]: n["from"] for n in data["query"].get("normalized", [])}
        for page in data["query"]["pages"].values():
            if "imageinfo" not in page:
                log.warning("missing on Commons: %s", page.get("title"))
                continue
            ii = page["imageinfo"][0]
            meta = ii.get("extmetadata", {})
            lic = meta.get("LicenseShortName", {}).get("value", "unknown")
            info[norm.get(page["title"], page["title"])] = {
                "thumb": ii.get("thumburl") or ii["url"],
                "license": re.sub(r"<[^>]+>", "", lic).strip(),
            }
    return info


def views(logo: Image.Image) -> dict[str, Image.Image]:
    """Two renderings: the logo alone, and the logo at the left of a wide header bar.

    A screenshot header crop is about 5:1 and SigLIP squashes it to a square, so a reference
    shaped the same way matches a cloned header much better than the bare logo does.
    """
    rgba = logo.convert("RGBA")
    flat = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
    side = max(flat.size)
    square = Image.new("RGB", (side, side), "white")
    square.paste(flat, ((side - flat.width) // 2, (side - flat.height) // 2))
    bar = Image.new("RGB", (1000, 200), "white")
    scale = min(120 / flat.height, 400 / flat.width)
    small = flat.resize((max(1, int(flat.width * scale)), max(1, int(flat.height * scale))))
    bar.paste(small, (40, (200 - small.height) // 2))
    return {"logo": square, "header": bar}


def main() -> int:
    """Download, embed and save the reference set."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update-licenses", action="store_true", help="write licenses back to CSV")
    ap.add_argument("--skip-download", action="store_true", help="embed already downloaded files")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with CSV_PATH.open(newline="") as f:
        rows = list(csv.DictReader(f))
    titles = [_title(r["source_url"]) for r in rows]

    if not args.skip_download:
        info = resolve(titles)
        for row, title in zip(rows, titles, strict=True):
            if title not in info:
                continue
            row["license"] = info[title]["license"]
            dest_dir = OUT_DIR / row["brand_slug"]
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / (re.sub(r"[^A-Za-z0-9._-]+", "_", title[5:]) + ".png")
            if not dest.exists():
                try:
                    dest.write_bytes(_get(info[title]["thumb"]))
                except httpx.HTTPError as exc:
                    log.warning("FAILED %s: %s", title, exc)
                    continue
                time.sleep(1.0)  # be polite to upload.wikimedia.org
            log.info("%-12s %-55s %s", row["brand_slug"], title[5:], row["license"])
        if args.update_licenses:
            with CSV_PATH.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["brand_slug", "source_url", "license"])
                w.writeheader()
                w.writerows(rows)

    from fakecollector.extractors.image_embed import embed_images, release

    images: list[Image.Image] = []
    slugs: list[str] = []
    files: list[str] = []
    kinds: list[str] = []
    for path in sorted(OUT_DIR.glob("*/*.png")):
        try:
            with Image.open(path) as im:
                im.load()
                logo = im.copy()
        except OSError as exc:
            log.warning("cannot read %s: %s", path, exc)
            continue
        for kind, view in views(logo).items():
            images.append(view)
            slugs.append(path.parent.name)
            files.append(path.name)
            kinds.append(kind)
    if not images:
        log.error("no logos found under %s", OUT_DIR)
        return 1
    vecs = embed_images(images)
    release()
    np.savez(
        OUT_DIR / "refs.npz",
        vectors=vecs,
        slugs=np.array(slugs),
        files=np.array(files),
        kinds=np.array(kinds),
    )
    log.info("saved %d reference vectors for %d brands", len(vecs), len(set(slugs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
