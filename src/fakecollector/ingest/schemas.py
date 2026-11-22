"""Ingest-local data shapes (HAR summaries); not part of the shared contract."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HarEntry(BaseModel):
    """One request/response pair from a HAR file."""

    url: str
    host: str
    method: str
    status: int
    ip: str | None = None
    mime: str = ""
    headers: dict[str, str] = {}  # response headers, lower-case names
    body_sha256: str | None = None
    body_size: int = 0
    redirect_to: str | None = None
    resource_type: str | None = None  # Chrome `_resourceType`: document, script, image, ...
    tls_issuer: str | None = None  # Playwright/Chrome `_securityDetails`, when present
    tls_san: list[str] = []


class HarSummary(BaseModel):
    """What ingest and extractors need from one HAR file."""

    creator: str
    started_at: datetime | None = None
    landing_url: str | None = None
    landing_status: int | None = None
    entries: list[HarEntry]
