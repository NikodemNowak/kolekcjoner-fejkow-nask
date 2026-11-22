from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isclose
from statistics import mean
from typing import Literal

from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Assignment, Campaign, Edge, Entity, Evidence, Feature
from fakecollector.graph.analyze import Analysis
from fakecollector.graph.blocking import PDQ, candidate_pairs, image_hash_value
from fakecollector.graph.cluster import (
    attach_operators,
    attach_toolkits,
    cluster,
    label_campaigns,
    operators,
    toolkits,
)
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import EntityLink, build_entities, entity_type_for
from fakecollector.graph.fusion import (
    build_edges,
    edges_for,
    fuse,
    passes_campaign_gate,
    slot_signals,
)
from fakecollector.graph.signals import evidence_order, siglip_usable
from fakecollector.graph.vectors import best_vector_match

type FeatureSignature = tuple[str, str, tuple[float, ...] | None]
type VectorMatch = tuple[float, list[Feature]]

# Keys that may corroborate a cross-modal vector lead. `text.topic` is not one of them: a
# handful of topics covers every scam, so a shared topic says nothing about which campaign.
# Generic context (`brand.logo` trust badges, `ocr.domain`) is excluded for the same reason.
_CROSSMODAL_KEYS = {"person.public_figure", "brand.impersonated", "ad.advertiser"}


def _without_toolkit(edge: Edge, cfg: EdgeConfig) -> float:
    """The edge's fused score recomputed without toolkit-tier evidence."""
    return fuse(slot_signals([item for item in edge.evidence if item.tier != "toolkit"]), cfg)


def assign(
    new_features: Sequence[Feature],
    base: Analysis,
    base_features: Sequence[Feature],
    cfg: EdgeConfig | None = None,
    new_case_ids: Sequence[str] | None = None,
) -> list[Assignment]:
    """Assign new cases against fixed base campaigns with combined corpus statistics."""
    cfg = cfg or EdgeConfig()
    new_ids = sorted(set(new_case_ids or ()).union(feature.case_id for feature in new_features))
    if not new_ids:
        return []

    features = [*base_features, *new_features]
    base_ids = set(base.case_ids)
    ids = base_ids.union(new_ids)
    entities, links = build_entities(features, cfg=cfg, case_ids=ids)
    by_entity, by_case = _active_memberships(entities, links)
    combined_operators = operators(ids, entities, links)
    base_by_case = _features_by_case(base_features)
    new_by_case = _features_by_case(new_features)
    duplicate_index = _DuplicateIndex(base_by_case)

    campaign_by_case = {
        case: campaign.id for campaign in base.campaigns for case in campaign.case_ids
    }
    campaigns = {campaign.id: campaign for campaign in base.campaigns}
    crossmodal = _CrossmodalIndex(base_features, campaign_by_case, entities, cfg, len(ids))

    assignments = []
    for case in new_ids:
        other_base_cases = base_ids - {case} if case in base_ids else base_ids
        shared_base = [
            (entity, by_entity[entity.id] & other_base_cases)
            for entity in by_case[case]
            if not by_entity[entity.id].isdisjoint(other_base_cases)
        ]
        operator_peers = {
            peer for entity, peers in shared_base if entity.tier == "operator" for peer in peers
        }
        known = {base.operators[peer] for peer in operator_peers if peer in base.operators}
        operator_id = None
        if len(known) == 1:
            operator_id = next(iter(known))
        elif not known and operator_peers:
            operator_id = combined_operators[case]

        pairs = [(min(case, peer), max(case, peer)) for peer in other_base_cases]
        edges = edges_for(
            case, features, entities, links, cfg, case_ids=ids, pairs=pairs, keep_subthreshold=True
        )
        duplicate = duplicate_index.find(new_by_case[case], campaign_by_case)
        assignments.append(
            _assignment(
                case,
                edges,
                campaign_by_case,
                campaigns,
                operator_id,
                sorted(entity.id for entity, _ in shared_base if entity.tier == "toolkit"),
                duplicate,
                cfg,
                crossmodal,
                new_by_case[case],
            )
        )
    return assignments


