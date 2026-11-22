from pathlib import Path

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.brand import BRAND_NAMES
from fakecollector.extractors.brand_rules import BrandRulesExtractor


def _page(tmp_path: Path, html: str, url: str = "https://lander-alpha.test/") -> Artifact:
    p = tmp_path / "a.html"
    p.write_text(html, encoding="utf-8")
    return Artifact(
        id="e" * 16,
        case_id="T:1",
        kind="html",
        role="landing_page",
        path=p,
        size=1,
        meta={"url": url},
    )


def _brands(fs: list[Feature]) -> set[str]:
    return {f.value for f in fs if f.name == "brand.impersonated"}


def test_title_suffix_names_the_imitated_portal(tmp_path: Path) -> None:
    title = "Sensacyjne wyznanie założyciela InPostu — Gazeta.pl"
    html = f"<html><head><title>{title}</title></head></html>"
    fs = BrandRulesExtractor().extract(_page(tmp_path, html), [])
    assert _brands(fs) == {"gazeta_pl"}  # InPost is the story, not the imitated brand
    assert all(f.value in BRAND_NAMES for f in fs)


def test_site_name_meta_and_logo_image(tmp_path: Path) -> None:
    html = (
        '<html><head><meta property="og:site_name" content="TVN24"></head><body>'
        '<img src="x_files/logo-pko-bp.png" alt=""><img src="hero.png" alt="Onet"></body></html>'
    )
    fs = BrandRulesExtractor().extract(_page(tmp_path, html), [])
    assert _brands(fs) == {"tvn24"}
    # A logo file alone may be an "as seen on" badge: context only.
    assert {(f.name, f.value) for f in fs if f.name == "brand.logo"} == {("brand.logo", "pko_bp")}


def test_real_brand_domain_is_not_impersonation(tmp_path: Path) -> None:
    html = "<html><head><title>Wiadomości — Gazeta.pl</title></head></html>"
    fs = BrandRulesExtractor().extract(_page(tmp_path, html, "https://next.gazeta.pl/a"), [])
    assert _brands(fs) == set()


def test_topic_mentions_do_not_count(tmp_path: Path) -> None:
    html = "<html><head><title>Jak znana dziennikarka przepytała prezesa NBP</title></head></html>"
    assert _brands(BrandRulesExtractor().extract(_page(tmp_path, html), [])) == set()


def test_rule_slugs_match_vision_brand_slugs() -> None:
    from fakecollector.extractors.brand_rules import _BRANDS

    assert set(_BRANDS) <= set(BRAND_NAMES)


def test_every_vision_brand_except_facebook_has_a_text_rule() -> None:
    from fakecollector.extractors.brand_rules import _BRANDS

    assert set(BRAND_NAMES) - set(_BRANDS) == {"facebook"}  # FB widgets are normal page chrome


def test_new_brand_slugs_from_titles_and_logos(tmp_path: Path) -> None:
    cases = {
        "Nowa ulga dla emerytów — ZUS": "zus",
        "Inwestycja roku | Business Insider Polska": "business_insider",
        "Breaking: new platform | Fox News": "fox_news",
        "Wiadomości - Polsat News": "polsat",
    }
    for title, slug in cases.items():
        html = f"<html><head><title>{title}</title></head></html>"
        assert _brands(BrandRulesExtractor().extract(_page(tmp_path, html), [])) == {slug}, title
    logo = '<html><body><img src="x_files/logo-mbank.svg"></body></html>'
    fs = BrandRulesExtractor().extract(_page(tmp_path, logo), [])
    assert _brands(fs) == set()  # a logo alone is context (brand.logo), not impersonation
    assert {f.value for f in fs if f.name == "brand.logo"} == {"mbank"}


def test_footer_payment_and_trust_badges_are_not_impersonation(tmp_path: Path) -> None:
    html = (
        "<html><head><title>Krem na stawy — oferta</title></head><body><footer>"
        '<img src="x_files/logo-pko-bp.png" alt="Płatność PKO BP">'
        '<img src="x_files/logo-tvn24.png" alt="Znane z TVN24 logo">'
        "</footer></body></html>"
    )
    fs = BrandRulesExtractor().extract(_page(tmp_path, html), [])
    assert _brands(fs) == set()  # page identity (title / site name) names no brand
    assert {f.value for f in fs if f.name == "brand.logo"} == {"pko_bp", "tvn24"}


def test_new_brand_on_its_own_domain_is_not_impersonation(tmp_path: Path) -> None:
    html = "<html><head><title>Najbogatsi Polacy — Forbes</title></head></html>"
    assert (
        _brands(BrandRulesExtractor().extract(_page(tmp_path, html, "https://www.forbes.pl/a"), []))
        == set()
    )


def test_ocr_wordmark_tolerates_letter_errors() -> None:
    from fakecollector.extractors.brand_rules import brands_in_text

    assert brands_in_text("BAZETA PL WIADOMOŚCI SPORT") == ["gazeta_pl"]
    assert brands_in_text("GAZETA.PL") == ["gazeta_pl"]
    assert brands_in_text("Bank Pekao S.A.") == ["pekao"]
    assert brands_in_text("Gazeta Polska codziennie") == []  # a different title
    assert brands_in_text("tvp") == ["tvp"]
    assert brands_in_text("tvq") == []  # short marks only match exactly
    assert brands_in_text("Polska dziś rano") == []
