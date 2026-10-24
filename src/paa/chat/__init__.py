"""聊天通道的纯逻辑层：要不要回应、什么时候回应。"""

from .batch import MessageBatcher
from .humanize import (
    HumanizeConfig,
    Outgoing,
    OutgoingMedia,
    OutgoingPart,
    plan,
    plan_media,
    split_text,
)
from .wake import ChatMessage, WakePolicy, WakeResult

__all__ = [
    "ChatMessage",
    "HumanizeConfig",
    "MessageBatcher",
    "Outgoing",
    "OutgoingMedia",
    "OutgoingPart",
    "WakePolicy",
    "WakeResult",
    "plan",
    "plan_media",
    "split_text",
]
