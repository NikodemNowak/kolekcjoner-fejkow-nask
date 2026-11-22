"""Build the synthetic case folders in `data/fixtures/cases/` (CI and `demo --fixtures` input).

Everything here is invented: no organizer data. Deterministic, so re-running gives the
same bytes. Run: `uv run python scripts/make_fixtures.py`.
"""

from __future__ import annotations

import io
import json
import random
import shutil
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "cases"

TENANT_A = "f1x7e0aa"
LANDING_A = "0f8fad5b-d9cb-469f-a165-70867728950e"
LANDING_B = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
PIXEL_A = "1111222233334444"
PIXEL_Z = "9999888877776666"

ARTICLE_A = "Szokujące wyznanie znanego prezesa. Ekspert ujawnia metodę na szybki zysk. " * 12
ARTICLE_B = "Nowy suplement podbija rynek. Lekarze milczą o tej prostej metodzie. " * 12
SHOP = "Sklep internetowy. Dostawa w 24 godziny. Regulamin i polityka prywatności. " * 12


def _png(seed: int, size: int = 64) -> bytes:
    rnd = random.Random(seed)
    img = Image.new("RGB", (size, size))
    img.putdata(
        [(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size * size)]
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _html(url: str, title: str, body: str, tenant: str, landing: str, pixel: str) -> str:
    cdn = f"/_cdn/production/landing-cdn/{tenant}/{landing}"
    return (
        f"<!-- saved from url=({len(url):04d}){url} -->\n"
        f"<html><head><title>{title}</title>"
        f'<script src="{cdn}/app.js"></script>'
        f'<script>fbq("init", "{pixel}");</script></head>'
        f'<body><div class="hdr portal-chrome"><h1>{title}</h1></div>'
        f'<img src="{cdn}/hero.png"><p class="lead">{body}</p>'
        f'<form action="https://{url.split("/")[2]}/api/v1/order" method="post"></form>'
        f'<img src="https://www.facebook.com/tr?id={pixel}&ev=PageView"></body></html>'
    )


def _har(url: str, status: int, tenant: str, landing: str, pixel: str) -> str:
    host = url.split("/")[2]

    def entry(u: str, mime: str, st: int = 200) -> dict[str, object]:
        return {
            "startedDateTime": "2026-10-08T09:00:00.000Z",
            "serverIPAddress": "203.0.113.10",
            "request": {"method": "GET", "url": u},
            "response": {
                "status": st,
                "headers": [{"name": "Server", "value": "cloudflare"}],
                "content": {"mimeType": mime, "size": 0},
                "redirectURL": "",
            },
        }

    cdn = f"https://{host}/_cdn/production/landing-cdn/{tenant}/{landing}"
    entries = [
        entry(url, "text/html", status),
        entry(f"{cdn}/app.js", "application/javascript"),
        entry(f"https://www.facebook.com/tr?id={pixel}&ev=PageView", "image/gif"),
        entry(
            f"https://collector.fixture-stats.click/events?v=1&cid={landing[:8]}",
            "application/json",
        ),
    ]
    log = {
        "log": {"version": "1.2", "creator": {"name": "fixture"}, "pages": [], "entries": entries}
    }
    return json.dumps(log, indent=1)


def _browser_case(
    d: Path,
    url: str,
    title: str,
    body: str,
    tenant: str,
    landing: str,
    pixel: str,
    hero: bytes,
    shot_seed: int,
    har_name: str,
) -> None:
    d.mkdir(parents=True)
    (d / f"{title}.html").write_text(_html(url, title, body, tenant, landing, pixel), "utf-8")
    files = d / f"{title}_files"
    files.mkdir()
    (files / "hero.png").write_bytes(hero)
    (files / "app.js.pobrane").write_text("/* fixture kit */ var kit = 1;\n" * 30, "utf-8")
    (d / har_name).write_text(_har(url, 200, tenant, landing, pixel), "utf-8")
    (d / "Zrzut ekranu 2026-10-08 100000.png").write_bytes(_png(shot_seed, 48))


def build(out: Path = OUT) -> None:
    """(Re)create the six fixture cases under `out`."""
    if out.exists():
        shutil.rmtree(out)
    hero_a = _png(1)
    # f1: browser save, kit landing A on domain alpha.
    _browser_case(
        out / "f1",
        "https://fixture-alpha.click/?clickid=abc123&utm_source=fb",
        "Wyznanie prezesa",
        ARTICLE_A,
        TENANT_A,
        LANDING_A,
        PIXEL_A,
        hero_a,
        11,
        "fixture-alpha.click.har",
    )
    # f2: archive-tool format, same kit landing A on another domain (same campaign).
    cap = out / "f2" / "archive_fixture-beta.live_20261008_090000"
    (cap / "html").mkdir(parents=True)
    (cap / "screenshots").mkdir()
    url_b = "https://fixture-beta.live/?clickid=zz999"
    (cap / "archive_info.json").write_text(
        json.dumps(
            {"url": url_b, "timestamp_utc": "2026-10-08T09:00:00", "title": "Wyznanie prezesa"}
        ),
        "utf-8",
    )
    (cap / "network.har").write_text(_har(url_b, 200, TENANT_A, LANDING_A, PIXEL_A), "utf-8")
    (cap / "html" / "rendered.html").write_text(
        _html(url_b, "Wyznanie prezesa", ARTICLE_A, TENANT_A, LANDING_A, PIXEL_A), "utf-8"
    )
    (cap / "screenshots" / "screenshot.png").write_bytes(_png(12, 48))
    (cap / "dns_ssl.json").write_text(
        json.dumps(
            {"domain": "fixture-beta.live", "a": ["203.0.113.10"], "cert_issuer": "Fixture CA"}
        ),
        "utf-8",
    )
    res = cap / "resources" / "image"
    res.mkdir(parents=True)
    (res / "hero.png").write_bytes(hero_a)
    # f3: same tenant (operator), different landing and story (other campaign).
    _browser_case(
        out / "f3",
        "https://fixture-gamma.top/oferta",
        "Suplement",
        ARTICLE_B,
        TENANT_A,
        LANDING_B,
        PIXEL_A,
        _png(2),
        13,
        "fixture-gamma.top.har",
    )
    # f4: cloaking: one URL, two different pages, plus the ad creative.
    url_c = "https://fixture-glow.org/"
    for i, (title, body) in enumerate([("Artykuł", ARTICLE_A), ("Sklep", SHOP)], start=1):
        v = out / "f4" / f"strona_{i}"
        v.mkdir(parents=True)
        (v / "dom.html").write_text(_html(url_c, title, body, "t0", LANDING_B, PIXEL_Z), "utf-8")
    (out / "f4" / "reklama_1.png").write_bytes(_png(14, 48))
    # f5: screenshot only.
    (out / "f5").mkdir(parents=True)
    (out / "f5" / "IMG_0001.PNG").write_bytes(_png(15, 48))
    # f6: unrelated, hidden HAR and .htm.
    d6 = out / "f6"
    d6.mkdir(parents=True)
    url_u = "https://fixture-unrelated.icu/start"
    (d6 / "Inna strona.htm").write_text(
        _html(url_u, "Inna strona", SHOP, "zz", "00000000-0000-4000-8000-000000000000", PIXEL_Z),
        "utf-8",
    )
    (d6 / ".har").write_text(
        _har(url_u, 200, "zz", "00000000-0000-4000-8000-000000000000", PIXEL_Z), "utf-8"
    )


if __name__ == "__main__":
    build()
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"fixtures written to {OUT} ({total} bytes)")
