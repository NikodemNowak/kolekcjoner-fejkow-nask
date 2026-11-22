"""Vision features for media that hold images inside them: video, MHTML archives and PDFs.

A video, a saved `page.mhtml` or a printed `page.pdf` yields no features by itself. This
extractor derives image artifacts from it (video keyframes, decoded MHTML image parts,
rendered PDF pages), runs every vision extractor that supports them (perceptual hashes,
SigLIP + brands, faces, OCR) and returns their features re-attributed to the ORIGINAL
artifact, with a locator naming where inside it they were found (`t=12.0s bbox=...`,
`mhtml:part=3`, `pdf:page=2`). Videos also get the `text.asr` transcript when ASR is on.
An MHTML also yields its archived page as a derived `landing_page` HTML artifact;
`expand_derived` adds it to the run so every HTML extractor reads it like a saved page.

Derived images are written to a content-addressed cache (`FAKECOLLECTOR_B_CACHE`), never
next to the corpus. Nothing in an MHTML or PDF is executed or fetched: MIME parts are decoded
with the standard `email` parser, PDF pages are rasterised by PDFium (no JavaScript).
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import io
import logging
import subprocess
from collections.abc import Collection, Sequence
from email.message import EmailMessage
from importlib import import_module
from pathlib import Path
from typing import Literal

from fakecollector.config import get_settings
from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature, Role
from fakecollector.core.text import normalize_text
from fakecollector.ingest.normalize import redact_url

logger = logging.getLogger(__name__)

MIN_SIDE = 120  # same floor as the image extractors: smaller parts are icons and pixels
MAX_MHTML_IMAGES = 200
MAX_PART_BYTES = 30 << 20
MAX_PDF_PAGES = 5
PDF_DPI = 150
MAX_PAGE_SIDE = 4000  # caps an oversized page box (posters, endless "print to PDF" pages)
BATCH = 32
_IMAGE_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}

# Vision extractors run on derived images, as (module, class) so they load lazily and an
# install without the `ml` extra simply skips the model-backed ones.
VISION_EXTRACTORS: tuple[tuple[str, str], ...] = (
    ("fakecollector.extractors.image_hash", "ImageHashExtractor"),
    ("fakecollector.extractors.image_embed", "SiglipExtractor"),
    ("fakecollector.extractors.face", "FaceExtractor"),
    ("fakecollector.extractors.ocr", "OcrExtractor"),
)


def _sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def combine_locator(prefix: str, inner: str) -> str:
    """Join the position in the source (`t=12.0s`) with the one inside the image (`bbox=...`)."""
    inner = inner.strip()
    if not inner or inner == prefix or inner.startswith(prefix + " "):
        return inner or prefix
    return f"{prefix} {inner}"


def _too_big(path: Path) -> bool:
    try:
        size = path.stat().st_size if path.is_file() else 0
    except OSError:
        return True
    return size > get_settings().max_artifact_mb << 20


def _derived(
    source: Artifact, path: Path, data: bytes, locator: str, role: Role, **meta: str
) -> Artifact:
    return Artifact(
        id=_sha16(data),
        case_id=source.case_id,
        kind="image",
        role=role,
        path=path,
        page=source.page,
        parent_id=source.id,
        size=len(data),
        meta={"locator": locator, "source_kind": source.kind, **meta},
    )


def _read_mhtml(source: Artifact) -> EmailMessage | None:
    """Parse an MHTML archive with the stdlib MIME parser; None when too big or unreadable."""
    if _too_big(source.path):
        logger.warning("mhtml too large, skipped: %s", source.path.name)
        return None
    try:
        raw = source.path.read_bytes()
    except OSError as exc:
        logger.warning("cannot read mhtml %s: %s", source.path.name, exc)
        return None
    # Archives that went through a text-mode copy end lines with CR CR LF, which the MIME
    # parser reads as a blank line right after the first header: the whole file then looks
    # like one text/plain body.
    raw = raw.replace(b"\r\r\n", b"\r\n")
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except (ValueError, TypeError) as exc:
        logger.warning("cannot parse mhtml %s: %s", source.path.name, exc)
        return None
    return msg if isinstance(msg, EmailMessage) else None


def _http_url(value: object) -> str:
    text = str(value or "").strip().strip("<>")
    return text if text.lower().startswith(("http://", "https://")) else ""


def mhtml_html(source: Artifact, out_dir: Path) -> list[Artifact]:
    """Decode the archived page (root `text/html` part) of an MHTML into `out_dir`.

    The root part is the one whose `Content-Location` equals the archive's
    `Snapshot-Content-Location`, else the first HTML part (iframes come later). The page URL
    (redacted) goes into `meta["url"]`/`meta["saved_from"]` like for a saved `.html` file.
    """
    msg = _read_mhtml(source)
    if msg is None:
        return []
    snapshot = _http_url(msg.get("Snapshot-Content-Location"))
    candidates: list[tuple[int, EmailMessage]] = [
        (index, part)
        for index, part in enumerate(msg.walk())
        if isinstance(part, EmailMessage)
        and part.get_content_type() == "text/html"
        and not part.is_multipart()
    ]
    if not candidates:
        return []
    index, root = next(
        (
            (i, p)
            for i, p in candidates
            if snapshot and _http_url(p.get("Content-Location")) == snapshot
        ),
        candidates[0],
    )
    try:
        text = root.get_content()
    except (LookupError, ValueError, TypeError, AssertionError):
        payload = root.get_payload(decode=True)
        text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""
    if not isinstance(text, str) or not text.strip():
        return []
    data = text.encode("utf-8", "replace")
    if len(data) > MAX_PART_BYTES:
        return []
    path = out_dir / f"{_sha16(data)}.html"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
    except OSError as exc:
        logger.warning("cannot cache mhtml page of %s: %s", source.path.name, exc)
        return []
    meta = {
        "locator": f"mhtml:part={index}",
        "source_kind": source.kind,
        "sha256": hashlib.sha256(data).hexdigest(),
        "rel": f"{source.meta.get('rel', source.path.name)}#part={index}",
    }
    if url := _http_url(root.get("Content-Location")) or snapshot:
        meta["url"] = meta["saved_from"] = redact_url(url)
    return [
        Artifact(
            id=_sha16(data),
            case_id=source.case_id,
            kind="html",
            role="landing_page",
            path=path,
            page=source.page,
            parent_id=source.id,
            size=len(data),
            meta=meta,
        )
    ]


def mhtml_images(source: Artifact, out_dir: Path) -> list[Artifact]:
    """Decode the image parts of an MHTML archive (>= 120 px on both sides) into `out_dir`."""
    msg = _read_mhtml(source)
    if msg is None:
        return []
    out: list[Artifact] = []
    seen: set[str] = set()
    for index, part in enumerate(msg.walk()):
        if len(out) >= MAX_MHTML_IMAGES:
            logger.warning("mhtml %s: more than %d images, rest skipped", source.path.name, index)
            break
        ctype = part.get_content_type()
        if ctype not in _IMAGE_EXT or part.is_multipart():
            continue
        try:
            data = part.get_payload(decode=True)
        except (ValueError, TypeError, LookupError):
            continue
        if not isinstance(data, bytes):
            continue
        cid = str(part.get("Content-ID", "") or "").strip().strip("<>")
        ref = cid if cid and len(cid) <= 80 and " " not in cid else str(index)
        image = _save_image(source, data, out_dir, f"mhtml:part={ref}", seen)
        if image is not None:
            out.append(image)
    return out


def _save_image(
    source: Artifact, data: bytes, out_dir: Path, locator: str, seen: set[str]
) -> Artifact | None:
    """Cache one embedded image (>= 120 px on both sides) as a derived landing asset."""
    if not data or len(data) > MAX_PART_BYTES:
        return None
    fmt = _image_format(data)
    if fmt is None or min(fmt[1]) < MIN_SIDE:
        return None
    sha = _sha16(data)
    if sha in seen:
        return None
    seen.add(sha)
    path = out_dir / f"{sha}{fmt[0]}"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
    except OSError as exc:
        logger.warning("cannot cache an image of %s: %s", source.path.name, exc)
        return None
    return _derived(source, path, data, locator, "landing_asset")


def _image_format(data: bytes) -> tuple[str, tuple[int, int]] | None:
    """(file suffix, pixel size) of an encoded raster image, or None when Pillow cannot read it."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as im:
            suffix = _PIL_EXT.get(str(im.format or "").upper())
            return (suffix, im.size) if suffix else None
    except (OSError, UnidentifiedImageError, ValueError):
        return None


