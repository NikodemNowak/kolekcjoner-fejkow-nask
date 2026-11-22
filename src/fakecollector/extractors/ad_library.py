"""Meta Ad Library metadata from yt-dlp `*.info.json` files (signal 10).

Emits `ids.ad_library` (ad archive id), `ad.advertiser` (page name slug),
`ids.advertiser_page` (page id) and the ad copy (title / description) as `text.ocr`:
there is no dedicated ad-copy feature, and `text.ocr` is the "text shown in the ad"
channel that the text extractors already consume.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.core.text import normalize_text

logger = logging.getLogger(__name__)

MAX_JSON_BYTES = 20 * 1024 * 1024
_DIGITS = re.compile(r"^\d{6,25}$")


def _str(value: Any) -> str:
    return str(value).strip() if isinstance(value, str | int) else ""


def ad_archive_id(info: dict[str, Any]) -> str | None:
    """Return the Ad Library archive id from `webpage_url ?id=`, `playlist_id` or `id`."""
    for key in ("webpage_url", "playlist_webpage_url", "original_url"):
        url = _str(info.get(key))
        if "facebook.com" in url and "id=" in url:
            ids = parse_qs(urlsplit(url).query).get("id", [])
            if ids and _DIGITS.match(ids[0]):
                return ids[0]
    for key in ("playlist_id", "id", "display_id"):
        head = _str(info.get(key)).split("_", 1)[0]
        if _DIGITS.match(head):
            return head
    return None


def advertiser_slug(name: str) -> str:
    """Normalise a page name to the same slug the OCR extractor produces."""
    return re.sub(r"[^\w]+", "-", normalize_text(name)).strip("-_")


def features_from_info(artifact: Artifact, info: dict[str, Any]) -> list[Feature]:
    """Turn one parsed yt-dlp info dict into features."""

    def feat(name: str, value: str, locator: str) -> Feature:
        return Feature(
            case_id=artifact.case_id,
            artifact_id=artifact.id,
            name=name,
            value=value,
            locator=locator,
        )

    feats: list[Feature] = []
    if ad_id := ad_archive_id(info):
        feats.append(feat("ids.ad_library", ad_id, "info.json:webpage_url"))
    for key in ("playlist_uploader", "uploader", "channel"):
        if (name := _str(info.get(key))) and (slug := advertiser_slug(name)):
            feats.append(feat("ad.advertiser", slug, f"info.json:{key}"))
            break
    for key in ("playlist_uploader_id", "uploader_id", "channel_id"):
        page = _str(info.get(key))
        if _DIGITS.match(page):
            feats.append(feat("ids.advertiser_page", page, f"info.json:{key}"))
            break
    copy = [_str(info.get(k)) for k in ("title", "description")]
    text = normalize_text("\n".join(dict.fromkeys(c for c in copy if c)))
    if len(text) >= 3:
        feats.append(feat("text.ocr", text, "info.json:title+description"))
    return feats


class AdLibraryExtractor(BaseExtractor):
    """Reads yt-dlp `facebook:ads` metadata next to downloaded ad videos."""

    name = "ad_library"
    version = 1
    stage = 1
    requires: Literal["base", "ml"] = "base"

    def supports(self, artifact: Artifact) -> bool:
        """Only yt-dlp `*.info.json` files."""
        return artifact.kind == "json" and artifact.path.name.endswith(".info.json")

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Parse one info.json; malformed or oversized files yield nothing."""
        try:
            if artifact.path.stat().st_size > MAX_JSON_BYTES:
                logger.warning("info.json too large, skipped: %s", artifact.path)
                return []
            info = json.loads(artifact.path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as exc:
            logger.warning("cannot read %s: %s", artifact.path, exc)
            return []
        if not isinstance(info, dict):
            return []
        return features_from_info(artifact, info)
