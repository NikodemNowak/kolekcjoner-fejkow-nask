import base64
import json
from pathlib import Path

import mmh3

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.infra_meta import InfraMetaExtractor, favicon_hash


def _values(fs: list[Feature], name: str) -> set[str]:
    return {f.value for f in fs if f.name == name}


def _har(tmp_path: Path, entries: list[dict[str, object]]) -> Artifact:
    p = tmp_path / "x.har"
    p.write_text(json.dumps({"log": {"creator": {"name": "t"}, "entries": entries}}))
    return Artifact(id="a" * 16, case_id="T:1", kind="har", role="network", path=p, size=1)


def _e(
    url: str,
    ip: str = "203.0.113.10",
    mime: str = "text/html",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    content: dict[str, object] = {"mimeType": mime}
    if body is not None:
        content.update({"text": base64.b64encode(body).decode(), "encoding": "base64"})
    resp: dict[str, object] = {
        "status": 200,
        "headers": [{"name": k, "value": v} for k, v in (headers or {}).items()],
        "content": content,
    }
    resp.update(extra or {})
    return {"serverIPAddress": ip, "request": {"method": "GET", "url": url}, "response": resp}


def test_favicon_hash_is_shodan_style() -> None:
    data = b"\x00\x00\x01\x00" + b"icon" * 100
    assert favicon_hash(data) == str(mmh3.hash(base64.encodebytes(data)))


def test_server_stack_ip_and_favicon_from_har(tmp_path: Path) -> None:
    icon = b"\x00\x00\x01\x00" + b"x" * 600
    art = _har(
        tmp_path,
        [
            _e(
                "https://lander.click/",
                headers={"Server": "nginx/1.26.3", "X-Powered-By": "PHP/8.4.25"},
            ),
            _e("https://lander.click/favicon.ico", mime="image/x-icon", body=icon),
            _e("https://cdn.other.test/a.js", ip="151.101.1.1", mime="application/javascript"),
        ],
    )
    fs = InfraMetaExtractor().extract(art, [])
    assert _values(fs, "infra.server_stack") == {"server=nginx/1|x-powered-by=php/8"}
    assert _values(fs, "infra.ip") == {"203.0.113.10"}
    assert _values(fs, "infra.favicon_mmh3") == {favicon_hash(icon)}


def test_cdn_ips_are_not_emitted(tmp_path: Path) -> None:
    art = _har(
        tmp_path,
        [_e("https://lander.click/", ip="188.114.96.11", headers={"Server": "cloudflare"})],
    )
    fs = InfraMetaExtractor().extract(art, [])
    assert _values(fs, "infra.ip") == set()
    assert _values(fs, "infra.server_stack") == {"server=cloudflare"}


def test_tls_details_from_playwright_har(tmp_path: Path) -> None:
    sec = {
        "_securityDetails": {
            "issuer": "WE1",
            "subjectName": "lander.click",
            "sanList": ["lander.click", "*.lander.click", "other.live"],
        }
    }
    fs = InfraMetaExtractor().extract(_har(tmp_path, [_e("https://lander.click/", extra=sec)]), [])
    assert _values(fs, "infra.cert_issuer") == {"we1"}
    assert _values(fs, "infra.cert_san") == {"lander.click", "other.live"}


def test_dns_ssl_json(tmp_path: Path) -> None:
    p = tmp_path / "dns_ssl.json"
    p.write_text(
        json.dumps(
            {
                "hostname": "lander.click",
                "ip": "188.114.97.11",
                "all_addresses": ["188.114.97.11", "203.0.113.20"],
                "ssl": {
                    "issuer": [
                        [["countryName", "US"]],
                        [["organizationName", "Google Trust Services"]],
                        [["commonName", "WE1"]],
                    ],
                    "subjectAltName": [
                        ["DNS", "lander.click"],
                        ["DNS", "*.lander.click"],
                        ["DNS", "twin.top"],
                    ],
                },
            }
        )
    )
    art = Artifact(id="b" * 16, case_id="T:1", kind="json", role="dns_tls", path=p, size=1)
    fs = InfraMetaExtractor().extract(art, [])
    assert _values(fs, "infra.ip") == {"203.0.113.20"}
    assert _values(fs, "infra.cert_issuer") == {"we1"}
    assert _values(fs, "infra.cert_san") == {"lander.click", "twin.top"}


def test_favicon_asset_in_saved_page(tmp_path: Path) -> None:
    p = tmp_path / "favicon.ico"
    p.write_bytes(b"\x00\x00\x01\x00" + b"y" * 700)
    art = Artifact(id="c" * 16, case_id="T:1", kind="asset", role="landing_asset", path=p, size=704)
    [f] = InfraMetaExtractor().extract(art, [])
    assert f.name == "infra.favicon_mmh3"
    assert f.value == favicon_hash(p.read_bytes())


def test_broken_inputs_are_not_fatal(tmp_path: Path) -> None:
    p = tmp_path / "dns_ssl.json"
    p.write_text("{")
    art = Artifact(id="d" * 16, case_id="T:1", kind="json", role="dns_tls", path=p, size=1)
    assert InfraMetaExtractor().extract(art, []) == []
