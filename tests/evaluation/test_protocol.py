from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

from fakecollector.core.schemas import Artifact, Assignment, Campaign, Feature, Role
from fakecollector.evaluation.gold import GoldLabel
from fakecollector.evaluation.metrics import PRF
from fakecollector.evaluation.protocol import (
    ablation,
    ablation_by_input,
    calibrate,
    cross_corpus,
    holdout_variant,
    leave_one_campaign_out,
)

LABELS = {"X:a": "A", "Y:b": "A", "Y:c": "S:Y:c", "Y:d": "S:Y:d"}
GOLD = {case_id: GoldLabel(case_id=case_id, campaign=label) for case_id, label in LABELS.items()}
FEATURES = [
    Feature(case_id=case_id, artifact_id=case_id, name="text.raw", value=label)
    for case_id, label in LABELS.items()
    if case_id != "Y:d"
]


@dataclass
class FakeAnalysis:
    case_ids: list[str]
    campaigns: list[Campaign]


def analyze(features: Sequence[Feature], case_ids: Sequence[str] | None = None) -> FakeAnalysis:
    assert case_ids is not None
    by_case = {feature.case_id: feature.value for feature in features}
    assert set(by_case) <= set(case_ids)
    groups: dict[str, list[str]] = defaultdict(list)
    for case_id in case_ids:
        groups[by_case.get(case_id, case_id)].append(case_id)
    campaigns = [
        Campaign(
            id=f"predicted-{group}",
            case_ids=members,
            label="",
            operator_id=None,
            traits=[],
            cohesion=0,
        )
        for group, members in groups.items()
    ]
    return FakeAnalysis(list(case_ids), campaigns)


def assign(
    new_features: Sequence[Feature],
    base: FakeAnalysis,
    base_features: Sequence[Feature],
    *,
    new_case_ids: Sequence[str] | None = None,
) -> list[Assignment]:
    assert new_case_ids is not None
    assert set(base.case_ids).isdisjoint(new_case_ids)
    assert all(feature.case_id in new_case_ids for feature in new_features)
    assert all(feature.case_id in base.case_ids for feature in base_features)
    campaigns = {campaign.id for campaign in base.campaigns}
    assignments = []
    for case_id in new_case_ids:
        campaign_id = f"predicted-{LABELS[case_id]}"
        decision: Literal["existing", "review", "new"]
        if campaign_id in campaigns or (case_id == "Y:c" and campaigns):
            decision = "existing"
            score = 0.8
        elif case_id == "Y:d":
            decision = "review"
            score = 0.5
        else:
            decision = "new"
            score = 0.2
        assignments.append(
            Assignment(
                case_id=case_id,
                decision=decision,
                campaign_id=campaign_id if campaign_id in campaigns else None,
                score=score,
                margin=0.1,
                comparable=[],
                evidence=[],
            )
        )
    return assignments


def test_holdout_variant_finds_retained_campaign() -> None:
    result = holdout_variant(FEATURES, GOLD, analyze_fn=analyze, assign_fn=assign)

    assert result.accuracy == 1.0
    assert result.false_reject_rate == 0.0
    assert result.scores_known == [0.8]
    assert result.scores_new == []


@pytest.mark.parametrize(("decision", "expected_frr"), [("existing", 0.0), ("new", 1.0)])
def test_holdout_distinguishes_wrong_campaign_from_false_rejection(
    decision: str, expected_frr: float
) -> None:
    def incorrect_assignment(
        new_features: Sequence[Feature],
        base: FakeAnalysis,
        base_features: Sequence[Feature],
        *,
        new_case_ids: Sequence[str] | None = None,
    ) -> list[Assignment]:
        return [
            result.model_copy(
                update={
                    "campaign_id": "predicted-S:Y:c" if decision == "existing" else None,
                    "decision": decision,
                }
            )
            for result in assign(new_features, base, base_features, new_case_ids=new_case_ids)
        ]

    result = holdout_variant(FEATURES, GOLD, analyze_fn=analyze, assign_fn=incorrect_assignment)

    assert result.accuracy == 0.0
    assert result.false_reject_rate == expected_frr


