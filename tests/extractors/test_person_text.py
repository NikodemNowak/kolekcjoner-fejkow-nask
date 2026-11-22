"""Tests for public figures named in text (`person.mentioned`)."""

from __future__ import annotations

from pathlib import Path

from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.person_text import (
    PersonMentionExtractor,
    build_patterns,
    find_mentions,
    fold,
)

NAMES = {
    "daniel-obajtek": "Daniel Obajtek",
    "adam-glapinski": "Adam Glapiński",
    "rafal-brzoska": "Rafał Brzoska",
    "robert-lewandowski": "Robert Lewandowski",
    "anna-lewandowska": "Anna Lewandowska",
    "kuba-wojewodzki": "Kuba Wojewódzki",
    "monika-olejnik": "Monika Olejnik",
    "tomasz-lis": "Tomasz Lis",
    "cezary-pazura": "Cezary Pazura",
    "jan-kowalski": "Jan Kowalski",
    "piotr-kowalski": "Piotr Kowalski",
}
PATTERNS = tuple(build_patterns(NAMES))


def _slugs(text: str) -> list[str]:
    return [m.slug for m in find_mentions(text, PATTERNS)]


def test_fold_removes_polish_diacritics() -> None:
    assert fold("Glapiński, ŁÓDŹ") == "glapinski, lodz"


def test_inflected_surnames_are_found() -> None:
    assert _slugs("Obajtek był częścią systemu. Glapiński wstał") == [
        "daniel-obajtek",
        "adam-glapinski",
    ]
    assert _slugs("rozmowa z Obajtkiem") == ["daniel-obajtek"]
    assert _slugs("zamach na Rafała Brzoskę") == ["rafal-brzoska"]
    assert _slugs("Kuba Wojewódzki Show") == ["kuba-wojewodzki"]
    assert _slugs("Anna Lewandowska nie wiedziała") == ["anna-lewandowska"]


def test_short_or_common_surnames_need_the_full_name() -> None:
    assert _slugs("lis w lesie i pazura kota") == []
    assert _slugs("Tomasz Lis i Cezary Pazura") == ["tomasz-lis", "cezary-pazura"]


def test_shared_surnames_need_the_full_name() -> None:
    # "Kowalski" belongs to two people here: the surname alone names nobody.
    assert _slugs("pan Kowalski") == []
    assert _slugs("Jan Kowalski") == ["jan-kowalski"]


def test_mention_reports_the_words_that_matched() -> None:
    (mention,) = find_mentions("Wywiad: Daniel Obajtek mówi", PATTERNS)
    assert mention.matched == "Daniel Obajtek"


def test_extractor_reads_only_its_own_artifact_text(tmp_path: Path) -> None:
    art = Artifact(
        id="a1", case_id="C:1", kind="image", role="screenshot", path=tmp_path / "x", size=1
    )
    prior = [
        Feature(case_id="C:1", artifact_id="a1", name="text.ocr", value="Obajtkiem i Duda"),
        Feature(case_id="C:1", artifact_id="a2", name="text.ocr", value="Rafał Brzoska"),
        Feature(case_id="C:1", artifact_id="a1", name="ocr.headline", value="Obajtek mówi"),
    ]
    feats = PersonMentionExtractor().extract(art, prior)
    values = [f.value for f in feats]
    assert "daniel-obajtek" in values and "rafal-brzoska" not in values
    assert values.count("daniel-obajtek") == 1
    assert all(f.name == "person.mentioned" for f in feats)
    assert "from:text.ocr" in feats[0].locator


def test_mentions_never_link_cases() -> None:
    spec = FEATURES["person.mentioned"]
    assert spec.kind == "info" and spec.weight == 0.0 and spec.entity_type is None


def test_common_surnames_and_other_first_names_are_not_the_figure() -> None:
    assert _slugs("komentarz: Zofia Lewandowska, Tomasz Lewandowski") == []
    assert _slugs("wywiad z Lewandowskim") == []  # too common a surname to stand alone
    assert _slugs("Robert Lewandowski strzelił") == ["robert-lewandowski"]
    assert _slugs("Tomasz Obajtek pisze") == []  # another first name: another person
    assert _slugs("prezes Obajtek mówi") == ["daniel-obajtek"]
