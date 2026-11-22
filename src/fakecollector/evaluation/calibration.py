"""Estimate similarity anchors from unlabelled pairs and controlled perturbations."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from itertools import combinations
from random import Random
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, FiniteFloat

from fakecollector.core.registry import FEATURES, FeatureSpec
from fakecollector.core.schemas import Feature
from fakecollector.core.text import headline_content as text_headline_content
from fakecollector.core.text import minhash_vector as text_minhash
from fakecollector.extractors.html_page import parse_html
from fakecollector.extractors.template import MIN_SHINGLES, css_classes, dom_shingles
from fakecollector.extractors.template import minhash_vector as template_minhash
from fakecollector.graph.blocking import IMAGE_HASH_BITS
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import build_entities, entity_type_for
from fakecollector.graph.signals import (
    SignalContext,
    _entity_evidence,
    _hash_evidence,
    _minhash_evidence,
    build_context,
    pair_signals,
)
from fakecollector.graph.vectors import best_vector_match

logger = logging.getLogger(__name__)

_WORDS = re.compile(r"[^\W_]+")
_DIGITS = re.compile(r"\d+")
_TEXT_SOURCES = {"text.raw", "html.title"}
_TEMPLATE_BLOCKS = (
    "article",
    "aside",
    "div",
    "footer",
    "form",
    "header",
    "li",
    "nav",
    "p",
    "section",
)
_IMAGE_MODES = {
    "img.phash": "phash/regions",
    "img.pdq": "pdq/regions",
    "img.siglip": "siglip/regions",
}

type Verdict = Literal["more conservative", "less conservative — keep prior"]


class PositiveSummary(BaseModel):
    """Count and tenth percentile of synthetic comparisons."""

    n: int = Field(gt=0)
    p10: FiniteFloat


class AnchorSummary(BaseModel):
    """Raw sample statistics and suggested anchors for one feature."""

    prior_lo: float
    prior_hi: float
    pairs_n: int
    null_n: int
    null_max: float | None
    null_q99: float | None
    null_q995: float | None
    synthetic_n: int
    synthetic_p10: float | None
    proposed_lo: float
    proposed_hi: float
    verdict: Verdict


class CalibrationReport(BaseModel):
    """Aggregate measurements that can be written without exposing case data."""

    cases_n: int
    seed: int
    n0: int
    features: dict[str, AnchorSummary]


def anchor_verdict(prior_lo: float, proposed_lo: float) -> Verdict:
    """Classify a proposal by its lower anchor."""
    return "more conservative" if proposed_lo >= prior_lo else "less conservative — keep prior"


def _shrink(measured: float, prior: float, n: int, n0: int) -> float:
    return prior + (measured - prior) * (n / (n + n0)) if n else prior


def summarize_anchors(
    prior_lo: float,
    prior_hi: float,
    pairs_n: int,
    null: Sequence[float],
    positive: PositiveSummary | None,
    n0: int,
) -> AnchorSummary:
    """Compute the null tail and shrink each anchor using its own sample count."""
    if n0 < 0:
        raise ValueError("n0 must be nonnegative")
    q99, q995 = map(float, np.percentile(null, [99, 99.5])) if len(null) else (None, None)
    measured_lo = max(prior_lo, q995) if q995 is not None else prior_lo
    proposed_lo = _shrink(measured_lo, prior_lo, len(null), n0)
    return AnchorSummary(
        prior_lo=prior_lo,
        prior_hi=prior_hi,
        pairs_n=pairs_n,
        null_n=len(null),
        null_max=max(null, default=None),
        null_q99=q99,
        null_q995=q995,
        synthetic_n=positive.n if positive else 0,
        synthetic_p10=positive.p10 if positive else None,
        proposed_lo=proposed_lo,
        proposed_hi=_shrink(positive.p10, prior_hi, positive.n, n0) if positive else prior_hi,
        verdict=anchor_verdict(prior_lo, proposed_lo),
    )


def perturb_text(source: str, rng: Random) -> str:
    """Drop tokens and replace numbers and likely names reproducibly."""
    words = _WORDS.findall(unicodedata.normalize("NFKC", source))
    dropped = set(rng.sample(range(len(words)), round(len(words) * rng.uniform(0.1, 0.3))))
    replacements: dict[str, str] = {}
    result = []
    for index, word in enumerate(words):
        if index in dropped:
            continue
        if word.isalpha() and word.istitle():
            if word not in replacements:
                replacements[word] = "Imie" + "".join(
                    rng.choices("abcdefghijklmnopqrstuvwxyz", k=6)
                )
            word = replacements[word]
        word = _DIGITS.sub(
            lambda match: "".join(str((int(digit) + rng.randint(1, 9)) % 10) for digit in match[0]),
            word,
        )
        result.append(word)
    return " ".join(result)


def _image_positives(rows: Mapping[str, PositiveSummary]) -> dict[str, PositiveSummary]:
    result = {}
    for name, mode in _IMAGE_MODES.items():
        if (row := rows.get(mode)) is None:
            continue
        bits = IMAGE_HASH_BITS.get(name)
        if bits is not None and -bits <= row.p10 <= 0:
            result[name] = PositiveSummary(n=row.n, p10=1 + row.p10 / bits)
        elif bits is None and -1 <= row.p10 <= 1:
            result[name] = row
        else:
            raise ValueError(f"Invalid robustness p10 for {mode}")
    return result


def _anchored_features(cfg: EdgeConfig) -> dict[str, FeatureSpec]:
    specs = {}
    for name, spec in FEATURES.items():
        if spec.kind == "vector":
            lo, hi = (
                (cfg.image_vector_lo, cfg.image_vector_hi)
                if spec.family == "image"
                else (cfg.text_vector_lo, cfg.text_vector_hi)
            )
            spec = replace(
                spec, lo=lo if spec.lo is None else spec.lo, hi=hi if spec.hi is None else spec.hi
            )
        if spec.lo is not None and spec.hi is not None:
            specs[name] = spec
    return specs


def _raw_score(
    name: str, spec: FeatureSpec, left: list[Feature], right: list[Feature], ctx: SignalContext
) -> float | None:
    if spec.kind == "vector":
        match = best_vector_match(left, right)
        return match[0] if match is not None else None

    # Graph evidence has no raw-score field. Request full precision in its detail and keep
    # every nonnegative score above the evidence floor, including an exact zero.
    raw = replace(spec, lo=-1.0, hi=1.0, weight=1.0, detail_pl="{sim}")
    if spec.kind == "set":
        evidence = _entity_evidence(name, raw, left, right, ctx)
        return float(evidence[0].detail) if evidence else 0.0
    scorer = _minhash_evidence if spec.kind == "minhash" else _hash_evidence
    item = scorer(name, raw, left, right, ctx)
    return float(item.detail) if item is not None else None


def _perturbed_sketch_score(
    name: str, original: list[float], variant: list[float], ctx: SignalContext
) -> float | None:
    base = Feature(name=name, case_id="original", artifact_id="original", value="", vector=original)
    changed = Feature(name=name, case_id="variant", artifact_id="variant", value="", vector=variant)
    return _raw_score(name, FEATURES[name], [base], [changed], ctx)


def _text_scores(features: Sequence[Feature], seed: int, ctx: SignalContext) -> list[float]:
    sources = sorted({(f.case_id, f.value) for f in features if f.name in _TEXT_SOURCES})
    rng = Random(seed)
    scores = []
    for _, source in sources:
        original = text_minhash(source)
        variant = text_minhash(perturb_text(source, rng))
        if original is not None and variant is not None:
            score = _perturbed_sketch_score("text.minhash", original, variant, ctx)
            if score is not None:
                scores.append(score)
    return scores


def _template_scores(
    html_sources: Iterable[str], seed: int, ctx: SignalContext
) -> dict[str, list[float]]:
    rng = Random(seed)
    scores: dict[str, list[float]] = defaultdict(list)
    for html in html_sources:
        try:
            soup = parse_html(html)
            original_dom, original_classes = dom_shingles(soup), css_classes(soup)
            blocks = soup.find_all(_TEMPLATE_BLOCKS)
            for block in rng.sample(blocks, round(len(blocks) * rng.uniform(0.1, 0.3))):
                if block.parent is not None:
                    block.decompose()
            variant_dom, surviving_classes = dom_shingles(soup), css_classes(soup)
        except Exception as exc:  # Match the extractor's tolerance of malformed pages.
            logger.warning("Skipping HTML calibration sample (%s)", type(exc).__name__)
            continue
        renamed = set(rng.sample(sorted(surviving_classes), (len(surviving_classes) + 4) // 5))
        suffix = "--calibration"
        while any(name + suffix in original_classes for name in renamed):
            suffix += "-"
        variant_classes = (surviving_classes - renamed) | {name + suffix for name in renamed}
        for name, original, variant, minimum in (
            ("html.dom_minhash", original_dom, variant_dom, MIN_SHINGLES),
            ("html.css_minhash", original_classes, variant_classes, 1),
        ):
            if min(len(original), len(variant)) >= minimum:
                score = _perturbed_sketch_score(
                    name, template_minhash(original), template_minhash(variant), ctx
                )
                if score is not None:
                    scores[name].append(score)
    return scores


def _asset_scores(
    by_case: Mapping[str, Mapping[str, list[Feature]]], seed: int, ctx: SignalContext
) -> list[float]:
    name = "asset.sha256"
    spec = FEATURES[name]
    rng = Random(seed)
    scores = []
    for groups in by_case.values():
        assets = {feature.value: feature for feature in groups.get(name, []) if feature.value}
        if len(assets) < 2:
            continue
        kept = min(len(assets) - 1, max(1, round(len(assets) * rng.uniform(0.3, 0.7))))
        variant = [assets[key] for key in rng.sample(sorted(assets), kept)]
        if any(
            (entity := ctx.entities.get(f"{spec.entity_type}:{feature.value}")) is not None
            and not entity.stop
            for feature in variant
        ):
            score = _raw_score(name, spec, list(assets.values()), variant, ctx)
            assert score is not None  # A retained active asset is present on both sides.
            scores.append(score)
    return scores


def calibrate(
    features: Sequence[Feature],
    *,
    case_ids: Sequence[str] = (),
    html_sources: Iterable[str] = (),
    image_summary: Mapping[str, PositiveSummary] | None = None,
    n0: int = 200,
    seed: int = 0,
) -> CalibrationReport:
    """Measure label-free null and synthetic-positive scores for anchored features."""
    cfg = EdgeConfig()
    specs = _anchored_features(cfg)
    ids = sorted(set(case_ids).union(f.case_id for f in features))
    entities, _ = build_entities(features, cfg=cfg, case_ids=ids)
    ctx = build_context(features, entities, cfg, case_ids=ids)
    # Measure containment before the graph's minimum-shared-files rule.
    raw_ctx = replace(ctx, cfg=cfg.model_copy(update={"set_min_shared": 1}))
    by_case: dict[str, dict[str, list[Feature]]] = {case_id: defaultdict(list) for case_id in ids}
    case_features: dict[str, list[Feature]] = defaultdict(list)
    campaign_keys: dict[str, set[str]] = defaultdict(set)
    for feature in features:
        spec = FEATURES.get(feature.name)
        if spec is None or spec.kind == "info":
            continue
        case_features[feature.case_id].append(feature)
        by_case[feature.case_id][feature.name].append(feature)
        if spec.kind == "key" and spec.tier == "campaign":
            entity_id = f"{entity_type_for(feature.name, spec)}:{feature.value}"
            if (entity := ctx.entities.get(entity_id)) is not None and not entity.stop:
                campaign_keys[feature.case_id].add(entity_id)

    counts: dict[str, int] = defaultdict(int)
    null: dict[str, list[float]] = defaultdict(list)
    for a, b in combinations(ids, 2):
        left, right = by_case[a], by_case[b]
        comparable = specs.keys() & left.keys() & right.keys()
        if not comparable:
            continue
        shared_campaign_key = not campaign_keys[a].isdisjoint(campaign_keys[b])
        fires = (
            pair_signals(case_features[a], case_features[b], ctx) if not shared_campaign_key else {}
        )
        for name in comparable:
            spec = specs[name]
            score = _raw_score(name, spec, left[name], right[name], raw_ctx)
            if score is None:
                continue
            counts[name] += 1
            if not shared_campaign_key and not (fires.keys() - {spec.family}):
                null[name].append(score)

    synthetic = _template_scores(html_sources, seed, raw_ctx)
    synthetic["text.minhash"] = _text_scores(features, seed, raw_ctx)
    synthetic["asset.sha256"] = _asset_scores(by_case, seed, raw_ctx)
    positive = _image_positives(image_summary or {})
    for name, scores in synthetic.items():
        if scores:
            positive[name] = PositiveSummary(n=len(scores), p10=float(np.percentile(scores, 10)))
    rows = {}
    for name, spec in specs.items():
        assert spec.lo is not None and spec.hi is not None
        rows[name] = summarize_anchors(
            spec.lo, spec.hi, counts[name], null[name], positive.get(name), n0
        )
    return CalibrationReport(cases_n=len(ids), seed=seed, n0=n0, features=rows)


def headline_fuzzy_null(
    features: Iterable[Feature],
    campaign_by_case: Mapping[str, str],
    cfg: EdgeConfig | None = None,
    *,
    per_headline_max: bool = False,
) -> np.ndarray:
    """Token-set ratios of headline templates from cases in different unsupervised campaigns.

    Label-free null for `EdgeConfig.headline_fuzzy_threshold`: templates (titles and OCR
    headlines, `{PERSON}`-masked) of two cases that the base run put in different campaigns
    (a case outside every campaign is its own) are taken as unrelated. Gold labels are not
    read. With `per_headline_max`, each headline contributes only its best unrelated match:
    the null for an upload that is compared with every base headline. The threshold is the
    q99.5 of that distribution.
    """
    from fakecollector.graph.signals import fuzzy_similarity

    cfg = cfg or EdgeConfig()
    contents: dict[str, set[str]] = defaultdict(set)
    sources = {spec.source for spec in FEATURES.values() if spec.kind == "fuzzy" and spec.source}
    for feature in features:
        if feature.name in sources:
            content = text_headline_content(feature.value, cfg.headline_fuzzy_min_tokens)
            if content is not None:
                contents[content].add(campaign_by_case.get(feature.case_id, feature.case_id))
    keys = sorted(contents)
    if per_headline_max:
        best = [
            max(
                (fuzzy_similarity(a, b) for b in keys if contents[a].isdisjoint(contents[b])),
                default=None,
            )
            for a in keys
        ]
        return np.asarray([x for x in best if x is not None], dtype=np.float64)
    scores = [
        fuzzy_similarity(a, b)
        for a, b in combinations(keys, 2)
        if contents[a].isdisjoint(contents[b])
    ]
    return np.asarray(scores, dtype=np.float64)
