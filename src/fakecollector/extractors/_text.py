"""Shared helpers for text-reading extractors (bounded reads, never executed)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_TEXT_BYTES = 8 * 1024 * 1024  # saved pages and kit JS are far below this
TEXT_ASSET_SUFFIXES = {".js", ".pobrane", ".pobierz", ".json", ".css", ".html", ".htm", ".txt"}


def read_text(path: Path, limit: int = MAX_TEXT_BYTES) -> str:
    """Read at most `limit` bytes as text; undecodable bytes are replaced."""
    try:
        with path.open("rb") as f:
            raw = f.read(limit)
    except OSError as exc:
        logger.warning("unreadable file skipped: %s (%s)", path.name, exc)
        return ""
    return raw.decode("utf-8", "replace")


def is_text_asset(path: Path) -> bool:
    """True for saved scripts, styles and documents (`main.js.pobrane` included)."""
    return any(s.lower() in TEXT_ASSET_SUFFIXES for s in path.suffixes[-2:])
