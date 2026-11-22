"""Case-folder ingest: one folder (or one file) -> a `Case` and its typed `Artifact`s.

Mapping follows `docs/DATA.md` §3. Every file is untrusted: nothing is executed or fetched,
unreadable files are kept as hashed artifacts and skipped by later stages with a warning.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from fakecollector.config import get_settings
from fakecollector.core.schemas import Artifact, ArtifactKind, Case, Role
from fakecollector.ingest.har import HarError, parse_har
from fakecollector.ingest.normalize import (
    canonical_url,
    display_text,
    redact_url,
    registrable_domain,
)

logger = logging.getLogger(__name__)

_IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_VIDEO = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m3u8", ".ts"}
_HTML = {".html", ".htm"}
_CAPTURE_META = {"archive_info.json", "metadata.json", "manifest.json"}
_SOURCE_META = {"zrodlo_meta.json", "source_meta.json"}  # publisher facts, see source_meta
_IGNORED_NAMES = {"sha256.json"}  # checksum list of the archive, no signal
_IGNORED_SUFFIXES = {".zip", ".sha256"}  # a .zip duplicates its unpacked folder
_ASSET_DIRS = {"resources"}
_EVIDENCE_SUFFIXES = _IMAGE | _VIDEO | _HTML | {".har", ".json", ".mhtml", ".mht", ".pdf"}
_SAVED_FROM = re.compile(rb"saved from url=\(\d+\)\s*(\S+?)\s*-->")
_URL_KEYS = ("url", "final_url", "landing_url", "page_url")
_TIME_KEYS = ("timestamp_utc", "timestamp", "captured_at", "capture_time")
_CHUNK = 1 << 20
_DIGIT_RUN = re.compile(r"(\d+)")
_SHINGLE = 5
_CLOAK_JACCARD = 0.5  # below this, two captures of one URL are different pages
_MAX_PAGE_BYTES = 8 * 1024 * 1024


def _ext(path: Path) -> str:
    """Suffix in lower case; a bare hidden name like `.har` counts as its own suffix."""
    if path.suffix:
        return path.suffix.lower()
    return path.name.lower() if path.name.startswith(".") else ""


def _classify(rel: Path) -> tuple[ArtifactKind, Role] | None:
    """Map a path relative to the case root to (kind, role); None = ignore the file."""
    name = rel.name.lower()
    ext = _ext(rel)
    if ext in _IGNORED_SUFFIXES or name in _IGNORED_NAMES:
        return None
    if any(p.endswith("_files") or p.lower() in _ASSET_DIRS for p in rel.parts[:-1]):
        return "asset", "landing_asset"
    if ext == ".har":
        return "har", "network"
    if ext in _HTML:
        return "html", ("other" if name == "source.html" else "landing_page")
    if ext in _IMAGE:
        return "image", ("ad_creative" if name.startswith("reklama") else "screenshot")
    if ext in _VIDEO:
        recording = any(w in name for w in ("nagranie", "recording", "screen"))
        return "video", ("screen_recording" if recording else "ad_video")
    if ext == ".json":
        if name.endswith(".info.json"):
            return "json", "ad_library_meta"
        if name in _CAPTURE_META:
            return "json", "capture_meta"
        if name == "dns_ssl.json":
            return "json", "dns_tls"
        if name in _SOURCE_META:
            return "json", "source_meta"
        return "json", "other"
    if ext in {".mhtml", ".mht"}:
        return "mhtml", "other"
    if ext == ".pdf":
        return "pdf", "other"
    if ext == ".txt":
        return "text", "other"
    return "asset", "other"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def _page_variant(rel: Path) -> str | None:
    """First sub-folder of the case = capture variant; files at case level = default."""
    if len(rel.parts) > 1 and not rel.parts[0].endswith("_files"):
        return rel.parts[0]
    return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig", errors="replace"))
    except (OSError, ValueError):
        logger.warning("unreadable JSON skipped: %s", path.name)
        return {}
    return data if isinstance(data, dict) else {}


def _saved_from(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    m = _SAVED_FROM.search(head)
    url = m.group(1).decode("utf-8", "replace") if m else None
    # "about:internet" and file:// paths say where the page was saved from, not where it lives
    return url if url and url.lower().startswith(("http://", "https://")) else None


def _parse_dt(value: object) -> datetime | None:
    """Parse an ISO timestamp; naive values are taken as UTC (capture tools write UTC)."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _first_str(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = data.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _make_artifacts(case_id: str, root: Path) -> list[Artifact]:
    limit = get_settings().max_artifact_mb * 1024 * 1024
    base = root.parent if root.is_file() else root
    files = _iter_files(root)
    stream_dirs = {p.parent for p in files if _ext(p) == ".m3u8"}
    seen: set[str] = set()
    out: list[Artifact] = []
    for path in files:
        rel = path.relative_to(base)
        kind_role = _classify(rel)
        if kind_role is None:
            continue
        if _ext(path) == ".ts" and path.parent in stream_dirs:
            continue  # HLS segments are read through their playlist
        try:
            size = path.stat().st_size
            if size > limit:
                logger.warning("artifact over size cap skipped: %s (%d B)", path.name, size)
                continue
            digest = _sha256(path)
        except OSError as exc:
            logger.warning("unreadable file skipped: %s (%s)", path.name, exc)
            continue
        art_id = digest[:16]
        if art_id in seen:
            continue  # same bytes twice inside one case
        seen.add(art_id)
        kind, role = kind_role
        out.append(
            Artifact(
                id=art_id,
                case_id=case_id,
                kind=kind,
                role=role,
                path=path,
                page=_page_variant(rel),
                size=size,
                meta={"sha256": digest, "rel": display_text(rel.as_posix())},
            )
        )
    _link_parents(out)
    return out


