"""AC-Step 音乐生成 Provider：把提示词交给侧车，拿回一段 MP3。

侧车一次性运行（加载模型 11s + 生成 8s），主进程不依赖 torch。
"""

from __future__ import annotations

from pathlib import Path

from ..contracts import Capability, MediaResult, ResultStatus
from ..worker_client import WorkerError, call_worker

DEFAULT_SECONDS = 30
MIN_BYTES = 8192


class MusicSidecarProvider:
    name = "acestep"

    def __init__(
        self,
        *,
        python_exe: Path,
        worker_script: Path,
        project_root: Path,
        checkpoints_dir: Path,
        ffmpeg: Path,
        seconds: int = DEFAULT_SECONDS,
        quantization: str = "int8_weight_only",
        timeout: float = 600.0,
    ) -> None:
        self.python_exe = python_exe
        self.worker_script = worker_script
        self.project_root = project_root
        self.checkpoints_dir = checkpoints_dir
        self.ffmpeg = ffmpeg
        self.seconds = seconds
        self.quantization = quantization
        self.timeout = timeout

    def available(self) -> bool:
        return all(
            [
                self.python_exe.is_file(),
                self.worker_script.is_file(),
                (self.project_root / "acestep" / "handler.py").is_file(),
                (self.checkpoints_dir / "acestep-v15-turbo" / "model.safetensors").is_file(),
                self.ffmpeg.is_file(),
            ]
        )

    def generate_music(
        self,
        prompt: str,
        *,
        out_dir: Path,
        lyrics: str = "",
        seconds: int | None = None,
        deadline_ms: int = 600_000,
    ) -> MediaResult:
        if not self.available():
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.GENERATE_MUSIC,
                error_code="E_MODEL_UNAVAILABLE",
                error_detail="ACE-Step 环境或权重不齐",
            )

        text = (prompt or "").strip()
        if not text:
            return MediaResult(
                status=ResultStatus.REJECTED,
                capability=Capability.GENERATE_MUSIC,
                error_code="E_EMPTY_PROMPT",
            )

        out_dir.mkdir(parents=True, exist_ok=True)
        timeout = max(60.0, min(self.timeout, deadline_ms / 1000))
        try:
            data = call_worker(
                python_exe=self.python_exe,
                script=self.worker_script,
                payload={
                    "prompt": text[:300],
                    "lyrics": lyrics[:1200],
                    "seconds": int(seconds or self.seconds),
                    "out_dir": str(out_dir),
                    "project_root": str(self.project_root),
                    "quantization": self.quantization,
                    "ffmpeg": str(self.ffmpeg),
                },
                timeout=timeout,
            )
        except WorkerError as exc:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.GENERATE_MUSIC,
                error_code=exc.code,
                error_detail=exc.detail,
            )

        path = Path(str(data.get("mp3") or data.get("wav") or ""))
        if not path.is_file() or path.stat().st_size < MIN_BYTES:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.GENERATE_MUSIC,
                error_code="E_TOO_SMALL",
            )

        return MediaResult(
            status=ResultStatus.OK,
            capability=Capability.GENERATE_MUSIC,
            text=text,
            data={
                "path": str(path),
                "bytes": path.stat().st_size,
                "init_s": data.get("init_s"),
                "gen_s": data.get("gen_s"),
                "seconds": data.get("seconds"),
            },
        )
