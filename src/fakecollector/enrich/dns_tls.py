"""DNS (over HTTPS), ASN (Team Cymru) and RDAP lookups for one registrable domain or IP.

Sources, all public and key-less:
- Cloudflare DNS over HTTPS JSON API (`cloudflare-dns.com/dns-query`): NS records.
- Team Cymru IP-to-ASN mapping via DNS TXT (`origin.asn.cymru.com`, `asn.cymru.com`).
- RDAP bootstrap redirector `rdap.org` -> the registry's RDAP server: registration date
  and registrar.
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import quote

from fakecollector.enrich.http import fetch_json

_DOH = "https://cloudflare-dns.com/dns-query?name={name}&type={rtype}"
_RDAP = "https://rdap.org/domain/{domain}"


def resolve(name: str, rtype: str) -> list[str]:
    """Answer data for one DNS query, trailing dots and quotes removed."""
    data = fetch_json(_DOH.format(name=quote(name), rtype=rtype), accept="application/dns-json")
    if not isinstance(data, dict) or data.get("Status") != 0:
        return []
    out = []
    for answer in data.get("Answer") or []:
        if isinstance(answer, dict) and isinstance(answer.get("data"), str):
            out.append(answer["data"].strip().strip('"').rstrip(".").lower())
    return out


def nameservers(domain: str) -> list[str]:
    """Sorted NS host names of a registrable domain."""
    return sorted(set(resolve(domain, "NS")))


def asn_for_ip(ip: str) -> tuple[str, str] | None:
    """`("AS14061", "digitalocean-asn, us")` for an IPv4 address, or None."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.version != 4:
        return None  # Cymru's IPv6 zone needs nibble format; not worth it for this corpus
    reversed_ip = ".".join(reversed(ip.split(".")))
    origin = resolve(f"{reversed_ip}.origin.asn.cymru.com", "TXT")
    if not origin:
        return None
    parts = origin[0].split("|")[0].strip().split()
    if not parts or not parts[0].isdigit():
        return None
    asn = parts[0]
    detail = resolve(f"AS{asn}.asn.cymru.com", "TXT")
    holder = detail[0].split("|")[-1].strip() if detail else ""
    return f"AS{asn}", holder


def _vcard_fn(entity: dict[str, Any]) -> str | None:
    card = entity.get("vcardArray")
    if not isinstance(card, list) or len(card) < 2 or not isinstance(card[1], list):
        return None
    for item in card[1]:
        if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
            return str(item[3])
    return None


def rdap(domain: str) -> tuple[str | None, str | None]:
    """(registration month `YYYY-MM`, registrar name) from RDAP; Nones when unknown."""
    data = fetch_json(_RDAP.format(domain=quote(domain)), accept="application/rdap+json")
    if not isinstance(data, dict):
        return None, None
    registered = None
    for event in data.get("events") or []:
        if isinstance(event, dict) and event.get("eventAction") == "registration":
            registered = str(event.get("eventDate", ""))[:7] or None
    registrar = None
    for entity in data.get("entities") or []:
        if isinstance(entity, dict) and "registrar" in (entity.get("roles") or []):
            registrar = _vcard_fn(entity)
    return registered, (registrar.lower() if registrar else None)
