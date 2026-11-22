"""Pack the feature cache entries of the corpora into `data/exports/feature-cache-<date>.tar.gz`.

Writes the archive plus `<archive>.manifest.json` (extractor names, cache versions, entry
counts, archive size and sha256). The archive holds organizer-derived data (OCR/ASR text):
share it only privately inside the team, never in git or via public links.

Usage:
    PYTHONPATH=src python scripts/export_feature_cache.py [--all] [--out data/exports]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Collect cache entries for the corpora, write the archive and its manifest."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "exports")
    parser.add_argument("--cache", type=Path, default=None, help="default: FEATURE_CACHE")
    parser.add_argument("--all", action="store_true", help="export every entry, not only corpora")
    args = parser.parse_args()

    from fakecollector.dev.cache_share import (
        collect_entries,
        keyframe_ids,
        sha256_file,
        summarize,
        write_archive,
    )
    from fakecollector.dev.run_b import DEFAULT_CORPORA, default_cache_root, scan_all

    cache_root = args.cache or default_cache_root()
    ids: set[str] | None = None
    if not args.all:
        arts = scan_all([(ROOT / root, corpus) for root, corpus in DEFAULT_CORPORA])
        if not arts:
            print("no corpus found under data/; use --all to export the whole cache")
            return 1
        ids = {a.id for a in arts}
        ids |= keyframe_ids(cache_root, {a.id for a in arts if a.kind == "video"})
    entries = collect_entries(cache_root, ids)
    if not entries:
        print(f"nothing to export from {cache_root}")
        return 1
    stats = summarize(entries)
    now = datetime.now(UTC)
    archive = args.out / f"feature-cache-{now:%Y-%m-%d}.tar.gz"
    manifest = {
        "format": 1,
        "created_at": now.isoformat(timespec="seconds"),
        "scope": "all" if args.all else "corpora",
        "artifact_ids": None if ids is None else len(ids),
        **stats,
    }
    write_archive(cache_root, entries, archive, manifest)
    manifest |= {
        "archive": archive.name,
        "size_bytes": archive.stat().st_size,
        "sha256": sha256_file(archive),
    }
    man_path = archive.with_name(archive.name + ".manifest.json")
    man_path.write_text(json.dumps(manifest, indent=2))
    for name, versions in manifest["extractors"].items():
        for ver, n in versions.items():
            print(f"{name:14} {ver:36} {n:5} entries")
    kf = manifest["keyframes"]
    print(f"keyframes      {kf['videos']} videos, {kf['frames']} frames")
    print(f"{archive} ({manifest['size_bytes'] / 2**20:.1f} MiB, sha256 {manifest['sha256']})")
    print(f"manifest -> {man_path}")
    print("Private to the team: contains organizer-derived OCR/ASR text. Never commit or publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
