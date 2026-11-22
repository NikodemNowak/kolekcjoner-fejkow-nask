"""Public figures named in the text of a case (`person.mentioned`, "wzmianka w tekście").

A scam ad often names the figure it abuses ("Obajtek był częścią systemu…") even when the
picture shows no usable face. Names come from the public-figure reference list
(`refs/faces.csv`, plus the display names in `app/pl.py`) and are matched in OCR, page and
transcript text with simple Polish inflection: a full name in any case, or a distinctive
surname alone. The feature is informational (weight 0): it never links cases in the graph,
it only tells the analyst who the material talks about.
"""

from __future__ import annotations

import csv
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature

FEATURE_NAME = "person.mentioned"
TEXT_SOURCES = frozenset({"text.raw", "html.title", "text.ocr", "text.asr", "ocr.headline"})
FACE_REFS_CSV = Path(os.environ.get("FACE_REFS_CSV", "refs/faces.csv"))
MIN_SURNAME = 6  # shorter surnames alone are too often ordinary words or other people
# Surnames that may stand alone although short: unambiguous in Polish news text.
SHORT_SURNAMES = frozenset({"tusk", "duda", "musk", "janda"})
# Surnames that are also common Polish words ("pazura" = claw, "leszczyna" = hazel).
COMMON_WORDS = frozenset({"pazura", "leszczyna", "belka", "prokop", "kammel"})
MALE_NAMES_IN_A = frozenset({"kuba", "barnaba", "bonawentura"})
# Very common surnames: fake comments are signed "Zofia Lewandowska", so only the full name
# of the public figure counts.
COMMON_SURNAMES = frozenset(
    {"lewandowski", "lewandowska", "sikorski", "nowacka", "olejnik", "kubica", "wellman"}
)
# A surname right after another first name belongs to someone else ("Tomasz Lewandowski").
_FIRST_NAMES_TEXT = """
adam adrian agata agnieszka aleksandra alicja andrzej aneta angelika anna antoni
arkadiusz artur barbara bartosz beata bogdan bozena czeslaw damian daniel danuta dariusz
dawid dominik dorota edyta elzbieta emilia ewa ewelina filip franciszek grazyna grzegorz
halina hanna helena henryk hubert irena iwona izabela jacek jadwiga jakub jan janina
janusz jaroslaw jerzy joanna jolanta jozef julia justyna kacper kamil karol karolina
katarzyna kazimierz kinga klaudia krystyna krzysztof kuba lech leszek lucyna lukasz
maciej magdalena malgorzata marcin marek maria mariusz marta marzena mateusz michal
miroslaw monika natalia norbert oliwia patryk patrycja paulina pawel piotr przemyslaw
radoslaw rafal robert roman ryszard sebastian slawomir stanislaw stanislawa stefan
sylwia szymon tadeusz teresa tomasz urszula wanda weronika wieslaw wiktoria witold
wladyslaw wojciech zbigniew zdzislaw zofia zuzanna
"""
FIRST_NAMES = frozenset(_FIRST_NAMES_TEXT.split())
_NAME_BEFORE = re.compile(r"([a-z]+)\s+$")
_FOLD = str.maketrans({"ł": "l", "Ł": "l"})


