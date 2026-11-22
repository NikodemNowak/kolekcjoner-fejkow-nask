from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_WORD = re.compile(r"[^\W_]+")
# Shared with OCR/ASR (workstream B): keeps . % / : - so domains survive normalisation.
_PUNCT = re.compile(r"[^\w\s.%/:-]", re.UNICODE)
_SPACE = re.compile(r"\s+")

_MONTH = (
    r"(?i:stycz(?:eń|nia)|lut(?:y|ego)|mar(?:zec|ca)|kwie(?:cień|tnia)|maj(?:a)?|"
    r"czerwiec|czerwca|lipi(?:ec|ca)|sierpień|sierpnia|wrzesień|września|"
    r"październik(?:a)?|listopad(?:a)?|grudzień|grudnia|january|february|"
    r"march|april|may|june|july|august|september|october|november|december)"
)
_DATE = (
    rf"(?<!\d)(?:\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|"
    rf"\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}|"
    rf"\d{{1,2}} {_MONTH}\b(?: \d{{4}})?|"
    rf"\b{_MONTH} \d{{1,2}}\b(?:,? \d{{4}})?)(?!\d)"
)
_NUMBER = r"(?:\d{1,3}(?: \d{3})+(?!\d)|\d+)(?:[.,]\d+)*"
_CAPITALIZED = r"[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+"
_HEADLINE_SPAN = re.compile(
    rf"(?P<DATE>{_DATE})|(?P<NUM>{_NUMBER})|"
    rf"(?P<name>\b{_CAPITALIZED}(?:[ -]+{_CAPITALIZED})+\b)|[^\W\d_]+"
)
_PLACEHOLDER = re.compile(r"(\{(?:DATE|NUM|PERSON)\})")


def _word_set(words: str) -> frozenset[str]:
    return frozenset(words.split())


_PL_DIACRITICS = frozenset("ąćęłńóśźż")
_PL_STOPWORDS = _word_set(
    "a aby ale bez bo by co czy dla do go i ich jak jest już ma mi na nam nie o od po "
    "przez się sie są ten to tylko w we z za ze że"
)
_EN_STOPWORDS = _word_set(
    "a an and are as at be but by can for from has have how in is it of on or "
    "that the their this to was we what when will with you your"
)

_TOPIC_KEYWORDS = {
    "investment": _word_set(
        "akcje bitcoin depozyt giełda giełdzie inwestuj inwestycja inwestycje inwestycji kapitał "
        "kryptowaluty lokata oszczędności transakcje wpłać wpłata zainwestuj zarabiaj "
        "zarobek zarobisz zysk zysku zyski deposit earnings invest investment investing profit "
        "profits returns trading stocks"
    ),
    "health_product": _word_set(
        "apteka cholesterol cukrzyca kapsułki leczenie lek maść odchudzanie suplement suplementy "
        "tabletki terapia zdrowie cure capsules diabetes health medicine pills supplement "
        "supplements treatment"
    ),
    "gambling": _word_set(
        "bukmacher hazard jackpot kasyno kasyna loteria loterii obstawiaj ruletka wygrana "
        "wygraną wygraj zakłady bet betting casino gamble gambling lottery roulette slots"
    ),
    "fake_news": _word_set(
        "aresztowany aresztowanie dziennikarz fałszywe napaść pilne polityk sensacja skandal "
        "wiadomości wywiad arrested breaking celebrity journalist news politician scandal"
    ),
}
_MIN_TOPIC_CONFIDENCE = 0.05


def normalize_text(text: str) -> str:
    """Lower-case, NFKC-normalise, drop decorative punctuation, collapse whitespace.

    Polish diacritics are kept: they carry meaning ("zł", "żółć"). NFKC also folds
    full-width and ligature look-alikes that scam pages use to dodge keyword filters.
    """
    text = unicodedata.normalize("NFKC", text).lower()
    text = _PUNCT.sub(" ", text)
    text = _SPACE.sub(" ", text).strip()
    return text.strip(" .:-/")


def tokens(s: str) -> list[str]:
    """Return normalized letter and number tokens, preserving Polish diacritics."""
    return _WORD.findall(normalize_text(s))


def shingles(tokens: list[str], k: int = 5) -> set[str]:
    """Return unique word shingles, using the entire sequence if it is short."""
    if k < 1:
        raise ValueError("shingle length must be positive")
    if not tokens:
        return set()
    return {" ".join(tokens[i : i + k]) for i in range(max(1, len(tokens) - k + 1))}


