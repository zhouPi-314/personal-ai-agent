"""Harness 适配器：把 dsh 子进程的 NDJSON 事件流变成结构化结果。

分两层：
- `run_process`：通用进程执行（超时、取消、事件回调），可用任意命令测试
- `HarnessRunner`：负责拼 dsh 命令行与运行环境
"""

from __future__ import annotations

import json
import locale
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 300.0
TERMINATE_GRACE = 5.0


def _decode(raw: bytes) -> str:
    """子进程编码不确定：优先 UTF-8，失败时回退到系统本地编码。"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors="replace")


@dataclass
class HarnessResult:
    exit_code: int | None
    final_text: str
    events: list[dict[str, Any]] = field(default_factory=list)
    timed_out: bool = False
    cancelled: bool = False
    stderr: str = ""
    dropped_events: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled


def run_process(
    argv: list[str] | str,
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    cancel_event: threading.Event | None = None,
    on_event=None,
    max_events: int | None = None,
) -> HarnessResult:
    use_shell = isinstance(argv, str)
    process = subprocess.Popen(
        argv,
        shell=use_shell,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    events: list[dict[str, Any]] = []
    stderr_chunks: list[str] = []
    dropped = 0

    def read_stdout() -> None:
        nonlocal dropped
        assert process.stdout is not None
        for raw in process.stdout:
            line = _decode(raw).strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if max_events is not None and len(events) >= max_events:
                dropped += 1
                continue
            events.append(event)
            if on_event is not None:
                on_event(event)

    def read_stderr() -> None:
        assert process.stderr is not None
        stderr_chunks.append(_decode(process.stderr.read()))

    readers = [
        threading.Thread(target=read_stdout, daemon=True),
        threading.Thread(target=read_stderr, daemon=True),
    ]
    for reader in readers:
        reader.start()

    timed_out = False
    cancelled = False
    try:
        deadline = threading.Event()
        waited = 0.0
        step = 0.1
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if waited >= timeout:
                timed_out = True
                break
            deadline.wait(step)
            waited += step
        if (timed_out or cancelled) and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=TERMINATE_GRACE)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        exit_code = process.wait()
    finally:
        for reader in readers:
            reader.join(timeout=5)

    return HarnessResult(
        exit_code=exit_code,
        final_text=_final_text(events),
        events=events,
        timed_out=timed_out,
        cancelled=cancelled,
        stderr="".join(stderr_chunks)[-2000:],
        dropped_events=dropped,
    )


def _final_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "final" and event.get("text"):
            return str(event["text"]).strip()
    for event in reversed(events):
        if event.get("type") == "text" and event.get("text"):
            return str(event["text"]).strip()
    return ""


class HarnessRunner:
    def __init__(
        self,
        *,
        dsh_path: str,
        profile: str,
        dsh_home: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.dsh_path = dsh_path
        self.profile = profile
        self.dsh_home = dsh_home
        self.timeout = timeout

    def build_argv(self, task_text: str) -> list[str]:
        base = [self.dsh_path, "--profile", self.profile, "--json", task_text]
        return base

    def build_command(self, task_text: str) -> list[str] | str:
        """Windows 的 .cmd 必须交给 shell，且带空格的路径要整体加引号。"""
        base = self.build_argv(task_text)
        if self.dsh_path.lower().endswith((".cmd", ".bat")):
            return subprocess.list2cmdline(base)
        return base

    def run(
        self,
        task_text: str,
        *,
        workspace: Path | str,
        cancel_event: threading.Event | None = None,
        on_event=None,
    ) -> HarnessResult:
        env = os.environ.copy()
        env["DSH_HOME"] = self.dsh_home
        env["DSH_TELEMETRY_DISABLED"] = "1"
        return run_process(
            self.build_command(task_text),
            cwd=workspace,
            env=env,
            timeout=self.timeout,
            cancel_event=cancel_event,
            on_event=on_event,
        )
