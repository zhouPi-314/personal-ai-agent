"""维护台 API：只读为主，唯一的写操作是撤销记忆。

单用户、仅本机/内网访问；如果配置了 PAA_UI_TOKEN，则要求请求头携带。
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import func, select

from .config import PROJECT_ROOT, get_settings
from .db import session_scope
from .health import check_all
from .media import tts_settings
from .media.tts_factory import build_tts
from .memory import MemoryService
from .models import AuditLog, Memory, Message, Task
from .usage import UsageService

router = APIRouter(prefix="/api")

TTS_PREFS_PATH = PROJECT_ROOT / "data" / "media" / "tts.json"
ROUTE_PATH = PROJECT_ROOT / "data" / "model_route.json"
PREVIEW_TEXT = "你好，我是你的助手。这样说话听起来自然吗？"


def require_token(x_paa_token: str | None = Header(default=None)) -> None:
    expected = get_settings().ui_token
    if expected and x_paa_token != expected:
        raise HTTPException(status_code=401, detail="令牌无效")


@router.get("/status", dependencies=[])
def status() -> dict:
    with session_scope() as db:
        return {
            "messages": db.scalar(select(func.count()).select_from(Message)) or 0,
            "memories": db.scalar(select(func.count()).select_from(Memory)) or 0,
            "tasks": db.scalar(select(func.count()).select_from(Task)) or 0,
            "audit_logs": db.scalar(select(func.count()).select_from(AuditLog)) or 0,
        }


@router.get("/messages", dependencies=[Depends(require_token)])
def list_messages(
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = None,
) -> list[dict]:
    with session_scope() as db:
        stmt = select(Message).order_by(Message.id.desc()).limit(limit)
        if before_id is not None:
            stmt = stmt.where(Message.id < before_id)
        rows = list(db.scalars(stmt))
    return [
        {
            "id": m.id,
            "role": m.role,
            "source": m.source,
            "provider": m.provider,
            "content": m.content,
            "input_tokens": m.input_tokens,
            "output_tokens": m.output_tokens,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


@router.get("/memories", dependencies=[Depends(require_token)])
def list_memories(
    kind: str | None = None,
    include_revoked: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    with session_scope() as db:
        stmt = select(Memory).order_by(Memory.created_at.desc()).limit(limit)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        if not include_revoked:
            stmt = stmt.where(Memory.revoked_at.is_(None))
        rows = list(db.scalars(stmt))
    return [
        {
            "id": str(m.id),
            "kind": m.kind,
            "content": m.content,
            "confidence": m.confidence,
            "source_message_id": m.source_message_id,
            "revoked_at": m.revoked_at.isoformat() if m.revoked_at else None,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


@router.post("/memories/{memory_id}/revoke", dependencies=[Depends(require_token)])
def revoke_memory(memory_id: uuid.UUID) -> dict:
    with session_scope() as db:
        ok = MemoryService(db).revoke(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在或已撤销")
    return {"revoked": True}


@router.get("/tasks", dependencies=[Depends(require_token)])
def list_tasks(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    with session_scope() as db:
        rows = list(db.scalars(select(Task).order_by(Task.created_at.desc()).limit(limit)))
    return [
        {
            "id": str(t.id),
            "title": t.title,
            "status": t.status,
            "error": t.error,
            "created_at": t.created_at.isoformat(),
        }
        for t in rows
    ]


@router.get("/audit", dependencies=[Depends(require_token)])
def list_audit(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    with session_scope() as db:
        rows = list(db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)))
    return [
        {
            "id": a.id,
            "actor": a.actor,
            "action": a.action,
            "target": a.target,
            "verdict": a.verdict,
            "detail": a.detail,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.get("/usage", dependencies=[Depends(require_token)])
def usage(days: int = Query(default=7, ge=1, le=90)) -> dict:
    with session_scope() as db:
        service = UsageService(db)
        return {
            "today_total": service.today_total(),
            "today_cost": service.today_cost(),
            "quota": get_settings().daily_token_quota,
            "remaining": service.remaining(get_settings().daily_token_quota),
            "series": service.daily_series(days),
        }


@router.get("/health", dependencies=[Depends(require_token)])
def health_detail() -> dict:
    return check_all(get_settings())


# ── 语音偏好（M3）────────────────────────────────────────────
# ── 本地/云端切换 ────────────────────────────────────────────
def _read_mode() -> str:
    try:
        data = json.loads(ROUTE_PATH.read_text(encoding="utf-8"))
        return str(data.get("mode") or "auto")
    except (OSError, json.JSONDecodeError):
        return "auto"


def _write_mode(mode: str) -> None:
    ROUTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROUTE_PATH.write_text(json.dumps({"mode": mode}, ensure_ascii=False), encoding="utf-8")


@router.get("/model/route", dependencies=[Depends(require_token)])
def get_model_route(request: Request) -> dict:
    settings = get_settings()
    router = getattr(request.app.state, "router", None)
    mode = getattr(router, "mode", None) or _read_mode()
    return {
        "mode": mode,
        "modes": ["auto", "primary", "fallback"],
        "primary_model": settings.local_model or settings.model_name,
        "fallback_model": settings.model_name,
        "cloud_configured": bool(settings.model_base_url and settings.model_api_key),
        "primary_healthy": bool(getattr(router, "primary_healthy", True)),
    }


@router.post("/model/route", dependencies=[Depends(require_token)])
def set_model_route(payload: dict, request: Request) -> dict:
    router = getattr(request.app.state, "router", None)
    mode = payload.get("mode")
    if router is None:
        raise HTTPException(status_code=409, detail="模型路由未就绪")
    applied = router.set_mode(str(mode or "auto"))
    _write_mode(applied)
    return {"mode": applied}


@router.get("/media/tts", dependencies=[Depends(require_token)])
def get_tts_prefs() -> dict:
    settings = get_settings()
    model_dir = PROJECT_ROOT / settings.media_tts_kokoro_dir
    prefs = tts_settings.load(TTS_PREFS_PATH)
    return {
        "enabled": settings.media_tts_enabled,
        "mode": settings.media_tts_mode,
        "provider": settings.media_tts_provider,
        "voice": prefs.voice,
        "speed": prefs.speed,
        "voices": tts_settings.list_voices(model_dir),
        "max_chars": settings.media_tts_max_chars,
        "speed_range": [tts_settings.MIN_SPEED, tts_settings.MAX_SPEED],
    }


@router.post("/media/tts", dependencies=[Depends(require_token)])
def set_tts_prefs(payload: dict) -> dict:
    settings = get_settings()
    voices = tts_settings.list_voices(PROJECT_ROOT / settings.media_tts_kokoro_dir)
    voice = str(payload.get("voice") or "").strip()
    if voice and voices and voice not in voices:
        raise HTTPException(status_code=400, detail="音色不存在")
    try:
        speed = float(payload.get("speed", tts_settings.DEFAULT_SPEED))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="语速必须是数字") from exc

    saved = tts_settings.save(
        TTS_PREFS_PATH,
        tts_settings.TtsPrefs(voice=voice or tts_settings.DEFAULT_VOICE, speed=speed),
    )
    return {"voice": saved.voice, "speed": saved.speed}


@router.post("/media/tts/preview", dependencies=[Depends(require_token)])
def preview_tts(payload: dict | None = None) -> Response:
    """按当前偏好合成一小段，直接返回 wav 给浏览器播放。"""
    settings = get_settings()
    if not settings.media_tts_enabled:
        raise HTTPException(status_code=409, detail="语音合成未启用")

    prefs = tts_settings.load(TTS_PREFS_PATH)
    if payload and payload.get("voice"):
        prefs = tts_settings.TtsPrefs(voice=str(payload["voice"]), speed=prefs.speed)
    if payload and payload.get("speed") is not None:
        prefs = tts_settings.TtsPrefs(voice=prefs.voice, speed=float(payload["speed"]))

    provider = build_tts(settings, PROJECT_ROOT)
    out_dir = PROJECT_ROOT / "data" / "media" / "tmp"
    result = provider.synthesize_speech(
        PREVIEW_TEXT,
        out_dir=out_dir,
        voice_id=prefs.voice,
        max_chars=settings.media_tts_max_chars,
        speed=prefs.speed,
    )
    if result.status.value != "ok":
        raise HTTPException(status_code=503, detail=f"合成失败：{result.error_code or result.status.value}")

    from pathlib import Path as _Path

    data = _Path(str(result.data.get("path") or "")).read_bytes()
    return Response(content=data, media_type="audio/wav")
