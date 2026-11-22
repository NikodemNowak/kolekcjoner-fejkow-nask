from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import networkx as nx
import pyarrow.parquet as pq
import pytest

from fakecollector.core.schemas import Artifact, Case, Feature
from fakecollector.export import FORMATS, export_all
from fakecollector.export._common import defang
from fakecollector.export.dataset import DatasetRecord, export_dataset
from fakecollector.export.gexf import export_gexf, export_graphml
from fakecollector.export.ioc_csv import export_ioc_csv
from fakecollector.export.neo4j import export_neo4j
from fakecollector.graph.analyze import Analysis

from .conftest import MEMBERS


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _statements(script: str) -> list[str]:
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))
    return [s.strip() for s in code.split(";") if s.strip()]


def test_neo4j_cypher_is_balanced_and_references_exported_nodes(
    analysis: Analysis, features: list[Feature], cases: list[Case], tmp_path: Path
) -> None:
    written = export_neo4j(analysis, features, tmp_path, cases)
    script = (tmp_path / "import.cypher").read_text(encoding="utf-8")
    statements = _statements(script)
    assert len(statements) == 5 + len([p for p in written if p.suffix == ".csv"])
    for statement in statements:
        for opening, closing in ("()", "[]", "{}"):
            assert statement.count(opening) == statement.count(closing), statement
        assert statement.count("'") % 2 == 0, statement
    referenced = re.findall(r"file:///([\w.]+)", script)
    assert sorted(referenced) == sorted(p.name for p in written if p.suffix == ".csv")
    for label in ("Case", "Campaign", "Operator", "Toolkit", "Entity"):
        assert f"FOR (n:{label}) REQUIRE n.id IS UNIQUE" in script
    for rel in ("HAS", "SIMILAR", "MEMBER_OF", "RUN_BY", "USES"):
        assert f"[:{rel}]" in script or f"[r:{rel}]" in script
    assert script.count("// 1.") == 1 and "// 3." in script

    ids = {
        "Case": {r["id"] for r in _rows(tmp_path / "nodes_case.csv")},
        "Campaign": {r["id"] for r in _rows(tmp_path / "nodes_campaign.csv")},
        "Operator": {r["id"] for r in _rows(tmp_path / "nodes_operator.csv")},
        "Toolkit": {r["id"] for r in _rows(tmp_path / "nodes_toolkit.csv")},
        "Entity": {r["id"] for p in tmp_path.glob("nodes_entity_*.csv") for r in _rows(p)},
    }
    assert ids["Case"] == set(analysis.case_ids)
    assert "KitLanding:landing-1111" in ids["Entity"]
    # Every MATCH in a relationship statement must find its nodes in the node CSVs.
    for statement in statements:
        source = re.search(r"file:///(rels_[\w.]+)", statement)
        if source is None:
            continue
        rows = _rows(tmp_path / source.group(1))
        assert rows, source.group(1)
        for label, column in re.findall(r"\(\w+:(\w+) \{id: row\.(\w+)\}\)", statement):
            missing = {row[column] for row in rows} - ids[label]
            assert not missing, (source.group(1), label, missing)


def test_neo4j_similar_edges_carry_score_and_evidence(
    analysis: Analysis, features: list[Feature], tmp_path: Path
) -> None:
    export_neo4j(analysis, features, tmp_path)
    similar = _rows(tmp_path / "rels_similar.csv")
    assert {(r["src"], r["dst"]) for r in similar} >= {("F:a", "F:b")}
    row = next(r for r in similar if (r["src"], r["dst"]) == ("F:a", "F:b"))
    assert float(row["score"]) >= 0.6
    assert "landing-1111" in row["evidence"]
    has = _rows(tmp_path / "rels_has.csv")
    landing = next(r for r in has if r["case_id"] == "F:a" and r["entity_id"].startswith("Kit"))
    assert landing["locators"] == "entry[3].request.url"
    assert (tmp_path / "nodes_entity_KitSdk.csv").exists()  # no clash with the Toolkit label


@pytest.mark.parametrize("fmt", ["gexf", "graphml"])
def test_graph_files_load_back(analysis: Analysis, tmp_path: Path, fmt: str) -> None:
    path = (export_gexf if fmt == "gexf" else export_graphml)(analysis, tmp_path)
    graph = nx.read_gexf(path) if fmt == "gexf" else nx.read_graphml(path)
    shared = [e for e in analysis.entities if e.df >= 2]
    assert graph.number_of_nodes() == len(analysis.case_ids) + len(shared)
    node = graph.nodes["F:a"]
    assert node["kind"] == "Case"
    campaign = next(c for c in analysis.campaigns if "F:a" in c.case_ids)
    assert node["campaign"] == campaign.id
    assert node["colour"].startswith("#")
    assert graph.nodes["KitLanding:landing-1111"]["tier"] == "campaign"
    assert graph.nodes["KitLanding:landing-1111"]["family"] == "ids"
    kinds = {data["kind"] for *_, data in graph.edges(data=True)}
    assert kinds == {"HAS", "SIMILAR"}


