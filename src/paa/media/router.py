"""媒体能力门面：开关、权限、限频、去重、审计都收在这里。

对上层只暴露"要不要发表情、发哪张"，不暴露素材库与 provider 细节。
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .contracts import Capability, StickerPick
from .providers.sticker_local import LocalStickerProvider, intent_for
from .stickers import StickerLibrary, StickerRateLimiter

log = logging.getLogger("paa.media.router")

# 审计出口：媒体层不碰数据库，由入口层注入一个写库的闭包。
AuditSink = Callable[..., None]


@dataclass(frozen=True)
class MediaSettings:
    enabled: bool = False
    sticker_enabled: bool = False
    sticker_cooldown_sec: float = 60.0
    sticker_daily_cap: int = 20
    sticker_recent: int = 5
    sticker_private_only: bool = True


@dataclass(frozen=True)
class StickerDecision:
    """一次"要不要发表情"的决定；reason 用于日志与审计，不是给用户看的。"""

    pick: StickerPick | None
    reason: str
    tag: str = ""

    @property
    def ok(self) -> bool:
        return self.pick is not None


class MediaRouter:
    def __init__(
        self,
        *,
        settings: MediaSettings,
        library: StickerLibrary,
        provider: LocalStickerProvider | None = None,
        limiter: StickerRateLimiter | None = None,
        audit: AuditSink | None = None,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.settings = settings
        self.library = library
        self.provider = provider or LocalStickerProvider(library, rng=rng)
        self.limiter = limiter or StickerRateLimiter(
            cooldown_seconds=settings.sticker_cooldown_sec,
            daily_cap=settings.sticker_daily_cap,
        )
        self.audit = audit
        self.clock = clock
        self._recent: dict[str, deque[str]] = {}

    def enabled(self, capability: Capability) -> bool:
        if not self.settings.enabled:
            return False
        return capability is Capability.SELECT_STICKER and self.settings.sticker_enabled

    def sticker_for(
        self,
        *,
        chat_key: str,
        reply_text: str,
        day: str,
        actor: str = "",
        is_group: bool = False,
    ) -> StickerDecision:
        """决定是否随这条回复发一张表情包。任何异常都降级为"不发"。"""
        try:
            return self._sticker_for(
                chat_key=chat_key,
                reply_text=reply_text,
                day=day,
                actor=actor or chat_key,
                is_group=is_group,
            )
        except Exception as exc:  # noqa: BLE001 - 表情包发不出去不能影响聊天
            log.warning("表情包判定异常：%s", exc)
            self._emit(actor=chat_key, verdict="failed", detail=f"exception={exc}"[:200])
            return StickerDecision(None, "exception")

    def _sticker_for(
        self, *, chat_key: str, reply_text: str, day: str, actor: str, is_group: bool
    ) -> StickerDecision:
        if not self.settings.enabled:
            return StickerDecision(None, "media_disabled")
        if not self.settings.sticker_enabled:
            return StickerDecision(None, "sticker_disabled")
        if is_group and self.settings.sticker_private_only:
            # 群聊接口预留：素材、限频、去重都已就绪，只差这一个开关
            return StickerDecision(None, "group_disabled")
        if len(self.library) == 0:
            return StickerDecision(None, "empty_library")

        tag = intent_for(reply_text)
        if tag is None:
            return StickerDecision(None, "no_intent")

        allowed, why = self.limiter.take(chat_key, now=self.clock(), day=day)
        if not allowed:
            self._emit(actor=actor, verdict="denied", tag=tag, detail=f"rate_limit={why}")
            return StickerDecision(None, f"rate_limit:{why}", tag)

        result = self.provider.select_sticker(
            intent=tag,
            context_text=reply_text,
            recent_sent=self._recent_tuple(chat_key),
            now=self.clock(),
        )
        if result.status.value != "ok":
            self._emit(actor=actor, verdict="failed", tag=tag, detail=result.error_code)
            return StickerDecision(None, "no_candidate", tag)

        pick = StickerPick(
            tag=str(result.data["tag"]),
            path=Path(str(result.data["path"])),
            sha256=str(result.data["sha256"]),
            size_bytes=int(str(result.data["size_bytes"])),
        )
        self._remember(chat_key, pick.sha256)
        self._emit(actor=actor, verdict="allowed", tag=pick.tag, sha256=pick.sha256)
        return StickerDecision(pick, "ok", pick.tag)

    def _recent_tuple(self, chat_key: str) -> tuple[str, ...]:
        return tuple(self._recent.get(chat_key, ()))

    def _remember(self, chat_key: str, sha256: str) -> None:
        limit = max(1, self.settings.sticker_recent)
        bucket = self._recent.setdefault(chat_key, deque(maxlen=limit))
        bucket.append(sha256)

    def _emit(
        self,
        *,
        actor: str,
        verdict: str,
        tag: str = "",
        sha256: str = "",
        detail: str = "",
    ) -> None:
        if self.audit is None:
            return
        payload = (
            f"tag={tag} hash={sha256[:12]} {detail}".strip()
            if sha256
            else f"tag={tag} {detail}".strip()
        )
        try:
            self.audit(
                actor=actor,
                action=Capability.SELECT_STICKER.value,
                target=sha256[:12],
                verdict=verdict,
                detail=payload[:500],
            )
        except Exception as exc:  # noqa: BLE001 - 审计失败不能反向影响主流程
            log.warning("表情包审计写入失败：%s", exc)