def cluster_new(
    assignments: Sequence[Assignment],
    new_features: Sequence[Feature],
    base: Analysis,
    base_features: Sequence[Feature],
    cfg: EdgeConfig | None = None,
) -> list[Campaign]:
    """Group cases assigned as new using the same corpus statistics as assignment."""
    new_ids = {item.case_id for item in assignments if item.decision == "new"} - set(base.case_ids)
    if not new_ids:
        return []
    cfg = cfg or EdgeConfig()
    features = [*base_features, *new_features]
    ids = set(base.case_ids).union(item.case_id for item in assignments)
    entities, links = build_entities(features, cfg=cfg, case_ids=ids)
    pairs = {
        (a, b)
        for a, b in candidate_pairs(entities, links, features, cfg)
        if a in new_ids and b in new_ids
    }
    edges = build_edges(features, entities, links, cfg, case_ids=ids, pairs=pairs)
    campaigns = cluster(new_ids, edges, cfg)
    known = {
        item.case_id: item.operator_id
        for item in assignments
        if item.case_id in new_ids and item.operator_id is not None
    }
    local = operators(new_ids, entities, links)
    attach_operators(campaigns, _inherit_operators(known, local))
    attach_toolkits(campaigns, toolkits(new_ids, entities, links))
    label_campaigns(campaigns, new_features)
    return campaigns


def _inherit_operators(known: dict[str, str], local: dict[str, str]) -> dict[str, str]:
    by_operator: dict[str, set[str]] = defaultdict(set)
    for case, operator in known.items():
        if case in local:
            by_operator[local[case]].add(operator)
    result = known.copy()
    for case, local_id in local.items():
        matches = by_operator[local_id]
        if not matches:
            result[case] = local_id
        elif len(matches) == 1:
            result[case] = next(iter(matches))
    return result


def _features_by_case(features: Sequence[Feature]) -> defaultdict[str, list[Feature]]:
    by_case: defaultdict[str, list[Feature]] = defaultdict(list)
    for feature in features:
        by_case[feature.case_id].append(feature)
    return by_case


def _active_memberships(
    entities: Collection[Entity], links: Collection[EntityLink]
) -> tuple[dict[str, set[str]], defaultdict[str, list[Entity]]]:
    active = {
        entity.id: entity
        for entity in entities
        if not entity.stop and entity.tier in {"operator", "toolkit"}
    }
    by_entity: dict[str, set[str]] = defaultdict(set)
    for case, entity_id, _ in links:
        if entity_id in active:
            by_entity[entity_id].add(case)
    by_case: defaultdict[str, list[Entity]] = defaultdict(list)
    for entity_id, cases in by_entity.items():
        for case in cases:
            by_case[case].append(active[entity_id])
    return by_entity, by_case


