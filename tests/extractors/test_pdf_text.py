"""PdfTextExtractor: text layer, title and link targets of a printed page (synthetic PDF)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fakecollector.core.schemas import Artifact
from fakecollector.extractors.pdf_text import PdfTextExtractor

pytest.importorskip("pypdfium2")


def _pdf(path: Path) -> Path:
    """One page with a line of text and a link annotation, written by hand."""
    stream = b"BT /F1 18 Tf 40 200 Td (Synthetic offer text for testing) Tj ET"
    link = (
        b"<< /Type /Annot /Subtype /Link /Rect [40 190 300 220] /Border [0 0 0] "
        b"/A << /S /URI /URI (https://shop.synthetic-offer.com/buy?fbclid=x"
        b"&utm_campaign=spring) >> >>"
    )
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> /Annots [6 0 R] >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        link,
        b"<< /Title (Synthetic offer page) >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 7 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    path.write_bytes(bytes(out))
    return path


def _artifact(path: Path) -> Artifact:
    return Artifact(id="p" * 16, case_id="T:1", kind="pdf", role="other", path=path, size=1)


def test_pdf_text_title_and_links(tmp_path: Path) -> None:
    # Audit 03: a PDF capture was only rasterised and OCR'd; its text layer and links unused.
    feats = PdfTextExtractor().extract(_artifact(_pdf(tmp_path / "page.pdf")), [])
    got = {(f.name, f.value) for f in feats}
    assert ("html.title", "Synthetic offer page") in got
    assert any(n == "text.raw" and "Synthetic offer text" in v for n, v in got)
    assert ("url.outlink_domain", "synthetic-offer.com") in got
    assert ("ids.ad_param", "utm_campaign=spring") in got
    assert all(f.locator.startswith("pdf:") for f in feats)


def test_broken_pdf_gives_nothing(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 garbage")
    assert PdfTextExtractor().extract(_artifact(bad), []) == []
