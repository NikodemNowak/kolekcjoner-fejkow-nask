"""Parse feeds and article HTML; tag persons, brands and the scam narrative of an article."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from fakecollector.collect.models import ArticleImage, FeedEntry

_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
_ATOM = "{http://www.w3.org/2005/Atom}"

# An article is about a scam ad when its title or body says so; fact-checkers also cover
# political disinformation, which the collector must skip.
_SCAM = re.compile(
    r"scam|oszus|oszuk|wyłudz|phishing|deepfake|fałszyw\w* reklam|platform\w* inwestyc"
    r"|inwestycyjn|podszywa|fałszyw\w* (stron|sklep|artyku|platform|aplikac)",
    re.IGNORECASE,
)
_BODY_AD = re.compile(r"reklam", re.IGNORECASE)
_BODY_FRAUD = re.compile(r"scam|oszus|oszuk|wyłudz|deepfake|phishing", re.IGNORECASE)

# Public figures and brands that scam ads impersonate (Polish market). Surname stems match
# inflected forms ("Brzoski", "Brzoską").
PERSONS: dict[str, str] = {
    "brzosk": "Rafał Brzoska",
    "morawieck": "Mateusz Morawiecki",
    "cejrowsk": "Wojciech Cejrowski",
    "kammel": "Tomasz Kammel",
    "gąsowsk": "Piotr Gąsowski",
    "stoparczyk": "Katarzyna Stoparczyk",
    "wojewódzk": "Kuba Wojewódzki",
    "olejnik": "Monika Olejnik",
    "glapińsk": "Adam Glapiński",
    "belk": "Marek Belka",
    "tusk": "Donald Tusk",
    "nawrock": "Karol Nawrocki",
    "andrzej dud": "Andrzej Duda",
    "prezydent dud": "Andrzej Duda",
    "trzaskowsk": "Rafał Trzaskowski",
    "lewandowsk": "Robert Lewandowski",
    "stanowsk": "Krzysztof Stanowski",
    "sekielsk": "Tomasz Sekielski",
    "hołowni": "Szymon Hołownia",
    "kwaśniewsk": "Aleksander Kwaśniewski",
    "kaczyńsk": "Jarosław Kaczyński",
    "obajt": "Daniel Obajtek",
    "mentzen": "Sławomir Mentzen",
    "majdan": "Radosław Majdan",
    "rozenek": "Małgorzata Rozenek",
    "kraśk": "Piotr Kraśko",
    "kursk": "Jacek Kurski",
    "pazur": "Cezary Pazura",
    "kubic": "Robert Kubica",
    "małysz": "Adam Małysz",
    "gessler": "Magda Gessler",
    "szumowsk": "Łukasz Szumowski",
    "świątek": "Iga Świątek",
    "jakimowicz": "Jarosław Jakimowicz",
    "domański": "Andrzej Domański",
    "ibisz": "Krzysztof Ibisz",
    "kosiniak": "Władysław Kosiniak-Kamysz",
    "sikorsk": "Radosław Sikorski",
    "wellman": "Dorota Wellman",
    "szczęsn": "Wojciech Szczęsny",
    "musk": "Elon Musk",
    "solorz": "Zygmunt Solorz",
    "kulczyk": "Jan Kulczyk",
    "lis ": "Tomasz Lis",
    "rusin": "Kinga Rusin",
    "pietrzak": "Jan Pietrzak",
    "zalewsk": "Paweł Zalewski",
    "błaszczak": "Mariusz Błaszczak",
    "owsiak": "Jerzy Owsiak",
    "jaworowicz": "Elżbieta Jaworowicz",
    "kurdej": "Agnieszka Kurdej",
    "mazurek": "Robert Mazurek",
    "rymanowsk": "Bogdan Rymanowski",
    "kraśko": "Piotr Kraśko",
    "chajzer": "Filip Chajzer",
    "wieniawa": "Julia Wieniawa",
    "zieliński": "Piotr Zieliński",
    "kowalsk": "Kowalski",
}
BRANDS: dict[str, str] = {
    "orlen": "Orlen",
    "pko": "PKO BP",
    "mbank": "mBank",
    "inpost": "InPost",
    "allegro": "Allegro",
    "pekao": "Pekao",
    " ing ": "ING",
    "santander": "Santander",
    "revolut": "Revolut",
    "blik": "BLIK",
    "pge": "PGE",
    "pzu": "PZU",
    "zus": "ZUS",
    "lotos": "Lotos",
    "pgnig": "PGNiG",
    "biedronk": "Biedronka",
    "lidl": "Lidl",
    "żabk": "Żabka",
    "netflix": "Netflix",
    "olx": "OLX",
    "vinted": "Vinted",
    "poczta polska": "Poczta Polska",
    "dpd": "DPD",
    "knf": "KNF",
    "nbp": "NBP",
    "bitcoin": "Bitcoin",
    "kryptowalut": "kryptowaluty",
    "meta ": "Meta",
    "tvn": "TVN",
    "polsat": "Polsat",
    "onet": "Onet",
    "gazeta.pl": "Gazeta.pl",
    "money.pl": "Money.pl",
    "wp.pl": "WP",
    "interia": "Interia",
    "tvp": "TVP",
    "rmf": "RMF",
    "business insider": "Business Insider",
    "baltic pipe": "Baltic Pipe",
    "rząd": "rząd",
    "ministerstw": "ministerstwo",
    "mobywatel": "mObywatel",
    "e-urząd skarbow": "e-Urząd Skarbowy",
}
# Narrative (the "hook" of the funnel), first match wins.
NARRATIVES: tuple[tuple[str, str], ...] = (
    (r"zamach|postrzel|strzela|strzał", "zamach"),
    (r"nie żyje|zmarł|śmier|pogrzeb|tragedi|wypad", "śmierć/tragedia"),
    (r"areszt|zatrzyma|afer|skandal|wpadk|na wizji|wywiad", "skandal w wywiadzie"),
    (r"kryptowalut|bitcoin", "kryptowaluty"),
    (r"inwest|platform|giełd|akcj|pasywn|dochód", "inwestycja"),
    (r"kasyn|hazard|lotto|zakład|aplikacj\w* do gry|wygran\w* w aplikac", "hazard/aplikacja"),
    (
        r"pasożyt|lek |leku|leki|cukrzyc|staw|odchudz|lecz|zdrow|suplement|wzrok|słuch|prostat"
        r"|cholester|ciśnien|serc|nowotw|rak ",
        "zdrowie/lek",
    ),
    (
        r"rozdaj|darmow|za darmo|gratis|loteri|konkurs|nagrod|prezent|kupon|voucher|bon |bony"
        r"|wygraj|wygrał|losowan|pudł|podarunk|urodzin|rocznic",
        "nagroda/loteria",
    ),
    (r"prac\w* zdaln|praca|pracy|zarobk|zarabia|zatrudni|rekrut", "oferta pracy"),
    (r"paczk|przesyłk|kurier", "paczka/dopłata"),
    (r"bilet", "fałszywe bilety"),
    (r"olx|vinted|sprzedaj|kupując|ogłoszen", "fałszywy kupujący/sprzedający"),
    (
        r"dopłat|zwrot|podatk|rekompensat|dofinans|świadczen|emerytur|odszkodow|dotacj|800",
        "zwrot/świadczenie",
    ),
    (r"bank|konto|blik|logowa|phishing|sms|karta", "phishing bank"),
    (r"sklep|wyprzedaż|promocj|likwidacj|rabat|zniżk", "fałszywy sklep"),
    (r"deepfake|wygenerowan|sztuczn\w* inteligencj|\bai\b", "deepfake"),
)


def _norm(text: str) -> str:
    return " " + unicodedata.normalize("NFC", text).lower() + " "


def _stem(stem: str, text: str) -> re.Match[str] | None:
    """Match a stem only at a word start, so "belk" does not hit "zbelkowany"."""
    return re.search(r"(?<!\w)" + re.escape(stem), text)


def is_scam_article(title: str, text: str = "") -> bool:
    """Return True when the article is about scam ads or fraud pages."""
    head = text[:6000]
    return bool(_SCAM.search(title) or (_BODY_AD.search(head) and _BODY_FRAUD.search(head)))


def find_persons(text: str) -> list[str]:
    """Public figures named in `text` (by surname stem), in first-mention order."""
    low = _norm(text)
    hits = [(m.start(), name) for stem, name in PERSONS.items() if (m := _stem(stem, low))]
    seen: list[str] = []
    for _, name in sorted(hits):
        if name not in seen:
            seen.append(name)
    return seen


def find_brands(text: str) -> list[str]:
    """Brands and institutions named in `text`, in first-mention order."""
    low = _norm(text)
    hits = [(m.start(), name) for stem, name in BRANDS.items() if (m := _stem(stem, low))]
    seen: list[str] = []
    for _, name in sorted(hits):
        if name not in seen:
            seen.append(name)
    return seen


def narrative(text: str) -> str:
    """Return the scam narrative label of `text` ("inwestycja", "zamach", ...)."""
    low = _norm(text)
    for pattern, label in NARRATIVES:
        if re.search(pattern, low):
            return label
    return "inne"


def story_label(title: str, persons: list[str], brands: list[str], context: str = "") -> str:
    """Group key for one article: narrative of the title plus its lead person or brand.

    `context` (alt text, caption, body) is the fallback when the title names no narrative.
    """
    lead = persons[0] if persons else (brands[0] if brands else "bez postaci")
    hook = narrative(title)
    if hook == "inne" and context:
        hook = narrative(context)
    return f"{hook}: {lead}"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_feed(body: bytes, source: str) -> list[FeedEntry]:
    """Parse RSS 2.0 or Atom; malformed XML yields an empty list."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []
    entries: list[FeedEntry] = []
    for item in root.iter("item"):
        url = (item.findtext("link") or "").strip()
        if not url:
            continue
        entries.append(
            FeedEntry(
                source=source,
                url=url,
                title=(item.findtext("title") or "").strip(),
                published=_parse_date(item.findtext("pubDate")),
                content_html=item.findtext(_CONTENT) or item.findtext("description") or "",
            )
        )
    for entry in root.iter(f"{_ATOM}entry"):
        link = entry.find(f"{_ATOM}link")
        url = (link.get("href") if link is not None else "") or ""
        if not url:
            continue
        entries.append(
            FeedEntry(
                source=source,
                url=url.strip(),
                title=(entry.findtext(f"{_ATOM}title") or "").strip(),
                published=_parse_date(
                    entry.findtext(f"{_ATOM}published") or entry.findtext(f"{_ATOM}updated")
                ),
                content_html=entry.findtext(f"{_ATOM}content") or "",
            )
        )
    return entries


