"""Candidate pair generation for similarity comparison.

Uses exact image-hash buckets, fuzzy text matching and MinHash LSH so that only
plausible case pairs are scored.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from itertools import combinations

from datasketch import MinHash, MinHashLSH

from fakecollector.core.registry import FEATURES, FeatureSpec
from fakecollector.core.schemas import Entity, Feature
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import EntityLink
from fakecollector.graph.vectors import CasePair as CasePair
from fakecollector.graph.vectors import vector_candidate_pairs

logger = logging.getLogger(__name__)

PHASH = "img.phash"
PDQ = "img.pdq"
IMAGE_HASH_BITS = {PHASH: 64, PDQ: 256}


def image_hash_value(feature: Feature) -> int | None:
    """Decode a fixed-width perceptual hash, preserving its width by feature name."""
    bits = IMAGE_HASH_BITS.get(feature.name)
    if (
        bits is None
        or len(feature.value) * 4 != bits
        or not re.fullmatch(r"[0-9a-fA-F]+", feature.value)
    ):
        logger.debug("Invalid %s hash on artifact %s", feature.name, feature.artifact_id)
        return None
    return int(feature.value, 16)


def hash_distance(a: int, b: int) -> int:
    """Count differing bits between two decoded hashes of the same format."""
    return (a ^ b).bit_count()


def _hash_candidate_pairs(
    features: Collection[Feature],
    registry: Mapping[str, FeatureSpec],
    bucket_limit: float,
    case_id: str | None,
) -> set[CasePair]:
    bands: dict[tuple[str, int, int], dict[str, set[int]]] = {}
    max_distances = {
        name: int(bits * (1 - spec.lo))
        for name, bits in IMAGE_HASH_BITS.items()
        if (spec := registry.get(name)) is not None and spec.kind == "hash" and spec.lo is not None
    }
    pdq_cases = {feature.case_id for feature in features if feature.name == PDQ}
    for feature in features:
        name = feature.name
        if name not in max_distances or (value := image_hash_value(feature)) is None:
            continue
        # With D + 1 disjoint bands, D bit flips leave at least one band unchanged.
        count = max_distances[name] + 1
        width, extra = divmod(IMAGE_HASH_BITS[name], count)
        offset = 0
        for band in range(count):
            band_width = width + (band < extra)
            band_value = (value >> offset) & ((1 << band_width) - 1)
            bucket = bands.setdefault((name, band, band_value), {})
            bucket.setdefault(feature.case_id, set()).add(value)
            offset += band_width

    pairs: set[CasePair] = set()
    for (name, _, _), bucket in bands.items():
        if len(bucket) > bucket_limit:
            continue
        candidates: Iterable[CasePair]
        if case_id is None:
            candidates = combinations(sorted(bucket), 2)
        elif case_id in bucket:
            candidates = (
                (min(case_id, other), max(case_id, other)) for other in bucket if other != case_id
            )
        else:
            continue
        max_distance = max_distances[name]
        for a, b in candidates:
            if (a, b) in pairs or (name == PHASH and a in pdq_cases and b in pdq_cases):
                continue
            if any(hash_distance(x, y) <= max_distance for x in bucket[a] for y in bucket[b]):
                pairs.add((a, b))
    return pairs


def _fuzzy_candidate_pairs(
    features: Collection[Feature],
    cfg: EdgeConfig,
    registry: Mapping[str, FeatureSpec],
    case_id: str | None,
) -> set[CasePair]:
    """Pairs whose headline templates are near-copies (`kind="fuzzy"` registry rows)."""
    from rapidfuzz import fuzz, process

    from fakecollector.core.text import headline_content

    sources = {spec.source for spec in registry.values() if spec.kind == "fuzzy" and spec.source}
    cases_by_content: dict[str, set[str]] = defaultdict(set)
    for feature in features:
        if feature.name in sources and (
            content := headline_content(feature.value, cfg.headline_fuzzy_min_tokens)
        ):
            cases_by_content[content].add(feature.case_id)
    contents = sorted(cases_by_content)
    if len(contents) < 2:
        return set()
    pairs: set[CasePair] = set()
    for start in range(0, len(contents), 512):  # row blocks keep the score matrix small
        scores = process.cdist(
            contents[start : start + 512],
            contents,
            scorer=fuzz.token_set_ratio,
            score_cutoff=cfg.headline_fuzzy_threshold * 100,
            dtype="float32",
        )
        for row, j in zip(*scores.nonzero(), strict=True):
            i = start + int(row)
            if i >= j:
                continue
            for a in cases_by_content[contents[i]]:
                for b in cases_by_content[contents[j]]:
                    if a != b and (case_id is None or case_id in (a, b)):
                        pairs.add((min(a, b), max(a, b)))
    return pairs


def minhash_values(feature: Feature, cfg: EdgeConfig) -> list[int] | None:
    """Read valid integral permutation values from a feature vector."""
    vector = feature.vector
    if vector is None or len(vector) != cfg.num_perm:
        return None
    if any(not 0 <= value < 2**32 or not float(value).is_integer() for value in vector):
        return None
    return [int(value) for value in vector]


def candidate_pairs(
    entities: Collection[Entity],
    links: Collection[EntityLink],
    features: Collection[Feature],
    cfg: EdgeConfig,
    registry: Mapping[str, FeatureSpec] = FEATURES,
    *,
    case_id: str | None = None,
    case_ids: Collection[str] = (),
) -> set[CasePair]:
    """Block on entities, MinHash LSH, perceptual hash bands, and vector neighbours."""
    active = {entity.id for entity in entities if not entity.stop}
    cases_by_entity: dict[str, set[str]] = defaultdict(set)
    for linked_case, entity_id, _ in links:
        if entity_id in active:
            cases_by_entity[entity_id].add(linked_case)
    pairs: set[CasePair] = set()
    for cases in cases_by_entity.values():
        if case_id is None:
            pairs.update(combinations(sorted(cases), 2))
        elif case_id in cases:
            pairs.update((min(case_id, other), max(case_id, other)) for other in cases - {case_id})

    hashes_by_name: dict[str, dict[int, tuple[str, MinHash]]] = defaultdict(dict)
    unknown: set[str] = set()
    for index, feature in enumerate(features):
        spec = registry.get(feature.name)
        if spec is None:
            unknown.add(feature.name)
        elif spec.kind == "minhash" and (values := minhash_values(feature, cfg)) is not None:
            # Rehydrate the default datasketch 2.x scheme without recomputing hashes.
            signature = MinHash(seed=cfg.seed, hashvalues=values, scheme="affine32")
            hashes_by_name[feature.name][index] = feature.case_id, signature
    for name in sorted(unknown):
        logger.warning("Ignoring unknown feature %s", name)

    for hashes in hashes_by_name.values():
        if len(hashes) < 2:
            continue
        index_lsh = MinHashLSH(threshold=cfg.lsh_threshold, num_perm=cfg.num_perm)
        for index, (_, signature) in hashes.items():
            index_lsh.insert(index, signature)
        for current_case, signature in hashes.values():
            if case_id is not None and case_id != current_case:
                continue
            for index in index_lsh.query(signature):
                other, _ = hashes[index]
                if other != current_case:
                    pairs.add((min(current_case, other), max(current_case, other)))
    n = len(set(case_ids).union(feature.case_id for feature in features))
    pairs.update(_hash_candidate_pairs(features, registry, max(50, 0.05 * n), case_id))
    pairs.update(_fuzzy_candidate_pairs(features, cfg, registry, case_id))
    return pairs | vector_candidate_pairs(features, cfg, registry, case_id=case_id)
