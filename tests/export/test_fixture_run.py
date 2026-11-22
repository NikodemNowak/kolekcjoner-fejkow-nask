from __future__ import annotations

from pathlib import Path

from fakecollector.evaluation.runner import extract_features_for_eval
from fakecollector.export import FORMATS, export_all
from fakecollector.export.dataset import DatasetRecord
from fakecollector.graph.analyze import analyze
from fakecollector.graph.profile import fill_traits
from fakecollector.ingest.casefolder import load_corpus

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "cases"


def test_fixture_corpus_exports_end_to_end(tmp_path: Path) -> None:
    cases, artifacts = load_corpus(FIXTURES, "F")
    features, _ = extract_features_for_eval(artifacts)
    analysis = fill_traits(analyze(features, case_ids=[case.id for case in cases]))
    shared = next(c for c in analysis.campaigns if c.case_ids == ["F:f1", "F:f2"])
    landing = next(t for t in shared.traits if t.entity_type == "KitLanding")
    assert (landing.kind, landing.coverage) == ("constant", 1.0)
    assert any(t.kind == "rotating" and t.entity_type == "Domain" for t in shared.traits)

    written = export_all(analysis, features, tmp_path, FORMATS, cases, artifacts)
    lines = (tmp_path / "dataset" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(cases)
    assert all(DatasetRecord.model_validate_json(line) for line in lines)
    # Exports hold derived values only, never copies of corpus files.
    names = {path.name for paths in written.values() for path in paths}
    assert not names & {path.name for path in FIXTURES.rglob("*") if path.is_file()}
