"""Opt-in passive enrichment (Task 3 [S1]): public metadata about domains and IPs.

Entry points: `enrich_domain` for one domain, `enrich_case` for the `url.domain` and
`infra.ip` features of one case, `on_cert_list` for the CERT Polska warning list. With
`ALLOW_ENRICH` unset every function returns an empty result without touching the network.
"""

from __future__ import annotations

import ipaddress
import logging

from fakecollector.core.schemas import Feature
from fakecollector.enrich.cert_hole import on_cert_list
from fakecollector.enrich.crtsh import certificates
from fakecollector.enrich.dns_tls import asn_for_ip, nameservers, rdap
from fakecollector.enrich.http import enabled
from fakecollector.graph.stoplist import is_hosting_ns, is_stopped_host, is_stopped_ip
from fakecollector.ingest.normalize import public_suffix, registrable_domain

logger = logging.getLogger(__name__)

__all__ = [
    "ENRICH_EXTRACTOR",
    "ENRICH_VERSION",
    "enrich_case",
    "enrich_domain",
    "enrich_ip",
    "on_cert_list",
]

ENRICH_EXTRACTOR = "enrich"  # name under which the run store keeps these features
ENRICH_VERSION = 1


def _feature(case_id: str, artifact_id: str, name: str, value: str, locator: str) -> Feature:
    return Feature(
        case_id=case_id, artifact_id=artifact_id, name=name, value=value, locator=locator
    )


MAX_CERT_NAMES = 20  # more names on one certificate = shared hosting, not one operator


def _is_public_domain(domain: str) -> bool:
    """A registrable name under a public suffix; never IPs, `localhost` or intranet names."""
    host = domain.strip().lower().rstrip(".")
    if not host or _is_ip(host):
        return False
    return bool(public_suffix(host)) and registrable_domain(host) != host.split(".")[-1]


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return False
    return True


def _is_public_ip(ip: str) -> bool:
    """Only globally routable addresses go to public services (no private, loopback, ...)."""
    try:
        return ipaddress.ip_address(ip.strip("[]")).is_global
    except ValueError:
        return False


def enrich_domain(domain: str, case_id: str = "", artifact_id: str = "") -> list[Feature]:
    """NS pair, registration month, registrar and CT issuers / co-hosted SANs of a domain.

    Works for dead pages: only the registrable domain is needed, the site is never visited.
    """
    if not enabled() or not _is_public_domain(domain):
        return []
    site = registrable_domain(domain)
    out: list[Feature] = []
    ns = nameservers(site)
    if ns and not all(is_hosting_ns(n) for n in ns):
        # The pair, not each name. Hosting / registrar / parking defaults are shared by
        # thousands of unrelated domains, so they are no operator evidence.
        out.append(_feature(case_id, artifact_id, "infra.ns", "+".join(ns), "dns:NS"))
    registered, registrar = rdap(site)
    if registered:
        out.append(_feature(case_id, artifact_id, "infra.registered", registered, "rdap"))
    if registrar:
        out.append(_feature(case_id, artifact_id, "infra.registrar", registrar, "rdap"))
    issuers: set[str] = set()
    sans: set[str] = set()
    for issuer, names in certificates(site):
        if issuer:
            issuers.add(issuer)
        if len(names) > MAX_CERT_NAMES:
            continue  # a shared hosting / CDN certificate: its co-hosted names are strangers
        sans.update(n for n in names if registrable_domain(n) != site and not is_stopped_host(n))
    out += [
        _feature(case_id, artifact_id, "infra.cert_issuer", i, "crt.sh") for i in sorted(issuers)
    ]
    out += [_feature(case_id, artifact_id, "infra.cert_san", s, "crt.sh") for s in sorted(sans)]
    return out


def enrich_ip(ip: str, case_id: str = "", artifact_id: str = "") -> list[Feature]:
    """Origin ASN of a non-CDN IP (CDN edges say nothing about the operator)."""
    if not enabled() or not _is_public_ip(ip) or is_stopped_ip(ip):
        return []
    found = asn_for_ip(ip)
    if found is None:
        return []
    asn, holder = found
    return [_feature(case_id, artifact_id, "infra.asn", asn, f"cymru: {holder}")]


def enrich_case(case_id: str, features: list[Feature]) -> list[Feature]:
    """Enrich every `url.domain` and `infra.ip` of a case, once per distinct value."""
    if not enabled():
        return []
    out: list[Feature] = []
    seen: set[tuple[str, str]] = set()
    for f in features:
        if f.case_id != case_id or (f.name, f.value) in seen:
            continue
        seen.add((f.name, f.value))
        if f.name == "url.domain":
            out += enrich_domain(f.value, case_id, f.artifact_id)
        elif f.name == "infra.ip":
            out += enrich_ip(f.value, case_id, f.artifact_id)
    return out
