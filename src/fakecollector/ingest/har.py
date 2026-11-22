"""HAR parsing: summary of entries, landing URL and response-body hashes."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from fakecollector.graph.stoplist import is_stopped_host
from fakecollector.ingest.normalize import canonical_url
from fakecollector.ingest.schemas import HarEntry, HarSummary


class HarError(ValueError):
    """The file is not a readable HAR (truncated, not JSON, wrong shape)."""


def _body(content: object) -> bytes | None:
    """Decoded response body, or None when the HAR did not keep it."""
    if not isinstance(content, dict):
        return None
    text = content.get("text")
    if not isinstance(text, str) or not text:
        return None
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text, validate=False)
        except (binascii.Error, ValueError):
            return None
    return text.encode("utf-8", "surrogatepass")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry(raw: dict[str, Any]) -> HarEntry | None:
    req = raw.get("request") or {}
    resp = raw.get("response") or {}
    url = req.get("url")
    if not isinstance(url, str) or not url:
        return None
    headers = {
        str(h.get("name", "")).lower(): str(h.get("value", ""))
        for h in resp.get("headers") or []
        if isinstance(h, dict)
    }
    content = resp.get("content") or {}
    body = _body(content)
    redirect = resp.get("redirectURL") or headers.get("location") or None
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    sec = raw.get("_securityDetails") or resp.get("_securityDetails") or {}
    if not isinstance(sec, dict):
        sec = {}
    san = sec.get("sanList") or []
    return HarEntry(
        url=url,
        host=host,
        method=str(req.get("method", "GET")).upper(),
        status=int(resp.get("status") or 0),
        ip=raw.get("serverIPAddress") or None,
        mime=str(content.get("mimeType", "")).split(";")[0].strip().lower(),
        headers=headers,
        body_sha256=hashlib.sha256(body).hexdigest() if body is not None else None,
        body_size=len(body) if body is not None else 0,
        redirect_to=redirect,
        resource_type=str(raw.get("_resourceType") or "").lower() or None,
        tls_issuer=str(sec["issuer"]) if sec.get("issuer") else None,
        tls_san=[str(x) for x in san] if isinstance(san, list) else [],
    )


def _is_candidate(e: HarEntry) -> bool:
    """A request that could be the page itself: sent, GET, not a tracker or platform host."""
    return e.status != 0 and e.method == "GET" and bool(e.host) and not is_stopped_host(e.host)


def _follow(start: HarEntry, entries: list[HarEntry]) -> HarEntry:
    """Follow HTTP redirects inside the HAR to the page actually reached."""
    by_url = {e.url: e for e in entries}
    current, seen = start, {start.url}
    while current.redirect_to:
        nxt = by_url.get(urljoin(current.url, current.redirect_to))
        if nxt is None or nxt.url in seen:
            break
        seen.add(nxt.url)
        current = nxt
    return current


def _landing(entries: list[HarEntry], page_title: str) -> tuple[str | None, int | None]:
    """(landing URL, its status) of a capture.

    Priority: the URL the browser recorded as the page title; the first `document` request
    (even a 4xx, so a dead page is flagged); for HARs without resource types, the first
    HTML response from a non-tracker host. A HAR whose page was opened from a local file
    has no landing: its requests are only the page's trackers and assets.
    """
    if page_title.startswith(("http://", "https://")):
        match = next((e for e in entries if e.url == page_title), None)
        if match is None:
            canon = canonical_url(page_title)
            match = next((e for e in entries if canonical_url(e.url) == canon), None)
        if match is None:
            return page_title, None
        reached = _follow(match, entries)
        return reached.url, reached.status
    typed = any(e.resource_type for e in entries)
    if typed:
        start = next(
            (e for e in entries if e.resource_type == "document" and _is_candidate(e)), None
        )
    elif page_title.startswith("file:"):
        start = None
    else:
        start = next((e for e in entries if _is_candidate(e) and "html" in e.mime), None)
    if start is None:
        return None, None
    reached = _follow(start, entries)
    return reached.url, reached.status


def _load_log(path: Path) -> tuple[dict[str, Any], list[Any]]:
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig", errors="replace"))
        log = data["log"]
        raw_entries = log.get("entries") or []
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HarError(f"unreadable HAR {path.name}: {exc}") from exc
    if not isinstance(raw_entries, list):
        raise HarError(f"unreadable HAR {path.name}: entries is not a list")
    return log, raw_entries


def iter_bodies(path: Path) -> Iterator[tuple[int, str, bytes]]:
    """Yield `(entry index, request URL, decoded body)` for entries that kept a body.

    Bodies are only read as bytes; nothing in them is executed. Raises `HarError`.
    """
    _, raw_entries = _load_log(path)
    for i, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            continue
        url = (raw.get("request") or {}).get("url", "")
        body = _body((raw.get("response") or {}).get("content"))
        if body is not None:
            yield i, str(url), body


def iter_responses(path: Path) -> Iterator[tuple[int, str, int, str, bytes]]:
    """Yield `(entry index, request URL, status, MIME type, body)` for kept bodies.

    Like `iter_bodies`, but with what a caller needs to pick the page document and images.
    Bodies are only read as bytes; nothing in them is executed. Raises `HarError`.
    """
    _, raw_entries = _load_log(path)
    for i, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            continue
        resp = raw.get("response") or {}
        content = resp.get("content") if isinstance(resp, dict) else None
        body = _body(content)
        if body is None:
            continue
        url = str((raw.get("request") or {}).get("url", ""))
        try:
            status = int(resp.get("status") or 0)
        except (TypeError, ValueError):
            status = 0
        mime = str((content or {}).get("mimeType", "")).split(";")[0].strip().lower()
        yield i, url, status, mime, body


def parse_har(path: Path) -> HarSummary:
    """Parse a HAR file. Raises `HarError` if it cannot be read."""
    log, raw_entries = _load_log(path)
    entries = [e for e in (_entry(r) for r in raw_entries if isinstance(r, dict)) if e]
    pages = log.get("pages") or []
    first_page = pages[0] if pages and isinstance(pages[0], dict) else {}
    landing_url, landing_status = _landing(entries, str(first_page.get("title") or ""))
    started = _parse_time(first_page.get("startedDateTime"))
    if started is None and raw_entries and isinstance(raw_entries[0], dict):
        started = _parse_time(raw_entries[0].get("startedDateTime"))
    creator = log.get("creator") or {}
    return HarSummary(
        creator=str(creator.get("name", "")) if isinstance(creator, dict) else "",
        started_at=started,
        landing_url=landing_url,
        landing_status=landing_status,
        entries=entries,
    )
