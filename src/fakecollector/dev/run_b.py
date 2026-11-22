"""Workstream B pipeline: every vision/video extractor over the corpora, with a feature cache.

scan -> videos, MHTML archives and PDFs expanded to derived image artifacts (keyframes,
embedded images, rendered pages; `parent_id` = source) -> image_hash, SigLIP (+ brands), faces,
OCR -> Ad Library metadata -> ASR (GPU only by default). Results are written in the plan's
run-directory format (`artifacts.parquet`, `features.parquet`, `vectors/`, `run.json`).

Features are cached per `(artifact sha256 id, extractor, version)` under
`~/.cache/fakecollector/` (env `FEATURE_CACHE`), stored as JSON plus an optional `.npy` for
vectors (no pickle), so a second run over the same bytes only reads files.
Temporary until the shared pipeline (Task 1c) owns orchestration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors.video import VideoExtractor

logger = logging.getLogger(__name__)

# The ASR stage runs `VideoExtractor`, which is deliberately not a `BaseExtractor`.
AnyExtractor = BaseExtractor | VideoExtractor

DEFAULT_RUN_DIR = Path("data/runs/b_vision")
DEFAULT_CORPORA: tuple[tuple[Path, str], ...] = (
    (Path("data/nask_backup"), "B"),
    (Path("data/nask_mentor"), "M"),
)
BATCH = 64
ALL_STAGES = ("image_hash", "image_siglip", "face", "ocr", "ad_library", "asr")
ALIASES = {"siglip": "image_siglip", "brand": "image_siglip", "video": "asr", "hash": "image_hash"}
IMAGE_STAGES = frozenset({"image_hash", "image_siglip", "face", "ocr"})


def default_cache_root() -> Path:
    """Feature cache directory: `FEATURE_CACHE` or `~/.cache/fakecollector`."""
    return Path(os.environ.get("FEATURE_CACHE", str(Path.home() / ".cache" / "fakecollector")))


class FeatureCache:
    """Content-addressed feature store keyed by (artifact id, extractor name, version).

    One entry is `<root>/features/<extractor>/v<version>/<id[:2]>/<id>.json` (features without
    vectors, each with a `vector_row` index) plus `<id>.npy` holding the stacked vectors.
    Stored features keep the case and artifact ids of the first observation; `get` callers
    rebase them, because identical bytes can occur in several cases.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.hits = 0
        self.misses = 0

    def _base(self, artifact_id: str, extractor: str, version: str) -> Path:
        return self.root / "features" / extractor / f"v{version}" / artifact_id[:2] / artifact_id

    def get(self, artifact_id: str, extractor: str, version: str) -> list[Feature] | None:
        """Return cached features, or None on a miss (or an unreadable entry)."""
        base = self._base(artifact_id, extractor, version)
        meta = base.with_suffix(".json")
        if not meta.exists():
            self.misses += 1
            return None
        try:
            rows = json.loads(meta.read_text())
            vecs = None
            if any(r.get("vector_row") is not None for r in rows):
                vecs = np.load(base.with_suffix(".npy"), allow_pickle=False)
            feats = []
            for r in rows:
                row = r.pop("vector_row", None)
                vector = None if row is None or vecs is None else vecs[row].tolist()
                feats.append(Feature(**r, vector=vector))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            logger.warning("broken cache entry %s, recomputing", meta)
            self.misses += 1
            return None
        self.hits += 1
        return feats

    def put(self, artifact_id: str, extractor: str, version: str, feats: list[Feature]) -> None:
        """Store features for one artifact (an empty list is cached too)."""
        base = self._base(artifact_id, extractor, version)
        base.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []
        vectors: list[list[float]] = []
        for f in feats:
            row = f.model_dump(exclude={"vector"}, mode="json")
            row["vector_row"] = None
            if f.vector is not None:
                row["vector_row"] = len(vectors)
                vectors.append(f.vector)
            rows.append(row)
        if vectors:
            tmp_npy = base.with_suffix(".npy.tmp")
            with tmp_npy.open("wb") as fh:
                np.save(fh, np.asarray(vectors, dtype=np.float32), allow_pickle=False)
            tmp_npy.replace(base.with_suffix(".npy"))
        tmp = base.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False))
        tmp.replace(base.with_suffix(".json"))  # json last: its presence marks a complete entry


@dataclass
class StageStats:
    """Timing and counts for one extractor stage."""

    name: str
    version: str
    inputs: int = 0
    unique: int = 0
    cached: int = 0
    computed: int = 0
    features: int = 0
    seconds: float = 0.0


@dataclass
class RunResult:
    """Everything a run produced, before it is written to disk."""

    artifacts: list[Artifact]
    features: list[Feature]
    stages: list[StageStats] = field(default_factory=list)


