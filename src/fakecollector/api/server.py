"""Read-only JSON API behind the web UI (`fakecollector-web`, bound to localhost).

The API never fetches URLs from inputs and never serves corpus HTML or scripts: artifacts are
exposed only as re-encoded image thumbnails.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from fakecollector.api.assign import Verdict, verdict
from fakecollector.api.network import (
    Network,
    cached_network,
    collector_image,
    collector_report,
)
from fakecollector.api.uploads import (
    UPLOAD_ID,
    UPLOADS_DIR,
    existing_upload,
    remove_upload,
    write_lock,
)
from fakecollector.api.views import (
    CampaignDetail,
    CampaignSummary,
    CaseDetail,
    GraphData,
    Ref,
    RunData,
    Summary,
    case_title,
    face_ref_file,
)
from fakecollector.config import get_settings
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.graph.coverage import INSUFFICIENT_DATA
from fakecollector.ingest.normalize import display_text
from fakecollector.pipeline import assign_new
from fakecollector.store import RunStore

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_TEXT = 2000
MAX_THUMB_SOURCE_BYTES = 40 * 1024 * 1024
UPLOAD_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".har",
    ".html",
    ".htm",
    ".mhtml",
    ".mht",
    ".pdf",
    ".mp4",
    ".webm",
    ".mov",
    ".txt",
    ".json",
}
_THUMB_CACHE_SIZE = 512


class State:
    """The loaded run, reloaded when its graph changes on disk."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.assign_lock = threading.Lock()
        self._data: RunData | None = None
        self._stamp = 0.0
        self.thumbs: OrderedDict[tuple[str, str, int], bytes] = OrderedDict()
        self.warm = False

    @property
    def run_dir(self) -> Path:
        """The run the API serves (`APP_RUN_DIR`)."""
        # KF_RUN_DIR (the web demo's variable) wins over APP_RUN_DIR from the settings.
        override = os.environ.get("KF_RUN_DIR")
        run = Path(override) if override else get_settings().run_dir
        if run is None or not (run / "graph.json").exists():
            raise HTTPException(503, "Brak wczytanej analizy (ustaw APP_RUN_DIR).")
        return run

    def data(self) -> RunData:
        """Current run data."""
        run = self.run_dir
        stamp = (run / "graph.json").stat().st_mtime
        with self.lock:
            if self._data is None or stamp != self._stamp:
                self._data = RunData(run)
                self._stamp = stamp
            return self._data

    def metadata(self) -> dict[str, object]:
        """The run's `run.json`, if present."""
        path = self.run_dir / "run.json"
        if not path.exists():
            return {}
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}


state = State()


