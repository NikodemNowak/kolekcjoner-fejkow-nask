"""Known operator + known kit, but a new story: `new` with the operator, not `review`."""

from __future__ import annotations

from fakecollector.core.schemas import Feature
from fakecollector.graph.analyze import analyze
from fakecollector.graph.assign import assign

from .test_graph import feat


def _case(c: str, story: str) -> list[Feature]:
    return [
        feat(c, "url.domain", f"{c}.test", artifact=f"{c}-page"),
        feat(c, "text.headline_tpl", story, artifact=f"{c}-page"),
        feat(c, "ids.kit_tenant", "tenant-1", artifact=f"{c}-har"),
        feat(c, "ids.fb_pixel", "1111222233334444", artifact=f"{c}-har"),
        feat(c, "infra.host_3p", "collector.stats.test", artifact=f"{c}-har"),
        feat(c, "infra.endpoint", "POST collector.stats.test/events?v", artifact=f"{c}-har"),
        *(
            feat(c, "kit.path_sig", path, artifact=f"{c}-har")
            for path in (
                "/sdk/main.js",
                "/sdk/main.css",
                "/api/v{n}/field/{uuid}/",
                "/api/v{n}/session/{uuid}/{uuid}",
            )
        ),
    ]


def test_known_operator_and_kit_without_campaign_evidence_is_new_not_review() -> None:
    others = [
        feat(f"o{i}", "url.domain", f"other{i}.test", artifact=f"o{i}-page") for i in range(8)
    ]
    base_features = _case("x", "story about a banker") + _case("y", "story about a banker")
    base = analyze(base_features + others)
    (result,) = assign(_case("upload", "completely different story"), base, base_features + others)
    assert result.score >= 0.5  # operator + toolkit slots reach the old review threshold
    assert result.decision == "new"
    assert result.operator_id is not None  # still reported: known operator
