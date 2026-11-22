"""Public sources the collector knows: fact-checkers and CERT-type publishers with RSS feeds."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    """A publisher feed and the hosts the collector may fetch for it.

    `feeds` may contain `{page}` for paginated WordPress feeds (`?paged=N`).
    """

    name: str
    publisher: str
    feeds: tuple[str, ...]
    hosts: tuple[str, ...]  # registrable hosts of the publisher; images elsewhere are skipped
    content_selectors: tuple[str, ...] = (".entry-content", "article", "main")
    paginated: bool = False
    extra: dict[str, str] = field(default_factory=dict)


SOURCES: dict[str, Source] = {
    source.name: source
    for source in (
        Source(
            name="demagog",
            publisher="Demagog",
            feeds=("https://demagog.org.pl/fake_news/feed/?paged={page}",),
            hosts=("demagog.org.pl",),
            # The body only: the cover collage and "related articles" thumbnails sit outside.
            content_selectors=(".dg-post-content__inner",),
            paginated=True,
        ),
        Source(
            name="fakenews",
            publisher="FakeNews.pl",
            feeds=("https://fakenews.pl/feed/?paged={page}",),
            hosts=("fakenews.pl",),
            content_selectors=(".post-content",),
            paginated=True,
        ),
        Source(
            name="cert",
            publisher="CERT Polska",
            feeds=("https://cert.pl/rss.xml",),
            hosts=("cert.pl",),
        ),
        Source(
            name="niebezpiecznik",
            publisher="Niebezpiecznik",
            feeds=("https://niebezpiecznik.pl/feed/",),
            hosts=("niebezpiecznik.pl",),
            content_selectors=(".entry", "article"),
        ),
    )
}


def resolve(names: str | list[str]) -> list[Source]:
    """Return sources by comma-separated name; unknown names raise `KeyError`."""
    items = names.split(",") if isinstance(names, str) else names
    wanted = [n.strip().lower() for n in items if n.strip()]
    if not wanted or wanted == ["all"]:
        return list(SOURCES.values())
    missing = [n for n in wanted if n not in SOURCES]
    if missing:
        raise KeyError(", ".join(missing))
    return [SOURCES[n] for n in wanted]
