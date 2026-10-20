"""唤醒策略：什么时候该说话，什么时候该安静。

只在纯逻辑层判定，不读配置、不碰网络。调用方负责把频道配置传进来。
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

# 中文里"像在提问"的粗略特征。宁可漏判也不误判：
# 误判会让它抢话，漏判只是少接一句。
QUESTION_HINTS = ("怎么", "为什么", "为啥", "如何", "是不是", "能不能", "可不可以", "有没有", "哪", "多少")
MIN_QUESTION_CHARS = 4


@dataclass(frozen=True)
class ChatMessage:
    text: str
    sender_id: str
    is_at_me: bool = False
    is_poke: bool = False


@dataclass(frozen=True)
class WakeResult:
    wake: bool
    reason: str = ""


@dataclass
class WakePolicy:
    """一个频道的策略。默认按"潜水"配置，需要主动说话时显式打开。"""

    mode: str = "diving"  # active | diving
    at_mention: bool = True
    name_mention: bool = True
    keywords: tuple[str, ...] = ()
    question: bool = True
    poke: bool = True
    owner_ids: frozenset[str] = frozenset()
    probability: float = 0.0
    cooldown_seconds: float = 300.0
    names: tuple[str, ...] = ()

    def should_wake(self, message: ChatMessage, *, now: float) -> WakeResult:
        text = message.text or ""
        sender = str(message.sender_id)

        # 被直接点名永远优先，不受冷却影响
        if message.is_at_me and self.at_mention:
            return WakeResult(True, "at_mention")
        if message.is_poke and self.poke:
            return WakeResult(True, "poke")
        if sender in self.owner_ids:
            return WakeResult(True, "owner")

        # 主动插话受冷却约束：刚说过话就别再凑热闹
        if self._cooling_down(now):
            return WakeResult(False, "")

        if self.mode == "active":
            return WakeResult(True, "active")

        if self.name_mention:
            for name in self.names:
                if name and name in text:
                    return WakeResult(True, f"name:{name}")

        for keyword in self.keywords:
            if keyword and keyword in text:
                return WakeResult(True, f"keyword:{keyword}")

        if self.question and self._looks_like_question(text):
            return WakeResult(True, "question")

        if self.probability > 0 and _jitter(message, now) < self.probability:
            return WakeResult(True, "probability")

        return WakeResult(False, "")

    def _cooling_down(self, now: float) -> bool:
        if self.cooldown_seconds <= 0:
            return False
        last = getattr(self, "last_wake_at", None)
        return last is not None and (now - last) < self.cooldown_seconds

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        stripped = text.strip()
        if len(stripped) < MIN_QUESTION_CHARS:
            return False
        if "?" in stripped or "？" in stripped:
            return True
        return any(hint in stripped for hint in QUESTION_HINTS)


def _jitter(message: ChatMessage, now: float) -> float:
    """确定性伪随机：同样的消息和时刻得到同样的结果，测试可复现。"""
    seed = f"{message.sender_id}|{message.text}|{int(now)}"
    return (zlib.crc32(seed.encode()) % 1000) / 1000
