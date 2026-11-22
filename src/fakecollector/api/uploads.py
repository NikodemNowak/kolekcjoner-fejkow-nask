"""Saving and removing uploaded reports of a run (the write side of the web API)."""

from __future__ import annotations

import fcntl
import json
import logging
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fakecollector.graph.analyze import analyze as analyze_graph
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.profile import fill_traits
from fakecollector.store import RunStore

logger = logging.getLogger(__name__)

UPLOAD_ID = re.compile(r"U:[0-9a-f]{8}(-\d+)?")
_REPEATED_ID = re.compile(r"(U:[0-9a-f]{8})-\d+")
UPLOADS_DIR = "uploads"
INPUTS_DIR = "inputs"
ASSIGNMENT_EXTRACTOR = "assignment"


@contextmanager
def write_lock(run_dir: Path) -> Iterator[None]:
    """Exclusive lock on a run directory: one writer at a time, also across processes."""
    path = run_dir / ".write.lock"
    with path.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def existing_upload(case_id: str, known: set[str]) -> str | None:
    """The saved upload with the same bytes, if the would-be id shows there is one.

    Upload ids are a digest of the content; `assign_new` appends "-2", "-3" when the plain id
    is taken, so a suffixed id means the same material is already in the run.
    """
    match = _REPEATED_ID.fullmatch(case_id)
    if match and match.group(1) in known:
        return match.group(1)
    return None


def _inside(path: Path, parent: Path) -> bool:
    try:
        return path.resolve().is_relative_to(parent.resolve())
    except OSError:
        return False


def remove_upload(store: RunStore, case_id: str) -> bool:
    """Remove one uploaded report from a run and rebuild the graph without it.

    Only `U:` cases of the upload corpus can be removed, and only files under the run's own
    `uploads/` and `inputs/` folders are deleted. Ids of the remaining campaigns do not change.
    """
    if not UPLOAD_ID.fullmatch(case_id):
        return False
    cases = store.cases()
    target = next((c for c in cases if c.id == case_id and c.corpus == "upload"), None)
    if target is None:
        return False
    artifacts = store.artifacts()
    mine = [a for a in artifacts if a.case_id == case_id]
    base = store.load_graph()

    store.write_cases(
        [c for c in cases if c.id != case_id], [a for a in artifacts if a.case_id != case_id]
    )
    kept = [f for f in store.features_from_extractor(ASSIGNMENT_EXTRACTOR) if f.case_id != case_id]
    store.add_features(kept, ASSIGNMENT_EXTRACTOR, 1)

    metadata_path = store.run_dir / "run.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    )
    remaining = [c.id for c in store.cases()]
    features = [f for f in store.all_features() if f.case_id != case_id]
    combined = analyze_graph(features, remaining, EdgeConfig(seed=metadata.get("seed", 0)))
    campaigns = []
    for campaign in base.campaigns:
        copy = campaign.model_copy(deep=True)
        copy.case_ids = [c for c in copy.case_ids if c != case_id]
        if copy.case_ids:
            campaigns.append(copy)
    combined.campaigns = campaigns
    store.save_graph(fill_traits(combined))
    if metadata_path.exists() and isinstance(metadata.get("counts"), dict):
        metadata["counts"] = {
            "cases": len(remaining),
            "artifacts": len(store.artifacts()),
            "features": len(store.features()),
            "campaigns": len(campaigns),
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), "utf-8")

    uploads = store.run_dir / UPLOADS_DIR
    inputs = store.run_dir / INPUTS_DIR
    folders = set()
    for artifact in mine:
        if _inside(artifact.path, uploads):
            # uploads/<batch>/upload/<file>: the whole batch folder belongs to this upload.
            relative = artifact.path.resolve().relative_to(uploads.resolve())
            folders.add(uploads / relative.parts[0])
        elif _inside(artifact.path, inputs) and artifact.path.is_file():
            artifact.path.unlink(missing_ok=True)
    for folder in folders:
        if _inside(folder, uploads) and folder != uploads:
            shutil.rmtree(folder, ignore_errors=True)
    logger.info("Removed upload %s", case_id)
    return True
