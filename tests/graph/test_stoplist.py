from fakecollector.graph.stoplist import is_stopped_host, is_stopped_ip, load_stoplist


def test_platform_hosts_and_cdn_ips_are_stopped() -> None:
    assert is_stopped_host("connect.facebook.net")
    assert is_stopped_host("www.google-analytics.com")
    assert is_stopped_host("cdn.jsdelivr.net")
    assert not is_stopped_host("t1.example-tracker.org")
    assert is_stopped_ip("188.114.96.11")  # Cloudflare anycast
    assert is_stopped_ip("2606:4700::1")
    assert not is_stopped_ip("203.0.113.10")
    assert not is_stopped_ip("not-an-ip")


def test_stoplist_loads_once() -> None:
    assert load_stoplist() is load_stoplist()


def test_saas_hubs_and_brand_sites_are_stopped() -> None:
    assert is_stopped_host("yt3.googleusercontent.com")
    assert is_stopped_host("player.pandavideo.com.br")
    assert is_stopped_host("open.er-api.com")
    assert is_stopped_host("static.im-g.pl")  # the impersonated portal's own CDN


def test_every_impersonated_brand_domain_is_stopped() -> None:
    from fakecollector.extractors.brand_rules import _BRANDS

    missing = [d for _, domains in _BRANDS.values() for d in domains if not is_stopped_host(d)]
    assert missing == []
