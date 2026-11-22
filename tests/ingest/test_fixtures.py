from pathlib import Path

from fakecollector.ingest.casefolder import load_corpus

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "cases"


def test_fixture_corpus_loads_with_expected_flags() -> None:
    cases, arts = load_corpus(FIXTURES, "F")
    by_id = {c.id: c for c in cases}
    assert sorted(by_id) == ["F:f1", "F:f2", "F:f3", "F:f4", "F:f5", "F:f6"]
    assert "cloaking_suspected" in by_id["F:f4"].flags
    assert "screenshot_only" in by_id["F:f5"].flags
    assert by_id["F:f1"].landing_urls == ["https://fixture-alpha.click/?clickid=abc123"]
    assert by_id["F:f6"].landing_urls == ["https://fixture-unrelated.icu/start"]
    assert all(c.duplicate_of is None for c in cases)
    hero = {a.case_id for a in arts if a.path.name == "hero.png"}
    assert {"F:f1", "F:f2"} <= hero
    assert (
        len({a.id for a in arts if a.path.name == "hero.png" and a.case_id in {"F:f1", "F:f2"}})
        == 1
    )
