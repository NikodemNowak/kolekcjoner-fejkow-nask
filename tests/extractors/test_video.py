import shutil
import subprocess
from pathlib import Path

import pytest

from fakecollector.core.schemas import Artifact
from fakecollector.extractors.video import VideoExtractor, keyframes

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")


def _two_scene_clip(path: Path) -> Path:
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2.5:r=25",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2.5:r=25",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
        "-pix_fmt", "yuv420p", str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return path


def test_two_scene_clip_gives_keyframes(tmp_path: Path) -> None:
    frames = keyframes(_two_scene_clip(tmp_path / "clip.mp4"))
    assert len(frames) >= 2
    times = [t for t, _ in frames]
    assert times == sorted(times)
    assert all(img.ndim == 3 and max(img.shape[:2]) <= 960 for _, img in frames)
    reds = [img[..., 0].mean() > img[..., 2].mean() for _, img in frames]
    assert any(reds) and not all(reds)


def test_hls_folder_with_renamed_segments(tmp_path: Path) -> None:
    clip = _two_scene_clip(tmp_path / "clip.mp4")
    hls = tmp_path / "hls"
    hls.mkdir()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(clip), "-c", "copy", "-f", "hls",
         "-hls_time", "2", "-hls_list_size", "0", str(hls / "out.m3u8")],
        check=True,
    )  # fmt: skip
    for ts in hls.glob("*.ts"):
        ts.rename(ts.with_name(f"{ts.stem}_abcd1234.ts"))
    assert len(keyframes(hls / "out.m3u8")) >= 2
    assert len(keyframes(hls)) >= 2


def test_keyframe_artifacts_are_cached(tmp_path: Path) -> None:
    clip = _two_scene_clip(tmp_path / "clip.mp4")
    video = Artifact(id="v" * 16, case_id="T:1", kind="video", role="ad_video", path=clip, size=1)
    ex = VideoExtractor(cache_dir=tmp_path / "cache")
    arts = ex.keyframe_artifacts(video)
    assert len(arts) >= 2
    assert all(a.kind == "image" and a.parent_id == video.id for a in arts)
    assert arts[0].path.parent == tmp_path / "cache" / "keyframes" / video.id
    assert arts[0].path.name.startswith("t=")
    assert [a.id for a in ex.keyframe_artifacts(video)] == [a.id for a in arts]


def test_broken_video_gives_nothing(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    video = Artifact(id="b" * 16, case_id="T:1", kind="video", role="ad_video", path=bad, size=1)
    assert VideoExtractor(cache_dir=tmp_path / "c").keyframe_artifacts(video) == []


def test_silent_clip_has_no_transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKECOLLECTOR_ASR", "1")
    clip = _two_scene_clip(tmp_path / "clip.mp4")  # no audio stream at all
    video = Artifact(id="s" * 16, case_id="T:1", kind="video", role="ad_video", path=clip, size=1)
    assert VideoExtractor(cache_dir=tmp_path / "c").extract(video, []) == []


class _FakeWhisper:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def transcribe(self, audio: object, **kwargs: object) -> tuple[list[object], None]:
        self.kwargs = kwargs
        return [], None


def test_transcribe_decodes_deterministically(monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np

    from fakecollector.extractors import video as video_mod

    fake = _FakeWhisper()
    monkeypatch.setattr(video_mod, "_audio", lambda path: np.zeros(32000, dtype=np.float32))
    monkeypatch.setattr(video_mod, "_whisper", lambda: fake)
    video_mod.transcribe(Path("clip.mp4"))
    # The default temperature schedule falls back to sampling: two runs then differ.
    assert fake.kwargs["temperature"] == 0.0
    assert fake.kwargs["beam_size"] == video_mod.ASR_BEAM_SIZE
    assert fake.kwargs["condition_on_previous_text"] is False


@pytest.mark.parametrize(
    ("value", "expected"), [(None, True), ("0", False), ("off", False), ("1", True)]
)
def test_asr_setting_does_not_depend_on_gpu(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    from fakecollector.extractors import video as video_mod

    if value is None:
        monkeypatch.delenv("FAKECOLLECTOR_ASR", raising=False)
    else:
        monkeypatch.setenv("FAKECOLLECTOR_ASR", value)
    monkeypatch.setattr("fakecollector.models.device", lambda: "cpu")
    assert video_mod.asr_enabled() is expected
