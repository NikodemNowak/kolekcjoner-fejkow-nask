"""Request graph (signal 4): who the landing talks to, how its URLs look, where it leads.

Built from HAR entries and, when a case has no HAR, from the saved page's resource and
link attributes. Hosts are only parsed out of URLs; none of them is contacted.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlsplit

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors._text import read_text
from fakecollector.extractors.html_page import parse_html
from fakecollector.ingest.har import HarError, parse_har
from fakecollector.ingest.normalize import registrable_domain, url_schema
from fakecollector.ingest.schemas import HarEntry, HarSummary

logger = logging.getLogger(__name__)

_COLLECTOR_PATH = re.compile(
    r"/(api|events?|collect|track(ing)?|trk|stats?|pixel|beacon|log|persist)(/|\b)", re.I
)
_JS_REDIRECT = [
    re.compile(r"location(?:\.href)?\s*=\s*['\"](https?://[^'\"\s]+)", re.I),
    re.compile(r"location\.(?:replace|assign)\(\s*['\"](https?://[^'\"\s]+)", re.I),
]
_META_REFRESH_URL = re.compile(r"url\s*=\s*['\"]?([^'\";\s]+)", re.I)
_RESOURCE_ATTRS = (
    ("script", "src"),
    ("img", "src"),
    ("link", "href"),
    ("iframe", "src"),
    ("source", "src"),
    ("video", "src"),
    ("audio", "src"),
)
_OUTLINK_ATTRS = (("a", "href"), ("area", "href"), ("form", "action"))

Hit = tuple[str, str, str]  # (feature name, value, locator)

__all__ = ["RequestGraphExtractor", "registrable_domain"]  # re-exported for other modules


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_real_host(host: str) -> bool:
    """A dotted name or an IP; `localhost` and bare words from broken captures are not hosts."""
    return "." in host or ":" in host


def _endpoint(method: str, url: str, first_party: str, mime: str = "") -> str | None:
    """`METHOD host+schema` of a third-party collection point (POST or collector path).

    First-party paths (the lander's own `/api/…`, `/order.php`) describe the kit, not
    who runs it, so they are `kit.path_sig` (template.py, toolkit tier). A plain GET of a
    script, style or image is a download, not a collector, even when its path says
    "events" (`GET /js/events-loader.js`).
    """
    host = _host(url)
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    if first_party and registrable_domain(host) == first_party:
        return None
    if method != "POST" and (not _COLLECTOR_PATH.search(path) or _is_static(path, mime)):
        return None
    return f"{method} {host}{url_schema(url)}"


_STATIC_EXT = re.compile(
    r"\.(js|mjs|css|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|otf|mp4|webm)$", re.I
)
_STATIC_MIME = ("javascript", "ecmascript", "css", "image/", "font", "video/")


_CODE_EXT = re.compile(r"\.(js|mjs|css|woff2?|ttf|otf)$", re.I)
_CODE_MIME = ("javascript", "ecmascript", "css", "font")


def _is_code_download(path: str, mime: str) -> bool:
    """A script, style or font: code the page runs, no data sent (unlike image beacons)."""
    return bool(_CODE_EXT.search(path)) or any(m in mime for m in _CODE_MIME)


def _is_static(path: str, mime: str) -> bool:
    return bool(_STATIC_EXT.search(path)) or any(m in mime for m in _STATIC_MIME)


def _landing_hits(landing: str | None, locator: str) -> tuple[str, list[Hit]]:
    if not landing or not (host := _host(landing)):
        return "", []
    first_party = registrable_domain(host)
    hits: list[Hit] = [("url.domain", first_party, locator)]
    schema = url_schema(landing)
    if schema and schema != "/":
        hits.append(("url.schema", schema, locator))
    return first_party, hits


def _is_navigation(e: HarEntry, typed: bool) -> bool:
    """A page navigation, not a sub-resource: CDN redirects of images or video are noise."""
    if typed:
        return e.resource_type == "document"
    return not e.mime or "html" in e.mime


def _har_hits(har: HarSummary, case_url: str | None = None) -> list[Hit]:
    first_party, hits = _landing_hits(har.landing_url, "landing")
    if not first_party and case_url and (host := _host(case_url)):
        # A HAR recorded from a saved file has no page request; without the case's own URL
        # the lander's assets would be counted as third-party hosts.
        first_party = registrable_domain(host)
    typed = any(e.resource_type for e in har.entries)
    third: dict[str, str] = {}  # host -> first locator
    receives_data: set[str] = set()
    for i, e in enumerate(har.entries):
        loc = f"entry[{i}].request.url"
        if not _is_real_host(e.host):
            continue
        third_party = registrable_domain(e.host) != first_party
        if third_party:
            third.setdefault(e.host, loc)
            if not (e.method == "GET" and _is_code_download(urlsplit(e.url).path, e.mime)):
                receives_data.add(e.host)
        if (ep := _endpoint(e.method, e.url, first_party, e.mime)) is not None:
            hits.append(("infra.endpoint", ep, loc))
        if (e.redirect_to or 300 <= e.status < 400) and _is_navigation(e, typed):
            if third_party:
                hits.append(("infra.redirect_hop", e.host, loc))
            target = _host(urljoin(e.url, e.redirect_to or ""))
            if target and registrable_domain(target) != first_party:
                hits.append(("infra.redirect_hop", target, f"entry[{i}].response.redirectURL"))
    for host, loc in third.items():
        # Only downloads of code from a host = a kit dependency (toolkit), not an operator.
        name = "infra.host_3p" if host in receives_data else "kit.dep_host"
        hits.append((name, host, loc))
    return hits


def _html_hits(text: str, page_url: str | None) -> list[Hit]:
    first_party, hits = _landing_hits(page_url, "saved_from")
    soup = parse_html(text)
    base = page_url or ""

    def is_third(host: str) -> bool:
        return _is_real_host(host) and registrable_domain(host) != first_party

    for tag, attr in _RESOURCE_ATTRS:
        for el in soup.find_all(tag):
            value = el.get(attr)
            if isinstance(value, str) and is_third(host := _host(urljoin(base, value))):
                hits.append(("infra.host_3p", host, f"{tag}[{attr}]"))
    for tag, attr in _OUTLINK_ATTRS:
        for el in soup.find_all(tag):
            value = el.get(attr)
            if not isinstance(value, str) or value.startswith(("#", "javascript:", "mailto:")):
                continue
            url = urljoin(base, value)
            host = _host(url)
            if is_third(host):
                hits.append(("url.outlink_domain", registrable_domain(host), f"{tag}[{attr}]"))
            method = str(el.get("method") or "get").upper()
            is_post_form = tag == "form" and method == "POST" and host
            if is_post_form and (ep := _endpoint("POST", url, first_party)) is not None:
                hits.append(("infra.endpoint", ep, "form[action]"))
    for meta in soup.find_all("meta"):
        if str(meta.get("http-equiv", "")).lower() == "refresh":
            m = _META_REFRESH_URL.search(str(meta.get("content", "")))
            if m and is_third(host := _host(urljoin(base, m.group(1)))):
                hits.append(("infra.redirect_hop", host, "meta[refresh]"))
    for script in soup.find_all("script"):
        for rx in _JS_REDIRECT:
            for target in rx.findall(script.get_text()):
                if is_third(host := _host(target)):
                    hits.append(("infra.redirect_hop", host, "script"))
    return hits


class RequestGraphExtractor(BaseExtractor):
    """Signal 4: third-party hosts, kit dependencies, endpoints, redirect hops, `url.*`."""

    name = "request_graph"
    version = 4  # v4: single-label hosts dropped; HARs without a page use the case URL

    def supports(self, artifact: Artifact) -> bool:
        """HARs and landing pages."""
        return artifact.kind == "har" or (
            artifact.kind == "html" and artifact.role == "landing_page"
        )

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """One feature per distinct (name, value), with the first locator seen."""
        try:
            if artifact.kind == "har":
                hits = _har_hits(parse_har(artifact.path), artifact.meta.get("case_url"))
            else:
                url = artifact.meta.get("url") or artifact.meta.get("saved_from")
                hits = _html_hits(read_text(artifact.path), url)
        except HarError as exc:
            logger.warning("%s: %s", artifact.case_id, exc)
            return []
        except Exception as exc:  # hostile HTML must not stop a run
            logger.warning("%s: request graph skipped (%s)", artifact.case_id, exc)
            return []
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
                    locator=locator,
                )
            )
        return out
