import sys
import threading
import time

from paa.tasks.harness import _final_text, run_process


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_parses_ndjson_and_picks_final_text():
    code = (
        "import json,sys\n"
        "for e in [{'type':'text','text':'中间'},{'type':'final','text':'完成了'}]:\n"
        "    print(json.dumps(e, ensure_ascii=False), flush=True)\n"
    )

    result = run_process(_py(code), timeout=10)

    assert result.exit_code == 0
    assert result.final_text == "完成了"
    assert len(result.events) == 2
    assert result.ok


def test_ignores_non_json_lines():
    code = (
        "print('not json', flush=True)\n"
        "print('{\"type\":\"final\",\"text\":\"ok\"}', flush=True)\n"
    )

    result = run_process(_py(code), timeout=10)

    assert result.final_text == "ok"
    assert len(result.events) == 1


def test_nonzero_exit_is_not_ok():
    result = run_process(_py("import sys; sys.exit(3)"), timeout=10)

    assert result.exit_code == 3
    assert not result.ok


def test_timeout_kills_process():
    start = time.monotonic()

    result = run_process(_py("import time; time.sleep(30)"), timeout=1)

    assert result.timed_out
    assert time.monotonic() - start < 15


def test_cancel_event_terminates():
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()

    result = run_process(_py("import time; time.sleep(30)"), timeout=30, cancel_event=cancel)

    assert result.cancelled
    assert not result.timed_out


def test_on_event_callback_receives_events():
    seen = []
    code = "print('{\"type\":\"text\",\"text\":\"hi\"}', flush=True)\n"

    run_process(_py(code), timeout=10, on_event=seen.append)

    assert seen and seen[0]["type"] == "text"


def test_final_text_falls_back_to_last_text():
    events = [{"type": "text", "text": "第一"}, {"type": "text", "text": "最后"}]

    assert _final_text(events) == "最后"


def test_final_text_empty_when_no_events():
    assert _final_text([]) == ""


import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="GBK 控制台是 Windows 特有行为，Linux CI 上不适用")
def test_handles_gbk_output_from_child():
    code = "print('{\"type\":\"final\",\"text\":\"完成\"}', flush=True)\n"
    env = {"PYTHONIOENCODING": "gbk", "PATH": ""}
    import os

    full_env = os.environ.copy()
    full_env.update(env)

    result = run_process(_py(code), timeout=10, env=full_env)

    assert result.final_text == "完成"
