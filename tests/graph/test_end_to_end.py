from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.asset import AssetExtractor
from fakecollector.extractors.har_ids import IdsExtractor
from fakecollector.extractors.html_page import HtmlPageExtractor
from fakecollector.extractors.infra import RequestGraphExtractor
from fakecollector.extractors.template import TemplateExtractor
from fakecollector.extractors.text import TextExtractor
from fakecollector.graph.analyze import analyze
from fakecollector.ingest.casefolder import load_corpus


def _extract(artifacts: list[Artifact]) -> list[Feature]:
    extractors = (
        AssetExtractor(),
        IdsExtractor(),
        HtmlPageExtractor(),
        RequestGraphExtractor(),
        TemplateExtractor(),
    )
    prior: dict[str, list[Feature]] = defaultdict(list)
    representative: dict[str, Artifact] = {}
    for artifact in artifacts:
        representative.setdefault(artifact.case_id, artifact)
        for extractor in extractors:
            if extractor.supports(artifact):
                prior[artifact.case_id].extend(extractor.extract(artifact, []))

    text = TextExtractor()
    features = []
    for case_id, artifact in representative.items():
        features.extend(prior[case_id])
        features.extend(text.extract(artifact, prior[case_id]))
    return features


def test_analyze_synthetic_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fakecollector.extractors.text._bge_model", lambda: None)
    cases, artifacts = load_corpus(Path("data/fixtures/cases"), "F")
    features = _extract(artifacts)
    case_ids = [case.id for case in cases]
    result = analyze(features, case_ids)
    assert result == analyze(list(reversed(features)), list(reversed(case_ids)))
    by_case = {case: campaign for campaign in result.campaigns for case in campaign.case_ids}
    assert by_case["F:f1"].id == by_case["F:f2"].id
    # f3 shares tenant and pixel with f1/f2. Its campaign is decided by the fixture's reuse of
    # landing B in f4, so only the operator is asserted for it.
    assert result.operators["F:f1"] == result.operators["F:f2"] == result.operators["F:f3"]
    assert by_case["F:f5"].case_ids == ["F:f5"]
    assert by_case["F:f6"].id != by_case["F:f1"].id
    edges = {(edge.src, edge.dst): edge for edge in result.edges}
    # f2 and f3 share only the page template and operator IDs, with unrelated text.
    assert ("F:f2", "F:f3") not in edges
    # f4's cloaked shop variant and f6 carry the identical shop text and the same pixel.
    assert edges["F:f4", "F:f6"].signals["text"] > 0.6
    assert by_case["F:f4"].id == by_case["F:f6"].id
    assert "cloaking_suspected" in next(case.flags for case in cases if case.id == "F:f4")