_UNTYPED = {"", "application/octet-stream", "binary/octet-stream"}
_PIL_EXT = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp"}


def har_parts(source: Artifact, out_dir: Path) -> list[Artifact]:
    """The landing document and image bodies a HAR kept, as derived artifacts in `out_dir`.

    The document is the response for the HAR's landing URL (`meta["landing_url"]`, set at
    ingest) with an HTML body; it becomes a `landing_page` with that URL. Image bodies
    (>= 120 px) become landing assets. Locators are `har:entry[i]`. Nothing is executed.
    """
    from fakecollector.ingest.har import HarError, iter_responses

    if _too_big(source.path):
        logger.warning("har too large, skipped: %s", source.path.name)
        return []
    landing = source.meta.get("landing_url", "")
    out: list[Artifact] = []
    seen: set[str] = set()
    page_done = False
    try:
        for index, url, status, mime, body in iter_responses(source.path):
            locator = f"har:entry[{index}]"
            if (
                not page_done
                and landing
                and redact_url(url) == landing
                and 200 <= status < 300
                and ("html" in mime or body.lstrip()[:1] == b"<")
            ):
                page = _har_page(source, body, out_dir, locator, landing)
                if page is not None:
                    out.append(page)
                    page_done = True
                continue
            if len(seen) >= MAX_MHTML_IMAGES:
                continue
            if mime.startswith("image/") or mime in _UNTYPED:
                image = _save_image(source, body, out_dir, locator, seen)
                if image is not None:
                    out.append(image)
    except HarError as exc:
        logger.warning("cannot read har %s: %s", source.path.name, exc)
    return out


