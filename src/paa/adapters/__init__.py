"""入口适配器：把外部平台事件翻译成 PAA 内部格式。"""

from .onebot import InboundMessage, OneBotSender, parse_event

__all__ = ["InboundMessage", "OneBotSender", "parse_event"]
