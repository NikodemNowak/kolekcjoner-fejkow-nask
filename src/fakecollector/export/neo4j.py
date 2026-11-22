"""Neo4j export: node/relationship CSVs plus an idempotent `import.cypher` (LOAD CSV + MERGE).

Copy the output directory into Neo4j's `import/` folder and run
`cypher-shell -f import.cypher` (or paste it into Neo4j Browser).
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from pathlib import Path

from fakecollector.core.schemas import Case, Feature
from fakecollector.export._common import campaign_by_case, provenance
from fakecollector.graph.analyze import Analysis
from fakecollector.graph.profile import rotating_summary

# Toolkit groups get the `Toolkit` label; the kit-SDK entity type must not collide with it.
_LABEL_RENAMES = {"Toolkit": "KitSdk"}

EXAMPLE_QUERIES = """\
// ---------------------------------------------------------------------------
// Example queries
// ---------------------------------------------------------------------------
// 1. A campaign's common-traits profile and its members:
//   MATCH (c:Case)-[:MEMBER_OF]->(k:Campaign)-[t:HAS_TRAIT]->(e:Entity)
//   WITH k, e, t, collect(DISTINCT c.id) AS cases
//   RETURN k.id, k.label, labels(e), e.value, t.coverage, t.lift, t.why, cases
//   ORDER BY k.size DESC, t.lift DESC LIMIT 50;
//
// 2. Pivot: every case that loads the same host / pixel / asset as a given case:
//   MATCH (a:Case {id: 'B:p1'})-[:HAS]->(e:Entity)<-[:HAS]-(b:Case)
//   WHERE NOT e.stop AND a <> b
//   RETURN e.type, e.value, e.tier, collect(DISTINCT b.id) AS other_cases
//   ORDER BY size(other_cases) DESC;
//
// 3. Operators behind more than one campaign, with the shared operator-tier entities:
//   MATCH (k:Campaign)-[:RUN_BY]->(o:Operator)
//   WITH o, collect(k) AS campaigns WHERE size(campaigns) > 1
//   MATCH (c:Case)-[:RUN_BY]->(o), (c)-[:HAS]->(e:Entity {tier: 'operator'})
//   WHERE NOT e.stop
//   RETURN o.id, [k IN campaigns | k.label] AS campaigns, collect(DISTINCT e.id) AS shared;
"""


def neo4j_label(entity_type: str) -> str:
    """Return a safe Neo4j label for an entity type."""
    label = _LABEL_RENAMES.get(entity_type, entity_type)
    return re.sub(r"[^A-Za-z0-9_]", "_", label) or "Unknown"


def _write(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            count += 1
    return count


def _list(values: Iterable[str]) -> str:
    return "|".join(values)


def _split(field: str) -> str:
    return f"[x IN split(coalesce(row.{field}, ''), '|') WHERE x <> '']"


def export_neo4j(
    analysis: Analysis,
    features: Collection[Feature],
    out_dir: Path,
    cases: Collection[Case] | None = None,
) -> list[Path]:
    """Write `nodes_*.csv`, `rels_*.csv` and `import.cypher`; return the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in [*out_dir.glob("nodes_*.csv"), *out_dir.glob("rels_*.csv")]:
        stale.unlink()
    by_case = campaign_by_case(analysis)
    case_info = {case.id: case for case in cases or ()}
    linked = {entity_id for _, entity_id, _ in analysis.links}
    entities = [e for e in analysis.entities if e.id in linked]
    prov = provenance(features)
    written: list[Path] = []
    statements: list[str] = []

    def emit(name: str, header: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
        path = out_dir / name
        _write(path, header, rows)
        written.append(path)

    def load(name: str, body: str) -> None:
        statements.append(f"LOAD CSV WITH HEADERS FROM 'file:///{name}' AS row\n{body};")

    # Nodes: cases, campaigns, operators, toolkits.
    emit(
        "nodes_case.csv",
        ["id", "corpus", "landing_urls", "flags", "duplicate_of", "campaign_id", "operator_id"],
        (
            [
                case_id,
                case_info[case_id].corpus if case_id in case_info else case_id.split(":")[0],
                _list(case_info[case_id].landing_urls) if case_id in case_info else "",
                _list(case_info[case_id].flags) if case_id in case_info else "",
                case_info[case_id].duplicate_of if case_id in case_info else "",
                by_case[case_id].id if case_id in by_case else "",
                analysis.operators.get(case_id, ""),
            ]
            for case_id in analysis.case_ids
        ),
    )
    load(
        "nodes_case.csv",
        "MERGE (n:Case {id: row.id})\n"
        "SET n.corpus = row.corpus, n.landing_urls = "
        + _split("landing_urls")
        + ",\n    n.flags = "
        + _split("flags")
        + ", n.duplicate_of = row.duplicate_of",
    )
    emit(
        "nodes_campaign.csv",
        ["id", "label", "size", "cohesion", "flags", "operator_id", "toolkits", "rotating"],
        (
            [
                c.id,
                c.label,
                len(c.case_ids),
                round(c.cohesion, 4),
                _list(c.flags),
                c.operator_id or "",
                _list(c.toolkits),
                rotating_summary(c.traits),
            ]
            for c in analysis.campaigns
        ),
    )
    load(
        "nodes_campaign.csv",
        "MERGE (n:Campaign {id: row.id})\n"
        "SET n.label = row.label, n.size = toInteger(row.size), "
        "n.cohesion = toFloat(row.cohesion),\n    n.flags = "
        + _split("flags")
        + ", n.rotating = row.rotating",
    )
    op_cases: dict[str, list[str]] = defaultdict(list)
    for case_id, operator_id in sorted(analysis.operators.items()):
        op_cases[operator_id].append(case_id)
    op_campaigns: dict[str, set[str]] = defaultdict(set)
    for operator_id, members in op_cases.items():
        op_campaigns[operator_id].update(by_case[c].id for c in members if c in by_case)
    emit(
        "nodes_operator.csv",
        ["id", "size", "campaigns"],
        ([o, len(m), len(op_campaigns[o])] for o, m in sorted(op_cases.items())),
    )
    load(
        "nodes_operator.csv",
        "MERGE (n:Operator {id: row.id})\n"
        "SET n.size = toInteger(row.size), n.campaigns = toInteger(row.campaigns)",
    )
    tk_cases: dict[str, list[str]] = defaultdict(list)
    for case_id, toolkit_ids in sorted(analysis.toolkits.items()):
        for toolkit_id in toolkit_ids:
            tk_cases[toolkit_id].append(case_id)
    by_entity = {e.id: e for e in analysis.entities}
    emit(
        "nodes_toolkit.csv",
        ["id", "entity_type", "value", "size"],
        (
            [
                t,
                by_entity[t].type if t in by_entity else "",
                by_entity[t].value if t in by_entity else t,
                len(m),
            ]
            for t, m in sorted(tk_cases.items())
        ),
    )
    load(
        "nodes_toolkit.csv",
        "MERGE (n:Toolkit {id: row.id})\n"
        "SET n.entity_type = row.entity_type, n.value = row.value, n.size = toInteger(row.size)",
    )

    # Entity nodes: one file per type, because LOAD CSV cannot set a label from a column.
    by_type: dict[str, list[list[object]]] = defaultdict(list)
    for e in entities:
        by_type[e.type].append([e.id, e.type, e.value, e.tier, e.df, str(e.stop).lower()])
    for entity_type, rows in sorted(by_type.items()):
        label = neo4j_label(entity_type)
        name = f"nodes_entity_{label}.csv"
        emit(name, ["id", "type", "value", "tier", "df", "stop"], rows)
        load(
            name,
            f"MERGE (n:Entity {{id: row.id}})\nSET n:{label}, n.type = row.type, "
            "n.value = row.value, n.tier = row.tier,\n"
            "    n.df = toInteger(row.df), n.stop = row.stop = 'true'",
        )

    # Relationships.
    has: dict[tuple[str, str], set[str]] = defaultdict(set)
    for case_id, entity_id, artifact_id in analysis.links:
        has[case_id, entity_id].add(artifact_id)
    emit(
        "rels_has.csv",
        ["case_id", "entity_id", "features", "artifacts", "locators"],
        (
            [
                case_id,
                entity_id,
                _list(sorted({p.feature for p in prov.get((case_id, entity_id), [])})),
                _list(sorted(artifacts)),
                _list(p.locator for p in prov.get((case_id, entity_id), []) if p.locator),
            ]
            for (case_id, entity_id), artifacts in sorted(has.items())
        ),
    )
    load(
        "rels_has.csv",
        "MATCH (c:Case {id: row.case_id}), (e:Entity {id: row.entity_id})\n"
        "MERGE (c)-[r:HAS]->(e)\n"
        "SET r.features = "
        + _split("features")
        + ", r.artifacts = "
        + _split("artifacts")
        + ",\n    r.locators = "
        + _split("locators"),
    )
    emit(
        "rels_similar.csv",
        [
            "src",
            "dst",
            "score",
            "operator_link",
            "signals",
            "comparable",
            "evidence",
            "evidence_json",
        ],
        (
            [
                edge.src,
                edge.dst,
                round(edge.score, 4),
                str(edge.operator_link).lower(),
                json.dumps(edge.signals, sort_keys=True),
                _list(edge.comparable),
                " | ".join(item.detail for item in edge.evidence),
                json.dumps([item.model_dump() for item in edge.evidence], ensure_ascii=False),
            ]
            for edge in analysis.edges
        ),
    )
    load(
        "rels_similar.csv",
        "MATCH (a:Case {id: row.src}), (b:Case {id: row.dst})\n"
        "MERGE (a)-[r:SIMILAR]->(b)\n"
        "SET r.score = toFloat(row.score), r.operator_link = row.operator_link = 'true',\n"
        "    r.signals = row.signals, r.comparable = " + _split("comparable") + ",\n"
        "    r.evidence = row.evidence, r.evidence_json = row.evidence_json",
    )
    emit(
        "rels_member_of.csv",
        ["case_id", "campaign_id"],
        ([case_id, c.id] for c in analysis.campaigns for case_id in c.case_ids),
    )
    load(
        "rels_member_of.csv",
        "MATCH (c:Case {id: row.case_id}), (k:Campaign {id: row.campaign_id})\n"
        "MERGE (c)-[:MEMBER_OF]->(k)",
    )
    emit(
        "rels_run_by_campaign.csv",
        ["campaign_id", "operator_id"],
        ([c.id, c.operator_id] for c in analysis.campaigns if c.operator_id),
    )
    load(
        "rels_run_by_campaign.csv",
        "MATCH (k:Campaign {id: row.campaign_id}), (o:Operator {id: row.operator_id})\n"
        "MERGE (k)-[:RUN_BY]->(o)",
    )
    emit(
        "rels_run_by_case.csv",
        ["case_id", "operator_id"],
        sorted(analysis.operators.items()),
    )
    load(
        "rels_run_by_case.csv",
        "MATCH (c:Case {id: row.case_id}), (o:Operator {id: row.operator_id})\n"
        "MERGE (c)-[:RUN_BY]->(o)",
    )
    emit(
        "rels_uses_case.csv",
        ["case_id", "toolkit_id"],
        ([case_id, t] for case_id, ts in sorted(analysis.toolkits.items()) for t in ts),
    )
    load(
        "rels_uses_case.csv",
        "MATCH (c:Case {id: row.case_id}), (t:Toolkit {id: row.toolkit_id})\n"
        "MERGE (c)-[:USES]->(t)",
    )
    emit(
        "rels_uses_campaign.csv",
        ["campaign_id", "toolkit_id"],
        ([c.id, t] for c in analysis.campaigns for t in c.toolkits),
    )
    load(
        "rels_uses_campaign.csv",
        "MATCH (k:Campaign {id: row.campaign_id}), (t:Toolkit {id: row.toolkit_id})\n"
        "MERGE (k)-[:USES]->(t)",
    )
    emit(
        "rels_has_trait.csv",
        ["campaign_id", "entity_id", "coverage", "lift", "why"],
        (
            [c.id, f"{t.entity_type}:{t.value}", t.coverage, t.lift, t.why]
            for c in analysis.campaigns
            for t in c.traits
            if t.kind == "constant" and f"{t.entity_type}:{t.value}" in linked
        ),
    )
    load(
        "rels_has_trait.csv",
        "MATCH (k:Campaign {id: row.campaign_id}), (e:Entity {id: row.entity_id})\n"
        "MERGE (k)-[r:HAS_TRAIT]->(e)\n"
        "SET r.coverage = toFloat(row.coverage), r.lift = toFloat(row.lift), r.why = row.why",
    )

    constraints = [
        f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.id IS UNIQUE;"
        for label in ("Case", "Campaign", "Operator", "Toolkit", "Entity")
    ]
    script = "\n\n".join(
        [
            "// Kolekcjoner Fejków: Neo4j import (LOAD CSV + MERGE, safe to re-run).\n"
            "// Copy every CSV in this folder into Neo4j's import/ directory first.",
            *constraints,
            *statements,
        ]
    )
    cypher = out_dir / "import.cypher"
    cypher.write_text(script + "\n\n" + EXAMPLE_QUERIES, encoding="utf-8")
    written.append(cypher)
    return written
