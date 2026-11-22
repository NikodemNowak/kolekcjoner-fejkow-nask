"""Enrichment-local data shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CertListStatus(BaseModel):
    """CERT Polska list check for one campaign; `available=False` means "no answer", not 0."""

    available: bool
    reason: Literal["ok", "disabled", "fetch_failed"]
    known: int = 0  # registrable domains with at least one listed input domain
    new: int = 0  # registrable domains with no listed input domain
    listed: list[str] = []  # the input domains that matched, sorted
