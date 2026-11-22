from pathlib import Path

from fakecollector.core.schemas import Artifact
from fakecollector.extractors.html_page import HtmlPageExtractor


def test_visible_text_and_title(tmp_path: Path) -> None:
    p = tmp_path / "a.html"
    p.write_text(
        "<html><head><title> PILNE:  napaść </title><style>.a{}</style></head>"
        "<body><script>var hidden=1</script><h1>Nagłówek</h1><p>Treść  artykułu</p>"
        "<noscript>no</noscript></body></html>",
        encoding="utf-8",
    )
    art = Artifact(id="4" * 16, case_id="T:1", kind="html", role="landing_page", path=p, size=1)
    fs = {f.name: f.value for f in HtmlPageExtractor().extract(art, [])}
    assert fs["html.title"] == "PILNE: napaść"
    assert fs["text.raw"] == "Nagłówek Treść artykułu"


def test_only_landing_pages_are_supported(tmp_path: Path) -> None:
    p = tmp_path / "source.html"
    p.write_text("<html></html>")
    art = Artifact(id="5" * 16, case_id="T:1", kind="html", role="other", path=p, size=1)
    assert not HtmlPageExtractor().supports(art)


def test_unparseable_bytes_do_not_crash(tmp_path: Path) -> None:
    p = tmp_path / "x.html"
    p.write_bytes(b"\xff\xfe\x00<<<\x00")
    art = Artifact(id="6" * 16, case_id="T:1", kind="html", role="landing_page", path=p, size=1)
    HtmlPageExtractor().extract(art, [])
