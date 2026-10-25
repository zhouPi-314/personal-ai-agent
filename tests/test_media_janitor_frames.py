"""媒体清理与动图抽帧。"""

import os
import time
from pathlib import Path

from paa.media import janitor
from paa.media.contracts import MediaRef
from paa.media.frames import FrameError, extract_frames

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _touch(path: Path, age_seconds: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


def test_janitor_removes_only_expired(tmp_path: Path):
    media = tmp_path / "media"
    old_tmp = _touch(media / "tmp" / "old.wav", 7 * 3600)
    fresh_tmp = _touch(media / "tmp" / "fresh.wav", 60)
    old_music = _touch(media / "music" / "old.mp3", 25 * 3600)
    fresh_music = _touch(media / "music" / "fresh.mp3", 3600)

    report = janitor.sweep(media)

    assert not old_tmp.exists()
    assert fresh_tmp.exists()
    assert not old_music.exists()
    assert fresh_music.exists()
    assert report.removed == 2


def test_janitor_skips_recently_written(tmp_path: Path):
    media = tmp_path / "media"
    just_now = _touch(media / "tmp" / "x.wav", 5)
    report = janitor.sweep(media)
    assert just_now.exists() and report.removed == 0


def test_janitor_missing_dir_is_noop(tmp_path: Path):
    report = janitor.sweep(tmp_path / "nope")
    assert report.scanned == 0 and report.removed == 0


def test_extract_frames_requires_ffmpeg(tmp_path: Path):
    ref = MediaRef("image", "file", str(_touch(tmp_path / "a.gif", 1)))
    try:
        extract_frames(ref, ffmpeg=tmp_path / "missing.exe", out_dir=tmp_path / "o")
        raise AssertionError("应当抛错")
    except FrameError as err:
        assert err.code == "E_FFMPEG_MISSING"


def test_extract_frames_returns_png_refs(tmp_path: Path, monkeypatch):
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a" + b"0" * 32)
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"bin")
    out_dir = tmp_path / "out"

    class _Done:
        returncode = 0
        stderr = b""

    def fake_run(argv, **kwargs):
        prefix = Path(argv[-1]).name.split("_")[0]
        for i in (1, 2):
            (out_dir / f"{prefix}_{i:02d}.png").write_bytes(PNG)
        return _Done()

    monkeypatch.setattr("paa.media.frames.subprocess.run", fake_run)
    frames = extract_frames(ref=MediaRef("image", "file", str(gif)), ffmpeg=ffmpeg, out_dir=out_dir, count=2)

    assert len(frames) == 2
    assert all(frame.kind == "image" and Path(frame.locator).is_file() for frame in frames)
