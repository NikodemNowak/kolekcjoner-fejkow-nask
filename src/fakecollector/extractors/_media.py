"""Shared media helpers for the vision extractors."""

from __future__ import annotations

from fakecollector.core.schemas import Artifact

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def is_image(artifact: Artifact) -> bool:
    """True for image artifacts, including landing-page assets that are images.

    Ingest types files inside `_files/` as `kind="asset"` whatever their format, so the
    suffix decides for those.
    """
    if artifact.kind == "image":
        return True
    return artifact.kind == "asset" and artifact.path.suffix.lower() in IMAGE_SUFFIXES
