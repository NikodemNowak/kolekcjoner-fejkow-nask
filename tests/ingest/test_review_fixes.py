"""Regression tests for the mentor-corpus review of the ingest (PR #7)."""

import json
from pathlib import Path

from fakecollector.ingest.casefolder import discover_cases, load_case
from fakecollector.ingest.har import parse_har
from fakecollector.ingest.normalize import redact_url


def _e(url: str, status: int, mime: str, rtype: str | None = None) -> dict[str, object]:
    e: dict[str, object] = {
        "request": {"method": "GET", "url": url},
        "response": {"status": status, "headers": [], "content": {"mimeType": mime}},
    }
    if rtype:
        e["_resourceType"] = rtype
    return e


def _har(path: Path, entries: list[dict[str, object]], page_title: str | None = None) -> Path:
    pages = [{"id": "page_1", "title": page_title}] if page_title else []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"log": {"creator": {"name": "t"}, "pages": pages, "entries": entries}})
    )
    return path


def test_trackers_and_status_zero_are_never_the_landing(tmp_path: Path) -> None:
    har = _har(
        tmp_path / "a.har",
        [
            _e("https://delivered/?id=", 0, "x-unknown", "image"),
            _e("https://glow.test/", 404, "x-unknown", "image"),
            _e("https://www.googletagmanager.com/gtag/js", 200, "application/javascript", "script"),
            _e("https://www.googletagmanager.com/a?id=AW-1", 200, "text/html", "image"),
        ],
        page_title="file:///C:/Users/x/Downloads/page.html",
    )
    summary = parse_har(har)
    assert summary.landing_url is None  # the page was opened from a local file


def test_page_title_url_is_the_landing(tmp_path: Path) -> None:
    har = _har(
        tmp_path / "b.har",
        [
            _e("https://cdn.test/x.css", 200, "text/css", "stylesheet"),
            _e("https://glow.test/?utm_id=1", 200, "text/html", "document"),
        ],
        page_title="https://glow.test/?utm_id=1",
    )
    assert parse_har(har).landing_url == "https://glow.test/?utm_id=1"


def test_first_document_is_the_landing_even_when_4xx(tmp_path: Path) -> None:
    har = _har(
        tmp_path / "c.har",
        [
            _e("https://www.googletagmanager.com/gtm.js", 200, "text/html"),
            _e("https://dead.test/", 404, "text/html", "document"),
        ],
    )
    summary = parse_har(har)
    assert summary.landing_url == "https://dead.test/"
    assert summary.landing_status == 404


def test_without_resource_types_trackers_are_skipped(tmp_path: Path) -> None:
    har = _har(
        tmp_path / "d.har",
        [
            _e("https://www.googletagmanager.com/ns.html?id=GTM-1", 200, "text/html"),
            _e("https://lander.test/", 200, "text/html"),
        ],
    )
    assert parse_har(har).landing_url == "https://lander.test/"


def test_tracker_landing_never_reaches_case_urls_and_4xx_flags_error(tmp_path: Path) -> None:
    case = tmp_path / "c"
    _har(
        case / "x.har",
        [
            _e("https://www.googletagmanager.com/a?id=AW-1", 200, "text/html", "image"),
            _e("https://dead.test/", 404, "text/html", "document"),
        ],
    )
    c, _ = load_case(case, "T")
    assert c.landing_urls == ["https://dead.test/"]
    assert "capture_error" in c.flags


def _page(path: Path, url: str, body: str, chrome: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<!-- saved from url=(0020){url} --><html><head>{chrome}</head><body>{body}</body></html>",
        encoding="utf-8",
    )


def test_same_page_saved_by_two_tools_is_not_cloaking(tmp_path: Path) -> None:
    text = " ".join(f"słowo{i}" for i in range(300))
    case = tmp_path / "same"
    _page(case / "strona_2" / "a.html", "https://glow.test/", f"<p>{text}</p>")
    _page(
        case / "strona_3" / "b.html",
        "https://glow.test/",
        f"<div class='x'><p>{text}</p></div>",
        chrome="<script>var saved=1</script>",
    )
    c, _ = load_case(case, "T")
    assert "cloaking_suspected" not in c.flags


def test_different_content_on_one_url_is_cloaking(tmp_path: Path) -> None:
    case = tmp_path / "cloak"
    _page(
        case / "strona_1" / "a.html",
        "https://glow.test/",
        " ".join(f"artykuł{i}" for i in range(300)),
    )
    _page(
        case / "strona_2" / "b.html",
        "https://glow.test/",
        " ".join(f"sklep{i}" for i in range(300)),
    )
    c, _ = load_case(case, "T")
    assert "cloaking_suspected" in c.flags


