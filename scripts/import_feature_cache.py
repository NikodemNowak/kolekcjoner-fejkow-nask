"""Unpack a shared feature-cache archive into the local cache (`FEATURE_CACHE` or ~/.cache).

Verifies the archive's sha256 against `<archive>.manifest.json` when that file is present,
then extracts only `features/` and `keyframes/` entries. Existing files are kept unless
`--overwrite`. Afterwards a `b_extract_all.py` run over the same corpora should report every
stage as cached with 0 computed.

Usage:
    PYTHONPATH=src python scripts/import_feature_cache.py data/exports/feature-cache-<date>.tar.gz
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    """Verify and extract the archive."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("--cache", type=Path, default=None, help="default: FEATURE_CACHE")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    from fakecollector.dev.cache_share import extract_archive, read_manifest, sha256_file
    from fakecollector.dev.run_b import default_cache_root

    man_path = args.manifest or args.archive.with_name(args.archive.name + ".manifest.json")
    if man_path.exists():
        expected = json.loads(man_path.read_text()).get("sha256")
        actual = sha256_file(args.archive)
        if expected != actual:
            print(f"sha256 mismatch: manifest {expected}, archive {actual}")
            return 1
        print(f"sha256 ok ({actual})")
    else:
        print(f"no manifest at {man_path}; sha256 not verified")
    inner = read_manifest(args.archive) or {}
    cache_root = args.cache or default_cache_root()
    counts = extract_archive(args.archive, cache_root, overwrite=args.overwrite)
    for name, versions in inner.get("extractors", {}).items():
        for ver, n in versions.items():
            print(f"{name:14} {ver:36} {n:5} entries")
    print(
        f"-> {cache_root}: {counts['written']} written, {counts['kept']} already present, "
        f"{counts['rejected']} rejected"
    )
    return 0 if counts["rejected"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