class _DuplicateIndex:
    def __init__(self, base_by_case: dict[str, list[Feature]]) -> None:
        self.by_signature: dict[frozenset[tuple[FeatureSignature, int]], str] = {}
        self.by_artifacts: dict[frozenset[str], str] = {}
        self.artifact_cases: dict[str, set[str]] = defaultdict(set)
        self.pdq_cases: dict[int, set[str]] = defaultdict(set)
        for case, features in sorted(base_by_case.items()):
            if signature := self._signature(features):
                self.by_signature.setdefault(signature, case)
            if artifacts := self._artifacts(features):
                self.by_artifacts.setdefault(artifacts, case)
                for artifact in artifacts:
                    self.artifact_cases[artifact].add(case)
            for pdq in self._pdq_hashes(features):
                self.pdq_cases[pdq].add(case)

    def find(self, features: Sequence[Feature], campaign_by_case: Mapping[str, str]) -> str | None:
        """Prefer exact case matches, then a base case that contains the whole input."""
        artifacts = self._artifacts(features)
        candidates = (
            self.by_signature.get(self._signature(features)),
            self.by_artifacts.get(artifacts),
        )
        exact = min((case for case in candidates if case is not None), default=None)
        if exact is not None:
            return exact
        return self._containing(features, campaign_by_case)

    def _containing(
        self, features: Sequence[Feature], campaign_by_case: Mapping[str, str]
    ) -> str | None:
        # A partial re-submission (one screenshot, a re-encoded creative, the video of a known
        # case) is a duplicate only when *every* file of the input is already in one base case,
        # by artifact hash or, for images, by PDQ distance 0. One shared file out of many is
        # not a re-submission: template assets, kit loaders and stock mock-ups recur across
        # unrelated campaigns, so they stay ordinary (weighted, df-capped) edge evidence.
        by_artifact: dict[str, list[Feature]] = defaultdict(list)
        for feature in features:
            by_artifact[feature.artifact_id].append(feature)
        covering: set[str] | None = None
        for artifact, artifact_features in by_artifact.items():
            holders = set(self.artifact_cases.get(artifact, ()))
            for pdq in self._pdq_hashes(artifact_features):
                holders |= self.pdq_cases.get(pdq, set())
            covering = holders if covering is None else covering & holders
            if not covering:
                return None
        if not covering:
            return None
        # Several holders are fine only when they agree on one campaign (a hub file shared by
        # unrelated campaigns must not become a score-1.0 duplicate).
        if len({campaign_by_case.get(case, case) for case in covering}) != 1:
            return None
        return min(covering)

    @staticmethod
    def _pdq_hashes(features: Sequence[Feature]) -> set[int]:
        return {
            value
            for feature in features
            if feature.name == PDQ and (value := image_hash_value(feature)) is not None
        }

    @staticmethod
    def _signature(features: Sequence[Feature]) -> frozenset[tuple[FeatureSignature, int]]:
        signatures: Counter[FeatureSignature] = Counter(
            (feature.name, feature.value, None if feature.vector is None else tuple(feature.vector))
            for feature in features
            if (spec := FEATURES.get(feature.name)) is not None and spec.kind != "info"
        )
        # Operator, toolkit and context signatures can be shared by unrelated campaigns.
        if not any(FEATURES[name].tier == "campaign" for name, _, _ in signatures):
            return frozenset()
        return frozenset(signatures.items())

    @staticmethod
    def _artifacts(features: Sequence[Feature]) -> frozenset[str]:
        return frozenset(feature.artifact_id for feature in features if feature.artifact_id)


@dataclass(frozen=True)
class _CrossmodalMatch:
    campaign: str
    margin: float
    corroborated: bool
    vectors: dict[str, VectorMatch]


