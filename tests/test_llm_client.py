import httpx
import pytest

from paa.llm import ModelClient, ModelError


def _client(handler, *, api_key="test-key", max_attempts=3) -> ModelClient:
    return ModelClient(
        base_url="https://example.test/v1",
        api_key=api_key,
        model="test-model",
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
        max_attempts=max_attempts,
    )


_slept: list[float] = []


def _no_sleep(seconds: float) -> None:
    _slept.append(seconds)


def test_complete_returns_text_and_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": " 你好 "}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    result = _client(handler).complete([{"role": "user", "content": "hi"}])

    assert result.text == "你好"
    assert result.model == "test-model"
    assert (result.input_tokens, result.output_tokens) == (12, 3)


def test_request_shape_is_openai_compatible():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _client(handler).complete([{"role": "user", "content": "hi"}], temperature=0.3)

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key"
    assert '"temperature":0.3' in captured["body"].replace(" ", "")
    assert '"model":"test-model"' in captured["body"].replace(" ", "")


def test_upstream_error_raises_model_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    with pytest.raises(ModelError, match="429"):
        _client(handler, max_attempts=1).complete([{"role": "user", "content": "hi"}])


def test_malformed_response_raises_model_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(ModelError, match="响应结构"):
        _client(handler).complete([{"role": "user", "content": "hi"}])


def test_missing_api_key_fails_before_network():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("不应该发起请求")

    with pytest.raises(ModelError, match="PAA_MODEL_API_KEY"):
        _client(handler, api_key="").complete([{"role": "user", "content": "hi"}])


def test_loopback_ignores_system_proxy():
    local = ModelClient(base_url="http://127.0.0.1:18900/v1", api_key="k", model="m")
    remote = ModelClient(base_url="https://api.example.com/v1", api_key="k", model="m")

    assert local.trust_env is False
    assert remote.trust_env is True


def test_retryable_status_is_retried_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="upstream busy")
        return httpx.Response(200, json={"choices": [{"message": {"content": "好了"}}]})

    result = _client(handler).complete([{"role": "user", "content": "hi"}])

    assert result.text == "好了"
    assert calls["n"] == 2


def test_client_error_is_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    with pytest.raises(ModelError, match="400"):
        _client(handler).complete([{"role": "user", "content": "hi"}])

    assert calls["n"] == 1


def test_retry_gives_up_after_max_attempts():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    with pytest.raises(ModelError, match="500"):
        _client(handler).complete([{"role": "user", "content": "hi"}])

    assert calls["n"] == 3


def test_retry_after_header_is_honored():
    _slept.clear()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, text="slow down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _client(handler).complete([{"role": "user", "content": "hi"}])

    assert _slept == [2.0]


def test_network_error_is_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("timeout")

    with pytest.raises(ModelError, match="请求失败"):
        _client(handler).complete([{"role": "user", "content": "hi"}])

    assert calls["n"] == 3
