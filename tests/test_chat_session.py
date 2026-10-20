import uuid

import pytest

from paa.chat.session import ChatSession
from paa.llm import Completion, RoutedCompletion
from paa.memory.render import render_memories
from paa.persona import PersonaCard


class FakeMemory:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.remembered = []

    def recall(self, user_id, **kwargs):
        return self.rows

    def remember(self, user_id, kind, content, **kwargs):
        self.remembered.append((kind, content))


class FakeRouter:
    def __init__(self, text="那就早点睡", provider="primary"):
        self.text = text
        self.provider = provider
        self.last_messages = None

    def complete(self, messages, **kwargs):
        self.last_messages = messages
        return RoutedCompletion(
            completion=Completion(text=self.text, model="m", input_tokens=10, output_tokens=5),
            provider=self.provider,
            fell_back=self.provider == "fallback",
        )


class FakeRow:
    def __init__(self, kind, content):
        self.kind = kind
        self.content = content


def _session(router=None, memory=None):
    return ChatSession(
        router=router or FakeRouter(),
        memory=memory or FakeMemory(),
        card=PersonaCard(name="t", text="你叫小满。"),
        user_id=uuid.uuid4(),
    )


def test_turn_returns_reply_and_usage():
    result = _session().ask("今天好累")

    assert result.reply == "那就早点睡"
    assert result.provider == "primary"
    assert (result.input_tokens, result.output_tokens) == (10, 5)


def test_system_prompt_includes_memory_and_persona():
    memory = FakeMemory([FakeRow("trait", "常熬夜")])
    router = FakeRouter()

    _session(router=router, memory=memory).ask("今天好累")

    system = router.last_messages[0]
    assert system["role"] == "system"
    assert "常熬夜" in system["content"]
    assert "你叫小满" in system["content"]


def test_history_is_carried_into_next_turn():
    router = FakeRouter()
    session = _session(router=router)

    session.ask("第一句")
    session.ask("第二句")

    roles = [m["role"] for m in router.last_messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert session.turns == 2


def test_turn_is_written_back_to_memory():
    memory = FakeMemory()

    _session(memory=memory).ask("今天好累")

    assert memory.remembered
    kind, content = memory.remembered[0]
    assert kind == "topic"
    assert "今天好累" in content


def test_empty_input_is_rejected():
    with pytest.raises(ValueError):
        _session().ask("   ")


def test_empty_reply_is_rejected():
    with pytest.raises(ValueError):
        _session(router=FakeRouter(text="")).ask("在吗")


def test_render_memories_groups_by_kind():
    rows = [FakeRow("trait", "常熬夜"), FakeRow("fact", "住在成都"), FakeRow("trait", "爱喝冰美式")]

    text = render_memories(rows)

    assert "性格习惯" in text
    assert "常熬夜" in text and "爱喝冰美式" in text
    assert "他说过的事" in text


def test_render_memories_empty_when_no_rows():
    assert render_memories([]) == ""
