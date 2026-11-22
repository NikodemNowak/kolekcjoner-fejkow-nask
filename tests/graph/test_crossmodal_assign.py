from __future__ import annotations

from math import sqrt

import pytest

from fakecollector.core.schemas import Campaign, Feature
from fakecollector.graph.analyze import Analysis, analyze
from fakecollector.graph.assign import NEAREST_KIND, assign
from fakecollector.graph.config import EdgeConfig

from .test_graph import feat


def _vector(case: str, name: str, cosine: float, *, rival: bool = False) -> Feature:
    orthogonal = sqrt(1 - cosine**2)
    return feat(
        case,
        name,
        artifact=f"{case}-{name}",
        locator="page" if case != "upload" else "ocr",
        vector=[cosine, 0, orthogonal] if rival else [cosine, orthogonal, 0],
    )


@pytest.mark.parametrize(
    ("name", "own", "rival", "key", "decision"),
    [
        ("text.bge", 0.80, 0.55, "brand.impersonated", "existing"),
        ("text.bge", 0.80, 0.55, None, "review"),
        ("text.bge", 0.70, 0.60, None, "review"),
        # A look-alike picture (below the solo SigLIP cut, so context only) and a shared face
        # lead to the campaign, but without campaign-tier evidence it is a review.
        ("img.siglip", 0.93, 0.80, "person.public_figure", "review"),
        ("img.siglip", 0.98, 0.80, "person.public_figure", "existing"),
        # A topic is shared by most scams; it never corroborates (LOCO false accept).
        ("img.siglip", 0.93, 0.80, "text.topic", "review"),
        ("text.bge", 0.80, 0.55, "ad.advertiser", "existing"),
        ("text.bge", 0.80, 0.55, "text.topic", "review"),
        ("text.bge", 0.75, 0.70, "brand.impersonated", "new"),
        ("text.bge", 0.60, 0.55, None, "new"),
    ],
)
def test_crossmodal_assignment(
    name: str, own: float, rival: float, key: str | None, decision: str
) -> None:
    base_features = [_vector("x", name, own), _vector("y", name, rival, rival=True)]
    new_features = [_vector("upload", name, 1)]
    if key is not None:
        base_features.append(feat("x", key, "shared"))
        new_features.append(feat("upload", key, "shared"))
    base = analyze(base_features)
    (result,) = assign(new_features, base, base_features)

    assert result.decision == decision
    assert result.duplicate_of is None
    if decision != "new":
        assert result.campaign_id == next(c.id for c in base.campaigns if c.case_ids == ["x"])
        (vector_evidence,) = (item for item in result.evidence if item.kind == name)
        assert vector_evidence.value == f"cos {own:.2f}"
        assert vector_evidence.artifacts == [f"upload-{name}#ocr", f"x-{name}#page"]
        assert f"podobieństwo {own:.0%}" in vector_evidence.detail


def test_crossmodal_uses_best_artifacts_and_corroborates_across_members() -> None:
    base_features = [
        *(feat(case, "ids.kit_landing", "landing-x") for case in ("x", "x-peer")),
        _vector("x", "text.bge", 0.72),
        feat("x", "text.bge", artifact="article", vector=[0.80, 0.60, 0]),
        _vector("x-peer", "img.siglip", 0.90),
        _vector("y", "text.bge", 0.55, rival=True),
        _vector("y", "img.siglip", 0.70, rival=True),
    ]
    base = analyze(base_features)
    (result,) = assign(
        [
            _vector("upload", "text.bge", 1),
            feat("upload", "text.bge", artifact="ocr-footer", vector=[0, 0, -1]),
            _vector("upload", "img.siglip", 1),
        ],
        base,
        base_features,
    )

    assert result.decision == "existing"
    assert result.campaign_id == next(c.id for c in base.campaigns if "x" in c.case_ids)
    matched = {item.kind: item.artifacts for item in result.evidence}
    assert matched["text.bge"] == ["article", "upload-text.bge#ocr"]
    assert matched["img.siglip"] == ["upload-img.siglip#ocr", "x-peer-img.siglip#page"]