def test_redact_url_removes_secrets_but_keeps_campaign_ids() -> None:
    url = "https://x.test/p?access_token=EAAU123&fbclid=abc&key=k1&utm_campaign=c&id=5"
    red = redact_url(url)
    assert "EAAU123" not in red
    assert "access_token=REDACTED" in red
    assert "key=k1" in red and "utm_campaign=c" in red and "id=5" in red


def test_meta_urls_are_redacted(tmp_path: Path) -> None:
    case = tmp_path / "tok"
    _har(
        case / "x.har",
        [_e("https://l.test/?access_token=EAAU999&key=1", 200, "text/html", "document")],
    )
    _, arts = load_case(case, "T")
    assert all("EAAU999" not in v for a in arts for v in a.meta.values())


def test_case_folders_sort_naturally(tmp_path: Path) -> None:
    for name in ["10", "2", "1", "36", "p10", "p2"]:
        (tmp_path / name).mkdir()
    assert [p.name for p in discover_cases(tmp_path)] == ["1", "2", "10", "36", "p2", "p10"]


def test_non_http_saved_from_is_not_a_landing(tmp_path: Path) -> None:
    case = tmp_path / "about"
    case.mkdir()
    (case / "a.html").write_text("<!-- saved from url=(0014)about:internet --><html></html>")
    (case / "b.html").write_text(
        "<!-- saved from url=(0030)file:///C:/Users/x/page.html --><html></html>"
    )
    c, arts = load_case(case, "T")
    assert c.landing_urls == []
    assert all("url" not in a.meta for a in arts)


def _saved_page(path: Path, url: str) -> None:
    _page(path, url, " ".join(f"tekst{i}" for i in range(50)))


def test_misplaced_har_moves_to_the_case_with_its_landing(tmp_path: Path) -> None:
    from fakecollector.ingest.casefolder import load_corpus

    _saved_page(tmp_path / "a" / "page.html", "https://alpha.live/")
    _har(
        tmp_path / "a" / "alpha.live.har", [_e("https://alpha.live/", 200, "text/html", "document")]
    )
    _har(
        tmp_path / "a" / "beta.pro.har",
        [_e("https://beta.pro/?clickid=1", 200, "text/html", "document")],
    )
    _saved_page(tmp_path / "b" / "other.html", "https://beta.pro/?clickid=1")
    cases, arts = load_corpus(tmp_path, "T")
    by_id = {c.id: c for c in cases}
    har = next(a for a in arts if a.path.name == "beta.pro.har")
    assert har.case_id == "T:b"
    assert by_id["T:a"].landing_urls == ["https://alpha.live/"]
    assert "har_moved_out" in by_id["T:a"].flags
    assert "har_moved_in" in by_id["T:b"].flags


def test_unmatched_foreign_har_is_flagged_and_its_features_ignored(tmp_path: Path) -> None:
    from fakecollector.ingest.casefolder import load_corpus

    _saved_page(tmp_path / "a" / "page.html", "https://alpha.live/")
    _har(tmp_path / "a" / "gamma.top.har", [_e("https://gamma.top/", 200, "text/html", "document")])
    cases, arts = load_corpus(tmp_path, "T")
    assert not [a for a in arts if a.kind == "har"]  # another report's capture: not evidence
    assert "har_landing_mismatch" in cases[0].flags
    assert cases[0].landing_urls == ["https://alpha.live/"]


def test_single_folder_with_a_foreign_har_ignores_it(tmp_path: Path) -> None:
    from fakecollector.ingest.casefolder import load_corpus

    case = tmp_path / "m2"
    _saved_page(case / "page.html", "https://alpha.live/")
    _har(case / "alpha.live.har", [_e("https://alpha.live/", 200, "text/html", "document")])
    _har(case / "beta.pro.har", [_e("https://beta.pro/?clickid=1", 200, "text/html", "document")])
    [c], arts = load_corpus(case, "U")  # the assign path loads one folder on its own
    assert [a.path.name for a in arts if a.kind == "har"] == ["alpha.live.har"]
    assert "har_landing_mismatch" in c.flags


def test_har_only_case_is_never_considered_misplaced(tmp_path: Path) -> None:
    from fakecollector.ingest.casefolder import load_corpus

    _har(tmp_path / "a" / "x.har", [_e("https://alpha.live/", 200, "text/html", "document")])
    _saved_page(tmp_path / "b" / "page.html", "https://alpha.live/")
    cases, arts = load_corpus(tmp_path, "T")
    assert next(a for a in arts if a.kind == "har").case_id == "T:a"
    assert all("har_moved_in" not in c.flags for c in cases)
