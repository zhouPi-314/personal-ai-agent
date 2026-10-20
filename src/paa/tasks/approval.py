"""审批：L3 操作的一次性授权。

一条审批 = 一个动作 + 一个目标 + 一个有效期，用一次就作废。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Approval

DEFAULT_TTL_SECONDS = 600


class ApprovalError(RuntimeError):
    pass


class ApprovalService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def request(
        self,
        *,
        action: str,
        target: str = "",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: datetime | None = None,
    ) -> Approval:
        if ttl_seconds <= 0:
            raise ApprovalError("ttl_seconds 必须为正")
        moment = now or datetime.now(UTC)
        approval = Approval(
            id=uuid.uuid4(),
            action=action[:64],
            target=target[:500],
            status="pending",
            expires_at=moment + timedelta(seconds=ttl_seconds),
        )
        self.session.add(approval)
        self.session.flush()
        return approval

    def approve(self, approval_id: uuid.UUID, *, now: datetime | None = None) -> Approval:
        return self._decide(approval_id, "approved", now)

    def deny(self, approval_id: uuid.UUID, *, now: datetime | None = None) -> Approval:
        return self._decide(approval_id, "denied", now)

    def consume(self, approval_id: uuid.UUID, *, now: datetime | None = None) -> Approval:
        moment = now or datetime.now(UTC)
        approval = self._get(approval_id)
        if approval.status != "approved":
            raise ApprovalError(f"审批状态为 {approval.status}，不能使用")
        if approval.expires_at <= moment:
            approval.status = "expired"
            self.session.flush()
            raise ApprovalError("审批已过期")
        if approval.used_at is not None:
            raise ApprovalError("审批已被使用过")
        approval.used_at = moment
        self.session.flush()
        return approval

    def expire(self, *, now: datetime | None = None) -> int:
        moment = now or datetime.now(UTC)
        pending = self.session.scalars(
            select(Approval).where(Approval.status == "pending")
        ).all()
        count = 0
        for approval in pending:
            if approval.expires_at <= moment:
                approval.status = "expired"
                count += 1
        if count:
            self.session.flush()
        return count

    def _decide(
        self, approval_id: uuid.UUID, status: str, now: datetime | None
    ) -> Approval:
        moment = now or datetime.now(UTC)
        approval = self._get(approval_id)
        if approval.status != "pending":
            raise ApprovalError(f"审批状态为 {approval.status}，不能再次处理")
        if approval.expires_at <= moment:
            approval.status = "expired"
            self.session.flush()
            raise ApprovalError("审批已过期")
        approval.status = status
        approval.decided_at = moment
        self.session.flush()
        return approval

    def _get(self, approval_id: uuid.UUID) -> Approval:
        approval = self.session.get(Approval, approval_id)
        if approval is None:
            raise ApprovalError(f"审批不存在：{approval_id}")
        return approval
