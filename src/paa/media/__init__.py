"""媒体能力插件层。

分层：contracts（纯数据）→ stickers（素材库）→ providers（具体能力）→ router（门面）。
依赖只能向下；本包不 import tasks、llm、内存/数据库模块。
"""

from .contracts import Capability, MediaResult, ResultStatus, StickerPick
from .router import MediaRouter, MediaSettings, StickerDecision
from .stickers import StickerLibrary, StickerRateLimiter

__all__ = [
    "Capability",
    "MediaResult",
    "MediaRouter",
    "MediaSettings",
    "ResultStatus",
    "StickerDecision",
    "StickerLibrary",
    "StickerPick",
    "StickerRateLimiter",
]
