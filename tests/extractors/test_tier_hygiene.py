"""A1 (plan v2): features land in the tier they describe (audit 04 section 1)."""

import json
from pathlib import Path

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.asset import AssetExtractor
from fakecollector.extractors.har_ids import IdsExtractor
from fakecollector.extractors.infra import RequestGraphExtractor
from fakecollector.extractors.template import TemplateExtractor

UUID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def _values(fs: list[Feature], name: str) -> set[str]:
    return {f.value for f in fs if f.name == name}


def _e(
    url: str,
    method: str = "GET",
    mime: str = "text/html",
    rtype: str | None = None,
    status: int = 200,
) -> dict[str, object]:
    e: dict[str, object] = {
        "request": {"method": method, "url": url},
        "response": {"status": status, "headers": [], "content": {"mimeType": mime}},
    }
    if rtype:
        e["_resourceType"] = rtype
    return e


def _har(tmp_path: Path, entries: list[dict[str, object]], name: str = "x.har") -> Artifact:
    p = tmp_path / name
    p.write_text(json.dumps({"log": {"creator": {"name": "t"}, "entries": entries}}))
    return Artifact(id="a" * 16, case_id="T:1", kind="har", role="network", path=p, size=1)


def _lander(host: str) -> list[dict[str, object]]:
    return [
        _e(f"https://{host}/", rtype="document"),
        _e(f"https://{host}/order-submit.php", method="POST", mime="application/json", rtype="xhr"),
        _e(
            f"https://{host}/include/stats-loader.js", mime="application/javascript", rtype="script"
        ),
        _e(
            f"https://{host}/api/v1/trigger/field/{UUID}/",
            method="POST",
            mime="application/json",
            rtype="fetch",
        ),
        _e(
            f"https://{host}/_cdn/production/landing-cdn/t1/{UUID}/img-1-hero.webp",
            mime="image/webp",
            rtype="image",
        ),
        _e(f"https://{host}/cdn-cgi/styles/cf.errors.css", mime="text/css", rtype="stylesheet"),
        _e("https://collector.stats.test/events?v=1", method="POST", mime="application/json"),
        _e("https://cdn.vendor.test/track.js", mime="application/javascript", rtype="script"),
    ]


def test_first_party_paths_are_never_operator_endpoints(tmp_path: Path) -> None:
    fs = RequestGraphExtractor().extract(_har(tmp_path, _lander("one.live")), [])
    endpoints = _values(fs, "infra.endpoint")
    assert not any("{1p}" in v for v in endpoints)  # order-submit.php, kit API, scripts
    assert "POST collector.stats.test/events?v" in endpoints  # a real third-party collector
    assert not any(v.startswith("GET") and v.endswith(".js") for v in endpoints)


def test_kit_signatures_keep_code_and_api_but_drop_story_and_error_paths(tmp_path: Path) -> None:
    sigs = _values(
        TemplateExtractor().extract(_har(tmp_path, _lander("one.live")), []), "kit.path_sig"
    )
    assert "/order-submit.php" in sigs  # first-party kit endpoint, now toolkit tier
    assert "/include/stats-loader.js" in sigs
    assert "/api/v{n}/trigger/field/{uuid}/" in sigs
    assert not any("hero" in s for s in sigs)  # story images are not toolkit evidence
    assert not any(s.startswith("/cdn-cgi/") for s in sigs)  # Cloudflare error chrome


def test_same_kit_on_two_domains_gives_the_same_signatures(tmp_path: Path) -> None:
    a = _values(
        TemplateExtractor().extract(_har(tmp_path, _lander("one.live"), "a.har"), []),
        "kit.path_sig",
    )
    b = _values(
        TemplateExtractor().extract(_har(tmp_path, _lander("two.click"), "b.har"), []),
        "kit.path_sig",
    )
    assert a == b and a


def _asset(path: Path, rel: str) -> Artifact:
    return Artifact(
        id="b" * 16,
        case_id="T:1",
        kind="asset",
        role="landing_asset",
        path=path,
        size=path.stat().st_size,
        meta={"rel": rel},
    )


def test_pixel_config_script_is_a_pixel_id_not_a_campaign_asset(tmp_path: Path) -> None:
    files = tmp_path / "Strona_files"
    files.mkdir()
    cfg = files / "1111222233334444"
    cfg.write_text("/* Meta pixel config */ fbq.registerPlugin('config', {});" * 40)
    art = _asset(cfg, "Strona_files/1111222233334444")
    assert AssetExtractor().extract(art, []) == []
    assert _values(IdsExtractor().extract(art, []), "ids.fb_pixel") == {"1111222233334444"}


def test_pixel_config_in_har_body_is_not_a_campaign_asset(tmp_path: Path) -> None:
    import base64

    body = ("fbq.registerPlugin('config', {});" * 40).encode()
    entry = _e(
        "https://connect.facebook.net/signals/config/1111222233334444?v=2",
        mime="application/javascript",
    )
    entry["response"]["content"].update(
        {"text": base64.b64encode(body).decode(), "encoding": "base64"}
    )  # type: ignore[index]
    art = _har(tmp_path, [_e("https://one.live/", rtype="document"), entry])
    assert AssetExtractor().extract(art, []) == []


def test_library_builds_are_not_campaign_assets(tmp_path: Path) -> None:
    files = tmp_path / "Strona_files"
    files.mkdir()
    jq = files / "jquery-3.6.0.min.js.pobrane"
    jq.write_text("/*! jQuery v3.6.0 | (c) OpenJS Foundation */" + "x" * 2000)
    banner = files / "vendor.js"
    banner.write_text("/*! Swiper 11.0.5 https://swiperjs.com */" + "y" * 2000)
    own = files / "app.js"
    own.write_text("var landing = 1;" * 200)
    ex = AssetExtractor()
    assert ex.extract(_asset(jq, "Strona_files/jquery-3.6.0.min.js.pobrane"), []) == []
    assert ex.extract(_asset(banner, "Strona_files/vendor.js"), []) == []
    assert len(ex.extract(_asset(own, "Strona_files/app.js"), [])) == 1


def test_script_only_third_party_host_is_a_kit_dependency_not_an_operator(tmp_path: Path) -> None:
    entries = [
        _e("https://one.live/", rtype="document"),
        _e("https://scripts-cdn.test/init.js?v=3", mime="text/javascript", rtype="script"),
        _e("https://collector.stats.test/events?v=1", method="POST", mime="application/json"),
        _e("https://api.data.test/track", mime="application/json", rtype="fetch"),
    ]
    fs = RequestGraphExtractor().extract(_har(tmp_path, entries), [])
    assert _values(fs, "kit.dep_host") == {"scripts-cdn.test"}
    assert "scripts-cdn.test" not in _values(fs, "infra.host_3p")
    assert {"collector.stats.test", "api.data.test"} <= _values(fs, "infra.host_3p")


def test_dependency_host_is_registered_as_toolkit() -> None:
    from fakecollector.core.registry import FEATURES

    assert FEATURES["kit.dep_host"].tier == "toolkit"
