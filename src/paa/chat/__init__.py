"""聊天通道的纯逻辑层：要不要回应、什么时候回应。"""

from .batch import MessageBatcher
from .humanize import HumanizeConfig, OutgoingPart, plan, split_text
from .wake import ChatMessage, WakePolicy, WakeResult

__all__ = [
    "ChatMessage",
    "HumanizeConfig",
    "MessageBatcher",
    "OutgoingPart",
    "WakePolicy",
    "WakeResult",
    "plan",
    "split_text",
]
