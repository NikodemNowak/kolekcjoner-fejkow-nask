"""Certificate Transparency via crt.sh (public, key-less, slow; rate-limit politely)."""

from __future__ import annotations

from urllib.parse import quote

from fakecollector.enrich.http import fetch_json

_CRTSH = "https://crt.sh/?q={domain}&output=json&exclude=expired"
MAX_CERTS = 200  # popular names have thousands of entries; the first ones are enough


def _issuer_cn(issuer: str) -> str | None:
    for part in issuer.split(","):
        key, _, value = part.strip().partition("=")
        if key == "CN" and value:
            return value.strip().lower()
    return None


def certificates(domain: str) -> list[tuple[str | None, list[str]]]:
    """(issuer CN, SAN names) for each logged certificate of the domain."""
    data = fetch_json(_CRTSH.format(domain=quote(domain)))
    if not isinstance(data, list):
        return []
    out = []
    for row in data[:MAX_CERTS]:
        if not isinstance(row, dict):
            continue
        names = str(row.get("name_value", "")).split("\n")
        sans = sorted({n.strip().lower().removeprefix("*.") for n in names if n.strip()})
        out.append((_issuer_cn(str(row.get("issuer_name", ""))), sans))
    return out
