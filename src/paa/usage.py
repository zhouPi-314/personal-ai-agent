"""用量统计：每次模型调用落一条，按天聚合。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import TokenUsage


class UsageService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        user_id: uuid.UUID | None,
        source: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self.session.add(
            TokenUsage(
                user_id=user_id,
                source=source[:16],
                provider=provider[:16],
                model=model[:64],
                input_tokens=max(0, int(input_tokens)),
                output_tokens=max(0, int(output_tokens)),
            )
        )
        self.session.flush()

    def today_total(self) -> int:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(
            func.coalesce(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens), 0)
        ).where(TokenUsage.created_at >= start)
        return int(self.session.scalar(stmt) or 0)

    def daily_series(self, days: int = 7) -> list[dict]:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(
                func.date(TokenUsage.created_at).label("day"),
                func.coalesce(func.sum(TokenUsage.input_tokens), 0).label("input"),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0).label("output"),
            )
            .where(TokenUsage.created_at >= since)
            .group_by("day")
            .order_by("day")
        )
        return [
            {"day": str(row.day), "input": int(row.input), "output": int(row.output)}
            for row in self.session.execute(stmt)
        ]
