"""OCR on ad creatives, screenshots and video keyframes (signal 9).

Emits `text.ocr` (normalised full text in reading order), `ocr.headline` (the title-like
block, see `headline_from_lines`, plus the link-card title of a feed ad, see
`card_title_from_lines`), `ad.advertiser` (the page name next to "Sponsorowane" /
"Sponsored") and `ocr.domain` for every domain typed in the image, `ocr.short_link` for a
"host/token" short link, and the feed-ad layout (`parse_ad_layout`) as context:
`ad.sponsored`, `ad.cta`, `ad.page_category`, `ad.card_domain`.
A domain read from pixels is only context (`ocr.domain`), not the campaign-tier landing
`url.domain`: two campaigns that both show the portal they imitate would merge on it.
The parsing helpers are pure and testable without the model.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

import numpy as np

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.core.text import normalize_text
from fakecollector.extractors._media import is_image

if TYPE_CHECKING:
    import tldextract

logger = logging.getLogger(__name__)

MAX_SIDE = 1280
MIN_TEXT_CHARS = 3
MIN_CONFIDENCE = 0.2
OCR_ROLES = {"screenshot", "ad_creative"}

# TLDs common in ads; OCR often inserts spaces or a comma before them ("example-lander . org").
_COMMON_TLDS = (
    "com|pl|net|org|info|online|shop|site|store|live|click|pro|top|xyz|icu|ink|life|io|co|eu|"
    "app|biz|club|website|space|fun|buzz|cc|me|tv|uk|de|news|blog|today|world|link|vip|best|"
    "sbs|cfd|bond|lat|guru|tech|digital|cloud|media|press|health|care"
)
_TLD_GAP = re.compile(
    rf"(?<=[a-z0-9])(?:\s*\.\s*|,)(?=(?:{_COMMON_TLDS})(?![a-z0-9-]))", re.IGNORECASE
)
_WWW_GAP = re.compile(r"\bw[wuv]w\s*[.,_]\s*|\bwww\s+(?=[a-z0-9])", re.IGNORECASE)
# Inside a URL ("https://" or "www." before it, or a "/" after it) a space stands for the
# dot before a common TLD: "www.sport-info click", "example com/AbC1".
_URL_SPACE_TLD = re.compile(
    rf"((?:https://|www\.)[a-z0-9.-]*[a-z0-9])\s+((?:{_COMMON_TLDS}))(?![a-z0-9-])|"
    rf"(?<![\w.-])([a-z0-9-]{{3,}})\s+((?:{_COMMON_TLDS}))(?=\s?/)",
    re.IGNORECASE,
)
# Defanged dots ("example[.]com", "example(.)com", "example[dot]com").
_DEFANG = re.compile(r"\s*(?:\[\s*\.\s*\]|\(\s*\.\s*\)|\[dot\]|\(dot\))\s*", re.IGNORECASE)
# A URL scheme as OCR misreads it: "https:llhost", "http:/lhost", "https //host",
# "httpsllhost", "ttps://", "hxxps://", "https:host". Group 1 = separator, 2 = slash-likes.
_SCHEME = re.compile(
    r"(?:h?(?:tt|xx)|ht)ps?(\s*[:;]?\s*)((?:[/\\|l1!I]\s*){0,2})(?=[a-z0-9ąćęłńóśźż])",
    re.IGNORECASE,
)
_SLASHES = "/\\|"
# A short-link token after a host: one path segment that looks generated (digits or
# mixed case), e.g. "/YwRG1X29".
_SHORT_PATH = re.compile(
    r"(?<![\w.-])((?:[a-z0-9ąćęłńóśźż-]+\.)+[a-z]{2,24})\s?/\s?([A-Za-z0-9_-]{4,32})(?![\w/.-])",
    re.IGNORECASE,
)
_HOST = re.compile(
    r"(?<![\w.-])((?:[a-z0-9ąćęłńóśźż](?:[a-z0-9ąćęłńóśźż-]{0,61}[a-z0-9ąćęłńóśźż])?\.)+"
    r"[a-z]{2,24})(?![\w-])"
)
# Real TLDs that in screenshots are far more often file extensions or abbreviations.
_REJECT_SUFFIX = {"zip", "mov", "py", "sh", "md", "rs", "js", "ts", "np", "nr", "tel"}
_SPONSORED = re.compile(r"\b(?:sponsorowan\w*|sponsored)\b", re.IGNORECASE)
_SEPARATORS = " \t·•.,:;|-–—*°'\"()[]"

HEADLINE_MIN_WORDS = 3
HEADLINE_MIN_CHARS = 12
HEADLINE_MAX_CHARS = 160
"""A title is a phrase, not a button label, and not a whole paragraph of post text."""

HEADLINE_LINE_RATIO = 0.75
"""Lines of one headline block differ in box height by less than this factor (descenders,
all-caps lines); body text under a title is set clearly smaller."""

HEADLINE_MAX_GAP = 1.0
"""Max vertical gap between two lines of one block, in multiples of the block line height."""

# Call-to-action buttons that OCR often merges into the neighbouring title line.
_CTA = re.compile(
    r"\b(?:dowiedz\s+si[eę]\s+wi[eę]cej|zobacz\s+wi[eę]cej|learn\s+more|see\s+more|"
    r"shop\s+now|kup\s+teraz|zam[oó]w\s+teraz|order\s+now|sign\s+up|"
    r"zarejestruj\s+si[eę]|wy[sś]lij\s+wiadomo[sś][cć]|send\s+message|apply\s+now|"
    r"czytaj\s+dalej|read\s+more|wy[sś]wietl\s+wi[eę]cej)\b",
    re.IGNORECASE,
)

# Feed / browser / app chrome that is never the ad's title (pl + en, lowercase match).
_CHROME = re.compile(
    # Meta Ad Library viewer (screenshots of an ad's library entry); phrases first.
    r"\b(?:szczegóły reklamy|link do reklamy|reklama ma kilka wersji|biblioteka reklam\w*|"
    r"ad details|ad library|transparentność\w*|wyświetl szczegóły|"
    r"sponsorowan\w*|sponsored|reklama|lubię to|like|komentarz\w*|comment\w*|"
    r"udostępnij\w*|share|wyślij\w*|send message|zobacz więcej|see more|więcej|"
    r"dowiedz się więcej|learn more|kup teraz|shop now|zarejestruj\w*|sign up|"
    r"zainstaluj|install|obserwuj|follow|zamknij|close|odpowiedz|reply|"
    r"wiadomość|message|przetłumacz|translate|ukryj|hide|zgłoś|report)\b",
    re.IGNORECASE,
)
_TIMESTAMP = re.compile(
    r"^\W*(?:\d{1,2}[:.]\d{2}|\d+\s*(?:min|godz|h|d|dni|tyg|w|s|sek)\.?|"
    r"(?:wczoraj|yesterday|teraz|now|just now)\b.*)\W*$",
    re.IGNORECASE,
)


class OcrLine(NamedTuple):
    """One grouped OCR text line, its median glyph height and its top edge in pixels."""

    text: str
    height: float
    top: float | None = None


@cache
def _tld() -> tldextract.TLDExtract:
    """Offline public-suffix extractor (bundled snapshot, never fetched)."""
    import tldextract

    return tldextract.TLDExtract(suffix_list_urls=())


def _scheme(m: re.Match[str]) -> str:
    sep, slashes = m.group(1), "".join(m.group(2).split())
    if not sep.strip() and not slashes:
        return m.group(0)  # "https" followed by a word: not a URL
    # Two slash-likes are the "//" ("ll", "/l", "/ I", "\\\\"); a lowercase "i" or a single
    # letter after the scheme is the host's first letter ("https:/instagram", "https:lidl").
    if "i" not in slashes and (len(slashes) == 2 or (slashes and slashes in _SLASHES)):
        return "https://"
    return "https://" + slashes.lstrip(_SLASHES)


def _space_tld(m: re.Match[str]) -> str:
    if m.group(1):
        return f"{m.group(1)}.{m.group(2)}"
    return f"{m.group(3)}.{m.group(4)}"


def normalize_urls(text: str) -> str:
    """Repair URL spelling that OCR breaks, keeping the case of paths.

    Undoes defanging ("[.]"), spaces or a comma before a common TLD, "www .", and scheme
    misreads ("https:llhost", "http:/lhost", "https //", "hxxps", "ttps"), so slash-likes
    read as letters are not glued onto the host ("llexample.com").
    """
    text = unicodedata.normalize("NFC", text)
    text = _DEFANG.sub(".", text)
    text = _WWW_GAP.sub("www.", text)
    text = _TLD_GAP.sub(".", text)
    text = _SCHEME.sub(_scheme, text)
    return _URL_SPACE_TLD.sub(_space_tld, text)


def _registrable(host: str) -> str | None:
    ext = _tld()(host)
    if not ext.suffix or not ext.domain:
        return None
    last = ext.suffix.rsplit(".", 1)[-1]
    if last in _REJECT_SUFFIX or ext.domain.isdigit():
        return None
    return f"{ext.domain}.{ext.suffix}"


def domains_from_text(text: str) -> list[str]:
    """Return registrable domains written in OCR text, in first-seen order.

    Repairs common OCR noise (`normalize_urls`), validates the suffix against the public
    suffix list, and rejects numbers ("5.00"), file names and abbreviations.
    """
    low = normalize_urls(text).lower()
    out: list[str] = []
    for m in _HOST.finditer(low):
        dom = _registrable(m.group(1))
        if dom and dom not in out:
            out.append(dom)
    return out


def short_links_from_text(text: str) -> list[str]:
    """Return "host/token" short links written in OCR text, e.g. "example.com/YwRG1X29".

    The token is a single path segment that looks generated (it has a digit or mixes
    case), so "/pl" or "/kontakt" are not short links. The host is lowercased, "www."
    dropped; the token keeps its case (short-link services are case-sensitive).
    """
    out: list[str] = []
    for m in _SHORT_PATH.finditer(normalize_urls(text)):
        host, token = m.group(1).lower(), m.group(2)
        host = host.removeprefix("www.")
        if not _registrable(host):
            continue
        # A capitalised word ("Zarejestruj" glued after a URL) is not a token.
        generated = any(ch.isdigit() for ch in token) or (
            any(ch.isupper() for ch in token[1:]) and any(ch.islower() for ch in token)
        )
        if not generated or token.isdigit():
            continue
        link = f"{host}/{token}"
        if link not in out:
            out.append(link)
    return out


def _slug(text: str) -> str:
    norm = normalize_text(text)
    return re.sub(r"[^\w]+", "-", norm).strip("-_")


def _is_name(text: str) -> bool:
    return sum(ch.isalnum() for ch in text) >= 2 and len(text) <= 60


def advertiser_from_lines(lines: list[str]) -> str | None:
    """Return the advertiser slug from OCR lines of a Facebook/Instagram ad screenshot.

    Takes the text after "Sponsorowane" / "Sponsored" on the same line, or else the
    page-name line directly above it.
    """
    for i, line in enumerate(lines):
        m = _SPONSORED.search(line)
        if not m:
            continue
        after = line[m.end() :]
        after = "".join(ch for ch in after if ch.isalnum() or ch in _SEPARATORS + "&_")
        after = after.strip(_SEPARATORS)
        if _is_name(after):
            return _slug(after) or None
        before = line[: m.start()].strip(_SEPARATORS)
        if _is_name(before):
            return _slug(before) or None
        if i > 0 and _is_name(lines[i - 1].strip(_SEPARATORS)):
            return _slug(lines[i - 1]) or None
    return None


# Ad call-to-action buttons (Meta's button set, pl + en), canonical label per pattern.
_AD_CTA: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"(?<!\w){pattern}(?!\w)", re.IGNORECASE), label)
    for pattern, label in (
        (r"dowiedz\s+si[eę]\s+wi[eę]cej", "Dowiedz się więcej"),
        (r"kup\s+teraz", "Kup teraz"),
        (r"zam[oó]w\s+teraz", "Zamów teraz"),
        (r"zarejestruj\s+si[eę]", "Zarejestruj się"),
        (r"zapisz\s+si[eę]", "Zapisz się"),
        (r"wy[sś]lij\s+wiadomo[sś][cć]", "Wyślij wiadomość"),
        (r"skorzystaj\s+z\s+oferty", "Skorzystaj z oferty"),
        (r"zainstaluj(?:\s+teraz)?", "Zainstaluj"),
        (r"pobierz(?:\s+teraz)?", "Pobierz"),
        (r"zarezerwuj(?:\s+teraz)?", "Zarezerwuj"),
        (r"zadzwo[nń](?:\s+teraz)?", "Zadzwoń"),
        (r"aplikuj(?:\s+teraz)?", "Aplikuj"),
        (r"zagraj(?:\s+teraz)?", "Zagraj"),
        (r"odbierz\s+ofert[eę]", "Odbierz ofertę"),
        (r"learn\s+more", "Learn more"),
        (r"shop\s+now", "Shop now"),
        (r"order\s+now", "Order now"),
        (r"sign\s+up", "Sign up"),
        (r"send\s+message", "Send message"),
        (r"apply\s+now", "Apply now"),
        (r"install\s+now", "Install now"),
        (r"get\s+offer", "Get offer"),
        (r"book\s+now", "Book now"),
        (r"download", "Download"),
    )
)
AD_CTA_MAX_WORDS = 6
"""A button line is short; the phrase inside a long sentence is post text, not a button."""

# Facebook page category line ("Usługi transportowe", "Strona · Witryna z wiadomościami").
_PAGE_CATEGORY = re.compile(
    r"^(?:(?:strona|page)\s*[·•.\-]\s*)?("
    r"(?:usługi|usługa|sklep|firma|serwis|witryna|organizacja|osoba publiczna|"
    r"blog|marka|produkt/usługa|produkt|finanse|bank|ubezpieczen\w*|doradc\w*|"
    r"edukacja|zdrowie|uroda|odzież|rozrywka|gry|media/wiadomości|społeczność|"
    r"agencja|inwestycj\w*|kryptowalut\w*|nieruchomości|sprzedaż|handel|"
    r"product/service|public figure|personal blog|news & media website|media/news company|"
    r"shopping & retail|financial service|transportation service|website|company|"
    r"e-commerce website|local business|community|brand|entertainment website|"
    r"internet company|investing service|insurance company|bank)\b[^\n]{0,40})$",
    re.IGNORECASE,
)
PAGE_CATEGORY_WINDOW = 3
"""The category line sits within this many lines of the page name / "Sponsorowane"."""


class AdLayout(NamedTuple):
    """Fields of a Facebook / Instagram feed-ad screenshot parsed from its OCR lines."""

    page_name: str | None
    sponsored: str | None
    ctas: list[str]
    category: str | None
    card_domain: str | None
    short_links: list[str]


def _page_name(lines: list[str], i: int, match: re.Match[str]) -> str | None:
    line = lines[i]
    after = line[match.end() :]
    after = "".join(ch for ch in after if ch.isalnum() or ch in _SEPARATORS + "&_")
    after = after.strip(_SEPARATORS)
    if _is_name(after):
        return " ".join(after.split())
    before = line[: match.start()].strip(_SEPARATORS)
    if _is_name(before):
        return " ".join(before.split())
    if i > 0 and _is_name(lines[i - 1].strip(_SEPARATORS)):
        return " ".join(lines[i - 1].strip(_SEPARATORS).split())
    return None


def _ctas(lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if len(line.split()) > AD_CTA_MAX_WORDS:
            continue
        for pattern, label in _AD_CTA:
            if pattern.search(line) and label not in [lab for _, lab in found]:
                found.append((i, label))
    return found


def parse_ad_layout(lines: list[str]) -> AdLayout | None:
    """Parse a feed-ad screenshot from OCR lines; None unless it looks like an ad.

    An ad has the "Sponsorowane" / "Sponsored" marker or a call-to-action button line.
    The page name is the line with or directly above the marker (as in
    `advertiser_from_lines`), the category a short category-like line near it, the card
    domain a bare domain line next to the button, and short links "host/token" anywhere.
    """
    sponsored: str | None = None
    page_name: str | None = None
    anchor: int | None = None
    for i, line in enumerate(lines):
        m = _SPONSORED.search(line)
        if m:
            sponsored = "Sponsored" if m.group(0).lower() == "sponsored" else "Sponsorowane"
            page_name = _page_name(lines, i, m)
            anchor = i
            break
    ctas = _ctas(lines)
    if sponsored is None and not ctas:
        return None
    category: str | None = None
    if anchor is not None:
        lo, hi = max(0, anchor - PAGE_CATEGORY_WINDOW), anchor + PAGE_CATEGORY_WINDOW + 1
        for line in lines[lo:hi]:
            text = " ".join(_SPONSORED.sub(" ", line).split()).strip(_SEPARATORS)
            cm = _PAGE_CATEGORY.match(text)
            if cm and len(cm.group(1).split()) <= 5 and cm.group(1) != page_name:
                category = cm.group(1).strip(_SEPARATORS)
                break
    card_domain: str | None = None
    for i, _label in ctas:
        for j in (i, i - 1, i + 1, i - 2, i + 2):
            if not 0 <= j < len(lines):
                continue
            text = lines[j]
            for _pattern, _lab in _AD_CTA:
                text = _pattern.sub(" ", text)
            text = text.strip(_SEPARATORS)
            if text and len(text.split()) <= 2:
                doms = domains_from_text(text)
                if doms:
                    card_domain = doms[0]
                    break
        if card_domain:
            break
    return AdLayout(
        page_name=page_name,
        sponsored=sponsored,
        ctas=[label for _, label in ctas],
        category=category,
        card_domain=card_domain,
        short_links=short_links_from_text("\n".join(lines)),
    )


def group_lines(detections: list[tuple[list[list[float]], str, float]]) -> list[str]:
    """Group easyocr detections into text lines in reading order (top-down, left-right)."""
    return [line.text for line in group_line_boxes(detections)]


def group_line_boxes(detections: list[tuple[list[list[float]], str, float]]) -> list[OcrLine]:
    """Like `group_lines`, but keep each line's median box height (title size cue)."""
    boxes = []
    for bbox, text, conf in detections:
        if conf < MIN_CONFIDENCE or not text.strip():
            continue
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        boxes.append((min(ys), max(ys), min(xs), text.strip()))
    boxes.sort(key=lambda b: (b[0], b[2]))
    lines: list[list[tuple[float, float, float, str]]] = []
    for box in boxes:
        top, bottom = box[0], box[1]
        if lines:
            cur = lines[-1]
            ctop = min(b[0] for b in cur)
            cbot = max(b[1] for b in cur)
            overlap = min(bottom, cbot) - max(top, ctop)
            if overlap > 0.5 * min(bottom - top, cbot - ctop):
                cur.append(box)
                continue
        lines.append([box])
    return [
        OcrLine(
            " ".join(b[3] for b in sorted(ln, key=lambda b: b[2])),
            float(np.median([b[1] - b[0] for b in ln])),
            float(min(b[0] for b in ln)),
        )
        for ln in lines
    ]


