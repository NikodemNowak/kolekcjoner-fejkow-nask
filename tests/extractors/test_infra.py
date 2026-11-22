import json
from pathlib import Path

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.infra import RequestGraphExtractor, registrable_domain


def _values(fs: list[Feature], name: str) -> set[str]:
    return {f.value for f in fs if f.name == name}


def _entry(
    url: str, method: str = "GET", status: int = 200, mime: str = "text/html", redirect: str = ""
) -> dict[str, object]:
    return {
        "request": {"method": method, "url": url},
        "response": {
            "status": status,
            "headers": [],
            "content": {"mimeType": mime},
            "redirectURL": redirect,
        },
    }


def _har_art(tmp_path: Path, entries: list[dict[str, object]], name: str = "x.har") -> Artifact:
    p = tmp_path / name
    p.write_text(json.dumps({"log": {"creator": {"name": "t"}, "entries": entries}}))
    return Artifact(id="7" * 16, case_id="T:1", kind="har", role="network", path=p, size=1)


def test_registrable_domain_uses_private_suffixes() -> None:
    assert registrable_domain("watch.example-lander.com") == "example-lander.com"
    assert registrable_domain("a.github.io") == "a.github.io"
    assert registrable_domain("a.github.io") != registrable_domain("b.github.io")
    assert registrable_domain("203.0.113.5") == "203.0.113.5"


def test_third_party_hosts_and_first_party_split(tmp_path: Path) -> None:
    art = _har_art(
        tmp_path,
        [
            _entry("https://www.lander.click/?clickid=1"),
            _entry("https://cdn.lander.click/app.js", mime="application/javascript"),
            _entry("https://t1.example-tracker.org/t.gif?x=1", mime="image/gif"),
            _entry("https://www.facebook.com/tr?id=1", mime="image/gif"),
        ],
    )
    fs = RequestGraphExtractor().extract(art, [])
    assert _values(fs, "infra.host_3p") == {"t1.example-tracker.org", "www.facebook.com"}
    assert _values(fs, "url.domain") == {"lander.click"}
    assert _values(fs, "url.schema") == {"/?clickid"}


def test_endpoints_are_domain_independent_for_first_party(tmp_path: Path) -> None:
    def endpoints(host: str) -> set[str]:
        art = _har_art(
            tmp_path,
            [
                _entry(f"https://{host}/"),
                _entry(
                    f"https://{host}/api/v1/trigger/field/123/",
                    method="POST",
                    mime="application/json",
                ),
                _entry(
                    "https://xd-f1.ecs.on.aws/events?cee=no", method="POST", mime="application/json"
                ),
            ],
            name=f"{host}.har",
        )
        return _values(RequestGraphExtractor().extract(art, []), "infra.endpoint")

    a, b = endpoints("one.live"), endpoints("two.click")
    assert a == b
    assert not any("{1p}" in v for v in a)  # first-party kit API is toolkit (kit.path_sig)
    assert "POST xd-f1.ecs.on.aws/events?cee" in a


def test_redirect_hops_from_har(tmp_path: Path) -> None:
    art = _har_art(
        tmp_path,
        [
            _entry("https://ad.tracker.top/c?k=1", status=302, redirect="https://lander.click/"),
            _entry("https://lander.click/"),
        ],
    )
    fs = RequestGraphExtractor().extract(art, [])
    assert _values(fs, "infra.redirect_hop") == {"ad.tracker.top"}
    assert _values(fs, "url.domain") == {"lander.click"}


def test_saved_html_gives_resources_outlinks_and_js_redirects(tmp_path: Path) -> None:
    p = tmp_path / "a.html"
    p.write_text(
        '<html><head><meta http-equiv="refresh" content="5; url=https://next.example.org/x">'
        '<script src="https://cdn.tracker-example.test/s.js"></script>'
        '<script src="/local.js"></script></head><body>'
        '<a href="https://shop.other.top/buy?id=1">kup</a><a href="#top">x</a>'
        '<form action="https://api.other.top/order" method="post"></form>'
        "<script>window.location.replace('https://jump.away.icu/');</script></body></html>"
    )
    art = Artifact(
        id="8" * 16,
        case_id="T:1",
        kind="html",
        role="landing_page",
        path=p,
        size=1,
        meta={"url": "https://www.lander.click/a"},
    )
    fs = RequestGraphExtractor().extract(art, [])
    assert _values(fs, "infra.host_3p") == {"cdn.tracker-example.test"}
    assert _values(fs, "url.outlink_domain") == {"other.top"}
    assert _values(fs, "infra.redirect_hop") == {"next.example.org", "jump.away.icu"}
    assert _values(fs, "url.domain") == {"lander.click"}
    assert "POST {1p}/order" not in _values(fs, "infra.endpoint")
    assert "POST api.other.top/order" in _values(fs, "infra.endpoint")