class _CrossmodalIndex:
    def __init__(
        self,
        features: Sequence[Feature],
        campaign_by_case: Mapping[str, str],
        entities: Sequence[Entity],
        cfg: EdgeConfig,
        corpus_size: int,
    ) -> None:
        self.thresholds = {"text.bge": cfg.crossmodal_bge, "img.siglip": cfg.crossmodal_siglip}
        self.margin = cfg.crossmodal_margin
        self.cfg = cfg
        # Portrait-like images and down-weighted rows (cloaking variants) never lead alone.
        features = self._leads(features)
        self.corpus_size = corpus_size
        self.active_entities = {entity.id for entity in entities if not entity.stop}
        self.by_campaign: dict[str, list[Feature]] = defaultdict(list)
        # Specificity of each corroborating key: the base campaigns that carry it. A key is
        # discriminative only when exactly one campaign has it (campaign frequency 1, the
        # label-free IDF floor); a face or brand seen in several campaigns names none of them.
        self.campaign_by_case = campaign_by_case
        self.key_cases: dict[tuple[str, str], set[str]] = defaultdict(set)
        for feature in features:
            if feature.case_id in campaign_by_case and feature.name in _CROSSMODAL_KEYS:
                self.key_cases[(feature.name, feature.value)].add(feature.case_id)
        for feature in features:
            campaign = campaign_by_case.get(feature.case_id)
            if campaign is not None and (
                feature.name in self.thresholds or feature.name in _CROSSMODAL_KEYS
            ):
                self.by_campaign[campaign].append(feature)

    def match(self, case: str, features: Sequence[Feature]) -> _CrossmodalMatch | None:
        """Find the strongest unambiguous vector lead and its campaign corroboration."""
        matches: dict[str, dict[str, VectorMatch]] = defaultdict(dict)
        features = self._leads(features)
        for name in self.thresholds:
            query = [feature for feature in features if feature.name == name]
            if not query:
                continue
            for campaign, members in self.by_campaign.items():
                candidates = [f for f in members if f.name == name and f.case_id != case]
                if (match := best_vector_match(query, candidates)) is not None:
                    matches[name][campaign] = match

        query_keys = {
            (f.name, f.value)
            for f in features
            if f.name in _CROSSMODAL_KEYS
            and f"{entity_type_for(f.name, FEATURES[f.name])}:{f.value}" in self.active_entities
        }
        leads = {}
        for name, by_campaign in matches.items():
            if (lead := self._lead(name, by_campaign)) is not None:
                leads[name] = lead
        results = []
        for name, (campaign, margin) in leads.items():
            vectors = {
                kind: match
                for kind, group in matches.items()
                if (match := group.get(campaign)) is not None
                and _meets(match[0], self.thresholds[kind])
            }
            family = FEATURES[name].family
            # The other vector corroborates only when it independently leads the same campaign
            # by the same margin; clearing the threshold alone is common for unrelated scams.
            other_vector = any(
                FEATURES[kind].family != family and lead[0] == campaign
                for kind, lead in leads.items()
            )
            corroborated = other_vector or any(
                FEATURES[key[0]].family != family and self._campaigns_with(key, case) == {campaign}
                for key in query_keys
            )
            results.append(_CrossmodalMatch(campaign, margin, corroborated, vectors))
        return max(results, key=lambda lead: (lead.corroborated, lead.margin), default=None)

    def _leads(self, features: Sequence[Feature]) -> list[Feature]:
        return [
            feature
            for feature in siglip_usable(features, self.cfg)
            if feature.name not in self.thresholds or feature.confidence >= 1.0
        ]

    def _campaigns_with(self, key: tuple[str, str], case: str) -> set[str]:
        return {self.campaign_by_case[peer] for peer in self.key_cases.get(key, ()) if peer != case}

    def _lead(self, name: str, by_campaign: Mapping[str, VectorMatch]) -> tuple[str, float] | None:
        # A missing rival embedding cannot establish separation in this feature space.
        if len(by_campaign) < 2:
            return None
        ranked = sorted(by_campaign, key=lambda c: (-by_campaign[c][0], c))
        cosine = by_campaign[ranked[0]][0]
        margin = cosine - by_campaign[ranked[1]][0]
        if not (_meets(cosine, self.thresholds[name]) and _meets(margin, self.margin)):
            return None
        return ranked[0], margin

    def evidence(self, match: _CrossmodalMatch, edges: Sequence[Edge]) -> list[Evidence]:
        """Explain the raw comparisons even when their batch contribution is zero."""
        evidence = []
        for name, (cosine, matched) in match.vectors.items():
            spec = FEATURES[name]
            value = f"cos {cosine:.2f}"
            evidence.append(
                Evidence(
                    family=spec.family,
                    tier=spec.tier,
                    kind=name,
                    value=value,
                    detail=spec.detail_pl.format(
                        kind=name, value=value, df=0, n=self.corpus_size, sim=cosine
                    ),
                    weight=max(
                        (
                            item.weight
                            for edge in edges
                            for item in edge.evidence
                            if item.kind == name
                        ),
                        default=0.0,
                    ),
                    artifacts=sorted(
                        {
                            f"{f.artifact_id}#{f.locator}" if f.locator else f.artifact_id
                            for f in matched
                        }
                    ),
                )
            )
        return evidence


