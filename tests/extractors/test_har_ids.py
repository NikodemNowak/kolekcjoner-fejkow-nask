import json
from pathlib import Path

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.har_ids import IdsExtractor, ids_from_text, ids_from_url

TENANT = "11111111-0000-4000-8000-000000000001"
LANDING = "00000000-0000-4000-8000-000000000001"


def _values(fs: list[Feature], name: str) -> set[str]:
    return {f.value for f in fs if f.name == name}


def test_kit_pixel_and_gtag_regexes() -> None:
    text = (
        f'<script src="/_cdn/production/landing-cdn/{TENANT}/{LANDING}/a.js"></script>'
        "<script>fbq('init', '1111222233334444');gtag('config','G-TEST000001');</script>"
        '<img src="https://www.facebook.com/tr?id=5555666677778888&ev=PageView">'
        "<!-- GTM-AB12CD --> AW-123456789"
    )
    found = ids_from_text(text)
    assert found["ids.kit_tenant"] == {TENANT}
    assert found["ids.kit_landing"] == {LANDING}
    assert found["ids.fb_pixel"] == {"1111222233334444", "5555666677778888"}
    assert found["ids.gtag"] == {"G-TEST000001", "GTM-AB12CD", "AW-123456789"}


def test_url_params_become_ad_and_click_ids() -> None:
    found = ids_from_url(
        "https://x.test/?utm_campaign=Spring&campaign_id=77&clickid=abc&lpkey=k1&q=1"
    )
    assert found["ids.ad_param"] == {"utm_campaign=Spring", "campaign_id=77"}  # case kept
    assert found["ids.click_key"] == {"clickid=abc", "lpkey=k1"}


def test_pixel_from_signals_config_url() -> None:
    found = ids_from_url("https://connect.facebook.net/signals/config/9999000011112222?v=2.9")
    assert found["ids.fb_pixel"] == {"9999000011112222"}


def test_id_only_in_saved_html_is_found(tmp_path: Path) -> None:
    page = tmp_path / "a.html"
    page.write_text(f"<html>fbq('init','1111222233334444') landing-cdn/t9/{LANDING}/x</html>")
    art = Artifact(id="1" * 16, case_id="T:1", kind="html", role="landing_page", path=page, size=1)
    fs = IdsExtractor().extract(art, [])
    assert _values(fs, "ids.fb_pixel") == {"1111222233334444"}
    assert _values(fs, "ids.kit_landing") == {LANDING}
    assert all(f.case_id == "T:1" and f.artifact_id == art.id and f.locator for f in fs)


def test_har_urls_and_bodies_are_scanned(tmp_path: Path) -> None:
    entries = [
        {
            "request": {
                "method": "GET",
                "url": f"https://l.test/landing-cdn/{TENANT}/{LANDING}/x.js",
            },
            "response": {
                "status": 200,
                "content": {"mimeType": "text/javascript", "text": "gtag('config','G-AAAA1111')"},
            },
        }
    ]
    har = tmp_path / "x.har"
    har.write_text(json.dumps({"log": {"creator": {"name": "t"}, "entries": entries}}))
    art = Artifact(id="2" * 16, case_id="T:1", kind="har", role="network", path=har, size=1)
    fs = IdsExtractor().extract(art, [])
    assert _values(fs, "ids.kit_tenant") == {TENANT}
    assert _values(fs, "ids.gtag") == {"G-AAAA1111"}
    assert any(f.locator.startswith("entry[0]") for f in fs)


def test_fixture_corpus_shares_landing_across_domains(fixture_artifacts: list[Artifact]) -> None:
    ex = IdsExtractor()
    by_case: dict[str, set[str]] = {}
    for a in fixture_artifacts:
        if ex.supports(a):
            for f in ex.extract(a, []):
                if f.name == "ids.kit_landing":
                    by_case.setdefault(f.case_id, set()).add(f.value)
    assert by_case["F:f1"] & by_case["F:f2"]
    assert not by_case["F:f1"] & by_case["F:f3"]
