"""Public-figure faces (signal 7): detect faces, match them against a reference DB.

Also emits `img.face_share` (area share of the largest face, a number without identity) so
graph/signals.py can keep portrait-like images out of SigLIP comparisons, and matches faces
again in the creative regions of screenshots, upscaled x2, where faces are small.

GDPR: only faces that match a public figure in the reference DB produce a feature.
Embeddings of unmatched faces live only in memory for the duration of one image and are
never stored, logged or emitted.

The default backend is InsightFace buffalo_l (weights licensed for non-commercial research
only); it sits behind the `FaceEmbedder` protocol so it can be swapped via `FACE_BACKEND`.
"""

from __future__ import annotations

import io
import logging
import os
import warnings
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors._media import is_image
from fakecollector.models import device

logger = logging.getLogger(__name__)

FEATURE_NAME = "person.public_figure"
SHARE_FEATURE = "img.face_share"
CROP_ROLES = {"screenshot", "ad_creative"}
CROP_UPSCALE = 2
MIN_REPORTED_SHARE = 0.2  # smaller faces never gate anything; keep the feature table small
SUPPORTED_ROLES = {"screenshot", "ad_creative", "landing_asset", "other"}
MAX_IMAGE_BYTES = 60 << 20
MAX_LONG_SIDE = 1600  # downscale huge captures before tiling; faces stay far above 40 px
TILE_ASPECT = 1.5  # tall full-page screenshots are cut into tiles of this height/width ratio


@dataclass(frozen=True)
class FaceConfig:
    """Thresholds and paths for face matching, read from the environment."""

    backend: str = "insightface"
    db_path: Path = Path("data/faces/db.npz")
    threshold: float = 0.40  # calibrated on both corpora; see docs/results-vision.md
    min_det_score: float = 0.6
    min_face_px: int = 40
    min_image_px: int = 120
    # Faces of 24-40 px (thumbnails in feeds, insets in composite ads) still embed well: on
    # the wild set true small faces scored 0.53-0.75 and the best wrong one 0.38, so they
    # count only with a stricter score.
    small_face_px: int = 24
    small_face_threshold: float = 0.50

    @classmethod
    def from_env(cls) -> FaceConfig:
        """Build the config from `FACE_*` environment variables."""
        env = os.environ
        return cls(
            backend=env.get("FACE_BACKEND", cls.backend),
            db_path=Path(env.get("FACE_DB", str(cls.db_path))),
            threshold=float(env.get("FACE_THRESHOLD", cls.threshold)),
            min_det_score=float(env.get("FACE_MIN_DET_SCORE", cls.min_det_score)),
            min_face_px=int(env.get("FACE_MIN_SIZE", cls.min_face_px)),
            min_image_px=int(env.get("FACE_MIN_IMAGE", cls.min_image_px)),
            small_face_px=int(env.get("FACE_SMALL_SIZE", cls.small_face_px)),
            small_face_threshold=float(env.get("FACE_SMALL_THRESHOLD", cls.small_face_threshold)),
        )


@dataclass
class Face:
    """One detected face: bbox `(x, y, w, h)` in image pixels and a unit 512-d embedding."""

    bbox: tuple[int, int, int, int]
    det_score: float
    embedding: np.ndarray = field(repr=False)
    size: int = 0  # min(w, h) in pixels

    def __post_init__(self) -> None:
        if not self.size:
            self.size = min(self.bbox[2], self.bbox[3])


class FaceEmbedder(Protocol):
    """Detects faces and embeds them; images are BGR uint8 arrays."""

    def embed(self, images: list[np.ndarray]) -> list[list[Face]]:
        """Return the faces of every image (same order as the input)."""
        ...


