"""Persistence helpers for pipeline runs and reusable extractor results."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import TypeAdapter, ValidationError

from fakecollector.core.schemas import Artifact, Campaign, Case, Edge, Entity, Feature
from fakecollector.graph.analyze import Analysis
from fakecollector.graph.cluster import operators, toolkits

logger = logging.getLogger(__name__)
_FEATURES = TypeAdapter(list[Feature])
_CASE_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("corpus", pa.string()),
        ("path", pa.string()),
        ("path_bytes", pa.binary()),
        ("landing_urls", pa.list_(pa.string())),
        ("captured_at", pa.string()),
        ("duplicate_of", pa.string()),
        ("flags", pa.list_(pa.string())),
    ]
)
_ARTIFACT_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("case_id", pa.string()),
        ("kind", pa.string()),
        ("role", pa.string()),
        ("path", pa.string()),
        ("path_bytes", pa.binary()),
        ("page", pa.string()),
        ("parent_id", pa.string()),
        ("size", pa.int64()),
        ("meta", pa.map_(pa.string(), pa.string())),
    ]
)


def _path_row(model: Case | Artifact) -> dict[str, object]:
    row: dict[str, object] = model.model_dump(mode="json")
    if model.path is not None:
        raw = os.fsencode(model.path)
        row["path"] = raw.decode("utf-8", errors="backslashreplace")
        row["path_bytes"] = raw
    else:
        row["path_bytes"] = None
    return row


def _restore_path(row: dict[str, object]) -> dict[str, object]:
    raw = row.get("path_bytes")
    if isinstance(raw, bytes):
        row["path"] = os.fsdecode(raw)
    return row


class RunStore:
    """Persist cases and artifacts in a run directory."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def invalidate_results(self) -> None:
        """Remove derived outputs before replacing the run's input cases."""
        for name in (
            "features.parquet",
            "entities.parquet",
            "case_entities.parquet",
            "edges.parquet",
            "campaigns.parquet",
            "graph.json",
            "campaigns.json",
            "report.html",
            "run.json",
        ):
            (self.run_dir / name).unlink(missing_ok=True)

    def write_cases(self, cases: list[Case], artifacts: list[Artifact]) -> None:
        """Replace the run's input tables with the supplied cases and artifacts."""
        case_table = pa.Table.from_pylist([_path_row(case) for case in cases], schema=_CASE_SCHEMA)
        artifact_table = pa.Table.from_pylist(
            [_path_row(artifact) for artifact in artifacts], schema=_ARTIFACT_SCHEMA
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(case_table, self.run_dir / "cases.parquet")
        pq.write_table(artifact_table, self.run_dir / "artifacts.parquet")

    def cases(self) -> list[Case]:
        """Read the run's cases, or return an empty list for a new run."""
        path = self.run_dir / "cases.parquet"
        if not path.exists():
            return []
        return [Case.model_validate(_restore_path(row)) for row in pq.read_table(path).to_pylist()]

    def artifacts(self, case_id: str | None = None) -> list[Artifact]:
        """Read all artifacts, optionally restricted to one case."""
        path = self.run_dir / "artifacts.parquet"
        if not path.exists():
            return []
        rows = pq.read_table(path).to_pylist()
        for row in rows:
            _restore_path(row)
            row["meta"] = dict(row["meta"])
        return [
            Artifact.model_validate(row)
            for row in rows
            if case_id is None or row["case_id"] == case_id
        ]

    def _feature_rows(self) -> list[dict[str, object]]:
        path = self.run_dir / "features.parquet"
        return list(pq.read_table(path).to_pylist()) if path.exists() else []

    def _vector_path(self, name: str) -> Path:
        key = hashlib.sha256(name.encode()).hexdigest()
        return self.run_dir / "vectors" / f"{key}.npy"

    def add_features(self, fs: list[Feature], extractor: str, version: int) -> None:
        """Replace the results of one extractor, keeping results from other extractors."""
        rows = self._feature_rows()
        previous = self.all_features()
        records = [
            (feature, str(row["extractor"]), int(str(row["version"])))
            for row, feature in zip(rows, previous, strict=True)
            if row["extractor"] != extractor
        ]
        records.extend((feature, extractor, version) for feature in fs)
        vectors: dict[str, list[list[float]]] = {}
        output: list[dict[str, object]] = []
        for feature, source, source_version in records:
            row = feature.model_dump(mode="json", exclude={"vector"})
            row.update(extractor=source, version=source_version, vector_index=None)
            if feature.vector is not None:
                group = vectors.setdefault(feature.name, [])
                row["vector_index"] = len(group)
                group.append(feature.vector)
            output.append(row)
        schema = pa.schema(
            [
                ("case_id", pa.string()),
                ("artifact_id", pa.string()),
                ("name", pa.string()),
                ("value", pa.string()),
                ("confidence", pa.float64()),
                ("locator", pa.string()),
                ("extractor", pa.string()),
                ("version", pa.int64()),
                ("vector_index", pa.int64()),
            ]
        )
        table = pa.Table.from_pylist(output, schema=schema)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        for name, values in vectors.items():
            path = self._vector_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, np.asarray(values, dtype=np.float64), allow_pickle=False)
        pq.write_table(table, self.run_dir / "features.parquet")

    def features(self, names: list[str] | None = None) -> list[Feature]:
        """Read scalar feature records, without loading their vectors."""
        return [
            Feature.model_validate(row)
            for row in self._feature_rows()
            if names is None or row["name"] in names
        ]

    def vectors(self, name: str) -> tuple[list[str], np.ndarray]:
        """Read case identifiers and vector rows for a feature name."""
        rows = [
            r for r in self._feature_rows() if r["name"] == name and r["vector_index"] is not None
        ]
        if not rows:
            return [], np.empty((0, 0), dtype=np.float64)
        array = np.load(self._vector_path(name), allow_pickle=False)
        return [str(row["case_id"]) for row in rows], array

    def all_features(self) -> list[Feature]:
        """Read all features, restoring vectors for graph computation."""
        arrays: dict[str, np.ndarray] = {}
        features = []
        for row in self._feature_rows():
            feature = Feature.model_validate(row)
            index = row["vector_index"]
            if index is not None:
                if feature.name not in arrays:
                    arrays[feature.name] = np.load(
                        self._vector_path(feature.name), allow_pickle=False
                    )
                feature.vector = arrays[feature.name][int(str(index))].tolist()
            features.append(feature)
        return features

    def features_from_extractor(self, name: str) -> list[Feature]:
        """Read features produced by one extractor, including their vectors."""
        return [
            feature
            for row, feature in zip(self._feature_rows(), self.all_features(), strict=True)
            if row["extractor"] == name
        ]

    def save_graph(
        self,
        entities: Analysis | list[Entity],
        links: list[tuple[str, str, str]] | None = None,
        edges: list[Edge] | None = None,
        campaigns: list[Campaign] | None = None,
    ) -> None:
        """Persist graph entities, links, edges, campaigns, and memberships."""
        if isinstance(entities, Analysis):
            graph = entities
        else:
            if links is None or edges is None or campaigns is None:
                raise ValueError("Graph links, edges and campaigns are required")
            case_ids = sorted(
                {case for campaign in campaigns for case in campaign.case_ids}
                | {case.id for case in self.cases()}
                | {case for case, _, _ in links}
            )
            graph = Analysis(
                case_ids=case_ids,
                entities=entities,
                links=links,
                edges=edges,
                campaigns=campaigns,
                operators=operators(case_ids, entities, links),
                toolkits=toolkits(case_ids, entities, links),
            )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        definitions = (
            (
                "entities",
                graph.entities,
                [
                    ("id", pa.string()),
                    ("type", pa.string()),
                    ("value", pa.string()),
                    ("tier", pa.string()),
                    ("df", pa.int64()),
                    ("stop", pa.bool_()),
                ],
            ),
            (
                "edges",
                graph.edges,
                [
                    ("src", pa.string()),
                    ("dst", pa.string()),
                    ("score", pa.float64()),
                    ("operator_link", pa.bool_()),
                ],
            ),
            (
                "campaigns",
                graph.campaigns,
                [
                    ("id", pa.string()),
                    ("operator_id", pa.string()),
                    ("label", pa.string()),
                    ("cohesion", pa.float64()),
                    ("case_ids", pa.list_(pa.string())),
                ],
            ),
        )
        for name, models, fields in definitions:
            schema = pa.schema([*fields, ("payload", pa.string())])
            rows = []
            for model in models:
                values = model.model_dump(mode="json")
                rows.append(
                    {**{key: values[key] for key, _ in fields}, "payload": model.model_dump_json()}
                )
            pq.write_table(
                pa.Table.from_pylist(rows, schema=schema), self.run_dir / f"{name}.parquet"
            )
        link_rows = [{"case_id": c, "entity_id": e, "artifact_id": a} for c, e, a in graph.links]
        schema = pa.schema([(key, pa.string()) for key in ("case_id", "entity_id", "artifact_id")])
        pq.write_table(
            pa.Table.from_pylist(link_rows, schema=schema), self.run_dir / "case_entities.parquet"
        )
        meta = graph.model_dump(mode="json", exclude={"entities", "links", "edges", "campaigns"})
        (self.run_dir / "graph.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

    def load_graph(self) -> Analysis:
        """Restore a previously persisted analysis."""
        meta = json.loads((self.run_dir / "graph.json").read_text(encoding="utf-8"))
        for name in ("entities", "edges", "campaigns"):
            meta[name] = [
                json.loads(row["payload"])
                for row in pq.read_table(self.run_dir / f"{name}.parquet").to_pylist()
            ]
        links = pq.read_table(self.run_dir / "case_entities.parquet").to_pylist()
        meta["links"] = [(r["case_id"], r["entity_id"], r["artifact_id"]) for r in links]
        return Analysis.model_validate(meta)


class FeatureCache:
    """Store results that depend only on artifact content and extractor version.

    Extractors whose outputs depend on prior features or case context need a
    broader key and must not use this cache until those inputs are included.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, sha256: str, extractor: str, version: int) -> Path:
        key = json.dumps([sha256, extractor, version], ensure_ascii=True).encode()
        digest = hashlib.sha256(key).hexdigest()
        return self.directory / digest[:2] / f"{digest}.json"

    def get(
        self, sha256: str, extractor: str, version: int, *, case_id: str, artifact_id: str
    ) -> list[Feature] | None:
        """Return cached features with provenance for the current artifact, or a miss."""
        path = self._path(sha256, extractor, version)
        try:
            features = _FEATURES.validate_json(path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError) as exc:
            logger.warning("Cannot read feature cache entry %s: %s", path, exc)
            return None
        return [
            feature.model_copy(update={"case_id": case_id, "artifact_id": artifact_id})
            for feature in features
        ]

    def put(self, sha256: str, extractor: str, version: int, features: list[Feature]) -> None:
        """Atomically save an extractor result, including an empty result."""
        path = self._path(sha256, extractor, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(_FEATURES.dump_json(features))
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