def _har_page(
    source: Artifact, body: bytes, out_dir: Path, locator: str, url: str
) -> Artifact | None:
    if not body.strip() or len(body) > MAX_PART_BYTES:
        return None
    path = out_dir / f"{_sha16(body)}.html"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(body)
    except OSError as exc:
        logger.warning("cannot cache the page of %s: %s", source.path.name, exc)
        return None
    return Artifact(
        id=_sha16(body),
        case_id=source.case_id,
        kind="html",
        role="landing_page",
        path=path,
        page=source.page,
        parent_id=source.id,
        size=len(body),
        meta={
            "locator": locator,
            "source_kind": source.kind,
            "sha256": hashlib.sha256(body).hexdigest(),
            "rel": f"{source.meta.get('rel', source.path.name)}#{locator}",
            "url": url,
            "saved_from": url,
        },
    )


def pdf_pages(
    source: Artifact, out_dir: Path, max_pages: int = MAX_PDF_PAGES, dpi: int = PDF_DPI
) -> list[Artifact]:
    """Render the first `max_pages` pages of a PDF to PNG in `out_dir` (PDFium, no scripts)."""
    if _too_big(source.path):
        logger.warning("pdf too large, skipped: %s", source.path.name)
        return []
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.warning("pypdfium2 not installed; pdf %s skipped", source.path.name)
        return []
    out: list[Artifact] = []
    try:
        pdf = pdfium.PdfDocument(source.path)
    except (pdfium.PdfiumError, OSError, ValueError) as exc:
        logger.warning("cannot open pdf %s: %s", source.path.name, exc)
        return []
    try:
        for i in range(min(len(pdf), max_pages)):
            try:
                page = pdf[i]
                width, height = page.get_size()
                scale = dpi / 72
                if max(width, height) * scale > MAX_PAGE_SIDE:
                    scale = MAX_PAGE_SIDE / max(width, height)
                image = page.render(scale=scale).to_pil()
                page.close()
                buf = io.BytesIO()
                image.convert("RGB").save(buf, format="PNG")
            except (pdfium.PdfiumError, OSError, ValueError, MemoryError) as exc:
                logger.warning("pdf %s page %d failed: %s", source.path.name, i + 1, exc)
                continue
            data = buf.getvalue()
            if min(image.size) < MIN_SIDE:
                continue
            path = out_dir / f"page{i + 1}_{_sha16(data)}.png"
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_bytes(data)
            except OSError as exc:
                logger.warning("cannot cache pdf page of %s: %s", source.path.name, exc)
                continue
            out.append(_derived(source, path, data, f"pdf:page={i + 1}", "screenshot"))
    finally:
        pdf.close()
    return out