def test_crossmodal_ignores_stopped_corroboration() -> None:
    base_features = [
        _vector("x", "text.bge", 0.80),
        _vector("y", "text.bge", 0.55, rival=True),
        *(feat(case, "brand.impersonated", "common") for case in ("x", "y", "z")),
    ]
    base = analyze(base_features)
    (result,) = assign(
        [_vector("upload", "text.bge", 1), feat("upload", "brand.impersonated", "common")],
        base,
        base_features,
    )

    assert result.decision == "review"
    assert result.campaign_id == next(c.id for c in base.campaigns if c.case_ids == ["x"])
    assert [item.kind for item in result.evidence] == ["text.bge", NEAREST_KIND]


def test_crossmodal_operator_conflict_downgrades_assignment() -> None:
    base_features = [
        _vector("x", "text.bge", 0.72),
        feat("x", "brand.impersonated", "shared"),
        feat("x-peer", "ids.fb_pixel", "operator-x"),
        feat("x", "ids.fb_pixel", "operator-x"),
        _vector("y", "text.bge", 0.55, rival=True),
        feat("y", "ids.fb_pixel", "operator-y"),
        feat("y-peer", "ids.fb_pixel", "operator-y"),
    ]
    base = analyze(base_features)
    (result,) = assign(
        [
            _vector("upload", "text.bge", 1),
            feat("upload", "brand.impersonated", "shared"),
            feat("upload", "ids.fb_pixel", "operator-y"),
        ],
        base,
        base_features,
    )

    assert result.decision == "review"
    assert result.campaign_id == next(c.id for c in base.campaigns if c.case_ids == ["x"])
    assert result.operator_id == base.operators["y"]
    assert any(item.value == "cos 0.72" for item in result.evidence)


def test_sparse_assignment_keeps_peak_over_top_three_mean() -> None:
    cfg = EdgeConfig(tau_assign=0.95)
    base_features = [
        *(feat(case, "ids.kit_landing", "shared") for case in ("a", "b", "c", "d")),
        *(feat(case, "url.domain", f"{case}.example") for case in ("a", "b", "c")),
    ]
    base = analyze(base_features, cfg=cfg)
    (campaign,) = base.campaigns
    assert len(campaign.case_ids) == 4
    (result,) = assign([feat("upload", "url.domain", "a.example")], base, base_features, cfg)

    assert result.comparable == ["ids"]
    assert result.score == pytest.approx(max(0.9, (0.9 + 0 + 0) / 3))
    assert result.decision == "existing"


def _split(base: Analysis, *groups: list[str]) -> Analysis:
    """Force base cases into the given campaigns (as if a stronger key had split them)."""
    campaigns = [
        Campaign(
            id=f"C-{group[0]}", operator_id=None, case_ids=group, label="", traits=[], cohesion=1
        )
        for group in groups
    ]
    return base.model_copy(update={"campaigns": campaigns})


def test_reencoded_resubmission_is_duplicate() -> None:
    exact_hash = "AB" * 32
    base_features = [
        feat("x", "img.pdq", exact_hash, artifact="base-image"),
        feat("x", "img.pdq", "1" * 64, artifact="other-base-image"),
        feat("x", "url.domain", "x.example", artifact="page"),
    ]
    base = analyze(base_features)
    (result,) = assign(
        [
            feat("upload", "img.pdq", exact_hash.lower(), artifact="reencoded"),
            feat("upload", "text.ocr", "re-encoded screenshot", artifact="reencoded"),
            feat("upload", "url.domain", "x.example", artifact="page"),
        ],
        base,
        base_features,
    )

    assert result.decision == "existing"
    assert result.duplicate_of == "x"
    assert result.campaign_id == base.campaigns[0].id
    assert result.score == 1


def test_one_identical_image_among_new_files_is_not_a_duplicate() -> None:
    exact_hash = "AB" * 32
    base_features = [feat("x", "img.pdq", exact_hash, artifact="base-image")]
    base = analyze(base_features)
    (result,) = assign(
        [
            feat("upload", "img.pdq", exact_hash, artifact="reencoded"),
            feat("upload", "img.pdq", "2" * 64, artifact="other-upload-image"),
        ],
        base,
        base_features,
    )

    assert result.duplicate_of is None


