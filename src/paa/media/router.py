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

from .contracts import Capability, MediaRef, MediaResult, ResultStatus, StickerPick
from .fetcher import MediaFetchError, fetch
from .providers.sticker_local import LocalStickerProvider, intent_for
from .providers.vision_openai import OpenAIVisionProvider
from .stickers import StickerLibrary, StickerRateLimiter

log = logging.getLogger("paa.media.router")


def _denied(capability: Capability, reason: str) -> MediaResult:
    return MediaResult(
        status=ResultStatus.DENIED,
        capability=capability,
        error_code="E_CONSENT",
        error_detail=reason,
    )

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
    # 图片理解（M2）：默认关；egress_allow 为空表示任何图片都不外发
    vision_enabled: bool = False
    vision_model: str = ""
    asr_enabled: bool = False
    tts_enabled: bool = False
    egress_allow: frozenset[str] = frozenset()


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
        vision: OpenAIVisionProvider | None = None,
        asr: object | None = None,
        tts: object | None = None,
        tmp_dir: Path | None = None,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.settings = settings
        self.library = library
        self.vision = vision
        self.asr = asr
        self.tts = tts
        self.tmp_dir = tmp_dir
        self.max_bytes = max_bytes
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
        if capability is Capability.SELECT_STICKER:
            return self.settings.sticker_enabled
        if capability is Capability.ANALYZE_IMAGE:
            return self.settings.vision_enabled
        if capability is Capability.RECOGNIZE_AUDIO:
            return self.settings.asr_enabled
        if capability is Capability.SYNTHESIZE_SPEECH:
            return self.settings.tts_enabled
        return False

    # ── 语音合成（M3，本地执行、不出网）────────────────────────
    def synthesize_speech(
        self, text: str, *, chat_key: str, actor: str = ""
    ) -> MediaResult:
        if not self.settings.enabled or not self.settings.tts_enabled:
            return _denied(Capability.SYNTHESIZE_SPEECH, "tts_disabled")
        if self.tts is None or not getattr(self.tts, "available", lambda: False)():
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_MODEL_UNAVAILABLE",
            )
        if self.tmp_dir is None:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_CONFIG",
            )

        result: MediaResult
        try:
            result = self.tts.synthesize_speech(text, out_dir=self.tmp_dir)
        except Exception as exc:  # noqa: BLE001 - 合成失败要退回文字
            self._emit(actor=actor or chat_key, verdict="failed", detail=str(exc)[:120])
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_PROVIDER",
                error_detail=str(exc)[:120],
            )

        self._emit(
            actor=actor or chat_key,
            verdict="allowed" if result.status is ResultStatus.OK else "failed",
            detail="tts status=" + result.status.value + " code=" + result.error_code,
        )
        return result

    # ── 语音识别（M3，本地执行、不出网）────────────────────────
    def transcribe_audio(
        self,
        ref: MediaRef,
        *,
        chat_key: str,
        actor: str = "",
    ) -> MediaResult:
        if not self.settings.enabled or not self.settings.asr_enabled:
            return _denied(Capability.RECOGNIZE_AUDIO, "asr_disabled")
        if self.asr is None or not getattr(self.asr, "available", lambda: False)():
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.RECOGNIZE_AUDIO,
                error_code="E_MODEL_UNAVAILABLE",
            )
        if self.tmp_dir is None:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.RECOGNIZE_AUDIO,
                error_code="E_CONFIG",
            )

        item = None
        result: MediaResult
        try:
            item = fetch(
                ref, out_dir=self.tmp_dir, max_bytes=self.max_bytes, allow_audio=True
            )
            result = self.asr.recognize_audio(item)
        except MediaFetchError as exc:
            self._emit(actor=actor or chat_key, verdict="denied", detail=exc.code)
            return MediaResult(
                status=ResultStatus.REJECTED,
                capability=Capability.RECOGNIZE_AUDIO,
                error_code=exc.code,
                error_detail=exc.detail,
            )
        except Exception as exc:  # noqa: BLE001 - 转写失败不能影响聊天
            self._emit(actor=actor or chat_key, verdict="failed", detail=str(exc)[:120])
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.RECOGNIZE_AUDIO,
                error_code="E_PROVIDER",
                error_detail=str(exc)[:120],
            )
        finally:
            if item is not None:
                item.local_path.unlink(missing_ok=True)

        self._emit(
            actor=actor or chat_key,
            verdict="allowed" if result.status is ResultStatus.OK else "failed",
            sha256=getattr(item, "sha256", "") or "",
            detail="asr status=" + result.status.value + " code=" + result.error_code,
        )
        return result

    # ── 图片理解（M2）──────────────────────────────────────────
    def describe_image(
        self,
        ref: MediaRef,
        *,
        chat_key: str,
        actor: str = "",
        user_text: str = "",
    ) -> MediaResult:
        """拉图 → 视觉模型 → 结构化结果。任何失败都返回 MediaResult，不抛异常。"""
        if not self.settings.enabled or not self.settings.vision_enabled:
            return _denied(Capability.ANALYZE_IMAGE, "vision_disabled")
        if "image" not in self.settings.egress_allow:
            # 默认不外发：图片属于最敏感的一类媒体
            return _denied(Capability.ANALYZE_IMAGE, "egress_not_allowed")
        if self.vision is None or not self.vision.available():
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.ANALYZE_IMAGE,
                error_code="E_MODEL_UNAVAILABLE",
            )
        if self.tmp_dir is None:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.ANALYZE_IMAGE,
                error_code="E_CONFIG",
            )

        item = None
        result: MediaResult
        try:
            item = fetch(ref, out_dir=self.tmp_dir, max_bytes=self.max_bytes)
            result = self.vision.analyze_image(item, context_text=user_text)
        except MediaFetchError as exc:
            self._emit(actor=actor or chat_key, verdict="denied", detail=exc.code)
            return MediaResult(
                status=ResultStatus.REJECTED,
                capability=Capability.ANALYZE_IMAGE,
                error_code=exc.code,
                error_detail=exc.detail,
            )
        except Exception as exc:  # noqa: BLE001 - 识别失败不能影响聊天
            self._emit(actor=actor or chat_key, verdict="failed", detail=str(exc)[:120])
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.ANALYZE_IMAGE,
                error_code="E_PROVIDER",
                error_detail=str(exc)[:120],
            )
        finally:
            if item is not None:
                item.local_path.unlink(missing_ok=True)

        verdict = "allowed" if result.status is ResultStatus.OK else "failed"
        self._emit(
            actor=actor or chat_key,
            verdict=verdict,
            sha256=getattr(item, "sha256", "") or "",
            detail="vision status=" + result.status.value + " code=" + result.error_code,
        )
        return result

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
