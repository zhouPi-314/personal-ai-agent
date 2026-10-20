import httpx
import pytest

from paa.adapters.onebot import OneBotSender, parse_event


def test_private_message():
    msg = parse_event(
        {
            "post_type": "message",
            "message_type": "private",
            "self_id": 100,
            "user_id": 200,
            "sender": {"nickname": "小明"},
            "message": [{"type": "text", "data": {"text": "你好"}}],
        }
    )

    assert msg is not None
    assert msg.chat_key == "private:200"
    assert msg.text == "你好"
    assert not msg.is_group
    assert msg.sender_name == "小明"


def test_group_message_with_at_me():
    msg = parse_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 100,
            "user_id": 200,
            "group_id": 300,
            "message": [
                {"type": "at", "data": {"qq": 100}},
                {"type": "text", "data": {"text": " 在吗"}},
            ],
        }
    )

    assert msg is not None
    assert msg.chat_key == "group:300"
    assert msg.is_at_me
    assert "在吗" in msg.text


def test_poke_event():
    msg = parse_event(
        {"post_type": "notice", "sub_type": "poke", "user_id": 200, "group_id": 300}
    )

    assert msg is not None
    assert msg.is_poke
    assert msg.chat_key == "group:300"


def test_ignores_non_message_events():
    assert parse_event({"post_type": "meta_event", "meta_event_type": "heartbeat"}) is None


def test_placeholder_only_message_is_still_parsed():
    """表情消息保留为 [表情]，丢不丢由唤醒策略决定，解析层不替它做主。"""
    msg = parse_event(
        {
            "post_type": "message",
            "message_type": "private",
            "self_id": 1,
            "user_id": 2,
            "message": [{"type": "face", "data": {}}],
        }
    )

    assert msg is not None
    assert msg.text == "[表情]"


def test_empty_message_is_ignored():
    assert (
        parse_event(
            {
                "post_type": "message",
                "message_type": "private",
                "self_id": 1,
                "user_id": 2,
                "message": [],
            }
        )
        is None
    )


def _sender(handler) -> OneBotSender:
    return OneBotSender(
        http_url="http://127.0.0.1:3000",
        access_token="secret",
        transport=httpx.MockTransport(handler),
    )


def test_send_private_uses_correct_action():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"status": "ok"})

    _sender(handler).send("private:200", "晚安")

    assert captured["path"] == "/send_private_msg"
    assert captured["auth"] == "Bearer secret"
    assert '"user_id":200' in captured["body"].replace(" ", "")


def test_send_group_uses_group_action():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={"status": "ok"})

    _sender(handler).send("group:300", "在的")

    assert captured["path"] == "/send_group_msg"


def test_send_failure_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "failed"})

    with pytest.raises(RuntimeError):
        _sender(handler).send("private:1", "hi")
