import io
import json
import random
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from fakecollector.cli import app
from fakecollector.collect import runner
from fakecollector.collect.http import BlockedError, OfflineError, PoliteFetcher, host_allowed
from fakecollector.collect.parse import (
    article_images,
    find_brands,
    find_persons,
    is_scam_article,
    narrative,
    parse_feed,
    story_label,
)
from fakecollector.collect.runner import collect, parse_interval, watch
from fakecollector.collect.sources import Source, resolve
from fakecollector.core.schemas import Assignment, Evidence

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = Source(
    name="fixture",
    publisher="Fixture",
    feeds=("https://factcheck.example/feed/?paged={page}",),
    hosts=("factcheck.example",),
    paginated=True,
)


def _png(seed: int, size: int = 320) -> bytes:
    rng = random.Random(seed)
    image = Image.new("RGB", (size, size))
    image.putdata(
        [(rng.randrange(256), rng.randrange(256), rng.randrange(256))] * 0
        or [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(size * size)
        ]
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _site() -> dict[str, bytes]:
    return {
        "https://factcheck.example/robots.txt": b"User-agent: *\nDisallow: /private/\n",
        "https://factcheck.example/feed/?paged=1": (FIXTURES / "feed.xml").read_bytes(),
        "https://factcheck.example/uploads/ad1.png": _png(1),
        "https://factcheck.example/uploads/ad2.png": _png(2),
        "https://factcheck.example/uploads/icon.png": _png(3, size=40),
        "https://factcheck.example/uploads/politics.png": _png(4),
    }


class FakeOpener:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        url = request.full_url
        self.calls.append(url)
        if url not in self.pages:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)  # type: ignore[arg-type]
        return self.pages[url]


def _offline(request: urllib.request.Request, timeout: float) -> bytes:
    raise urllib.error.URLError(OSError("Name or service not known"))


def _assignment(decision: str, campaign: str | None) -> Assignment:
    evidence = Evidence(
        family="person",
        tier="campaign",
        kind="face.identity",
        value="0.9",
        detail="ta sama twarz",
        weight=0.9,
    )
    return Assignment(
        case_id="U:1",
        decision=decision,
        campaign_id=campaign,
        score=0.8,
        margin=0.3,
        comparable=["person"],
        evidence=[evidence, evidence],
    )


def test_parse_feed_reads_rss_items_with_content() -> None:
    entries = parse_feed((FIXTURES / "feed.xml").read_bytes(), "fixture")
    assert next(e.url for e in entries) == "https://factcheck.example/fake_news/brzoska-scam/"
    assert entries[0].published == datetime(2026, 11, 20, 10, tzinfo=UTC)
    assert "Brzosk" in entries[0].content_html
    assert parse_feed(b"<not xml", "x") == []


def test_article_images_keep_alt_caption_and_lazy_src() -> None:
    entry = parse_feed((FIXTURES / "feed.xml").read_bytes(), "fixture")[0]
    images = article_images(entry.content_html, entry.url)
    assert images[0].caption.startswith("Źródło: Facebook")
    assert images[1].url.endswith("ad2.png")  # data-src wins over a data: placeholder
    assert any("scam-landing" in i.url for i in images)  # parsed, but never fetched


def test_tagging_finds_persons_brands_and_story() -> None:
    text = "Fałszywy artykuł o zamachu na Rafała Brzoskę, InPost i Orlen. Autor: Przemysław Dudek"
    assert find_persons(text) == ["Rafał Brzoska"]
    assert find_brands(text) == ["InPost", "Orlen"]
    assert narrative("Cejrowski nie żyje? To scam") == "śmierć/tragedia"
    assert story_label("Zamach na Brzoskę", ["Rafał Brzoska"], []) == "zamach: Rafał Brzoska"
    assert is_scam_article("Uwaga na scam z Orlenem")
    assert not is_scam_article("Polityk nie powiedział tych słów", "zwykły tekst")


def test_fetcher_enforces_allowlist_robots_and_offline() -> None:
    assert host_allowed("https://cdn.factcheck.example/a.png", ("factcheck.example",))
    assert not host_allowed("https://factcheck.example.evil/a", ("factcheck.example",))
    assert not host_allowed("ftp://factcheck.example/a", ("factcheck.example",))
    opener = FakeOpener(_site())
    fetcher = PoliteFetcher(("factcheck.example",), min_interval=0, opener=opener)
    with pytest.raises(BlockedError):
        fetcher.get("https://scam-landing.example/banner.png")
    with pytest.raises(BlockedError):
        fetcher.get("https://factcheck.example/private/x")
    assert not any("scam-landing" in c for c in opener.calls)
    offline = PoliteFetcher(("factcheck.example",), min_interval=0, opener=_offline)
    with pytest.raises(OfflineError):
        offline.get("https://factcheck.example/feed/")


