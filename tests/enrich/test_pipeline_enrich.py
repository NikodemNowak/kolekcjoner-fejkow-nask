"""A4 (plan v2): enrichment runs inside the pipeline when ALLOW_ENRICH is on."""

from pathlib import Path

import pytest

from fakecollector.config import get_settings
from fakecollector.core.schemas import Artifact, Case
from fakecollector.enrich import http
from fakecollector.extractors.infra import RequestGraphExtractor
from fakecollector.pipeline import extract
from fakecollector.store import RunStore


def _store(tmp_path: Path) -> RunStore:
    page = tmp_path / "page.html"
    page.write_text("<!-- saved from url=(0024)https://lander.click/ --><html></html>")
    store = RunStore(tmp_path / "run")
    store.write_cases(
        [Case(id="T:1", corpus="T", path=tmp_path)],
        [
            Artifact(
                id="p" * 16,
                case_id="T:1",
                kind="html",
                role="landing_page",
                path=page,
                size=1,
                meta={"url": "https://lander.click/"},
            )
        ],
    )
    return store


def test_enrichment_features_are_stored_when_enabled(tmp_path: Path, net: list[str]) -> None:
    store = _store(tmp_path)
    extract(store, extractors=[RequestGraphExtractor()])
    names = {f.name for f in store.features()}
    assert {"url.domain", "infra.ns", "infra.registered"} <= names
    assert all(f.case_id == "T:1" for f in store.features() if f.name == "infra.ns")


def test_no_network_and_no_enrichment_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALLOW_ENRICH", raising=False)
    get_settings.cache_clear()

    def boom(*args: object) -> bytes:
        raise AssertionError("network used while enrichment is off")

    monkeypatch.setattr(http, "_download", boom)
    store = _store(tmp_path)
    extract(store, extractors=[RequestGraphExtractor()])
    assert not {f.name for f in store.features()} & {"infra.ns", "infra.asn", "infra.registrar"}


def test_malformed_lookup_does_not_abort_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, net: list[str]
) -> None:
    from fakecollector.enrich import dns_tls

    monkeypatch.setattr(dns_tls, "resolve", lambda name, rtype: [" | malformed"])
    store = _store(tmp_path)
    extract(store, extractors=[RequestGraphExtractor()])


def test_enrichment_cleared_when_disabled_after_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, net: list[str]
) -> None:
    store = _store(tmp_path)
    extract(store, extractors=[RequestGraphExtractor()])
    assert any(f.name == "infra.ns" for f in store.features())

    monkeypatch.delenv("ALLOW_ENRICH", raising=False)
    get_settings.cache_clear()
    extract(store, extractors=[])
    assert not any(f.name == "infra.ns" for f in store.features())
