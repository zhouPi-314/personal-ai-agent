"""动图抽帧：只抽有限几帧，不把整段动画丢给视觉模型。

用项目自带的 ffmpeg（参数数组调用，禁 shell），不需要额外依赖。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .contracts import MediaRef
from .fetcher import fetch

MAX_FRAMES = 3
MAX_BYTES = 8 * 1024 * 1024


class FrameError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code + ((": " + detail) if detail else ""))
        self.code = code


def extract_frames(
    ref: MediaRef,
    *,
    ffmpeg: Path,
    out_dir: Path,
    count: int = MAX_FRAMES,
    timeout: float = 30.0,
) -> list[MediaRef]:
    """把动图抽成若干 PNG，返回指向这些文件的 MediaRef 列表。"""
    if not ffmpeg.is_file():
        raise FrameError("E_FFMPEG_MISSING", str(ffmpeg))

    out_dir.mkdir(parents=True, exist_ok=True)
    item = fetch(ref, out_dir=out_dir, max_bytes=MAX_BYTES)
    pattern = out_dir / (item.sha256[:8] + "_%02d.png")

    argv = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(item.local_path),
        "-vf",
        "fps=1",
        "-frames:v",
        str(max(1, min(count, MAX_FRAMES))),
        str(pattern),
    ]
    completed = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    produced = sorted(out_dir.glob(item.sha256[:8] + "_*.png"))
    if completed.returncode != 0 or not produced:
        raise FrameError(
            "E_DECODE_FAILED",
            completed.stderr.decode("utf-8", errors="replace")[-160:] or "没有抽到帧",
        )

    return [
        MediaRef(kind="image", source="file", locator=str(path), name=path.name)
        for path in produced[:count]
    ]