def is_chrome(text: str) -> bool:
    """True for UI chrome: platform buttons, "Sponsorowane", timestamps, bare URLs.

    A line is chrome when, after removing chrome words, digits and separators, fewer than
    `HEADLINE_MIN_CHARS` letters remain, so "Lubię to! · Komentarz · Udostępnij" is chrome
    but "Zarabiaj więcej niż w pracy" is not.
    """
    stripped = text.strip(_SEPARATORS)
    if not stripped or _TIMESTAMP.match(stripped):
        return True
    rest = _CHROME.sub(" ", stripped)
    if sum(ch.isalpha() for ch in rest) < HEADLINE_MIN_CHARS and rest != stripped:
        return True
    words = stripped.split()
    return len(words) <= 2 and bool(domains_from_text(stripped))


def _clean_title(text: str) -> str:
    return " ".join(_CTA.sub(" ", text).split()).strip(_SEPARATORS)


def _is_title(text: str) -> bool:
    return (
        len(text.split()) >= HEADLINE_MIN_WORDS
        and HEADLINE_MIN_CHARS <= len(text) <= HEADLINE_MAX_CHARS
    )


def _blocks(lines: list[OcrLine], skip: set[int]) -> list[tuple[float, str]]:
    """Runs of consecutive non-chrome lines set in the same font size, as (height, text)."""
    blocks: list[list[OcrLine]] = []
    current: list[OcrLine] = []
    for i, line in enumerate(lines):
        text = _clean_title(line.text)
        if i in skip or not text or is_chrome(text):
            if current:
                blocks.append(current)
            current = []
            continue
        if current:
            height = float(np.median([ln.height for ln in current]))
            prev = current[-1]
            gap = (
                line.top - (prev.top + prev.height)
                if line.top is not None and prev.top is not None
                else 0.0
            )
            ratio = min(line.height, height) / max(line.height, height, 1e-6)
            if ratio < HEADLINE_LINE_RATIO or gap > HEADLINE_MAX_GAP * height:
                blocks.append(current)
                current = []
        current.append(line._replace(text=text))
    if current:
        blocks.append(current)
    return [
        (float(np.median([ln.height for ln in block])), " ".join(ln.text for ln in block))
        for block in blocks
    ]