def _warm_up() -> None:
    """Load the models once in the background so the first real request is fast."""
    try:
        state.data()
        with tempfile.TemporaryDirectory(prefix="kf-warm-") as directory:
            folder = Path(directory) / "warm"
            folder.mkdir()
            Image.new("RGB", (320, 240), (200, 210, 220)).save(folder / "warm.png")
            with state.assign_lock:
                assign_new([folder], RunStore(state.run_dir), commit=False)
        state.warm = True
        logger.info("Models warmed up")
    except Exception:
        logger.exception("Warm-up failed; the first analysis will load the models")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start model warm-up without blocking the server start."""
    threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="Kolekcjoner Fejków API", lifespan=lifespan, docs_url="/api/docs")


@app.get("/api/health")
def health() -> dict[str, object]:
    """Liveness and model warm-up state."""
    return {"ok": True, "warm": state.warm}


@app.get("/api/summary")
def summary() -> Summary:
    """Run totals and metadata."""
    return state.data().summary(state.metadata())


@app.get("/api/campaigns")
def campaigns() -> list[CampaignSummary]:
    """All campaigns, largest first."""
    return state.data().campaign_list()


@app.get("/api/campaigns/{campaign_id}")
def campaign(campaign_id: str) -> CampaignDetail:
    """One campaign with its profile, evidence and links."""
    detail = state.data().campaign_detail(campaign_id)
    if detail is None:
        raise HTTPException(404, "Nie znaleziono kampanii.")
    return detail


@app.get("/api/cases/{case_id}")
def case(case_id: str) -> CaseDetail:
    """One case with inputs, features and neighbours."""
    detail = state.data().case_detail(case_id)
    if detail is None:
        raise HTTPException(404, "Nie znaleziono zgłoszenia.")
    return detail


@app.get("/api/graph")
def graph(
    level: Annotated[str, Query(pattern="^(campaign|case|entity)$")] = "campaign",
    campaign: str | None = None,
) -> GraphData:
    """Graph data pre-shaped for the UI."""
    data = state.data()
    if level == "campaign":
        return data.campaign_graph()
    if level == "case":
        return data.case_graph(campaign)
    if not campaign:
        raise HTTPException(400, "Widok encji wymaga wskazania kampanii.")
    return data.entity_graph(campaign)


@app.get("/api/network")
def network() -> Network:
    """Reports, campaign clusters and shared traces as one network."""
    return cached_network(state.data())


@app.get("/api/collector")
def collector() -> dict[str, object]:
    """The last automatic collector report, or {} when the collector has not run."""
    return collector_report(state.run_dir) or {}


@app.get("/api/collector/{item_id}/image")
def collector_item_image(item_id: str, w: int = 240) -> Response:
    """A re-encoded JPEG of one ad screenshot found by the collector."""
    data = collector_image(state.run_dir, item_id, max(64, min(w, 960)))
    if data is None:
        raise HTTPException(404, "Brak obrazu.")
    return Response(
        data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/artifacts/{case_id}/{artifact_id}/thumb")
def thumb(case_id: str, artifact_id: str, w: int = 480) -> Response:
    """A re-encoded JPEG thumbnail of an image artifact (never the original bytes)."""
    width = max(64, min(w, 1400))
    key = (case_id, artifact_id, width)
    cached = state.thumbs.get(key)
    if cached is None:
        artifact = state.data().image_artifact(case_id, artifact_id)
        if artifact is None:
            raise HTTPException(404, "Brak obrazu.")
        path = artifact.path
        try:
            if path.is_symlink() and not path.resolve().is_file():
                raise HTTPException(404, "Brak obrazu.")
            if not path.is_file() or path.stat().st_size > MAX_THUMB_SOURCE_BYTES:
                raise HTTPException(404, "Brak obrazu.")
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((width, width * 3))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=82)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise HTTPException(404, "Brak obrazu.") from exc
        cached = output.getvalue()
        state.thumbs[key] = cached
        if len(state.thumbs) > _THUMB_CACHE_SIZE:
            state.thumbs.popitem(last=False)
    return Response(
        cached,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/faces/{slug}/ref")
def face_ref(slug: str, w: int = 96) -> Response:
    """A small JPEG of a person's reference photo from the face database (images only)."""
    width = max(32, min(w, 320))
    key = ("face-ref", slug, width)
    cached = state.thumbs.get(key)
    if cached is None:
        found = face_ref_file(slug)
        if found is None:
            raise HTTPException(404, "Brak zdjęcia.")
        path, _ = found
        try:
            if path.stat().st_size > MAX_THUMB_SOURCE_BYTES:
                raise HTTPException(404, "Brak zdjęcia.")
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((width, width * 2))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=85)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise HTTPException(404, "Brak zdjęcia.") from exc
        cached = output.getvalue()
        state.thumbs[key] = cached
        if len(state.thumbs) > _THUMB_CACHE_SIZE:
            state.thumbs.popitem(last=False)
    return Response(
        cached,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/artifacts/{case_id}/{artifact_id}/crop")
def crop(case_id: str, artifact_id: str, bbox: str, w: int = 96) -> Response:
    """A small JPEG crop of an image artifact around a bounding box (a recognised face)."""
    width = max(32, min(w, 256))
    try:
        x, y, bw, bh = (int(part) for part in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(400, "Niepoprawny parametr bbox.") from exc
    if bw <= 0 or bh <= 0 or bw > 20000 or bh > 20000:
        raise HTTPException(400, "Niepoprawny parametr bbox.")
    key = (case_id, f"{artifact_id}#{x},{y},{bw},{bh}", width)
    cached = state.thumbs.get(key)
    if cached is None:
        artifact = state.data().image_artifact(case_id, artifact_id)
        if artifact is None:
            raise HTTPException(404, "Brak obrazu.")
        path = artifact.path
        try:
            if not path.is_file() or path.stat().st_size > MAX_THUMB_SOURCE_BYTES:
                raise HTTPException(404, "Brak obrazu.")
            with Image.open(path) as source:
                image = source.convert("RGB")
                # A square around the face with some margin, clamped to the picture.
                side = int(max(bw, bh) * 1.5)
                cx, cy = x + bw // 2, y + bh // 2
                left = max(0, min(cx - side // 2, image.width - side))
                top = max(0, min(cy - side // 2, image.height - side))
                box = (left, top, min(image.width, left + side), min(image.height, top + side))
                if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                    raise HTTPException(404, "Brak obrazu.")
                image = image.crop(box)
                image.thumbnail((width, width))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=85)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise HTTPException(404, "Brak obrazu.") from exc
        cached = output.getvalue()
        state.thumbs[key] = cached
        if len(state.thumbs) > _THUMB_CACHE_SIZE:
            state.thumbs.popitem(last=False)
    return Response(
        cached,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


def _collect_inputs(
    files: list[UploadFile] | None, text: str | None, directory: Path
) -> list[str | Path]:
    """Validate an upload and store it under `directory`; returns the inputs for `assign_new`."""
    inputs: list[str | Path] = []
    if files:
        folder = directory / "upload"
        folder.mkdir(parents=True)
        total = 0
        for upload in files:
            name = display_text(Path(upload.filename or "upload").name) or "upload"
            if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
                raise HTTPException(415, f"Nieobsługiwany typ pliku: {name}")
            content = upload.file.read(MAX_UPLOAD_BYTES + 1)
            total += len(content)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Pliki są zbyt duże.")
            (folder / name).write_bytes(content)
        inputs.append(folder)
    elif text and text.strip():
        inputs.append(text.strip()[:MAX_TEXT])
    if not inputs:
        raise HTTPException(400, "Podaj plik, link albo nazwę produktu.")
    return inputs


@app.post("/api/assign")
def assign(
    files: Annotated[list[UploadFile] | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
) -> list[Verdict]:
    """Compare new material with the run without changing it (`commit=False`)."""
    data = state.data()
    features: list[Feature] = []
    artifacts: list[Artifact] = []
    with tempfile.TemporaryDirectory(prefix="kf-upload-") as directory:
        inputs = _collect_inputs(files, text, Path(directory))
        with state.assign_lock:
            answers = assign_new(
                inputs,
                RunStore(data.run_dir),
                commit=False,
                features_out=features,
                artifacts_out=artifacts,
            )
        if not answers:
            raise HTTPException(422, "Nie udało się odczytać materiału.")
        # Built while the uploaded files still exist: face crops are cut from them.
        return [verdict(answer, data, features, artifacts) for answer in answers]


class Committed(BaseModel):
    """A report saved to the run: where to find it afterwards."""

    case: Ref
    campaign: Ref | None


class CommitResult(BaseModel):
    """Verdicts for analysed material and what happened to it in the run."""

    verdicts: list[Verdict]
    committed: list[Committed] = []  # newly saved reports
    already: list[Committed] = []  # the same bytes were in the run before: nothing added
    skipped: list[str] = []  # case ids not saved because there was nothing to compare


def _located(data: RunData, case_id: str) -> Committed:
    campaign = data.campaign_of.get(case_id)
    return Committed(
        case=Ref(id=case_id, label=case_title(case_id)),
        campaign=data.ref(campaign.id) if campaign else None,
    )


@app.post("/api/assign/commit")
def assign_commit(
    files: Annotated[list[UploadFile] | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
) -> CommitResult:
    """Analyse new material and save it to the run (the default flow of the analyse page).

    Material whose bytes are already in the run is not added twice, and a bare address with
    nothing to compare is not saved. Uploaded files are kept under `<run>/uploads/`, because the
    saved case points at them. Writes take the run's file lock; existing campaign ids are kept.
    """
    before = state.data()
    store = RunStore(before.run_dir)
    keep = before.run_dir / UPLOADS_DIR / uuid.uuid4().hex[:12]
    saved = False
    try:
        inputs = _collect_inputs(files, text, keep)
        with state.assign_lock, write_lock(before.run_dir):
            known = {case.id for case in store.cases()}
            features: list[Feature] = []
            artifacts: list[Artifact] = []
            preview = assign_new(
                inputs, store, commit=False, features_out=features, artifacts_out=artifacts
            )
            if not preview:
                raise HTTPException(422, "Nie udało się odczytać materiału.")
            repeats = {a.case_id: existing_upload(a.case_id, known) for a in preview}
            duplicates: dict[str, str] = {}
            for a in preview:
                original = repeats[a.case_id] or a.duplicate_of
                if original:
                    duplicates[a.case_id] = original
            empty = [a.case_id for a in preview if INSUFFICIENT_DATA in a.flags]
            if duplicates or len(empty) == len(preview):
                return CommitResult(
                    verdicts=[verdict(a, before, features, artifacts) for a in preview],
                    already=[_located(before, case) for case in dict.fromkeys(duplicates.values())],
                    skipped=empty if not duplicates else [],
                )
            features, artifacts = [], []
            answers = assign_new(
                inputs, store, commit=True, features_out=features, artifacts_out=artifacts
            )
            saved = True
            # Verdicts describe the comparison with the run as it was before saving.
            verdicts = [verdict(a, before, features, artifacts) for a in answers]
    finally:
        if not saved or not keep.exists() or not any(keep.rglob("*")):
            shutil.rmtree(keep, ignore_errors=True)
    state.thumbs.clear()
    data = state.data()  # reloaded: graph.json changed
    return CommitResult(
        verdicts=verdicts,
        committed=[_located(data, a.case_id) for a in answers],
    )


@app.delete("/api/uploads/{case_id}")
def delete_upload(case_id: str) -> dict[str, bool]:
    """Undo a saved upload: remove the case and rebuild the graph (uploads only)."""
    if not UPLOAD_ID.fullmatch(case_id):
        raise HTTPException(400, "Można cofnąć tylko zgłoszenia dodane przez tę stronę.")
    run_dir = state.run_dir
    with state.assign_lock, write_lock(run_dir):
        removed = remove_upload(RunStore(run_dir), case_id)
    if not removed:
        raise HTTPException(404, "Nie ma takiego zgłoszenia.")
    state.thumbs.clear()
    state.data()
    return {"removed": True}


def main() -> None:
    """Serve the API on localhost (`fakecollector-web`)."""
    import uvicorn

    logging.basicConfig(level=get_settings().log_level)
    uvicorn.run(app, host="127.0.0.1", port=8600, log_level="info")
