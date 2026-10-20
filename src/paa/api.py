"""维护台 API：只读为主，唯一的写操作是撤销记忆。

单用户、仅本机/内网访问；如果配置了 PAA_UI_TOKEN，则要求请求头携带。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select

from .config import get_settings
from .db import session_scope
from .memory import MemoryService
from .models import AuditLog, Memory, Message, Task
from .usage import UsageService

router = APIRouter(prefix="/api")


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
            "series": service.daily_series(days),
        }
