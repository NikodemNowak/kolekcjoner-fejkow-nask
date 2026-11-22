"""Exact file reuse: `asset.sha256` over saved page assets and HAR bodies (signal 2)."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.graph.stoplist import is_library_asset
from fakecollector.ingest.har import HarError, iter_bodies

logger = logging.getLogger(__name__)

MIN_ASSET_BYTES = 512  # tracking pixels, empty JSON and 1x1 gifs carry no signal
# A Meta pixel's config script is saved under the pixel ID (`…_files/<pixel id>`) or
# fetched from `connect.facebook.net/signals/config/<id>`: it identifies the ad account
# (operator), so it becomes `ids.fb_pixel` (har_ids) and never campaign-tier file evidence.
PIXEL_CONFIG_NAME = re.compile(r"^\d{10,20}(\.js)?(\.pobrane|\.pobierz)?$")
PIXEL_CONFIG_URL = re.compile(r"connect\.facebook\.net/signals/config/\d+", re.I)


def _head(path: Path) -> str:
    try:
        with path.open("rb") as f:
            return f.read(512).decode("utf-8", "replace")
    except OSError:
        return ""


def is_shared_code(name: str, head: str = "") -> bool:
    """Pixel config scripts and third-party library builds: never campaign evidence."""
    return bool(PIXEL_CONFIG_NAME.match(name)) or is_library_asset(name, head)


class AssetExtractor(BaseExtractor):
    """Hash every landing asset and HAR response body of at least 512 bytes.

    Case-level screenshots are left to the vision extractors (perceptual hashes). Pixel
    config scripts and library builds (jQuery, Swiper, `fbevents.js`, ...) are skipped:
    they are the same bytes on unrelated sites, so they say nothing about a campaign.
    """

    name = "asset"
    version = 2  # v2: pixel configs and library builds skipped

    def supports(self, artifact: Artifact) -> bool:
        """Landing assets and HARs."""
        return artifact.kind == "har" or (
            artifact.kind == "asset" and artifact.role == "landing_asset"
        )

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """One feature per distinct file hash."""
        if artifact.kind == "asset":
            if artifact.size < MIN_ASSET_BYTES:
                return []
            if is_shared_code(artifact.path.name, _head(artifact.path)):
                return []
            digest = artifact.meta.get("sha256")
            if not digest:
                try:
                    digest = hashlib.sha256(artifact.path.read_bytes()).hexdigest()
                except OSError:
                    return []
            return [self._feature(artifact, digest, artifact.meta.get("rel", "file"))]
        out: list[Feature] = []
        seen: set[str] = set()
        try:
            for i, url, body in iter_bodies(artifact.path):
                if len(body) < MIN_ASSET_BYTES:
                    continue
                name = url.split("?")[0].rsplit("/", 1)[-1]
                head = body[:512].decode("utf-8", "replace")
                if PIXEL_CONFIG_URL.search(url) or is_shared_code(name, head):
                    continue
                digest = hashlib.sha256(body).hexdigest()
                if digest not in seen:
                    seen.add(digest)
                    out.append(self._feature(artifact, digest, f"entry[{i}].response.content"))
        except HarError as exc:
            logger.warning("%s: %s", artifact.case_id, exc)
        return out

    def _feature(self, artifact: Artifact, digest: str, locator: str) -> Feature:
        return Feature(
            case_id=artifact.case_id,
            artifact_id=artifact.id,
            name="asset.sha256",
            value=digest,
            locator=locator,
        )
