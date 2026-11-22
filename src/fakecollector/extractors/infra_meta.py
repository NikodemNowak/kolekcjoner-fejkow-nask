"""Infrastructure metadata (signal 11): favicon hash, server stack, non-CDN IPs, TLS.

Everything comes from what the capture already recorded (HAR headers, `serverIPAddress`,
`_securityDetails`, `dns_ssl.json`, saved favicon files). Nothing is resolved or fetched;
live DNS / RDAP / crt.sh enrichment is the opt-in Task 3.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import mmh3

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.infra import registrable_domain
from fakecollector.graph.stoplist import is_stopped_ip
from fakecollector.ingest.har import HarError, iter_bodies, parse_har
from fakecollector.ingest.schemas import HarSummary

logger = logging.getLogger(__name__)

_STACK_HEADERS = ("server", "x-powered-by", "via")
_VERSION = re.compile(r"([a-z][\w.+-]*?)/(\d+)[\w.-]*")
_PROTO_PREFIX = re.compile(r"^\d(\.\d)?\s+")
_FAVICON_PATH = re.compile(r"(^|/)(favicon[^/]*|apple-touch-icon[^/]*|[^/]+\.ico)$", re.I)

Hit = tuple[str, str, str]


def favicon_hash(data: bytes) -> str:
    """Shodan-style favicon hash: MurmurHash3 (32-bit, signed) of the MIME base64 text."""
    return str(mmh3.hash(base64.encodebytes(data)))


def _stack(headers: dict[str, str]) -> str | None:
    """`server=nginx/1|x-powered-by=php/8`: names kept, versions cut to the major."""
    parts = []
    for name in _STACK_HEADERS:
        value = headers.get(name, "").strip().lower()
        if not value:
            continue
        value = _PROTO_PREFIX.sub("", value)  # "1.1 caddy" -> "caddy"
        value = _VERSION.sub(lambda m: f"{m.group(1)}/{m.group(2)}", value)
        parts.append(f"{name}={value}")
    return "|".join(parts) or None


def _sans(names: list[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        host = n.strip().lower().removeprefix("*.")
        if host and host not in out:
            out.append(host)
    return out


def _har_hits(artifact: Artifact) -> list[Hit]:
    har: HarSummary = parse_har(artifact.path)
    landing_host = (urlsplit(har.landing_url or "").hostname or "").lower()
    first_party = registrable_domain(landing_host) if landing_host else ""
    hits: list[Hit] = []
    favicon_entries: set[int] = set()
    for i, e in enumerate(har.entries):
        loc = f"entry[{i}]"
        is_first = bool(first_party) and registrable_domain(e.host) == first_party
        if e.url == har.landing_url and (stack := _stack(e.headers)):
            hits.append(("infra.server_stack", stack, f"{loc}.response.headers"))
        if is_first and e.ip and not is_stopped_ip(e.ip):
            hits.append(("infra.ip", e.ip.strip("[]"), f"{loc}.serverIPAddress"))
        if is_first and e.tls_issuer:
            hits.append(
                ("infra.cert_issuer", e.tls_issuer.strip().lower(), f"{loc}._securityDetails")
            )
            hits.extend(("infra.cert_san", s, f"{loc}._securityDetails") for s in _sans(e.tls_san))
        if "icon" in e.mime or _FAVICON_PATH.search(urlsplit(e.url).path):
            favicon_entries.add(i)
    for i, _, body in iter_bodies(artifact.path):
        if i in favicon_entries and body:
            hits.append(("infra.favicon_mmh3", favicon_hash(body), f"entry[{i}].response.content"))
    return hits


def _rdn(value: Any, key: str) -> str | None:
    """Pick one attribute from Python's `ssl.getpeercert()` RDN nesting."""
    if not isinstance(value, list):
        return None
    for rdn in value:
        for pair in rdn if isinstance(rdn, list) else []:
            if isinstance(pair, list) and len(pair) == 2 and pair[0] == key:
                return str(pair[1])
    return None


def _dns_tls_hits(artifact: Artifact) -> list[Hit]:
    data = json.loads(artifact.path.read_bytes().decode("utf-8-sig", errors="replace"))
    if not isinstance(data, dict):
        return []
    hits: list[Hit] = []
    addresses = [data.get("ip"), *(data.get("all_addresses") or [])]
    for ip in addresses:
        if isinstance(ip, str) and ip and not is_stopped_ip(ip):
            hits.append(("infra.ip", ip, "all_addresses"))
    raw_ssl = data.get("ssl")
    ssl: dict[str, Any] = raw_ssl if isinstance(raw_ssl, dict) else {}
    # CN only, the same field HAR `_securityDetails.issuer` carries, so both sources agree.
    issuer = _rdn(ssl.get("issuer"), "commonName") or _rdn(ssl.get("issuer"), "organizationName")
    if issuer:
        hits.append(("infra.cert_issuer", issuer.lower(), "ssl.issuer"))
    san = [p[1] for p in ssl.get("subjectAltName") or [] if isinstance(p, list) and len(p) == 2]
    hits.extend(("infra.cert_san", s, "ssl.subjectAltName") for s in _sans([str(x) for x in san]))
    return hits


class InfraMetaExtractor(BaseExtractor):
    """Signal 11: `infra.favicon_mmh3`, `infra.server_stack`, `infra.ip`, `infra.cert_*`."""

    name = "infra_meta"
    version = 1

    def supports(self, artifact: Artifact) -> bool:
        """HARs, `dns_ssl.json` and saved favicon files."""
        if artifact.kind == "har" or artifact.role == "dns_tls":
            return True
        return artifact.kind == "asset" and bool(_FAVICON_PATH.search(artifact.path.name))

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """One feature per distinct (name, value)."""
        try:
            if artifact.kind == "har":
                hits = _har_hits(artifact)
            elif artifact.role == "dns_tls":
                hits = _dns_tls_hits(artifact)
            else:
                hits = [("infra.favicon_mmh3", favicon_hash(artifact.path.read_bytes()), "file")]
        except (HarError, OSError, ValueError) as exc:
            logger.warning("%s: infrastructure metadata skipped (%s)", artifact.case_id, exc)
            return []
        seen: set[tuple[str, str]] = set()
        out: list[Feature] = []
        for name, value, locator in hits:
            if (name, value) not in seen:
                seen.add((name, value))
                out.append(
                    Feature(
                        case_id=artifact.case_id,
                        artifact_id=artifact.id,
                        name=name,
                        value=value,
                        locator=locator,
                    )
                )
        return out
