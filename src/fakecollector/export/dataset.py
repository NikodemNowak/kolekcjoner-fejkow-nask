"""Enriched structured dataset: one JSON Lines record per case + Parquet tables + schema.md.

The dataset is derived from organizer data and stays local: it is never committed or
published. It contains feature values and provenance, never the raw corpus files.
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Artifact, Case, Family, Feature, Tier
from fakecollector.export._common import campaign_by_case
from fakecollector.graph.analyze import Analysis
from fakecollector.graph.entities import entity_type_for
from fakecollector.ingest.normalize import display_text

SCHEMA_VERSION = 1
MAX_NEIGHBOURS = 10


class DatasetInputs(BaseModel):
    """Which input modalities the case had."""

    n_artifacts: int
    kinds: dict[str, int]
    roles: dict[str, int]
    pages: list[str]


class DatasetFeature(BaseModel):
    """One key or informational feature with its provenance."""

    name: str
    family: Family
    tier: Tier
    value: str
    truncated: bool = False
    confidence: float
    entity_id: str | None
    artifact_id: str
    artifact_path: str | None
    artifact_role: str | None
    locator: str


class DatasetEntity(BaseModel):
    """A graph entity the case links to."""

    id: str
    type: str
    value: str
    tier: Tier
    df: int
    stop: bool


class DatasetCampaign(BaseModel):
    """The campaign a case belongs to."""

    id: str
    label: str
    size: int
    cohesion: float
    flags: list[str]
    rotating: list[str]


class DatasetNeighbour(BaseModel):
    """A linked case, strongest first."""

    case_id: str
    score: float
    operator_link: bool
    families: list[Family]
    top_evidence: str


class DatasetRecord(BaseModel):
    """One case in the unified schema (one JSON Lines row)."""

    schema_version: int
    case_id: str
    corpus: str
    captured_at: str | None
    duplicate_of: str | None
    flags: list[str]
    inputs: DatasetInputs
    landing_urls: list[str]
    landing_domains: list[str]
    campaign: DatasetCampaign | None
    operator_id: str | None
    toolkits: list[str]
    features: list[DatasetFeature]
    similarity_features: list[str]
    entities: list[DatasetEntity]
    neighbours: list[DatasetNeighbour]


def _relative(artifact: Artifact, case: Case | None) -> str:
    """Path relative to the case folder, as UTF-8-safe display text.

    Undecodable file-name bytes survive ingest as surrogates (#24); they are replaced here so
    JSON/Parquet writers never fail, while the `Artifact.path` itself stays untouched.
    """
    rel = artifact.path.name
    if case is not None and case.path is not None:
        with contextlib.suppress(ValueError):
            rel = artifact.path.relative_to(case.path).as_posix()
    return display_text(rel)


def build_records(
    analysis: Analysis,
    features: Collection[Feature],
    cases: Collection[Case] | None = None,
    artifacts: Collection[Artifact] | None = None,
    *,
    max_value_chars: int = 4000,
) -> list[DatasetRecord]:
    """Build one record per case of the analysis, in case-id order."""
    case_info = {c.id: c for c in cases or ()}
    # Artifact ids are content hashes: identical bytes can appear in several cases, so the
    # lookup must include the case or provenance would point at another case's file.
    arts = {(a.case_id, a.id): a for a in artifacts or ()}
    arts_by_case: dict[str, list[Artifact]] = defaultdict(list)
    for artifact in artifacts or ():
        arts_by_case[artifact.case_id].append(artifact)
    by_case = campaign_by_case(analysis)
    entities = {e.id: e for e in analysis.entities}
    entity_ids: dict[str, set[str]] = defaultdict(set)
    for case_id, entity_id, _ in analysis.links:
        entity_ids[case_id].add(entity_id)
    feats: dict[str, list[DatasetFeature]] = defaultdict(list)
    similarity: dict[str, set[str]] = defaultdict(set)
    domains: dict[str, set[str]] = defaultdict(set)
    for f in sorted(features, key=lambda f: (f.case_id, f.name, f.value, f.artifact_id)):
        spec = FEATURES.get(f.name)
        if spec is None:
            continue
        if spec.kind in {"vector", "minhash"} or (not f.value and f.vector is not None):
            similarity[f.case_id].add(f.name)
            continue
        if not f.value:
            continue
        entity_type = entity_type_for(f.name, spec)
        feature_entity = f"{entity_type}:{f.value}" if entity_type and spec.kind != "info" else None
        source = arts.get((f.case_id, f.artifact_id))
        if f.name == "url.domain":
            domains[f.case_id].add(f.value)
        feats[f.case_id].append(
            DatasetFeature(
                name=f.name,
                family=spec.family,
                tier=spec.tier,
                value=f.value[:max_value_chars],
                truncated=len(f.value) > max_value_chars,
                confidence=f.confidence,
                entity_id=feature_entity if feature_entity in entities else None,
                artifact_id=f.artifact_id,
                artifact_path=_relative(source, case_info.get(f.case_id)) if source else None,
                artifact_role=source.role if source else None,
                locator=f.locator,
            )
        )
    neighbours: dict[str, list[DatasetNeighbour]] = defaultdict(list)
    for edge in sorted(analysis.edges, key=lambda e: (-e.score, e.src, e.dst)):
        detail = edge.evidence[0].detail if edge.evidence else ""
        families = sorted(edge.signals, key=lambda f: (-edge.signals[f], f))
        for here, there in ((edge.src, edge.dst), (edge.dst, edge.src)):
            if len(neighbours[here]) < MAX_NEIGHBOURS:
                neighbours[here].append(
                    DatasetNeighbour(
                        case_id=there,
                        score=round(edge.score, 4),
                        operator_link=edge.operator_link,
                        families=families,
                        top_evidence=detail,
                    )
                )

    records = []
    for case_id in analysis.case_ids:
        case = case_info.get(case_id)
        own = arts_by_case.get(case_id, [])
        campaign = by_case.get(case_id)
        records.append(
            DatasetRecord(
                schema_version=SCHEMA_VERSION,
                case_id=case_id,
                corpus=case.corpus if case else case_id.split(":", 1)[0],
                captured_at=case.captured_at.isoformat() if case and case.captured_at else None,
                duplicate_of=case.duplicate_of if case else None,
                flags=list(case.flags) if case else [],
                inputs=DatasetInputs(
                    n_artifacts=len(own),
                    kinds=dict(sorted(Counter(a.kind for a in own).items())),
                    roles=dict(sorted(Counter(a.role for a in own).items())),
                    pages=sorted({a.page for a in own if a.page}),
                ),
                landing_urls=list(case.landing_urls) if case else [],
                landing_domains=sorted(domains[case_id]),
                campaign=(
                    DatasetCampaign(
                        id=campaign.id,
                        label=campaign.label,
                        size=len(campaign.case_ids),
                        cohesion=round(campaign.cohesion, 4),
                        flags=campaign.flags,
                        rotating=[t.value for t in campaign.traits if t.kind == "rotating"],
                    )
                    if campaign
                    else None
                ),
                operator_id=analysis.operators.get(case_id),
                toolkits=analysis.toolkits.get(case_id, []),
                features=feats[case_id],
                similarity_features=sorted(similarity[case_id]),
                entities=[
                    DatasetEntity(**entities[e].model_dump())
                    for e in sorted(entity_ids[case_id])
                    if e in entities
                ],
                neighbours=neighbours[case_id],
            )
        )
    return records


def _parquet(path: Path, rows: Sequence[dict[str, Any]], schema: pa.Schema) -> None:
    pq.write_table(pa.Table.from_pylist(list(rows), schema=schema), path)


def _str_fields(*names: str) -> pa.Schema:
    return pa.schema([(name, pa.string()) for name in names])


SCHEMA_MD = """\
# Enriched case dataset (schema v{version})

> **Local only.** This dataset is derived from organizer (NASK) data: feature values, landing
> URLs and text excerpts come from the reported material. Do not commit, publish or share it
> outside the challenge. It never contains the raw corpus files themselves.

Files:

| File | Content |
|---|---|
| `cases.jsonl` | one JSON record per case (schema below; JSON Schema in `case.schema.json`) |
| `cases.parquet` | flat case table: id, corpus, campaign, operator, flags, input counts |
| `features.parquet` | every key/info feature with provenance (case, artifact, locator) |
| `entities.parquet` | graph entities: id, type, value, tier, document frequency, stop flag |
| `case_entities.parquet` | case-entity links with the artifact they were observed in |
| `edges.parquet` | case-case links: fused score, per-family scores, comparable families, evidence |
| `campaigns.parquet` | campaigns: label, members, operator, toolkits, cohesion, flags |
| `traits.parquet` | common-traits profile rows per campaign |

## `cases.jsonl` record

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | {version} |
| `case_id` | str | `<corpus>:<folder>` (uploads `U:<sha8>`) |
| `corpus` | str | corpus prefix |
| `captured_at` | ISO datetime / null | capture time when the input records one |
| `duplicate_of` | str / null | earlier byte-identical report |
| `flags` | list[str] | ingest flags (`cloaking_suspected`, `capture_error`, `video_only`, …) |
| `inputs` | object | `n_artifacts`, counts per artifact `kinds` and `roles`, capture `pages` |
| `landing_urls` | list[str] | canonical landing URLs (raw, not defanged) |
| `landing_domains` | list[str] | registrable landing domains (`url.domain`) |
| `campaign` | object / null | `id`, `label`, `size`, `cohesion`, `flags`, `rotating` |
| `operator_id` | str / null | operator group (shared rare operator-tier entity) |
| `toolkits` | list[str] | toolkit entity ids (kit SDK, URL schema, path signatures) |
| `features` | list[object] | key and informational features, see below |
| `similarity_features` | list[str] | vector / MinHash features of the case (values omitted) |
| `entities` | list[object] | linked entities: `id`, `type`, `value`, `tier`, `df`, `stop` |
| `neighbours` | list[object] | up to {neighbours} strongest links, see below |

`campaign.rotating` lists rotating traits, e.g. "5 domen". Each `neighbours[]` item has
`case_id`, `score`, `operator_link`, `families` (fired, strongest first) and `top_evidence`
(Polish).

### `features[]`

| Field | Meaning |
|---|---|
| `name` | registry key (`ids.kit_landing`, `asset.sha256`, `text.headline_tpl`, …) |
| `family`, `tier` | signal family and tier from the feature registry |
| `value` | the key value; text longer than {max_chars} characters is cut, `truncated` = true |
| `confidence` | extractor confidence 0..1 |
| `entity_id` | graph entity the feature became, if any |
| `artifact_id` | provenance: first 16 hex of the artifact's sha256 |
| `artifact_path`, `artifact_role` | path relative to the case folder, artifact role |
| `locator` | where inside the artifact (`entry[12].request.url`, `img#hero`, `t=14.0s`) |
"""


def export_dataset(
    analysis: Analysis,
    features: Collection[Feature],
    out_dir: Path,
    cases: Collection[Case] | None = None,
    artifacts: Collection[Artifact] | None = None,
    *,
    max_value_chars: int = 4000,
) -> list[Path]:
    """Write `cases.jsonl`, `case.schema.json`, Parquet tables and `schema.md`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    records = build_records(analysis, features, cases, artifacts, max_value_chars=max_value_chars)
    written = []
    jsonl = out_dir / "cases.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")
    written.append(jsonl)
    schema_json = out_dir / "case.schema.json"
    schema_json.write_text(
        json.dumps(DatasetRecord.model_json_schema(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    written.append(schema_json)
    schema_md = out_dir / "schema.md"
    schema_md.write_text(
        SCHEMA_MD.format(
            version=SCHEMA_VERSION, neighbours=MAX_NEIGHBOURS, max_chars=max_value_chars
        ),
        encoding="utf-8",
    )
    written.append(schema_md)

    tables: dict[str, tuple[list[dict[str, Any]], pa.Schema]] = {
        "cases": (
            [
                {
                    "case_id": r.case_id,
                    "corpus": r.corpus,
                    "captured_at": r.captured_at,
                    "duplicate_of": r.duplicate_of,
                    "flags": "|".join(r.flags),
                    "n_artifacts": str(r.inputs.n_artifacts),
                    "kinds": json.dumps(r.inputs.kinds),
                    "landing_urls": "|".join(r.landing_urls),
                    "landing_domains": "|".join(r.landing_domains),
                    "campaign_id": r.campaign.id if r.campaign else None,
                    "operator_id": r.operator_id,
                    "toolkits": "|".join(r.toolkits),
                }
                for r in records
            ],
            _str_fields(
                "case_id",
                "corpus",
                "captured_at",
                "duplicate_of",
                "flags",
                "n_artifacts",
                "kinds",
                "landing_urls",
                "landing_domains",
                "campaign_id",
                "operator_id",
                "toolkits",
            ),
        ),
        "features": (
            [
                {"case_id": r.case_id, **f.model_dump(exclude={"truncated", "confidence"})}
                for r in records
                for f in r.features
            ],
            _str_fields(
                "case_id",
                "name",
                "family",
                "tier",
                "value",
                "entity_id",
                "artifact_id",
                "artifact_path",
                "artifact_role",
                "locator",
            ),
        ),
        "entities": (
            [
                {**e.model_dump(exclude={"df", "stop"}), "df": e.df, "stop": e.stop}
                for e in analysis.entities
            ],
            pa.schema(
                [
                    ("id", pa.string()),
                    ("type", pa.string()),
                    ("value", pa.string()),
                    ("tier", pa.string()),
                    ("df", pa.int64()),
                    ("stop", pa.bool_()),
                ]
            ),
        ),
        "case_entities": (
            [{"case_id": c, "entity_id": e, "artifact_id": a} for c, e, a in analysis.links],
            _str_fields("case_id", "entity_id", "artifact_id"),
        ),
        "edges": (
            [
                {
                    "src": e.src,
                    "dst": e.dst,
                    "score": e.score,
                    "operator_link": e.operator_link,
                    "signals": json.dumps(e.signals, sort_keys=True),
                    "comparable": "|".join(e.comparable),
                    "evidence": json.dumps(
                        [item.model_dump() for item in e.evidence], ensure_ascii=False
                    ),
                }
                for e in analysis.edges
            ],
            pa.schema(
                [
                    ("src", pa.string()),
                    ("dst", pa.string()),
                    ("score", pa.float64()),
                    ("operator_link", pa.bool_()),
                    ("signals", pa.string()),
                    ("comparable", pa.string()),
                    ("evidence", pa.string()),
                ]
            ),
        ),
        "campaigns": (
            [
                {
                    "id": c.id,
                    "label": c.label,
                    "size": len(c.case_ids),
                    "case_ids": "|".join(c.case_ids),
                    "operator_id": c.operator_id,
                    "toolkits": "|".join(c.toolkits),
                    "cohesion": c.cohesion,
                    "flags": "|".join(c.flags),
                }
                for c in analysis.campaigns
            ],
            pa.schema(
                [
                    ("id", pa.string()),
                    ("label", pa.string()),
                    ("size", pa.int64()),
                    ("case_ids", pa.string()),
                    ("operator_id", pa.string()),
                    ("toolkits", pa.string()),
                    ("cohesion", pa.float64()),
                    ("flags", pa.string()),
                ]
            ),
        ),
        "traits": (
            [{"campaign_id": c.id, **t.model_dump()} for c in analysis.campaigns for t in c.traits],
            pa.schema(
                [
                    ("campaign_id", pa.string()),
                    ("entity_type", pa.string()),
                    ("value", pa.string()),
                    ("tier", pa.string()),
                    ("coverage", pa.float64()),
                    ("lift", pa.float64()),
                    ("kind", pa.string()),
                    ("why", pa.string()),
                ]
            ),
        ),
    }
    for name, (rows, schema) in tables.items():
        path = out_dir / f"{name}.parquet"
        _parquet(path, rows, schema)
        written.append(path)
    return written
