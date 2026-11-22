"""Presentation-only labels for known person and brand identifiers."""

from __future__ import annotations

import re

from fakecollector.app import pl
from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import Evidence
from fakecollector.extractors.brand import BRAND_NAMES


def display_value(entity_type: str, value: str) -> str:
    """Return a known display name without changing the stored identifier."""
    if entity_type == "Person":
        return pl.PERSON_DISPLAY_NAMES.get(value, value)
    if entity_type in {"Brand", "BrandLogo"}:
        return BRAND_NAMES.get(value, value)
    return value


def display_evidence(evidence: Evidence) -> str:
    """Use a display name in a known person or brand evidence description."""
    spec = FEATURES.get(evidence.kind)
    if spec is None or not spec.entity_type or not evidence.value:
        return evidence.detail
    return evidence.detail.replace(evidence.value, display_value(spec.entity_type, evidence.value))


def display_description(entity_type: str, text: str) -> str:
    """Replace complete known slugs in a person or brand profile description."""
    names = (
        pl.PERSON_DISPLAY_NAMES
        if entity_type == "Person"
        else BRAND_NAMES
        if entity_type in {"Brand", "BrandLogo"}
        else {}
    )
    for slug in sorted(names, key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", lambda m: names[m.group()], text)
    return text


def display_campaign_label(label: str) -> str:
    """Remove unverified person prefixes from labels produced by older analyses."""
    prefix, separator, rest = label.partition(" · ")
    known = prefix in pl.PERSON_DISPLAY_NAMES or prefix in pl.PERSON_DISPLAY_NAMES.values()
    return rest.replace("{PERSON}", "[osoba]") if separator and known else label
