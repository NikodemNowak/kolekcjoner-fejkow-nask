from __future__ import annotations

from pathlib import Path

import pytest

from fakecollector.core.schemas import Artifact, Case, Feature
from fakecollector.graph.analyze import Analysis, analyze
from fakecollector.graph.profile import fill_traits

MEMBERS = ("F:a", "F:b", "F:c")
OTHERS = ("F:x", "F:y", "F:z")
DOMAINS = ("example.com", "scam1.example", "scam2.example")


def feat(case: str, name: str, value: str, locator: str = "") -> Feature:
    return Feature(
        case_id=case, artifact_id=f"{case[2:]}-har", name=name, value=value, locator=locator
    )


@pytest.fixture
def features() -> list[Feature]:
    out = []
    for case, domain in zip(MEMBERS, DOMAINS, strict=True):
        out += [
            feat(case, "ids.kit_landing", "landing-1111", "entry[3].request.url"),
            feat(case, "url.domain", domain, "entry[0].request.url"),
            feat(case, "ids.fb_pixel", "1111222233334444"),
            feat(case, "asset.sha256", "shared-hero"),
            feat(case, "infra.host_3p", "collector.evil.example"),
            feat(case, "kit.sdk", "sdk-hash"),
            feat(case, "html.title", f"Tytuł {case}"),
        ]
    out.append(feat("F:a", "infra.ip", "203.0.113.10"))
    for case in OTHERS:
        out += [
            feat(case, "url.domain", f"{case[2:]}.other"),
            feat(case, "asset.sha256", f"own-{case}"),
        ]
    return out


@pytest.fixture
def cases() -> list[Case]:
    return [
        Case(
            id=case,
            corpus="F",
            path=Path("/corpus") / case[2:],
            landing_urls=[f"https://{domain}/article?id=1"],
            flags=["cloaking_suspected"] if case == "F:b" else [],
        )
        for case, domain in zip(MEMBERS, DOMAINS, strict=True)
    ] + [Case(id=case, corpus="F", path=None) for case in OTHERS]


@pytest.fixture
def artifacts() -> list[Artifact]:
    return [
        Artifact(
            id=f"{case[2:]}-har",
            case_id=case,
            kind="har",
            role="network",
            path=Path("/corpus") / case[2:] / "network.har",
            size=10,
        )
        for case in (*MEMBERS, *OTHERS)
    ]


@pytest.fixture
def analysis(features: list[Feature]) -> Analysis:
    return fill_traits(analyze(features))