@cache
def _insightface_app(use_cuda: bool) -> Any:
    """Load buffalo_l (detection + recognition only) once per process."""
    from insightface.app import FaceAnalysis

    providers: list[str] = ["CPUExecutionProvider"]
    options: list[dict[str, str]] = [{}]
    if use_cuda:
        # The GPU is shared with other extractors: cap the ONNX arena.
        providers.insert(0, "CUDAExecutionProvider")
        options.insert(
            0, {"gpu_mem_limit": str(2 << 30), "arena_extend_strategy": "kSameAsRequested"}
        )
    app = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection", "recognition"],
        providers=providers,
        provider_options=options,
    )
    app.prepare(ctx_id=0 if use_cuda else -1, det_size=(640, 640))
    active = app.models["detection"].session.get_providers()
    if use_cuda and "CUDAExecutionProvider" not in active:
        logger.warning("InsightFace: CUDAExecutionProvider not active, running on %s", active)
    logger.info("InsightFace buffalo_l loaded with providers %s", active)
    return app


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _tiles(height: int, width: int) -> list[int]:
    """Top offsets of overlapping tiles covering a tall image (one tile if not tall)."""
    tile_h = int(width * TILE_ASPECT)
    if height <= tile_h * 1.2:
        return [0]
    step = int(tile_h * 0.75)
    tops = list(range(0, height - tile_h, step))
    tops.append(height - tile_h)
    return tops


class InsightFaceEmbedder:
    """InsightFace buffalo_l (SCRFD-10G detector + ArcFace R50), det_size 640."""

    def __init__(self, use_cuda: bool | None = None) -> None:
        self.use_cuda = device() == "cuda" if use_cuda is None else use_cuda

    @property
    def providers(self) -> list[str]:
        """ONNX Runtime providers actually in use (loads the model)."""
        return list(_insightface_app(self.use_cuda).models["detection"].session.get_providers())

    def _embed_one(self, image: np.ndarray) -> list[Face]:
        import cv2

        app = _insightface_app(self.use_cuda)
        h, w = image.shape[:2]
        scale = 1.0
        if w > MAX_LONG_SIDE:
            scale = MAX_LONG_SIDE / w
            image = cv2.resize(
                image, (MAX_LONG_SIDE, max(1, int(h * scale))), interpolation=cv2.INTER_AREA
            )
            h, w = image.shape[:2]
        faces: list[Face] = []
        tops = _tiles(h, w)
        for top in tops:
            tile = image if len(tops) == 1 else image[top : top + int(w * TILE_ASPECT)]
            with warnings.catch_warnings():
                # insightface's alignment calls a deprecated scikit-image API on every face.
                warnings.simplefilter("ignore", FutureWarning)
                detected = app.get(np.ascontiguousarray(tile))
            for f in detected:
                x1, y1, x2, y2 = (float(v) for v in f.bbox)
                box = (
                    round(x1 / scale),
                    round((y1 + top) / scale),
                    round((x2 - x1) / scale),
                    round((y2 - y1) / scale),
                )
                emb = np.asarray(f.normed_embedding, dtype=np.float32)
                face = Face(bbox=box, det_score=float(f.det_score), embedding=emb)
                dup = next((i for i, g in enumerate(faces) if _iou(g.bbox, box) > 0.4), None)
                if dup is None:
                    faces.append(face)
                elif face.det_score > faces[dup].det_score:
                    faces[dup] = face
        return faces

    def embed(self, images: list[np.ndarray]) -> list[list[Face]]:
        """Detect and embed faces in BGR images; a failing image yields `[]`."""
        out: list[list[Face]] = []
        for img in images:
            try:
                out.append(self._embed_one(img))
            except Exception:  # one bad image must not stop the batch
                logger.warning("face embedding failed for one image", exc_info=True)
                out.append([])
        return out


@cache
def get_embedder(backend: str = "insightface") -> FaceEmbedder:
    """Return the face embedder for `backend` (env `FACE_BACKEND`)."""
    if backend == "insightface":
        return InsightFaceEmbedder()
    raise ValueError(f"unknown FACE_BACKEND: {backend}")


def decode_image(data: bytes) -> np.ndarray | None:
    """Decode image bytes to a BGR uint8 array; `None` for corrupt or unsupported data."""
    import cv2

    if not data:
        return None
    img = None
    if not data.startswith((b"GIF87a", b"GIF89a")):  # OpenCV's GIF reader logs noisy errors
        try:
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        except cv2.error:
            img = None
    if img is None:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as pil:
                pil.seek(0)
                rgb = np.asarray(pil.convert("RGB"))
            img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    return img if img.ndim == 3 and img.shape[2] == 3 else None


