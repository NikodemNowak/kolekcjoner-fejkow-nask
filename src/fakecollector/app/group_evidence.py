"""Reconstruct group evidence from the persisted case-to-entity graph."""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from fakecollector.graph.analyze import Analysis


class EvidenceSource(BaseModel):
    """A case and the artifacts that connect it to a shared entity."""

    case_id: str
    artifacts: list[str]


class GroupEvidence(BaseModel):
    """A shared entity and its case-specific provenance."""

    entity_type: str
    value: str
    sources: list[EvidenceSource]


def group_evidence(analysis: Analysis) -> dict[str, dict[str, list[GroupEvidence]]]:
    """Return direct evidence for operator and toolkit groups, including old runs."""
    by_entity: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    case_ids = set(analysis.case_ids)
    for case, entity_id, artifact in analysis.links:
        if case in case_ids:
            by_entity[entity_id][case].add(artifact)
    grouped: dict[str, dict[str, list[GroupEvidence]]] = {"operator": {}, "toolkit": {}}
    for entity in sorted(analysis.entities, key=lambda item: item.id):
        if entity.stop or entity.tier not in {"operator", "toolkit"}:
            continue
        tier = entity.tier
        members: dict[str, dict[str, set[str]]] = defaultdict(dict)
        for case, artifacts in by_entity.get(entity.id, {}).items():
            if tier == "operator":
                operator = analysis.operators.get(case)
                if operator:
                    members[operator][case] = artifacts
            elif entity.id in analysis.toolkits.get(case, []):
                members[entity.id][case] = artifacts
        for group, cases in members.items():
            if len(cases) < 2:
                continue
            sources = [
                EvidenceSource(case_id=case, artifacts=sorted(artifacts))
                for case, artifacts in sorted(cases.items())
            ]
            grouped[tier].setdefault(group, []).append(
                GroupEvidence(entity_type=entity.type, value=entity.value, sources=sources)
            )
    return grouped
