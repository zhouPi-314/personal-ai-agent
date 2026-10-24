"""SAPI 语音合成（Windows 自带，零下载）。

文本经过临时文件传给 PowerShell，绝不拼进命令行——避免引号与命令注入。
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from ..contracts import Capability, MediaResult, ResultStatus

DEFAULT_MAX_CHARS = 150
MIN_WAV_BYTES = 1024


class SapiTTSProvider:
    name = "sapi"

    def __init__(
        self,
        *,
        script: Path,
        powershell: str = "powershell.exe",
        voice: str = "Microsoft Huihui Desktop",
        rate: int = 0,
        max_chars: int = DEFAULT_MAX_CHARS,
        timeout: float = 30.0,
    ) -> None:
        self.script = script
        self.powershell = powershell
        self.voice = voice
        self.rate = rate
        self.max_chars = max_chars
        self.timeout = timeout

    def available(self) -> bool:
        return self.script.is_file()

    def synthesize_speech(
        self,
        text: str,
        *,
        out_dir: Path,
        voice_id: str = "",
        max_chars: int | None = None,
        deadline_ms: int = 30_000,
    ) -> MediaResult:
        if not self.available():
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_MODEL_UNAVAILABLE",
                error_detail="缺少 scripts/tts_sapi.ps1",
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
        token = uuid.uuid4().hex[:12]
        text_file = out_dir / f"{token}.txt"
        out_file = out_dir / f"{token}.wav"
        text_file.write_text(content, encoding="utf-8")

        argv = [
            self.powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.script),
            "-TextFile",
            str(text_file),
            "-OutFile",
            str(out_file),
            "-Voice",
            voice_id or self.voice,
            "-Rate",
            str(self.rate),
        ]
        timeout = max(5.0, min(self.timeout, deadline_ms / 1000))
        try:
            completed = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_TIMEOUT",
            )
        except OSError as exc:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_SPAWN_FAILED",
                error_detail=str(exc)[:160],
            )
        finally:
            text_file.unlink(missing_ok=True)

        if completed.returncode != 0 or not out_file.is_file():
            detail = completed.stderr.decode("utf-8", errors="replace")[-200:]
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_SYNTH_FAILED",
                error_detail=detail,
            )
        size = out_file.stat().st_size
        if size < MIN_WAV_BYTES:
            out_file.unlink(missing_ok=True)
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_TOO_SMALL",
                error_detail=str(size),
            )

        return MediaResult(
            status=ResultStatus.OK,
            capability=Capability.SYNTHESIZE_SPEECH,
            text=content,
            data={"path": str(out_file), "bytes": size, "truncated": truncated},
            limitations=(("文本超过 " + str(limit) + " 字，已截断",) if truncated else ()),
        )
