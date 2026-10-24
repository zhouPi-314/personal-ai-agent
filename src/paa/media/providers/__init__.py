"""具体能力实现。每个 provider 只做一件事，通过 router 被调用。"""

from .sticker_local import LocalStickerProvider, intent_for

__all__ = ["LocalStickerProvider", "intent_for"]
