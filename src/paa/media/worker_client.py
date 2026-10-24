"""侧车客户端：拉起独立解释器跑一次性任务，按行收发 JSON。

为什么不用常驻进程：模型加载只要 1.7 秒，而常驻进程要处理崩溃恢复、
闲置卸载、单实例互斥等一堆状态。语音是低频操作，"用完就退"更简单也更安全。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT = 90.0


class WorkerError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code + ((": " + detail) if detail else ""))
        self.code = code
        self.detail = detail


def call_worker(
    *,
    python_exe: Path,
    script: Path,
    payload: dict[str, object],
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, object]:
    """跑一次侧车任务。成功返回解析后的 JSON，失败抛 WorkerError。"""
    if not python_exe.is_file():
        raise WorkerError("E_PYTHON_MISSING", str(python_exe))
    if not script.is_file():
        raise WorkerError("E_WORKER_MISSING", str(script))

    request = json.dumps(payload, ensure_ascii=False) + "\n"
    # 子进程 stdout 被重定向时，Python 默认用系统代码页（中文 Windows 是 cp936），
    # 会把中文输出写成 GBK，主进程按 UTF-8 解就是乱码。必须强制 UTF-8。
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [str(python_exe), str(script)],
            input=request.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerError("E_TIMEOUT", "侧车超时") from exc
    except OSError as exc:
        raise WorkerError("E_SPAWN_FAILED", str(exc)) from exc

    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    if not stdout:
        detail = completed.stderr.decode("utf-8", errors="replace")[-200:]
        raise WorkerError("E_EMPTY_OUTPUT", detail)

    last_line = stdout.splitlines()[-1]
    try:
        result = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise WorkerError("E_BAD_OUTPUT", last_line[:200]) from exc

    if not isinstance(result, dict):
        raise WorkerError("E_BAD_OUTPUT", "响应不是对象")
    if result.get("status") != "ok":
        raise WorkerError(
            str(result.get("code") or "E_WORKER"),
            str(result.get("detail") or "")[:200],
        )
    return result
