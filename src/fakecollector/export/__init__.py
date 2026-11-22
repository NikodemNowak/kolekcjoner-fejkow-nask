"""Exports of an analysed run: Neo4j, GEXF/GraphML, IOC CSV and the enriched dataset."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from pathlib import Path

from fakecollector.core.schemas import Artifact, Case, Feature
from fakecollector.export.dataset import export_dataset
from fakecollector.export.gexf import export_gexf, export_graphml
from fakecollector.export.ioc_csv import export_ioc_csv
from fakecollector.export.neo4j import export_neo4j
from fakecollector.graph.analyze import Analysis

FORMATS = ("neo4j", "gexf", "graphml", "ioc-csv", "dataset")

__all__ = [
    "FORMATS",
    "export_all",
    "export_dataset",
    "export_gexf",
    "export_graphml",
    "export_ioc_csv",
    "export_neo4j",
]


def export_all(
    analysis: Analysis,
    features: Collection[Feature],
    out_dir: Path,
    formats: Iterable[str] = FORMATS,
    cases: Collection[Case] | None = None,
    artifacts: Collection[Artifact] | None = None,
) -> dict[str, list[Path]]:
    """Run the selected exporters into `out_dir/<format>/`; call `fill_traits` first.

    Raises:
        ValueError: An unknown format name.
    """
    wanted = list(dict.fromkeys(formats))
    if unknown := [f for f in wanted if f not in FORMATS]:
        raise ValueError(f"Unknown export format(s): {', '.join(unknown)}; use {FORMATS}")
    written: dict[str, list[Path]] = {}
    for name in wanted:
        target = out_dir / name
        if name == "neo4j":
            written[name] = export_neo4j(analysis, features, target, cases)
        elif name == "gexf":
            written[name] = [export_gexf(analysis, target)]
        elif name == "graphml":
            written[name] = [export_graphml(analysis, target)]
        elif name == "ioc-csv":
            written[name] = [export_ioc_csv(analysis, target, cases)]
        else:
            written[name] = export_dataset(analysis, features, target, cases, artifacts)
    return written
