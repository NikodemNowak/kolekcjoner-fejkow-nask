"""Text layer and link targets of a printed page (`page.pdf`).

A browser "print to PDF" keeps the page's text and its links, which the rasterised pages
(`derived.pdf_pages` -> OCR) only recover approximately. This extractor reads them directly
with PDFium: `text.raw` (the text layer, like a saved page's visible text), `html.title`
(the document title the browser copies from the page), and for each `http(s)` link
annotation `url.outlink_domain` plus any IDs in the URL (`ids_from_url`). Nothing in the
PDF is executed (PDFium without JavaScript) and no link is fetched.
"""

from __future__ import annotations

import ctypes
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from fakecollector.config import get_settings
from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.har_ids import ids_from_url
from fakecollector.extractors.infra import registrable_domain

logger = logging.getLogger(__name__)

MAX_PAGES = 20
MAX_CHARS = 200_000
MAX_LINKS = 500
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\x00", " ")).strip()


def _uri(pdfium_c: Any, doc: Any, link: Any) -> str:
    action = pdfium_c.FPDFLink_GetAction(link)
    if not action or pdfium_c.FPDFAction_GetType(action) != pdfium_c.PDFACTION_URI:
        return ""
    size = pdfium_c.FPDFAction_GetURIPath(doc, action, None, 0)
    if size <= 1:
        return ""
    buf = ctypes.create_string_buffer(size)
    pdfium_c.FPDFAction_GetURIPath(doc, action, buf, size)
    return buf.value.decode("utf-8", "replace").strip()


def read_pdf(path: Any, max_pages: int = MAX_PAGES) -> tuple[str, str, list[tuple[int, str]]]:
    """(title, text of the first `max_pages` pages, [(page number, link URI)]).

    Raises ImportError without pypdfium2 and `pypdfium2.PdfiumError`/OSError on bad input.
    """
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    pdf = pdfium.PdfDocument(path)
    try:
        title = str(pdf.get_metadata_dict().get("Title") or "")
        texts: list[str] = []
        links: list[tuple[int, str]] = []
        for i in range(min(len(pdf), max_pages)):
            page = pdf[i]
            try:
                textpage = page.get_textpage()
                try:
                    texts.append(textpage.get_text_range())
                finally:
                    textpage.close()
                pos, link = ctypes.c_int(0), pdfium_c.FPDF_LINK()
                while len(links) < MAX_LINKS and pdfium_c.FPDFLink_Enumerate(
                    page.raw, ctypes.byref(pos), ctypes.byref(link)
                ):
                    if uri := _uri(pdfium_c, pdf.raw, link):
                        links.append((i + 1, uri))
            finally:
                page.close()
    finally:
        pdf.close()
    return _clean(title), _clean(" ".join(texts))[:MAX_CHARS], links


class PdfTextExtractor(BaseExtractor):
    """`text.raw`, `html.title`, link domains and link IDs from a PDF capture."""

    name = "pdf_text"
    version = 1

    def supports(self, artifact: Artifact) -> bool:
        """PDF captures."""
        return artifact.kind == "pdf"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Read the text layer and link annotations; `[]` when unreadable."""
        try:
            size = artifact.path.stat().st_size
        except OSError:
            return []
        if size > get_settings().max_artifact_mb << 20:
            logger.warning("pdf too large, skipped: %s", artifact.path.name)
            return []
        try:
            title, text, links = read_pdf(artifact.path)
        except ImportError:
            logger.warning("pypdfium2 not installed; pdf text of %s skipped", artifact.path.name)
            return []
        except Exception as exc:  # pdfium raises its own error type on hostile input
            logger.warning("cannot read pdf %s: %s", artifact.path.name, exc)
            return []

        def feat(name: str, value: str, locator: str) -> Feature:
            return Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name=name,
                value=value,
                locator=locator,
            )

        out: list[Feature] = []
        if title:
            out.append(feat("html.title", title, "pdf:meta[Title]"))
        if text:
            out.append(feat("text.raw", text, "pdf:text"))
        seen: set[tuple[str, str]] = set()
        for page, uri in links:
            try:
                parts = urlsplit(uri)
            except ValueError:
                continue
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                continue
            found = ids_from_url(uri)
            found.setdefault("url.outlink_domain", set()).add(registrable_domain(parts.hostname))
            for name, values in sorted(found.items()):
                for value in sorted(values):
                    if value and (name, value) not in seen:
                        seen.add((name, value))
                        out.append(feat(name, value, f"pdf:page={page} link"))
        return out
