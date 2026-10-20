"""任务通道：状态机与（后续）执行。"""

from .engine import TaskEngine, TaskError
from .executor import ExecutionResult, TaskExecutor

__all__ = ["ExecutionResult", "TaskEngine", "TaskError", "TaskExecutor"]