def expand_derived(
    artifacts: Sequence[Artifact],
    media: DerivedMediaExtractor,
    kinds: Collection[str] | None = None,
    source_kinds: Collection[str] | None = None,
) -> list[Artifact]:
    """New derived artifacts to add to a run, deduplicated by content within a case.

    Sources: video, MHTML and PDF (`media.derive`) and HAR bodies (`media.derive_har`).
    `kinds` keeps only derived artifacts of those kinds, `source_kinds` derives only from
    sources of those kinds (both default to all).

    A derived page (MHTML part, HAR document) is only added when its capture has no saved
    landing page of its own, and HAR images only when it has no saved page assets: parsing
    both would count the same page twice.
    """
    known = {(a.case_id, a.id) for a in artifacts}
    pages = {(a.case_id, a.page) for a in artifacts if a.role == "landing_page"}
    assets = {(a.case_id, a.page) for a in artifacts if a.role == "landing_asset"}
    out: list[Artifact] = []
    for artifact in artifacts:
        if source_kinds is not None and artifact.kind not in source_kinds:
            continue
        if media.supports(artifact):
            items = media.derive(artifact)
        elif artifact.kind == "har":
            items = media.derive_har(artifact)
        else:
            continue
        for item in items:
            if kinds is not None and item.kind not in kinds:
                continue
            slot = (item.case_id, item.page)
            if item.role == "landing_page" and slot in pages:
                continue
            if artifact.kind == "har" and item.role == "landing_asset" and slot in assets:
                continue
            if (item.case_id, item.id) not in known:
                out.append(item)
                known.add((item.case_id, item.id))
                if item.role == "landing_page":
                    pages.add(slot)
    return out


def _load_vision_extractors() -> list[BaseExtractor]:
    out: list[BaseExtractor] = []
    for module_name, cls_name in VISION_EXTRACTORS:
        try:
            out.append(getattr(import_module(module_name), cls_name)())
        except Exception as exc:  # an optional model extractor may be unavailable
            logger.warning("derived media: %s unavailable (%s)", cls_name, exc)
    return out


