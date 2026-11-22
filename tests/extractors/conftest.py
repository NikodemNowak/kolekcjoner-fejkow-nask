from pathlib import Path

import pytest

from fakecollector.core.schemas import Artifact
from fakecollector.ingest.casefolder import load_corpus

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "cases"


@pytest.fixture(scope="session")
def fixture_artifacts() -> list[Artifact]:
    return load_corpus(FIXTURES, "F")[1]
