import hashlib
from pathlib import Path

from fakecollector.core.schemas import Artifact
from fakecollector.extractors.asset import AssetExtractor


def _art(path: Path, kind: str = "asset", role: str = "landing_asset") -> Artifact:
    return Artifact(
        id="3" * 16,
        case_id="T:1",
        kind=kind,
        role=role,
        path=path,
        size=path.stat().st_size,  # type: ignore[arg-type]
        meta={"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    )


def test_assets_below_512_bytes_are_ignored(tmp_path: Path) -> None:
    small = tmp_path / "s.png"
    small.write_bytes(b"x" * 511)
    big = tmp_path / "b.png"
    big.write_bytes(b"y" * 512)
    ex = AssetExtractor()
    assert ex.extract(_art(small), []) == []
    [f] = ex.extract(_art(big), [])
    assert f.name == "asset.sha256"
    assert f.value == hashlib.sha256(b"y" * 512).hexdigest()


def test_har_bodies_give_asset_hashes(tmp_path: Path) -> None:
    import base64
    import json

    body = b"z" * 1000
    entries = [
        {
            "request": {"method": "GET", "url": "https://l.test/a.png"},
            "response": {
                "status": 200,
                "content": {
                    "mimeType": "image/png",
                    "encoding": "base64",
                    "text": base64.b64encode(body).decode(),
                },
            },
        },
        {
            "request": {"method": "GET", "url": "https://l.test/tiny"},
            "response": {"status": 200, "content": {"mimeType": "text/plain", "text": "hi"}},
        },
    ]
    har = tmp_path / "x.har"
    har.write_text(json.dumps({"log": {"creator": {"name": "t"}, "entries": entries}}))
    fs = AssetExtractor().extract(_art(har, "har", "network"), [])
    assert [f.value for f in fs] == [hashlib.sha256(body).hexdigest()]
    assert fs[0].locator == "entry[0].response.content"


def test_screenshots_are_left_to_vision(tmp_path: Path) -> None:
    p = tmp_path / "shot.png"
    p.write_bytes(b"q" * 2000)
    assert not AssetExtractor().supports(_art(p, "image", "screenshot"))
