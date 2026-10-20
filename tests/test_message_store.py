import uuid

from paa.chat.history import MessageStore
from paa.chat.session import ChatSession
from paa.llm import Completion, RoutedCompletion
from paa.persona import PersonaCard


class FakeMemory:
    def recall(self, user_id, **kwargs):
        return []

    def remember(self, *args, **kwargs):
        return None


class FakeRouter:
    def complete(self, messages, **kwargs):
        return RoutedCompletion(
            completion=Completion(text="嗯", model="m", input_tokens=7, output_tokens=2),
            provider="primary",
            fell_back=False,
        )


def test_append_turn_persists_both_sides(session, user):
    store = MessageStore(session)

    store.append_turn(
        user_id=user.id,
        user_text="今天好累",
        reply="那就早点睡",
        source="cli",
        provider="primary",
        input_tokens=7,
        output_tokens=2,
    )

    rows = store.recent(user.id)
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[1].provider == "primary"
    assert rows[1].input_tokens == 7


def test_recent_returns_chronological_and_limited(session, user):
    store = MessageStore(session)
    for index in range(3):
        store.append_turn(
            user_id=user.id,
            user_text=f"问{index}",
            reply=f"答{index}",
            source="cli",
            provider="primary",
            input_tokens=1,
            output_tokens=1,
        )

    rows = store.recent(user.id, limit=4)

    assert [r.content for r in rows] == ["问1", "答1", "问2", "答2"]


def test_chat_session_writes_through_store(session, user):
    store = MessageStore(session)
    chat = ChatSession(
        router=FakeRouter(),
        card=PersonaCard(name="t", text="你叫小满。"),
        user_id=user.id,
    )

    chat.ask("在吗", memory=FakeMemory(), store=store)

    rows = store.recent(user.id)
    assert [r.content for r in rows] == ["在吗", "嗯"]


def test_session_can_resume_from_history():
    chat = ChatSession(
        router=FakeRouter(),
        card=PersonaCard(name="t", text="你叫小满。"),
        user_id=uuid.uuid4(),
        history=[{"role": "user", "content": "上一句"}, {"role": "assistant", "content": "上一答"}],
    )

    assert chat.turns == 1