def test_ioc_csv_defangs_and_lists_campaign_indicators(
    analysis: Analysis, cases: list[Case], tmp_path: Path
) -> None:
    rows = _rows(export_ioc_csv(analysis, tmp_path, cases))
    campaign = next(c for c in analysis.campaigns if set(MEMBERS) <= set(c.case_ids))
    mine = [r for r in rows if r["campaign_id"] == campaign.id]
    domain = next(r for r in mine if r["value"] == "example.com")
    assert domain["ioc_type"] == "domain"
    assert domain["value_defanged"] == "example[.]com"
    assert domain["for_warning_list"] == "true"
    url = next(r for r in mine if r["ioc_type"] == "url" and "example.com" in r["value"])
    assert url["value_defanged"] == "hxxps://example[.]com/article?id=1"
    types = {r["ioc_type"] for r in mine}
    assert {"tracker_id", "kit_landing_id", "hostname", "ip"} <= types
    pixel = next(r for r in mine if r["ioc_type"] == "tracker_id")
    assert pixel["value_defanged"] == pixel["value"] == "1111222233334444"
    assert pixel["case_count"] == "3"
    assert rows[0]["campaign_id"] == campaign.id  # largest campaign first


def test_defang() -> None:
    assert defang("example.com") == "example[.]com"
    assert defang("http://a.b.pl/x.js") == "hxxp://a[.]b[.]pl/x.js"
    assert defang("203.0.113.10") == "203[.]0[.]113[.]10"


def test_dataset_jsonl_validates_and_has_one_record_per_case(
    analysis: Analysis,
    features: list[Feature],
    cases: list[Case],
    artifacts: list[Artifact],
    tmp_path: Path,
) -> None:
    export_dataset(analysis, features, tmp_path, cases, artifacts)
    lines = (tmp_path / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    records = [DatasetRecord.model_validate_json(line) for line in lines]
    assert [r.case_id for r in records] == analysis.case_ids
    a = records[0]
    assert a.case_id == "F:a"
    assert a.landing_urls == ["https://example.com/article?id=1"]
    assert a.landing_domains == ["example.com"]
    assert a.inputs.kinds == {"har": 1}
    assert a.campaign is not None and a.campaign.rotating == ["3 domeny"]
    landing = next(f for f in a.features if f.name == "ids.kit_landing")
    assert landing.entity_id == "KitLanding:landing-1111"
    assert landing.artifact_path == "network.har"
    assert landing.locator == "entry[3].request.url"
    assert any(f.name == "html.title" and f.entity_id is None for f in a.features)
    assert a.neighbours and a.neighbours[0].case_id in MEMBERS
    schema = json.loads((tmp_path / "case.schema.json").read_text(encoding="utf-8"))
    assert set(schema["required"]) >= {"case_id", "features", "entities", "campaign"}
    assert "Local only" in (tmp_path / "schema.md").read_text(encoding="utf-8")
    assert pq.read_table(tmp_path / "cases.parquet").num_rows == len(analysis.case_ids)
    traits = pq.read_table(tmp_path / "traits.parquet").to_pylist()
    assert any(t["kind"] == "constant" and t["entity_type"] == "KitLanding" for t in traits)


def test_export_all_writes_every_format(
    analysis: Analysis,
    features: list[Feature],
    cases: list[Case],
    artifacts: list[Artifact],
    tmp_path: Path,
) -> None:
    written = export_all(analysis, features, tmp_path, FORMATS, cases, artifacts)
    assert list(written) == list(FORMATS)
    assert all(path.exists() for paths in written.values() for path in paths)
    with pytest.raises(ValueError, match="stix"):
        export_all(analysis, features, tmp_path, ["stix"])


def _same_bytes(artifacts: list[Artifact], name_a: str, name_b: str) -> list[Artifact]:
    """F:a and F:b share one artifact id (identical bytes) under different file names."""
    out = []
    for art in artifacts:
        if art.case_id in ("F:a", "F:b"):
            name = name_a if art.case_id == "F:a" else name_b
            art = art.model_copy(update={"id": "same-bytes", "path": art.path.parent / name})
        out.append(art)
    return out


def test_dataset_provenance_is_per_case_for_identical_bytes(
    analysis: Analysis,
    features: list[Feature],
    cases: list[Case],
    artifacts: list[Artifact],
    tmp_path: Path,
) -> None:
    arts = _same_bytes(artifacts, "first.har", "second.har")
    feats = [
        f.model_copy(update={"artifact_id": "same-bytes"}) if f.case_id in ("F:a", "F:b") else f
        for f in features
    ]
    export_dataset(analysis, feats, tmp_path, cases, arts)
    lines = (tmp_path / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    records = {r.case_id: r for r in map(DatasetRecord.model_validate_json, lines)}
    paths_a = {f.artifact_path for f in records["F:a"].features if f.artifact_id == "same-bytes"}
    paths_b = {f.artifact_path for f in records["F:b"].features if f.artifact_id == "same-bytes"}
    assert paths_a == {"first.har"}
    assert paths_b == {"second.har"}


def test_dataset_export_survives_undecodable_file_names(
    analysis: Analysis,
    features: list[Feature],
    cases: list[Case],
    artifacts: list[Artifact],
    tmp_path: Path,
) -> None:
    odd = os.fsdecode(b"sample-\xff.har")
    arts = [
        a.model_copy(update={"path": a.path.parent / odd}) if a.case_id == "F:a" else a
        for a in artifacts
    ]
    export_dataset(analysis, features, tmp_path, cases, arts)
    lines = (tmp_path / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    record = DatasetRecord.model_validate_json(lines[0])
    shown = {f.artifact_path for f in record.features if f.artifact_path}
    assert shown and all(p.startswith("sample-") and "\udcff" not in p for p in shown)