def test_leave_one_campaign_out_includes_each_singleton_even_without_features() -> None:
    result = leave_one_campaign_out(FEATURES, GOLD, analyze_fn=analyze, assign_fn=assign)

    assert result.scores_new == [0.2, 0.2, 0.8, 0.5]
    assert result.accuracy == 0.5
    assert result.false_accept_rate == 0.25
    assert result.review_rate == 0.25


def test_cross_corpus_uses_only_source_corpus_for_the_base() -> None:
    result = cross_corpus(FEATURES, GOLD, "X", "Y", analyze_fn=analyze, assign_fn=assign)

    assert result.scores_known == [0.8]
    assert result.scores_new == [0.8, 0.5]
    assert result.accuracy == pytest.approx(1 / 3)
    assert result.false_accept_rate == 0.5
    assert result.false_reject_rate == 0
    assert result.review_rate == pytest.approx(1 / 3)


def test_calibrate_keeps_the_lowest_cutoff_that_meets_the_far_limit() -> None:
    known, new = [0.70, 0.8, 0.95], [0.1] * 17 + [0.7, 0.7, 0.9]

    tau, margin = calibrate(known, new)

    assert tau == pytest.approx(0.7)
    assert sum(score >= tau for score in new) == 1
    assert sum(score >= tau for score in new) / len(new) <= 0.05
    assert tau >= 0.5
    assert sum(score >= tau for score in known) == 2
    assert margin == 0.1


def test_calibrate_handles_empty_scores_and_score_one() -> None:
    assert calibrate([0.5], [])[0] == 0.5
    assert calibrate([], [1.0])[0] == 1.0


def test_calibrate_applies_the_floor_when_new_scores_are_all_zero() -> None:
    assert calibrate([0.8, 0.95], [0.0, 0.0])[0] == 0.5
    assert calibrate([0.8, 0.95], [0.0, 0.0], floor=0.65)[0] == 0.65


def test_calibrate_uses_the_midpoint_when_scores_are_separated() -> None:
    assert calibrate([0.8, 0.9], [0.2, 0.3])[0] == pytest.approx(0.55)


def test_ablation_uses_registry_and_keeps_cases_without_remaining_features() -> None:
    scores = ablation(FEATURES, GOLD, ["text", "ids"], analyze_fn=analyze)

    assert scores == {"text": 0.0, "ids": 1.0}


def test_input_ablation_uses_case_scoped_artifact_roles_and_keeps_empty_cases() -> None:
    provenance: list[tuple[str, str, Role]] = [
        ("X:a", "same-content", "screenshot"),
        ("Y:b", "ad", "ad_creative"),
        ("Y:c", "same-content", "network"),
        ("X:a", "page", "landing_page"),
        ("Y:b", "asset", "landing_asset"),
        ("X:a", "ad-video", "ad_video"),
        ("Y:c", "recording", "screen_recording"),
    ]
    artifacts = [
        Artifact(id=aid, case_id=cid, kind="text", role=role, path=Path(aid), size=0)
        for cid, aid, role in provenance
    ]
    features = [
        Feature(case_id=cid, artifact_id=aid, name="text.raw", value=LABELS[cid])
        for cid, aid, _ in provenance
    ]
    observed_case_ids = []

    def analyze_all_cases(features: Sequence[Feature], *, case_ids: Sequence[str]) -> FakeAnalysis:
        observed_case_ids.append(list(case_ids))
        return analyze(features, case_ids)

    results = ablation_by_input(features, artifacts, GOLD, analyze_fn=analyze_all_cases)

    assert observed_case_ids == [sorted(GOLD)] * 5
    assert {
        name: (result.scores, result.cases_with_features) for name, result in results.items()
    } == {
        "screenshot_only": (PRF(1.0, 1.0, 1.0), 2),
        "har_only": (PRF(0.0, 0.0, 0.0), 1),
        "html_only": (PRF(1.0, 1.0, 1.0), 2),
        "video_only": (PRF(0.0, 0.0, 0.0), 2),
        "all": (PRF(1.0, 1.0, 1.0), 3),
    }
