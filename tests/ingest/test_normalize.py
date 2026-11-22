from fakecollector.ingest.normalize import canonical_url, url_schema


def test_canonical_url_strips_tracking() -> None:
    assert canonical_url("https://Ex.com/a?utm_source=x&gclid=1&id=5") == "https://ex.com/a?id=5"


def test_canonical_url_drops_fragment_default_port_and_sorts_query() -> None:
    assert canonical_url("HTTPS://ex.com:443/a/?b=2&a=1#top") == "https://ex.com/a/?a=1&b=2"
    assert canonical_url("http://ex.com") == "http://ex.com/"


def test_canonical_url_keeps_non_urls_untouched() -> None:
    assert canonical_url("not a url") == "not a url"


def test_url_schema_equal_when_only_values_differ() -> None:
    a = "https://one.test/landing/123/?clickid=abc&key=1"
    b = "https://two.test/landing/98765/?key=zz&clickid=def"
    assert url_schema(a) == url_schema(b) == "/landing/{n}/?clickid&key"


def test_url_schema_masks_uuid_and_hex() -> None:
    url = "https://x.test/_cdn/production/landing-cdn/t1/0f8fad5b-d9cb-469f-a165-70867728950e/a.js"
    assert url_schema(url) == "/_cdn/production/landing-cdn/t1/{uuid}/a.js"
    assert url_schema("https://x.test/p/9f86d081884c7d65") == "/p/{hex}"


def test_as_url_accepts_bare_domains_with_a_public_suffix() -> None:
    from fakecollector.ingest.normalize import as_url

    assert as_url("https://x.test/a") == "https://x.test/a"
    assert as_url("evil-site.live") == "https://evil-site.live/"
    assert as_url("www.evil-site.live/oferta?id=1") == "https://www.evil-site.live/oferta?id=1"
    assert as_url("Synthetic product name") is None  # a text hint, not a URL
    assert as_url("main.js") is None  # .js is not a public suffix
    assert as_url("ftp://x.live") is None
