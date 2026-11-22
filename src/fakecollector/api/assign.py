"""Readable verdicts for new material, built from `assign_new` answers."""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from fakecollector.api import pl
from fakecollector.api.found import Found, SimilarCampaign, build_found, build_similar
from fakecollector.api.views import FACE_THRESHOLD, FAMILIES, Ref, RunData, Value, case_title
from fakecollector.core.schemas import Artifact, Assignment, Feature
from fakecollector.graph.assign import NEAREST_KIND
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.coverage import INSUFFICIENT_DATA

MAX_REASONS = 6
# `assign_new` builds its EdgeConfig from defaults (only the seed varies), so these match it.
_CFG = EdgeConfig()


class Reason(BaseModel):
    """One readable reason behind a verdict."""

    family: str
    family_label: str
    tier: str
    tier_label: str
    label: str
    text: Value
    weight: float
    matched: list[str]


class Verdict(BaseModel):
    """The answer card for one analysed input."""

    case_id: str
    decision: str
    title: str
    plain: str = ""
    explanation: str
    score: float
    margin: float
    threshold: float
    min_margin: float
    strong_link: float
    campaign: Ref | None
    closest: Ref | None
    closest_score: float
    operator: Ref | None
    toolkits: list[Ref]
    duplicate_of: str | None
    reasons: list[Reason]
    hints: list[str]
    comparable: list[Ref]
    missing: list[Ref]
    flags: list[str]
    # What was recognised and the closest known campaigns; see api/found.py for the contract.
    found: Found = Found()
    similar: list[SimilarCampaign] = []


def _plain(decision: str, campaign: Ref | None, reasons: list[Reason]) -> str:
    """The first line of a verdict, in words a newcomer understands."""
    if decision == "insufficient":
        return pl.PLAIN_VERDICT_INSUFFICIENT
    if decision == "new" or campaign is None:
        return pl.PLAIN_VERDICT_NEW if decision == "new" else pl.PLAIN_VERDICT_REVIEW_BARE
    name = campaign.label.replace("[osoba]", "…").rstrip(".")
    if decision == "review":
        return pl.PLAIN_VERDICT_REVIEW.format(campaign=name)
    strong = [r.label for r in reasons if r.tier in {"campaign", "operator"}]
    labels = [label[0].lower() + label[1:] for label in dict.fromkeys(strong)][:2]
    if not labels:
        return pl.PLAIN_VERDICT_EXISTING_BARE.format(campaign=name)
    return pl.PLAIN_VERDICT_EXISTING.format(campaign=name, reasons=" i ".join(labels))


def _plain_found(found: Found, similar: list[SimilarCampaign], decision: str) -> str:
    """Second part of the first line: who was recognised, and where else they appear."""
    items: list[str] = []
    by_face = {p.slug for p in found.persons if p.method == "face"}
    for person in found.persons:
        if person.method == "text" and person.slug in by_face:
            continue  # the face line already names this person
        if person.method == "face":
            item = pl.PLAIN_FOUND_FACE.format(name=person.name, similarity=person.similarity_text)
        else:
            item = pl.PLAIN_FOUND_TEXT.format(name=person.name)
        if item not in items:
            items.append(item)
    if not items:
        return ""
    text = pl.PLAIN_FOUND.format(items=", ".join(items[:4]))
    if decision != "existing":
        for person in found.persons:
            if person.campaigns:
                name = person.campaigns[0].label.replace("[osoba]", "…").rstrip(".")
                text += pl.PLAIN_SAME_PERSON.format(name=person.name, campaign=name)
                break
    return text


def verdict(
    answer: Assignment,
    data: RunData,
    features: list[Feature] | None = None,
    artifacts: list[Artifact] | None = None,
) -> Verdict:
    """Turn an assignment into a readable verdict card.

    `features` / `artifacts` of the new material (from `assign_new(features_out=…)`) fill
    `found` and the person/brand traces of `similar`; without them both stay minimal.
    """
    insufficient = answer.decision == "new" and INSUFFICIENT_DATA in answer.flags
    decision = "insufficient" if insufficient else answer.decision
    hints = [e for e in answer.evidence if e.kind == "url.schema" and e.weight == 0]
    # The "nearest campaign" note is shown as its own block (closest / closest_score), built
    # from the numbers; its technical sentence never goes into the list of reasons.
    evidence = [
        e
        for e in answer.evidence
        if e.kind != NEAREST_KIND and not (e.kind == "url.schema" and e.weight == 0)
    ]

    # Which known campaigns the evidence points at, by summed weight.
    by_campaign: dict[str, float] = defaultdict(float)
    matched_cases: dict[int, list[str]] = {}
    for index, item in enumerate(evidence):
        cases = []
        for ref in item.artifacts:
            artifact_id = ref.split("#", 1)[0]
            case = data.case_of_artifact.get(artifact_id)
            if case:
                cases.append(case)
                campaign = data.campaign_of.get(case)
                if campaign:
                    by_campaign[campaign.id] = max(by_campaign[campaign.id], item.weight)
        matched_cases[index] = sorted(set(cases))
    nearest = next((e.value for e in answer.evidence if e.kind == NEAREST_KIND), None)
    closest_id = (
        answer.campaign_id
        or (nearest if nearest in data.campaigns else None)
        or (max(by_campaign, key=lambda c: by_campaign[c]) if by_campaign else None)
    )

    reasons: list[Reason] = []
    seen: set[tuple[str, str]] = set()
    order = sorted(range(len(evidence)), key=lambda i: -evidence[i].weight)
    for index in order:
        item = evidence[index]
        text = data.evidence_text(item)
        key = (item.family, text.text)
        if key in seen:
            continue
        seen.add(key)
        reasons.append(
            Reason(
                family=item.family,
                family_label=pl.family_label(item.family),
                tier=item.tier,
                tier_label=pl.REPORT_TIERS.get(item.tier, pl.REPORT_TIERS["context"]),
                label=pl.kind_label(item.kind),
                text=text,
                weight=item.weight,
                matched=[case_title(c) for c in matched_cases[index]][:3],
            )
        )
        if len(reasons) >= MAX_REASONS:
            break
    found = build_found(answer.case_id, features or [], artifacts or [], data, FACE_THRESHOLD)
    similar = build_similar(answer.case_id, features or [], answer.evidence, data)
    comparable = [f for f in FAMILIES if f in answer.comparable]
    missing = [f for f in FAMILIES if f not in answer.comparable]
    return Verdict(
        case_id=answer.case_id,
        decision=decision,
        title=pl.DECISIONS[decision],
        plain=_plain(decision, data.ref(closest_id), reasons)
        + _plain_found(found, similar, decision),
        explanation=pl.DECISION_TEXT[decision],
        score=answer.score,
        margin=answer.margin,
        threshold=_CFG.tau_assign,
        min_margin=_CFG.assign_margin,
        strong_link=_CFG.strong_link,
        campaign=data.ref(answer.campaign_id) if answer.decision == "existing" else None,
        closest=data.ref(closest_id),
        closest_score=by_campaign.get(closest_id or "", answer.score),
        operator=data.operator_ref(answer.operator_id),
        toolkits=[data.toolkit_ref(t) for t in answer.toolkits],
        duplicate_of=case_title(answer.duplicate_of) if answer.duplicate_of else None,
        reasons=reasons,
        hints=[h.detail for h in hints],
        comparable=[Ref(id=f, label=pl.family_label(f)) for f in comparable],
        missing=[Ref(id=f, label=pl.family_label(f)) for f in missing],
        flags=[pl.flag_label(f) for f in answer.flags],
        found=found,
        similar=similar,
    )
