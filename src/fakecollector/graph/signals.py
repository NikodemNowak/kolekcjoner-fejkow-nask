"""Pairwise evidence signals between features of different cases.

Computes entity, MinHash, fuzzy-text, image-hash and vector similarity evidence and
gathers it into a per-pair `SignalContext`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from math import log

from rapidfuzz import fuzz

from fakecollector.core.registry import (
    FEATURES,
    IMAGE_HASH_IDENTICAL_DETAIL,
    IMAGE_HASH_SIMILAR_DETAIL,
    FeatureSpec,
)
from fakecollector.core.schemas import Entity, Evidence, Family, Feature, Tier
from fakecollector.core.text import headline_content, informative_tokens
from fakecollector.graph.blocking import (
    IMAGE_HASH_BITS,
    PDQ,
    PHASH,
    hash_distance,
    image_hash_value,
    minhash_values,
)
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import entity_type_for
from fakecollector.graph.vectors import best_vector_match

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalContext:
    """Hold corpus frequencies, stop status, and scoring settings for pair evaluation."""

    n: int
    entities: Mapping[str, Entity]
    registry: Mapping[str, FeatureSpec]
    cfg: EdgeConfig


def build_context(
    features: Collection[Feature],
    entities: Collection[Entity],
    cfg: EdgeConfig,
    registry: Mapping[str, FeatureSpec] = FEATURES,
    *,
    case_ids: Collection[str] = (),
) -> SignalContext:
    """Index corpus statistics once for all pair comparisons."""
    return SignalContext(
        n=len(set(case_ids).union(feature.case_id for feature in features)),
        entities={entity.id: entity for entity in entities},
        registry=registry,
        cfg=cfg,
    )


def comparable_families(
    a: Collection[Feature],
    b: Collection[Feature],
    registry: Mapping[str, FeatureSpec] = FEATURES,
) -> list[Family]:
    """Return families with at least one non-informational feature on each side."""
    return sorted(_families(a, registry) & _families(b, registry))


def pair_signals(
    a: Collection[Feature], b: Collection[Feature], ctx: SignalContext
) -> dict[Family, tuple[float, list[Evidence]]]:
    """Score supported feature matches and take the maximum probability per family."""
    a, b = siglip_usable(a, ctx.cfg), siglip_usable(b, ctx.cfg)
    left, right = _group_features(a, ctx.registry), _group_features(b, ctx.registry)
    evidence_by_family: dict[Family, list[Evidence]] = defaultdict(list)
    solo_images: list[tuple[Evidence, float]] = []
    shared_names = left.keys() & right.keys()
    # On gold, PDQ had zero false pairs after the flat-graphic gate, versus one for pHash.
    if PDQ in shared_names:
        shared_names.discard(PHASH)
    for name in sorted(shared_names):
        spec = ctx.registry[name]
        if spec.kind in {"key", "set"}:
            evidence_by_family[spec.family].extend(
                _entity_evidence(name, spec, left[name], right[name], ctx)
            )
        elif spec.kind == "vector" and spec.family == "image":
            looks = _vector_evidence(name, spec, left[name], right[name], ctx)
            if looks is not None:
                solo_images.append(looks)
        elif spec.kind in {"minhash", "vector", "hash"}:
            if spec.kind == "vector":
                vector = _vector_evidence(name, spec, left[name], right[name], ctx)
                item = None if vector is None else vector[0]
            elif spec.kind == "minhash":
                item = _minhash_evidence(name, spec, left[name], right[name], ctx)
            else:
                item = _hash_evidence(name, spec, left[name], right[name], ctx)
            if item is not None:
                evidence_by_family[spec.family].append(item)
    for name, spec in sorted(ctx.registry.items()):
        source = spec.source
        if spec.kind == "fuzzy" and source is not None and source in left and source in right:
            item = _fuzzy_evidence(name, spec, left[source], right[source], ctx)
            if item is not None:
                evidence_by_family[spec.family].append(item)
    # A look-alike picture (stock photo, headshot) is campaign evidence on its own only when
    # nearly identical; otherwise another family has to point the same way.
    corroborated = any(
        item.tier == "campaign" and item.weight > 0
        for family, items in evidence_by_family.items()
        if family != "image"
        for item in items
    )
    for image, similarity in solo_images:
        if similarity < ctx.cfg.image_vector_solo and not corroborated:
            image = image.model_copy(
                update={
                    "tier": "context",
                    "weight": min(image.weight, ctx.cfg.tier_caps["context"]),
                }
            )
        evidence_by_family[image.family].append(image)
    return {
        family: (max(item.weight for item in evidence), evidence)
        for family, evidence in sorted(evidence_by_family.items())
        if evidence
    }


def evidence_order(evidence: Evidence) -> tuple[float, str, str, str, list[str]]:
    """Rank stronger evidence first and break ties consistently."""
    return -evidence.weight, evidence.family, evidence.kind, evidence.value, evidence.artifacts


def _families(features: Collection[Feature], registry: Mapping[str, FeatureSpec]) -> set[Family]:
    return {
        spec.family
        for feature in features
        if (spec := registry.get(feature.name)) is not None and spec.kind != "info"
    }


def _group_features(
    features: Collection[Feature], registry: Mapping[str, FeatureSpec]
) -> dict[str, list[Feature]]:
    groups: dict[str, list[Feature]] = defaultdict(list)
    unknown: set[str] = set()
    for feature in features:
        spec = registry.get(feature.name)
        if spec is None:
            unknown.add(feature.name)
        elif spec.kind != "info":
            groups[feature.name].append(feature)
    for name in sorted(unknown):
        logger.warning("Ignoring unknown feature %s", name)
    return groups


def _active_values(
    features: list[Feature], entity_type: str, ctx: SignalContext
) -> dict[str, set[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for feature in features:
        entity_id = f"{entity_type}:{feature.value}"
        if (entity := ctx.entities.get(entity_id)) is not None and not entity.stop:
            values[entity_id].add(_artifact_ref(feature))
    return values


def _artifact_ref(feature: Feature) -> str:
    return f"{feature.artifact_id}#{feature.locator}" if feature.locator else feature.artifact_id


def _entity_evidence(
    name: str, spec: FeatureSpec, a: list[Feature], b: list[Feature], ctx: SignalContext
) -> list[Evidence]:
    entity_type = entity_type_for(name, spec)
    if entity_type is None:
        return []
    left, right = _active_values(a, entity_type, ctx), _active_values(b, entity_type, ctx)
    shared = sorted(left.keys() & right.keys())
    if not shared:
        return []
    # One shared file seen in 3+ cases is usually a kit or library file, not campaign reuse
    # (real campaigns share 7-23 files); a lone file still counts when only this pair has it.
    if (
        spec.kind == "set"
        and spec.tier == "campaign"
        and len(shared) < ctx.cfg.set_min_shared
        and all(ctx.entities[key].df > 2 for key in shared)
    ):
        return []

    containment = 0.0
    if spec.kind == "set":
        # Smoothing keeps containment defined even when every observed case shares an asset.
        idf = {key: log((ctx.n + 1) / ctx.entities[key].df) for key in left.keys() | right.keys()}
        smaller_weight = min(sum(idf[key] for key in sorted(side)) for side in (left, right))
        containment = sum(idf[key] for key in shared) / smaller_weight

    evidence: list[Evidence] = []
    for key in shared:
        entity = ctx.entities[key]
        if spec.kind == "set":
            similarity = containment
            strength = _anchored(similarity, spec)
        else:
            similarity = 1.0
            # A value shared by both cases has full rarity weight in a two-case corpus.
            strength = min(1.0, log(ctx.n / entity.df) / log(ctx.n / 2)) if ctx.n > 2 else 1.0
            # A campaign key can stay distinctive even when many members share it.
            if spec.tier == "campaign":
                strength = max(ctx.cfg.campaign_key_floor, strength)
        tier = spec.tier
        if (
            name == HEADLINE_TEMPLATE
            and len(informative_tokens(entity.value)) < ctx.cfg.headline_key_min_informative
        ):
            tier = "context"
        item = _evidence(
            name,
            spec,
            tier,
            entity.value,
            entity.df,
            similarity,
            strength,
            left[key] | right[key],
            ctx,
        )
        if item is not None:
            evidence.append(item)
    return evidence


def _minhash_evidence(
    name: str, spec: FeatureSpec, a: list[Feature], b: list[Feature], ctx: SignalContext
) -> Evidence | None:
    left = [
        (_artifact_ref(f), values) for f in a if (values := minhash_values(f, ctx.cfg)) is not None
    ]
    right = [
        (_artifact_ref(f), values) for f in b if (values := minhash_values(f, ctx.cfg)) is not None
    ]
    best = 0
    artifacts: set[str] = set()
    for left_id, left_values in left:
        for right_id, right_values in right:
            matches = sum(x == y for x, y in zip(left_values, right_values, strict=True))
            if matches > best:
                best = matches
                artifacts.clear()
            if matches == best:
                artifacts.update((left_id, right_id))
    if not artifacts:
        return None
    similarity = best / ctx.cfg.num_perm
    tier = spec.tier
    if tier == "toolkit" and similarity >= ctx.cfg.template_campaign_threshold:
        tier = "campaign"
    return _evidence(
        name,
        spec,
        tier,
        f"J {similarity:.2f}",
        0,
        similarity,
        _anchored(similarity, spec),
        artifacts,
        ctx,
    )


HEADLINE_TEMPLATE = "text.headline_tpl"


def fuzzy_contents(features: Collection[Feature], ctx: SignalContext) -> dict[str, str]:
    """Map active (non-stop) template values to their content words for fuzzy matching."""
    out: dict[str, str] = {}
    for feature in features:
        spec = ctx.registry.get(feature.name)
        entity_type = entity_type_for(feature.name, spec) if spec is not None else None
        entity = ctx.entities.get(f"{entity_type}:{feature.value}") if entity_type else None
        if entity is not None and entity.stop:
            continue
        content = headline_content(feature.value, ctx.cfg.headline_fuzzy_min_tokens)
        if content is not None:
            out[feature.value] = content
    return out


def shared_content_words(a: str, b: str) -> int:
    """Informative words of the shorter headline with a near-identical word in the other.

    A word counts when it matches up to an OCR slip ("stało" / "stałow", ratio >= 0.8).
    """
    left, right = sorted((informative_tokens(a), informative_tokens(b)), key=len)
    return sum(
        1
        for word in left
        if word in right or any(fuzz.ratio(word, other) >= _WORD_MATCH for other in right)
    )


_WORD_MATCH = 80.0


def fuzzy_similarity(a: str, b: str) -> float:
    """Token-set ratio of two content strings in 0..1 (word order and extra words ignored)."""
    return float(fuzz.token_set_ratio(a, b)) / 100


def _fuzzy_evidence(
    name: str, spec: FeatureSpec, a: list[Feature], b: list[Feature], ctx: SignalContext
) -> Evidence | None:
    # Identical templates are the exact key's job (with its stoplist and rarity weight).
    left, right = fuzzy_contents(a, ctx), fuzzy_contents(b, ctx)
    threshold = ctx.cfg.headline_fuzzy_threshold
    min_shared = ctx.cfg.headline_fuzzy_min_shared
    best, pair = 0.0, ("", "")
    for x, x_words in sorted(left.items()):
        for y, y_words in sorted(right.items()):
            if x == y or shared_content_words(x, y) < min_shared:
                continue
            if (similarity := fuzzy_similarity(x_words, y_words)) > best:
                best, pair = similarity, (x, y)
    if best < threshold:
        return None
    artifacts = {
        _artifact_ref(f) for f in [*a, *b] if f.value in pair and f.value in {*left, *right}
    }
    # A near-copy of a headline is a softened campaign key: the same floor as an exact key.
    floor = ctx.cfg.campaign_key_floor
    strength = floor + (1 - floor) * _anchored(best, spec, threshold, 1.0)
    value = " ≈ ".join(f"„{text[:60]}”" for text in pair)
    return _evidence(name, spec, spec.tier, value, 0, best, strength, artifacts, ctx)


def _hash_evidence(
    name: str, spec: FeatureSpec, a: list[Feature], b: list[Feature], ctx: SignalContext
) -> Evidence | None:
    left = [(_artifact_ref(f), value) for f in a if (value := image_hash_value(f)) is not None]
    right = [(_artifact_ref(f), value) for f in b if (value := image_hash_value(f)) is not None]
    if not left or not right:
        return None
    bits = IMAGE_HASH_BITS[name]
    best = bits + 1
    artifacts: set[str] = set()
    for left_ref, left_hash in left:
        for right_ref, right_hash in right:
            distance = hash_distance(left_hash, right_hash)
            if distance < best:
                best = distance
                artifacts.clear()
            if distance == best:
                artifacts.update((left_ref, right_ref))
    similarity = 1 - best / bits
    return _evidence(
        name,
        spec,
        spec.tier,
        f"H {best}/{bits}",
        0,
        similarity,
        _anchored(similarity, spec),
        artifacts,
        ctx,
    )


def _vector_evidence(
    name: str, spec: FeatureSpec, a: list[Feature], b: list[Feature], ctx: SignalContext
) -> tuple[Evidence, float] | None:
    match = best_vector_match(a, b)
    if match is None:
        return None
    similarity, matched = match
    cfg = ctx.cfg
    lo, hi = (
        (cfg.image_vector_lo, cfg.image_vector_hi)
        if spec.family == "image"
        else (cfg.text_vector_lo, cfg.text_vector_hi)
    )
    # Down-weighted rows (e.g. images of page variants flagged as cloaking) carry it in
    # their confidence.
    trust = min((feature.confidence for feature in matched), default=1.0)
    item = _evidence(
        name,
        spec,
        spec.tier,
        f"cos {similarity:.2f}",
        0,
        similarity,
        _anchored(similarity, spec, lo, hi) * trust,
        {_artifact_ref(feature) for feature in matched},
        ctx,
    )
    return None if item is None else (item, similarity)


def siglip_usable(features: Collection[Feature], cfg: EdgeConfig) -> list[Feature]:
    """Drop SigLIP rows of images that are mostly one face (identity belongs to faces)."""
    portraits = set()
    for feature in features:
        if feature.name == "img.face_share":
            try:
                share = float(feature.value)
            except ValueError:
                continue
            if share > cfg.siglip_max_face_share:
                portraits.add(feature.artifact_id)
    if not portraits:
        return list(features)
    return [f for f in features if not (f.name == "img.siglip" and f.artifact_id in portraits)]


def _anchored(
    similarity: float, spec: FeatureSpec, lo: float | None = None, hi: float | None = None
) -> float:
    lo = spec.lo if spec.lo is not None else lo
    hi = spec.hi if spec.hi is not None else hi
    if lo is None or hi is None:
        return similarity
    return max(0.0, min(1.0, (similarity - lo) / (hi - lo)))


def _evidence(
    name: str,
    spec: FeatureSpec,
    tier: Tier,
    value: str,
    df: int,
    similarity: float,
    strength: float,
    artifacts: set[str],
    ctx: SignalContext,
) -> Evidence | None:
    weight = min(spec.weight * strength, ctx.cfg.tier_caps[tier])
    if weight <= 0:
        return None
    display_value = value.removeprefix("H ") if spec.kind == "hash" else value
    template = (
        IMAGE_HASH_IDENTICAL_DETAIL
        if spec.kind == "hash" and similarity == 1 and spec.detail_pl == IMAGE_HASH_SIMILAR_DETAIL
        else spec.detail_pl
    )
    return Evidence(
        family=spec.family,
        tier=tier,
        kind=name,
        value=value,
        detail=template.format(kind=name, value=display_value, df=df, n=ctx.n, sim=similarity),
        weight=weight,
        artifacts=sorted(artifacts),
    )
