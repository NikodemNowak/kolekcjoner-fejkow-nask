import hashlib
from pathlib import Path

from fakecollector.app.page_add import save_upload


def test_different_bytes_never_share_a_folder(tmp_path: Path) -> None:
    first = save_upload(tmp_path, "input.har", b"one")
    second = save_upload(tmp_path, "input.har", b"two")
    assert first != second
    assert (first / "input.har").read_bytes() == b"one"  # not overwritten
    assert first.name == hashlib.sha256(b"one").hexdigest()


def test_same_upload_twice_is_idempotent(tmp_path: Path) -> None:
    assert save_upload(tmp_path, "a.png", b"x" * 10) == save_upload(tmp_path, "a.png", b"x" * 10)


def test_upload_name_cannot_escape_the_folder(tmp_path: Path) -> None:
    folder = save_upload(tmp_path, "../../evil.html", b"<html></html>")
    assert [p.name for p in folder.iterdir()] == ["evil.html"]
    assert folder.parent == tmp_path / "uploads"
