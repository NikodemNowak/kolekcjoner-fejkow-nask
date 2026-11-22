import json
import shutil
from pathlib import Path

import pytest

from fakecollector.ingest.casefolder import discover_cases, load_case, load_corpus

PAGE = (
    "<!-- saved from url=(0024){url} -->"
    "<html><head><title>{title}</title></head><body>{body}</body></html>"
)


def _page(path: Path, url: str, title: str = "T", body: str = "x" * 600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PAGE.format(url=url, title=title, body=body), encoding="utf-8")
    return path


def _har(path: Path, url: str, status: int = 200) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "startedDateTime": "2026-10-08T09:09:40.000Z",
        "request": {"method": "GET", "url": url},
        "response": {"status": status, "headers": [], "content": {"mimeType": "text/html"}},
    }
    path.write_text(json.dumps({"log": {"creator": {"name": "t"}, "entries": [entry]}}), "utf-8")
    return path


def _browser_case(root: Path, name: str, url: str, body: str = "x" * 600) -> Path:
    case = root / name
    _page(case / "Artykuł.html", url, body=body)
    (case / "Artykuł_files").mkdir()
    (case / "Artykuł_files" / "hero.webp").write_bytes(b"\x01" * 2048)
    (case / "Artykuł_files" / "main.js.pobrane").write_bytes(b"var x=1;" * 100)
    _har(case / "lander.test.har", url)
    (case / "Zrzut ekranu 1.png").write_bytes(b"\x89PNG" + b"\x02" * 1000)
    return case


def test_browser_save_is_mapped_to_roles(tmp_path: Path) -> None:
    case_dir = _browser_case(tmp_path, "c1", "https://lander.test/a?utm_source=fb&id=1")
    case, arts = load_case(case_dir, "T")
    roles = {a.path.name: (a.kind, a.role) for a in arts}
    assert case.id == "T:c1"
    assert roles["Artykuł.html"] == ("html", "landing_page")
    assert roles["hero.webp"] == ("asset", "landing_asset")
    assert roles["main.js.pobrane"] == ("asset", "landing_asset")
    assert roles["lander.test.har"] == ("har", "network")
    assert roles["Zrzut ekranu 1.png"] == ("image", "screenshot")
    page = next(a for a in arts if a.role == "landing_page")
    assert all(a.parent_id == page.id for a in arts if a.role == "landing_asset")
    assert case.landing_urls == ["https://lander.test/a?id=1"]


def test_archive_format_and_capture_meta(tmp_path: Path) -> None:
    cap = tmp_path / "c2" / "archive_beta.test_20261008"
    _har(cap / "network.har", "https://beta.test/")
    _page(cap / "html" / "rendered.html", "https://beta.test/")
    (cap / "archive_info.json").write_text(
        json.dumps({"url": "https://beta.test/?gclid=9", "timestamp_utc": "2026-10-08T09:09:40Z"})
    )
    (cap / "dns_ssl.json").write_text("{}")
    (cap / "screenshots").mkdir()
    (cap / "screenshots" / "full.png").write_bytes(b"\x89PNG" + b"\x03" * 900)
    (tmp_path / "c2" / "archive_beta.test_20261008.zip").write_bytes(b"PK")
    case, arts = load_case(tmp_path / "c2", "T")
    kinds = {a.path.name: (a.kind, a.role) for a in arts}
    assert kinds["archive_info.json"] == ("json", "capture_meta")
    assert kinds["dns_ssl.json"] == ("json", "dns_tls")
    assert kinds["full.png"] == ("image", "screenshot")
    assert "archive_beta.test_20261008.zip" not in kinds  # duplicates its folder
    assert case.landing_urls == ["https://beta.test/"]
    assert case.captured_at is not None


def test_duplicate_case_is_flagged(tmp_path: Path) -> None:
    _browser_case(tmp_path, "a", "https://lander.test/")
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    cases, _ = load_corpus(tmp_path, "T")
    by_id = {c.id: c for c in cases}
    assert by_id["T:a"].duplicate_of is None
    assert by_id["T:b"].duplicate_of == "T:a"


