"""按配置组装模型路由。CLI 与常驻服务共用同一条逻辑。"""

from __future__ import annotations

from ..config import Settings
from .client import ModelClient
from .router import BrainRouter


def build_router(settings: Settings) -> BrainRouter:
    primary = (
        ModelClient(
            base_url=settings.local_base_url,
            api_key=settings.local_api_key,
            model=settings.local_model or settings.model_name,
        )
        if settings.local_base_url
        else None
    )
    fallback = (
        ModelClient(
            base_url=settings.model_base_url,
            api_key=settings.model_api_key,
            model=settings.model_name,
        )
        if settings.model_base_url
        else None
    )
    if primary and fallback:
        return BrainRouter(primary=primary, fallback=fallback)
    if primary:
        return BrainRouter(primary=primary, fallback=primary)
    if fallback:
        return BrainRouter(primary=fallback, fallback=fallback)
    raise RuntimeError("至少配置 PAA_LOCAL_BASE_URL 或 PAA_MODEL_BASE_URL 之一")
