from __future__ import annotations

import pytest

from fakecollector.core.text import (
    detect_lang,
    headline_template,
    minhash_vector,
    normalize_text,
    shingles,
    tokens,
    topic,
)


def test_normalize_text_preserves_polish_letters() -> None:
    assert normalize_text("ZAROBISZ 5000 ZŁ!!") == "zarobisz 5000 zł"
    assert normalize_text("„  ＺＹＳＫ   rośnie... dalej!!!  ”") == "zysk rośnie... dalej"
    assert tokens("ZYSK: 5000 zł!") == ["zysk", "5000", "zł"]


def test_minhash_tolerates_a_changed_price() -> None:
    text = (
        "Wpłać 500 zł i odblokuj dostęp do fikcyjnej platformy gwiezdnych inwestycji. "
        "Na panelu zobaczysz jak rosną twoje środki każdego ranka. "
        "Po rejestracji opiekun pokaże ci wykresy i przygotuje raport na koniec tygodnia."
    )
    first = minhash_vector(text)
    second = minhash_vector(text.replace("500", "750"))
    assert first is not None and second is not None
    assert len(first) == len(second) == 128
    assert all(isinstance(value, float) and value.is_integer() for value in first)
    assert all(0 <= value < 2**32 for value in first)
    assert sum(left == right for left, right in zip(first, second, strict=True)) / 128 >= 0.7
    assert first == minhash_vector(text)


def test_minhash_uses_all_four_tokens_as_one_shingle() -> None:
    words = tokens("Zysk na jutro obiecany")
    assert shingles(words) == {"zysk na jutro obiecany"}
    assert shingles([]) == set()
    assert minhash_vector("Zysk na jutro") is None
    assert minhash_vector("Zysk na jutro obiecany", num_perm=8) is not None
    assert len(minhash_vector("Zysk na jutro obiecany", num_perm=8) or []) == 8


def test_headline_masks_names_dates_and_amounts() -> None:
    title = "Fikcyjny zespół Błękitny Zagajnik obiecuje 2 500,50 zł do 12.05.2027"
    assert headline_template(title) == "fikcyjny zespół {PERSON} obiecuje {NUM} zł do {DATE}"
    assert headline_template("Oferta trwa do 12 maja 2027 roku") == "oferta trwa do {DATE} roku"
    assert headline_template("Wiadomość od malinowskiego", ["Jan Malinowski"]) == (
        "wiadomość od {PERSON}"
    )
    assert headline_template("Nowy Projekt trafia do ABC DEF") == ("nowy projekt trafia do abc def")
    assert headline_template("?!") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("To jest oferta, która ma pomóc ci w oszczędzaniu.", "pl"),
        ("This is an offer that can help you save money.", "en"),
        ("Nie daj sie nabrac na to co widzisz.", "pl"),
        ("123 #?!", "und"),
    ],
)
def test_detect_lang(text: str, expected: str) -> None:
    assert detect_lang(text) == expected


def test_topic_returns_supported_prototype_and_hit_fraction() -> None:
    result = topic("Wpłać depozyt i inwestuj w akcje dla zysku.")
    assert result is not None
    name, score = result
    assert name == "investment"
    assert score == pytest.approx(5 / 8)
    assert topic("Dziś przyleciały bociany.") is None
