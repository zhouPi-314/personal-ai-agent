"""ASR Provider：AMR/MP3 → 16k WAV → 侧车 SenseVoice → 文字。

本地执行，不出网；权重与解释器都在项目内，删目录即卸载。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..audio import AudioError, to_wav16k
from ..contracts import Capability, MediaInput, MediaResult, ResultStatus
from ..worker_client import WorkerError, call_persistent

WAV_MIMES = frozenset({"audio/wav", "audio/x-wav", "audio/wave"})


class ASRSidecarProvider:
    name = "sensevoice-sidecar"

    def __init__(
        self,
        *,
        ffmpeg: Path,
        python_exe: Path,
        worker_script: Path,
        model_dir: Path,
        max_seconds: int = 120,
        timeout: float = 90.0,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.python_exe = python_exe
        self.worker_script = worker_script
        self.model_dir = model_dir
        self.max_seconds = max_seconds
        self.timeout = timeout

    def available(self) -> bool:
        return all(
            [
                self.ffmpeg.is_file(),
                self.python_exe.is_file(),
                self.worker_script.is_file(),
                (self.model_dir / "model.int8.onnx").is_file(),
                (self.model_dir / "tokens.txt").is_file(),
            ]
        )

    def recognize_audio(
        self,
        item: MediaInput,
        *,
        language: str = "zh",
        deadline_ms: int = 90_000,
    ) -> MediaResult:
        if not self.available():
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.RECOGNIZE_AUDIO,
                error_code="E_MODEL_UNAVAILABLE",
                error_detail="ASR 侧车组件不齐",
            )

        timeout = max(10.0, min(self.timeout, deadline_ms / 1000))
        with tempfile.TemporaryDirectory(prefix="paa-asr-") as tmp:
            try:
                if item.mime in WAV_MIMES:
                    wav = item.local_path
                else:
                    wav = to_wav16k(
                        item.local_path,
                        ffmpeg=self.ffmpeg,
                        out_dir=Path(tmp),
                        max_seconds=self.max_seconds,
                        timeout=timeout,
                    )
            except AudioError as exc:
                return MediaResult(
                    status=ResultStatus.REJECTED,
                    capability=Capability.RECOGNIZE_AUDIO,
                    error_code=exc.code,
                    error_detail=exc.detail,
                )

            try:
                data = call_persistent(
                    python_exe=self.python_exe,
                    script=self.worker_script,
                    payload={
                        "wav_path": str(wav),
                        "model_dir": str(self.model_dir),
                        "language": language,
                    },
                    timeout=timeout,
                )
            except WorkerError as exc:
                return MediaResult(
                    status=ResultStatus.FAILED,
                    capability=Capability.RECOGNIZE_AUDIO,
                    error_code=exc.code,
                    error_detail=exc.detail,
                )

        text = str(data.get("text") or "").strip()
        if not text:
            return MediaResult(
                status=ResultStatus.DEGRADED,
                capability=Capability.RECOGNIZE_AUDIO,
                limitations=("语音里没有识别出文字（可能是静音或噪音）",),
            )
        return MediaResult(
            status=ResultStatus.OK,
            capability=Capability.RECOGNIZE_AUDIO,
            text=text,
            confidence=0.85,
            data={
                "audio_sec": data.get("audio_sec"),
                "decode_ms": data.get("decode_ms"),
            },
        )