def dedupe_evidence(items: Iterable[Evidence]) -> list[Evidence]:
    """One line per (kind, detail): the same trace seen in several members of a campaign.

    Keeps the strongest weight and the union of artifacts; ordered strongest first.
    """
    merged: dict[tuple[str, str], Evidence] = {}
    for item in items:
        key = (item.kind, item.detail)
        if (seen := merged.get(key)) is None:
            merged[key] = item
            continue
        merged[key] = seen.model_copy(
            update={
                "weight": max(seen.weight, item.weight),
                "artifacts": sorted({*seen.artifacts, *item.artifacts}),
            }
        )
    return sorted(merged.values(), key=evidence_order)


NEAREST_KIND = "assign.nearest"
"""`Evidence.kind` of the weight-0 note on a `new` / `review` answer: the closest campaign."""


def _nearest_note(
    campaign_id: str,
    campaign: Campaign,
    score: float,
    margin: float,
    used: Sequence[Edge],
    decision: str,
    cfg: EdgeConfig,
) -> Evidence:
    """Polish note: which campaign came closest, how far below τ, and why it was not linked."""
    tau = cfg.tau_assign
    anchored = bool(used) and passes_campaign_gate(used[0], cfg)
    if score < tau:
        why = f"wynik {score:.2f} jest o {tau - score:.2f} poniżej progu τ = {tau:.2f}"
    elif not anchored:
        why = f"wynik {score:.2f} ≥ τ = {tau:.2f}, ale brak mocnego dowodu kampanii"
    else:
        why = f"przewaga nad kolejną kampanią {margin:.2f} < wymagane {cfg.assign_margin:.2f}"
    if not anchored and score < tau:
        why += "; brak mocnego dowodu kampanii (np. wspólnej domeny, pliku lub nagłówka)"
    name = f"„{campaign.label}” ({campaign_id})" if campaign.label else campaign_id
    verdict = "do weryfikacji" if decision == "review" else "nie przypisano"
    family = used[0].evidence[0].family if used and used[0].evidence else "text"
    return Evidence(
        family=family,
        tier="context",
        kind=NEAREST_KIND,
        value=campaign_id,
        detail=f"Najbliższa kampania: {name} — {verdict}: {why}.",
        weight=0.0,
        artifacts=[],
    )


def _meets(value: float, threshold: float) -> bool:
    return value >= threshold or isclose(value, threshold, rel_tol=0.0, abs_tol=1e-12)


