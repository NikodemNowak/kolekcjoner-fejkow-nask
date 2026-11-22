"""Helpers shared by the exporters: lookups over an `Analysis` and defanging."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass

from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Campaign, Feature
from fakecollector.graph.analyze import Analysis
from fakecollector.graph.entities import entity_type_for

# Colour-blind friendly categorical palette (Okabe-Ito + Tableau extras); cycled per campaign.
PALETTE = (
    "#0072B2",
    "#E69F00",
    "#009E73",
    "#CC79A7",
    "#D55E00",
    "#56B4E9",
    "#F0E442",
    "#4E79A7",
    "#B07AA1",
    "#59A14F",
    "#EDC948",
    "#76B7B2",
)
SINGLETON_COLOUR = "#9E9E9E"
TIER_COLOURS = {
    "campaign": "#C62828",
    "operator": "#6A1B9A",
    "toolkit": "#1565C0",
    "context": "#757575",
}


@dataclass(frozen=True)
class Provenance:
    """Where a case-entity link was observed."""

    feature: str
    artifact_id: str
    locator: str


def campaign_by_case(analysis: Analysis) -> dict[str, Campaign]:
    """Map each case id to its campaign."""
    return {case: c for c in analysis.campaigns for case in c.case_ids}


def campaign_colours(analysis: Analysis) -> dict[str, str]:
    """Give multi-case campaigns a stable palette colour (largest first); singletons grey."""
    ranked = sorted(
        (c for c in analysis.campaigns if len(c.case_ids) > 1),
        key=lambda c: (-len(c.case_ids), c.id),
    )
    colours = {c.id: PALETTE[i % len(PALETTE)] for i, c in enumerate(ranked)}
    for campaign in analysis.campaigns:
        colours.setdefault(campaign.id, SINGLETON_COLOUR)
    return colours


def provenance(features: Collection[Feature]) -> dict[tuple[str, str], list[Provenance]]:
    """Index feature provenance by (case id, entity id), mirroring `build_entities`."""
    index: dict[tuple[str, str], set[Provenance]] = defaultdict(set)
    for feature in features:
        spec = FEATURES.get(feature.name)
        if spec is None or spec.kind not in {"key", "set"} or not feature.value:
            continue
        entity_type = entity_type_for(feature.name, spec)
        if entity_type is None:
            continue
        index[feature.case_id, f"{entity_type}:{feature.value}"].add(
            Provenance(feature.name, feature.artifact_id, feature.locator)
        )
    return {
        key: sorted(items, key=lambda p: (p.feature, p.artifact_id, p.locator))
        for key, items in index.items()
    }


def entity_families() -> dict[str, str]:
    """Map each graph entity type to its signal family (first registry row wins)."""
    families: dict[str, str] = {}
    for name, spec in sorted(FEATURES.items()):
        entity_type = entity_type_for(name, spec)
        if entity_type is not None:
            families.setdefault(entity_type, spec.family)
    return families


def defang(value: str) -> str:
    """Defang a domain, IP or URL for publication: `example[.]com`, `hxxps://…`."""
    if "://" in value:
        scheme, rest = value.split("://", 1)
        host, sep, tail = rest.partition("/")
        scheme = scheme.replace("http", "hxxp")
        return f"{scheme}://{host.replace('.', '[.]')}{sep}{tail}"
    return value.replace(".", "[.]")
