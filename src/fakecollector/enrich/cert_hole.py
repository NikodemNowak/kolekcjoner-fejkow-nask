"""CERT Polska warning list (hole.cert.pl): which domains are already known as dangerous.

The list is downloaded once into the enrichment cache (about 2.6 MB of plain text, one
domain per line) and read from disk afterwards. "List unavailable" (enrichment off or the
download failed) is kept apart from "nothing listed", so a report never calls every domain
new just because the list could not be read.
"""

from __future__ import annotations

from collections.abc import Iterable

from fakecollector.enrich.http import enabled, fetch
from fakecollector.enrich.schemas import CertListStatus
from fakecollector.extractors.infra import registrable_domain

CERT_LIST_URL = "https://hole.cert.pl/domains/v2/domains.txt"

_loaded: dict[str, frozenset[str]] = {}  # only successful loads are kept in memory


def load_cert_list() -> frozenset[str] | None:
    """Domains on the CERT Polska list, or None when the list is unavailable."""
    if CERT_LIST_URL in _loaded:
        return _loaded[CERT_LIST_URL]
    body = fetch(CERT_LIST_URL, accept="text/plain")
    if body is None:
        return None
    lines = body.decode("utf-8", "replace").splitlines()
    listed = frozenset(d.strip().lower() for d in lines if d.strip() and not d.startswith("#"))
    _loaded[CERT_LIST_URL] = listed
    return listed


def _candidates(domain: str) -> list[str]:
    """The domain itself and every parent down to its registrable domain."""
    host = domain.strip().lower().rstrip(".")
    site = registrable_domain(host)
    labels = host.split(".")
    out = []
    for i in range(len(labels)):
        name = ".".join(labels[i:])
        out.append(name)
        if name == site:
            break
    return out


def _matches(domains: Iterable[str], listed: frozenset[str]) -> set[str]:
    return {d for d in domains if d and any(c in listed for c in _candidates(d))}


def on_cert_list(domains: Iterable[str]) -> set[str]:
    """Input domains that are listed themselves or sit under a listed parent domain.

    Empty when the list is unavailable; use `cert_list_status` to tell the two apart.
    """
    listed = load_cert_list()
    return _matches(domains, listed) if listed is not None else set()


def cert_list_status(domains: Iterable[str]) -> CertListStatus:
    """Per-campaign summary, counted per registrable domain, matched per input domain."""
    if not enabled():
        return CertListStatus(available=False, reason="disabled")
    listed = load_cert_list()
    if listed is None:
        return CertListStatus(available=False, reason="fetch_failed")
    inputs = sorted({d.strip().lower() for d in domains if d and d.strip()})
    matched = _matches(inputs, listed)
    sites = {registrable_domain(d) for d in inputs}
    known_sites = {registrable_domain(d) for d in matched}
    return CertListStatus(
        available=True,
        reason="ok",
        known=len(known_sites),
        new=len(sites - known_sites),
        listed=sorted(matched),
    )
