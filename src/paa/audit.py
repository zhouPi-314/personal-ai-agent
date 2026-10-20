"""审计：只追加地记录"谁在什么时候对什么做了什么、结果如何"。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        actor: str,
        action: str,
        target: str = "",
        verdict: str,
        detail: str | None = None,
    ) -> AuditLog:
        if verdict not in {"allowed", "denied", "approved", "failed"}:
            raise ValueError(f"未知 verdict：{verdict}")
        entry = AuditLog(
            actor=actor[:64],
            action=action[:64],
            target=target[:500],
            verdict=verdict,
            detail=(detail or "")[:2000] or None,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def recent(self, *, limit: int = 50) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        return list(self.session.scalars(stmt))
