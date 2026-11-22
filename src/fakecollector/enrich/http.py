"""Opt-in HTTP access for enrichment: gate, timeout and on-disk cache in one place.

Only public, key-less metadata services are called, and only with registrable domains or
IPs derived from the data, never with a URL found in the data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from fakecollector.config import get_settings

logger = logging.getLogger(__name__)

USER_AGENT = "fakecollector-research/0.1"  # generic: no team or user details
# Failures are remembered only for this process: crt.sh and RDAP servers fail
# transiently, so a miss must not be written to disk for good.
_failed: set[str] = set()


def enabled() -> bool:
    """True when the user opted in with `ALLOW_ENRICH=true`."""
    return get_settings().allow_enrich


def _download(url: str, accept: str | None, timeout: float) -> bytes | None:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)  # fixed https hosts
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body: bytes = resp.read()
            return body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("enrichment request failed: %s (%s)", url.split("?")[0], exc)
        return None


def fetch(url: str, accept: str | None = None) -> bytes | None:
    """GET `url` through the cache; None when disabled, failed or empty."""
    if not enabled():
        return None
    settings = get_settings()
    cache_dir = settings.enrich_cache_dir
    path = cache_dir / hashlib.sha256(url.encode()).hexdigest()
    if path.exists():
        return path.read_bytes()
    if url in _failed:
        return None
    body = _download(url, accept, settings.enrich_timeout_s)
    if not body:
        _failed.add(url)
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def fetch_json(url: str, accept: str | None = "application/json") -> Any:
    """`fetch` + JSON decode; None on any failure."""
    body = fetch(url, accept)
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        logger.warning("enrichment response is not JSON: %s", url.split("?")[0])
        return None
