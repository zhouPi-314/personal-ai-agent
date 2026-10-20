"""消息仓储：只负责把对话写进库、按人取回来。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Message


class MessageStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append_turn(
        self,
        *,
        user_id: uuid.UUID,
        user_text: str,
        reply: str,
        source: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self.session.add_all(
            [
                Message(user_id=user_id, role="user", content=user_text, source=source),
                Message(
                    user_id=user_id,
                    role="assistant",
                    content=reply,
                    source=source,
                    provider=provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ),
            ]
        )
        self.session.flush()

    def recent(self, user_id: uuid.UUID, *, limit: int = 20) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.user_id == user_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
        return list(reversed(list(self.session.scalars(stmt))))
