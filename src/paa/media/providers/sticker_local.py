"""本地表情包选择：从素材库里按意图标签挑一张。

判断意图只用关键词表，不调模型——这样行为可复现、可单测，
也不会为了"发表情"再付一次模型调用。
"""

from __future__ import annotations

import random

from ..contracts import Capability, MediaResult, ResultStatus
from ..stickers import StickerLibrary

# 标签 -> 触发词。按"宁可漏判也不误判"的原则，词表只放明确情绪词。
INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "开心": ("哈哈", "开心", "高兴", "太好了", "嘿嘿", "笑死", "乐", "舒服"),
    "卖萌": ("撒娇", "嘿嘿嘿", "喵", "求求", "嘛", "呀", "啦"),
    "委屈": ("委屈", "难过", "不开心", "呜", "想哭", "算了"),
    "得意": ("哼", "厉害吧", "当然", "小意思", "那必须"),
    "无语": ("无语", "服了", "离谱", "真是", "……", "..."),
    "生气": ("生气", "气死", "讨厌", "过分", "烦"),
    "震惊": ("震惊", "真的假的", "居然", "没想到", "天啊", "卧槽"),
}


def intent_for(reply_text: str) -> str | None:
    """从一句回复里判断情绪标签；命中多个时取最先出现的那一类。"""
    text = (reply_text or "").strip()
    if not text:
        return None
    best: tuple[int, str] | None = None
    for tag, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            index = text.find(keyword)
            if index < 0:
                continue
            if best is None or index < best[0]:
                best = (index, tag)
            break
    return best[1] if best else None


class LocalStickerProvider:
    """本地素材库选择器；不联网、不解码图片。"""

    name = "local"

    def __init__(self, library: StickerLibrary, *, rng: random.Random | None = None) -> None:
        self.library = library
        self.rng = rng

    def available(self) -> bool:
        return len(self.library) > 0

    def select_sticker(
        self,
        *,
        intent: str,
        context_text: str = "",
        recent_sent: tuple[str, ...] = (),
        now: float = 0.0,
    ) -> MediaResult:
        pick = self.library.pick(intent, recent=recent_sent, rng=self.rng)
        if pick is None:
            return MediaResult(
                status=ResultStatus.REJECTED,
                capability=Capability.SELECT_STICKER,
                error_code="E_NO_CANDIDATE",
                error_detail=f"标签 {intent} 下没有可用素材（空库或全部刚发过）",
            )
        return MediaResult(
            status=ResultStatus.OK,
            capability=Capability.SELECT_STICKER,
            confidence=1.0,
            data={
                "tag": pick.tag,
                "path": str(pick.path),
                "sha256": pick.sha256,
                "size_bytes": pick.size_bytes,
            },
        )
