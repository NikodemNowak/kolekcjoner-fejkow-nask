"""DerivedMediaExtractor: video / MHTML / PDF -> image features on the source (no models)."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest
from PIL import Image

from fakecollector.config import get_settings
from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors import video as video_mod
from fakecollector.extractors.derived import DerivedMediaExtractor, combine_locator


class FakeVision(BaseExtractor):
    """Stands in for the vision extractors: one face-like and one OCR-like feature per image."""

    name = "fake_vision"

    def __init__(self) -> None:
        self.seen: list[Artifact] = []

    def supports(self, artifact: Artifact) -> bool:
        return artifact.kind == "image"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        self.seen.append(artifact)
        return [
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="person.public_figure",
                value="someone",
                locator="bbox=1,2,3,4",
            ),
            Feature(
                case_id=artifact.case_id,
                artifact_id=artifact.id,
                name="text.ocr",
                value="tekst",
                locator=artifact.meta.get("locator", ""),
            ),
        ]


class Exploding(FakeVision):
    name = "exploding"

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        raise RuntimeError("model crashed")


def _png(color: str, side: int = 200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (side, side), color).save(buf, format="PNG")
    return buf.getvalue()


def _source(path: Path, kind: str, case: str = "T:1") -> Artifact:
    data = path.read_bytes() if path.is_file() else b""
    return Artifact(
        id=hashlib.sha256(data + kind.encode()).hexdigest()[:16],
        case_id=case,
        kind=kind,  # type: ignore[arg-type]
        role="other",
        path=path,
        size=len(data),
    )


def _extractor(tmp_path: Path, *fakes: BaseExtractor) -> DerivedMediaExtractor:
    return DerivedMediaExtractor(
        cache_dir=tmp_path / "cache", extractors=list(fakes) or [FakeVision()], asr=False
    )


def test_combine_locator() -> None:
    assert combine_locator("t=12.0s", "bbox=1,2,3,4") == "t=12.0s bbox=1,2,3,4"
    assert combine_locator("t=12.0s", "") == "t=12.0s"
    assert combine_locator("t=12.0s", "t=12.0s") == "t=12.0s"


def test_video_keyframe_features_point_at_the_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _source(tmp_path / "ad.mp4", "video")

    def fake_keyframes(self: video_mod.VideoExtractor, src: Artifact) -> list[Artifact]:
        out = []
        for t, color in (("0.0", "red"), ("12.0", "blue")):
            path = tmp_path / f"t{t}.png"
            path.write_bytes(_png(color))
            out.append(
                Artifact(
                    id=f"kf{t}",
                    case_id=src.case_id,
                    kind="image",
                    role="screenshot",
                    path=path,
                    parent_id=src.id,
                    size=1,
                    meta={"locator": f"t={t}s"},
                )
            )
        return out

    monkeypatch.setattr(video_mod.VideoExtractor, "keyframe_artifacts", fake_keyframes)
    feats = _extractor(tmp_path).extract(video, [])
    assert {f.artifact_id for f in feats} == {video.id}
    assert {f.case_id for f in feats} == {"T:1"}
    locators = {f.locator for f in feats}
    assert "t=12.0s bbox=1,2,3,4" in locators
    assert "t=0.0s" in locators


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
def test_real_video_is_decoded(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=3:r=25",
        "-pix_fmt", "yuv420p", str(clip),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    feats = _extractor(tmp_path).extract(_source(clip, "video"), [])
    assert feats
    assert all(f.locator.startswith("t=") for f in feats)


def _mhtml(path: Path) -> Path:
    msg = MIMEMultipart("related")
    msg.attach(MIMEText("<html><body><img src='a.png'></body></html>", "html"))
    for i, color in enumerate(("red", "green")):
        part = MIMEImage(_png(color), "png")
        part["Content-Location"] = f"https://example.invalid/{i}.png"
        msg.attach(part)
    msg.attach(MIMEImage(_png("blue", side=16), "png"))  # an icon: below 120 px
    path.write_bytes(msg.as_bytes())
    return path


def test_mhtml_embedded_images(tmp_path: Path) -> None:
    fake = FakeVision()
    src = _source(_mhtml(tmp_path / "page.mhtml"), "mhtml")
    feats = _extractor(tmp_path, fake).extract(src, [])
    assert len(fake.seen) == 2
    assert {f.artifact_id for f in feats} == {src.id}
    parts = {f.locator.split(" ")[0] for f in feats}
    assert len(parts) == 2
    assert all(p.startswith("mhtml:part=") for p in parts)
    assert all(a.path.is_relative_to(tmp_path / "cache") for a in fake.seen)


def _minimal_pdf(path: Path) -> Path:
    """A one-page 300x300 pt PDF with a filled rectangle, written by hand."""
    stream = b"0 0 1 rg 50 50 200 200 re f"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    path.write_bytes(bytes(out))
    return path


def test_pdf_page_features(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    fake = FakeVision()
    src = _source(_minimal_pdf(tmp_path / "page.pdf"), "pdf")
    feats = _extractor(tmp_path, fake).extract(src, [])
    assert len(fake.seen) == 1
    assert {f.artifact_id for f in feats} == {src.id}
    assert "pdf:page=1 bbox=1,2,3,4" in {f.locator for f in feats}
    with Image.open(fake.seen[0].path) as im:
        assert im.size == (625, 625)  # 300 pt at 150 dpi


@pytest.mark.parametrize(
    ("name", "kind"), [("x.mhtml", "mhtml"), ("x.pdf", "pdf"), ("x.mp4", "video")]
)
def test_corrupt_inputs_give_nothing(tmp_path: Path, name: str, kind: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"\x00garbage" * 100)
    assert _extractor(tmp_path).extract(_source(path, kind), []) == []


def test_oversize_inputs_are_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_artifact_mb", 0)
    fake = FakeVision()
    src = _source(_mhtml(tmp_path / "page.mhtml"), "mhtml")
    assert _extractor(tmp_path, fake).extract(src, []) == []
    assert fake.seen == []


def test_failing_vision_extractor_does_not_crash(tmp_path: Path) -> None:
    src = _source(_mhtml(tmp_path / "page.mhtml"), "mhtml")
    feats = _extractor(tmp_path, Exploding(), FakeVision()).extract(src, [])
    assert len(feats) == 4  # the healthy extractor still contributes


def test_shared_source_is_computed_once_and_rehomed(tmp_path: Path) -> None:
    fake = FakeVision()
    ext = _extractor(tmp_path, fake)
    src = _source(_mhtml(tmp_path / "page.mhtml"), "mhtml")
    other = src.model_copy(update={"case_id": "T:2"})
    first, second = ext.extract_batch([src, other], [[], []])
    assert len(fake.seen) == 2
    assert {f.case_id for f in second} == {"T:2"}
    assert len(first) == len(second)


def test_eval_discovery_uses_derived_not_video() -> None:
    from fakecollector.evaluation.runner import _discover_extractors

    names = {e.name for e in _discover_extractors()}
    assert "derived_media" in names
    assert "ad_library" in names
    assert "video" not in names


def _mhtml_page(path: Path, *, crcrlf: bool = False) -> Path:
    """A Blink-style archive: root page, an iframe page and one image (synthetic)."""
    msg = MIMEMultipart("related", type="text/html")
    msg["Snapshot-Content-Location"] = "https://landing.example.invalid/offer?token=secret"
    frame = MIMEText("<html><title>frame</title></html>", "html")
    frame["Content-Location"] = "https://ads.example.invalid/frame"
    root = MIMEText("<html><title>Synthetic offer</title><body>Buy now</body></html>", "html")
    root["Content-Location"] = "https://landing.example.invalid/offer?token=secret"
    msg.attach(frame)
    msg.attach(root)
    msg.attach(MIMEImage(_png("red"), "png"))
    data = msg.as_bytes().replace(b"\n", b"\r\n")
    path.write_bytes(data.replace(b"\r\n", b"\r\r\n") if crcrlf else data)
    return path


@pytest.mark.parametrize("crcrlf", [False, True])
def test_mhtml_page_becomes_landing_page_html(tmp_path: Path, crcrlf: bool) -> None:
    src = _source(_mhtml_page(tmp_path / "page.mhtml", crcrlf=crcrlf), "mhtml")
    derived = _extractor(tmp_path).derive(src)
    pages = [a for a in derived if a.kind == "html"]
    assert [a.kind for a in derived].count("image") == 1
    assert len(pages) == 1
    page = pages[0]
    assert page.role == "landing_page"
    assert page.parent_id == src.id
    assert page.meta["locator"].startswith("mhtml:part=")
    assert page.meta["url"].startswith("https://landing.example.invalid/offer")
    assert "secret" not in page.meta["url"]
    assert "Synthetic offer" in page.path.read_text(encoding="utf-8")
    assert page.path.is_relative_to(tmp_path / "cache")


def test_expand_derived_adds_mhtml_page_only_without_saved_html(tmp_path: Path) -> None:
    from fakecollector.extractors.derived import expand_derived

    src = _source(_mhtml_page(tmp_path / "page.mhtml"), "mhtml")
    ext = _extractor(tmp_path)
    added = expand_derived([src], ext, kinds={"html"}, source_kinds={"mhtml"})
    assert [a.kind for a in added] == ["html"]
    saved = src.model_copy(update={"id": "f" * 16, "kind": "html", "role": "landing_page"})
    assert expand_derived([src, saved], ext, kinds={"html"}) == []
