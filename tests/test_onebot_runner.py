import pytest

from paa.adapters.onebot import InboundMessage
from paa.adapters.runner import OneBotRunner


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, chat_key, text):
        self.sent.append((chat_key, text))


def _runner(respond, sender=None):
    return OneBotRunner(
        ws_url="ws://127.0.0.1:3001",
        access_token="",
        self_id="100",
        sender=sender or FakeSender(),
        respond=respond,
    )


def _private_event(text="你好"):
    return {
        "post_type": "message",
        "message_type": "private",
        "self_id": 100,
        "user_id": 200,
        "message": [{"type": "text", "data": {"text": text}}],
    }


@pytest.mark.asyncio
async def test_private_message_triggers_reply():
    sender = FakeSender()
    seen = []

    async def respond(message: InboundMessage):
        seen.append(message.text)
        return "在的"

    result = await _runner(respond, sender).handle(_private_event(), now=0.0)

    assert result == "在的"
    assert sender.sent == [("private:200", "在的")]
    assert seen == ["你好"]


@pytest.mark.asyncio
async def test_group_message_without_mention_is_ignored():
    async def respond(message):  # pragma: no cover
        raise AssertionError("不应该回复")

    event = {
        "post_type": "message",
        "message_type": "group",
        "self_id": 100,
        "user_id": 200,
        "group_id": 300,
        "message": [{"type": "text", "data": {"text": "今天好热"}}],
    }

    assert await _runner(respond).handle(event, now=0.0) is None


@pytest.mark.asyncio
async def test_group_message_with_mention_triggers_reply():
    async def respond(message):
        return "怎么了"

    event = {
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

    assert await _runner(respond).handle(event, now=0.0) == "怎么了"


@pytest.mark.asyncio
async def test_empty_reply_sends_nothing():
    sender = FakeSender()

    async def respond(message):
        return None

    await _runner(respond, sender).handle(_private_event(), now=0.0)

    assert sender.sent == []


@pytest.mark.asyncio
async def test_heartbeat_is_ignored():
    async def respond(message):  # pragma: no cover
        raise AssertionError("不应该回复")

    assert await _runner(respond).handle({"post_type": "meta_event"}, now=0.0) is None