def headline_from_lines(lines: list[OcrLine]) -> str | None:
    """Pick the title-like OCR block: the largest-font run of lines, merged into one string.

    On a feed or page screenshot the first OCR line is the status bar, the page name or
    "Sponsorowane", so it is not the headline. A headline wraps over several lines set in
    the same large font, so consecutive lines of similar box height (`HEADLINE_LINE_RATIO`)
    with small vertical gaps (`HEADLINE_MAX_GAP`) form one block; UI chrome (`is_chrome`),
    the advertiser line next to "Sponsorowane" and call-to-action buttons merged into a line
    break or are cut from blocks. Blocks with at least `HEADLINE_MIN_WORDS` words and
    `HEADLINE_MIN_CHARS`..`HEADLINE_MAX_CHARS` characters are candidates (a longer block is
    body text). The tallest wins (headlines are set larger than body text); near-ties
    (within 10 %) go to the longer block. Returns None when no block qualifies, so callers
    can fall back to the first line.
    """
    skip: set[int] = set()
    for i, line in enumerate(lines):
        if _SPONSORED.search(line.text):
            skip.update({i - 1, i})
    candidates = [(height, text) for height, text in _blocks(lines, skip) if _is_title(text)]
    if not candidates:
        return None
    tallest = max(height for height, _ in candidates)
    return max((text for height, text in candidates if height * 1.1 >= tallest), key=len)


