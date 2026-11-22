from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fakecollector.core.schemas import Artifact
from fakecollector.extractors.ocr import (
    OcrExtractor,
    OcrLine,
    advertiser_from_lines,
    card_title_from_lines,
    domains_from_text,
    features_from_lines,
    group_line_boxes,
    group_lines,
    headline_from_lines,
    is_chrome,
)


def test_domain_from_ocr_text() -> None:
    assert domains_from_text("wejdź na Super-Zysk.com/promo") == ["super-zysk.com"]


def test_price_is_not_a_domain() -> None:
    assert domains_from_text("cena 5.00 zł") == []


def test_domain_ocr_noise_is_repaired() -> None:
    assert domains_from_text("www . example-lander . org i example-shop,com") == [
        "example-lander.org",
        "example-shop.com",
    ]
    assert domains_from_text("https://shop.example.co.uk/x?id=1") == ["example.co.uk"]


def test_file_names_and_abbreviations_rejected() -> None:
    assert domains_from_text("zdjecie.png raport.pdf skrypt.js np. tak 3.14") == []


def test_sentence_end_does_not_glue_into_domain() -> None:
    assert domains_from_text("Kup teraz. Promocja trwa") == []


def test_advertiser_line_above_sponsored() -> None:
    assert advertiser_from_lines(["Sunnyshop", "Sponsorowane · 🌐"]) == "sunnyshop"


def test_advertiser_after_sponsored() -> None:
    assert advertiser_from_lines(["Sponsorowane · Sunnyshop"]) == "sunnyshop"
    assert advertiser_from_lines(["Easy Joy", "Sponsored"]) == "easy-joy"


def test_no_advertiser_without_marker() -> None:
    assert advertiser_from_lines(["Sunnyshop", "Kup teraz"]) is None


def test_group_lines_reading_order() -> None:
    det = [
        ([[100, 10], [150, 10], [150, 30], [100, 30]], "world", 0.9),
        ([[10, 12], [80, 12], [80, 31], [10, 31]], "hello", 0.9),
        ([[10, 50], [80, 50], [80, 70], [10, 70]], "next", 0.9),
    ]
    assert group_lines(det) == ["hello world", "next"]


def _artifact(path: Path, role: str = "screenshot") -> Artifact:
    return Artifact(
        id="0" * 16,
        case_id="T:1",
        kind="image",
        role=role,  # type: ignore[arg-type]
        path=path,
        size=1,
    )


def test_supports_skips_landing_assets(tmp_path: Path) -> None:
    ex = OcrExtractor()
    assert ex.supports(_artifact(tmp_path / "a.png"))
    assert not ex.supports(_artifact(tmp_path / "a.png", role="landing_asset"))


@pytest.mark.gpu
def test_blank_image_gives_no_text(tmp_path: Path) -> None:
    path = tmp_path / "blank.png"
    Image.fromarray(np.full((200, 300, 3), 255, np.uint8)).save(path)
    feats = OcrExtractor().extract(_artifact(path), [])
    assert [f for f in feats if f.name == "text.ocr"] == []


@pytest.mark.gpu
def test_rendered_ad_text(tmp_path: Path) -> None:
    from PIL import ImageDraw, ImageFont

    img = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(img)
    try:  # the bitmap default font renders the dot too small for OCR
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        pytest.skip("DejaVuSans font not installed")
    draw.text((20, 20), "Sunnyshop", fill="black", font=font)
    draw.text((20, 90), "Sponsorowane", fill="black", font=font)
    draw.text((20, 170), "Wejdz na super-zysk.com", fill="black", font=font)
    path = tmp_path / "ad.png"
    img.save(path)
    feats = {(f.name, f.value) for f in OcrExtractor().extract(_artifact(path), [])}
    assert ("ad.advertiser", "sunnyshop") in feats
    assert ("ocr.domain", "super-zysk.com") in feats


def _box(x: float, y: float, h: float, text: str) -> tuple[list[list[float]], str, float]:
    w = 12.0 * len(text)
    return ([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], text, 0.9)


