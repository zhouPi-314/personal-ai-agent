from datetime import UTC, datetime, timedelta

import pytest

from paa.tasks.approval import ApprovalError, ApprovalService


def test_request_creates_pending(session):
    approval = ApprovalService(session).request(action="delete", target="D:/tmp")

    assert approval.status == "pending"
    assert approval.expires_at > approval.requested_at


def test_approve_then_consume_once(session):
    service = ApprovalService(session)
    approval = service.request(action="delete")

    service.approve(approval.id)
    service.consume(approval.id)

    with pytest.raises(ApprovalError, match="使用过"):
        service.consume(approval.id)


def test_expired_cannot_be_approved(session):
    service = ApprovalService(session)
    start = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    approval = service.request(action="delete", ttl_seconds=60, now=start)

    with pytest.raises(ApprovalError, match="过期"):
        service.approve(approval.id, now=start + timedelta(seconds=120))

    assert approval.status == "expired"


def test_deny_blocks_consumption(session):
    service = ApprovalService(session)
    approval = service.request(action="delete")
    service.deny(approval.id)

    with pytest.raises(ApprovalError, match="denied"):
        service.consume(approval.id)


def test_expire_sweeps_pending(session):
    service = ApprovalService(session)
    start = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    service.request(action="delete", ttl_seconds=10, now=start)

    assert service.expire(now=start + timedelta(seconds=60)) == 1
