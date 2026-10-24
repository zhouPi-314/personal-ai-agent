"""侧车客户端：一次性调用 + 常驻 worker 两种模式。

- `call_worker`：拉起一次、做完就退。简单、无残留，适合低频或调试。
- `call_persistent`：同一脚本常驻，模型只加载一次；空闲超时自动退出。

为什么两种都要：常驻省掉 2–3 秒冷启动，但需要一个能管进程的薄封装；
如果常驻进程挂了，调用方会退回一次性模式，保证"慢一点但能出结果"。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("paa.media.worker")

DEFAULT_TIMEOUT = 90.0
DEFAULT_IDLE_TIMEOUT = 600.0


class WorkerError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code + ((": " + detail) if detail else ""))
        self.code = code
        self.detail = detail


def _child_env() -> dict[str, str]:
    # 子进程 stdout 被重定向时 Python 默认用系统代码页（中文 Windows 是 cp936），
    # 会把中文输出写成 GBK，主进程按 UTF-8 解就是乱码。必须强制 UTF-8。
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def call_worker(
    *,
    python_exe: Path,
    script: Path,
    payload: dict[str, object],
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, object]:
    """一次性侧车调用。"""
    if not python_exe.is_file():
        raise WorkerError("E_PYTHON_MISSING", str(python_exe))
    if not script.is_file():
        raise WorkerError("E_WORKER_MISSING", str(script))

    request = json.dumps(payload, ensure_ascii=False) + "\n"
    try:
        completed = subprocess.run(
            [str(python_exe), str(script)],
            input=request.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            check=False,
            env=_child_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerError("E_TIMEOUT", "侧车超时") from exc
    except OSError as exc:
        raise WorkerError("E_SPAWN_FAILED", str(exc)) from exc

    return _parse_stdout(completed.stdout, completed.stderr)


def _parse_stdout(stdout: bytes, stderr: bytes) -> dict[str, object]:
    return parse_line(
        stdout.decode("utf-8", errors="replace").strip(),
        fallback_detail=stderr.decode("utf-8", errors="replace")[-200:],
    )


def parse_line(text: str, *, fallback_detail: str = "") -> dict[str, object]:
    """从可能的噪音中挑出真正的响应行（从后往前找带 status 的 JSON 对象）。"""
    if not text.strip():
        raise WorkerError("E_EMPTY_OUTPUT", fallback_detail)
    for raw in reversed(text.splitlines()):
        candidate = raw.strip()
        if not candidate.startswith("{"):
            continue
        try:
            result = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(result, dict) or "status" not in result:
            continue
        if result["status"] != "ok":
            raise WorkerError(
                str(result.get("code") or "E_WORKER"),
                str(result.get("detail") or "")[:200],
            )
        return result
    raise WorkerError("E_BAD_OUTPUT", text[-200:] or fallback_detail)


@dataclass
class LineWorker:
    """一个常驻的 JSON-lines 子进程。线程安全。"""

    python_exe: Path
    script: Path
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT
    start_timeout: float = 60.0
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _lines: queue.Queue = field(default_factory=queue.Queue, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _last_used: float = 0.0
    calls: int = 0

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _expired(self) -> bool:
        return self.idle_timeout > 0 and (time.monotonic() - self._last_used) > self.idle_timeout

    def _spawn(self) -> None:
        self.close()
        try:
            self._proc = subprocess.Popen(
                [str(self.python_exe), str(self.script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=_child_env(),
            )
        except OSError as exc:
            self._proc = None
            raise WorkerError("E_SPAWN_FAILED", str(exc)) from exc

        self._lines = queue.Queue()

        def pump(stream) -> None:
            for line in stream:
                if not line.lstrip().startswith("{"):
                    logger.debug("侧车噪音：%s", line.rstrip()[:120])
                    continue
                self._lines.put(line)
            self._lines.put(None)

        threading.Thread(target=pump, args=(self._proc.stdout,), daemon=True).start()
        self._last_used = time.monotonic()

    def call(self, payload: dict[str, object], *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, object]:
        with self._lock:
            if not self.alive() or self._expired():
                self._spawn()
            assert self._proc is not None and self._proc.stdin is not None
            try:
                self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.close()
                raise WorkerError("E_PIPE_CLOSED", str(exc)) from exc

            self._last_used = time.monotonic()
            try:
                line = self._lines.get(timeout=max(1.0, timeout))
            except queue.Empty as exc:
                self.close()
                raise WorkerError("E_TIMEOUT", "侧车响应超时") from exc

            if line is None:
                self.close()
                raise WorkerError("E_WORKER_DIED", "侧车进程退出")

            self.calls += 1
            return parse_line(line)

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001 - 关闭失败不影响主流程
            try:
                proc.kill()
            except Exception as exc:  # noqa: BLE001
                logger.debug("侧车强杀失败：%s", exc)


_REGISTRY: dict[str, LineWorker] = {}
_REGISTRY_LOCK = threading.Lock()


def get_worker(python_exe: Path, script: Path, *, idle_timeout: float = DEFAULT_IDLE_TIMEOUT) -> LineWorker:
    key = str(Path(script).resolve())
    with _REGISTRY_LOCK:
        worker = _REGISTRY.get(key)
        if worker is None:
            worker = LineWorker(python_exe=python_exe, script=script, idle_timeout=idle_timeout)
            _REGISTRY[key] = worker
        return worker


def call_persistent(
    *,
    python_exe: Path,
    script: Path,
    payload: dict[str, object],
    timeout: float = DEFAULT_TIMEOUT,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
) -> dict[str, object]:
    """走常驻 worker；失败时清掉进程并退回一次性模式。"""
    if not python_exe.is_file():
        raise WorkerError("E_PYTHON_MISSING", str(python_exe))
    if not script.is_file():
        raise WorkerError("E_WORKER_MISSING", str(script))

    worker = get_worker(python_exe, script, idle_timeout=idle_timeout)
    try:
        return worker.call(payload, timeout=timeout)
    except WorkerError as exc:
        worker.close()
        if exc.code in {"E_WORKER", "E_BAD_REQUEST", "E_EMPTY_REQUEST"}:
            raise  # 业务错误，重试没意义
        # 进程级故障：退回一次性调用，至少给一次机会
        return call_worker(python_exe=python_exe, script=script, payload=payload, timeout=timeout)


def shutdown_workers() -> None:
    with _REGISTRY_LOCK:
        for worker in _REGISTRY.values():
            worker.close()
        _REGISTRY.clear()