def test_cloaked_variants_are_kept(tmp_path: Path) -> None:
    case = tmp_path / "c61"
    _page(case / "strona_1" / "a.html", "https://glow.test/", body="scam " * 200)
    _page(case / "strona_2" / "b.html", "https://glow.test/", body="shop " * 200)
    c, arts = load_case(case, "T")
    pages = sorted(a.page or "" for a in arts if a.role == "landing_page")
    assert pages == ["strona_1", "strona_2"]
    assert "cloaking_suspected" in c.flags
    marked = {a.page for a in arts if a.meta.get("cloaking_suspected")}
    assert marked == {"strona_1", "strona_2"}  # unknown which one is the decoy


def test_corrupt_file_is_skipped_not_fatal(tmp_path: Path) -> None:
    case = tmp_path / "bad"
    case.mkdir()
    (case / "x.png").write_bytes(b"not an image")
    (case / "broken.har").write_text('{"log": {"entries": [', encoding="utf-8")
    c, arts = load_case(case, "T")
    assert {a.path.name for a in arts} == {"x.png", "broken.har"}
    assert c.landing_urls == []


def test_hidden_and_mojibake_names(tmp_path: Path) -> None:
    case = tmp_path / "m"
    case.mkdir()
    _har(case / ".har", "https://hidden.test/")
    _page(case / "Trudna odpowied½.htm", "https://hidden.test/")
    raw = bytes(case) + b"/PILNE_ napa\xff\xe5.html"
    try:
        Path(raw.decode("utf-8", "surrogateescape")).write_text("<html></html>", "utf-8")
    except OSError:
        pytest.skip("filesystem rejects non-UTF-8 names")
    c, arts = load_case(case, "T")
    kinds = sorted(a.kind for a in arts)
    assert kinds == ["har", "html", "html"]
    assert c.landing_urls == ["https://hidden.test/"]


def test_capture_error_and_video_only_flags(tmp_path: Path) -> None:
    dead = tmp_path / "dead"
    _har(dead / "d.har", "https://dead.test/", status=502)
    vid = tmp_path / "vid"
    vid.mkdir()
    (vid / "ad.mp4").write_bytes(b"\x00" * 2000)
    assert "capture_error" in load_case(dead, "T")[0].flags
    case, arts = load_case(vid, "T")
    assert "video_only" in case.flags
    assert arts[0].kind == "video"


def test_discover_cases_handles_corpus_and_single_case(tmp_path: Path) -> None:
    _browser_case(tmp_path, "a", "https://a.test/")
    _browser_case(tmp_path, "b", "https://b.test/")
    assert [p.name for p in discover_cases(tmp_path)] == ["a", "b"]
    assert discover_cases(tmp_path / "a") == [tmp_path / "a"]


def test_landing_url_priority_prefers_capture_meta(tmp_path: Path) -> None:
    case = tmp_path / "p"
    _har(case / "n.har", "https://from-har.test/")
    _page(case / "a.html", "https://from-html.test/")
    (case / "manifest.json").write_text(json.dumps({"url": "https://from-meta.test/x"}))
    c, _ = load_case(case, "T")
    assert c.landing_urls[0] == "https://from-meta.test/x"


def test_naive_and_aware_timestamps_mix(tmp_path: Path) -> None:
    case = tmp_path / "t"
    _har(case / "n.har", "https://t.test/")  # aware (Z)
    (case / "archive_info.json").write_text(json.dumps({"timestamp_utc": "2026-10-08T08:00:00"}))
    c, _ = load_case(case, "T")
    assert c.captured_at is not None
    assert c.captured_at.tzinfo is not None
    assert c.captured_at.hour == 8


def test_har_without_landing_gets_the_case_url(tmp_path: Path) -> None:
    case = tmp_path / "h"
    _page(case / "a.html", "https://lander.test/x")
    har = case / "n.har"
    har.write_text(
        json.dumps({"log": {"pages": [{"title": "file:///tmp/a.html"}], "entries": []}}), "utf-8"
    )
    _, arts = load_case(case, "T")
    by_name = {a.path.name: a for a in arts}
    assert "landing_url" not in by_name["n.har"].meta
    assert by_name["n.har"].meta["case_url"] == "https://lander.test/x"
