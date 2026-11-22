"""Kit and tracker IDs by regex over HAR URLs, HAR bodies, saved HTML and kit JS (signal 1).

Regex and parsing only: no URL from the data is fetched and no script is run.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlsplit

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors._text import is_text_asset, read_text
from fakecollector.extractors.asset import PIXEL_CONFIG_NAME
from fakecollector.ingest.har import HarError, iter_bodies, parse_har
from fakecollector.ingest.normalize import looks_random

logger = logging.getLogger(__name__)

_KIT = re.compile(r"landing-cdn/(?P<tenant>[\w-]+)/(?P<landing>[0-9a-f]{8}-[0-9a-f-]{27})", re.I)
_PIXEL = [
    re.compile(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{10,20})['\"]"),
    re.compile(r"facebook\.com/tr/?\?(?:[^\"'\s<>]*?&(?:amp;)?)?id=(\d{10,20})"),
    re.compile(r"connect\.facebook\.net/signals/config/(\d{10,20})"),
]
_GTAG = re.compile(r"\b(G-[A-Z0-9]{6,12}|AW-\d{6,12}|UA-\d{4,10}-\d{1,4}|GTM-[A-Z0-9]{4,8})\b")

# Campaign-level ad parameters vs per-landing click/tracker keys (docs/DATA.md §4.1).
_AD_PARAMS = {"utm_campaign", "utm_content", "utm_id", "campaign_id", "adset_id", "ad_id"}
_CLICK_KEYS = {"clickid", "click_id", "key", "lpkey", "_trk", "subid", "sub_id", "offer_id"}
# Some landers carry the Meta pixel ID in their own URL instead of loading its config.
_PIXEL_PARAMS = {"pxl", "fbpx", "pixel", "pixel_id", "fb_pixel", "fbpixel", "pixel_fb"}
_PIXEL_VALUE = re.compile(r"^\d{10,20}$")

IdMap = dict[str, set[str]]


def _add(found: IdMap, name: str, values: Iterable[str]) -> None:
    for v in values:
        if v:
            found.setdefault(name, set()).add(v)


def ids_from_text(text: str) -> IdMap:
    """Kit tenant/landing, Meta pixel and Google tag IDs found in any text."""
    found: IdMap = {}
    for m in _KIT.finditer(text):
        _add(found, "ids.kit_tenant", [m.group("tenant").lower()])
        _add(found, "ids.kit_landing", [m.group("landing").lower()])
    for rx in _PIXEL:
        _add(found, "ids.fb_pixel", rx.findall(text))
    _add(found, "ids.gtag", _GTAG.findall(text))
    return found


def ids_from_url(url: str) -> IdMap:
    """IDs in a URL: everything `ids_from_text` finds plus ad and click parameters."""
    found = ids_from_text(url)
    try:
        query = parse_qsl(urlsplit(url).query, keep_blank_values=False)
    except ValueError:
        return found
    for k, v in query:
        key = k.lower()
        value = v.strip()
        if key in _PIXEL_PARAMS and _PIXEL_VALUE.match(value):
            _add(found, "ids.fb_pixel", [value])
        elif key in _AD_PARAMS and not looks_random(value):
            # Random per-visit values (generated utm_* tokens) identify nothing; values are
            # case-sensitive, so they are kept as sent.
            _add(found, "ids.ad_param", [f"{key}={value}"])
        elif key in _CLICK_KEYS:
            _add(found, "ids.click_key", [f"{key}={v.strip()}"])
    return found


class IdsExtractor(BaseExtractor):
    """Signal 1: `ids.kit_*`, `ids.fb_pixel`, `ids.gtag`, `ids.ad_param`, `ids.click_key`."""

    name = "har_ids"
    version = 3  # v3: pixel IDs from URL params; random ad-param values dropped

    def supports(self, artifact: Artifact) -> bool:
        """HARs, landing pages, text-like landing assets and saved pixel config scripts."""
        if artifact.kind in {"har", "html"}:
            return True
        return artifact.kind == "asset" and (
            is_text_asset(artifact.path) or bool(PIXEL_CONFIG_NAME.match(artifact.path.name))
        )

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Collect IDs with a locator pointing at where each one was seen."""
        hits: list[tuple[str, str, str]] = []  # (name, value, locator)

        def keep(found: IdMap, locator: str) -> None:
            hits.extend((n, v, locator) for n, vs in found.items() for v in sorted(vs))

        if artifact.kind == "har":
            try:
                har = parse_har(artifact.path)
                for i, e in enumerate(har.entries):
                    keep(ids_from_url(e.url), f"entry[{i}].request.url")
                for i, _, body in iter_bodies(artifact.path):
                    keep(
                        ids_from_text(body.decode("utf-8", "replace")),
                        f"entry[{i}].response.content",
                    )
            except HarError as exc:
                logger.warning("%s: %s", artifact.case_id, exc)
        else:
            text = read_text(artifact.path)
            keep(ids_from_text(text), "html" if artifact.kind == "html" else "file")
            name = artifact.path.name
            if artifact.kind == "asset" and PIXEL_CONFIG_NAME.match(name) and "fbq" in text:
                # "Save page as" names the pixel's config script after the pixel ID.
                keep({"ids.fb_pixel": {name.split(".")[0]}}, "file_name")
            if url := artifact.meta.get("url") or artifact.meta.get("saved_from"):
                keep(ids_from_url(url), "saved_from")

        seen: set[tuple[str, str]] = set()
        out: list[Feature] = []
        for name, value, locator in hits:
            if (name, value) in seen:
                continue  # first locator is enough provenance
            seen.add((name, value))
            out.append(
                Feature(
                    case_id=artifact.case_id,
                    artifact_id=artifact.id,
                    name=name,
                    value=value,
                    locator=locator,
                )
            )
        return out
