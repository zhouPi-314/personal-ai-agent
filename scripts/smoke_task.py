"""端到端：建任务 → 审批 → 真实 dsh 执行 → 审计与工具调用落库。"""

import sys
from pathlib import Path

from sqlalchemy import select

from paa.audit import AuditService
from paa.db import session_scope
from paa.models import ToolCall, User
from paa.tasks import TaskEngine, TaskExecutor
from paa.tasks.approval import ApprovalService
from paa.tasks.harness import HarnessRunner

DSH = r"D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd"
WORKSPACE = Path(__file__).resolve().parent / "tasks"


def main() -> int:
    with session_scope() as db:
        user = db.scalars(select(User).where(User.display_name == "owner")).first()
        if user is None:
            print("没有 owner 用户，先跑一次 CLI")
            return 1

        approvals = ApprovalService(db)
        approval = approvals.request(action="execute", ttl_seconds=600)
        approvals.approve(approval.id)

        engine = TaskEngine(db)
        task = engine.create(
            user_id=user.id,
            title="Create a file hello.txt with the word ok, then read it back. Use tools.",
            timeout_sec=180,
        )

        executor = TaskExecutor(
            engine=engine,
            runner=HarnessRunner(
                dsh_path=DSH, profile="ofmtest", dsh_home=r"D:\dsh-home", timeout=180
            ),
            audit=AuditService(db),
            approvals=approvals,
            workspace_root=WORKSPACE,
        )
        result = executor.run(task.id, approval_id=approval.id)

        calls = db.scalars(select(ToolCall).where(ToolCall.task_id == task.id)).all()
        audit = AuditService(db).recent(limit=5)

        print(f"denied={result.denied} status={result.status}")
        print(f"final={result.final_text[:120]!r}")
        print(f"tool_calls={[(c.tool, c.status) for c in calls]}")
        print(f"audit={[(a.action, a.verdict) for a in audit]}")
        print(f"workspace_exists={(WORKSPACE / str(task.id)).is_dir()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
