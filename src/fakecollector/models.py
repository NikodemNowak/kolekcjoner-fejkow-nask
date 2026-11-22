"""Device selection and shared model helpers. Heavy models load lazily, once."""

from __future__ import annotations

import logging
import os
from functools import cache

logger = logging.getLogger(__name__)


@cache
def device() -> str:
    """Return "cuda" or "cpu" from FAKECOLLECTOR_DEVICE (auto|cpu|cuda)."""
    wanted = os.environ.get("FAKECOLLECTOR_DEVICE", "auto")
    if wanted == "cpu":
        return "cpu"
    try:
        import torch

        ok = bool(torch.cuda.is_available())
    except ImportError:
        ok = False
    if wanted == "cuda" and not ok:
        logger.warning("CUDA requested but not available; using CPU")
    return "cuda" if ok else "cpu"
