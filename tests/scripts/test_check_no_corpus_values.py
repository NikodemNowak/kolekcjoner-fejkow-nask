"""Guard against organizer-derived values in tracked files (scripts/check_no_corpus_values.py)."""

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_no_corpus_values.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_no_corpus_values", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _features(path: Path, rows: list[tuple[str, str]]) -> Path:
    table = pa.table(
        {
            "case_id": ["S:1"] * len(rows),
            "artifact_id": ["ab" * 8] * len(rows),
            "name": [n for n, _ in rows],
            "value": [v for _, v in rows],
        }
    )
    pq.write_table(table, path)
    return path


def _repo(root: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel, text in files.items():
        (root / rel).write_text(text)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


def test_finds_plain_defanged_and_abbreviated_values(tmp_path: Path) -> None:
    mod = _load()
    values = mod.build_values(
        _features(
            tmp_path / "features.parquet",
            [
                ("url.domain", "lander-one.example"),
                ("ids.fb_pixel", "1111222233334444"),
                ("ids.kit_tenant", "abcdef01-2345-4678-9abc-def012345678"),
                ("infra.host_3p", "www.facebook.com"),
            ],
        )
    )
    repo = _repo(
        tmp_path / "repo",
        {
            "a.md": "see lander-one[.]example and pixel 1111222233334444",
            "b.py": "tenant = 'abcdef01…'",
            "c.md": "connect via www.facebook.com only",
        },
    )
    hits = {(f, kind) for f, kind, _ in mod.scan(repo, values)}
    assert hits == {("a.md", "host"), ("a.md", "id"), ("b.py", "hash")}


def test_skips_without_features(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KF_FEATURES", raising=False)
    monkeypatch.setattr("sys.argv", ["check", "--features", "/nonexistent/features.parquet"])
    assert _load().main() == 0


@pytest.mark.skipif(not os.environ.get("KF_FEATURES"), reason="set KF_FEATURES to a real run")
def test_repo_has_no_corpus_values() -> None:
    mod = _load()
    hits = mod.scan(SCRIPT.parents[1], mod.build_values(Path(os.environ["KF_FEATURES"])))
    assert not hits, f"{len(hits)} organizer-derived value(s) in tracked files"
