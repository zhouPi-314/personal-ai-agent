import uuid
from datetime import UTC, datetime, timedelta

import pytest

from paa.memory import MemoryService


def test_remember_then_recall(session, user):
    service = MemoryService(session)
    created = service.remember(user.id, "fact", "他住在成都", confidence=0.9)

    rows = service.recall(user.id)

    assert [m.id for m in rows] == [created.id]
    assert rows[0].content == "他住在成都"
    assert rows[0].confidence == 0.9


def test_recall_filters_by_kind(session, user):
    service = MemoryService(session)
    service.remember(user.id, "fact", "喜欢喝冰美式")
    service.remember(user.id, "trait", "常熬夜")

    traits = service.recall(user.id, kind="trait")

    assert len(traits) == 1
    assert traits[0].content == "常熬夜"


def test_revoked_memory_is_hidden_by_default(session, user):
    service = MemoryService(session)
    memory = service.remember(user.id, "topic", "昨天聊到搬家")

    assert service.revoke(memory.id) is True
    assert service.recall(user.id) == []
    assert len(service.recall(user.id, include_revoked=True)) == 1


def test_revoke_unknown_id_returns_false(session):
    service = MemoryService(session)

    assert service.revoke(uuid.uuid4()) is False


def test_rejects_unknown_kind(session, user):
    service = MemoryService(session)

    with pytest.raises(ValueError):
        service.remember(user.id, "guess", "随便写的")


def test_rejects_empty_content(session, user):
    service = MemoryService(session)

    with pytest.raises(ValueError):
        service.remember(user.id, "fact", "   ")


def test_expired_memory_is_not_returned(session, user):
    service = MemoryService(session)
    past = datetime.now(UTC) - timedelta(hours=1)
    service.remember(user.id, "fact", "上周说要去爬山", expires_at=past)
    service.remember(user.id, "fact", "他喜欢安静的地方")

    rows = service.recall(user.id)

    assert [m.content for m in rows] == ["他喜欢安静的地方"]


def test_recall_respects_limit(session, user):
    service = MemoryService(session)
    for index in range(5):
        service.remember(user.id, "topic", f"话题 {index}")

    assert len(service.recall(user.id, limit=2)) == 2
