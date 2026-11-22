"""Run evaluation end to end with a temporary extractor runner.

Workstream D owns the production extraction pipeline.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from importlib import import_module
from inspect import getmembers, isabstract, isclass
from itertools import combinations
from pathlib import Path
from pkgutil import walk_packages
from time import perf_counter
from typing import TYPE_CHECKING

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Artifact, Case, Feature
from fakecollector.evaluation.gold import GoldLabel, load_gold
from fakecollector.evaluation.metrics import adjusted_rand_index, bcubed, compression, pairwise
from fakecollector.evaluation.protocol import (
    OpenSetResult,
    ablation,
    ablation_by_input,
    calibrate_with_rule,
    campaign_partition,
    cross_corpus,
    holdout_variant,
    leave_one_campaign_out,
)
from fakecollector.extractors.derived import DerivedMediaExtractor, expand_derived
from fakecollector.ingest.casefolder import load_corpus

if TYPE_CHECKING:
    from fakecollector.graph.analyze import Analysis

logger = logging.getLogger(__name__)


def _discover_extractors() -> list[BaseExtractor]:
    from fakecollector import extractors

    instances = []
    modules = [extractors]
    for module_info in walk_packages(extractors.__path__, f"{extractors.__name__}."):
        try:
            modules.append(import_module(module_info.name))
        except ImportError as exc:
            logger.warning("Skipping extractor module %s: %s", module_info.name, exc)
    for module in modules:
        for _, cls in getmembers(module, isclass):
            if (
                cls.__module__ == module.__name__
                and cls is not BaseExtractor
                and issubclass(cls, BaseExtractor)
                and not isabstract(cls)
            ):
                try:
                    instances.append(cls())
                except Exception as exc:  # an optional extractor may be unavailable
                    logger.warning("Skipping extractor %s: %s", cls.__name__, exc)
    return sorted(instances, key=lambda extractor: (extractor.stage, extractor.name))


def extract_features_for_eval(
    artifacts: Sequence[Artifact],
) -> tuple[list[Feature], dict[str, float]]:
    """Extract each supported artifact at every stage and retain unique case features."""
    by_stage: dict[int, list[BaseExtractor]] = defaultdict(list)
    by_case: dict[str, list[Artifact]] = defaultdict(list)
    timings = {}
    start = perf_counter()
    for extractor in _discover_extractors():
        by_stage[extractor.stage].append(extractor)
    for artifact in artifacts:
        by_case[artifact.case_id].append(artifact)
    timings["Extractor discovery"] = perf_counter() - start

    type FeatureKey = tuple[str, str, str, str, tuple[float, ...] | None]
    features_by_case: dict[str, dict[FeatureKey, Feature]] = defaultdict(dict)
    for stage in sorted(by_stage):
        start = perf_counter()
        for case_id, case_artifacts in by_case.items():
            case_features = features_by_case[case_id]
            prior = list(case_features.values())
            for extractor in by_stage[stage]:
                for artifact in case_artifacts:
                    try:
                        if extractor.supports(artifact):
                            for feature in extractor.extract(artifact, prior.copy()):
                                key = (
                                    feature.name,
                                    feature.value,
                                    feature.artifact_id,
                                    feature.locator,
                                    tuple(feature.vector) if feature.vector else None,
                                )
                                case_features.setdefault(key, feature)
                    except Exception as exc:  # isolate failures to this artifact and extractor
                        logger.warning("%s on %s/%s: %s", extractor.name, case_id, artifact.id, exc)
        timings[f"Extraction stage {stage}"] = perf_counter() - start
    return [feature for group in features_by_case.values() for feature in group.values()], timings


def _metric_row(tier: str, predicted: dict[str, str], expected: dict[str, str]) -> str:
    scores = (
        *pairwise(predicted, expected),
        *bcubed(predicted, expected),
        adjusted_rand_index(predicted, expected),
    )
    return f"| {tier} | " + " | ".join(f"{score:.3f}" for score in scores) + " |"


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _open_set_report(splits: dict[str, OpenSetResult]) -> list[str]:
    lines = [
        "### Open-set assignment",
        "",
        "| Split | Known | New | Accuracy | FAR | FRR | Review rate | New reviews |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, result in splits.items():
        rates = " | ".join(
            map(
                _percent,
                (
                    result.accuracy,
                    result.false_accept_rate,
                    result.false_reject_rate,
                    result.review_rate,
                ),
            )
        )
        new_reviews = sum(
            not trial.known and trial.assignment.decision == "review" for trial in result.trials
        )
        lines.append(
            f"| {name} | {len(result.scores_known)} | {len(result.scores_new)} | {rates} | "
            f"{new_reviews} |"
        )
    if len(splits) == 2:
        lines.extend(["", "Cross-corpus assignment requires at least two labeled corpora."])
    lines.extend(
        [
            "",
            "The variant split holds out the first case by ID from each multi-case campaign.",
            "Accuracy counts correct automatic decisions. Reviews are reported separately. "
            "FAR uses truly new cases and FRR uses truly known cases. "
            "A dash indicates zero eligible cases.",
            "",
            "#### Best-campaign score distribution",
            "",
            "| Split | Gold status | [0, 0.2) | [0.2, 0.4) | [0.4, 0.6) | [0.6, 0.8) | [0.8, 1] |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, result in splits.items():
        for status, scores in (("Known", result.scores_known), ("New", result.scores_new)):
            bins = [0] * 5
            for score in scores:
                bins[min(int(score * 5), 4)] += 1
            lines.append(f"| {name} | {status} | " + " | ".join(map(str, bins)) + " |")

    known = splits["Held-out variant"].scores_known
    new = splits["Leave one campaign out"].scores_new
    calibration = calibrate_with_rule(known, new)
    tau = calibration.tau
    far = _percent(sum(score >= tau for score in new) / len(new)) if new else "—"
    known_pass = sum(score >= tau for score in known)
    lines.extend(
        [
            "",
            f"Suggested score threshold `tau_assign = {tau!r}` and default margin "
            f"`{calibration.margin}`. Calibration used the {calibration.rule}. "
            f"The score-only FAR on the calibration splits is {far}, "
            f"with {known_pass}/{len(known)} known scores meeting the cutoff.",
            "Calibration reuses the held-out-variant and leave-one-campaign-out scores. "
            "The assignment table uses the graph defaults. "
            "An independent run is needed to validate the suggested threshold.",
            "",
        ]
    )
    return lines


def _variant_report(
    name: str,
    analysis: Analysis,
    features: list[Feature],
    artifacts: list[Artifact],
    gold: dict[str, GoldLabel],
    corpora: Sequence[str],
    timings: dict[str, float],
) -> list[str]:
    campaigns = campaign_partition(analysis.campaigns, gold)
    expected_campaigns = {case_id: label.campaign for case_id, label in gold.items()}
    operators = {case_id: analysis.operators.get(case_id, f"S:{case_id}") for case_id in gold}
    expected_operators = {
        case_id: label.operator or f"S:{case_id}" for case_id, label in gold.items()
    }
    lines = [
        f"## {name} labels",
        "",
        "| Tier | Pairwise P | Pairwise R | Pairwise F1 "
        "| B-cubed P | B-cubed R | B-cubed F1 | ARI |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        _metric_row("Campaign", campaigns, expected_campaigns),
        _metric_row("Operator", operators, expected_operators),
        "",
        "Cases without an operator label are treated as singletons for operator metrics.",
        "",
    ]
    start = perf_counter()
    splits = {
        "Held-out variant": holdout_variant(features, gold),
        "Leave one campaign out": leave_one_campaign_out(features, gold),
    }
    for source, target in combinations(corpora, 2):
        splits[f"Cross-corpus {source} → {target}"] = cross_corpus(features, gold, source, target)
    timings[f"{name} open-set protocol"] = perf_counter() - start
    lines.extend(_open_set_report(splits))

    start = perf_counter()
    families = sorted({spec.family for spec in FEATURES.values()})
    dropped = ablation(features, gold, families)
    timings[f"{name} ablation"] = perf_counter() - start
    lines.extend(
        [
            "### Ablation",
            "",
            "| Dropped feature family | Campaign pairwise F1 |",
            "| --- | ---: |",
            f"| None | {pairwise(campaigns, expected_campaigns).f1:.3f} |",
            *(f"| {family} | {f1:.3f} |" for family, f1 in dropped.items()),
            "",
        ]
    )
    start = perf_counter()
    input_results = ablation_by_input(features, artifacts, gold)
    timings[f"{name} input ablation"] = perf_counter() - start
    lines.extend(
        [
            "### Ablation by input type",
            "",
            "| Input type | Cases with features | Campaign pairwise P | R | F1 |",
            "| --- | ---: | ---: | ---: | ---: |",
            *(
                f"| {scenario} | {result.cases_with_features} | {result.scores.precision:.3f} | "
                f"{result.scores.recall:.3f} | {result.scores.f1:.3f} |"
                for scenario, result in input_results.items()
            ),
            "",
        ]
    )
    return lines


def evaluate(
    case_dirs: Sequence[Path],
    gold_path: Path,
    out: Path,
    *,
    corpus_prefixes: Sequence[str] | None = None,
    fixture_run: bool = False,
) -> None:
    """Load labeled cases, run the graph and protocols, and write a Markdown report."""
    prefixes = (
        list(corpus_prefixes)
        if corpus_prefixes is not None
        else [path.name or path.resolve().name for path in case_dirs]
    )
    if len(prefixes) != len(case_dirs) or any(
        not prefix.strip() or ":" in prefix for prefix in prefixes
    ):
        raise ValueError("Provide one nonempty --corpus-prefix without a colon per case directory")

    strict = load_gold(gold_path)
    lenient = load_gold(gold_path, strict=False)
    cases: dict[str, Case] = {}
    artifacts: list[Artifact] = []
    start = perf_counter()
    for path, prefix in zip(case_dirs, prefixes, strict=True):
        loaded_cases, loaded_artifacts = load_corpus(path, prefix)
        for case in loaded_cases:
            if case.id in cases:
                raise ValueError(f"Repeated case {case.id}; check the input roots and prefixes")
            cases[case.id] = case
        artifacts.extend(loaded_artifacts)
    timings = {"Ingestion": perf_counter() - start}

    case_ids = sorted(cases.keys() & strict.keys())
    if not case_ids:
        raise ValueError("No ingested cases match the gold CSV; check the corpus prefixes")
    if unmatched := cases.keys() - strict.keys():
        logger.warning("Ignoring %d ingested cases without gold labels", len(unmatched))
    if missing := strict.keys() - cases.keys():
        logger.warning("Skipping %d gold labels without ingested cases", len(missing))
    strict = {case_id: strict[case_id] for case_id in case_ids}
    lenient = {case_id: lenient[case_id] for case_id in case_ids}
    labeled_artifacts = [artifact for artifact in artifacts if artifact.case_id in strict]
    # Same as `pipeline.extract`: MHTML pages and HAR bodies become artifacts of their own.
    # Derived MHTML images stay with DerivedMediaExtractor, which this runner discovers.
    media = DerivedMediaExtractor(extractors=[])
    labeled_artifacts += expand_derived(
        labeled_artifacts, media, kinds={"html"}, source_kinds={"mhtml"}
    )
    labeled_artifacts += expand_derived(labeled_artifacts, media, source_kinds={"har"})
    features, extraction_times = extract_features_for_eval(labeled_artifacts)
    timings.update(extraction_times)
    for case_id in sorted(strict.keys() - {feature.case_id for feature in features}):
        logger.warning("No features extracted for %s; keeping the case in evaluation", case_id)

    from fakecollector.graph.analyze import analyze

    start = perf_counter()
    analysis = analyze(features, case_ids=case_ids)
    timings["Clustering"] = perf_counter() - start

    lines = ["# Evaluation results", ""]
    if fixture_run:
        lines.extend(
            [
                "Fixture run. Real-corpus results will be added when the corpora are available.",
                "",
            ]
        )
    unique = sum(cases[case_id].duplicate_of not in strict for case_id in case_ids)
    campaign_count = len(set(campaign_partition(analysis.campaigns, case_ids).values()))
    lines.extend(
        [
            compression(
                len(case_ids), unique, campaign_count, len(set(analysis.operators.values()))
            ),
            "",
        ]
    )
    labeled_corpora = {cases[case_id].corpus for case_id in case_ids}
    corpora = [prefix for prefix in dict.fromkeys(prefixes) if prefix in labeled_corpora]
    lines.extend(
        _variant_report("Strict", analysis, features, labeled_artifacts, strict, corpora, timings)
    )
    if strict != lenient:
        lines.extend(
            _variant_report(
                "Lenient", analysis, features, labeled_artifacts, lenient, corpora, timings
            )
        )
    lines.extend(
        [
            "## Runtime",
            "",
            "| Stage | Seconds |",
            "| --- | ---: |",
            *(f"| {stage} | {elapsed:.3f} |" for stage, elapsed in timings.items()),
            "",
        ]
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
