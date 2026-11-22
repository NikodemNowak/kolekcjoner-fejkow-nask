"""Facts a publisher wrote about a scam next to its screenshot (`zrodlo_meta.json`).

Public fact-checking articles (Demagog, FakeNews.pl) name the landing domain, short links,
the advertiser's page, phone numbers or Ad Library ids of the scam they show. A case built
from such an article carries them in `zrodlo_meta.json`; this extractor turns them into the
same features a capture would give:

- `landing_domains` -> `url.domain` (only names the publisher gave in full, no masks),
- `short_links` -> `ids.short_link`, `ad_library_ids` -> `ids.ad_library`,
- `advertisers` -> `ad.advertiser` (same slug as OCR and the Ad Library reader),
- `phones` / `bank_accounts` / `messengers` -> `ids.phone` / `ids.bank_account` /
  `ids.messenger`,
- `enrichment` (passive DNS / RDAP / CT lookups cached by the collector) -> `meta.ns`,
  `meta.ip`, `meta.cert_san` (operator) and `meta.asn`, `meta.registrar`,
  `meta.cert_issuer`, `meta.registered` (context), the tiers of the opt-in `infra.*` rows
  in a family of their own,
- platform, ad date, persons, brands and the story -> `meta.*` information only: they are
  the publisher's labels, so they never link cases.

Nothing here is fetched; the file is read as untrusted data.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.ad_library import advertiser_slug
from fakecollector.ingest.normalize import registrable_domain

logger = logging.getLogger(__name__)

SOURCE_META_NAMES = frozenset({"zrodlo_meta.json", "source_meta.json"})
MAX_BYTES = 2 * 1024 * 1024
_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
# Free site builders and app hosts: their customers are strangers, so the full host is the
# landing, not the shared parent domain.
SHARED_PARENTS = frozenset(
    {
        "tilda.ws",
        "myfreesites.net",
        "apps.com",
        "blogspot.com",
        "wixsite.com",
        "weebly.com",
        "webflow.io",
        "github.io",
        "netlify.app",
        "vercel.app",
        "pages.dev",
        "web.app",
        "firebaseapp.com",
        "herokuapp.com",
        "000webhostapp.com",
        "glitch.me",
        "carrd.co",
        "framer.website",
        "godaddysites.com",
        "square.site",
        "mystrikingly.com",
        "jimdosite.com",
    }
)
_DIGITS = re.compile(r"^\d{6,25}$")
# Rows of the enrichment block -> feature names (same names as enrich/__init__.py).
_ENRICH_KEYS = {
    "ns": "meta.ns",
    "registered": "meta.registered",
    "registrar": "meta.registrar",
    "cert_issuers": "meta.cert_issuer",
    "cert_sans": "meta.cert_san",
    "asn": "meta.asn",
    "ips": "meta.ip",
}
_INFO_KEYS = {
    "platform": "meta.platform",
    "ad_date": "meta.ad_date",
    "persons": "meta.person",
    "brands": "meta.brand",
    "narrative": "meta.narrative",
    "cert_pl_listed": "meta.cert_pl_listed",
}


def _values(entry: Any) -> list[str]:
    """A list of strings or of `{"value": ...}` records -> the clean strings."""
    items = entry if isinstance(entry, list) else [entry]
    out: list[str] = []
    for item in items:
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, str | int) and (text := str(value).strip()):
            out.append(text)
    return out


def clean_domain(value: str) -> str | None:
    """Registrable domain of a fully given host; masked (`e***.com`) or odd names -> None."""
    host = value.strip().lower()
    host = re.sub(r"^[a-z]+://", "", host).split("/", 1)[0].split(":", 1)[0].strip(".")
    host = host.replace("[.]", ".").replace("(.)", ".")
    if not _DOMAIN.match(host):
        return None
    site = registrable_domain(host)
    if site in SHARED_PARENTS:
        return host.removeprefix("www.") if host != site else None
    return site or None


def clean_phone(value: str) -> str | None:
    """Digits with an optional leading +; a Polish 9-digit number gets +48."""
    digits = re.sub(r"[^\d+]", "", value)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if re.fullmatch(r"\d{9}", digits):
        digits = "+48" + digits
    return digits if re.fullmatch(r"\+\d{9,15}", digits) else None


def features_from_meta(artifact: Artifact, meta: dict[str, Any]) -> list[Feature]:
    """Turn one parsed `zrodlo_meta.json` into features (one per distinct name/value)."""
    hits: list[tuple[str, str, str]] = []
    for raw in _values(meta.get("landing_domains", [])):
        if domain := clean_domain(raw):
            hits.append(("url.domain", domain, "landing_domains"))
    for raw in _values(meta.get("short_links", [])):
        # Same value as OCR's `ocr.short_link`: host lowercased without "www.", token as is
        # (short-link services are case-sensitive).
        link = re.sub(r"^[a-zA-Z]+://", "", raw.strip()).rstrip("/")
        host, _, token = link.partition("/")
        if token and "*" not in link:
            host = host.lower().removeprefix("www.")
            hits.append(("ids.short_link", f"{host}/{token}", "short_links"))
    for raw in _values(meta.get("ad_library_ids", [])):
        if _DIGITS.match(raw):
            hits.append(("ids.ad_library", raw, "ad_library_ids"))
    for raw in _values(meta.get("advertisers", [])):
        if slug := advertiser_slug(raw):
            hits.append(("ad.advertiser", slug, "advertisers"))
    for raw in _values(meta.get("phones", [])):
        if phone := clean_phone(raw):
            hits.append(("ids.phone", phone, "phones"))
    for raw in _values(meta.get("bank_accounts", [])):
        account = re.sub(r"\s", "", raw.upper())
        if re.fullmatch(r"(PL)?\d{26}", account):
            hits.append(("ids.bank_account", account.removeprefix("PL"), "bank_accounts"))
    for raw in _values(meta.get("messengers", [])):
        handle = raw.strip().lower().lstrip("@")
        if len(handle) >= 4 and "*" not in handle:
            hits.append(("ids.messenger", handle, "messengers"))
    enrichment = meta.get("enrichment")
    for domain, rows in (enrichment if isinstance(enrichment, dict) else {}).items():
        if not isinstance(rows, dict):
            continue
        for key, name in _ENRICH_KEYS.items():
            for value in _values(rows.get(key, [])):
                hits.append((name, value.lower(), f"enrichment:{domain}:{key}"))
        if rows.get("cert_pl_listed") is True:
            hits.append(("meta.cert_pl_listed", domain, f"enrichment:{domain}:cert_pl"))
    for key, name in _INFO_KEYS.items():
        if key == "cert_pl_listed":
            continue
        for value in _values(meta.get(key, [])):
            hits.append((name, value, key))
    seen: set[tuple[str, str]] = set()
    out: list[Feature] = []
    for name, value, locator in hits:
        if (name, value) in seen:
            continue
        seen.add((name, value))
        out.append(
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name=name,
                value=value,
                locator=f"zrodlo_meta.json:{locator}",
            )
        )
    return out


class SourceMetaExtractor(BaseExtractor):
    """Reads `zrodlo_meta.json`: what a public article says about the scam it shows."""

    name = "source_meta"
    version = 1
    requires: Literal["base", "ml"] = "base"

    def supports(self, artifact: Artifact) -> bool:
        """Only the publisher-metadata JSON of a case."""
        return artifact.role == "source_meta"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Parse the file; malformed or oversized files yield nothing."""
        try:
            if artifact.path.stat().st_size > MAX_BYTES:
                logger.warning("source metadata too large, skipped: %s", artifact.path.name)
                return []
            data = json.loads(artifact.path.read_bytes().decode("utf-8-sig", errors="replace"))
        except (OSError, ValueError) as exc:
            logger.warning("%s: source metadata unreadable (%s)", artifact.case_id, exc)
            return []
        return features_from_meta(artifact, data) if isinstance(data, dict) else []