def _file_fingerprint(paths: Sequence[Path]) -> str:
    """Short hash of reference files, so rebuilt face DBs or logo sets invalidate the cache."""
    h = hashlib.sha256()
    for p in paths:
        if p.exists():
            h.update(p.read_bytes())
        else:
            h.update(b"missing:" + str(p).encode())
    return h.hexdigest()[:8]


def cache_version(ext: AnyExtractor, refs: Sequence[Path] = (), extra: str = "") -> str:
    """Cache version string: extractor version plus a fingerprint of its reference data."""
    parts = [str(ext.version)]
    if refs:
        parts.append(_file_fingerprint(refs))
    if extra:
        parts.append(extra)
    return "-".join(parts)


def _rebase(feats: list[Feature], art: Artifact) -> list[Feature]:
    return [
        f
        if f.case_id == art.case_id and f.artifact_id == art.id
        else f.model_copy(update={"case_id": art.case_id, "artifact_id": art.id})
        for f in feats
    ]


def _compute(ext: AnyExtractor, todo: list[Artifact], batch: int) -> dict[str, list[Feature]]:
    """Run `extract_batch` in chunks; a failing chunk falls back to one artifact at a time."""
    out: dict[str, list[Feature]] = {}
    for i in range(0, len(todo), batch):
        chunk = todo[i : i + batch]
        try:
            results = ext.extract_batch(chunk, [[] for _ in chunk])
        except Exception:  # one bad chunk must not stop the run
            logger.warning("%s: batch failed, retrying per artifact", ext.name, exc_info=True)
            results = []
            for art in chunk:
                try:
                    results.append(ext.extract(art, []))
                except Exception:
                    logger.warning("%s failed on %s", ext.name, art.path.name, exc_info=True)
                    results.append([])
        for art, feats in zip(chunk, results, strict=True):
            out[art.id] = feats
    return out


def run_extractor(
    ext: AnyExtractor,
    artifacts: list[Artifact],
    cache: FeatureCache | None,
    version: str | None = None,
    batch: int = BATCH,
) -> tuple[list[Feature], StageStats]:
    """Run one extractor over the artifacts it supports, reading and filling the cache.

    Identical bytes (same artifact id) are computed once per run and fanned out to every case.
    """
    ver = version or str(ext.version)
    stats = StageStats(name=ext.name, version=ver)
    t0 = time.perf_counter()
    supported = [a for a in artifacts if ext.supports(a)]
    reps: dict[str, Artifact] = {}
    for a in supported:
        reps.setdefault(a.id, a)
    stats.inputs, stats.unique = len(supported), len(reps)
    by_id: dict[str, list[Feature]] = {}
    todo: list[Artifact] = []
    for aid, rep in reps.items():
        hit = cache.get(aid, ext.name, ver) if cache is not None else None
        if hit is None:
            todo.append(rep)
        else:
            by_id[aid] = hit
    stats.cached, stats.computed = len(reps) - len(todo), len(todo)
    if todo:
        logger.info("%s: computing %d of %d unique artifacts", ext.name, len(todo), len(reps))
        fresh = _compute(ext, todo, batch)
        for aid, feats in fresh.items():
            if cache is not None:
                cache.put(aid, ext.name, ver, feats)
            by_id[aid] = feats
    feats_out = [f for a in supported for f in _rebase(by_id.get(a.id, []), a)]
    stats.features = len(feats_out)
    stats.seconds = round(time.perf_counter() - t0, 3)
    return feats_out, stats


def resolve_stages(only: str | None) -> list[str]:
    """Parse `--only a,b` into canonical stage names (all stages when empty)."""
    if not only:
        return list(ALL_STAGES)
    wanted = {ALIASES.get(s.strip(), s.strip()) for s in only.split(",") if s.strip()}
    unknown = wanted - set(ALL_STAGES)
    if unknown:
        raise ValueError(f"unknown extractor(s): {sorted(unknown)}; known: {list(ALL_STAGES)}")
    return [s for s in ALL_STAGES if s in wanted]


def scan_all(corpora: Sequence[tuple[Path, str]], cases: set[str] | None = None) -> list[Artifact]:
    """Load every corpus root through case-folder ingest; a missing root is skipped."""
    from fakecollector.ingest.casefolder import load_corpus

    arts: list[Artifact] = []
    for root, corpus in corpora:
        if not root.exists():
            logger.warning("corpus %s missing at %s, skipped", corpus, root)
            continue
        arts += load_corpus(root, corpus)[1]
    seen: set[tuple[str, str]] = set()
    out = []
    for a in arts:  # the same file twice in one case adds nothing
        if cases is not None and a.case_id not in cases:
            continue
        if (a.case_id, a.id) not in seen:
            seen.add((a.case_id, a.id))
            out.append(a)
    return out