@dataclass
class FaceDB:
    """Reference embeddings of public figures (`data/faces/db.npz`)."""

    slugs: list[str]
    centroids: np.ndarray  # (P, 512), unit rows
    embeddings: np.ndarray  # (N, 512), unit rows
    owners: np.ndarray  # (N,) index into slugs
    ref_sha256: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> FaceDB:
        """Load a DB written by `scripts/build_face_db.py`."""
        with np.load(path, allow_pickle=False) as z:
            return cls(
                slugs=[str(s) for s in z["slugs"]],
                centroids=z["centroids"].astype(np.float32),
                embeddings=z["embeddings"].astype(np.float32),
                owners=z["owners"].astype(np.int64),
                ref_sha256=[str(s) for s in z["ref_sha256"]] if "ref_sha256" in z else [],
            )

    def save(self, path: Path) -> None:
        """Write the DB as a compressed npz."""
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            slugs=np.array(self.slugs),
            centroids=self.centroids,
            embeddings=self.embeddings,
            owners=self.owners,
            ref_sha256=np.array(self.ref_sha256),
        )

    def match(self, embedding: np.ndarray) -> tuple[str, float]:
        """Best person and its score: max of cosine to the centroid and to the best reference."""
        cent = self.centroids @ embedding
        refs = self.embeddings @ embedding
        best_ref = np.full(len(self.slugs), -1.0, dtype=np.float32)
        np.maximum.at(best_ref, self.owners, refs)
        scores = np.maximum(cent, best_ref)
        i = int(np.argmax(scores))
        return self.slugs[i], float(scores[i])


@cache
def load_face_db(path: str) -> FaceDB | None:
    """Load the reference DB once; `None` (with a warning) if it is missing or unreadable."""
    p = Path(path)
    if not p.is_file():
        logger.warning("face reference DB %s not found; person.public_figure disabled", p)
        return None
    try:
        return FaceDB.load(p)
    except Exception:  # a broken DB disables the signal, never the run
        logger.warning("face reference DB %s unreadable", p, exc_info=True)
        return None


