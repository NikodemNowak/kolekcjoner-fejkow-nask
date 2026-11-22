"""URL canonicalisation and URL schemas (pure functions, no network)."""

from __future__ import annotations

import os
import re
from functools import cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

# Tracking / click parameters: removed from the canonical URL. Extractors read them as
# features from the raw URL first, so nothing is lost.
_TRACKING_EXACT = frozenset(
    {
        "gclid",
        "gbraid",
        "wbraid",
        "dclid",
        "fbclid",
        "msclkid",
        "ttclid",
        "twclid",
        "yclid",
        "igshid",
        "_ga",
        "_gl",
        "mc_cid",
        "mc_eid",
    }
)
_DEFAULT_PORTS = {"http": 80, "https": 443}

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HEX = re.compile(r"^[0-9a-f]{12,}$", re.I)
_DIGITS = re.compile(r"^\d+$")


# Credentials that capture tools leave in URLs (e.g. a Facebook `access_token`): their
# values are replaced before a URL is stored or shown; campaign and click IDs stay.
_SECRET_PARAMS = frozenset(
    {
        "access_token",
        "id_token",
        "refresh_token",
        "token",
        "auth",
        "authorization",
        "api_key",
        "apikey",
        "password",
        "passwd",
        "pwd",
        "secret",
        "client_secret",
        "session",
        "sessionid",
        "session_id",
        "sid",
        "signature",
        "sig",
    }
)


def redact_url(url: str) -> str:
    """Replace the values of credential-like query parameters with `REDACTED`."""
    try:
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return url
    if not any(k.lower() in _SECRET_PARAMS for k, _ in query):
        return url
    safe = [(k, "REDACTED" if k.lower() in _SECRET_PARAMS else v) for k, v in query]
    return urlunsplit(parts._replace(query=urlencode(safe)))


def _is_tracking(name: str) -> bool:
    low = name.lower()
    return low.startswith("utm_") or low in _TRACKING_EXACT


def canonical_url(url: str) -> str:
    """Lower-case scheme and host, drop fragment, default port and tracking parameters.

    Strings that are not absolute http(s) URLs are returned unchanged.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return url
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname:
        return url
    host = parts.hostname.lower()
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    )
    return urlunsplit((scheme, host, parts.path or "/", urlencode(query), ""))


_TOKEN = re.compile(r"^[A-Za-z0-9ąćęłńóśźżĄĆĘŁŃÓŚŹŻ_-]{6,48}$")
_VOWELS = set("aeiouyąęó")
_CONSONANT_RUN = re.compile(r"[bcdfghjklmnpqrstvwxzćłńśźż]{5,}")


def looks_random(value: str) -> bool:
    """A generated token (`kt5vpccv`, `tzqfbfsc`) rather than a word or a plain number.

    Letters mixed with digits, or letters with almost no vowels (< 15 %, `y` counts, as in
    Polish). Digit-only values (ad and campaign IDs) and short strings are not random.
    """
    if not _TOKEN.match(value) or value.replace("-", "").replace("_", "").isdigit():
        return False
    low = value.lower()
    letters = [c for c in low if c.isalpha()]
    if not letters:
        return False
    if any(c.isdigit() for c in value):
        return True
    # Polish words have at most four consonants in a row ("strz", "szcz").
    words = re.split(r"[-_]", low)
    return any(
        len(w) >= 6
        and (bool(_CONSONANT_RUN.search(w)) or sum(c in _VOWELS for c in w) / len(w) < 0.15)
        for w in words
    )


def _mask_segment(seg: str) -> str:
    if _UUID.match(seg):
        return "{uuid}"
    if _DIGITS.match(seg):
        return "{n}"
    if _HEX.match(seg):
        return "{hex}"
    if looks_random(seg):
        return "{slug}"  # per-landing random slug: the schema must not encode it
    return seg.lower()


def _mask_param(name: str) -> str:
    """`utm_kqzrtvbnmxl` -> `utm_{slug}`: generated parameter names say nothing."""
    head, sep, tail = name.partition("_")
    if sep and looks_random(tail):
        return f"{head}_{{slug}}"
    return "{slug}" if looks_random(name) else name


def url_schema(url: str) -> str:
    """Host-free URL shape: masked path segments plus sorted parameter names.

    Two URLs that differ only in IDs or parameter values get the same schema, which is
    what identifies a tracker or kit family across domains.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    path = "/".join(_mask_segment(s) for s in (parts.path or "/").split("/"))
    names = sorted(
        {_mask_param(k) for k, _ in parse_qsl(parts.query.lstrip("?"), keep_blank_values=True)}
    )
    return f"{path}?{'&'.join(names)}" if names else path


# Bundled public-suffix snapshot (no download at runtime); private suffixes on, so
# `a.github.io` and `b.github.io` are different sites.
_TLD = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True, cache_dir=None)


@cache
def registrable_domain(host: str) -> str:
    """Registrable domain (eTLD+1, private suffixes included); IPs are returned as is."""
    host = host.lower().strip(".")
    parts = _TLD(host)
    if parts.ipv4 or parts.ipv6:
        return host
    return parts.top_domain_under_public_suffix or host


def display_text(text: str) -> str:
    """UTF-8-safe copy of a file-system string: undecodable bytes become backslash escapes.

    `Path` keeps undecodable file-name bytes as surrogates, which every UTF-8 writer (CSV,
    Parquet, JSON) rejects. Ids, metadata and locators use this; `Artifact.path` keeps
    the real name so the file can still be opened.
    """
    return os.fsencode(text).decode("utf-8", "backslashreplace")


def public_suffix(host: str) -> str:
    """The public suffix of `host` (`live`, `co.uk`), or "" when it has none (offline PSL)."""
    return _TLD(host.lower().strip(".")).suffix


_BARE_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)+(?:[/?#]\S*)?$", re.I)


def as_url(text: str) -> str | None:
    """`text` as an http(s) URL, or None when it is not one.

    Accepts full http(s) URLs and bare `host.tld[/path]` whose suffix is a public suffix
    (offline list), so `evil-site.live` is a URL while `main.js` or a product name are not.
    """
    value = text.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme:
        return value if parts.scheme.lower() in ("http", "https") and parts.hostname else None
    if not _BARE_HOST.match(value):
        return None
    host = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if not _TLD(host).suffix:
        return None
    url = f"https://{value}"
    return url if "/" in value else canonical_url(url)
