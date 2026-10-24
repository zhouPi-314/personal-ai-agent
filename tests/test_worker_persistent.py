"""常驻侧车：进程复用、错误传播、超时回收。"""

import sys
from pathlib import Path

import pytest

from paa.media.worker_client import (
    WorkerError,
    call_persistent,
    shutdown_workers,
)

ECHO = (
    "import json, os, sys\n"
    "for line in sys.stdin:\n"
    "    req = json.loads(line)\n"
    "    if req.get('boom'):\n"
    "        print(json.dumps({'status': 'error', 'code': 'E_WORKER', 'detail': 'boom'}), flush=True)\n"
    "        continue\n"
    "    print(json.dumps({'status': 'ok', 'pid': os.getpid(), 'echo': req.get('x')}), flush=True)\n"
)


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "echo_worker.py"
    path.write_text(ECHO, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    shutdown_workers()


def test_persistent_worker_reuses_same_process(tmp_path: Path):
    script = _script(tmp_path)
    first = call_persistent(python_exe=Path(sys.executable), script=script, payload={"x": 1})
    second = call_persistent(python_exe=Path(sys.executable), script=script, payload={"x": 2})

    assert first["echo"] == 1 and second["echo"] == 2
    assert first["pid"] == second["pid"]  # 同一个进程，没有重复冷启动


def test_persistent_worker_surfaces_business_error(tmp_path: Path):
    script = _script(tmp_path)
    call_persistent(python_exe=Path(sys.executable), script=script, payload={"x": 1})
    with pytest.raises(WorkerError) as err:
        call_persistent(python_exe=Path(sys.executable), script=script, payload={"boom": True})
    assert err.value.code == "E_WORKER"


def test_persistent_worker_recovers_after_kill(tmp_path: Path):
    script = _script(tmp_path)
    first = call_persistent(python_exe=Path(sys.executable), script=script, payload={"x": 1})

    # 手工杀掉进程，下次调用应自动重启
    from paa.media import worker_client

    for worker in worker_client._REGISTRY.values():
        if worker._proc is not None:
            worker._proc.kill()
            worker._proc.wait(timeout=5)

    second = call_persistent(python_exe=Path(sys.executable), script=script, payload={"x": 2})
    assert second["echo"] == 2
    assert second["pid"] != first["pid"]


def test_persistent_worker_missing_script(tmp_path: Path):
    with pytest.raises(WorkerError) as err:
        call_persistent(
            python_exe=Path(sys.executable), script=tmp_path / "nope.py", payload={}
        )
    assert err.value.code == "E_WORKER_MISSING"
