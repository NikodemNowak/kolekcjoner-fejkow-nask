"""Vector-based candidate pairs for embedding features.

Groups vectors by dimension and returns mutual nearest-neighbour pairs and best matches
using blockwise dot products.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterator, Mapping

import numpy as np
from numpy.typing import NDArray

from fakecollector.core.registry import FEATURES, FeatureSpec
from fakecollector.core.schemas import Feature
from fakecollector.graph.config import EdgeConfig

type CasePair = tuple[str, str]
type Vector = NDArray[np.float64]
type VectorRow = tuple[Feature, Vector]


def _by_dimension(features: Collection[Feature]) -> dict[int, list[VectorRow]]:
    groups: dict[int, list[VectorRow]] = defaultdict(list)
    for feature in features:
        if not feature.vector:
            continue
        vector = np.asarray(feature.vector, dtype=np.float64)
        scale = np.max(np.abs(vector))
        if scale == 0 or not np.isfinite(scale):
            continue
        vector /= scale
        groups[len(vector)].append((feature, vector / np.linalg.norm(vector)))
    for rows in groups.values():
        rows.sort(
            key=lambda row: (row[0].case_id, row[0].artifact_id, row[0].locator, row[0].vector)
        )
    return groups


def vector_candidate_pairs(
    features: Collection[Feature],
    cfg: EdgeConfig,
    registry: Mapping[str, FeatureSpec] = FEATURES,
    *,
    case_id: str | None = None,
) -> set[CasePair]:
    """Find mutual cross-case neighbours independently for each embedding space."""
    if cfg.knn_k <= 0:
        return set()
    by_name: dict[str, list[Feature]] = defaultdict(list)
    for feature in features:
        spec = registry.get(feature.name)
        if spec is not None and spec.kind == "vector":
            by_name[feature.name].append(feature)

    pairs: set[CasePair] = set()
    for group in by_name.values():
        for rows in _by_dimension(group).values():
            if case_id is not None and all(feature.case_id != case_id for feature, _ in rows):
                continue
            pairs.update(_mutual_pairs(rows, cfg.knn_k, case_id))
    return pairs


def _mutual_pairs(rows: list[VectorRow], k: int, case_id: str | None) -> set[CasePair]:
    ids = [feature.case_id for feature, _ in rows]
    if len(set(ids)) < 2:
        return set()
    matrix = np.stack([vector for _, vector in rows])
    _, cases = np.unique(ids, return_inverse=True)
    k = min(k, len(rows) - 1)
    neighbours: list[set[int]] = []
    for start, scores in _score_blocks(matrix, matrix):
        scores[cases[start : start + len(scores), None] == cases] = -np.inf
        top = np.argpartition(scores, -k, axis=1)[:, -k:]
        neighbours.extend(
            {int(i) for i in indices if np.isfinite(row[i])}
            for row, indices in zip(scores, top, strict=True)
        )
    return {
        (ids[i], ids[j])
        for i, nearby in enumerate(neighbours)
        for j in nearby
        if i < j and i in neighbours[j] and (case_id is None or case_id in (ids[i], ids[j]))
    }


def best_vector_match(
    a: Collection[Feature], b: Collection[Feature]
) -> tuple[float, list[Feature]] | None:
    """Return the best cross-artifact cosine for one embedding feature."""
    left, right = _by_dimension(a), _by_dimension(b)
    best = -float("inf")
    matched: list[Feature] = []
    for dimension in sorted(left.keys() & right.keys()):
        left_rows, right_rows = left[dimension], right[dimension]
        left_matrix = np.stack([vector for _, vector in left_rows])
        right_matrix = np.stack([vector for _, vector in right_rows])
        for start, scores in _score_blocks(left_matrix, right_matrix):
            similarity = float(scores.max())
            if similarity < best:
                continue
            if similarity > best:
                best = similarity
                matched.clear()
            ties = scores == best
            matched.extend(left_rows[start + i][0] for i in np.flatnonzero(ties.any(axis=1)))
            matched.extend(right_rows[i][0] for i in np.flatnonzero(ties.any(axis=0)))
    return (max(-1.0, min(1.0, best)), matched) if matched else None


def _score_blocks(left: Vector, right: Vector) -> Iterator[tuple[int, Vector]]:
    # Blocking rows of the exact product keeps the similarity matrix out of memory.
    for start in range(0, len(left), 256):
        yield start, left[start : start + 256] @ right.T