def _release_gpu() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _stage_factories() -> dict[str, Callable[[], tuple[BaseExtractor, str]]]:
    """Lazily build each extractor with its cache version (imports stay out of module load)."""

    def image_hash() -> tuple[BaseExtractor, str]:
        from fakecollector.extractors.image_hash import _HAS_PDQ, ImageHashExtractor

        ext = ImageHashExtractor()
        return ext, cache_version(ext, extra="pdq" if _HAS_PDQ else "nopdq")

    def siglip() -> tuple[BaseExtractor, str]:
        from fakecollector.extractors.brand import BRAND_NAMES, REFS_PATH, THRESHOLD
        from fakecollector.extractors.image_embed import SiglipExtractor

        ext = SiglipExtractor()
        # The zero-shot prompts are part of the brand reference too.
        names = hashlib.sha256(repr(sorted(BRAND_NAMES.items())).encode()).hexdigest()[:6]
        return ext, cache_version(ext, [REFS_PATH], extra=f"t{THRESHOLD}-b{names}")

    def face() -> tuple[BaseExtractor, str]:
        from fakecollector.extractors.face import FaceConfig, FaceExtractor

        cfg = FaceConfig.from_env()
        ext = FaceExtractor(config=cfg)
        extra = f"t{cfg.threshold}-d{cfg.min_det_score}-s{cfg.min_face_px}-i{cfg.min_image_px}"
        return ext, cache_version(ext, [cfg.db_path], extra=extra)

    def ocr() -> tuple[BaseExtractor, str]:
        from fakecollector.extractors.ocr import OcrExtractor

        ext = OcrExtractor()
        return ext, cache_version(ext)

    def ad_library() -> tuple[BaseExtractor, str]:
        from fakecollector.extractors.ad_library import AdLibraryExtractor

        ext = AdLibraryExtractor()
        return ext, cache_version(ext)

    return {
        "image_hash": image_hash,
        "image_siglip": siglip,
        "face": face,
        "ocr": ocr,
        "ad_library": ad_library,
    }


def _release(stage: str) -> None:
    """Free a stage's model before the next one loads (the GPU is shared)."""
    if stage == "image_siglip":
        from fakecollector.extractors import brand
        from fakecollector.extractors.image_embed import release

        brand._prompts.cache_clear()
        release()
    elif stage == "ocr":
        from fakecollector.extractors.ocr import _reader

        _reader.cache_clear()
        _release_gpu()


def expand_derived(
    artifacts: list[Artifact], keyframe_dir: Path
) -> tuple[list[Artifact], StageStats]:
    """Add derived image artifacts (parent_id = source id) for videos, MHTML and PDFs.

    The image stages below then see them as ordinary images, so `DerivedMediaExtractor`
    itself is never run here and no image is processed twice.
    """
    from fakecollector.extractors.derived import DerivedMediaExtractor

    ext = DerivedMediaExtractor(cache_dir=keyframe_dir, extractors=[])
    stats = StageStats(name="derived", version=f"{ext.version}-max{ext.max_frames}")
    t0 = time.perf_counter()
    sources = [a for a in artifacts if ext.supports(a)]
    derived: list[Artifact] = []
    done: dict[str, list[Artifact]] = {}
    for src in sources:
        if src.id not in done:
            done[src.id] = ext.derive(src)
        # Re-home shared sources so each case owns its derived images.
        derived += [
            k if k.case_id == src.case_id else k.model_copy(update={"case_id": src.case_id})
            for k in done[src.id]
        ]
    stats.inputs, stats.unique, stats.features = len(sources), len(done), len(derived)
    stats.seconds = round(time.perf_counter() - t0, 3)
    return derived, stats


def run_asr(
    artifacts: list[Artifact], cache: FeatureCache | None, keyframe_dir: Path
) -> tuple[list[Feature], StageStats]:
    """Transcribe videos (`text.asr`); skipped when `FAKECOLLECTOR_ASR` turns ASR off."""
    from fakecollector.extractors.video import ASR_DECODE, asr_enabled, asr_model

    ext = VideoExtractor(cache_dir=keyframe_dir)
    if not asr_enabled():
        return [], StageStats(name="asr", version="skipped")
    extra = f"{asr_model()}-{ASR_DECODE}"
    feats, stats = run_extractor(ext, artifacts, cache, cache_version(ext, extra=extra), batch=1)
    stats.name = "asr"
    from fakecollector.extractors.video import _whisper

    _whisper.cache_clear()
    _release_gpu()
    return feats, stats


