"""Where a SigLIP logo match sits decides impersonation vs trust badge (no model needed)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors import brand
from fakecollector.extractors.image_embed import brand_features


def _art(role: str) -> Artifact:
    return Artifact(
        id="a" * 16,
        case_id="T:1",
        kind="image",
        role=role,
        path=Path("x.png"),
        size=1,  # type: ignore[arg-type]
    )


@pytest.fixture
def every_part_is_tvn24(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brand, "match_brands", lambda parts: [("tvn24", 0.9, loc) for loc in parts])


def _names(feats: list[Feature]) -> set[tuple[str, str, str]]:
    return {(f.name, f.value, f.locator) for f in feats}


V = np.zeros(4, dtype=np.float32)


@pytest.mark.usefixtures("every_part_is_tvn24")
def test_header_logo_is_impersonation() -> None:
    feats = brand_features(_art("screenshot"), {"header": V, "tile 0,0,100": V}, set())
    assert _names(feats) == {("brand.impersonated", "tvn24", "header")}


@pytest.mark.usefixtures("every_part_is_tvn24")
def test_trust_badge_asset_is_context_only() -> None:
    # A TVN24 "as seen on" badge image on a supplement lander must not claim impersonation.
    feats = brand_features(_art("landing_asset"), {"": V}, set())
    assert _names(feats) == {("brand.logo", "tvn24", "")}


@pytest.mark.usefixtures("every_part_is_tvn24")
def test_tile_match_alone_is_dropped() -> None:
    # Blue UI bars in a lower tile once read as WP: a tile has no placement, so no feature.
    assert brand_features(_art("screenshot"), {"tile 111,555,222": V}, set()) == []


@pytest.mark.usefixtures("every_part_is_tvn24")
def test_page_title_corroborates_a_badge_or_tile() -> None:
    feats = brand_features(_art("landing_asset"), {"": V}, {"tvn24"})
    assert _names(feats) == {("brand.impersonated", "tvn24", "")}
    feats = brand_features(_art("screenshot"), {"tile 0,0,100": V}, {"tvn24"})
    assert _names(feats) == {("brand.impersonated", "tvn24", "tile 0,0,100")}
