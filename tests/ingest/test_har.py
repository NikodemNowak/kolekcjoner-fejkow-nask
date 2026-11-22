import base64
import hashlib
import json
from pathlib import Path

import pytest

from fakecollector.ingest.har import HarError, parse_har


def _entry(url: str, status: int = 200, mime: str = "text/html", **kw: object) -> dict[str, object]:
    content: dict[str, object] = {"mimeType": mime, "size": 4}
    content.update(kw.pop("content", {}))  # type: ignore[arg-type]
    return {
        "startedDateTime": "2026-10-08T09:09:40.000Z",
        "serverIPAddress": kw.get("ip", "203.0.113.5"),
        "request": {"method": "GET", "url": url},
        "response": {
            "status": status,
            "headers": [{"name": "Server", "value": "nginx"}],
            "content": content,
            "redirectURL": kw.get("redirect", ""),
        },
    }


def _write(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    har = {"log": {"creator": {"name": "WebInspector"}, "pages": [], "entries": entries}}
    p = tmp_path / "x.har"
    p.write_text(json.dumps(har), encoding="utf-8")
    return p


def test_parse_har_finds_landing_and_entries(tmp_path: Path) -> None:
    body = b"<html>hi</html>"
    p = _write(
        tmp_path,
        [
            _entry(
                "https://lander.test/a?clickid=1",
                content={"text": base64.b64encode(body).decode(), "encoding": "base64"},
            ),
            _entry(
                "https://cdn.test/x.js", mime="application/javascript", content={"text": "var a"}
            ),
        ],
    )
    har = parse_har(p)
    assert har.creator == "WebInspector"
    assert har.landing_url == "https://lander.test/a?clickid=1"
    first = har.entries[0]
    assert first.host == "lander.test"
    assert first.ip == "203.0.113.5"
    assert first.headers["server"] == "nginx"
    assert first.body_sha256 == hashlib.sha256(body).hexdigest()
    assert har.entries[1].body_sha256 == hashlib.sha256(b"var a").hexdigest()


def test_landing_skips_redirects_and_errors(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        [
            _entry("https://ad.test/c", status=302, redirect="https://lander.test/"),
            _entry("https://lander.test/", status=200),
        ],
    )
    har = parse_har(p)
    assert har.entries[0].redirect_to == "https://lander.test/"
    assert har.landing_url == "https://lander.test/"
    assert har.landing_status == 200


def test_error_capture_reports_status(tmp_path: Path) -> None:
    har = parse_har(_write(tmp_path, [_entry("https://dead.test/", status=502)]))
    assert har.landing_url == "https://dead.test/"
    assert har.landing_status == 502


def test_truncated_har_raises_har_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.har"
    p.write_text('{"log": {"entries": [', encoding="utf-8")
    with pytest.raises(HarError):
        parse_har(p)
