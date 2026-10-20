"""任务状态机。

只做状态与持久化，不执行任何东西。执行器（Harness）在阶段 3.3 接入，
它只能通过这里的方法改变任务状态——这就是"低耦合"的具体含义。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Task

TERMINAL = frozenset({"done", "failed", "cancelled", "timeout", "interrupted"})

ALLOWED: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"done", "failed", "cancelled", "timeout", "interrupted"}),
    "done": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "timeout": frozenset(),
    "interrupted": frozenset(),
}


class TaskError(RuntimeError):
    """非法状态转换或参数错误。"""


class TaskEngine:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        user_id: uuid.UUID,
        title: str,
        timeout_sec: int = 300,
    ) -> Task:
        title = (title or "").strip()
        if not title:
            raise TaskError("title 不能为空")
        if timeout_sec <= 0:
            raise TaskError("timeout_sec 必须为正")

        task = Task(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title[:200],
            status="pending",
            timeout_sec=timeout_sec,
        )
        self.session.add(task)
        self.session.flush()
        return task

    def get(self, task_id: uuid.UUID) -> Task:
        return self._get(task_id)

    def timeout(
        self, task_id: uuid.UUID, *, reason: str = "任务超时", now: datetime | None = None
    ) -> Task:
        task = self._get(task_id)
        self._transition(task, "timeout")
        task.error = reason[:2000]
        task.finished_at = now or datetime.now(UTC)
        self.session.flush()
        return task

    def start(self, task_id: uuid.UUID, *, now: datetime | None = None) -> Task:
        task = self._get(task_id)
        self._transition(task, "running")
        task.started_at = now or datetime.now(UTC)
        self.session.flush()
        return task

    def finish(self, task_id: uuid.UUID, *, now: datetime | None = None) -> Task:
        task = self._get(task_id)
        self._transition(task, "done")
        task.finished_at = now or datetime.now(UTC)
        self.session.flush()
        return task

    def fail(
        self,
        task_id: uuid.UUID,
        *,
        error: str,
        now: datetime | None = None,
    ) -> Task:
        task = self._get(task_id)
        self._transition(task, "failed")
        task.error = (error or "")[:2000]
        task.finished_at = now or datetime.now(UTC)
        self.session.flush()
        return task

    def cancel(self, task_id: uuid.UUID, *, now: datetime | None = None) -> Task:
        task = self._get(task_id)
        self._transition(task, "cancelled")
        task.finished_at = now or datetime.now(UTC)
        self.session.flush()
        return task

    def mark_timeouts(self, *, now: datetime | None = None) -> list[Task]:
        moment = now or datetime.now(UTC)
        expired: list[Task] = []
        running = self.session.scalars(select(Task).where(Task.status == "running")).all()
        for task in running:
            if task.started_at is None:
                continue
            deadline = task.started_at + timedelta(seconds=task.timeout_sec)
            if moment >= deadline:
                self._transition(task, "timeout")
                task.finished_at = moment
                task.error = "超过任务超时时间"
                expired.append(task)
        if expired:
            self.session.flush()
        return expired

    def recover_interrupted(self, *, now: datetime | None = None) -> int:
        """进程重启时调用：running 一律标记中断，绝不自动重跑。

        自动重跑有副作用风险（比如任务已经删了文件），宁可让人看一眼再决定。
        """
        moment = now or datetime.now(UTC)
        running = self.session.scalars(select(Task).where(Task.status == "running")).all()
        for task in running:
            self._transition(task, "interrupted")
            task.finished_at = moment
            task.error = "进程重启，任务被中断"
        if running:
            self.session.flush()
        return len(running)

    def _get(self, task_id: uuid.UUID) -> Task:
        task = self.session.get(Task, task_id)
        if task is None:
            raise TaskError(f"任务不存在：{task_id}")
        return task

    @staticmethod
    def _transition(task: Task, target: str) -> None:
        if target not in ALLOWED.get(task.status, frozenset()):
            raise TaskError(f"非法状态转换：{task.status} -> {target}")
        task.status = target