def _link_parents(arts: list[Artifact]) -> None:
    """Point each landing asset at the page it belongs to."""
    pages = [a for a in arts if a.role == "landing_page"]
    by_files_dir = {a.path.parent / f"{a.path.stem}_files": a.id for a in pages}
    for a in arts:
        if a.role != "landing_asset":
            continue
        for parent in a.path.parents:
            if parent in by_files_dir:
                a.parent_id = by_files_dir[parent]
                break
        else:
            same_variant = [p for p in pages if p.page == a.page]
            if same_variant:
                a.parent_id = same_variant[0].id


def _annotate(case: Case, arts: list[Artifact]) -> None:
    """Fill landing URLs, capture time and flags from capture meta, HARs and saved pages."""
    meta_urls: list[str] = []
    har_urls: list[str] = []
    html_urls: list[str] = []
    times: list[datetime] = []
    variant_url: dict[str | None, str] = {}
    error_variants: set[str | None] = set()

    for a in arts:
        if a.role == "capture_meta":
            data = _read_json(a.path)
            url = _first_str(data, _URL_KEYS)
            if url and url.lower().startswith(("http://", "https://")):
                meta_urls.append(url)
                variant_url.setdefault(a.page, url)
            if ts := _parse_dt(_first_str(data, _TIME_KEYS)):
                times.append(ts)
        elif a.kind == "har":
            try:
                har = parse_har(a.path)
            except HarError as exc:
                logger.warning("%s: %s", case.id, exc)
                a.meta["error"] = "unreadable"
                continue
            if har.started_at:
                t = har.started_at
                times.append(t if t.tzinfo else t.replace(tzinfo=UTC))
            if har.landing_url:
                har_urls.append(har.landing_url)
                variant_url.setdefault(a.page, har.landing_url)
                a.meta["landing_url"] = redact_url(har.landing_url)
            if har.landing_status is not None:
                a.meta["landing_status"] = str(har.landing_status)
                if har.landing_status >= 400:
                    error_variants.add(a.page)
        elif a.role == "landing_page" and (url := _saved_from(a.path)):
            html_urls.append(url)
            a.meta["saved_from"] = redact_url(url)

    ordered: list[str] = []
    for url in meta_urls + har_urls + html_urls:
        canon = redact_url(canonical_url(url))
        if canon not in ordered:
            ordered.append(canon)
    case.landing_urls = ordered
    # A HAR without its own page request gets the case's URL, so the request graph can
    # still tell the lander's own hosts from third parties.
    fallback = ordered[0] if ordered else None
    for a in arts:
        missing = a.kind == "har" and "landing_url" not in a.meta and "error" not in a.meta
        if missing and (url := variant_url.get(a.page) or fallback):
            a.meta["case_url"] = redact_url(url)
    case.captured_at = min(times) if times else None

    flags: list[str] = []
    if error_variants:
        flags.append("capture_error")
    pages_by_url: dict[str, set[str]] = {}
    for a in arts:
        if a.role != "landing_page" or a.page in error_variants:
            continue
        url = a.meta.get("saved_from") or variant_url.get(a.page)
        if url:
            a.meta["url"] = redact_url(url)
            pages_by_url.setdefault(canonical_url(url), set()).add(a.id)
    by_id = {a.id: a for a in arts}
    cloaked_pages: set[str | None] = set()
    for ids in pages_by_url.values():
        if any(_differ(by_id[x].path, by_id[y].path) for x, y in combinations(sorted(ids), 2)):
            cloaked_pages.update(by_id[x].page for x in ids)
    if cloaked_pages:
        flags.append("cloaking_suspected")
        # Which variant is the decoy is unknown, so every variant's page and assets are
        # marked; their images then count less in SigLIP comparisons.
        for a in arts:
            if a.page is not None and a.page in cloaked_pages:
                a.meta["cloaking_suspected"] = "1"
    content = [a for a in arts if a.kind not in {"json", "text"}]
    if content and all(a.kind == "video" for a in content):
        flags.append("video_only")
    if content and all(a.kind == "image" for a in content):
        flags.append("screenshot_only")
    case.flags = flags


