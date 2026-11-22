"""Local-feature verification of candidate image pairs (`local_match`).

Global descriptors (pHash, PDQ, SigLIP) rank candidates; this checks a short list
geometrically: keypoints + descriptors (SIFT by default, ORB as a fast fallback), ratio-test
matching and a RANSAC homography. A creative pasted into a feed screenshot, cropped, rescaled
or re-encoded keeps dozens of geometrically consistent matches; unrelated pictures keep a
handful. Meant for the fusion stage to confirm top-k pairs, not for all-pairs search.

SIFT is in OpenCV main since 4.4 (patent expired 2020, Apache-2.0 code); ORB is BSD.
Needs `opencv-python-headless` (extra `ml`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from fakecollector.core.schemas import Feature

Detector = Literal["sift", "orb"]

MAX_SIDE = 768
"""Images are matched at this long side: enough detail, bounded cost (~20-40 ms per image)."""

N_FEATURES = 1500
RATIO = 0.75
RANSAC_PX = 6.0
MIN_INLIERS = 15
"""Unrelated pictures rarely reach 10 consistent inliers; true variants give 30-500."""

MIN_COVERAGE = 0.1
"""The inliers must span this share of at least one image: the contained picture itself,
not a shared logo strip or platform button."""

MIN_SCALE, MAX_SCALE = 1 / 10, 10.0


class LocalMatch(NamedTuple):
    """Result of verifying one image pair."""

    inliers: int
    homography_ok: bool


@dataclass(frozen=True)
class LocalFeatures:
    """Keypoint coordinates (in the working raster) and descriptors of one image."""

    points: np.ndarray  # (n, 2) float32
    descriptors: np.ndarray | None
    detector: Detector
    size: tuple[int, int]  # working raster (w, h)


def _gray(im: Image.Image | np.ndarray) -> np.ndarray:
    """Grayscale uint8 raster with long side <= MAX_SIDE."""
    pil = im if isinstance(im, Image.Image) else Image.fromarray(np.asarray(im, dtype=np.uint8))
    pil = pil.convert("L")
    if max(pil.size) > MAX_SIDE:
        pil = pil.copy()
        pil.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return np.ascontiguousarray(np.asarray(pil, dtype=np.uint8))


def describe(im: Image.Image | np.ndarray, detector: Detector = "sift") -> LocalFeatures:
    """Detect keypoints and compute descriptors once, so one image can be matched many times."""
    import cv2

    gray = _gray(im)
    if detector == "sift":
        det = cv2.SIFT_create(nfeatures=N_FEATURES)
    else:
        det = cv2.ORB_create(nfeatures=N_FEATURES, scaleFactor=1.2, nlevels=10)
    kps, desc = det.detectAndCompute(gray, None)
    pts = np.array([k.pt for k in kps], dtype=np.float32).reshape(-1, 2)
    return LocalFeatures(pts, desc, detector, (gray.shape[1], gray.shape[0]))


def _homography_ok(h: np.ndarray, size: tuple[int, int]) -> bool:
    """Reject degenerate fits: mirrored, collapsed, exploded or non-convex projections."""
    import cv2

    a = h[:2, :2] / h[2, 2] if abs(h[2, 2]) > 1e-9 else h[:2, :2]
    det = float(np.linalg.det(a))
    if det <= 0:  # a mirror is not the same creative layout
        return False
    scale = det**0.5
    if not MIN_SCALE <= scale <= MAX_SCALE:
        return False
    w, h_ = size
    corners = np.array([[[0, 0]], [[w, 0]], [[w, h_]], [[0, h_]]], dtype=np.float32)
    proj = cv2.perspectiveTransform(corners, h)
    return bool(cv2.isContourConvex(proj.astype(np.float32)))


def match_features(a: LocalFeatures, b: LocalFeatures) -> LocalMatch:
    """Ratio-test matches between two described images, verified by a RANSAC homography."""
    import cv2

    if a.detector != b.detector:
        raise ValueError("features come from different detectors")
    if a.descriptors is None or b.descriptors is None:
        return LocalMatch(0, False)
    if len(a.points) < 4 or len(b.points) < 4:
        return LocalMatch(0, False)
    norm = cv2.NORM_L2 if a.detector == "sift" else cv2.NORM_HAMMING
    knn = cv2.BFMatcher(norm).knnMatch(a.descriptors, b.descriptors, k=2)
    ratio = RATIO if a.detector == "sift" else 0.8
    good = [m[0] for m in knn if len(m) == 2 and m[0].distance < ratio * m[1].distance]
    if len(good) < 4:
        return LocalMatch(0, False)
    src = a.points[[m.queryIdx for m in good]].reshape(-1, 1, 2)
    dst = b.points[[m.trainIdx for m in good]].reshape(-1, 1, 2)
    h, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_PX)
    if h is None or mask is None:
        return LocalMatch(0, False)
    keep = mask.ravel().astype(bool)
    inliers = int(keep.sum())
    ok = (
        inliers >= MIN_INLIERS
        and _homography_ok(h, a.size)
        and max(_coverage(src[keep], a.size), _coverage(dst[keep], b.size)) >= MIN_COVERAGE
    )
    return LocalMatch(inliers, ok)


def _coverage(points: np.ndarray, size: tuple[int, int]) -> float:
    """Share of the image covered by the convex hull of the inlier points."""
    import cv2

    if len(points) < 3:
        return 0.0
    hull = cv2.convexHull(points.reshape(-1, 2).astype(np.float32))
    return float(cv2.contourArea(hull)) / float(size[0] * size[1])


def local_match(
    img_a: Image.Image | np.ndarray,
    img_b: Image.Image | np.ndarray,
    detector: Detector = "sift",
) -> LocalMatch:
    """Verify whether `img_a` appears in `img_b` (or vice versa) up to crop, scale and re-encode.

    Args:
        img_a: First image (PIL or HxW[x3] uint8 array).
        img_b: Second image.
        detector: "sift" (robust to large scale changes, default) or "orb" (faster).

    Returns:
        `LocalMatch(inliers, homography_ok)`: RANSAC inlier count and whether a plausible,
        non-mirrored homography with at least `MIN_INLIERS` inliers spanning
        `MIN_COVERAGE` of one image was found. `homography_ok` means "the two images share
        a picture region", which is strong image evidence but not proof of one campaign:
        screenshots of the same cloned site chrome or a reused stock photo verify too.
    """
    return match_features(describe(img_a, detector), describe(img_b, detector))


SIGLIP_GATE = 0.88
"""SigLIP cosine from which a pair is worth a geometric check (audit 03: own creative
0.89-0.98, held-out singletons peak at 0.895, so the gate alone does not decide)."""

MAX_VERIFY = 12
"""Pairs verified per new case; each costs ~20-40 ms of SIFT once images are described."""


class VerifiedPair(NamedTuple):
    """One SigLIP candidate pair after local-feature verification."""

    new_artifact: str
    base_artifact: str
    base_case: str
    siglip: float
    inliers: int
    homography_ok: bool


def _unit(vector: Sequence[float]) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def siglip_candidates(
    new_features: Sequence[Feature],
    base_features: Sequence[Feature],
    gate: float = SIGLIP_GATE,
    limit: int = MAX_VERIFY,
) -> list[tuple[str, str, str, float]]:
    """Artifact pairs `(new_artifact, base_artifact, base_case, cosine)` with `img.siglip` >= gate.

    Every SigLIP view (whole, region crop, header, tile) counts; an artifact pair keeps its best
    cosine. Sorted by cosine, highest first, at most `limit` pairs.
    """
    new = [
        (f.artifact_id, _unit(f.vector))
        for f in new_features
        if f.name == "img.siglip" and f.vector
    ]
    base = [
        (f.artifact_id, f.case_id, _unit(f.vector))
        for f in base_features
        if f.name == "img.siglip" and f.vector
    ]
    best: dict[tuple[str, str], tuple[str, float]] = {}
    for new_art, u in new:
        for base_art, case, v in base:
            if u.shape != v.shape:
                continue
            cos = float(u @ v)
            key = (new_art, base_art)
            if cos >= gate and cos > best.get(key, ("", -1.0))[1]:
                best[key] = (case, cos)
    rows = [(a, b, case, cos) for (a, b), (case, cos) in best.items()]
    rows.sort(key=lambda row: (-row[3], row[0], row[1]))
    return rows[:limit]


def verify_siglip_candidates(
    new_features: Sequence[Feature],
    base_features: Sequence[Feature],
    artifact_paths: Mapping[str, Path],
    *,
    gate: float = SIGLIP_GATE,
    limit: int = MAX_VERIFY,
    detector: Detector = "sift",
    loader: Callable[[Path], Image.Image | None] | None = None,
) -> list[VerifiedPair]:
    """Geometrically verify SigLIP >= `gate` candidates of one new case against the base.

    Intended for the assign path (`graph/assign.py`, owner: Mateusz), NOT wired in yet. SigLIP
    alone cannot separate a re-cropped screenshot of a known creative (0.89-0.98) from an
    unrelated look-alike (up to 0.895 on held-out singletons); a RANSAC-verified local match can,
    because crop, rescale and JPEG keep the keypoint geometry. Suggested use: for a new case
    whose best campaign rests on `img.siglip`, call this with the new case's features, the
    base features and `{artifact.id: artifact.path}` from `RunStore.artifacts()`; treat a pair
    with `homography_ok` as image evidence of weight ~ PDQ (`kind="img.local_match"`,
    detail "Ten sam obraz po przycięciu/kompresji ({inliers} zgodnych punktów)"), and a SigLIP
    match without it as review-only.

    Args:
        new_features: Features of the new case (only `img.siglip` is read).
        base_features: Features of the base run (only `img.siglip` is read).
        artifact_paths: Artifact id -> image file, for both sides; missing ids are skipped.
        gate: Minimum SigLIP cosine for a pair to be verified.
        limit: At most this many pairs (highest cosine first) are verified.
        detector: "sift" (default) or "orb".
        loader: Image loader (defaults to the hashing loader: upright RGB, bomb-guarded).

    Returns:
        One `VerifiedPair` per verified candidate, in candidate order. Unreadable images are
        skipped; descriptors are computed once per artifact.
    """
    if loader is None:
        from fakecollector.extractors.image_hash import load_image

        loader = load_image
    load = loader
    cache: dict[str, LocalFeatures | None] = {}

    def features_of(artifact: str) -> LocalFeatures | None:
        if artifact not in cache:
            path = artifact_paths.get(artifact)
            im = load(path) if path is not None else None
            cache[artifact] = describe(im, detector) if im is not None else None
        return cache[artifact]

    out: list[VerifiedPair] = []
    for new_art, base_art, case, cos in siglip_candidates(new_features, base_features, gate, limit):
        a, b = features_of(new_art), features_of(base_art)
        if a is None or b is None:
            continue
        m = match_features(a, b)
        out.append(VerifiedPair(new_art, base_art, case, cos, m.inliers, m.homography_ok))
    return out
