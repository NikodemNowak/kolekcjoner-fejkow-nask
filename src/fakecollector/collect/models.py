"""Data shapes of the collector (items found in public sources and the per-run report)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FeedEntry(BaseModel):
    """One article listed by a source feed."""

    source: str
    url: str
    title: str
    published: datetime | None = None
    content_html: str = ""  # full body when the feed carries it (WordPress content:encoded)


class ArticleImage(BaseModel):
    """An image embedded in a publisher article, with its textual context."""

    url: str
    alt: str = ""
    caption: str = ""


class CollectedItem(BaseModel):
    """One ad screenshot taken from a publisher article, saved as a case folder."""

    id: str
    source: str
    publisher: str
    article_url: str
    article_title: str
    published: datetime | None = None
    image_url: str
    image_file: str = ""
    alt: str = ""
    caption: str = ""
    persons: list[str] = []
    brands: list[str] = []
    story: str = ""


class ItemResult(BaseModel):
    """The assignment verdict for one collected item."""

    item: CollectedItem
    case_dir: str
    decision: str  # existing | review | new
    campaign_id: str | None = None
    score: float = 0.0
    margin: float = 0.0
    evidence: list[str] = []


class CollectReport(BaseModel):
    """What one collector pass found (written to `<run>/collector/last.json`)."""

    started_at: datetime
    finished_at: datetime | None = None
    sources: list[str]
    since: datetime | None = None
    run_dir: str
    committed: bool = False
    offline: bool = False
    articles_seen: int = 0
    articles_matched: int = 0
    items: list[ItemResult] = []
    errors: list[str] = []

    def counts(self) -> dict[str, int]:
        """Return how many items got each decision."""
        out = {"existing": 0, "review": 0, "new": 0}
        for result in self.items:
            out[result.decision] = out.get(result.decision, 0) + 1
        return out
