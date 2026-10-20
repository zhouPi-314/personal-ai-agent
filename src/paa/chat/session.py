"""一次对话回合：组装上下文 → 调模型 → 写回记忆。

这是唯一把「人格 / 记忆 / 模型 / 路由」串起来的地方，其余模块彼此不知道对方存在。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..llm import BrainRouter
from ..memory import MemoryService
from ..memory.render import render_memories
from ..persona import PersonaCard, build_system_prompt
from ..usage import UsageService
from .history import MessageStore

MAX_HISTORY = 20


@dataclass(frozen=True)
class TurnResult:
    reply: str
    provider: str
    input_tokens: int
    output_tokens: int


class ChatSession:
    def __init__(
        self,
        *,
        router: BrainRouter,
        memory: MemoryService | None = None,
        card: PersonaCard,
        user_id: uuid.UUID,
        situation: str = "你在和这个人一对一聊天。",
        store: MessageStore | None = None,
        usage: UsageService | None = None,
        source: str = "cli",
        history: list[dict[str, str]] | None = None,
    ) -> None:
        self.router = router
        self.memory = memory
        self.card = card
        self.user_id = user_id
        self.situation = situation
        self.store = store
        self.usage = usage
        self.source = source
        self._history: list[dict[str, str]] = list(history or [])

    @property
    def turns(self) -> int:
        return len(self._history) // 2

    def ask(
        self,
        text: str,
        *,
        memory: MemoryService | None = None,
        store: MessageStore | None = None,
        usage: UsageService | None = None,
    ) -> TurnResult:
        text = (text or "").strip()
        if not text:
            raise ValueError("消息不能为空")

        memory = memory or self.memory
        store = store or self.store
        usage = usage or self.usage
        if memory is None:
            raise ValueError("缺少 MemoryService")

        memories = memory.recall(self.user_id, limit=20)
        system = build_system_prompt(
            self.card,
            situation=self.situation,
            memory=render_memories(memories),
            recent=self._render_history(),
        )
        messages = [{"role": "system", "content": system}, *self._history]
        messages.append({"role": "user", "content": text})

        routed = self.router.complete(messages)
        reply = routed.completion.text
        if not reply:
            raise ValueError("模型返回了空回复")

        self._history.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply},
            ]
        )
        del self._history[:-MAX_HISTORY]

        memory.remember(self.user_id, "topic", f"{text[:40]} → {reply[:40]}")
        if store is not None:
            store.append_turn(
                user_id=self.user_id,
                user_text=text,
                reply=reply,
                source=self.source,
                provider=routed.provider,
                input_tokens=routed.completion.input_tokens,
                output_tokens=routed.completion.output_tokens,
            )
        if usage is not None:
            usage.record(
                user_id=self.user_id,
                source=self.source,
                provider=routed.provider,
                model=routed.completion.model,
                input_tokens=routed.completion.input_tokens,
                output_tokens=routed.completion.output_tokens,
            )

        return TurnResult(
            reply=reply,
            provider=routed.provider,
            input_tokens=routed.completion.input_tokens,
            output_tokens=routed.completion.output_tokens,
        )

    def _render_history(self) -> str:
        if not self._history:
            return ""
        lines = []
        for message in self._history:
            speaker = "他" if message["role"] == "user" else "你"
            lines.append(f"{speaker}：{message['content']}")
        return "【最近这段对话】\n" + "\n".join(lines)