def test_collect_saves_case_folders_assigns_and_writes_last_json(tmp_path: Path) -> None:
    opener = FakeOpener(_site())
    calls: list[tuple[list[Path], bool]] = []

    def fake_assign(paths: list[Path], run_dir: Path, commit: bool) -> list[Assignment]:
        calls.append((paths, commit))
        return [_assignment("existing", "C1") if len(calls) == 1 else _assignment("new", None)]

    report = collect(
        [SOURCE],
        tmp_path,
        since=datetime(2026, 1, 1, tzinfo=UTC),
        fetcher_factory=lambda s: PoliteFetcher(s.hosts, min_interval=0, opener=opener),
        assign_fn=fake_assign,
    )
    assert report.articles_seen == 2  # the 2023 article is older than --since
    assert report.articles_matched == 1  # the political article is not about a scam
    assert [r.decision for r in report.items] == ["existing", "new"]
    assert report.items[0].campaign_id == "C1"
    assert report.items[0].evidence == ["ta sama twarz"]  # deduplicated
    assert report.items[0].item.story == "zamach: Rafał Brzoska"
    assert report.items[0].item.caption.startswith("Źródło")
    assert not any("scam-landing" in c for c in opener.calls)
    assert not any("icon.png" in r.item.image_url for r in report.items)
    folder = Path(report.items[0].case_dir)
    assert sorted(p.name for p in folder.iterdir()) == ["opis.txt", "zrzut.png"]
    last = json.loads((tmp_path / "collector" / "last.json").read_text(encoding="utf-8"))
    assert last["items"][1]["decision"] == "new"
    again = collect(
        [SOURCE],
        tmp_path,
        since=datetime(2026, 1, 1, tzinfo=UTC),
        fetcher_factory=lambda s: PoliteFetcher(s.hosts, min_interval=0, opener=opener),
        assign_fn=fake_assign,
    )
    assert again.items == []  # seen articles are not collected twice


def test_collect_offline_reports_clearly(tmp_path: Path) -> None:
    report = collect(
        [SOURCE],
        tmp_path,
        fetcher_factory=lambda s: PoliteFetcher(s.hosts, min_interval=0, opener=_offline),
        assign_fn=lambda *a: [],
    )
    assert report.offline
    assert "brak połączenia" in report.errors[0]
    assert (tmp_path / "collector" / "last.json").is_file()


def test_watch_and_interval() -> None:
    assert parse_interval("6h") == 6 * 3600
    assert parse_interval("30m") == 1800
    with pytest.raises(ValueError):
        parse_interval("soon")
    slept: list[float] = []
    stub = runner.CollectReport(started_at=datetime.now(UTC), sources=[], run_dir=".")
    reports = watch(lambda: stub, 10.0, iterations=3, sleep=slept.append)
    assert len(reports) == 3
    assert len(slept) == 2


def test_resolve_sources() -> None:
    assert [s.name for s in resolve("demagog,cert")] == ["demagog", "cert"]
    assert len(resolve("all")) >= 4
    with pytest.raises(KeyError):
        resolve("nope")


def test_cli_collect_rejects_non_run_and_unknown_source(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["collect", "--run", str(tmp_path), "--sources", "nope"])
    assert result.exit_code != 0
    result = CliRunner().invoke(app, ["collect", "--run", str(tmp_path), "--sources", "cert"])
    assert result.exit_code == 2


def test_cli_collect_offline_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "graph.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_default_fetcher",
        lambda s: PoliteFetcher(s.hosts, min_interval=0, opener=_offline),
    )
    result = CliRunner().invoke(app, ["collect", "--run", str(tmp_path), "--sources", "cert"])
    assert result.exit_code == 2, result.output
    assert "Brak połączenia" in result.output


def test_cli_watch_runs_given_iterations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "graph.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_default_fetcher",
        lambda s: PoliteFetcher(s.hosts, min_interval=0, opener=_offline),
    )
    result = CliRunner().invoke(
        app,
        [
            "watch",
            "--run",
            str(tmp_path),
            "--sources",
            "cert",
            "--every",
            "1s",
            "--iterations",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "collector" / "last.json").is_file()


def test_collect_assigns_against_a_real_run(tmp_path: Path) -> None:
    run = tmp_path / "run"
    built = CliRunner().invoke(app, ["demo", "--fixtures", "--out", str(run)])
    assert built.exit_code == 0, built.output
    opener = FakeOpener(_site())
    report = collect(
        [SOURCE],
        run,
        since=datetime(2026, 1, 1, tzinfo=UTC),
        commit=True,
        fetcher_factory=lambda s: PoliteFetcher(s.hosts, min_interval=0, opener=opener),
    )
    assert not report.errors
    assert len(report.items) == 2
    assert {r.decision for r in report.items} <= {"existing", "review", "new"}
    from fakecollector.store import RunStore

    assert len(RunStore(run).cases()) == 6 + 2  # committed into the run
