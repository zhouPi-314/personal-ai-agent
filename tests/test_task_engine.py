import uuid
from datetime import UTC, datetime, timedelta

import pytest

from paa.tasks import TaskEngine, TaskError


def _engine(session, user):
    return TaskEngine(session)


def _create(engine, user, **kwargs):
    return engine.create(user_id=user.id, title="整理下载目录", **kwargs)


def test_create_starts_pending(session, user):
    task = _create(_engine(session, user), user)

    assert task.status == "pending"
    assert task.timeout_sec == 300


def test_start_sets_started_at(session, user):
    engine = _engine(session, user)
    task = _create(engine, user)
    moment = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

    engine.start(task.id, now=moment)

    assert task.status == "running"
    assert task.started_at == moment


def test_finish_marks_done(session, user):
    engine = _engine(session, user)
    task = _create(engine, user)
    engine.start(task.id)

    engine.finish(task.id)

    assert task.status == "done"
    assert task.finished_at is not None


def test_illegal_transition_is_rejected(session, user):
    engine = _engine(session, user)
    task = _create(engine, user)

    with pytest.raises(TaskError, match="非法状态转换"):
        engine.finish(task.id)


def test_cancel_pending_task(session, user):
    engine = _engine(session, user)
    task = _create(engine, user)

    engine.cancel(task.id)

    assert task.status == "cancelled"


def test_terminal_task_cannot_be_cancelled(session, user):
    engine = _engine(session, user)
    task = _create(engine, user)
    engine.start(task.id)
    engine.finish(task.id)

    with pytest.raises(TaskError):
        engine.cancel(task.id)


def test_fail_records_error(session, user):
    engine = _engine(session, user)
    task = _create(engine, user)
    engine.start(task.id)

    engine.fail(task.id, error="模型返回 500")

    assert task.status == "failed"
    assert "500" in task.error


def test_mark_timeouts_only_expires_overdue(session, user):
    engine = _engine(session, user)
    start = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    slow = _create(engine, user, timeout_sec=60)
    fast = _create(engine, user, timeout_sec=600)
    engine.start(slow.id, now=start)
    engine.start(fast.id, now=start)

    expired = engine.mark_timeouts(now=start + timedelta(seconds=120))

    assert [t.id for t in expired] == [slow.id]
    assert slow.status == "timeout"
    assert fast.status == "running"


def test_recover_interrupted_marks_running(session, user):
    engine = _engine(session, user)
    task = _create(engine, user)
    engine.start(task.id)

    count = engine.recover_interrupted()

    assert count == 1
    assert task.status == "interrupted"


def test_unknown_task_raises(session, user):
    engine = _engine(session, user)

    with pytest.raises(TaskError, match="不存在"):
        engine.start(uuid.uuid4())


def test_rejects_bad_parameters(session, user):
    engine = _engine(session, user)

    with pytest.raises(TaskError):
        engine.create(user_id=user.id, title="   ")
    with pytest.raises(TaskError):
        engine.create(user_id=user.id, title="x", timeout_sec=0)
