from pathlib import Path

import pytest

from fakecollector.config import get_settings
from fakecollector.core.schemas import Feature
from fakecollector.enrich import enrich_case, enrich_domain, enrich_ip, http, on_cert_list


def _values(fs: list[Feature], name: str) -> set[str]:
    return {f.value for f in fs if f.name == name}


def test_disabled_by_default_and_never_touches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_ENRICH", raising=False)
    get_settings.cache_clear()

    def boom(*args: object) -> bytes:
        raise AssertionError("network used while enrichment is off")

    monkeypatch.setattr(http, "_download", boom)
    assert enrich_domain("lander.click") == []
    assert on_cert_list(["lander.click"]) == set()


def test_enrich_domain_collects_ns_rdap_and_certs(net: list[str]) -> None:
    fs = enrich_domain("www.lander.click", case_id="T:1", artifact_id="a" * 16)
    assert _values(fs, "infra.ns") == {"aria.ns.cloudflare.com+bob.ns.cloudflare.com"}
    assert _values(fs, "infra.registered") == {"2026-09"}
    assert _values(fs, "infra.registrar") == {"namesilo, llc"}
    assert _values(fs, "infra.cert_issuer") == {"e6", "we1"}
    assert _values(fs, "infra.cert_san") == {"twin.top"}  # the domain itself is not evidence
    assert all(f.case_id == "T:1" and f.artifact_id == "a" * 16 for f in fs)
    assert all("lander.click" in u for u in net if "cymru" not in u)  # registrable domain only


def test_asn_for_non_cdn_ip_only(net: list[str]) -> None:
    fs = enrich_case(
        "T:1",
        [
            Feature(case_id="T:1", artifact_id="b" * 16, name="infra.ip", value="1.2.3.4"),
            Feature(case_id="T:1", artifact_id="b" * 16, name="infra.ip", value="188.114.96.11"),
        ],
    )
    assert _values(fs, "infra.asn") == {"AS14061"}
    assert not any("11.96.114.188" in u for u in net)


def test_responses_are_cached_on_disk(net: list[str]) -> None:
    enrich_domain("lander.click")
    first = len(net)
    enrich_domain("lander.click")
    assert len(net) == first
    assert any(Path(get_settings().enrich_cache_dir).iterdir())


def test_failures_are_not_fatal(net: list[str]) -> None:
    assert enrich_domain("unknown.test") == []


def test_cert_list_matches_registrable_domains(net: list[str]) -> None:
    assert on_cert_list(["www.lander.click", "fine.org", "bad.example"]) == {
        "www.lander.click",
        "bad.example",
    }


def test_enrich_case_uses_url_domains(net: list[str]) -> None:
    fs = enrich_case(
        "T:1",
        [Feature(case_id="T:1", artifact_id="c" * 16, name="url.domain", value="lander.click")],
    )
    assert "infra.ns" in {f.name for f in fs}
    assert all(f.artifact_id == "c" * 16 for f in fs)


def test_enrichment_features_are_registered() -> None:
    from fakecollector.core.registry import FEATURES

    for name in [
        "infra.ns",
        "infra.asn",
        "infra.registrar",
        "infra.registered",
        "infra.cert_issuer",
        "infra.cert_san",
    ]:
        assert name in FEATURES


def test_failed_lookups_are_not_cached_on_disk(net: list[str]) -> None:
    http._failed.clear()
    enrich_domain("unknown-site.click")
    calls = len(net)
    enrich_domain("unknown-site.click")
    assert len(net) == calls  # not retried in the same process
    http._failed.clear()
    enrich_domain("unknown-site.click")
    assert len(net) > calls  # retried in a new run


def test_private_and_non_public_inputs_are_never_sent(net: list[str]) -> None:
    for domain in ["localhost", "intranet", "printer.local", "10.0.0.1", "192.168.1.1"]:
        assert enrich_domain(domain) == []
    for ip in ["10.1.2.3", "192.168.0.5", "127.0.0.1", "169.254.1.1", "::1", "not-an-ip"]:
        assert enrich_ip(ip) == []
    assert net == []  # zero requests


def test_shared_hosting_nameservers_are_not_operator_evidence(
    net: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakecollector import enrich

    parked = ["ns1.dns-parking.com", "ns2.dns-parking.com"]
    monkeypatch.setattr(enrich, "nameservers", lambda d: parked)
    assert "infra.ns" not in {f.name for f in enrich_domain("lander.click")}


def test_certificates_with_many_names_are_shared_not_operator_evidence(
    net: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakecollector import enrich

    shared = [f"site{i}.test" for i in range(40)]
    monkeypatch.setattr(
        enrich, "certificates", lambda d: [("r3", shared), ("e6", ["lander.click", "twin.top"])]
    )
    sans = {f.value for f in enrich_domain("lander.click") if f.name == "infra.cert_san"}
    assert sans == {"twin.top"}
