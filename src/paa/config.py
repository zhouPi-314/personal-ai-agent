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


@lru_cache
def get_settings() -> Settings:
    return Settings()