def fold(text: str) -> str:
    """Lowercase ASCII form of Polish text: diacritics removed, `ł` -> `l`."""
    text = unicodedata.normalize("NFKD", text.translate(_FOLD).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _inflected(token: str, female: bool) -> str:
    """A regex for the common case forms of one folded name token."""
    if not female and len(token) > 4 and token.endswith("ki"):  # Morawiecki, Wojewódzki
        return re.escape(token[:-1]) + "(?:i|iego|iemu|im)"
    if female and len(token) > 4 and token[-3:] in {"ska", "cka", "zka"}:  # Lewandowska
        return re.escape(token[:-1]) + "(?:a|iej)"
    if not female and token.endswith("y") and len(token) > 3:  # Jerzy
        return re.escape(token[:-1]) + "(?:y|ego|emu|ym)"
    if token.endswith("ek") and len(token) > 4:  # Obajtek -> Obajtka, Obajtkiem
        return re.escape(token[:-2]) + "(?:ek|ka|kiem|kowi|ku)"
    if token[-1] in "aeiou":  # Brzoska -> Brzoski, Brzoskę; Kuba -> Kuby
        return re.escape(token[:-1]) + "(?:a|y|i|e|o|ie|zie|ce|dze)"
    if female:  # women's consonant surnames do not decline: Olejnik, Gessler
        return re.escape(token)
    return re.escape(token) + "(?:a|owi|em|iem|u|ie|e|y)?"  # Tusk -> Tuska, Tuskiem


@dataclass(frozen=True)
class NamePattern:
    """How one public figure can be named in text."""

    slug: str
    name: str
    pattern: re.Pattern[str]


def build_patterns(names: dict[str, str]) -> list[NamePattern]:
    """Regexes for `slug -> display name`; surnames shared by two people need the full name."""
    parts: dict[str, tuple[list[str], bool]] = {}
    for slug, name in names.items():
        tokens = fold(name).replace("-", " ").split()
        if len(tokens) < 2:
            continue
        female = tokens[0].endswith("a") and tokens[0] not in MALE_NAMES_IN_A
        parts[slug] = (tokens, female)
    surname_forms: dict[str, list[str]] = {}
    for slug, (tokens, female) in parts.items():
        surname_forms.setdefault(_inflected(tokens[-1], female), []).append(slug)
    out: list[NamePattern] = []
    for slug, (tokens, female) in parts.items():
        first, last = tokens[0], tokens[-1]
        middle = "".join(rf"\s+{re.escape(t)}" for t in tokens[1:-1])
        full = rf"{_inflected(first, female)}{middle}\s+{_inflected(last, female)}"
        alternatives = [f"(?P<full>{full})"]
        surname = _inflected(last, female)
        alone = (len(last) >= MIN_SURNAME or last in SHORT_SURNAMES) and last not in (
            COMMON_WORDS | COMMON_SURNAMES
        )
        if alone and len(surname_forms[surname]) == 1:
            alternatives.append(f"(?P<last>{surname})")
        regex = re.compile(rf"(?<![a-z0-9])(?:{'|'.join(alternatives)})(?![a-z0-9])")
        out.append(NamePattern(slug=slug, name=names[slug], pattern=regex))
    return out


def known_names(csv_path: Path | None = None) -> dict[str, str]:
    """Display names of the public figures the tool knows (reference list + UI names)."""
    from fakecollector.app.pl import PERSON_DISPLAY_NAMES

    names = dict(PERSON_DISPLAY_NAMES)
    path = csv_path or FACE_REFS_CSV
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                slug, name = row.get("person_slug", ""), row.get("display_name", "")
                if slug and name:
                    names.setdefault(slug, name)
    return names


@cache
def default_patterns() -> tuple[NamePattern, ...]:
    """Patterns for every known public figure (built once per process)."""
    return tuple(build_patterns(known_names()))


@dataclass(frozen=True)
class Mention:
    """One public figure named in a text, with the words that matched."""

    slug: str
    name: str
    matched: str


def find_mentions(text: str, patterns: tuple[NamePattern, ...] | None = None) -> list[Mention]:
    """Public figures named in `text`, each once, in order of first appearance."""
    if not text:
        return []
    folded = fold(text)
    # Folding keeps offsets for Polish letters; if it did not, report the folded words.
    original = text if len(folded) == len(text) else folded
    hits: list[tuple[int, Mention]] = []
    for item in patterns if patterns is not None else default_patterns():
        match = next(
            (m for m in item.pattern.finditer(folded) if not _someone_else(folded, m)), None
        )
        if match:
            words = original[match.start() : match.end()]
            hits.append((match.start(), Mention(item.slug, item.name, words)))
    return [mention for _, mention in sorted(hits, key=lambda h: h[0])]


def _someone_else(folded: str, match: re.Match[str]) -> bool:
    """A bare surname preceded by another first name names another person."""
    if match.group("full") is not None:
        return False
    before = _NAME_BEFORE.search(folded[max(0, match.start() - 40) : match.start()])
    return before is not None and before.group(1) in FIRST_NAMES


class PersonMentionExtractor(BaseExtractor):
    """`person.mentioned`: public figures named in the text found in an artifact."""

    name = "person_text"
    version = 2  # v2: common surnames need the full name
    stage = 3  # after OCR, page text and transcripts (stages 1-2)
    requires: Literal["base", "ml"] = "base"

    def supports(self, artifact: Artifact) -> bool:
        """Any artifact: the text comes from features of earlier stages."""
        return True

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """One feature per figure named in this artifact's text."""
        seen: set[str] = set()
        out: list[Feature] = []
        for source in prior:
            if source.artifact_id != artifact.id or source.name not in TEXT_SOURCES:
                continue
            for mention in find_mentions(source.value):
                if mention.slug in seen:
                    continue
                seen.add(mention.slug)
                out.append(
                    Feature(
                        case_id=artifact.case_id,
                        artifact_id=artifact.id,
                        name=FEATURE_NAME,
                        value=mention.slug,
                        confidence=1.0,
                        locator=f"from:{source.name} „{mention.matched[:60]}”",
                    )
                )
        return out
