from __future__ import annotations

from fakecollector.core.schemas import Campaign, Entity, Feature
from fakecollector.graph.analyze import analyze
from fakecollector.graph.profile import fill_traits, plural, rotating_summary, traits


def feat(case: str, name: str, value: str) -> Feature:
    return Feature(case_id=case, artifact_id=f"{case}-art", name=name, value=value)


def campaign_features() -> list[Feature]:
    members = ("F:a", "F:b", "F:c")
    features = []
    for i, case in enumerate(members):
        features += [
            feat(case, "ids.kit_landing", "landing-1111"),
            feat(case, "url.domain", f"scam{i}.example"),
            feat(case, "ids.fb_pixel", "4567"),
            feat(case, "asset.sha256", "shared-hero"),
            feat(case, "asset.sha256", "shared-css"),
        ]
    for case in ("F:x", "F:y", "F:z"):
        features += [
            feat(case, "url.domain", f"{case[2:]}.other"),
            feat(case, "asset.sha256", f"own-{case}"),
        ]
    return features


def test_shared_landing_is_constant_and_domains_rotate() -> None:
    analysis = fill_traits(analyze(campaign_features()))
    (campaign,) = [c for c in analysis.campaigns if "F:a" in c.case_ids]
    assert campaign.case_ids == ["F:a", "F:b", "F:c"]
    landing = next(t for t in campaign.traits if t.entity_type == "KitLanding")
    assert landing.kind == "constant"
    assert landing.coverage == 1.0
    assert landing.lift == 2.0  # every member has it, half of the corpus does
    assert landing.why.startswith("Ten sam identyfikator landingu")
    domains = next(t for t in campaign.traits if t.entity_type == "Domain")
    assert domains.kind == "rotating"
    assert domains.value == "3 domeny"
    assert "scam0.example" in domains.why
    assert all(t.why for t in campaign.traits)
    assert rotating_summary(campaign.traits) == "3 domeny"


def test_constants_sorted_by_tier_then_lift() -> None:
    analysis = fill_traits(analyze(campaign_features()))
    (campaign,) = [c for c in analysis.campaigns if "F:a" in c.case_ids]
    constant = [t for t in campaign.traits if t.kind == "constant"]
    order = {"campaign": 0, "operator": 1, "toolkit": 2, "context": 3}
    keys = [(order[t.tier], -t.lift) for t in constant]
    assert keys == sorted(keys)
    assert {t.entity_type for t in constant} == {"KitLanding", "Asset", "Tracker"}
    assert campaign.traits[-1].kind == "rotating"


def test_fill_traits_keeps_campaign_ids_and_input() -> None:
    base = analyze(campaign_features())
    filled = fill_traits(base)
    assert [c.id for c in filled.campaigns] == [c.id for c in base.campaigns]
    assert all(not c.traits for c in base.campaigns)


def test_stopped_entities_are_not_constant() -> None:
    analysis = analyze(campaign_features())
    entities = [e.model_copy(update={"stop": True}) for e in analysis.entities]
    (campaign,) = [c for c in analysis.campaigns if "F:a" in c.case_ids]
    assert traits(campaign, entities, analysis.links, len(analysis.case_ids)) == []


def test_limit_per_type_and_singletons() -> None:
    features = [feat("S:1", "asset.sha256", f"h{i}") for i in range(30)]
    analysis = analyze(features, case_ids=["S:1", "S:2"])
    (single,) = [c for c in analysis.campaigns if c.case_ids == ["S:1"]]
    result = traits(single, analysis.entities, analysis.links, 2, limit_per_type=5)
    assert len(result) == 5
    assert all(t.kind == "constant" and t.coverage == 1.0 for t in result)


def test_polish_plurals() -> None:
    assert plural(1, "Domain") == "1 domena"
    assert plural(2, "Tracker") == "2 piksele"
    assert plural(5, "Domain") == "5 domen"
    assert plural(12, "Tracker") == "12 pikseli"
    assert plural(22, "Domain") == "22 domeny"


def test_generic_rotating_profile_does_not_expose_internal_type() -> None:
    campaign = Campaign(
        id="C1", operator_id=None, case_ids=["a", "b"], label="Example", traits=[], cohesion=1
    )
    entities = [
        Entity(id=f"AdParam:{value}", type="AdParam", value=value, tier="campaign", df=1)
        for value in ("one", "two")
    ]
    result = traits(campaign, entities, [("a", "AdParam:one", "a"), ("b", "AdParam:two", "b")], 2)
    [rotating] = [trait for trait in result if trait.kind == "rotating"]
    assert "AdParam" not in rotating.why
    assert "zgłoszeni" in rotating.why
