from pathlib import Path

from paa.audit import AuditService
from paa.models import ToolCall
from paa.tasks.approval import ApprovalService
from paa.tasks.engine import TaskEngine
from paa.tasks.executor import TaskExecutor
from paa.tasks.harness import HarnessResult


class FakeRunner:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.last_workspace = None

    def run(self, task_text, *, workspace, cancel_event=None, on_event=None):
        self.calls += 1
        self.last_workspace = workspace
        if on_event:
            on_event({"type": "tool_call", "callId": "c1", "tool": "write", "input": {"p": "a"}})
        return self.result


def _executor(session, tmp_path, result):
    return TaskExecutor(
        engine=TaskEngine(session),
        runner=FakeRunner(result),
        audit=AuditService(session),
        approvals=ApprovalService(session),
        workspace_root=Path(tmp_path),
    )


def _approved(session):
    service = ApprovalService(session)
    approval = service.request(action="execute")
    service.approve(approval.id)
    return approval.id


def test_denied_without_approval(session, user, tmp_path):
    engine = TaskEngine(session)
    task = engine.create(user_id=user.id, title="整理文件")
    executor = _executor(session, tmp_path, HarnessResult(exit_code=0, final_text=""))

    result = executor.run(task.id)

    assert result.denied
    assert task.status == "pending"
    assert executor.runner.calls == 0


def test_runs_with_approval(session, user, tmp_path):
    engine = TaskEngine(session)
    task = engine.create(user_id=user.id, title="整理文件")
    executor = _executor(session, tmp_path, HarnessResult(exit_code=0, final_text="完成"))

    result = executor.run(task.id, approval_id=_approved(session))

    assert not result.denied
    assert task.status == "done"
    assert result.final_text == "完成"
    assert executor.runner.last_workspace.name == str(task.id)


def test_tool_events_are_recorded(session, user, tmp_path):
    engine = TaskEngine(session)
    task = engine.create(user_id=user.id, title="整理文件")
    executor = _executor(session, tmp_path, HarnessResult(exit_code=0, final_text="ok"))

    executor.run(task.id, approval_id=_approved(session))

    calls = session.query(ToolCall).filter_by(task_id=task.id).all()
    assert len(calls) == 1
    assert calls[0].tool == "write"
    assert len(calls[0].args_digest) == 64


def test_failure_marks_task_failed(session, user, tmp_path):
    engine = TaskEngine(session)
    task = engine.create(user_id=user.id, title="整理文件")
    executor = _executor(session, tmp_path, HarnessResult(exit_code=1, final_text="", stderr="boom"))

    result = executor.run(task.id, approval_id=_approved(session))

    assert task.status == "failed"
    assert "boom" in task.error
    assert result.reason == "执行失败"


def test_timeout_marks_task_timeout(session, user, tmp_path):
    engine = TaskEngine(session)
    task = engine.create(user_id=user.id, title="慢任务")
    executor = _executor(
        session, tmp_path, HarnessResult(exit_code=None, final_text="", timed_out=True)
    )

    executor.run(task.id, approval_id=_approved(session))

    assert task.status == "timeout"


def test_audit_trail_written(session, user, tmp_path):
    engine = TaskEngine(session)
    task = engine.create(user_id=user.id, title="整理文件")
    executor = _executor(session, tmp_path, HarnessResult(exit_code=0, final_text="ok"))

    executor.run(task.id, approval_id=_approved(session))

    verdicts = [r.verdict for r in AuditService(session).recent()]
    assert "approved" in verdicts
    assert "allowed" in verdicts
