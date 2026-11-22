"""OCR URL repair and feed-ad layout parsing on synthetic OCR lines."""

from pathlib import Path

import pytest

from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Artifact
from fakecollector.extractors.ocr import (
    domains_from_text,
    features_from_lines,
    normalize_urls,
    parse_ad_layout,
    short_links_from_text,
)


@pytest.mark.parametrize(
    "text",
    [
        "kliknij w poniższy link👇. https://example-shop.com/Ab12Cd34",
        "kliknij: https:llexample-shop.com/Ab12Cd34",
        "kliknij: https:/lexample-shop.com/Ab12Cd34",
        "kliknij: http:llexample-shop.com/Ab12Cd34",
        "kliknij: httpsllexample-shop.com/Ab12Cd34",
        "kliknij: https //example-shop.com/Ab12Cd34",
        "kliknij: https//example-shop.com/Ab12Cd34",
        "kliknij: https:\\\\example-shop.com/Ab12Cd34",
        "kliknij: https:||example-shop.com/Ab12Cd34",
        "kliknij: ttps://example-shop.com/Ab12Cd34",
        "kliknij: hxxps://example-shop[.]com/Ab12Cd34",
        "kliknij: https://example-shop. com/Ab12Cd34",
        "kliknij: HTTPS:LLEXAMPLE-SHOP.COM/Ab12Cd34",
        "linkhttps:llexample-shop.com/Ab12Cd34",
        "kliknij: https:/ /example-shop.com/Ab12Cd34",
        "kliknij: https:/ Iexample-shop.com/Ab12Cd34",
        "kliknij: https:|lexample-shop.com/Ab12Cd34",
        "kliknij: https:llexample-shop com/Ab12Cd34",
        "kliknij: example-shop com /Ab12Cd34",
    ],
)
def test_scheme_misreads_do_not_glue_onto_host(text: str) -> None:
    assert domains_from_text(text) == ["example-shop.com"]
    assert short_links_from_text(text) == ["example-shop.com/Ab12Cd34"]


def test_single_letter_after_scheme_is_kept() -> None:
    # "https:lidl..." lost both slashes; the "l" belongs to the host.
    assert domains_from_text("https:lampy-sklep.pl") == ["lampy-sklep.pl"]
    assert domains_from_text("https://lampy-sklep.pl") == ["lampy-sklep.pl"]


def test_space_for_dot_only_inside_a_url() -> None:
    assert domains_from_text("www example-shop icu i www.sport-info click") == [
        "example-shop.icu",
        "sport-info.click",
    ]
    assert domains_from_text("wuw.example.pl") == ["example.pl"]
    assert domains_from_text("piszę do was com sens") == []


def test_lowercase_i_after_scheme_is_the_host() -> None:
    assert domains_from_text("https:/instagram.com/x") == ["instagram.com"]


def test_normalize_urls_keeps_path_case() -> None:
    assert normalize_urls("https:llexample.com/YwRG") == "https://example.com/YwRG"
    assert normalize_urls("https to protokół") == "https to protokół"


def test_unknown_suffix_rejected() -> None:
    assert domains_from_text("https://example.notarealtld") == []


def test_short_link_needs_generated_token() -> None:
    assert short_links_from_text("example.com/kontakt example.com/pl") == []
    assert short_links_from_text("www.example.com/x7Kq") == ["example.com/x7Kq"]
    assert short_links_from_text("example.com/2024") == []
    assert short_links_from_text("https://example.blogspot.com/Zarejestruj") == []


_AD = [
    "12:41",
    "Karta promocyjna Testowo",
    "Sponsorowane · 🌐",
    "Usługi transportowe",
    "Aby otrzymać kartę, kliknij w poniższy link👇. https:llexample-card.com/Qw3Er7Ty",
    "EXAMPLE-CARD.COM",
    "Odbierz darmową kartę miejską już dziś",
    "Dowiedz się więcej",
    "Lubię to! Komentarz Udostępnij",
]


def test_parse_ad_layout_fields() -> None:
    layout = parse_ad_layout(_AD)
    assert layout is not None
    assert layout.page_name == "Karta promocyjna Testowo"
    assert layout.sponsored == "Sponsorowane"
    assert layout.category == "Usługi transportowe"
    assert layout.ctas == ["Dowiedz się więcej"]
    assert layout.card_domain == "example-card.com"
    assert layout.short_links == ["example-card.com/Qw3Er7Ty"]


def test_parse_ad_layout_english_and_inline_cta() -> None:
    layout = parse_ad_layout(
        ["Easy Joy", "Sponsored", "Great deal today", "SHOP.EXAMPLE.PL Shop now"]
    )
    assert layout is not None
    assert layout.sponsored == "Sponsored"
    assert layout.page_name == "Easy Joy"
    assert layout.ctas == ["Shop now"]
    assert layout.card_domain == "example.pl"
    assert layout.category is None


def test_no_layout_without_ad_markers() -> None:
    assert parse_ad_layout(["Zwykły artykuł", "o pogodzie w mieście"]) is None


def test_cta_inside_long_sentence_is_not_a_button() -> None:
    layout = parse_ad_layout(
        ["Sponsorowane", "Jeśli chcesz kup teraz w naszym sklepie wszystko co potrzebujesz"]
    )
    assert layout is not None
    assert layout.ctas == []


def test_layout_features_and_tiers(tmp_path: Path) -> None:
    art = Artifact(
        id="0" * 16, case_id="T:1", kind="image", role="screenshot", path=tmp_path / "a.png", size=1
    )
    feats = {(f.name, f.value) for f in features_from_lines(art, _AD)}
    assert ("ad.advertiser", "karta-promocyjna-testowo") in feats
    assert ("ad.sponsored", "Sponsorowane") in feats
    assert ("ad.cta", "Dowiedz się więcej") in feats
    assert ("ad.page_category", "Usługi transportowe") in feats
    assert ("ad.card_domain", "example-card.com") in feats
    assert ("ocr.short_link", "example-card.com/Qw3Er7Ty") in feats
    assert ("ocr.domain", "example-card.com") in feats
    assert not any(v.startswith("ll") for n, v in feats if n == "ocr.domain")
    for name in ("ad.sponsored", "ad.cta", "ad.page_category", "ad.card_domain"):
        assert FEATURES[name].kind == "info"
        assert FEATURES[name].weight == 0.0
    assert FEATURES["ocr.short_link"].family == "ids"
    assert FEATURES["ocr.short_link"].entity_type == "ShortLink"


def test_case_page_labels_are_polish() -> None:
    from fakecollector.api import pl

    for name in ("ad.advertiser", "ad.cta", "ad.page_category", "ocr.short_link"):
        assert name in pl.CASE_FEATURES
    assert pl.CASE_FEATURES["ad.cta"] == "Przycisk reklamy"
    assert pl.CASE_FEATURES["ocr.short_link"] == "Link skrócony"