def test_broken_har_is_not_fatal(tmp_path: Path) -> None:
    p = tmp_path / "b.har"
    p.write_text("{")
    art = Artifact(id="9" * 16, case_id="T:1", kind="har", role="network", path=p, size=1)
    assert RequestGraphExtractor().extract(art, []) == []


def test_fixture_cases_share_collector_endpoint(fixture_artifacts: list[Artifact]) -> None:
    ex = RequestGraphExtractor()
    by_case: dict[str, set[str]] = {}
    for a in fixture_artifacts:
        if ex.supports(a):
            for f in ex.extract(a, []):
                if f.name == "infra.host_3p":
                    by_case.setdefault(f.case_id, set()).add(f.value)
    assert "collector.fixture-stats.click" in by_case["F:f1"] & by_case["F:f2"]


def test_subresource_redirects_are_not_hops(tmp_path: Path) -> None:
    video = _entry(
        "https://cdn.video.test/v.mp4",
        status=302,
        mime="video/mp4",
        redirect="https://edge.video.test/v.mp4",
    )
    video["_resourceType"] = "media"
    art = _har_art(
        tmp_path,
        [
            {**_entry("https://lander.click/"), "_resourceType": "document"},
            video,
        ],
    )
    fs = RequestGraphExtractor().extract(art, [])
    assert _values(fs, "infra.redirect_hop") == set()
    assert "cdn.video.test" in _values(fs, "infra.host_3p")


def test_document_redirect_without_resource_types_is_a_hop(tmp_path: Path) -> None:
    art = _har_art(
        tmp_path,
        [
            _entry("https://ad.tracker.top/c", status=302, redirect="https://lander.click/"),
            _entry("https://lander.click/"),
            _entry(
                "https://img.cdn.test/a.png",
                status=301,
                mime="image/png",
                redirect="https://x.cdn.test/a.png",
            ),
        ],
    )
    assert _values(RequestGraphExtractor().extract(art, []), "infra.redirect_hop") == {
        "ad.tracker.top"
    }


def test_single_label_hosts_are_not_third_parties(tmp_path: Path) -> None:
    art = _har_art(
        tmp_path,
        [
            _entry("https://lander.click/"),
            _entry("https://delivered/ping", method="POST", mime="text/plain"),
            _entry("http://203.0.113.7/c.gif", mime="image/gif"),
        ],
    )
    hosts = _values(RequestGraphExtractor().extract(art, []), "infra.host_3p")
    assert hosts == {"203.0.113.7"}


def test_har_without_landing_uses_the_case_url_as_first_party(tmp_path: Path) -> None:
    entries = [
        {
            **_entry("https://cdn.lander.click/app.js", mime="application/javascript"),
            "_resourceType": "script",
        },
        {
            **_entry("https://lander.click/img/hero.webp", mime="image/webp"),
            "_resourceType": "image",
        },
        {
            **_entry("https://t1.example-tracker.org/t.gif", mime="image/gif"),
            "_resourceType": "image",
        },
    ]
    art = _har_art(tmp_path, entries)
    art.meta["case_url"] = "https://www.lander.click/a"
    fs = RequestGraphExtractor().extract(art, [])
    assert _values(fs, "infra.host_3p") == {"t1.example-tracker.org"}
    assert _values(fs, "kit.dep_host") == set()
    assert _values(fs, "url.domain") == set()  # the HAR itself did not record the page


def test_saved_html_ignores_single_label_hosts(tmp_path: Path) -> None:
    p = tmp_path / "a.html"
    p.write_text('<img src="https://delivered/x.png"><img src="https://img.cdn-x.org/y.png">')
    art = Artifact(
        id="8" * 16,
        case_id="T:1",
        kind="html",
        role="landing_page",
        path=p,
        size=1,
        meta={"url": "https://www.lander.click/a"},
    )
    assert _values(RequestGraphExtractor().extract(art, []), "infra.host_3p") == {"img.cdn-x.org"}
