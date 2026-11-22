import json
from pathlib import Path

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.template import (
    TemplateExtractor,
    css_classes,
    dom_shingles,
    minhash_similarity,
)

PAGE = """<html><head><title>t</title></head><body>
<div class="hdr portal"><h1>{title}</h1></div>
<article class="story lead"><p>{a}</p><p>{b}</p><img src="x.png"></article>
<footer class="foot"><a href="#">x</a></footer></body></html>"""


def _art(tmp_path: Path, name: str, html: str, url: str = "https://a.test/") -> Artifact:
    p = tmp_path / name
    p.write_text(html, encoding="utf-8")
    return Artifact(
        id=name[:1] * 16,
        case_id=f"T:{name}",
        kind="html",
        role="landing_page",
        path=p,
        size=1,
        meta={"url": url},
    )


def _vec(fs: list[Feature], name: str) -> list[float]:
    [f] = [f for f in fs if f.name == name]
    assert f.value == ""
    assert f.vector is not None
    return f.vector


def test_same_template_different_text_is_similar(tmp_path: Path) -> None:
    ex = TemplateExtractor()
    a = ex.extract(_art(tmp_path, "a.html", PAGE.format(title="A", a="x", b="y")), [])
    b = ex.extract(_art(tmp_path, "b.html", PAGE.format(title="B", a="z", b="w")), [])
    assert minhash_similarity(_vec(a, "html.dom_minhash"), _vec(b, "html.dom_minhash")) == 1.0
    assert minhash_similarity(_vec(a, "html.css_minhash"), _vec(b, "html.css_minhash")) == 1.0


def test_different_template_is_dissimilar(tmp_path: Path) -> None:
    other = (
        "<html><body><table class='grid'><thead><tr><th><b>h</b></th></tr></thead>"
        "<tbody><tr><td><span><i>1</i></span><ul><li><em>x</em></li></ul></td></tr></tbody>"
        "</table><nav><ol><li><small>y</small></li></ol></nav></body></html>"
    )
    ex = TemplateExtractor()
    a = ex.extract(_art(tmp_path, "a.html", PAGE.format(title="A", a="x", b="y")), [])
    c = ex.extract(_art(tmp_path, "c.html", other), [])
    assert minhash_similarity(_vec(a, "html.dom_minhash"), _vec(c, "html.dom_minhash")) < 0.2
    assert minhash_similarity(_vec(a, "html.css_minhash"), _vec(c, "html.css_minhash")) == 0.0


def test_shingles_and_classes() -> None:
    html = "<html><body><div class='A b'><p>x</p><p class='b'>y</p></div></body></html>"
    from fakecollector.extractors.html_page import parse_html

    soup = parse_html(html)
    assert css_classes(soup) == {"a", "b"}
    assert "0:html 1:body 2:div 3:p" in dom_shingles(soup)


def test_tiny_pages_give_no_minhash(tmp_path: Path) -> None:
    fs = TemplateExtractor().extract(_art(tmp_path, "e.html", "<html></html>"), [])
    assert not [f for f in fs if f.name.endswith("_minhash")]


def test_first_party_path_signatures_and_sdk_from_har(tmp_path: Path) -> None:
    def har(host: str) -> Artifact:
        entries = [
            {
                "request": {"method": "GET", "url": f"https://{host}/"},
                "response": {"status": 200, "content": {"mimeType": "text/html"}},
            },
            {
                "request": {
                    "method": "GET",
                    "url": f"https://{host}/_cdn/landing-cdn/0f8fad5b-d9cb-469f-a165-70867728950e/a1/img-1-hero.webp",
                },
                "response": {"status": 200, "content": {"mimeType": "image/webp"}},
            },
            {
                "request": {"method": "GET", "url": f"https://{host}/aio-static/sdk/main.js?v=3"},
                "response": {"status": 200, "content": {"mimeType": "application/javascript"}},
            },
            {
                "request": {"method": "GET", "url": "https://cdn.other.test/lib/123/x.js"},
                "response": {"status": 200, "content": {"mimeType": "application/javascript"}},
            },
        ]
        p = tmp_path / f"{host}.har"
        p.write_text(json.dumps({"log": {"creator": {"name": "t"}, "entries": entries}}))
        return Artifact(id="h" * 16, case_id="T:h", kind="har", role="network", path=p, size=1)

    def sigs(host: str) -> tuple[set[str], set[str]]:
        fs = TemplateExtractor().extract(har(host), [])
        return (
            {f.value for f in fs if f.name == "kit.path_sig"},
            {f.value for f in fs if f.name == "kit.sdk"},
        )

    paths_a, sdk_a = sigs("one.live")
    paths_b, sdk_b = sigs("two.click")
    assert paths_a == paths_b
    assert not any("hero.webp" in p for p in paths_a)  # story image: not a kit signature
    assert all("other.test" not in p and "/lib/" not in p for p in paths_a)
    assert sdk_a == sdk_b == {"/aio-static/sdk/main.js"}
