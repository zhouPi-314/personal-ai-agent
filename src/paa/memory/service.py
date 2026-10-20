"""记忆服务：按人存、可追溯来源、可撤销。

刻意只暴露三个方法。接口越窄，调用方越难绕过来源与撤销语义。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Memory

KINDS = frozenset({"trait", "fact", "topic", "pending"})
MAX_CONTENT = 2000


class MemoryService:
    """不持有连接，只使用调用方传入的 Session。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def remember(
        self,
        user_id: uuid.UUID,
        kind: str,
        content: str,
        *,
        source_message_id: uuid.UUID | None = None,
        confidence: float = 0.5,
        expires_at: datetime | None = None,
    ) -> Memory:
        if kind not in KINDS:
            raise ValueError(f"kind 必须是 {sorted(KINDS)} 之一，收到 {kind!r}")
        text = (content or "").strip()
        if not text:
            raise ValueError("content 不能为空")
        if len(text) > MAX_CONTENT:
            raise ValueError(f"content 超过 {MAX_CONTENT} 字符")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence 必须在 0.0 到 1.0 之间")

        memory = Memory(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=kind,
            content=text,
            source_message_id=source_message_id,
            confidence=confidence,
            expires_at=expires_at,
        )
        self.session.add(memory)
        self.session.flush()
        return memory

    def recall(
        self,
        user_id: uuid.UUID,
        *,
        kind: str | None = None,
        limit: int = 20,
        include_revoked: bool = False,
    ) -> list[Memory]:
        stmt = select(Memory).where(Memory.user_id == user_id)
        if kind is not None:
            stmt = stmt.where(Memory.kind == kind)
        if not include_revoked:
            stmt = stmt.where(Memory.revoked_at.is_(None))

        now = datetime.now(UTC)
        stmt = stmt.where((Memory.expires_at.is_(None)) | (Memory.expires_at > now))
        stmt = stmt.order_by(Memory.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def revoke(self, memory_id: uuid.UUID) -> bool:
        memory = self.session.get(Memory, memory_id)
        if memory is None or memory.revoked_at is not None:
            return False
        memory.revoked_at = datetime.now(UTC)
        self.session.flush()
        return True
