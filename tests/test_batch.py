import pytest

from paa.chat import ChatMessage, MessageBatcher


def _msg(text: str) -> ChatMessage:
    return ChatMessage(text=text, sender_id="u1")


def test_not_due_before_window():
    batcher = MessageBatcher(window_seconds=2.0)
    batcher.add(_msg("在"), now=0.0)

    assert not batcher.is_due(now=1.9)
    assert batcher.is_due(now=2.0)


def test_new_message_restarts_window():
    batcher = MessageBatcher(window_seconds=2.0)
    batcher.add(_msg("在"), now=0.0)
    batcher.add(_msg("吗"), now=1.5)

    assert not batcher.is_due(now=2.0)
    assert batcher.is_due(now=3.5)


def test_max_batch_forces_flush():
    batcher = MessageBatcher(window_seconds=60.0, max_batch=2)
    batcher.add(_msg("a"), now=0.0)
    batcher.add(_msg("b"), now=0.1)

    assert batcher.is_due(now=0.2)


def test_flush_returns_in_order_and_clears():
    batcher = MessageBatcher(window_seconds=1.0)
    batcher.add(_msg("第一"), now=0.0)
    batcher.add(_msg("第二"), now=0.1)

    items = batcher.flush()

    assert [m.text for m in items] == ["第一", "第二"]
    assert len(batcher) == 0
    assert not batcher.is_due(now=99.0)


def test_rejects_non_positive_window():
    with pytest.raises(ValueError):
        MessageBatcher(window_seconds=0)