def _assignment(
    case: str,
    edges: Sequence[Edge],
    campaign_by_case: dict[str, str],
    campaigns: Mapping[str, Campaign],
    operator_id: str | None,
    toolkits: list[str],
    duplicate: str | None,
    cfg: EdgeConfig,
    crossmodal: _CrossmodalIndex,
    new_features: Sequence[Feature],
) -> Assignment:
    by_campaign: dict[str, list[Edge]] = defaultdict(list)
    for edge in sorted(edges, key=lambda edge: (-edge.score, edge.src, edge.dst)):
        peer = edge.dst if edge.src == case else edge.src
        if peer in campaign_by_case:
            by_campaign[campaign_by_case[peer]].append(edge)

    duplicate_campaign = campaign_by_case.get(duplicate) if duplicate is not None else None
    if duplicate_campaign is not None:
        by_campaign.setdefault(duplicate_campaign, [])

    # Keep the strongest link for sparse uploads and use the comparable mean to break ties.
    ranked = []
    for campaign, matches in by_campaign.items():
        peak = matches[0].score if matches else 0.0
        if matches and len({family for edge in matches for family in edge.comparable}) <= 3:
            k = min(3, len(campaigns[campaign].case_ids))
            peak = max(peak, mean(edge.score for edge in matches[:k]))
        score = 1.0 if campaign == duplicate_campaign else peak
        average = mean(edge.score for edge in matches) if matches else 0.0
        ranked.append((score, average, campaign, matches))
    ranked.sort(key=lambda row: (-row[0], row[2] != duplicate_campaign, -row[1], row[2]))
    score, _, best, used = ranked[0] if ranked else (0.0, 0.0, None, [])
    runner_score, _, _, runner_matches = ranked[1] if len(ranked) > 1 else (0.0, 0.0, None, [])
    margin = score - runner_score
    comparable = sorted({family for edge in edges for family in edge.comparable})
    margin_met = margin >= cfg.assign_margin or isclose(margin, cfg.assign_margin, abs_tol=1e-12)
    best_pair = used[0] if used else None
    runner_pair = runner_matches[0] if runner_matches else None
    competing_link = (
        not margin_met and runner_pair is not None and passes_campaign_gate(runner_pair, cfg)
    )
    # A strong edge can bypass the margin when the rival has weaker support.
    strong = score >= cfg.strong_link and not (competing_link and runner_score >= cfg.strong_link)
    decision: Literal["existing", "new", "review"] = "new"
    raw_evidence: list[Evidence] = []
    if duplicate_campaign is not None or (
        best_pair is not None
        and passes_campaign_gate(best_pair, cfg)
        and (strong or (score >= cfg.tau_assign and margin_met))
    ):
        decision = "existing"
    elif (match := crossmodal.match(case, new_features)) is not None:
        best = match.campaign
        score, _, _, used = next(row for row in ranked if row[2] == best)
        margin = score - max((row[0] for row in ranked if row[2] != best), default=0.0)
        # A vector lead plus a shared face or brand names the campaign only when the edge
        # carries campaign-tier evidence or reaches the review score; otherwise a look-alike
        # picture of a well-known person is a question for the analyst, not a link.
        anchored = score >= cfg.review_min_score or any(
            item.tier == "campaign" and item.weight > 0
            for edge in used[:3]
            for item in edge.evidence
        )
        decision = "existing" if match.corroborated and anchored else "review"
        raw_evidence = crossmodal.evidence(match, used)
    elif best_pair is not None and (
        # The review threshold ignores toolkit-tier evidence: a kit is software sold to many
        # operators, so "known operator + known kit" alone stays `new` (with operator_id and
        # toolkits set), while operator or context evidence can still ask for review.
        _without_toolkit(best_pair, cfg) >= cfg.review_min_score
        or any(
            item.tier == "campaign" and item.weight >= cfg.review_min_campaign_evidence
            for item in best_pair.evidence
        )
        or competing_link
    ):
        decision = "review"

    # A campaign has at most one operator (ADR 0004). Conflicts can indicate a multi-story capture.
    best_operator = campaigns[best].operator_id if best is not None else None
    if (
        decision == "existing"
        and duplicate_campaign is None
        and operator_id is not None
        and best_operator is not None
        and operator_id != best_operator
    ):
        decision = "review"

    raw_kinds = {item.kind for item in raw_evidence}
    edge_evidence = dedupe_evidence(
        item for edge in used[:3] for item in edge.evidence if item.kind not in raw_kinds
    )
    evidence = sorted(raw_evidence + edge_evidence[: 10 - len(raw_evidence)], key=evidence_order)
    if decision != "existing" and best is not None and score > 0:
        evidence.append(_nearest_note(best, campaigns[best], score, margin, used, decision, cfg))
    return Assignment(
        case_id=case,
        decision=decision,
        campaign_id=best if decision != "new" else None,
        score=score,
        margin=margin,
        operator_id=operator_id,
        toolkits=toolkits,
        duplicate_of=duplicate,
        comparable=comparable,
        evidence=evidence,
    )
