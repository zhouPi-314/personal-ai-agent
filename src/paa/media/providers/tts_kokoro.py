"""Kokoro TTS Provider：把中文文本交给侧车合成 24k WAV。

与 ASR 一样是"一次性侧车"：主进程不装 onnxruntime / misaki，也不加载模型。
"""

from __future__ import annotations

from pathlib import Path

from ..contracts import Capability, MediaResult, ResultStatus
from ..worker_client import WorkerError, call_worker

DEFAULT_MAX_CHARS = 120
MIN_WAV_BYTES = 4096


class KokoroTTSProvider:
    name = "kokoro"

    def __init__(
        self,
        *,
        python_exe: Path,
        worker_script: Path,
        model_dir: Path,
        voice: str = "zf_001",
        speed: float = 1.0,
        model_file: str = "model_int8.onnx",
        max_chars: int = DEFAULT_MAX_CHARS,
        timeout: float = 180.0,
    ) -> None:
        self.python_exe = python_exe
        self.worker_script = worker_script
        self.model_dir = model_dir
        self.voice = voice
        self.speed = speed
        self.model_file = model_file
        self.max_chars = max_chars
        self.timeout = timeout

    def available(self) -> bool:
        if not (self.python_exe.is_file() and self.worker_script.is_file()):
            return False
        if not (self.model_dir / self.model_file).is_file():
            return False
        if not (self.model_dir / "tokenizer.json").is_file():
            return False
        return (self.model_dir / f"{self.voice}.bin").is_file() or (
            self.model_dir / "voices" / f"{self.voice}.bin"
        ).is_file()

    def synthesize_speech(
        self,
        text: str,
        *,
        out_dir: Path,
        voice_id: str = "",
        max_chars: int | None = None,
        deadline_ms: int = 180_000,
    ) -> MediaResult:
        if not self.available():
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_MODEL_UNAVAILABLE",
                error_detail="Kokoro 侧车组件不齐",
            )

        limit = max(1, int(max_chars or self.max_chars))
        content = (text or "").strip()
        if not content:
            return MediaResult(
                status=ResultStatus.REJECTED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_EMPTY_TEXT",
            )
        truncated = len(content) > limit
        if truncated:
            content = content[:limit]

        out_dir.mkdir(parents=True, exist_ok=True)
        out_wav = out_dir / ("tts_" + str(abs(hash(content)) % 10**10) + ".wav")
        timeout = max(20.0, min(self.timeout, deadline_ms / 1000))

        try:
            data = call_worker(
                python_exe=self.python_exe,
                script=self.worker_script,
                payload={
                    "text": content,
                    "model_dir": str(self.model_dir),
                    "out_wav": str(out_wav),
                    "voice": voice_id or self.voice,
                    "speed": self.speed,
                    "model_file": self.model_file,
                    "threads": 8,
                },
                timeout=timeout,
            )
        except WorkerError as exc:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code=exc.code,
                error_detail=exc.detail,
            )

        if not out_wav.is_file() or out_wav.stat().st_size < MIN_WAV_BYTES:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_TOO_SMALL",
            )

        return MediaResult(
            status=ResultStatus.OK,
            capability=Capability.SYNTHESIZE_SPEECH,
            text=content,
            data={
                "path": str(out_wav),
                "bytes": out_wav.stat().st_size,
                "seconds": data.get("seconds"),
                "tts_ms": data.get("tts_ms"),
                "truncated": truncated,
            },
            limitations=(("文本超过 " + str(limit) + " 字，已截断",) if truncated else ()),
        )
