from streamlit.testing.v1 import AppTest

from fakecollector.app import pl
from fakecollector.cli import APP_FILE


def test_app_starts_and_shows_title() -> None:
    at = AppTest.from_file(str(APP_FILE)).run(timeout=30)
    assert not at.exception
    assert at.title[0].value == pl.TITLE