# A synthetic feed screenshot as easyocr boxes: status bar, page name, "Sponsorowane",
# post text, the creative's big title, the link bar and the buttons.
_FEED = [
    _box(10, 5, 14, "12:41"),
    _box(600, 5, 14, "87%"),
    _box(60, 40, 18, "Strona Testowa"),
    _box(60, 62, 14, "Sponsorowane · 3 godz."),
    _box(10, 100, 18, "Zobacz, co ogłoszono dziś rano w programie na żywo"),
    _box(10, 400, 46, "Nowy program oszczędnościowy"),
    _box(10, 455, 46, "dla każdego mieszkańca"),
    _box(10, 720, 14, "przyklad-portal.example"),
    _box(10, 740, 20, "Dowiedz się więcej"),
    _box(10, 790, 16, "Lubię to! · Komentarz · Udostępnij"),
]


def test_group_line_boxes_keep_line_height() -> None:
    lines = group_line_boxes(_FEED)
    assert lines[0] == OcrLine("12:41 87%", 14.0, 5.0)
    assert [line.height for line in lines][-5:] == [46.0, 46.0, 14.0, 20.0, 16.0]


def test_headline_is_title_not_first_line() -> None:
    """Audit 03: 94/113 OCR headline rows were the first OCR line, i.e. UI chrome."""
    lines = group_line_boxes(_FEED)
    assert lines[0].text == "12:41 87%"  # what the first-line rule picked
    assert headline_from_lines(lines) == "Nowy program oszczędnościowy dla każdego mieszkańca"


def test_headline_tie_prefers_longer_block() -> None:
    lines = [
        OcrLine("Krótki tytuł reklamy tutaj", 40, 0),
        OcrLine("Dłuższy tytuł tej samej reklamy", 38, 400),  # far below: its own block
    ]
    assert headline_from_lines(lines) == "Dłuższy tytuł tej samej reklamy"


def test_headline_merges_wrapped_title_lines() -> None:
    """Wild test: a three-line title was cut to its tallest line ("Rafała ..., założyciela")."""
    lines = [
        OcrLine("Portal Testowy WIADOMOŚCI SPORT", 26, 60),
        OcrLine("Wiem, kto to zrobił: skandal w", 42, 120),
        OcrLine("Jana Kowalskiego, założyciela", 49, 168),
        OcrLine("Firmy", 38, 222),  # one word, no descenders: still the same font
        OcrLine("Twórca sieci sklepów opowiada wczoraj wieczorem o wszystkim", 30, 268),
    ]
    assert (
        headline_from_lines(lines)
        == "Wiem, kto to zrobił: skandal w Jana Kowalskiego, założyciela Firmy"
    )


def test_headline_block_drops_merged_call_to_action() -> None:
    lines = [
        OcrLine("Smutny dzień dla wszystkich: żegnamy Dowiedz się więcej", 43, 100),
        OcrLine("Jana Kowalskiego", 42, 146),
    ]
    assert headline_from_lines(lines) == "Smutny dzień dla wszystkich: żegnamy Jana Kowalskiego"


def test_headline_block_breaks_on_chrome_and_font_change() -> None:
    lines = [
        OcrLine("Duży napis na grafice reklamy", 40, 100),
        OcrLine("Sponsorowane", 40, 145),
        OcrLine("Inny duży napis na grafice", 40, 190),
        OcrLine("mały podpis pod zdjęciem tutaj", 20, 235),
    ]
    assert headline_from_lines(lines) == "Inny duży napis na grafice"


def test_card_title_next_to_call_to_action() -> None:
    """A feed ad's story line sits small beside the CTA; the creative's big text wins size."""
    lines = [
        OcrLine("Strona Testowa", 16, 0),
        OcrLine("Sponsorowane", 16, 20),
        OcrLine("PILNE: NA ŻYWO", 40, 100),
        OcrLine("Dowiedz sie wiecej", 16, 400),
        OcrLine("PL Wydarzenie, które zmieniło cały kraj", 16, 420),
    ]
    assert headline_from_lines(lines) == "PILNE: NA ŻYWO"
    assert card_title_from_lines(lines) == "PL Wydarzenie, które zmieniło cały kraj"
    assert card_title_from_lines(lines[:3]) is None


