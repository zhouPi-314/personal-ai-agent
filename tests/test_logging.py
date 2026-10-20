import io
import json

from paa.logging import configure, get_logger


def test_logs_are_single_line_json():
    stream = io.StringIO()
    configure("INFO", stream=stream)

    get_logger("paa.test").info("任务开始", extra={"fields": {"task_id": "t1"}})

    payload = json.loads(stream.getvalue().strip())
    assert payload["msg"] == "任务开始"
    assert payload["task_id"] == "t1"
    assert payload["level"] == "INFO"


def test_level_filters_debug():
    stream = io.StringIO()
    configure("WARNING", stream=stream)

    get_logger("paa.test").debug("不该出现")

    assert stream.getvalue() == ""


def test_exception_is_captured():
    stream = io.StringIO()
    configure("INFO", stream=stream)

    try:
        raise ValueError("boom")
    except ValueError:
        get_logger("paa.test").exception("失败")

    payload = json.loads(stream.getvalue().strip())
    assert "ValueError" in payload["exc"]
