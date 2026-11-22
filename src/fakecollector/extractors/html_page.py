"""Saved landing pages: visible text and title (inputs for the text family, C)."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors._text import read_text

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_INVISIBLE = ("script", "style", "noscript", "template", "svg")


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def parse_html(text: str) -> BeautifulSoup:
    """Parse untrusted HTML with lxml; nothing is rendered or fetched."""
    return BeautifulSoup(text, "lxml")


class HtmlPageExtractor(BaseExtractor):
    """`text.raw` (visible text) and `html.title` for every landing page."""

    name = "html_page"
    version = 1

    def supports(self, artifact: Artifact) -> bool:
        """Landing pages only (archive `source.html` duplicates `rendered.html`)."""
        return artifact.kind == "html" and artifact.role == "landing_page"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Visible text without scripts and styles, whitespace collapsed."""
        try:
            soup = parse_html(read_text(artifact.path))
        except Exception as exc:  # parser bugs on hostile input must not stop a run
            logger.warning("%s: HTML not parsed (%s)", artifact.case_id, exc)
            return []
        title = _clean(soup.title.get_text()) if soup.title else ""
        for tag in soup(_INVISIBLE):
            tag.decompose()
        if soup.head:
            soup.head.decompose()
        body = _clean(soup.get_text(" "))
        out: list[Feature] = []
        for name, value in (("html.title", title), ("text.raw", body)):
            if value:
                out.append(
                    Feature(
                        case_id=artifact.case_id,
                        artifact_id=artifact.id,
                        name=name,
                        value=value,
                        locator="title" if name == "html.title" else "body",
                    )
                )
        return out
