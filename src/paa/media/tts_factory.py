"""按配置挑一个 TTS 引擎；面板与 QQ 入口共用同一套选择逻辑。"""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from .providers.tts_kokoro import KokoroTTSProvider
from .providers.tts_sapi import SapiTTSProvider


def build_tts(settings: Settings, project_root: Path):
    sapi = SapiTTSProvider(
        script=project_root / "scripts" / "tts_sapi.ps1",
        voice=settings.media_tts_voice,
        max_chars=settings.media_tts_max_chars,
    )
    if (settings.media_tts_provider or "kokoro").strip().lower() == "sapi":
        return sapi
    kokoro = KokoroTTSProvider(
        python_exe=project_root / settings.media_asr_python,
        worker_script=project_root / settings.media_tts_kokoro_worker,
        model_dir=project_root / settings.media_tts_kokoro_dir,
        voice=settings.media_tts_kokoro_voice,
        model_file=settings.media_tts_kokoro_model,
        max_chars=settings.media_tts_max_chars,
    )
    return kokoro if kokoro.available() else sapi