def minhash_vector(text: str, num_perm: int = 128, seed: int = 0) -> list[float] | None:
    """Hash five-word shingles into integral values that fit the graph vector format."""
    words = tokens(text)
    if len(words) < 4:
        return None

    from datasketch import MinHash

    sketch = MinHash(num_perm=num_perm, seed=seed)
    sketch.update_batch([shingle.encode("utf-8") for shingle in sorted(shingles(words))])
    return [float(value) for value in sketch.hashvalues]


def headline_template(title: str, known_names: Iterable[str] = ()) -> str | None:
    """Mask dates, numbers, and likely proper names in a headline."""
    text = " ".join(unicodedata.normalize("NFKC", title).split())
    if not text:
        return None
    surname_prefixes = {
        words[-1][:5] for name in known_names if (words := tokens(name)) and len(words[-1]) >= 5
    }

    def mask(match: re.Match[str]) -> str:
        kind = match.lastgroup
        if kind in ("DATE", "NUM"):
            return "{" + kind + "}"
        span = match[0]
        if surname_prefixes and any(word[:5] in surname_prefixes for word in tokens(span)):
            return "{PERSON}"
        if kind == "name":
            preceding = text[: match.start()].rstrip(" \"'„”«»([{")
            if preceding and preceding[-1] not in ".!?":
                return "{PERSON}"
        return span

    # Keep generated markers uppercase even when they sit at a headline boundary.
    parts = _PLACEHOLDER.split(_HEADLINE_SPAN.sub(mask, text))
    parts[::2] = [normalize_text(part) for part in parts[::2]]
    return " ".join(filter(None, parts)) or None


def headline_content(template: str, min_tokens: int = 4) -> str | None:
    """Content words of a headline template for fuzzy comparison, or None when too short.

    Placeholders ({PERSON}, {NUM}, {DATE}) and punctuation-only tokens are dropped: they
    are shared by unrelated headlines, and a token-set ratio counts a short template that is
    a subset of a longer one as a full match. Punctuation is cut and Polish diacritics are
    folded, since OCR drops both ("wstrzasnęło", "strzelałw:").
    """
    words = [
        folded
        for word in template.split()
        if not _PLACEHOLDER.fullmatch(word) and (folded := _fold(word))
    ]
    return " ".join(words) if len(words) >= min_tokens else None


def _fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.replace("ł", "l").replace("Ł", "L"))
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


# Function words and generic interface phrases ("kliknij", "kontynuuj", "witaj"): they do
# not make a headline specific to one campaign, so they never count as informative content.
_UNINFORMATIVE = frozenset(
    _fold(word)
    for word in _word_set(
        "a aby ale bez bo by co czy dla do go i ich jak jest już ma mi na nam nie o od po "
        "przez się sie są ten to tylko w we z za ze że ta te tak tej tego jego jej oraz "
        "lub albo też także jeszcze bardzo teraz tu tutaj gdy kiedy który która które "
        "którzy kto twój twoja twoje twoich swój swoja swoje swoich mój moja moje nasz nasze "
        "wasz wszystkie wszystkich wszystko każdy można może być był była było będzie "
        "kliknij klikaj kontynuuj dalej witaj witajcie zobacz sprawdź więcej przejdź "
        "zaloguj zarejestruj pobierz otwórz zamknij ok pl com www http https "
        "an and are as at be but by can for from has have how in is it of on or that the "
        "their this to was we what when will with you your click continue welcome here "
        "more see now"
    )
)


def informative_tokens(text: str) -> set[str]:
    """Distinct folded content words of a headline, without generic words.

    Placeholders, function words and interface phrases are dropped: "witaj w {PERSON}" has
    none.
    """
    return {
        folded
        for word in _PLACEHOLDER.sub(" ", text).split()
        if (folded := _fold(word).lower())
        and len(folded) > 1
        and folded not in _UNINFORMATIVE
        and not folded.isdigit()
    }


def detect_lang(text: str) -> str:
    """Guess Polish or English from stopwords and Polish diacritics."""
    words = tokens(text)
    polish = sum(word in _PL_STOPWORDS for word in words)
    polish += 2 * sum(not _PL_DIACRITICS.isdisjoint(word) for word in words)
    english = sum(word in _EN_STOPWORDS for word in words)
    if polish == english:
        return "und"
    return "pl" if polish > english else "en"


def topic(text: str) -> tuple[str, float] | None:
    """Return the closest keyword prototype and its hit rate, with a confidence floor."""
    words = tokens(text)
    hits = {
        name: sum(word in keywords for word in words) for name, keywords in _TOPIC_KEYWORDS.items()
    }
    name = max(hits, key=hits.__getitem__)
    if not hits[name]:
        return None
    return name, max(_MIN_TOPIC_CONFIDENCE, hits[name] / len(words))