def _natural_key(name: str) -> list[tuple[int, int | str]]:
    """`p2` before `p10`, `2` before `10`: numbers compare as numbers."""
    return [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in _DIGIT_RUN.split(name) if t]


def _shingles(path: Path) -> set[str]:
    """Word 5-grams of the page's visible text (scripts and styles dropped)."""
    try:
        soup = BeautifulSoup(path.read_bytes()[:_MAX_PAGE_BYTES].decode("utf-8", "replace"), "lxml")
    except Exception:  # hostile HTML: treat as unreadable, never crash ingest
        return set()
    for tag in soup(("script", "style", "noscript", "template")):
        tag.decompose()
    words = soup.get_text(" ").lower().split()
    return {" ".join(words[i : i + _SHINGLE]) for i in range(max(0, len(words) - _SHINGLE + 1))}


def _differ(a: Path, b: Path) -> bool:
    """True when two captures of one URL show different content, not just different bytes.

    Two tools saving the same page ("save page as" vs an archiver) never give identical
    bytes, so file hashes would flag every re-capture as cloaking.
    """
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return False  # nothing to compare: absent is not different
    return len(sa & sb) / len(sa | sb) < _CLOAK_JACCARD


def discover_cases(root: Path) -> list[Path]:
    """Return the case folders under `root`, or `[root]` if it is itself one case.

    A directory with evidence files directly inside it is a single case; otherwise each
    non-hidden sub-folder is a case.
    """
    if root.is_file():
        return [root]
    direct = [p for p in root.iterdir() if p.is_file() and _ext(p) in _EVIDENCE_SUFFIXES]
    if direct:
        return [root]
    dirs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    # A folder with only a description (opis.txt) and no sub-folders is still one report.
    if not dirs and any(p.is_file() and _ext(p) == ".txt" for p in root.iterdir()):
        return [root]
    return sorted(dirs, key=lambda p: _natural_key(p.name))