def run_pipeline(
    corpora: Sequence[tuple[Path, str]],
    stages: list[str],
    cache: FeatureCache | None,
    keyframe_dir: Path,
    cases: set[str] | None = None,
    on_stage_start: Callable[[str], None] | None = None,
    on_stage_end: Callable[[StageStats], None] | None = None,
) -> RunResult:
    """Scan, expand videos/MHTML/PDF and run the selected stages in a GPU-friendly order.

    The optional hooks run around each extractor stage (the benchmark uses them to reset and
    read peak GPU memory per stage).
    """
    t0 = time.perf_counter()
    artifacts = scan_all(corpora, cases)
    result = RunResult(artifacts=artifacts, features=[])
    result.stages.append(
        StageStats(
            name="scan",
            version="1",
            inputs=len(artifacts),
            seconds=round(time.perf_counter() - t0, 3),
        )
    )
    if IMAGE_STAGES & set(stages):
        frames, kstats = expand_derived(artifacts, keyframe_dir)
        result.artifacts = artifacts + frames
        result.stages.append(kstats)
    factories = _stage_factories()
    for stage in stages:
        if on_stage_start is not None:
            on_stage_start(stage)
        if stage == "asr":
            feats, stats = run_asr(artifacts, cache, keyframe_dir)
        else:
            ext, ver = factories[stage]()
            feats, stats = run_extractor(ext, result.artifacts, cache, ver)
            _release(stage)
        if on_stage_end is not None:
            on_stage_end(stats)
        logger.info(
            "%-12s %5d in, %4d cached, %4d computed, %5d features, %7.1f s",
            stats.name,
            stats.inputs,
            stats.cached,
            stats.computed,
            stats.features,
            stats.seconds,
        )
        result.features += feats
        result.stages.append(stats)
    return result


def write_run(result: RunResult, out: Path, meta: dict[str, Any]) -> None:
    """Write the run directory: artifacts/features parquet, vectors and run.json."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out.mkdir(parents=True, exist_ok=True)
    vec_dir = out / "vectors"
    if vec_dir.exists():
        shutil.rmtree(vec_dir)
    vec_dir.mkdir()
    art_cols = ("id", "case_id", "kind", "role", "path", "page", "parent_id", "size", "meta")
    art_rows = [
        {
            "id": a.id,
            "case_id": a.case_id,
            "kind": a.kind,
            "role": a.role,
            "path": str(a.path),
            "page": a.page,
            "parent_id": a.parent_id,
            "size": a.size,
            "meta": json.dumps(a.meta, ensure_ascii=False, sort_keys=True),
        }
        for a in result.artifacts
    ]
    art_schema = pa.schema([(c, pa.int64() if c == "size" else pa.string()) for c in art_cols])
    pq.write_table(pa.Table.from_pylist(art_rows, schema=art_schema), out / "artifacts.parquet")
    cols = ("case_id", "artifact_id", "name", "value", "confidence", "locator")
    feat_schema = pa.schema([(c, pa.float64() if c == "confidence" else pa.string()) for c in cols])
    feat_rows = [{c: getattr(f, c) for c in cols} for f in result.features]
    pq.write_table(pa.Table.from_pylist(feat_rows, schema=feat_schema), out / "features.parquet")
    vec_counts: dict[str, int] = {}
    by_name: dict[str, list[Feature]] = {}
    for f in result.features:
        if f.vector is not None:
            by_name.setdefault(f.name, []).append(f)
    for name, feats in by_name.items():
        np.save(vec_dir / f"{name}.npy", np.asarray([f.vector for f in feats], dtype=np.float32))
        index = pa.table(
            {
                "row": list(range(len(feats))),
                "case_id": [f.case_id for f in feats],
                "artifact_id": [f.artifact_id for f in feats],
                "locator": [f.locator for f in feats],  # "" = whole image, "crop=..." = region
            }
        )
        pq.write_table(index, vec_dir / f"{name}.index.parquet")
        vec_counts[name] = len(feats)
    counts: dict[str, int] = {}
    for f in result.features:
        counts[f.name] = counts.get(f.name, 0) + 1
    run = {
        **meta,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": {
            "cases": len({a.case_id for a in result.artifacts}),
            "artifacts": len(result.artifacts),
            "keyframes": sum(1 for a in result.artifacts if a.parent_id),
            "features": len(result.features),
            "features_by_name": dict(sorted(counts.items())),
            "vectors": vec_counts,
        },
        "stages": [asdict(s) for s in result.stages],
    }
    (out / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))


def library_versions() -> dict[str, str]:
    """Versions of the libraries that shape the features (for reproducibility)."""
    from importlib.metadata import PackageNotFoundError, version

    out = {"python": platform.python_version()}
    for pkg in (
        "torch",
        "transformers",
        "imagehash",
        "pdqhash",
        "insightface",
        "onnxruntime-gpu",
        "onnxruntime",
        "easyocr",
        "faster-whisper",
        "numpy",
        "pillow",
    ):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            continue
    return out