def test_headline_none_when_only_chrome() -> None:
    lines = [OcrLine("Strona Testowa", 20), OcrLine("Sponsorowane", 14), OcrLine("Kup teraz", 30)]
    assert headline_from_lines(lines) is None


def test_chrome_lines() -> None:
    for text in (
        "Lubię to! · Komentarz · Udostępnij",
        "3 godz.",
        "14:05",
        "Learn more",
        "super-zysk.com",
        "Meta Szczegóły reklamy",
        "Meta Link do reklamy",
        "Reklama ma kilka wersji. 2 z 3",
    ):
        assert is_chrome(text), text
    for text in ("Zarabiaj więcej niż w pracy", "Nowy program oszczędnościowy"):
        assert not is_chrome(text), text


def test_features_carry_ocr_headline(tmp_path: Path) -> None:
    feats = features_from_lines(_artifact(tmp_path / "a.png"), group_line_boxes(_FEED))
    head = [f for f in feats if f.name == "ocr.headline"]
    assert [f.value for f in head] == ["Nowy program oszczędnościowy dla każdego mieszkańca"]
    ocr = next(f for f in feats if f.name == "text.ocr")
    assert ocr.value.startswith("12:41 87%")  # reading order unchanged
    plain = features_from_lines(_artifact(tmp_path / "a.png"), group_lines(_FEED))
    assert not any(f.name == "ocr.headline" for f in plain)


def test_ocr_domains_are_context_not_landing_domains(tmp_path: Path) -> None:
    from fakecollector.core.registry import FEATURES
    from fakecollector.extractors.ocr import features_from_lines
    from fakecollector.graph.entities import build_entities

    feats = features_from_lines(_artifact(tmp_path / "a.png"), ["Czytaj na portal-x.pl"])
    assert {(f.name, f.value) for f in feats if "domain" in f.name} == {
        ("ocr.domain", "portal-x.pl")
    }
    assert FEATURES["ocr.domain"].tier == "context"
    # Two campaigns showing the same portal must not share a campaign-tier Domain entity.
    ocr = next(f for f in feats if f.name == "ocr.domain")
    other = ocr.model_copy(update={"case_id": "T:2", "name": "url.domain"})
    entities, _ = build_entities([*feats, other], case_ids=["T:1", "T:2"])
    by_id = {e.id: e for e in entities}
    assert by_id["OcrDomain:portal-x.pl"].tier == "context"
    assert by_id["Domain:portal-x.pl"].df == 1


def test_header_brand_needs_masthead_position() -> None:
    from fakecollector.extractors.ocr import header_brands

    lines = [
        OcrLine("BAZETA PL WIADOMOŚCI SPORT", 26, 40),
        OcrLine("Założyciel InPostu opowiada o wszystkim", 30, 600),  # story, not masthead
    ]
    assert header_brands(lines, 1000, []) == ["gazeta_pl"]
    assert header_brands(lines, 150, []) == []  # line 1 starts below the top 20 %
    assert header_brands(lines, 1000, ["gazeta.pl"]) == []  # the real site's own domain


def test_features_carry_header_brand(tmp_path: Path) -> None:
    lines = [OcrLine("BAZETA PL WIADOMOŚCI", 26, 10), OcrLine("Treść artykułu na stronie", 20, 400)]
    feats = features_from_lines(_artifact(tmp_path / "a.png"), lines, 1000)
    brand = [f for f in feats if f.name == "brand.impersonated"]
    assert [(f.value, f.locator) for f in brand] == [("gazeta_pl", "ocr:header")]
    assert not any(
        f.name == "brand.impersonated"
        for f in features_from_lines(_artifact(tmp_path / "a.png"), lines)
    )
