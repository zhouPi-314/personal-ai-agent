"""音频转码：只做一件事，把任意输入转成 16k 单声道 WAV。

ffmpeg 一律参数数组调用，禁止拼接 shell 字符串（防命令注入）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

TARGET_RATE = 16000
DEFAULT_MAX_SECONDS = 120


class AudioError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code + ((": " + detail) if detail else ""))
        self.code = code
        self.detail = detail


def to_wav16k(
    source: Path,
    *,
    ffmpeg: Path,
    out_dir: Path,
    max_seconds: int = DEFAULT_MAX_SECONDS,
    timeout: float = 60.0,
) -> Path:
    """把 source 转成 16k/单声道 WAV，返回新文件路径。"""
    if not ffmpeg.is_file():
        raise AudioError("E_FFMPEG_MISSING", str(ffmpeg))
    if not source.is_file():
        raise AudioError("E_NOT_FOUND", str(source))

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (source.stem + "_16k.wav")
    argv = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-t",
        str(max(1, int(max_seconds))),
        "-ar",
        str(TARGET_RATE),
        "-ac",
        "1",
        "-f",
        "wav",
        str(target),
    ]
    try:
        completed = subprocess.run(
            argv, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioError("E_TIMEOUT", "ffmpeg 超时") from exc
    except OSError as exc:
        raise AudioError("E_FFMPEG_MISSING", str(exc)) from exc

    if completed.returncode != 0 or not target.is_file():
        detail = completed.stderr.decode("utf-8", errors="replace")[-200:]
        raise AudioError("E_DECODE_FAILED", detail)
    return target