class DerivedMediaExtractor(BaseExtractor):
    """Image features (and ASR) for video, MHTML and PDF artifacts, attributed to the source."""

    name = "derived_media"
    version = 1
    stage = 1
    requires: Literal["base", "ml"] = "ml"

    def __init__(
        self,
        cache_dir: Path | None = None,
        extractors: Sequence[BaseExtractor] | None = None,
        max_frames: int = 40,
        max_pdf_pages: int = MAX_PDF_PAGES,
        pdf_dpi: int = PDF_DPI,
        asr: bool | None = None,
    ) -> None:
        """`extractors` defaults to the vision extractors that import on this install.

        `asr=None` follows `FAKECOLLECTOR_ASR` (default on, see `video.asr_enabled`).
        """
        from fakecollector.extractors.video import _cache_root

        self.cache_dir = cache_dir or _cache_root()
        self._extractors = list(extractors) if extractors is not None else None
        self.max_frames = max_frames
        self.max_pdf_pages = max_pdf_pages
        self.pdf_dpi = pdf_dpi
        self.asr = asr
        self._memo: dict[str, list[Feature]] = {}

    @property
    def extractors(self) -> list[BaseExtractor]:
        """Vision extractors applied to derived images (loaded on first use)."""
        if self._extractors is None:
            self._extractors = _load_vision_extractors()
        return self._extractors

    def supports(self, artifact: Artifact) -> bool:
        """Videos, MHTML archives and PDF captures."""
        return artifact.kind in {"video", "mhtml", "pdf"}

    def derive(self, artifact: Artifact) -> list[Artifact]:
        """Derived artifacts (images; the page of an MHTML), cached on disk; never raises."""
        try:
            if artifact.kind == "video":
                from fakecollector.extractors.video import VideoExtractor

                video = VideoExtractor(cache_dir=self.cache_dir, max_frames=self.max_frames)
                return video.keyframe_artifacts(artifact)
            if artifact.kind == "mhtml":
                out_dir = self.cache_dir / "mhtml" / artifact.id
                return mhtml_images(artifact, out_dir) + mhtml_html(artifact, out_dir)
            if artifact.kind == "pdf":
                out_dir = self.cache_dir / "pdf" / artifact.id / f"dpi{self.pdf_dpi}"
                return pdf_pages(artifact, out_dir, self.max_pdf_pages, self.pdf_dpi)
        except Exception:  # one broken container must not stop the run
            logger.warning("deriving images from %s failed", artifact.path.name, exc_info=True)
        return []

    def derive_har(self, artifact: Artifact) -> list[Artifact]:
        """The landing document and images a HAR kept (cached on disk); never raises."""
        try:
            return har_parts(artifact, self.cache_dir / "har" / artifact.id)
        except Exception:  # one broken capture must not stop the run
            logger.warning("deriving from %s failed", artifact.path.name, exc_info=True)
            return []

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Features of every derived image plus ASR, attributed to `artifact`."""
        return self.extract_batch([artifact], [prior])[0]

    def extract_batch(
        self, artifacts: list[Artifact], priors: list[list[Feature]]
    ) -> list[list[Feature]]:
        """Derive images for all sources, run each vision extractor over them in batches."""
        results: list[list[Feature]] = [[] for _ in artifacts]
        todo: dict[str, Artifact] = {}
        for art in artifacts:
            if self.supports(art) and art.id not in self._memo:
                todo.setdefault(art.id, art)
        if todo:
            self._compute(list(todo.values()))
        for i, art in enumerate(artifacts):
            if self.supports(art):
                results[i] = [
                    f.model_copy(update={"case_id": art.case_id})
                    for f in self._memo.get(art.id, [])
                ]
        return results

    def _compute(self, sources: list[Artifact]) -> None:
        derived: list[Artifact] = []
        for src in sources:
            self._memo[src.id] = []
            derived += self.derive(src)
        by_id = {s.id: s for s in sources}
        if derived:
            for ext in self.extractors:
                self._run_vision(ext, derived, by_id)
        for src in sources:
            if src.kind == "video":
                self._memo[src.id] += self._asr(src)

    def _run_vision(
        self, ext: BaseExtractor, derived: list[Artifact], sources: dict[str, Artifact]
    ) -> None:
        try:
            todo = [d for d in derived if ext.supports(d)]
        except Exception:
            logger.warning("%s.supports failed on derived media", ext.name, exc_info=True)
            return
        for start in range(0, len(todo), BATCH):
            chunk = todo[start : start + BATCH]
            try:
                feats = ext.extract_batch(chunk, [[] for _ in chunk])
            except Exception:  # a model failure degrades to "no vision", never a crash
                logger.warning("%s failed on derived media", ext.name, exc_info=True)
                continue
            for img, img_feats in zip(chunk, feats, strict=True):
                src = sources[img.parent_id or ""]
                prefix = img.meta.get("locator", "")
                self._memo[src.id] += [
                    f.model_copy(
                        update={
                            "case_id": src.case_id,
                            "artifact_id": src.id,
                            "locator": combine_locator(prefix, f.locator),
                        }
                    )
                    for f in img_feats
                ]

    def _asr(self, video: Artifact) -> list[Feature]:
        from fakecollector.extractors.video import asr_enabled, transcribe

        if not (asr_enabled() if self.asr is None else self.asr):
            return []
        try:
            text = normalize_text(transcribe(video.path))
        except ImportError:
            logger.warning("faster-whisper not installed; ASR skipped")
            return []
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            logger.warning("ASR failed for %s: %s", video.path.name, exc)
            return []
        if len(text) < 3:
            return []
        return [
            Feature(
                case_id=video.case_id,
                artifact_id=video.id,
                name="text.asr",
                value=text,
                locator="audio",
            )
        ]
