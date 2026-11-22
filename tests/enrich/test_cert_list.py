import pytest

from fakecollector.app import pl
from fakecollector.config import get_settings
from fakecollector.enrich import http
from fakecollector.enrich.cert_hole import cert_list_status, on_cert_list


def test_disabled_enrichment_is_unavailable_not_new(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_ENRICH", raising=False)
    get_settings.cache_clear()
    status = cert_list_status(["lander.click"])
    assert not status.available
    assert status.reason == "disabled"
    assert status.known == status.new == 0


def test_failed_fetch_is_unavailable(net: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http, "_download", lambda url, accept, timeout: None)
    status = cert_list_status(["lander.click", "fine.org"])
    assert not status.available
    assert status.reason == "fetch_failed"
    assert status.known == status.new == 0
    assert on_cert_list(["lander.click"]) == set()


def test_listed_subdomain_is_found(net: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"sub.evil.click\nparent.top\nb.deep.icu\n"
    monkeypatch.setattr(http, "_download", lambda url, accept, timeout: body)
    found = on_cert_list(["sub.evil.click", "other.evil.click", "www.parent.top", "a.b.deep.icu"])
    # exact subdomain, parent of the input, and an intermediate parent all match;
    # a sibling of a listed subdomain does not
    assert found == {"sub.evil.click", "www.parent.top", "a.b.deep.icu"}


def test_status_aggregates_per_registrable_domain(
    net: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"sub.evil.click\n"
    monkeypatch.setattr(http, "_download", lambda url, accept, timeout: body)
    status = cert_list_status(["sub.evil.click", "other.evil.click", "fine.org", "www.fine.org"])
    assert status.available and status.reason == "ok"
    assert (status.known, status.new) == (1, 1)  # evil.click listed via its subdomain; fine.org new
    assert status.listed == ["sub.evil.click"]
    assert pl.CERT_LIST_LINE.format(known=status.known, new=status.new).startswith("Lista")
    assert pl.CERT_LIST_UNAVAILABLE
