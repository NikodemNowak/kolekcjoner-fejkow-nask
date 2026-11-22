"""Tests for the Workstream B feature cache and pipeline helpers (fake extractor, no models)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.dev.run_b import (
    FeatureCache,
    RunResult,
    cache_version,
    resolve_stages,
    run_extractor,
    write_run,
)


class FakeExtractor(BaseExtractor):
    """Emits one key feature and one vector feature per image; counts real computations."""

    name = "fake"
    version = 1

    def __init__(self) -> None:
        self.calls = 0

    def supports(self, artifact: Artifact) -> bool:
        return artifact.kind == "image"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        self.calls += 1
        return [
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="img.phash",
                value=f"h{artifact.id}",
                locator="x",
            ),
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="img.siglip",
                value="",
                vector=[0.5, 0.25, -1.0],
            ),
        ]


def _art(aid: str, case: str = "T:1", kind: str = "image") -> Artifact:
    return Artifact(
        id=aid, case_id=case, kind=kind, role="screenshot", path=Path(f"/x/{aid}.png"), size=1
    )


def test_cache_roundtrip_keeps_vectors(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    feats = FakeExtractor().extract(_art("a1"), [])
    assert cache.get("a1", "fake", "1") is None
    cache.put("a1", "fake", "1", feats)
    got = cache.get("a1", "fake", "1")
    assert got is not None
    assert [f.value for f in got] == [f.value for f in feats]
    assert got[1].vector == pytest.approx([0.5, 0.25, -1.0])
    assert got[0].vector is None
    assert (cache.hits, cache.misses) == (1, 1)
    # No pickle anywhere: the vector file loads with allow_pickle=False.
    npy = next(tmp_path.rglob("*.npy"))
    assert np.load(npy, allow_pickle=False).shape == (1, 3)


def test_empty_result_is_cached(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    cache.put("a1", "fake", "1", [])
    assert cache.get("a1", "fake", "1") == []


def test_run_extractor_hit_and_miss(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    arts = [_art("a1"), _art("a2"), _art("v1", kind="video")]
    ext = FakeExtractor()
    feats, stats = run_extractor(ext, arts, cache)
    assert ext.calls == 2 and stats.computed == 2 and stats.cached == 0
    assert len(feats) == 4

    ext2 = FakeExtractor()
    feats2, stats2 = run_extractor(ext2, [*arts, _art("a3")], cache)
    assert ext2.calls == 1  # only the new artifact is computed
    assert (stats2.cached, stats2.computed) == (2, 1)
    assert [f.model_dump() for f in feats2[:4]] == [f.model_dump() for f in feats]


def test_version_bump_invalidates(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    run_extractor(FakeExtractor(), [_art("a1")], cache)
    bumped = FakeExtractor()
    bumped.version = 2
    _, stats = run_extractor(bumped, [_art("a1")], cache)
    assert bumped.calls == 1 and stats.cached == 0
    _, stats = run_extractor(FakeExtractor(), [_art("a1")], cache, version="1")
    assert stats.cached == 1  # the old version's entry is still there


def test_reference_fingerprint_changes_version(tmp_path: Path) -> None:
    ref = tmp_path / "db.npz"
    ref.write_bytes(b"one")
    v1 = cache_version(FakeExtractor(), [ref])
    ref.write_bytes(b"two")
    assert cache_version(FakeExtractor(), [ref]) != v1
    assert cache_version(FakeExtractor()) == "1"


def test_same_bytes_in_two_cases_computed_once(tmp_path: Path) -> None:
    ext = FakeExtractor()
    feats, stats = run_extractor(
        ext, [_art("a1", "T:1"), _art("a1", "T:2")], FeatureCache(tmp_path)
    )
    assert ext.calls == 1 and stats.unique == 1
    assert sorted({f.case_id for f in feats}) == ["T:1", "T:2"]


def test_no_cache_always_computes() -> None:
    ext = FakeExtractor()
    run_extractor(ext, [_art("a1")], None)
    run_extractor(ext, [_art("a1")], None)
    assert ext.calls == 2


def test_broken_entry_is_a_miss(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    cache.put("a1", "fake", "1", [])
    next(tmp_path.rglob("*.json")).write_text("{not json")
    assert cache.get("a1", "fake", "1") is None


def test_resolve_stages() -> None:
    assert resolve_stages("face,image_hash") == ["image_hash", "face"]
    assert resolve_stages("siglip") == ["image_siglip"]
    assert len(resolve_stages("")) == 6
    with pytest.raises(ValueError):
        resolve_stages("nope")


def test_write_run_layout(tmp_path: Path) -> None:
    arts = [_art("a1"), _art("a2", "T:2")]
    feats = [f for a in arts for f in FakeExtractor().extract(a, [])]
    write_run(RunResult(artifacts=arts, features=feats), tmp_path, {"device": "cpu"})
    assert pq.read_table(tmp_path / "artifacts.parquet").num_rows == 2
    fdf = pq.read_table(tmp_path / "features.parquet")
    assert fdf.num_rows == 4 and "vector" not in fdf.column_names
    vecs = np.load(tmp_path / "vectors" / "img.siglip.npy")
    idx = pq.read_table(tmp_path / "vectors" / "img.siglip.index.parquet")
    assert vecs.shape == (2, 3) and idx.column("case_id").to_pylist() == ["T:1", "T:2"]
    run = json.loads((tmp_path / "run.json").read_text())
    assert run["counts"]["vectors"] == {"img.siglip": 2}
