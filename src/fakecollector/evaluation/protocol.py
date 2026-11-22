"""Compare graph assignment decisions to campaign membership in each base split."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from math import inf, nextafter
from typing import TYPE_CHECKING, Literal, Protocol, cast

from pydantic import BaseModel

from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Artifact, Assignment, Campaign, Family, Feature, Role
from fakecollector.evaluation.gold import GoldLabel
from fakecollector.evaluation.metrics import PRF, pairwise

if TYPE_CHECKING:
    from fakecollector.graph.analyze import Analysis

DEFAULT_MARGIN = 0.1


class CampaignAnalysis(Protocol):
    """The part of graph analysis required to judge assignment correctness."""

    @property
    def campaigns(self) -> list[Campaign]:
        """Return the predicted campaigns with their members."""
        ...


class AnalyzeFn[A: CampaignAnalysis](Protocol):
    """Analyze a base split, including cases without features."""

    def __call__(self, features: Sequence[Feature], /, *, case_ids: Sequence[str]) -> A:
        """Return the base analysis."""
        ...


class AssignFn[A: CampaignAnalysis](Protocol):
    """Assign held-out cases against the analysis returned by the paired callable."""

    def __call__(
        self,
        new_features: Sequence[Feature],
        base: A,
        base_features: Sequence[Feature],
        /,
        *,
        new_case_ids: Sequence[str],
    ) -> list[Assignment]:
        """Return a decision for each held-out case."""
        ...


class AssignmentTrial(BaseModel):
    """The outcome for one case and whether its campaign was available in the base."""

    assignment: Assignment
    known: bool
    correct: bool


class OpenSetResult(BaseModel):
    """Assignments and rates for a single open-set protocol."""

    trials: list[AssignmentTrial]

    @property
    def accuracy(self) -> float | None:
        """Return the fraction of cases assigned correctly without review."""
        return _rate(sum(trial.correct for trial in self.trials), len(self.trials))

    @property
    def false_accept_rate(self) -> float | None:
        """Return existing decisions as a fraction of truly new cases."""
        new = [trial for trial in self.trials if not trial.known]
        return _rate(sum(trial.assignment.decision == "existing" for trial in new), len(new))

    @property
    def false_reject_rate(self) -> float | None:
        """Return new decisions as a fraction of truly known cases."""
        known = [trial for trial in self.trials if trial.known]
        return _rate(sum(trial.assignment.decision == "new" for trial in known), len(known))

    @property
    def review_rate(self) -> float | None:
        """Return reviews as a fraction of all cases."""
        return _rate(
            sum(trial.assignment.decision == "review" for trial in self.trials), len(self.trials)
        )

    @property
    def scores_known(self) -> list[float]:
        """Return best-campaign scores of truly known cases."""
        return [trial.assignment.score for trial in self.trials if trial.known]

    @property
    def scores_new(self) -> list[float]:
        """Return best-campaign scores of truly new cases."""
        return [trial.assignment.score for trial in self.trials if not trial.known]


def _rate(count: int, total: int) -> float | None:
    return count / total if total else None


def _gold_groups(case_ids: Iterable[str], gold: dict[str, GoldLabel]) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for case_id in sorted(case_ids):
        groups[gold[case_id].campaign].add(case_id)
    return groups


def _evaluate_split[A: CampaignAnalysis](
    features: Sequence[Feature],
    gold: dict[str, GoldLabel],
    base_ids: set[str],
    new_ids: set[str],
    analyze_fn: AnalyzeFn[A] | None,
    assign_fn: AssignFn[A] | None,
) -> list[AssignmentTrial]:
    if not new_ids:
        return []
    base_features = [feature for feature in features if feature.case_id in base_ids]
    new_features = [feature for feature in features if feature.case_id in new_ids]
    if analyze_fn is None:
        from fakecollector.graph.analyze import analyze

        base = cast(A, analyze(base_features, case_ids=sorted(base_ids)))
    else:
        base = analyze_fn(base_features, case_ids=sorted(base_ids))
    if assign_fn is None:
        from fakecollector.graph.assign import assign

        assignments = assign(
            new_features, cast("Analysis", base), base_features, new_case_ids=sorted(new_ids)
        )
    else:
        assignments = assign_fn(new_features, base, base_features, new_case_ids=sorted(new_ids))
    if len(assignments) != len(new_ids) or {item.case_id for item in assignments} != new_ids:
        raise ValueError("assign must return exactly one decision for each held-out case")

    gold_groups = _gold_groups(base_ids, gold)
    predicted_groups = {campaign.id: set(campaign.case_ids) for campaign in base.campaigns}
    trials = []
    for item in assignments:
        peers = gold_groups.get(gold[item.case_id].campaign, set())
        if peers:
            members = predicted_groups.get(item.campaign_id or "", set())
            correct = item.decision == "existing" and peers <= members
        else:
            correct = item.decision == "new"
        trials.append(AssignmentTrial(assignment=item, known=bool(peers), correct=correct))
    return trials


def holdout_variant[A: CampaignAnalysis](
    features: Sequence[Feature],
    gold: dict[str, GoldLabel],
    *,
    analyze_fn: AnalyzeFn[A] | None = None,
    assign_fn: AssignFn[A] | None = None,
) -> OpenSetResult:
    """Hold out the lexicographically first case in each multi-case campaign."""
    case_ids = set(gold)
    trials = []
    for members in _gold_groups(case_ids, gold).values():
        if len(members) >= 2:
            held_out = {min(members)}
            trials.extend(
                _evaluate_split(
                    features, gold, case_ids - held_out, held_out, analyze_fn, assign_fn
                )
            )
    return OpenSetResult(trials=trials)


def leave_one_campaign_out[A: CampaignAnalysis](
    features: Sequence[Feature],
    gold: dict[str, GoldLabel],
    *,
    analyze_fn: AnalyzeFn[A] | None = None,
    assign_fn: AssignFn[A] | None = None,
) -> OpenSetResult:
    """Hold out each gold campaign in turn, including singletons."""
    case_ids = set(gold)
    trials = []
    for held_out in _gold_groups(case_ids, gold).values():
        trials.extend(
            _evaluate_split(features, gold, case_ids - held_out, held_out, analyze_fn, assign_fn)
        )
    return OpenSetResult(trials=trials)


def cross_corpus[A: CampaignAnalysis](
    features: Sequence[Feature],
    gold: dict[str, GoldLabel],
    source: str,
    target: str,
    *,
    analyze_fn: AnalyzeFn[A] | None = None,
    assign_fn: AssignFn[A] | None = None,
) -> OpenSetResult:
    """Build on the source corpus and assign all cases in the unseen target corpus."""
    if source == target:
        raise ValueError("Cross-corpus evaluation requires distinct prefixes")
    base_ids = {case_id for case_id in gold if case_id.startswith(f"{source}:")}
    new_ids = {case_id for case_id in gold if case_id.startswith(f"{target}:")}
    return OpenSetResult(
        trials=_evaluate_split(features, gold, base_ids, new_ids, analyze_fn, assign_fn)
    )


def calibrate(
    scores_known: Sequence[float],
    scores_new: Sequence[float],
    max_far: float = 0.05,
    floor: float = 0.5,
) -> tuple[float, float]:
    """Return the calibrated score cutoff and default assignment margin."""
    result = calibrate_with_rule(scores_known, scores_new, max_far, floor)
    return result.tau, result.margin


class CalibrationResult(BaseModel):
    """The assignment threshold, default margin, and rule used to select the threshold."""

    tau: float
    margin: float = DEFAULT_MARGIN
    rule: Literal["separated-score midpoint", "floor", "ceiling", "empirical FAR cutoff"]


def calibrate_with_rule(
    scores_known: Sequence[float],
    scores_new: Sequence[float],
    max_far: float = 0.05,
    floor: float = 0.5,
) -> CalibrationResult:
    """Choose a separated-score midpoint or clamp the empirical FAR cutoff."""
    if not 0 <= max_far <= 1:
        raise ValueError("max_far must be in [0, 1]")
    if not 0 <= floor <= 1:
        raise ValueError("floor must be in [0, 1]")
    if any(not 0 <= score <= 1 for scores in (scores_known, scores_new) for score in scores):
        raise ValueError("Assignment scores must be in [0, 1]")

    if scores_known and scores_new:
        max_new, min_known = max(scores_new), min(scores_known)
        midpoint = (max_new + min_known) / 2
        if max_new < min_known and midpoint > max(floor, max_new):
            return CalibrationResult(tau=midpoint, rule="separated-score midpoint")

    cutoff = 0.0
    total = len(scores_new)
    for rank, score in enumerate(sorted(scores_new, reverse=True), start=1):
        if rank / total > max_far:
            # Scores equal to the threshold are accepted, including ties at the FAR boundary.
            cutoff = nextafter(score, inf)
            break
    if cutoff > 1.0:
        return CalibrationResult(tau=1.0, rule="ceiling")
    if cutoff < floor:
        return CalibrationResult(tau=floor, rule="floor")
    return CalibrationResult(tau=cutoff, rule="empirical FAR cutoff")


def campaign_partition(campaigns: Iterable[Campaign], case_ids: Iterable[str]) -> dict[str, str]:
    """Map case IDs to campaign IDs, with singleton labels for ungrouped cases."""
    groups = {member: campaign.id for campaign in campaigns for member in campaign.case_ids}
    return {case_id: groups.get(case_id, f"S:{case_id}") for case_id in case_ids}


def ablation(
    features: Sequence[Feature],
    gold: dict[str, GoldLabel],
    families: Iterable[Family],
    *,
    analyze_fn: AnalyzeFn[CampaignAnalysis] | None = None,
) -> dict[Family, float]:
    """Return campaign pairwise F1 when each registry family is dropped in turn."""
    if analyze_fn is None:
        from fakecollector.graph.analyze import analyze

        analyze_fn = analyze
    expected = {case_id: label.campaign for case_id, label in gold.items()}
    case_ids = sorted(gold)
    scored_features = [
        (feature, FEATURES.get(feature.name)) for feature in features if feature.case_id in gold
    ]
    results: dict[Family, float] = {}
    for family in families:
        kept = [
            feature for feature, spec in scored_features if spec is None or spec.family != family
        ]
        analysis = analyze_fn(kept, case_ids=case_ids)
        results[family] = pairwise(campaign_partition(analysis.campaigns, case_ids), expected).f1
    return results


class InputAblationResult(BaseModel):
    """Campaign pairwise metrics and the number of cases with retained features."""

    scores: PRF
    cases_with_features: int


def ablation_by_input(
    features: Sequence[Feature],
    artifacts: Sequence[Artifact],
    gold: dict[str, GoldLabel],
    *,
    analyze_fn: AnalyzeFn[CampaignAnalysis] | None = None,
) -> dict[str, InputAblationResult]:
    """Measure campaign clustering with each source artifact group in isolation."""
    if analyze_fn is None:
        from fakecollector.graph.analyze import analyze

        analyze_fn = analyze
    role_groups: dict[str, set[Role]] = {
        "screenshot_only": {"screenshot", "ad_creative"},
        "har_only": {"network"},
        "html_only": {"landing_page", "landing_asset"},
        "video_only": {"ad_video", "screen_recording"},
    }
    artifacts_by_role: dict[Role, set[tuple[str, str]]] = defaultdict(set)
    for artifact in artifacts:
        artifacts_by_role[artifact.role].add((artifact.case_id, artifact.id))

    expected = {case_id: label.campaign for case_id, label in gold.items()}
    case_ids = sorted(gold)
    labeled_features = [feature for feature in features if feature.case_id in gold]
    scenarios = {}
    for scenario, roles in role_groups.items():
        source_ids = set().union(*(artifacts_by_role[role] for role in roles))
        scenarios[scenario] = [
            feature
            for feature in labeled_features
            if (feature.case_id, feature.artifact_id) in source_ids
        ]
    scenarios["all"] = labeled_features

    results = {}
    for scenario, kept in scenarios.items():
        analysis = analyze_fn(kept, case_ids=case_ids)
        results[scenario] = InputAblationResult(
            scores=pairwise(campaign_partition(analysis.campaigns, case_ids), expected),
            cases_with_features=len({feature.case_id for feature in kept}),
        )
    return results
