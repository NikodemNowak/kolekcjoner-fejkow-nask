import json
from pathlib import Path

from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Artifact
from fakecollector.extractors.source_meta import (
    SourceMetaExtractor,
    clean_domain,
    clean_phone,
)
from fakecollector.ingest.casefolder import load_case


def _art(path: Path) -> Artifact:
    return Artifact(id="m" * 16, case_id="P:1", kind="json", role="source_meta", path=path, size=1)


def test_clean_domain_keeps_full_names_only() -> None:
    assert clean_domain("https://sxr.example-lander.top/x") == "example-lander.top"
    assert clean_domain("e*****.com") is None
    assert clean_domain("example[.]shop") == "example.shop"
    assert clean_domain("shop-x.tilda.ws") == "shop-x.tilda.ws"
    assert clean_domain("tilda.ws") is None


def test_clean_phone() -> None:
    assert clean_phone("500 600 700") == "+48500600700"
    assert clean_phone("+44 7700 900123") == "+447700900123"
    assert clean_phone("12") is None


def test_extract_maps_facts_to_features(tmp_path: Path) -> None:
    meta = {
        "landing_domains": [{"value": "https://a.example-lander.top", "provenance": "artykuł"}],
        "short_links": ["https://www.Bit.ly/AbC123", "bit.ly/a***"],
        "ad_library_ids": ["1234567890123456"],
        "advertisers": [{"value": "Quantum Veil AI", "provenance": "obraz"}],
        "phones": ["500 600 700"],
        "bank_accounts": ["PL 61 1090 1014 0000 0712 1981 2874"],
        "messengers": ["@helper_bot"],
        "platform": ["Facebook"],
        "persons": ["Jan Kowalski"],
        "enrichment": {
            "example-lander.top": {
                "ns": ["a.ns.example+b.ns.example"],
                "registrar": "Example Registrar",
                "cert_pl_listed": True,
            }
        },
    }
    path = tmp_path / "zrodlo_meta.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    feats = SourceMetaExtractor().extract(_art(path), [])
    got = {(f.name, f.value) for f in feats}
    assert ("url.domain", "example-lander.top") in got
    assert ("ids.short_link", "bit.ly/AbC123") in got
    assert not any(v.startswith("bit.ly/a*") for _, v in got)
    assert ("ids.ad_library", "1234567890123456") in got
    assert ("ad.advertiser", "quantum-veil-ai") in got
    assert ("ids.phone", "+48500600700") in got
    assert ("ids.bank_account", "61109010140000071219812874") in got
    assert ("ids.messenger", "helper_bot") in got
    assert ("meta.ns", "a.ns.example+b.ns.example") in got
    assert ("meta.registrar", "example registrar") in got
    assert ("meta.cert_pl_listed", "example-lander.top") in got
    assert ("meta.person", "Jan Kowalski") in got
    assert all(f.name in FEATURES for f in feats)
    # The publisher's labels never link cases.
    assert FEATURES["meta.person"].kind == "info"
    assert FEATURES["meta.registrar"].tier == "context"


def test_malformed_file_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "zrodlo_meta.json"
    path.write_text("[1, 2", encoding="utf-8")
    assert SourceMetaExtractor().extract(_art(path), []) == []


def test_casefolder_classifies_source_meta(tmp_path: Path) -> None:
    case = tmp_path / "c1"
    case.mkdir()
    (case / "zrzut.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (case / "zrodlo_meta.json").write_text("{}", encoding="utf-8")
    _, arts = load_case(case, "pub")
    roles = {a.path.name: a.role for a in arts}
    assert roles["zrodlo_meta.json"] == "source_meta"
    assert roles["zrzut.png"] == "screenshot"
