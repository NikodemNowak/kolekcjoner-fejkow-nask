"""Stop-list of platform hosts and CDN IP ranges (`stoplist.toml`)."""

from __future__ import annotations

import ipaddress
import re
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_FILE = Path(__file__).with_name("stoplist.toml")

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class Stoplist:
    """Hosts (matched as domain suffixes) and CDN networks."""

    hosts: frozenset[str]
    networks: tuple[IpNetwork, ...]
    library: re.Pattern[str]
    hosting_ns: tuple[str, ...] = ()


@cache
def load_stoplist() -> Stoplist:
    """Read the bundled stop-list once."""
    data = tomllib.loads(_FILE.read_text(encoding="utf-8"))
    return Stoplist(
        hosts=frozenset(h.lower() for h in data.get("hosts", [])),
        networks=tuple(ipaddress.ip_network(n) for n in data.get("cdn_ip_ranges", [])),
        hosting_ns=tuple(n.lower() for n in data.get("hosting_ns", [])),
        library=re.compile("|".join(data.get("library_patterns", [])) or "(?!)", re.I),
    )


def is_stopped_host(host: str) -> bool:
    """True if `host` is a listed platform or one of its subdomains."""
    labels = host.lower().rstrip(".").split(".")
    hosts = load_stoplist().hosts
    return any(".".join(labels[i:]) in hosts for i in range(len(labels) - 1))


def is_stopped_ip(ip: str) -> bool:
    """True if `ip` sits in a CDN edge range (shared by unrelated sites)."""
    try:
        addr = ipaddress.ip_address(ip.strip("[]"))
    except ValueError:
        return False
    return any(addr in net for net in load_stoplist().networks)


def is_hosting_ns(host: str) -> bool:
    """True for a hosting / registrar / parking default name server (a hub)."""
    host = host.lower().rstrip(".")
    return any(
        (marker in host)
        if marker.endswith(("-", "."))
        else (host == marker or host.endswith("." + marker))
        for marker in load_stoplist().hosting_ns
    )


def is_library_asset(name: str, head: str = "") -> bool:
    """True for a saved third-party library build (jQuery, Swiper, ...), by name or banner."""
    lib = load_stoplist().library
    return bool(lib.search(name) or lib.search(head[:512]))
