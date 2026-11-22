"""Rule-based impersonated-brand detection (`brand.impersonated`, signal 7, A's rules).

Complements the SigLIP logo matcher in `brand.py` (B) with cheap text evidence that the
page dresses up as a known portal: the brand as the *suffix* of the title ("... — Gazeta.pl"),
the `og:site_name` / `application-name` meta, and image files or alt texts that say "logo"
next to a brand name. Mentions in the story itself ("founder of InPost") are not matched.
A logo image alone may be an "as seen on" trust badge, so it gives context-only
`brand.logo`; the title suffix and site-name meta give `brand.impersonated`.
Slugs are the ones in `brand.BRAND_NAMES`, so both extractors produce the same entities.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors._text import read_text
from fakecollector.extractors.html_page import parse_html
from fakecollector.extractors.infra import registrable_domain

logger = logging.getLogger(__name__)

# slug -> (name pattern, the brand's own registrable domains)
_BRANDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "gazeta_pl": (r"gazeta\.pl|gazeta wyborcza", ("gazeta.pl", "wyborcza.pl")),
    "tvn24": (r"tvn\s?24", ("tvn24.pl", "tvn.pl")),
    "onet": (r"onet(\.pl)?", ("onet.pl",)),
    "wp": (r"wp\.pl|wirtualna polska", ("wp.pl",)),
    "inpost": (r"inpost", ("inpost.pl",)),
    "pko_bp": (r"pko[\s_-]?bp|pko bank polski", ("pkobp.pl", "pko.pl")),
    "pekao": (r"(bank )?pekao", ("pekao.com.pl",)),
    "nbp": (r"nbp|narodowy bank polski", ("nbp.pl",)),
    "app_store": (r"app[\s_-]?store", ("apple.com",)),
    "google_play": (r"google[\s_-]?play", ("google.com",)),
    "allegro": (r"allegro", ("allegro.pl",)),
    # Added with the 34-brand reference set (#30); `facebook` is left out on purpose:
    # Like buttons and FB widgets are ordinary page chrome, not impersonation.
    "mbank": (r"mbank", ("mbank.pl",)),
    "ing": (r"ing(\s?bank(\s?śląski)?)?", ("ing.pl", "ing.com")),
    "santander": (r"santander(\s?bank)?", ("santander.pl",)),
    "millennium": (r"(bank\s?)?millennium", ("bankmillennium.pl",)),
    "alior": (r"alior(\s?bank)?", ("aliorbank.pl",)),
    "bnp_paribas": (r"bnp\s?paribas", ("bnpparibas.pl",)),
    "interia": (r"interia(\.pl)?", ("interia.pl",)),
    "polsat": (r"polsat(\s?news)?", ("polsat.pl", "polsatnews.pl")),
    "tvp": (r"tvp(\s?info|\.info)?|telewizja polska", ("tvp.pl", "tvp.info")),
    "rzeczpospolita": (r"rzeczpospolita|rp\.pl", ("rp.pl",)),
    "business_insider": (r"business\s?insider(\s?polska)?", ("businessinsider.com.pl",)),
    "forbes": (r"forbes(\.pl)?", ("forbes.pl", "forbes.com")),
    "zus": (r"zus", ("zus.pl",)),
    "orlen": (r"orlen", ("orlen.pl",)),
    "pge": (r"pge", ("pge.pl", "gkpge.pl")),
    "olx": (r"olx", ("olx.pl",)),
    "revolut": (r"revolut", ("revolut.com",)),
    "binance": (r"binance", ("binance.com",)),
    "fox_news": (r"fox\s?news", ("foxnews.com",)),
    "nbc": (r"nbc(\s?news)?", ("nbc.com", "nbcnews.com")),
    "cnn": (r"cnn", ("cnn.com",)),
    "bbc": (r"bbc(\s?news)?", ("bbc.com", "bbc.co.uk")),
}

_SEPARATOR = r"[\s]*[—–\-|:·•][\s]*"
_TITLE_SUFFIX = {s: re.compile(rf"{_SEPARATOR}({p})\s*$", re.I) for s, (p, _) in _BRANDS.items()}
_WHOLE = {s: re.compile(rf"^\s*({p})\s*$", re.I) for s, (p, _) in _BRANDS.items()}
_TOKEN = {s: re.compile(rf"(^|[^a-z0-9])({p})([^a-z0-9]|$)", re.I) for s, (p, _) in _BRANDS.items()}
_SITE_META = ("og:site_name", "application-name", "apple-mobile-web-app-title")


class BrandRulesExtractor(BaseExtractor):
    """`brand.impersonated` from title suffix, site-name meta and logo images."""

    name = "brand_rules"
    version = 3  # v2: brand.logo split (B3c); v3: rules for the 34-brand reference set

    def supports(self, artifact: Artifact) -> bool:
        """Landing pages."""
        return artifact.kind == "html" and artifact.role == "landing_page"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """One feature per brand, with the first rule that fired as its locator."""
        try:
            soup = parse_html(read_text(artifact.path))
        except Exception as exc:  # hostile HTML must not stop a run
            logger.warning("%s: brand rules skipped (%s)", artifact.case_id, exc)
            return []
        url = artifact.meta.get("url") or artifact.meta.get("saved_from") or ""
        host = (urlsplit(url).hostname or "").lower()
        own = registrable_domain(host) if host else ""

        hits: list[tuple[str, str]] = []
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        hits += [(s, "title") for s, rx in _TITLE_SUFFIX.items() if rx.search(title)]
        for meta in soup.find_all("meta"):
            key = str(meta.get("property") or meta.get("name") or "").lower()
            if key in _SITE_META:
                content = str(meta.get("content") or "")
                hits += [(s, f"meta[{key}]") for s, rx in _WHOLE.items() if rx.search(content)]
        for img in soup.find_all("img"):
            src = str(img.get("src") or "").rsplit("/", 1)[-1]
            alt = str(img.get("alt") or "")
            for text, where in ((src, "img[src]"), (alt, "img[alt]")):
                if "logo" in text.lower():
                    hits += [(s, where) for s, rx in _TOKEN.items() if rx.search(text)]

        out: list[Feature] = []
        for slug, locator in hits:
            if own in _BRANDS[slug][1] or any(f.value == slug for f in out):
                continue
            out.append(
                Feature(
                    case_id=artifact.case_id,
                    artifact_id=artifact.id,
                    name="brand.logo" if locator.startswith("img[") else "brand.impersonated",
                    value=slug,
                    confidence=0.9,
                    locator=locator,
                )
            )
        return out


# Wordmarks as OCR reads them off a page header: lowercase letters and digits only. A short
# mark (<= 4 characters) must match a whole token exactly; a longer one may be garbled by
# one OCR error, two from 8 characters ("bazeta pl" -> gazetapl). Generic words that are
# also brand names ("gazeta", "ing") are left out on purpose. Up to 7 characters only a
# misread letter is allowed (same length), so a common word one letter shorter never hits.
_WORDMARKS: dict[str, tuple[str, ...]] = {
    "gazeta_pl": ("gazetapl", "gazetawyborcza"),
    "tvn24": ("tvn24",),
    "onet": ("onetpl", "onet"),
    "wp": ("wppl", "wirtualnapolska"),
    "inpost": ("inpost",),
    "pko_bp": ("pkobp", "pkobankpolski"),
    "pekao": ("pekao",),
    "nbp": ("nbp", "narodowybankpolski"),
    "app_store": ("appstore",),
    "google_play": ("googleplay",),
    "allegro": ("allegro",),
    "mbank": ("mbank",),
    "santander": ("santander",),
    "millennium": ("millennium",),
    "alior": ("aliorbank",),
    "bnp_paribas": ("bnpparibas",),
    "interia": ("interiapl", "interia"),
    "polsat": ("polsatnews", "polsat"),
    "tvp": ("tvpinfo", "tvp"),
    "rzeczpospolita": ("rzeczpospolita",),
    "business_insider": ("businessinsider",),
    "forbes": ("forbes",),
    "zus": ("zus",),
    "orlen": ("orlen",),
    "revolut": ("revolut",),
    "binance": ("binance",),
    "fox_news": ("foxnews",),
    "cnn": ("cnn",),
    "bbc": ("bbcnews", "bbc"),
}
_MAX_NGRAM = 3


def _compact(token: str) -> str:
    import unicodedata

    folded = unicodedata.normalize("NFKD", token.lower().replace("ł", "l"))
    return "".join(ch for ch in folded if ch.isascii() and ch.isalnum())


def _mark_matches(candidate: str, mark: str) -> bool:
    from rapidfuzz.distance import Levenshtein

    if len(mark) <= 4:
        return candidate == mark
    if len(mark) <= 7:  # one misread letter, no dropped one ("bank" is not "mbank")
        if len(candidate) != len(mark):
            return False
        return sum(a != b for a, b in zip(candidate, mark, strict=True)) <= 1
    return abs(len(candidate) - len(mark)) <= 1 and (
        Levenshtein.distance(candidate, mark, score_cutoff=2) <= 2
    )


def brands_in_text(text: str) -> list[str]:
    """Brand slugs whose wordmark appears in one OCR line, tolerating OCR letter errors."""
    tokens = [t for t in (_compact(raw) for raw in text.split()) if t]
    grams = {tokens[0]} if len(tokens) == 1 else set()
    for size in range(1, _MAX_NGRAM + 1):
        grams.update("".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1))
    singles = set(tokens)
    found = []
    for slug, marks in _WORDMARKS.items():
        for mark in marks:
            pool = singles if len(mark) <= 4 else grams
            if any(_mark_matches(gram, mark) for gram in pool):
                found.append(slug)
                break
    return found


def brand_domains() -> frozenset[str]:
    """Registrable domains of every known brand: the portals scams imitate, not scam hosts."""
    return frozenset(domain for _, domains in _BRANDS.values() for domain in domains)


def own_brand(slug: str, domains: list[str]) -> bool:
    """True when a domain shown in the image is one of the brand's own domains."""
    return any(domain in _BRANDS[slug][1] for domain in domains)
