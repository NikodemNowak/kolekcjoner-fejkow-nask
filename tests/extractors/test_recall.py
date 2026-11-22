"""A3 (plan v2): cheap recall gains (synthetic values only)."""

from fakecollector.extractors.har_ids import ids_from_url
from fakecollector.ingest.normalize import looks_random, url_schema


def test_pixel_id_from_landing_url_parameters() -> None:
    found = ids_from_url("https://l.test/?pxl=1111222233334444&fbpx=5555666677778888&x=1")
    assert found["ids.fb_pixel"] == {"1111222233334444", "5555666677778888"}
    assert "ids.fb_pixel" not in ids_from_url("https://l.test/?pxl=abc")


def test_random_slugs_are_masked_in_url_schema() -> None:
    a = url_schema("https://one.test/kt5vpccv?utm_source=fb")
    b = url_schema("https://two.test/tzqfbfsc?utm_source=ig")
    assert a == b == "/{slug}?utm_source"
    assert url_schema("https://x.test/landing/oferta") == "/landing/oferta"  # words stay


def test_looks_random() -> None:
    assert looks_random("kt5vpccv") and looks_random("tzqfbfsc") and looks_random("q8ZrT3mXp2")
    assert not looks_random("landing") and not looks_random("oferta") and not looks_random("Spring")
    assert not looks_random("abc")  # too short to tell


def test_random_ad_parameter_values_are_not_ids_and_case_is_kept() -> None:
    found = ids_from_url(
        "https://x.test/?utm_campaign=SpringSale&utm_content=qwrtzpkdlm&campaign_id=12345"
    )
    assert found["ids.ad_param"] == {"utm_campaign=SpringSale", "campaign_id=12345"}


def test_hyphenated_generated_slugs_and_param_names_are_masked() -> None:
    a = url_schema("https://one.test/l11111111ab-222c333-xyz444q/?clickid=1&key=2")
    b = url_schema("https://two.test/l99999999cd-888d777-qwe111z/?key=3&clickid=4")
    assert a == b == "/{slug}/?clickid&key"
    assert (
        url_schema("https://x.test/a??utm_kqzrtvbnmxl=1&utm_source=2") == "/a?utm_source&utm_{slug}"
    )


def test_more_random_shapes_and_polish_words() -> None:
    assert looks_random("pkldrnqusa")  # long consonant run
    assert not looks_random("przestrzeń") and not looks_random("szczygieł")
    assert not looks_random("oferta-specjalna")


def test_pixel_fb_parameter() -> None:
    assert ids_from_url("https://l.test/?pixel_fb=1111222233334444")["ids.fb_pixel"] == {
        "1111222233334444"
    }