CARD_MIN_WORDS = 4
CARD_MIN_ALPHA = 0.75
"""A card title is a sentence: at least four words, mostly letters (not a phone mask, a
price list or the carousel's repeated button labels)."""


def _is_card_title(text: str) -> bool:
    chars = [ch for ch in text if not ch.isspace()]
    words = text.lower().split()
    return (
        _is_title(text)
        and len(words) >= CARD_MIN_WORDS
        and len(set(words)) > len(words) / 2
        and sum(ch.isalpha() for ch in chars) >= CARD_MIN_ALPHA * len(chars)
        and not is_chrome(text)
        and not _SPONSORED.search(text)
    )


def card_title_from_lines(lines: list[OcrLine]) -> str | None:
    """The link-card title of a feed ad: the phrase next to its call-to-action button.

    In a Facebook / Instagram ad the creative carries its own big text, and the story's
    title sits in the small link card beside "Dowiedz się więcej" / "Learn more", so the
    largest-font rule never picks it. Returns the first title-like line that shares a line
    with a CTA button or directly follows or precedes one, else None.
    """
    for i, line in enumerate(lines):
        if not _CTA.search(line.text):
            continue
        own = _clean_title(line.text)
        neighbours = [own] + [
            _clean_title(lines[j].text) for j in (i + 1, i - 1) if 0 <= j < len(lines)
        ]
        for text in neighbours:
            if _is_card_title(text):
                return text
    return None