class FaceExtractor(BaseExtractor):
    """`person.public_figure`: faces matched against the public-figure reference DB."""

    name = "face"
    version = 3
    stage = 2
    requires = "ml"

    def __init__(
        self,
        config: FaceConfig | None = None,
        embedder: FaceEmbedder | None = None,
        db: FaceDB | None = None,
    ) -> None:
        self.config = config or FaceConfig.from_env()
        self._embedder = embedder
        self._db = db

    @property
    def embedder(self) -> FaceEmbedder:
        """The face embedder (created lazily)."""
        if self._embedder is None:
            self._embedder = get_embedder(self.config.backend)
        return self._embedder

    @property
    def db(self) -> FaceDB | None:
        """The reference DB (loaded lazily)."""
        if self._db is None:
            self._db = load_face_db(str(self.config.db_path))
        return self._db

    def supports(self, artifact: Artifact) -> bool:
        """Images in screenshot / ad creative / content-image roles."""
        return is_image(artifact) and artifact.role in SUPPORTED_ROLES

    def _load(self, artifact: Artifact) -> np.ndarray | None:
        try:
            if artifact.path.stat().st_size > MAX_IMAGE_BYTES:
                logger.warning("face: %s too large, skipped", artifact.path)
                return None
            img = decode_image(artifact.path.read_bytes())
        except OSError:
            logger.warning("face: cannot read %s", artifact.path)
            return None
        if img is None or min(img.shape[:2]) < self.config.min_image_px:
            return None
        return img

    def match_faces(
        self, case_id: str, artifact_id: str, faces: list[Face], locator_prefix: str = ""
    ) -> list[Feature]:
        """Turn detected faces into features; unmatched faces are dropped here."""
        db = self.db
        if db is None:
            return []
        best: dict[str, tuple[float, Face]] = {}
        cfg = self.config
        for face in faces:
            if face.det_score < cfg.min_det_score or face.size < cfg.small_face_px:
                continue
            slug, score = db.match(face.embedding)
            needed = cfg.threshold if face.size >= cfg.min_face_px else cfg.small_face_threshold
            if score >= needed and score > best.get(slug, (-1.0, face))[0]:
                best[slug] = (score, face)
        feats = []
        for slug, (score, face) in sorted(best.items()):
            x, y, w, h = face.bbox
            feats.append(
                Feature(
                    case_id=case_id,
                    artifact_id=artifact_id,
                    name=FEATURE_NAME,
                    value=slug,
                    confidence=round(score, 4),
                    locator=f"{locator_prefix}bbox={x},{y},{w},{h}",
                )
            )
        return feats

    def extract_images(
        self,
        case_id: str,
        artifact_id: str,
        images: list[np.ndarray],
        locators: list[str] | None = None,
    ) -> list[Feature]:
        """Features for in-memory BGR images, e.g. video keyframes (`locators` like "t=14.0s ")."""
        if self.db is None or not images:
            return []
        locs = locators or [""] * len(images)
        feats: list[Feature] = []
        for faces, loc in zip(self.embedder.embed(images), locs, strict=True):
            feats.extend(self.match_faces(case_id, artifact_id, faces, loc))
        return feats

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Detect and match faces in one image artifact; never raises on bad input."""
        return self.extract_batch([artifact], [prior])[0]

    def extract_batch(
        self, artifacts: list[Artifact], priors: list[list[Feature]]
    ) -> list[list[Feature]]:
        """Decode all images, embed them in one pass, keep only public-figure matches."""
        out: list[list[Feature]] = [[] for _ in artifacts]
        if self.db is None:
            return out
        # Decode in chunks so a large batch never holds hundreds of full-page captures in RAM.
        for start in range(0, len(artifacts), 16):
            idx, imgs = [], []
            for i in range(start, min(start + 16, len(artifacts))):
                art = artifacts[i]
                img = self._load(art) if self.supports(art) else None
                if img is not None:
                    idx.append(i)
                    imgs.append(img)
            for i, img, faces in zip(idx, imgs, self.embedder.embed(imgs), strict=True):
                art = artifacts[i]
                out[i] = self.match_faces(art.case_id, art.id, faces)
                if (share := self._face_share(img, faces)) >= MIN_REPORTED_SHARE:
                    out[i].append(share_feature(art, share))
                if art.role in CROP_ROLES:
                    out[i] += self._crop_matches(art, img, {f.value for f in out[i]})
        return out

    def _face_share(self, img: np.ndarray, faces: list[Face]) -> float:
        """Area share of the largest confidently detected face (geometry only)."""
        area = img.shape[0] * img.shape[1]
        boxes = [f.bbox[2] * f.bbox[3] for f in faces if f.det_score >= self.config.min_det_score]
        return min(1.0, max(boxes) / area) if boxes and area else 0.0

    def _crop_matches(self, art: Artifact, img: np.ndarray, found: set[str]) -> list[Feature]:
        """Faces in the creative regions of a screenshot, upscaled so small faces count.

        A composite ad shows the public figure small inside a feed frame; at screenshot
        scale the face is under `min_face_px` or too blurry for the detector. Each region
        (`regions.content_regions`) is enlarged `CROP_UPSCALE` times and matched again;
        only figures not already found in the whole image are added.
        """
        import cv2
        from PIL import Image

        from fakecollector.extractors.regions import content_regions

        rgb = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        regions = content_regions(rgb)
        if not regions:
            return []
        crops = [
            cv2.resize(
                img[r.y : r.y + r.h, r.x : r.x + r.w],
                (r.w * CROP_UPSCALE, r.h * CROP_UPSCALE),
                interpolation=cv2.INTER_CUBIC,
            )
            for r in regions
        ]
        feats: list[Feature] = []
        for region, faces in zip(regions, self.embedder.embed(crops), strict=True):
            # Boxes back in whole-image pixels (crops of the face are cut from the original);
            # `size` stays the upscaled one, which is what the size gate was calibrated on.
            placed = [
                Face(
                    bbox=(
                        region.x + f.bbox[0] // CROP_UPSCALE,
                        region.y + f.bbox[1] // CROP_UPSCALE,
                        max(1, f.bbox[2] // CROP_UPSCALE),
                        max(1, f.bbox[3] // CROP_UPSCALE),
                    ),
                    det_score=f.det_score,
                    embedding=f.embedding,
                    size=f.size,
                )
                for f in faces
            ]
            for feat in self.match_faces(art.case_id, art.id, placed, f"{region.locator} x2 "):
                if feat.value not in found:
                    found.add(feat.value)
                    feats.append(feat)
        return feats


def share_feature(art: Artifact, share: float) -> Feature:
    """`img.face_share`: how much of the image the largest face covers (no identity)."""
    return Feature(
        case_id=art.case_id,
        artifact_id=art.id,
        name=SHARE_FEATURE,
        value=f"{share:.2f}",
        locator="",
    )
