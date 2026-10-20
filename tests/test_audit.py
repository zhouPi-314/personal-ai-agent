import uuid

import pytest

from paa.audit import AuditService


def test_record_appends(session):
    audit = AuditService(session)
    actor = f"test-{uuid.uuid4()}"

    audit.record(actor=actor, action="delete", target="D:/tmp", verdict="denied", detail="L3")

    rows = [r for r in audit.recent() if r.actor == actor]
    assert len(rows) == 1
    assert rows[0].verdict == "denied"
    assert rows[0].target == "D:/tmp"


def test_recent_returns_newest_first(session):
    audit = AuditService(session)
    actor = f"test-{uuid.uuid4()}"
    audit.record(actor=actor, action="a", verdict="allowed")
    audit.record(actor=actor, action="b", verdict="allowed")

    mine = [r for r in audit.recent() if r.actor == actor]
    assert [r.action for r in mine] == ["b", "a"]


def test_rejects_unknown_verdict(session):
    with pytest.raises(ValueError):
        AuditService(session).record(actor="owner", action="x", verdict="maybe")
