"""任务执行编排：策略 → 审批 → 执行 → 审计。

这是唯一把"能不能做"和"做完记什么"绑在一起的地方。
执行器可以换（Harness、本地 shell、远程设备），这条流程不变。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..audit import AuditService
from ..models import Task, ToolCall
from ..policy import classify
from .approval import ApprovalError, ApprovalService
from .engine import TaskEngine, TaskError
from .harness import HarnessResult, HarnessRunner

ACTOR = "agent"


@dataclass(frozen=True)
class ExecutionResult:
    task_id: uuid.UUID
    status: str
    final_text: str
    denied: bool = False
    reason: str = ""


class TaskExecutor:
    def __init__(
        self,
        *,
        engine: TaskEngine,
        runner: HarnessRunner,
        audit: AuditService,
        approvals: ApprovalService,
        workspace_root: Path,
        max_events: int = 5000,
    ) -> None:
        self.engine = engine
        self.runner = runner
        self.audit = audit
        self.approvals = approvals
        self.workspace_root = Path(workspace_root)
        self.max_events = max_events

    def run(
        self,
        task_id: uuid.UUID,
        *,
        approval_id: uuid.UUID | None = None,
        cancel_event=None,
    ) -> ExecutionResult:
        task = self.engine.get(task_id)
        decision = classify("execute")

        if decision.needs_approval:
            if approval_id is None:
                return self._deny(task, "该任务需要人工审批")
            try:
                self.approvals.consume(approval_id)
            except ApprovalError as exc:
                return self._deny(task, str(exc))
            self.audit.record(
                actor=ACTOR, action="execute", target=task.title, verdict="approved",
                detail=f"approval={approval_id}",
            )

        try:
            self.engine.start(task.id)
        except TaskError as exc:
            return ExecutionResult(task.id, task.status, "", denied=True, reason=str(exc))

        workspace = self.workspace_root / str(task.id)
        workspace.mkdir(parents=True, exist_ok=True)

        result = self.runner.run(
            task.title,
            workspace=workspace,
            cancel_event=cancel_event,
            on_event=lambda event: self._record_tool_event(task, event),
        )

        return self._settle(task, result)

    def _settle(self, task: Task, result: HarnessResult) -> ExecutionResult:
        if result.cancelled:
            self.engine.cancel(task.id)
            self._audit(task, "denied", "用户取消")
            return ExecutionResult(task.id, task.status, result.final_text, reason="已取消")

        if result.timed_out:
            self.engine.timeout(task.id)
            self._audit(task, "failed", "执行超时")
            return ExecutionResult(task.id, task.status, result.final_text, reason="超时")

        if result.exit_code != 0:
            self.engine.fail(task.id, error=result.stderr or f"退出码 {result.exit_code}")
            self._audit(task, "failed", result.stderr[:500])
            return ExecutionResult(task.id, task.status, result.final_text, reason="执行失败")

        self.engine.finish(task.id)
        self._audit(task, "allowed", f"events={len(result.events)}")
        return ExecutionResult(task.id, task.status, result.final_text)

    def _deny(self, task: Task, reason: str) -> ExecutionResult:
        self._audit(task, "denied", reason)
        return ExecutionResult(task.id, task.status, "", denied=True, reason=reason)

    def _audit(self, task: Task, verdict: str, detail: str) -> None:
        self.audit.record(
            actor=ACTOR, action="execute", target=task.title, verdict=verdict, detail=detail
        )

    def _record_tool_event(self, task: Task, event: dict) -> None:
        if event.get("type") != "tool_call":
            return
        raw = json.dumps(event.get("input", {}), sort_keys=True, ensure_ascii=False)
        self.engine.session.add(
            ToolCall(
                task_id=task.id,
                call_id=str(event.get("callId") or "")[:128] or None,
                tool=str(event.get("tool") or "unknown")[:64],
                args_digest=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                status="called",
            )
        )
