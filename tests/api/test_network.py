import json
from pathlib import Path

from PIL import Image

from fakecollector.api.network import collector_image, collector_report


def test_collector_report_is_optional_and_tolerates_bad_json(tmp_path: Path) -> None:
    assert collector_report(tmp_path) is None
    folder = tmp_path / "collector"
    folder.mkdir()
    (folder / "last.json").write_text("{not json", encoding="utf-8")
    assert collector_report(tmp_path) is None
    (folder / "last.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    assert collector_report(tmp_path) == {"items": []}


def test_collector_image_is_reencoded_and_rejects_unsafe_ids(tmp_path: Path) -> None:
    item = tmp_path / "collector" / "inbox" / "demagog-1"
    item.mkdir(parents=True)
    Image.new("RGB", (400, 300), "red").save(item / "zrzut.png")
    data = collector_image(tmp_path, "demagog-1", 100)
    assert data is not None and data[:2] == b"\xff\xd8"  # JPEG, not the original PNG
    assert collector_image(tmp_path, "../demagog-1", 100) is None
    assert collector_image(tmp_path, "missing", 100) is None
