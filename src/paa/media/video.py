"""视频处理：抽关键帧 + 抽音轨，交给视觉与语音链路复用。

全部用项目自带 ffmpeg（参数数组调用），不引入新依赖。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .contracts import MediaRef
from .fetcher import fetch

MAX_FRAMES = 3
MAX_VIDEO_BYTES = 30 * 1024 * 1024


class VideoError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code + ((": " + detail) if detail else ""))
        self.code = code


@dataclass(frozen=True)
class VideoAssets:
    local_path: Path
    frames: tuple[Path, ...]
    audio: Path | None
    seconds: float


def _run(argv: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, timeout=timeout, check=False)


def _duration(ffprobe: Path, path: Path) -> float:
    if not ffprobe.is_file():
        return 0.0
    done = _run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        timeout=30.0,
    )
    try:
        return float(done.stdout.decode().strip() or 0)
    except ValueError:
        return 0.0


def extract(
    ref: MediaRef,
    *,
    ffmpeg: Path,
    out_dir: Path,
    frames: int = MAX_FRAMES,
    max_seconds: int = 120,
) -> VideoAssets:
    """下载视频 → 抽 N 帧 PNG + 抽 16k 单声道 WAV。"""
    if not ffmpeg.is_file():
        raise VideoError("E_FFMPEG_MISSING", str(ffmpeg))

    out_dir.mkdir(parents=True, exist_ok=True)
    item = fetch(ref, out_dir=out_dir, max_bytes=MAX_VIDEO_BYTES, allow_video=True)
    token = item.sha256[:8]
    ffprobe = ffmpeg.with_name("ffprobe.exe")

    seconds = _duration(ffprobe, item.local_path)

    pattern = out_dir / (token + "_%02d.png")
    frame_done = _run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(item.local_path),
        "-t", str(max_seconds),
        "-vf", "fps=1",
        "-frames:v", str(max(1, min(frames, MAX_FRAMES))),
        str(pattern),
    ])
    produced = tuple(sorted(out_dir.glob(token + "_*.png"))[:frames])
    if frame_done.returncode != 0 or not produced:
        raise VideoError("E_FRAME_FAILED", frame_done.stderr.decode("utf-8", "replace")[-160:])

    audio_path = out_dir / (token + "_audio.wav")
    audio_done = _run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(item.local_path),
        "-t", str(max_seconds),
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        str(audio_path),
    ])
    audio = audio_path if audio_done.returncode == 0 and audio_path.is_file() else None

    return VideoAssets(
        local_path=item.local_path,
        frames=produced,
        audio=audio,
        seconds=round(seconds, 1),
    )
