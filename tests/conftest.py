from __future__ import annotations

import importlib.util

import pytest

# Heavy model extractors live behind the optional `ml` extra; CI installs only the base set.
_HAS_ML = all(importlib.util.find_spec(m) is not None for m in ("torch", "cv2"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "gpu: needs model weights or a GPU; skipped in CI")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _HAS_ML:
        return
    skip = pytest.mark.skip(reason="ml extra not installed (uv sync --extra ml)")
    for item in items:
        if "gpu" in item.keywords:
            item.add_marker(skip)


# Test modules that import the `ml` extra at module level are not collected without it.
collect_ignore = (
    []
    if importlib.util.find_spec("cv2")
    else ["extractors/test_face.py", "extractors/test_video.py"]
)
