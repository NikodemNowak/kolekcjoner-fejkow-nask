from __future__ import annotations

import pytest

from fakecollector.graph.config import EdgeConfig


@pytest.fixture
def cfg() -> EdgeConfig:
    return EdgeConfig()
