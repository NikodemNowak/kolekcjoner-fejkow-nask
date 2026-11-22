import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fakecollector.cli import app


def test_help_lists_app_command() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "app" in result.output


def test_demo_writes_a_reopenable_run_and_report(tmp_path: Path) -> None:
    out = tmp_path / "demo"
    result = CliRunner().invoke(app, ["demo", "--fixtures", "--out", str(out)])
    assert result.exit_code == 0, result.output
    from fakecollector.store import RunStore

    store = RunStore(out)
    assert len(store.cases()) == 6
    graph = store.load_graph()
    assert sorted(graph.case_ids) == sorted(case.id for case in store.cases())
    assert (out / "report.html").is_file()
    assert (out / "run.json").is_file()
    second = tmp_path / "second"
    repeated = CliRunner().invoke(app, ["demo", "--fixtures", "--out", str(second)])
    assert repeated.exit_code == 0, repeated.output
    assert (out / "campaigns.parquet").read_bytes() == (second / "campaigns.parquet").read_bytes()
    exported = CliRunner().invoke(app, ["export", str(out), "--format", "gexf"])
    assert exported.exit_code == 0, exported.output
    import networkx as nx

    graph_file = out / "export" / "gexf" / "graph.gexf"
    assert nx.read_gexf(graph_file).number_of_nodes() >= len(store.cases())
    for fmt in ("dataset", "neo4j", "graphml", "ioc-csv", "json"):
        result = CliRunner().invoke(app, ["export", str(out), "--format", fmt])
        assert result.exit_code == 0, (fmt, result.output, result.exception)
    dataset = out / "export" / "dataset" / "cases.jsonl"
    neo4j = out / "export" / "neo4j"
    assert len(dataset.read_text().splitlines()) == len(store.cases())
    assert (neo4j / "import.cypher").is_file()
    records = [json.loads(line) for line in dataset.read_text().splitlines()]
    assert any(record["entities"] for record in records)
    with (neo4j / "nodes_case.csv").open(newline="") as source:
        case_ids = {row["id"] for row in csv.DictReader(source)}
    entity_ids = set()
    for path in neo4j.glob("nodes_entity_*.csv"):
        with path.open(newline="") as source:
            entity_ids.update(row["id"] for row in csv.DictReader(source))
    with (neo4j / "rels_has.csv").open(newline="") as source:
        assert all(
            row["case_id"] in case_ids and row["entity_id"] in entity_ids
            for row in csv.DictReader(source)
        )
    graphml = out / "export" / "graphml" / "graph.graphml"
    assert nx.read_graphml(graphml).number_of_nodes() >= len(store.cases())
    assigned = CliRunner().invoke(
        app, ["assign", "https://unseen.example.invalid/", "--against", str(out)]
    )
    assert assigned.exit_code == 0, assigned.output
    assert (out / "assignments.csv").is_file()
    assert (out / "assignments.html").is_file()
