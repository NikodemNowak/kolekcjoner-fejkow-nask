"""Page structure and kit fingerprints (signal 5).

`html.dom_minhash` (tag-sequence shingles) and `html.css_minhash` (class vocabulary) separate
"same campaign" (0.85-1.00) from "same kit" (0.19-0.38) on the real data; `kit.path_sig`
and `kit.sdk` describe the first-party file layout a landing builder leaves behind.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag
from datasketch import MinHash

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors._text import read_text
from fakecollector.extractors.html_page import parse_html
from fakecollector.extractors.infra import registrable_domain
from fakecollector.ingest.har import HarError, parse_har
from fakecollector.ingest.schemas import HarEntry

logger = logging.getLogger(__name__)

NUM_PERM = 128
SEED = 0  # fixed: the same page always gives the same signature
SHINGLE = 4
MIN_SHINGLES = 8  # below this a page is too small to say anything about its template

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HEX = re.compile(r"\b[0-9a-f]{16,}\b", re.I)
_DIGITS = re.compile(r"\d+")
_SDK_SEGMENT = re.compile(r"(^|[/_.-])sdk([/_.-]|$)", re.I)
_SCRIPT_MIMES = ("javascript", "ecmascript")


def dom_shingles(soup: BeautifulSoup, k: int = SHINGLE) -> set[str]:
    """`k`-grams over the document-order sequence of `depth:tag` tokens.

    Depth keeps nesting information, document order keeps layout; on the real corpus this
    reproduces the calibration anchors in docs/DATA.md §4.6 (same campaign ~1.0, same kit
    ~0.2, median pair ~0.01), which root-path shingles did not (median 0.14).
    """
    tokens: list[str] = []

    def walk(el: Tag, depth: int) -> None:
        tokens.append(f"{depth}:{el.name.lower()}")
        for child in el.children:
            if isinstance(child, Tag):
                walk(child, depth + 1)

    for top in soup.children:
        if isinstance(top, Tag):
            walk(top, 0)
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def css_classes(soup: BeautifulSoup) -> set[str]:
    """All class tokens used on the page, lower-cased."""
    out: set[str] = set()
    for el in soup.find_all(class_=True):
        raw = el.get("class")
        tokens = raw.split() if isinstance(raw, str) else list(raw or [])
        out.update(str(c).lower() for c in tokens)
    return out


def minhash_vector(tokens: set[str]) -> list[float]:
    """MinHash signature as floats (uint32 values, exact in float64)."""
    mh = MinHash(num_perm=NUM_PERM, seed=SEED)
    for t in sorted(tokens):
        mh.update(t.encode("utf-8"))
    return [float(v) for v in mh.hashvalues]


def minhash_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Estimated Jaccard similarity of two signatures from `minhash_vector`."""
    if not a or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


# Kit-level requests: code, styles, fonts and API calls. Images, media and documents are
# the story (they repeat only inside one campaign and are covered by asset.sha256 / img.*).
_KIT_TYPES = {"script", "stylesheet", "font", "xhr", "fetch"}
_KIT_MIMES = ("javascript", "ecmascript", "css", "font", "json")
_ERROR_CHROME = ("/cdn-cgi/",)  # Cloudflare error / challenge pages of dead captures


def _is_kit_request(e: HarEntry) -> bool:
    if e.method == "POST":
        return True
    if e.resource_type:
        return e.resource_type in _KIT_TYPES
    return any(m in e.mime for m in _KIT_MIMES)


def path_signature(path: str) -> str:
    """URL path with UUIDs, long hex runs and digit runs replaced by placeholders."""
    sig = _UUID.sub("{uuid}", path)
    sig = _HEX.sub("{hex}", sig)
    return _DIGITS.sub("{n}", sig)


class TemplateExtractor(BaseExtractor):
    """Signal 5: `html.dom_minhash`, `html.css_minhash`, `kit.path_sig`, `kit.sdk`."""

    name = "template"
    version = 2  # v2: kit.path_sig only for code / API requests

    def supports(self, artifact: Artifact) -> bool:
        """Landing pages (structure) and HARs (first-party file layout)."""
        return artifact.kind == "har" or (
            artifact.kind == "html" and artifact.role == "landing_page"
        )

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Two MinHash vectors per page; path signatures and SDK paths per HAR."""
        try:
            if artifact.kind == "har":
                return self._har(artifact)
            return self._page(artifact)
        except HarError as exc:
            logger.warning("%s: %s", artifact.case_id, exc)
        except Exception as exc:  # hostile input must not stop a run
            logger.warning("%s: template features skipped (%s)", artifact.case_id, exc)
        return []

    def _feature(
        self,
        artifact: Artifact,
        name: str,
        value: str,
        locator: str,
        vector: list[float] | None = None,
    ) -> Feature:
        return Feature(
            case_id=artifact.case_id,
            artifact_id=artifact.id,
            name=name,
            value=value,
            vector=vector,
            locator=locator,
        )

    def _page(self, artifact: Artifact) -> list[Feature]:
        soup = parse_html(read_text(artifact.path))
        out: list[Feature] = []
        shingles = dom_shingles(soup)
        if len(shingles) >= MIN_SHINGLES:
            out.append(
                self._feature(artifact, "html.dom_minhash", "", "dom", minhash_vector(shingles))
            )
        classes = css_classes(soup)
        if classes:
            out.append(
                self._feature(artifact, "html.css_minhash", "", "class", minhash_vector(classes))
            )
        return out

    def _har(self, artifact: Artifact) -> list[Feature]:
        har = parse_har(artifact.path)
        landing_host = urlsplit(har.landing_url or "").hostname or ""
        if not landing_host:
            return []
        first_party = registrable_domain(landing_host)
        seen: set[tuple[str, str]] = set()
        out: list[Feature] = []
        for i, e in enumerate(har.entries):
            if not e.host or registrable_domain(e.host) != first_party:
                continue
            path = urlsplit(e.url).path
            if path in ("", "/") or path.startswith(_ERROR_CHROME) or not _is_kit_request(e):
                continue
            sig = path_signature(path)
            names = ["kit.path_sig"]
            if any(m in e.mime for m in _SCRIPT_MIMES) and _SDK_SEGMENT.search(path):
                names.append("kit.sdk")
            for name in names:
                if (name, sig) not in seen:
                    seen.add((name, sig))
                    out.append(self._feature(artifact, name, sig, f"entry[{i}].request.url"))
        return out
