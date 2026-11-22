"""Build the public-figure face reference DB from a directory of per-person photo folders.

Usage:
    python scripts/build_face_db.py data/faces/refs [--out data/faces/db.npz]

Input layout: `<dir>/<person-slug>/*.{jpg,png,webp}` (see `scripts/fetch_face_refs.py`).
Group photos are fine: in each photo the face closest to the person's other references is
taken (seeded by the largest face of single-face photos, then re-picked against the person's
median face), and faces that agree poorly with the rest (cosine < 0.35 to the element-wise
median of the person's faces, or < 0.35 to every other photo) are dropped and reported: a
wrong-person photo would poison the centroid.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path

import numpy as np

from fakecollector.extractors.face import Face, FaceDB, decode_image, get_embedder

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MIN_AGREEMENT = 0.35


def _unit(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _person_embeddings(
    photos: list[tuple[str, list[Face]]],
) -> tuple[list[np.ndarray], list[str], list[str]]:
    """Pick one face per photo for one person; returns embeddings, kept sha256s, notes."""
    usable = [(sha, [f for f in faces if f.det_score >= 0.6]) for sha, faces in photos]
    usable = [(sha, faces) for sha, faces in usable if faces]
    singles = [max(faces, key=lambda f: f.size).embedding for _, faces in usable if len(faces) == 1]
    if not singles:  # only group photos: trust the largest face of each
        singles = [max(faces, key=lambda f: f.size).embedding for _, faces in usable]
    seed = _unit(np.median(np.stack(singles), axis=0)) if singles else None
    if seed is None:
        return [], [], ["no usable face"]
    shas = [sha for sha, _ in usable]
    embs = [max(faces, key=lambda f: float(f.embedding @ seed)).embedding for _, faces in usable]
    if len(embs) < 3:
        if len(embs) == 2 and float(embs[0] @ embs[1]) < MIN_AGREEMENT:
            return embs, shas, [f"WARNING: 2 photos disagree (cos {float(embs[0] @ embs[1]):.2f})"]
        return embs, shas, []
    # Re-pick each photo's face against the robust (median) face, then drop disagreeing ones.
    median = _unit(np.median(np.stack(embs), axis=0))
    embs = [max(faces, key=lambda f: float(f.embedding @ median)).embedding for _, faces in usable]
    median = _unit(np.median(np.stack(embs), axis=0))
    agree = [float(e @ median) for e in embs]
    # With few photos the median sits close to every one of them; also require each photo to
    # agree with at least one other photo of the person.
    stack = np.stack(embs)
    pair = stack @ stack.T
    np.fill_diagonal(pair, -1.0)
    best = pair.max(axis=1)
    keep = [i for i, c in enumerate(agree) if c >= MIN_AGREEMENT and best[i] >= MIN_AGREEMENT]
    notes = [
        f"dropped {shas[i][:8]} (cos to median {agree[i]:.2f}, best other {best[i]:.2f})"
        for i in range(len(embs))
        if i not in keep
    ]
    return [embs[i] for i in keep], [shas[i] for i in keep], notes


def build(root: Path) -> FaceDB:
    """Embed every reference photo under `root` and return the DB."""
    embedder = get_embedder()
    slugs: list[str] = []
    centroids, all_embs, owners, ref_sha = [], [], [], []
    for person_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        photos = []
        for path in sorted(person_dir.iterdir()):
            if path.suffix.lower() not in IMAGE_EXT:
                continue
            data = path.read_bytes()
            img = decode_image(data)
            if img is None:
                print(f"  {person_dir.name}: unreadable {path.name}")
                continue
            photos.append((hashlib.sha256(data).hexdigest(), embedder.embed([img])[0]))
        embs, shas, notes = _person_embeddings(photos)
        if not embs:
            print(f"  {person_dir.name}: SKIPPED ({'; '.join(notes)})")
            continue
        idx = len(slugs)
        slugs.append(person_dir.name)
        stack = np.stack(embs).astype(np.float32)
        centroid = _unit(stack.mean(axis=0))
        centroids.append(centroid)
        all_embs.extend(stack)
        owners.extend([idx] * len(embs))
        ref_sha.extend(shas)
        pair = stack @ stack.T
        off = pair[~np.eye(len(stack), dtype=bool)]
        spread = (
            f"pairwise cos min {off.min():.2f} mean {off.mean():.2f}" if off.size else "1 photo"
        )
        print(
            f"  {person_dir.name}: {len(embs)}/{len(photos)} photos, {spread}"
            + (f"; {'; '.join(notes)}" if notes else "")
        )
    return FaceDB(
        slugs=slugs,
        centroids=np.stack(centroids).astype(np.float32),
        embeddings=np.stack(all_embs).astype(np.float32),
        owners=np.array(owners, dtype=np.int64),
        ref_sha256=ref_sha,
    )


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help="directory of <person-slug>/ photo folders")
    ap.add_argument("--out", type=Path, default=Path("data/faces/db.npz"))
    args = ap.parse_args()
    db = build(args.root)
    db.save(args.out)
    cross = db.centroids @ db.centroids.T
    np.fill_diagonal(cross, -1)
    print(
        f"wrote {args.out}: {len(db.slugs)} people, {len(db.embeddings)} reference faces; "
        f"max cross-person centroid cos {cross.max():.2f}"
    )


if __name__ == "__main__":
    main()
