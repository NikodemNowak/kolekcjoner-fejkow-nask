from typing import get_args

from fakecollector.core.registry import FEATURES, FeatureSpec
from fakecollector.core.schemas import Family, Tier


def test_every_row_has_valid_family_tier_and_ranges() -> None:
    for name, spec in FEATURES.items():
        assert spec.family in get_args(Family), name
        assert spec.tier in get_args(Tier), name
        assert 0.0 <= spec.weight <= 1.0, name
        assert 0.0 < spec.max_df <= 1.0, name


def test_names_are_dotted_family_prefixes() -> None:
    for name in FEATURES:
        prefix, _, rest = name.partition(".")
        assert prefix and rest, name


def test_workstream_a_signals_are_registered() -> None:
    for name in [
        "ids.kit_landing",
        "ids.kit_tenant",
        "ids.fb_pixel",
        "asset.sha256",
        "infra.host_3p",
        "url.schema",
        "html.dom_minhash",
        "kit.path_sig",
        "text.raw",
        "html.title",
    ]:
        assert name in FEATURES, name


def test_workstream_b_rows_match_their_pr() -> None:
    assert FEATURES["img.phash"] == FeatureSpec(
        "image",
        "campaign",
        None,
        0.8,
        0.3,
        kind="hash",
        lo=0.86,
        hi=0.97,
        detail_pl="Podobny skrót obrazu (odległość {value})",
    )
    assert FEATURES["url.domain"] == FeatureSpec(
        "ids", "campaign", "Domain", 0.9, 0.3, detail_pl="Wspólna domena: {value}"
    )


def test_operator_tier_ids_never_claim_campaign_tier() -> None:
    # Review focus 1: tenant / pixel link operators, not campaigns.
    for name in ["ids.kit_tenant", "ids.fb_pixel", "ids.gtag"]:
        assert FEATURES[name].tier == "operator", name