def test_shared_hub_file_or_image_is_not_a_duplicate() -> None:
    # A library file and a stock image present in two unrelated base campaigns are hubs.
    hub_image = "CD" * 32
    base_features = [
        *(feat(case, "url.domain", f"{case}.test", artifact="library-js") for case in ("x", "y")),
        *(feat(case, "img.pdq", hub_image, artifact=f"{case}-stock") for case in ("x", "y")),
    ]
    base = _split(analyze(base_features), ["x"], ["y"])
    (result,) = assign(
        [
            feat("upload", "url.domain", "upload.test", artifact="library-js"),
            feat("upload", "img.pdq", hub_image, artifact="upload-stock"),
        ],
        base,
        base_features,
    )

    assert result.duplicate_of is None
    assert result.decision != "existing" or result.score < 1


def test_single_shared_landing_asset_is_not_a_duplicate() -> None:
    # LOCO false accepts: a new campaign whose page reuses one template asset (a loader script,
    # a UI mock-up) that exactly one base case also has was a score-1.0 "duplicate".
    base_features = [
        *(feat("x", "asset.sha256", f"x-asset-{i}", artifact=f"x-asset-{i}") for i in range(5)),
        feat("x", "asset.sha256", "template", artifact="template-asset"),
        feat("x", "url.domain", "x.example", artifact="x-page"),
        *(feat("y", "asset.sha256", f"y-asset-{i}", artifact=f"y-asset-{i}") for i in range(5)),
        feat("y", "url.domain", "y.example", artifact="y-page"),
    ]
    base = analyze(base_features)
    new_features = [
        *(feat("new", "asset.sha256", f"n-asset-{i}", artifact=f"n-asset-{i}") for i in range(5)),
        feat("new", "asset.sha256", "template", artifact="template-asset"),
        feat("new", "url.domain", "new.example", artifact="new-page"),
    ]
    (result,) = assign(new_features, base, base_features)

    assert result.duplicate_of is None
    assert result.decision != "existing"


def test_crossmodal_key_in_several_campaigns_does_not_corroborate() -> None:
    # A public figure used by two campaigns cannot say which one a new creative belongs to.
    base_features = [
        _vector("x", "img.siglip", 0.95),
        _vector("y", "img.siglip", 0.80, rival=True),
        *(feat(case, "person.public_figure", "celebrity") for case in ("x", "y")),
    ]
    base = analyze(base_features)
    base = _split(base, ["x"], ["y"])
    (result,) = assign(
        [_vector("upload", "img.siglip", 1), feat("upload", "person.public_figure", "celebrity")],
        base,
        base_features,
    )

    assert result.decision == "review"
    assert result.campaign_id == "C-x"


def test_crossmodal_other_vector_must_lead_on_its_own() -> None:
    # BGE leads x by 0.25; SigLIP clears 0.90 for x but a rival is just as close: no second family.
    base_features = [
        _vector("x", "text.bge", 0.80),
        _vector("y", "text.bge", 0.55, rival=True),
        _vector("x", "img.siglip", 0.92),
        _vector("y", "img.siglip", 0.91, rival=True),
    ]
    base = _split(analyze(base_features), ["x"], ["y"])
    (result,) = assign(
        [_vector("upload", "text.bge", 1), _vector("upload", "img.siglip", 1)],
        base,
        base_features,
    )

    assert result.decision == "review"
    assert result.campaign_id == "C-x"


@pytest.mark.parametrize(
    ("extra", "decision"),
    [
        ([], "review"),
        # An upload that is mostly one face: identity is the face extractor's job.
        ([feat("upload", "img.face_share", "0.60", artifact="upload-img.siglip")], "new"),
    ],
)
def test_crossmodal_ignores_portrait_uploads(extra: list[Feature], decision: str) -> None:
    base_features = [_vector("x", "img.siglip", 0.93), _vector("y", "img.siglip", 0.8, rival=True)]
    base = analyze(base_features)
    (result,) = assign([_vector("upload", "img.siglip", 1), *extra], base, base_features)
    assert result.decision == decision


def test_crossmodal_ignores_cloaked_variant_images() -> None:
    cloaked = _vector("x", "img.siglip", 0.93).model_copy(update={"confidence": 0.5})
    base_features = [cloaked, _vector("y", "img.siglip", 0.8, rival=True)]
    base = analyze(base_features)
    (result,) = assign([_vector("upload", "img.siglip", 1)], base, base_features)
    assert result.decision == "new"