def _best_src(img: Tag, base: str) -> str:
    src = str(img.get("data-src") or img.get("data-lazy-src") or img.get("src") or "")
    srcset = str(img.get("srcset") or img.get("data-srcset") or "")
    best = 0
    for candidate in srcset.split(","):
        parts = candidate.strip().split()
        if len(parts) == 2 and parts[1].endswith("w") and parts[1][:-1].isdigit():
            width = int(parts[1][:-1])
            if width > best:
                best, src = width, parts[0]
    if not src or src.startswith("data:"):
        return ""
    return urljoin(base, src)


def _caption(img: Tag) -> str:
    figure = img.find_parent("figure")
    if figure is not None and (cap := figure.find("figcaption")) is not None:
        return cap.get_text(" ", strip=True)
    wp = img.find_parent(class_=re.compile("wp-caption"))
    if wp is not None and (cap := wp.find(class_=re.compile("caption-text"))) is not None:
        return cap.get_text(" ", strip=True)
    return ""


def article_text(html: str) -> str:
    """Plain text of an article body."""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def article_images(html: str, base_url: str) -> list[ArticleImage]:
    """Images of an article body in document order, with alt text and figure caption."""
    soup = BeautifulSoup(html, "lxml")
    images: list[ArticleImage] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        if not isinstance(img, Tag):
            continue
        url = _best_src(img, base_url)
        if not url or url in seen or re.search(r"\.(svg|gif)(\?|$)", url, re.IGNORECASE):
            continue
        if any(str(c) in {"avatar", "emoji", "wp-smiley"} for c in img.get("class") or []):
            continue
        seen.add(url)
        images.append(ArticleImage(url=url, alt=str(img.get("alt") or ""), caption=_caption(img)))
    return images
