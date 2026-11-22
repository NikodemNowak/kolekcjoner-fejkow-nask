"""Command-line entry point (`fakecollector`); pipeline commands are added per the plan."""

from __future__ import annotations

import csv
import html as html_lib
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Annotated

import typer

from fakecollector.app import pl
from fakecollector.config import get_settings
from fakecollector.export import export_all
from fakecollector.graph.config import EdgeConfig
from fakecollector.pipeline import analyze, assign_new, default_extractors, extract, ingest
from fakecollector.report.build import build_report
from fakecollector.store import FeatureCache, RunStore

app = typer.Typer(name="fakecollector", help="Kolekcjoner Fejków: scam-ad campaign linking.")

APP_FILE = Path(__file__).parent / "app" / "streamlit_app.py"


@app.callback()
def main() -> None:
    """Group scam-ad cases into campaigns, operators and toolkits."""


def _run(paths: list[Path], out: Path, profile: str, seed: int) -> None:
    store = RunStore(out)
    timings: dict[str, float] = {}
    start = perf_counter()
    ingest(paths, store)
    timings["ingest"] = perf_counter() - start
    start = perf_counter()
    extract(
        store,
        "full" if profile == "full" else "fast",
        cache=FeatureCache(get_settings().feature_cache),
    )
    timings["extract"] = perf_counter() - start
    start = perf_counter()
    graph = analyze(store, EdgeConfig(seed=seed))
    timings["analyze"] = perf_counter() - start
    start = perf_counter()
    build_report(store)
    timings["report"] = perf_counter() - start
    packages = {}
    for package in ("fakecollector", "pydantic", "duckdb", "pyarrow", "networkx"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            continue
    meta = {
        "profile": profile,
        "seed": seed,
        "config": get_settings().model_dump(mode="json"),
        "versions": packages,
        "extractors": {x.name: x.version for x in default_extractors()},
        "timings_seconds": timings,
        "counts": {
            "cases": len(store.cases()),
            "artifacts": len(store.artifacts()),
            "features": len(store.features()),
            "campaigns": len(graph.campaigns),
        },
    }
    (out / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


@app.command("run")
def run_command(
    paths: Annotated[list[Path], typer.Argument(help="Case folders or files.")],
    out: Annotated[Path, typer.Option(help="Run directory.")],
    profile: Annotated[str, typer.Option(help="Extraction profile: fast or full.")] = "fast",
    seed: Annotated[int, typer.Option(help="Deterministic seed.")] = 0,
) -> None:
    """Ingest, extract, analyze and report on input cases."""
    if profile not in {"fast", "full"}:
        raise typer.BadParameter("Choose fast or full", param_hint="--profile")
    _run(paths, out, profile, seed)


@app.command("demo")
def demo(
    fixtures: Annotated[bool, typer.Option(help="Use synthetic fixtures.")] = False,
    out: Annotated[Path, typer.Option(help="Run directory.")] = Path("runs/demo"),
) -> None:
    """Run the pipeline on the synthetic fixture corpus."""
    path = Path("data/fixtures/cases")
    if not path.is_dir():
        raise typer.BadParameter("Synthetic fixtures are unavailable")
    _run([path], out, "fast", 0)


@app.command("ingest")
def ingest_command(
    paths: Annotated[list[Path], typer.Argument(help="Case folders or files.")],
    out: Annotated[Path, typer.Option(help="Run directory.")],
) -> None:
    """Read input cases into a run directory."""
    ingest(paths, RunStore(out))


@app.command("extract")
def extract_command(
    run_dir: Path,
    profile: Annotated[str, typer.Option(help="Extraction profile: fast or full.")] = "fast",
) -> None:
    """Extract features into an existing run directory."""
    if profile not in {"fast", "full"}:
        raise typer.BadParameter("Choose fast or full", param_hint="--profile")
    extract(
        RunStore(run_dir),
        "full" if profile == "full" else "fast",
        cache=FeatureCache(get_settings().feature_cache),
    )


@app.command("analyze")
def analyze_command(run_dir: Path, seed: int = 0) -> None:
    """Build campaigns and evidence from extracted features."""
    analyze(RunStore(run_dir), EdgeConfig(seed=seed))


@app.command("report")
def report_command(run_dir: Path, html: bool = True) -> None:
    """Write the self-contained HTML report."""
    if html:
        build_report(RunStore(run_dir))


@app.command("assign")
def assign_command(
    inputs: Annotated[list[str], typer.Argument(help="New files, folders, or URLs.")],
    against: Annotated[Path, typer.Option(help="Existing run directory.")],
    commit: Annotated[bool, typer.Option(help="Add the inputs to the run.")] = False,
) -> None:
    """Assign new inputs against existing campaigns without fetching URLs."""
    assignments = assign_new(inputs, RunStore(against), commit=commit)
    with (against / "assignments.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["case_id", "decision", "campaign_id", "score", "margin"])
        for item in assignments:
            writer.writerow(
                [item.case_id, item.decision, item.campaign_id or "", item.score, item.margin]
            )
    lines = ['<!doctype html><html lang="pl"><meta charset="utf-8"><body><ul>']
    for item in assignments:
        evidence = "; ".join(e.detail.replace(".", "[.]") for e in item.evidence)
        decision = html_lib.escape(pl.ASSIGNMENT_DECISIONS[item.decision])
        lines.append(
            f"<li>{html_lib.escape(item.case_id)}: {decision} "
            f"{html_lib.escape(item.campaign_id or '')} {html_lib.escape(evidence)}</li>"
        )
    lines.append("</ul></body></html>")
    (against / "assignments.html").write_text("".join(lines), encoding="utf-8")


def _collect_once(
    sources: str, run: Path, since: str | None, commit: bool, max_pages: int, assign: bool
) -> int:
    """Run one collector pass, print a summary and return the exit code."""
    from datetime import UTC, datetime

    from fakecollector.collect.runner import collect, collector_dir
    from fakecollector.collect.sources import resolve

    try:
        chosen = resolve(sources)
    except KeyError as exc:
        raise typer.BadParameter(f"Unknown source: {exc}", param_hint="--sources") from exc
    start = None
    if since:
        try:
            start = datetime.fromisoformat(since).replace(tzinfo=UTC)
        except ValueError as exc:
            raise typer.BadParameter("Use YYYY-MM-DD", param_hint="--since") from exc
    if assign and not (run / "graph.json").exists() and not (run / "campaigns.json").exists():
        raise typer.BadParameter(f"{run} is not a run directory", param_hint="--run")
    report = collect(chosen, run, since=start, commit=commit, max_pages=max_pages, assign=assign)
    counts = report.counts()
    typer.echo(
        f"Artykuły: {report.articles_seen} (o oszustwach: {report.articles_matched}); "
        f"materiały: {len(report.items)}; warianty znanych kampanii: {counts['existing']}; "
        f"do przeglądu: {counts['review']}; nowe: {counts['new']}"
    )
    for result in report.items:
        target = result.campaign_id or "-"
        typer.echo(
            f"  {result.item.id}\t{result.decision}\t{target}\t{result.score:.2f}\t"
            f"{result.item.story}"
        )
    for error in report.errors:
        typer.echo(f"  ! {error}", err=True)
    typer.echo(f"Raport: {collector_dir(run) / 'last.json'}")
    if report.offline and not report.items:
        typer.echo("Brak połączenia z siecią: kolektor nic nie pobrał.", err=True)
        return 2
    return 0


@app.command("collect")
def collect_command(
    run: Annotated[Path, typer.Option(help="Run directory to assign against.")],
    sources: Annotated[str, typer.Option(help="Comma-separated sources or 'all'.")] = "all",
    since: Annotated[str | None, typer.Option(help="Only articles from this date.")] = None,
    commit: Annotated[bool, typer.Option(help="Add collected material to the run.")] = False,
    max_pages: Annotated[int, typer.Option(help="Feed pages per source.")] = 3,
    assign: Annotated[bool, typer.Option(help="Assign each item to campaigns.")] = True,
) -> None:
    """Fetch new scam-ad material from public fact-checking sources and assign it."""
    raise typer.Exit(_collect_once(sources, run, since, commit, max_pages, assign))


@app.command("watch")
def watch_command(
    run: Annotated[Path, typer.Option(help="Run directory to assign against.")],
    every: Annotated[str, typer.Option(help="Interval, e.g. 6h, 30m, 1d.")] = "6h",
    sources: Annotated[str, typer.Option(help="Comma-separated sources or 'all'.")] = "all",
    since: Annotated[str | None, typer.Option(help="Only articles from this date.")] = None,
    commit: Annotated[bool, typer.Option(help="Add collected material to the run.")] = False,
    max_pages: Annotated[int, typer.Option(help="Feed pages per source.")] = 3,
    iterations: Annotated[int | None, typer.Option(help="Stop after N passes.")] = None,
) -> None:
    """Run the collector periodically (simple loop; stop with Ctrl+C)."""
    from fakecollector.collect.models import CollectReport
    from fakecollector.collect.runner import parse_interval, watch

    try:
        seconds = parse_interval(every)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--every") from exc

    def once() -> CollectReport:
        _collect_once(sources, run, since, commit, max_pages, True)
        from fakecollector.collect.runner import collector_dir

        return CollectReport.model_validate_json(
            (collector_dir(run) / "last.json").read_text(encoding="utf-8")
        )

    try:
        watch(once, seconds, iterations=iterations)
    except KeyboardInterrupt:
        typer.echo("Zatrzymano.")


@app.command("export")
def export_command(
    run_dir: Path,
    format_name: Annotated[str, typer.Option("--format", help="Export format.")] = "json",
) -> None:
    """Export a graph or dataset to the run's export directory."""
    if format_name not in {"dataset", "neo4j", "gexf", "graphml", "ioc-csv", "json"}:
        raise typer.BadParameter("Unsupported export format", param_hint="--format")
    store = RunStore(run_dir)
    if format_name == "json":
        path = run_dir / "export" / "graph.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(store.load_graph().model_dump_json(indent=2), encoding="utf-8")
    else:
        export_all(
            store.load_graph(),
            store.all_features(),
            run_dir / "export",
            [format_name],
            store.cases(),
            store.artifacts(),
        )


@app.command("app")
def run_app(
    run_dir: Annotated[Path | None, typer.Argument(help="Run directory to open.")] = None,
    port: Annotated[int, typer.Option(help="Streamlit port.")] = 8501,
) -> None:
    """Start the Streamlit analyst app."""
    cmd = [sys.executable, "-m", "streamlit", "run", str(APP_FILE), "--server.port", str(port)]
    if run_dir is not None:
        cmd += ["--", "--run", str(run_dir)]
    raise typer.Exit(subprocess.call(cmd))  # fixed argv, no shell
