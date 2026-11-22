"""Fail if any git-tracked file contains a concrete value derived from the organizer's corpus.

NASK mentors allow the code to be public, but values extracted from the scam data (domains,
image hashes, pixel/account IDs, IPs, kit IDs, phone numbers, page titles) must stay in the
private Google Drive copy. This guard builds the value list from a real run's
``features.parquet`` (plus ``artifacts.parquet`` / ``cases.parquet`` next to it, when present)
and scans every tracked text file, case-insensitively and also in defanged ``[.]`` form.

Run locally (the data is not in git, so CI has nothing to compare against and skips)::

    uv run python scripts/check_no_corpus_values.py --features runs/dev/features.parquet

or set ``KF_FEATURES=/path/to/features.parquet`` and run ``uv run pytest
tests/test_no_corpus_values.py``. Exit code 0 = clean or skipped, 1 = values found.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Hosts of public platforms (ad networks, CDNs, the impersonated news brands): naming them
# reveals nothing about the corpus. Matched as a suffix of the candidate host.
GENERIC_HOST_SUFFIXES = (
    "facebook.com",
    "facebook.net",
    "fbcdn.net",
    "google.com",
    "google.pl",
    "googleapis.com",
    "gstatic.com",
    "googletagmanager.com",
    "googleusercontent.com",
    "doubleclick.net",
    "cloudflare.com",
    "jquery.com",
    "jsdelivr.net",
    "unpkg.com",
    "unsplash.com",
    "er-api.com",
    "im-g.pl",
    "gazeta.pl",
    "tvn24.pl",
    "cdn.pandavideo.com",
    "player.pandavideo.com.br",
    "hit-video.pandavideo.com",
)

# Feature names whose values are corpus-specific identifiers, matched as whole tokens.
ID_FEATURES = (
    "ids.",
    "infra.ip",
    "infra.favicon_mmh3",
)
HOST_FEATURES = (
    "url.domain",
    "ocr.domain",
    "infra.cert_san",
    "url.outlink_domain",
    "infra.host_3p",
    "kit.dep_host",
)
HASH_FEATURES = ("asset.sha256", "img.phash", "img.pdq")
TEXT_FEATURES = ("html.title", "text.headline_tpl")
PHONE_SOURCES = ("text.raw", "text.ocr", "ocr.headline")

MIN_HASH_PREFIX = 12
# Docs abbreviate kit UUIDs and hex host labels ("0a1b2c3d…"), so match shorter prefixes there.
MIN_ID_PREFIX = 8
MIN_TEXT_FRAGMENT = 25
PHONE_RE = re.compile(r"(?<!\d)(?:\+?48[\s-]?)?\d{3}[\s-]?\d{3}[\s-]?\d{3}(?!\d)")
HEX_RE = re.compile(r"(?<![0-9a-z])[0-9a-f]{8,64}(?![0-9a-z])")
LONG_HEX_RE = re.compile(r"[0-9a-f]{16,}")
HOST_RE = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}")
PLACEHOLDER_RE = re.compile(r"\{[A-Z_a-z]+\}")


def _is_generic_host(host: str) -> bool:
    return any(host == s or host.endswith("." + s) for s in GENERIC_HOST_SUFFIXES)


def _read_table(path: Path) -> list[dict[str, object]]:
    import pyarrow.parquet as pq

    return list(pq.read_table(path).to_pylist())


def build_values(features: Path) -> dict[str, set[str]]:
    """Return corpus values grouped by kind (``token``, ``host``, ``hash``, ``idhex``, ...)."""
    values: dict[str, set[str]] = defaultdict(set)
    for row in _read_table(features):
        name = str(row.get("name") or "")
        raw = row.get("value")
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip().lower()
        if name.startswith(ID_FEATURES):
            token = value.split("=", 1)[-1]
            if len(token) >= 6 and re.fullmatch(r"[\w.:/-]+", token):
                values["token"].add(token)
                values["idhex"].update(LONG_HEX_RE.findall(token.replace("-", "")))
        elif name in HOST_FEATURES or name == "infra.endpoint":
            for host in HOST_RE.findall(value):
                if not _is_generic_host(host):
                    values["host"].add(host)
                    values["idhex"].update(LONG_HEX_RE.findall(host))
        elif name == "ad.advertiser":
            if len(value) >= 5:
                values["text"].add(value)
                values["text"].add(value.replace("-", " "))
        elif name in HASH_FEATURES:
            values["hash"].add(value)
        elif name in TEXT_FEATURES:
            for frag in PLACEHOLDER_RE.split(value):
                frag = frag.strip(" :,.-—|")
                if len(frag) >= MIN_TEXT_FRAGMENT or (
                    name == "html.title" and len(frag) >= 8 and frag == value
                ):
                    values["text"].add(frag)
        elif name in PHONE_SOURCES:
            for phone in PHONE_RE.findall(value):
                values["phone"].add(re.sub(r"\D", "", phone)[-9:])
        if row.get("artifact_id"):
            values["hash"].add(str(row["artifact_id"]).lower())
    _add_run_tables(features.parent, values)
    return values


def _add_run_tables(run_dir: Path, values: dict[str, set[str]]) -> None:
    artifacts = run_dir / "artifacts.parquet"
    if artifacts.exists():
        for row in _read_table(artifacts):
            meta = row.get("meta") or []
            pairs = meta.items() if isinstance(meta, dict) else meta
            for key, val in pairs:  # type: ignore[misc]
                if key == "sha256" and val:
                    values["hash"].add(str(val).lower())
            page = row.get("page")
            if isinstance(page, str) and len(page) >= 12:
                values["text"].add(page.lower())
    cases = run_dir / "cases.parquet"
    if cases.exists():
        for row in _read_table(cases):
            for url in row.get("landing_urls") or []:  # type: ignore[attr-defined]
                for host in HOST_RE.findall(str(url).lower()):
                    if not _is_generic_host(host):
                        values["host"].add(host)


def tracked_files(repo: Path) -> Iterable[Path]:
    """Yield git-tracked files that look like text."""
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    for rel in out.decode().split("\0"):
        if not rel:
            continue
        path = repo / rel
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        data = path.read_bytes()
        if b"\0" in data[:4096]:
            continue
        yield path


def _normalise(text: str) -> str:
    text = text.lower()
    return text.replace("[.]", ".").replace("(.)", ".").replace("[dot]", ".")


def scan(repo: Path, values: dict[str, set[str]]) -> list[tuple[str, str, str]]:
    """Return ``(file, kind, value)`` for every corpus value found in a tracked file."""
    hash_prefixes = {h[:n] for h in values["hash"] for n in range(MIN_HASH_PREFIX, len(h) + 1)}
    hash_prefixes |= {h[:n] for h in values["idhex"] for n in range(MIN_ID_PREFIX, len(h) + 1)}
    token_re = _word_re(values["token"])
    host_re = _word_re(values["host"])
    hits: list[tuple[str, str, str]] = []
    for path in tracked_files(repo):
        rel = str(path.relative_to(repo))
        text = _normalise(path.read_text(errors="replace"))
        found: set[tuple[str, str]] = set()
        for pattern, kind in ((token_re, "id"), (host_re, "host")):
            if pattern is not None:
                found |= {(kind, m) for m in pattern.findall(text)}
        found |= {
            ("hash", m)
            for m in HEX_RE.findall(text)
            if m in hash_prefixes and m not in values["token"]
        }
        found |= {("text", t) for t in values["text"] if t in text}
        digits = re.sub(r"[\s-]", "", text)
        found |= {("phone", p) for p in values["phone"] if p in digits}
        hits.extend((rel, kind, val) for kind, val in sorted(found))
    return hits


def _word_re(words: set[str]) -> re.Pattern[str] | None:
    if not words:
        return None
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![\w.-])(?:{alts})(?![\w-])")


def main() -> int:
    """Scan tracked files; return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--features", type=Path, default=os.environ.get("KF_FEATURES"))
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--show-values", action="store_true", help="Print matched values")
    args = parser.parse_args()
    if args.features is None or not Path(args.features).exists():
        print("SKIP: no features.parquet given (use --features or KF_FEATURES)")
        return 0
    values = build_values(Path(args.features))
    print("value list: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(values.items())))
    hits = scan(args.repo, values)
    for rel, kind, val in hits:
        print(f"{rel}: {kind}" + (f" {val!r}" if args.show_values else ""))
    print(f"{len(hits)} hit(s) in {len({h[0] for h in hits})} file(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
