"""运行时配置：全部来自环境变量或 .env，代码里不出现任何凭据。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # 用绝对路径，避免从不同工作目录启动时静默读不到 .env。
    model_config = SettingsConfigDict(
        env_prefix="PAA_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    env: str = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    # 留空表示尚未配置；业务代码必须显式检查后再使用。
    database_url: str = ""
    model_provider: str = ""
    model_base_url: str = ""
    model_name: str = "deepseek-chat"
    model_api_key: str = ""

    # 主通道：本机 DSH 的 OpenAI 兼容端口（可选）
    local_base_url: str = ""
    local_api_key: str = ""
    local_model: str = ""

    persona_path: str = "persona.md"
    user_name: str = "owner"
    log_file: str = ""
    ui_token: str = ""
    pricing_path: str = "pricing.json"
    daily_token_quota: int = 0  # 0 = 不限制
    timezone: str = "Asia/Shanghai"

    # OneBot（可选）
    onebot_ws_url: str = ""
    onebot_http_url: str = ""
    onebot_access_token: str = ""
    onebot_self_id: str = ""
    owner_qq: str = ""
    # backup_remote: str = ""  # 云服务器已取消

    # 媒体能力（默认全关；设计见 docs/multimodal/）
    media_enabled: bool = False
    media_sticker_enabled: bool = False
    media_sticker_dir: str = "data/stickers"
    media_sticker_cooldown_sec: float = 60.0
    media_sticker_daily_cap: int = 20
    media_sticker_recent: int = 5
    # 先只私聊；群聊接口预留，打开群场景也仍需 owner/被 @ 才唤醒
    media_sticker_private_only: bool = True

    # 学习线（M1.5）：只收主人私聊里的图，先进隔离区，人工晋级后才可发送
    media_learn_enabled: bool = False
    media_quarantine_dir: str = "data/media/quarantine"
    media_learn_daily_cap: int = 10
    media_learn_total_cap: int = 200

    # 图片理解（M2）：默认关；egress_allow 为空表示不外发任何图片
    media_vision_enabled: bool = False
    media_vision_model: str = "Qwen/Qwen3-VL-8B-Instruct"
    media_egress_allow: str = ""  # 逗号分隔，例如 image

    # 语音识别（M3）：本地侧车，不出网
    media_asr_enabled: bool = False
    media_asr_python: str = "runtime/python312/python.exe"
    media_asr_model_dir: str = "models/sensevoice"
    media_asr_worker: str = "scripts/asr_worker.py"
    media_ffmpeg: str = "runtime/ffmpeg/bin/ffmpeg.exe"

    # 语音合成（M3）：off / voice_input（收到语音才回语音）/ always
    media_tts_enabled: bool = False
    media_tts_mode: str = "voice_input"
    media_tts_voice: str = "Microsoft Huihui Desktop"
    media_tts_max_chars: int = 150
    # 合成引擎：kokoro（自然，CPU 较慢）/ sapi（快，机器音）
    media_tts_provider: str = "kokoro"
    media_tts_kokoro_voice: str = "zf_001"
    media_tts_kokoro_model: str = "model.onnx"  # fp32 在本机比 int8 快 8 倍
    media_tts_kokoro_dir: str = "models/kokoro"
    media_tts_kokoro_worker: str = "scripts/tts_kokoro_worker.py"


@lru_cache
def get_settings() -> Settings:
    return Settings()
