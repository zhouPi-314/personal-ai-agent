"""Qwen3-TTS 音色克隆 Provider（0.6B，Apache-2.0）。

两种模式：
- clone：给一段参考音频（音色来源），合成同音色语音；
- custom：用模型内置音色（speaker 名）。

音色必须来自 authorized 清单（data/voices/index.json），见 media.voices。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..contracts import Capability, MediaResult, ResultStatus
from ..voices import resolve
from ..worker_client import WorkerError, call_persistent

DEFAULT_MAX_CHARS = 160
MIN_WAV_BYTES = 8192


class QwenTTSProvider:
    name = "qwen-tts"

    def __init__(
        self,
        *,
        python_exe: Path,
        worker_script: Path,
        model_dir: Path,
        voices_root: Path,
        default_voice: str = "",
        speaker: str = "",
        language: str = "Chinese",
        device: str = "cuda",
        max_chars: int = DEFAULT_MAX_CHARS,
        timeout: float = 180.0,
    ) -> None:
        self.python_exe = python_exe
        self.worker_script = worker_script
        self.model_dir = model_dir
        self.voices_root = voices_root
        self.default_voice = default_voice
        self.speaker = speaker
        self.language = language
        self.device = device
        self.max_chars = max_chars
        self.timeout = timeout

    def available(self) -> bool:
        return all(
            [
                self.python_exe.is_file(),
                self.worker_script.is_file(),
                (self.model_dir / "model.safetensors").is_file(),
                (self.model_dir / "config.json").is_file(),
            ]
        )

    def _reference(self, voice_id: str) -> tuple[str, str, str]:
        """返回 (模式, 参考音频路径/speaker, 署名)。"""
        target = (voice_id or self.default_voice or "").strip()
        if target:
            voice = resolve(self.voices_root, target)
            if voice is not None:
                ref = self.voices_root / voice.file
                return "clone", str(ref), voice.credit
            direct = Path(target)
            if direct.is_file():
                return "clone", str(direct), ""
        if self.speaker:
            return "custom", self.speaker, ""
        return "custom", "", ""

    def synthesize_speech(
        self,
        text: str,
        *,
        out_dir: Path,
        voice_id: str = "",
        max_chars: int | None = None,
        deadline_ms: int = 180_000,
        speed: float | None = None,
    ) -> MediaResult:
        if not self.available():
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_MODEL_UNAVAILABLE",
                error_detail="Qwen3-TTS 模型或侧车缺失",
            )

        content = (text or "").strip()
        if not content:
            return MediaResult(
                status=ResultStatus.REJECTED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_EMPTY_TEXT",
            )
        limit = max(1, int(max_chars or self.max_chars))
        truncated = len(content) > limit
        if truncated:
            content = content[:limit]

        mode, reference, credit = self._reference(voice_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / ("qwen_" + uuid.uuid4().hex[:10] + ".wav")
        timeout = max(30.0, min(self.timeout, deadline_ms / 1000))

        try:
            data = call_persistent(
                python_exe=self.python_exe,
                script=self.worker_script,
                payload={
                    "text": content,
                    "out_wav": str(target),
                    "model_dir": str(self.model_dir),
                    "language": self.language,
                    "mode": mode,
                    "ref_audio": reference if mode == "clone" else "",
                    "speaker": reference if mode == "custom" else "",
                    "device": self.device,
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

        if not target.is_file() or target.stat().st_size < MIN_WAV_BYTES:
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
                "path": str(target),
                "bytes": target.stat().st_size,
                "seconds": data.get("seconds"),
                "gen_ms": data.get("gen_ms"),
                "mode": mode,
                "credit": credit,
                "truncated": truncated,
            },
            limitations=(("文本超过 " + str(limit) + " 字，已截断",) if truncated else ()),
        )
