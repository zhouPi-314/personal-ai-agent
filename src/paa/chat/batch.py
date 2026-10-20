"""消息合并：等人把话说完再回。

真人打字是一串一串的，逐条回复会得到"嗯""好""在的"三连。
"""

from __future__ import annotations

from .wake import ChatMessage


class MessageBatcher:
    def __init__(self, *, window_seconds: float, max_batch: int = 6) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds 必须为正")
        self.window_seconds = window_seconds
        self.max_batch = max(1, max_batch)
        self._items: list[ChatMessage] = []
        self._updated_at: float | None = None

    def add(self, message: ChatMessage, *, now: float) -> None:
        self._items.append(message)
        self._updated_at = now

    def is_due(self, *, now: float) -> bool:
        if not self._items:
            return False
        if len(self._items) >= self.max_batch:
            return True
        assert self._updated_at is not None
        return (now - self._updated_at) >= self.window_seconds

    def flush(self) -> list[ChatMessage]:
        items, self._items = self._items, []
        self._updated_at = None
        return items

    def __len__(self) -> int:
        return len(self._items)
