from __future__ import annotations

import logging
from pathlib import Path

import pytest

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.evaluation import runner


class RawExtractor(BaseExtractor):
    name = "raw"

    def supports(self, artifact: Artifact) -> bool:
        return artifact.kind == "text"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        assert not prior
        return [
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="text.raw",
                value=artifact.id,
            )
        ]


class BrokenExtractor(RawExtractor):
    name = "broken"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        raise FileNotFoundError(artifact.id)


class DerivedExtractor(RawExtractor):
    name = "derived"
    stage = 2

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        assert {feature.case_id for feature in prior} == {artifact.case_id}
        return [
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="text.topic",
                value="+".join(feature.value for feature in prior),
            )
        ]


class CaseLevelExtractor(DerivedExtractor):
    name = "case-level"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        assert all(feature.name == "text.raw" for feature in prior)
        return [
            source.model_copy(update={"name": "text.bge", "vector": [1.0, 0.0]}) for source in prior
        ]


def test_extractors_use_only_the_cases_own_prior_and_skip_broken_artifacts(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        runner,
        "_discover_extractors",
        lambda: [BrokenExtractor(), RawExtractor(), CaseLevelExtractor(), DerivedExtractor()],
    )
    artifacts = [
        Artifact(id=aid, case_id=cid, kind="text", role="other", path=Path(aid), size=0)
        for cid, aid in (("a", "x"), ("a", "y"), ("b", "z"))
    ]

    features, _ = runner.extract_features_for_eval(artifacts)

    assert [
        (feature.case_id, feature.artifact_id, feature.value)
        for feature in features
        if feature.name == "text.topic"
    ] == [
        ("a", "x", "x+y"),
        ("a", "y", "x+y"),
        ("b", "z", "z"),
    ]
    assert [feature.artifact_id for feature in features if feature.name == "text.bge"] == [
        "x",
        "y",
        "z",
    ]
    assert sum(record.levelno == logging.WARNING for record in caplog.records) == 3
