"""Video keyframes via ffmpeg scene detection (signal 10).

Decodes a video once at 1 fps, long side <= 960 px, scores scene changes with ffmpeg's
`scene` metric and keeps every cut above 0.3 plus a uniform grid (first frame included), so
videos with few cuts (screen recordings, talking heads) are still covered.
Keyframes become derived image `Artifact`s; `extractors.derived.DerivedMediaExtractor` runs the
image, face and OCR extractors on them and attributes the features back to the video.
HLS input (`.m3u8` or a folder of `.ts` segments) is concatenated from local files only.
[S3] `transcribe` turns the audio track into Polish text (`text.asr`) with faster-whisper.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path
from typing import Any, Literal

import numpy as np

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.core.text import normalize_text

logger = logging.getLogger(__name__)

SCENE_THRESHOLD = 0.3
MAX_SIDE = 960
MIN_GRID_FRAMES = 4
FFMPEG_TIMEOUT_S = 900
DEFAULT_CACHE = Path("data/runs/b_features")

_FRAME_RE = re.compile(r"frame:(\d+)\s+pts:\S+\s+pts_time:([-\d.]+)")
_SCORE_RE = re.compile(r"lavfi\.scene_score=([\d.]+)")


def _hls_segments(path: Path) -> list[Path]:
    """Return local `.ts` segments of an HLS playlist or folder, in play order."""
    folder = path if path.is_dir() else path.parent
    siblings = sorted(folder.glob("*.ts"))
    if path.is_dir():
        return siblings
    ordered: list[Path] = []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "://" in line:
            continue  # remote segments are never fetched
        name = Path(line).name
        exact = folder / name
        if exact.is_file():
            ordered.append(exact)
            continue
        # Saved-page tools rename "output_000.ts" to "output_000_<hash>.ts".
        stem = Path(name).stem
        match = next((s for s in siblings if s.stem.startswith(stem + "_")), None)
        if match is not None:
            ordered.append(match)
    return ordered or siblings


def _input_args(path: Path, workdir: Path) -> list[str]:
    """Build ffmpeg input arguments; HLS becomes a concat list of local segments."""
    if path.is_dir() or path.suffix.lower() == ".m3u8":
        segments = _hls_segments(path)
        if not segments:
            raise FileNotFoundError(f"no local .ts segments for {path}")
        listing = workdir / "segments.txt"
        lines = ["file '" + str(s.resolve()).replace("'", r"'\''") + "'" for s in segments]
        listing.write_text("\n".join(lines) + "\n")
        return ["-protocol_whitelist", "file", "-f", "concat", "-safe", "0", "-i", str(listing)]
    return ["-protocol_whitelist", "file", "-i", str(path)]


def _decode(path: Path, workdir: Path) -> list[tuple[float, float, Path]]:
    """Decode at 1 fps into `workdir`; return (time, scene score, frame file) per frame."""
    vf = (
        f"fps=1,scale=w='min({MAX_SIDE},iw)':h='min({MAX_SIDE},ih)'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2,"
        "select='gte(scene,0)',"
        f"metadata=print:key=lavfi.scene_score:file={workdir / 'scores.txt'}"
    )
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "error",
        *_input_args(path, workdir),
        "-an", "-sn", "-vf", vf, "-fps_mode", "passthrough",
        "-q:v", "3", str(workdir / "f%05d.jpg"),
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT_S, check=False)
    frames = sorted(workdir.glob("f*.jpg"))
    if proc.returncode != 0 and not frames:
        raise RuntimeError(proc.stderr.decode(errors="replace")[-500:])
    times: list[float] = []
    scores: list[float] = []
    scores_file = workdir / "scores.txt"
    text = scores_file.read_text() if scores_file.exists() else ""
    for line in text.splitlines():
        if m := _FRAME_RE.search(line):
            times.append(float(m.group(2)))
            scores.append(0.0)
        elif (m := _SCORE_RE.search(line)) and scores:
            scores[-1] = float(m.group(1))
    out = []
    for i, frame in enumerate(frames):
        t = times[i] if i < len(times) else float(i)
        s = scores[i] if i < len(scores) else 0.0
        out.append((t, s, frame))
    if out:
        t0 = out[0][0]  # HLS / edit lists may start at a non-zero timestamp
        out = [(t - t0, s, f) for t, s, f in out]
    return out


def _choose(scored: list[tuple[float, float, Path]], max_frames: int) -> list[int]:
    """Pick frame indices: scene cuts plus a uniform coverage grid (about one per 10 s).

    The grid keeps long cut-free stretches (screen recordings, talking heads) covered; when
    the union exceeds `max_frames`, the weakest scene cuts are dropped first.
    """
    n = len(scored)
    if n == 0 or max_frames <= 0:
        return []
    grid_size = min(n, max_frames, max(MIN_GRID_FRAMES, min(n // 10, max_frames // 2)))
    grid = set(np.linspace(0, n - 1, num=grid_size).round().astype(int).tolist())
    cuts = [i for i, (_, s, _) in enumerate(scored) if s > SCENE_THRESHOLD and i not in grid]
    cuts.sort(key=lambda i: scored[i][1], reverse=True)
    return sorted(grid | set(cuts[: max(0, max_frames - len(grid))]))


def _keyframe_files(path: Path, workdir: Path, max_frames: int) -> list[tuple[float, Path]]:
    scored = _decode(path, workdir)
    return [(scored[i][0], scored[i][2]) for i in _choose(scored, max_frames)]


def keyframes(path: Path, max_frames: int = 40) -> list[tuple[float, np.ndarray]]:
    """Return up to `max_frames` keyframes as (time in seconds, RGB uint8 array)."""
    import cv2

    with tempfile.TemporaryDirectory(prefix="kf_") as tmp:
        picked = _keyframe_files(Path(path), Path(tmp), max_frames)
        out = []
        for t, frame in picked:
            bgr = cv2.imread(str(frame), cv2.IMREAD_COLOR)
            if bgr is not None:
                out.append((t, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
        return out


def _preload_cuda_libs() -> None:
    """Make pip-installed cuBLAS/cuDNN (shipped with torch) visible to CTranslate2."""
    import ctypes

    for mod_name in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            mod = __import__(mod_name, fromlist=["__path__"])
        except ImportError:
            continue
        for lib_dir in (Path(p) / "lib" for p in mod.__path__):
            for lib in sorted(lib_dir.glob("lib*.so.*")):
                try:
                    ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    logger.debug("could not preload %s", lib)


ASR_BEAM_SIZE = 5
ASR_DECODE = f"t0-beam{ASR_BEAM_SIZE}-nocond"
"""Decoding settings, part of the ASR cache key: change it when the settings change."""


def asr_model() -> str:
    """Whisper model name: `FAKECOLLECTOR_ASR_MODEL`, else `turbo` on GPU and `small` on CPU."""
    from fakecollector.models import device

    default = "turbo" if device() == "cuda" else "small"
    return os.environ.get("FAKECOLLECTOR_ASR_MODEL", default)


@cache
def _whisper() -> Any:
    """Load faster-whisper once: GPU FP16, CPU int8 fallback (model from `asr_model`)."""
    from faster_whisper import WhisperModel

    from fakecollector.models import device

    name = asr_model()
    if device() == "cuda":
        _preload_cuda_libs()
        try:
            return WhisperModel(name, device="cuda", compute_type="float16")
        except (RuntimeError, ValueError) as exc:
            logger.warning("faster-whisper on GPU failed (%s); using CPU int8", exc)
    return WhisperModel(name, device="cpu", compute_type="int8")


def _audio(path: Path) -> np.ndarray:
    """Decode the audio track to 16 kHz mono float32 (empty when there is no audio)."""
    with tempfile.TemporaryDirectory(prefix="asr_") as tmp:
        cmd = [
            "ffmpeg", "-nostdin", "-v", "error", *_input_args(path, Path(tmp)),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-",
        ]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT_S, check=False)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def transcribe(path: Path) -> str:
    """Transcribe the video's speech in Polish; "" when there is no audio or speech.

    Decoding is deterministic: a single pass at temperature 0 (no temperature fallback,
    which samples), a fixed beam and no conditioning on the previous window's text, so two
    runs on the same input and model give the same transcript.
    """
    audio = _audio(Path(path))
    if audio.size < 16000:  # under one second of audio
        return ""
    segments, _ = _whisper().transcribe(
        audio,
        language="pl",
        vad_filter=True,
        beam_size=ASR_BEAM_SIZE,
        temperature=0.0,
        condition_on_previous_text=False,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


_OFF = {"0", "false", "off", "no"}
_ON = {"1", "true", "on", "yes"}


def asr_enabled() -> bool:
    """Whether videos get `text.asr`: `FAKECOLLECTOR_ASR` (default on); the choice is logged.

    The default does not depend on the hardware, so CPU and GPU runs produce the same
    feature set; `auto` (GPU only) is still accepted but logged as hardware-dependent.
    """
    raw = os.environ.get("FAKECOLLECTOR_ASR")
    wanted = (raw or "on").strip().lower()
    if wanted == "auto":
        from fakecollector.models import device

        enabled = device() == "cuda"
        _announce(logging.WARNING, f"ASR {_onoff(enabled)}: FAKECOLLECTOR_ASR=auto follows the GPU")
        return enabled
    if wanted not in _ON | _OFF:
        _announce(logging.WARNING, f"FAKECOLLECTOR_ASR={raw!r} not understood; ASR stays on")
    enabled = wanted not in _OFF
    source = "FAKECOLLECTOR_ASR" if raw is not None else "default; FAKECOLLECTOR_ASR=0 disables"
    detail = f", model {asr_model()}, decoding {ASR_DECODE}" if enabled else ""
    _announce(logging.INFO, f"ASR {_onoff(enabled)} ({source}){detail}")
    return enabled


@cache
def _announce(level: int, message: str) -> None:
    """Log each distinct ASR setting once per process, not once per video."""
    logger.log(level, message)


def _onoff(flag: bool) -> str:
    return "on" if flag else "off"


def _cache_root() -> Path:
    return Path(os.environ.get("FAKECOLLECTOR_B_CACHE", str(DEFAULT_CACHE)))


def _sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


class VideoExtractor:
    """Turns a video artifact into cached keyframe image artifacts (and [S3] a transcript).

    Deliberately not a `BaseExtractor`: on its own it yields no image features, so feature
    pipelines use `DerivedMediaExtractor`, which calls this class for keyframes and ASR.
    It still satisfies the `Extractor` protocol for the run_b ASR stage.
    """

    name = "video"
    version = 1
    stage = 1
    requires: Literal["base", "ml"] = "base"

    def __init__(self, cache_dir: Path | None = None, max_frames: int = 40) -> None:
        """Keyframes go to `<cache_dir>/keyframes/<artifact_id>/t=XX.Xs.jpg`."""
        self.cache_dir = cache_dir or _cache_root()
        self.max_frames = max_frames

    def supports(self, artifact: Artifact) -> bool:
        """Any video artifact (mp4/mov/webm/mkv/m3u8 or a folder of .ts segments)."""
        return artifact.kind == "video"

    def keyframe_artifacts(self, video: Artifact) -> list[Artifact]:
        """Extract (or reuse cached) keyframes and return them as image artifacts."""
        out_dir = self.cache_dir / "keyframes" / video.id
        manifest = out_dir / "manifest.json"
        if manifest.exists():
            try:
                entries = json.loads(manifest.read_text())
                if entries.get("version") == self.version and entries.get("max") == self.max_frames:
                    return [
                        self._artifact(video, out_dir / e["file"], e) for e in entries["frames"]
                    ]
            except (ValueError, KeyError, OSError):
                logger.warning("ignoring broken keyframe manifest %s", manifest)
        try:
            with tempfile.TemporaryDirectory(prefix="kf_") as tmp:
                picked = _keyframe_files(video.path, Path(tmp), self.max_frames)
                if out_dir.exists():
                    shutil.rmtree(out_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                frames = []
                for t, src in picked:
                    data = src.read_bytes()
                    name = f"t={t:05.1f}s.jpg"
                    (out_dir / name).write_bytes(data)
                    frames.append({"file": name, "t": f"{t:.1f}", "id": _sha16(data)})
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            logger.warning("keyframes failed for %s: %s", video.path, exc)
            return []
        manifest.write_text(
            json.dumps({"version": self.version, "max": self.max_frames, "frames": frames})
        )
        return [self._artifact(video, out_dir / e["file"], e) for e in frames]

    @staticmethod
    def _artifact(video: Artifact, path: Path, entry: dict[str, str]) -> Artifact:
        return Artifact(
            id=entry["id"],
            case_id=video.case_id,
            kind="image",
            role="screenshot",
            path=path,
            page=video.page,
            parent_id=video.id,
            size=path.stat().st_size if path.exists() else 0,
            meta={"t": entry["t"], "locator": f"t={entry['t']}s", "video_role": video.role},
        )

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Materialise keyframes in the cache and, when enabled, emit the `text.asr` transcript.

        Image features come from the image, face and OCR extractors run on
        `keyframe_artifacts(artifact)`.
        """
        self.keyframe_artifacts(artifact)
        if not asr_enabled():
            return []
        try:
            text = normalize_text(transcribe(artifact.path))
        except ImportError:
            logger.warning("faster-whisper not installed; ASR skipped")
            return []
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            logger.warning("ASR failed for %s: %s", artifact.path, exc)
            return []
        if len(text) < 3:
            return []
        return [
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="text.asr",
                value=text,
                locator="audio",
            )
        ]

    def extract_batch(
        self, artifacts: list[Artifact], priors: list[list[Feature]]
    ) -> list[list[Feature]]:
        """Loop over `extract` (one video at a time)."""
        return [self.extract(a, p) for a, p in zip(artifacts, priors, strict=True)]