@cache
def _reader() -> Any:
    """Load the easyocr reader once (GPU when available)."""
    import easyocr

    from fakecollector.models import device

    gpu = device() == "cuda"
    logger.info("loading easyocr pl+en (gpu=%s)", gpu)
    return easyocr.Reader(["pl", "en"], gpu=gpu, verbose=False)


def load_image(path: Path, max_side: int = MAX_SIDE) -> np.ndarray | None:
    """Read an image as RGB uint8, long side at most `max_side`; None if unreadable."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as im:
            im.seek(0)
            rgb = im.convert("RGB")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        logger.warning("cannot read image %s: %s", path, exc)
        return None
    scale = max_side / max(rgb.size)
    if scale < 1:
        rgb = rgb.resize(
            (round(rgb.width * scale), round(rgb.height * scale)), Image.Resampling.LANCZOS
        )
    return np.asarray(rgb)


def ocr_lines(image: np.ndarray) -> list[str]:
    """Run OCR on an RGB image and return text lines in reading order."""
    return [line.text for line in ocr_line_boxes(image)]


def ocr_line_boxes(image: np.ndarray) -> list[OcrLine]:
    """Run OCR on an RGB image and return text lines with their heights, in reading order."""
    detections = _reader().readtext(image, detail=1, paragraph=False)
    return group_line_boxes(detections)


HEADER_FRACTION = 0.2
"""Top share of the image where a cloned page keeps its masthead (as in image_embed)."""


def header_brands(lines: list[OcrLine], height: float, domains: list[str]) -> list[str]:
    """Brands whose wordmark OCR reads in the header band, even garbled ("BAZETA PL").

    A brand named in the story ("founder of InPost") sits in the body; the masthead of the
    portal a page dresses up as sits on top. So a fuzzy wordmark hit counts only for lines
    starting in the top `HEADER_FRACTION` of the image (layout corroboration), and not when
    the image also shows one of the brand's own domains (a real page of that brand).
    """
    from fakecollector.extractors.brand_rules import brands_in_text, own_brand

    found: list[str] = []
    for line in lines:
        if line.top is None or line.top > HEADER_FRACTION * height:
            continue
        for slug in brands_in_text(line.text):
            if slug not in found and not own_brand(slug, domains):
                found.append(slug)
    return found


def features_from_lines(
    artifact: Artifact, lines: list[str] | list[OcrLine], height: float = 0.0
) -> list[Feature]:
    """Turn OCR lines of one artifact into features.

    With `OcrLine`s (text + height) `ocr.headline` features are added (the largest-font
    block and, for a feed ad, the link-card title), and with the image `height` also
    `brand.impersonated` for wordmarks in the header band (`header_brands`); `TextExtractor`
    builds `text.headline_tpl` from it instead of the first OCR line.
    """
    boxes = [line for line in lines if isinstance(line, OcrLine)]
    lines = [line.text if isinstance(line, OcrLine) else line for line in lines]
    locator = artifact.meta.get("locator", "")
    full = normalize_text("\n".join(lines))
    feats: list[Feature] = []
    if len(full) >= MIN_TEXT_CHARS:
        feats.append(
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="text.ocr",
                value=full,
                locator=locator,
            )
        )
    if boxes and len(full) >= MIN_TEXT_CHARS:
        headlines = [headline_from_lines(boxes), card_title_from_lines(boxes)]
        for headline in dict.fromkeys(h for h in headlines if h):
            feats.append(
                Feature(
                    case_id=artifact.case_id,
                    artifact_id=artifact.id,
                    name="ocr.headline",
                    value=headline,
                    locator=locator,
                )
            )
    adv = advertiser_from_lines(lines)
    if adv:
        feats.append(
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="ad.advertiser",
                value=adv,
                confidence=0.8,
                locator=locator,
            )
        )
    layout = parse_ad_layout(lines)
    if layout is not None:
        layout_feats = [("ad.sponsored", layout.sponsored), ("ad.page_category", layout.category)]
        layout_feats += [("ad.cta", label) for label in layout.ctas]
        layout_feats.append(("ad.card_domain", layout.card_domain))
        for name, value in layout_feats:
            if value:
                feats.append(
                    Feature(
                        case_id=artifact.case_id,
                        artifact_id=artifact.id,
                        name=name,
                        value=value,
                        confidence=0.7,
                        locator=locator,
                    )
                )
    for link in short_links_from_text("\n".join(lines)):
        feats.append(
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="ocr.short_link",
                value=link,
                confidence=0.8,
                locator=locator,
            )
        )
    domains = domains_from_text("\n".join(lines))
    if boxes and height:
        for slug in header_brands(boxes, height, domains):
            feats.append(
                Feature(
                    case_id=artifact.case_id,
                    artifact_id=artifact.id,
                    name="brand.impersonated",
                    value=slug,
                    confidence=0.7,
                    locator="ocr:header",
                )
            )
    for dom in domains:
        feats.append(
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="ocr.domain",
                value=dom,
                confidence=0.8,
                locator=locator,
            )
        )
    return feats


class OcrExtractor(BaseExtractor):
    """easyocr (pl+en) on case-level screenshots, ad creatives and video keyframes."""

    name = "ocr"
    version = 6
    stage = 2
    requires: Literal["base", "ml"] = "ml"

    def supports(self, artifact: Artifact) -> bool:
        """Only case-level screenshots, ad creatives and keyframes; never landing assets."""
        return is_image(artifact) and artifact.role in OCR_ROLES

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """OCR one image."""
        image = load_image(artifact.path)
        if image is None or min(image.shape[:2]) < 8:
            return []
        try:
            lines = ocr_line_boxes(image)
        except (RuntimeError, ValueError, OSError, MemoryError) as exc:  # skip, never crash
            logger.warning("OCR failed on %s: %s", artifact.path, exc)
            return []
        return features_from_lines(artifact, lines, float(image.shape[0]))