def load_case(path: Path, corpus: str) -> tuple[Case, list[Artifact]]:
    """Load one case folder (or a single file) into a `Case` and its artifacts."""
    case = Case(id=f"{corpus}:{display_text(path.name)}", corpus=corpus, path=path)
    arts = _make_artifacts(case.id, path)
    _annotate(case, arts)
    logger.info("%s: %d artifacts, flags=%s", case.id, len(arts), case.flags)
    return case, arts


def _site(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return registrable_domain(host) if host else None


def _page_sites(arts: list[Artifact]) -> set[str]:
    """Landing sites shown by a case's own pages and capture metadata (not by its HARs)."""
    sites = set()
    for a in arts:
        if a.role == "landing_page":
            url = a.meta.get("saved_from") or a.meta.get("url")
        elif a.role == "capture_meta":
            url = a.meta.get("url")
        else:
            continue
        if site := _site(url):
            sites.add(site)
    return sites


def _relocate_hars(cases: list[Case], by_case: dict[str, list[Artifact]]) -> None:
    """Move a HAR filed under the wrong report to the report whose page it captured.

    A HAR is foreign when its landing site matches none of its case's pages while that case
    has pages of its own. It moves when exactly one other case shows that site; otherwise
    it stays and the case is flagged. Without this, one misplaced HAR merges two campaigns.
    """
    sites = {c.id: _page_sites(by_case[c.id]) for c in cases}
    owners: dict[str, list[str]] = {}
    for cid, ss in sites.items():
        for site in ss:
            owners.setdefault(site, []).append(cid)
    changed: set[str] = set()
    extra_flags: dict[str, list[str]] = {}
    for case in cases:
        own = sites[case.id]
        if not own:
            continue  # a HAR-only case: its HAR is the evidence
        for har in [a for a in by_case[case.id] if a.kind == "har"]:
            har_site = _site(har.meta.get("landing_url"))
            if har_site is None or har_site in own:
                continue
            targets = [cid for cid in owners.get(har_site, []) if cid != case.id]
            if len(targets) != 1:
                # Another report's capture that we cannot place (e.g. one folder assigned on
                # its own): flag it and drop its features, so it cannot fake a link.
                logger.warning("%s: HAR %s captures another site, ignored", case.id, har.path.name)
                by_case[case.id].remove(har)
                extra_flags.setdefault(case.id, []).append("har_landing_mismatch")
                changed.add(case.id)
                continue
            target = targets[0]
            logger.warning("%s: HAR %s belongs to %s, moved", case.id, har.path.name, target)
            by_case[case.id].remove(har)
            har.case_id = target
            har.page = None
            by_case[target].append(har)
            extra_flags.setdefault(case.id, []).append("har_moved_out")
            extra_flags.setdefault(target, []).append("har_moved_in")
            changed.update({case.id, target})
    for case in cases:
        if case.id in changed:
            _annotate(case, by_case[case.id])
        for flag in extra_flags.get(case.id, []):
            if flag not in case.flags:
                case.flags.append(flag)


def load_corpus(root: Path, corpus: str) -> tuple[list[Case], list[Artifact]]:
    """Load every case under `root`, fix misplaced HARs and mark repeated reports.

    A case whose set of file hashes is contained in an earlier case's set adds nothing
    new, so it gets `duplicate_of` (it stays a case: "N reports -> M unique").
    """
    cases: list[Case] = []
    by_case: dict[str, list[Artifact]] = {}
    for case_dir in discover_cases(root):
        try:
            case, arts = load_case(case_dir, corpus)
        except Exception:  # one broken case must not stop the corpus
            logger.exception("case skipped: %s", case_dir.name)
            continue
        cases.append(case)
        by_case[case.id] = arts
    _relocate_hars(cases, by_case)
    fingerprints: list[tuple[str, frozenset[str]]] = []
    for case in cases:
        fp = frozenset(a.id for a in by_case[case.id])
        if fp:
            case.duplicate_of = next((cid for cid, other in fingerprints if fp <= other), None)
            if case.duplicate_of is None:
                fingerprints.append((case.id, fp))
    return cases, [a for case in cases for a in by_case[case.id]]
