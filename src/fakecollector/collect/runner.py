"""Collector passes: discover new publisher articles, save their ad images, assign them."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from fakecollector.collect.http import BlockedError, OfflineError, PoliteFetcher, host_allowed
from fakecollector.collect.models import (
    CollectedItem,
    CollectReport,
    FeedEntry,
    ItemResult,
)
from fakecollector.collect.parse import (
    article_images,
    article_text,
    find_brands,
    find_persons,
    is_scam_article,
    parse_feed,
    story_label,
)
from fakecollector.collect.sources import Source
from fakecollector.core.schemas import Assignment

logger = logging.getLogger(__name__)

MIN_IMAGE_BYTES = 12_000  # icons, avatars and share buttons are smaller
MIN_IMAGE_SIDE = 200
_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}

FetcherFactory = Callable[[Source], PoliteFetcher]
AssignFn = Callable[[list[Path], Path, bool], list[Assignment]]


def collector_dir(run_dir: Path) -> Path:
    """Where a run keeps collected cases, the seen-article list and reports."""
    return run_dir / "collector"


def _default_fetcher(source: Source) -> PoliteFetcher:
    return PoliteFetcher(source.hosts)


def _default_assign(paths: list[Path], run_dir: Path, commit: bool) -> list[Assignment]:
    from fakecollector.pipeline import assign_new
    from fakecollector.store import RunStore

    return assign_new([str(p) for p in paths], RunStore(run_dir), commit=commit)


def discover(
    source: Source, fetcher: PoliteFetcher, since: datetime | None, max_pages: int
) -> list[FeedEntry]:
    """List feed entries published at or after `since`, walking paginated feeds."""
    entries: list[FeedEntry] = []
    for feed in source.feeds:
        pages = max_pages if source.paginated else 1
        for page in range(1, pages + 1):
            url = feed.format(page=page)
            try:
                batch = parse_feed(fetcher.get(url), source.name)
            except OfflineError:
                raise
            except Exception as exc:  # a missing page ends pagination
                logger.info("%s: feed page %s unavailable (%s)", source.name, page, exc)
                break
            if not batch:
                break
            fresh = [
                e for e in batch if since is None or e.published is None or e.published >= since
            ]
            entries.extend(fresh)
            if len(fresh) < len(batch):
                break
    unique: dict[str, FeedEntry] = {}
    for entry in entries:
        unique.setdefault(entry.url, entry)
    return list(unique.values())


def _body_html(entry: FeedEntry, source: Source, fetcher: PoliteFetcher) -> str:
    """The article body: from the feed when it carries it, otherwise from the article page."""
    if len(article_text(entry.content_html)) > 3000:
        return entry.content_html
    try:
        page = fetcher.get(entry.url).decode("utf-8", "replace")
    except OfflineError:
        raise
    except Exception as exc:  # the feed excerpt is better than nothing
        logger.info("article page unavailable %s: %s", entry.url, exc)
        return entry.content_html
    soup = BeautifulSoup(page, "lxml")
    for selector in source.content_selectors:
        nodes = soup.select(selector)
        if nodes:
            return "".join(str(node) for node in nodes)
    return entry.content_html  # unknown layout: never fall back to sidebars and related posts


def _image_ok(data: bytes) -> str | None:
    """Return the file suffix of a usable raster image, None for icons and non-images."""
    if len(data) < MIN_IMAGE_BYTES:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            if min(image.size) < MIN_IMAGE_SIDE:
                return None
            return _EXT.get(image.format or "")
    except Exception:
        return None


def harvest(
    entry: FeedEntry, source: Source, fetcher: PoliteFetcher, max_images: int = 6
) -> list[tuple[CollectedItem, bytes, str]]:
    """Return (item, image bytes, suffix) for each ad image in a scam-related article.

    Images hosted outside the publisher (embeds, scam sites) are skipped, never fetched.
    """
    # Feeds often carry only an excerpt: decide on title + excerpt before fetching the page,
    # so the collector does not download every political fact-check.
    if not is_scam_article(entry.title, article_text(entry.content_html)):
        return []
    html = _body_html(entry, source, fetcher)
    text = article_text(html)
    persons = find_persons(f"{entry.title} {text}")
    brands = find_brands(f"{entry.title} {text}")
    lead_brands = find_brands(entry.title) or brands
    story = story_label(entry.title, find_persons(entry.title) or persons, lead_brands, text)
    key = hashlib.sha1(entry.url.encode()).hexdigest()[:8]
    out: list[tuple[CollectedItem, bytes, str]] = []
    for index, image in enumerate(article_images(html, entry.url)):
        if len(out) >= max_images:
            break
        if not host_allowed(image.url, source.hosts):
            logger.info("skip off-publisher image host %s", urlsplit(image.url).hostname)
            continue
        try:
            data = fetcher.get(image.url)
        except (BlockedError, OSError, ValueError) as exc:
            logger.info("image skipped %s: %s", image.url, exc)
            continue
        suffix = _image_ok(data)
        if suffix is None:
            continue
        context = f"{image.alt} {image.caption}"
        item = CollectedItem(
            id=f"{source.name}-{key}-{index:02d}",
            source=source.name,
            publisher=source.publisher,
            article_url=entry.url,
            article_title=entry.title,
            published=entry.published,
            image_url=image.url,
            alt=image.alt,
            caption=image.caption,
            persons=find_persons(context) or persons,
            brands=find_brands(context) or brands,
            story=story,
        )
        out.append((item, data, suffix))
    return out


def materialize(item: CollectedItem, data: bytes, suffix: str, inbox: Path) -> Path:
    """Write one item as a case folder: the image plus a caption text file."""
    folder = inbox / item.id
    folder.mkdir(parents=True, exist_ok=True)
    image = folder / f"zrzut{suffix}"
    image.write_bytes(data)
    lines = [item.article_title, item.alt, item.caption]
    (folder / "opis.txt").write_text(
        "\n".join(line for line in lines if line) + "\n", encoding="utf-8"
    )
    item.image_file = str(image)
    return folder


def _load_seen(path: Path) -> set[str]:
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def collect(
    sources: Sequence[Source],
    run_dir: Path,
    *,
    since: datetime | None = None,
    commit: bool = False,
    max_pages: int = 3,
    assign: bool = True,
    fetcher_factory: FetcherFactory | None = None,
    assign_fn: AssignFn | None = None,
) -> CollectReport:
    """Run one collector pass and write `<run>/collector/last.json`."""
    fetcher_factory = fetcher_factory or _default_fetcher
    assign_fn = assign_fn or _default_assign
    base = collector_dir(run_dir)
    inbox = base / "inbox"
    seen_path = base / "seen.json"
    seen = _load_seen(seen_path)
    report = CollectReport(
        started_at=datetime.now(UTC),
        sources=[s.name for s in sources],
        since=since,
        run_dir=str(run_dir),
        committed=commit,
    )
    for source in sources:
        fetcher = fetcher_factory(source)
        try:
            entries = discover(source, fetcher, since, max_pages)
        except OfflineError as exc:
            report.offline = True
            report.errors.append(f"{source.name}: brak połączenia z siecią ({exc})")
            continue
        except BlockedError as exc:
            report.errors.append(f"{source.name}: {exc}")
            continue
        report.articles_seen += len(entries)
        for entry in entries:
            if entry.url in seen:
                continue
            try:
                harvested = harvest(entry, source, fetcher)
            except OfflineError as exc:
                report.offline = True
                report.errors.append(f"{source.name}: brak połączenia z siecią ({exc})")
                break
            except Exception as exc:
                report.errors.append(f"{entry.url}: {exc}")
                continue
            seen.add(entry.url)
            if harvested:
                report.articles_matched += 1
            for item, data, suffix in harvested:
                folder = materialize(item, data, suffix, inbox)
                result = ItemResult(item=item, case_dir=str(folder), decision="new")
                if assign:
                    try:
                        verdicts = assign_fn([folder], run_dir, commit)
                    except Exception as exc:
                        report.errors.append(f"{item.id}: assign failed ({exc})")
                        verdicts = []
                    if verdicts:
                        best = verdicts[0]
                        result.decision = best.decision
                        result.campaign_id = best.campaign_id
                        result.score = round(best.score, 3)
                        result.margin = round(best.margin, 3)
                        result.evidence = list(dict.fromkeys(e.detail for e in best.evidence))
                report.items.append(result)
    report.finished_at = datetime.now(UTC)
    base.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(sorted(seen), indent=0), encoding="utf-8")
    payload = report.model_dump_json(indent=2)
    (base / "last.json").write_text(payload, encoding="utf-8")
    history = base / "history"
    history.mkdir(exist_ok=True)
    stamp = report.started_at.strftime("%Y%m%dT%H%M%SZ")
    (history / f"{stamp}.json").write_text(payload, encoding="utf-8")
    with (base / "items.jsonl").open("a", encoding="utf-8") as log:
        for result in report.items:
            log.write(result.item.model_dump_json() + "\n")
    return report


def parse_interval(value: str) -> float:
    """Parse "6h", "30m", "1d" or "45s" into seconds."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*", value.lower())
    if not match:
        raise ValueError(f"invalid interval: {value!r}")
    unit = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    seconds = float(match.group(1)) * unit
    if seconds <= 0:
        raise ValueError("interval must be positive")
    return seconds


def watch(
    run_once: Callable[[], CollectReport],
    every: float,
    *,
    iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[CollectReport]:
    """Call `run_once` every `every` seconds; `iterations=None` runs until interrupted."""
    reports: list[CollectReport] = []
    count = 0
    while iterations is None or count < iterations:
        started = time.monotonic()
        reports.append(run_once())
        count += 1
        if iterations is not None and count >= iterations:
            break
        sleep(max(0.0, every - (time.monotonic() - started)))
    return reports
