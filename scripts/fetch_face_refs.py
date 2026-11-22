"""Download public-figure reference photos listed in `refs/faces.csv` from Wikimedia Commons.

Usage:
    python scripts/fetch_face_refs.py [--csv refs/faces.csv] [--out data/faces/refs]
    python scripts/fetch_face_refs.py describe <slug> "<Display Name>" "File:..." ...
    python scripts/fetch_face_refs.py discover <slug> "<Display Name>" [--limit 12]

The default mode saves each photo to `<out>/<slug>/<sha8>.jpg` (a 500 px rendition from
Wikimedia's media servers). `describe` prints CSV rows (license and author read from the
Commons API) for new candidate files, to paste into `refs/faces.csv` after checking them.
`discover` lists candidate photos from the person's Commons category (JPEG, allowed license,
surname in the file name) as CSV rows; `build_face_db.py` then rejects wrong-person photos.
Only Wikimedia hosts are contacted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.parse
from functools import cache
from html import unescape
from pathlib import Path

import httpx

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "fakecollector-face-refs/0.1 (scam-ad campaign research tool; hackathon project)"
ALLOWED_HOSTS = {"commons.wikimedia.org", "upload.wikimedia.org", "thumb.wikimedia.org"}
ALLOWED_LICENSES = ("CC0", "Public domain", "PDM", "CC BY ", "CC BY-SA ")
WIDTH = 500  # a standard, pre-rendered thumbnail step (cheap for Wikimedia to serve)
FIELDS = ["person_slug", "display_name", "source_url", "license", "author"]


@cache
def _client() -> httpx.Client:
    # Wikimedia's media servers rate-limit HTTP/1.1 clients far harder than HTTP/2 ones.
    return httpx.Client(http2=True, headers={"User-Agent": USER_AGENT}, timeout=60)


def _get(url: str) -> bytes:
    host = urllib.parse.urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"refusing non-Wikimedia host {host}")
    for attempt in range(6):
        resp = _client().get(url)
        if resp.status_code not in (429, 503) or attempt == 5:
            resp.raise_for_status()
            return resp.content
        wait = int(resp.headers.get("Retry-After") or 0) or 5 * 2**attempt
        if wait > 120:  # long penalty: skip this file, a rerun picks it up later
            resp.raise_for_status()
        print(f"{host}: rate limited, waiting {wait}s", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError("unreachable")


def _imageinfo(title: str) -> dict:
    params = {
        "action": "query",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": WIDTH,
        "format": "json",
    }
    data = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))
    page = next(iter(data["query"]["pages"].values()))
    if "imageinfo" not in page:
        raise KeyError(f"no such file: {title}")
    return dict(page["imageinfo"][0])


def _title(source_url: str) -> str:
    return urllib.parse.unquote(source_url.rsplit("/wiki/", 1)[-1]).replace("_", " ")


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", html))).strip()


def describe(slug: str, name: str, titles: list[str]) -> None:
    """Print CSV rows for candidate Commons files."""
    w = csv.writer(sys.stdout)
    for title in titles:
        meta = _imageinfo(title).get("extmetadata", {})
        lic = _plain(meta.get("LicenseShortName", {}).get("value", ""))
        author = _plain(meta.get("Artist", {}).get("value", ""))[:120]
        url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
            title.replace(" ", "_"), safe=":"
        )
        if not lic.startswith(ALLOWED_LICENSES):
            print(f"# skipped {title}: license {lic!r}", file=sys.stderr)
            continue
        w.writerow([slug, name, url, lic, author])
        time.sleep(1.0)


def _fold(text: str) -> str:
    """Lowercase ASCII folding for file-name matching (Polish diacritics included)."""
    table = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return (
        unicodedata.normalize("NFKD", text.translate(table))
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )


def discover(slug: str, name: str, limit: int = 12) -> list[list[str]]:
    """Candidate CSV rows: Commons file search for the name, full name in the file title."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": f'"{name}" filemime:image/jpeg',
        "srnamespace": "6",
        "srlimit": "60",
        "format": "json",
    }
    hits = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))["query"]["search"]
    parts = [_fold(p) for p in name.split()]
    titles = [h["title"] for h in hits if all(p in _fold(h["title"]) for p in parts)]
    rows = []
    for i in range(0, len(titles), 20):
        params = {
            "action": "query",
            "titles": "|".join(titles[i : i + 20]),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "format": "json",
        }
        pages = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))["query"]["pages"]
        by_title = {p["title"]: p for p in pages.values()}
        for title in titles[i : i + 20]:
            info = (by_title.get(title, {}).get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            lic = _plain(meta.get("LicenseShortName", {}).get("value", ""))
            if not lic.startswith(ALLOWED_LICENSES):
                continue
            if min(info.get("width", 0), info.get("height", 0)) < 400:
                continue
            author = _plain(meta.get("Artist", {}).get("value", ""))[:120]
            url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
                title.replace(" ", "_"), safe=":"
            )
            rows.append([slug, name, url, lic, author])
        time.sleep(1.0)
    return rows[:limit]


def download(csv_path: Path, out: Path) -> None:
    """Download every row of the reference CSV (skips files already present)."""
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    ok = 0
    for row in rows:
        if not row["license"].startswith(ALLOWED_LICENSES):
            print(f"skip (license {row['license']}): {row['source_url']}", file=sys.stderr)
            continue
        dest_dir = out / row["person_slug"]
        key = hashlib.sha256(row["source_url"].encode()).hexdigest()[:8]
        dest = dest_dir / f"{key}.jpg"
        if dest.exists():
            ok += 1
            continue
        try:
            info = _imageinfo(_title(row["source_url"]))
            data = _get(info.get("thumburl") or info["url"])
        except Exception as exc:
            print(f"FAILED {row['source_url']}: {exc}", file=sys.stderr)
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        ok += 1
        time.sleep(3.0)  # be polite to Wikimedia
    print(f"{ok}/{len(rows)} reference photos in {out}")


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "describe":
        describe(sys.argv[2], sys.argv[3], sys.argv[4:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "discover":
        limit = int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[4] == "--limit" else 12
        csv.writer(sys.stdout).writerows(discover(sys.argv[2], sys.argv[3], limit))
        return
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=Path("refs/faces.csv"))
    ap.add_argument("--out", type=Path, default=Path("data/faces/refs"))
    args = ap.parse_args()
    download(args.csv, args.out)


if __name__ == "__main__":
    main()
