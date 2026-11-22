import json
from pathlib import Path

from fakecollector.core.schemas import Artifact
from fakecollector.extractors.ad_library import AdLibraryExtractor


def _write(tmp_path: Path, info: object) -> Artifact:
    path = tmp_path / "Ad [123456789012345_1].info.json"
    path.write_text(json.dumps(info))
    return Artifact(
        id="1" * 16, case_id="T:1", kind="json", role="ad_library_meta", path=path, size=1
    )


def test_info_json_gives_ad_id_and_advertiser(tmp_path: Path) -> None:
    art = _write(
        tmp_path,
        {
            "id": "123456789012345_1",
            "title": "Kliknij TERAZ!",
            "playlist_id": "123456789012345",
            "playlist_uploader": "Easy Joy",
            "playlist_uploader_id": "998877665544",
            "webpage_url": "https://www.facebook.com/ads/library/?id=123456789012345",
            "extractor": "facebook:ads",
        },
    )
    ex = AdLibraryExtractor()
    assert ex.supports(art)
    feats = {(f.name, f.value) for f in ex.extract(art, [])}
    assert ("ids.ad_library", "123456789012345") in feats
    assert ("ad.advertiser", "easy-joy") in feats
    assert ("ids.advertiser_page", "998877665544") in feats
    assert ("text.ocr", "kliknij teraz") in feats


def test_id_from_id_field_when_no_url(tmp_path: Path) -> None:
    art = _write(tmp_path, {"id": "555555555555_2"})
    feats = AdLibraryExtractor().extract(art, [])
    assert [(f.name, f.value) for f in feats] == [("ids.ad_library", "555555555555")]


def test_malformed_json_is_skipped(tmp_path: Path) -> None:
    art = _write(tmp_path, {})
    art.path.write_text("{not json")
    assert AdLibraryExtractor().extract(art, []) == []
