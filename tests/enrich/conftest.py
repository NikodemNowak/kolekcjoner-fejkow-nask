import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from fakecollector.config import get_settings
from fakecollector.enrich import http

Responder = Callable[[str], bytes | None]


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[list[str]]:
    """Enable enrichment, isolate the cache and serve canned responses; yields called URLs."""
    monkeypatch.setenv("ALLOW_ENRICH", "true")
    monkeypatch.setenv("APP_ENRICH_CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    calls: list[str] = []

    def fake(url: str, accept: str | None, timeout: float) -> bytes | None:
        calls.append(url)
        return _respond(url)

    monkeypatch.setattr(http, "_download", fake)
    yield calls
    get_settings.cache_clear()


def _doh(*data: str) -> bytes:
    return json.dumps({"Status": 0, "Answer": [{"data": d} for d in data]}).encode()


def _respond(url: str) -> bytes | None:
    if "type=NS" in url and "lander.click" in url:
        return _doh("bob.ns.cloudflare.com.", "aria.ns.cloudflare.com.")
    if "4.3.2.1.origin.asn.cymru.com" in url:
        return _doh('"14061 | 1.2.3.0/24 | US | arin | 2012-09-25"')
    if "AS14061.asn.cymru.com" in url:
        return _doh('"14061 | US | arin | 2012-09-25 | DIGITALOCEAN-ASN, US"')
    if "rdap.org/domain/lander.click" in url:
        return json.dumps(
            {
                "events": [{"eventAction": "registration", "eventDate": "2026-09-30T10:00:00Z"}],
                "entities": [
                    {
                        "roles": ["registrar"],
                        "vcardArray": ["vcard", [["fn", {}, "text", "NameSilo, LLC"]]],
                    }
                ],
            }
        ).encode()
    if "crt.sh" in url and "lander.click" in url:
        return json.dumps(
            [
                {
                    "issuer_name": "C=US, O=Let's Encrypt, CN=E6",
                    "name_value": "lander.click\n*.lander.click",
                },
                {
                    "issuer_name": "C=US, O=Google Trust Services, CN=WE1",
                    "name_value": "lander.click\ntwin.top",
                },
            ]
        ).encode()
    if "hole.cert.pl" in url:
        return b"bad.example\nlander.click\n\n"
    return None


@pytest.fixture(autouse=True)
def _fresh_cert_list() -> Iterator[None]:
    from fakecollector.enrich import cert_hole

    cert_hole._loaded.clear()
    http._failed.clear()
    yield
    cert_hole._loaded.clear()
    http._failed.clear()
