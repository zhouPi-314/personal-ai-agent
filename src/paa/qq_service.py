"""把 QQ 入口接到对话链路上。

每个 chat_key 一个 ChatSession（保持上下文），每条消息一个数据库事务。
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime

from sqlalchemy import select

from .adapters.onebot import InboundMessage, OneBotSender
from .adapters.runner import OneBotRunner
from .audit import AuditService
from .chat.history import MessageStore
from .chat.humanize import Outgoing, OutgoingMedia, OutgoingPart, plan_media
from .chat.session import ChatSession
from .config import PROJECT_ROOT, Settings
from .db import session_scope
from .llm import BrainRouter
from .logging import get_logger
from .media.fetcher import fetch
from .media.quarantine import Quarantine
from .media.router import MediaRouter, MediaSettings
from .media.stickers import StickerLibrary
from .memory import MemoryService
from .models import User
from .persona import PersonaCard
from .usage import UsageService


def _user_for(db, display_name: str) -> User:
    user = db.scalars(select(User).where(User.display_name == display_name)).first()
    if user is None:
        user = User(display_name=display_name)
        db.add(user)
        db.flush()
    return user


class QqService:
    def __init__(
        self,
        *,
        settings: Settings,
        router: BrainRouter,
        card: PersonaCard,
    ) -> None:
        self.settings = settings
        self.router = router
        self.card = card
        self.sessions: dict[str, ChatSession] = {}
        self.sender = OneBotSender(
            http_url=settings.onebot_http_url,
            access_token=settings.onebot_access_token,
        )
        self.runner = OneBotRunner(
            ws_url=settings.onebot_ws_url,
            access_token=settings.onebot_access_token,
            self_id=settings.onebot_self_id,
            sender=self.sender,
            respond=self.respond,
            owner_ids=frozenset({settings.owner_qq}) if settings.owner_qq else frozenset(),
        )
        self.media = MediaRouter(
            settings=MediaSettings(
                enabled=settings.media_enabled,
                sticker_enabled=settings.media_sticker_enabled,
                sticker_cooldown_sec=settings.media_sticker_cooldown_sec,
                sticker_daily_cap=settings.media_sticker_daily_cap,
                sticker_recent=settings.media_sticker_recent,
                sticker_private_only=settings.media_sticker_private_only,
            ),
            # 总开关关闭时连素材库都不读：默认配置下零磁盘 I/O
            library=(
                StickerLibrary.load(PROJECT_ROOT / settings.media_sticker_dir)
                if settings.media_enabled
                else StickerLibrary()
            ),
            audit=self._audit_media,
        )
        self.quarantine = Quarantine(
            PROJECT_ROOT / settings.media_quarantine_dir,
            daily_cap=settings.media_learn_daily_cap,
            total_cap=settings.media_learn_total_cap,
        )
        self._media_tmp = PROJECT_ROOT / "data" / "media" / "tmp"
        self._learn_tasks: set[asyncio.Task] = set()
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self.log = get_logger("paa.qq")
        self._quota_notice_day: str | None = None

    async def respond(self, message: InboundMessage) -> list[Outgoing] | None:
        self.log.info(
            "收到消息",
            extra={
                "fields": {
                    "chat": message.chat_key,
                    "from": message.sender_id,
                    "group": message.is_group,
                    "chars": len(message.text),
                }
            },
        )
        # 先收录媒体，再走模型：模型 404/超时都不能让学习线丢素材
        self._spawn_learn(message)

        session = self.sessions.get(message.chat_key)
        if session is None:
            user_id = await asyncio.to_thread(self._ensure_user, message.sender_id)
            session = ChatSession(
                router=self.router,
                card=self.card,
                user_id=user_id,
                source="qq",
                situation=(
                    "你在 QQ 群里。"
                    if message.is_group
                    else f"你在跟 {message.sender_name or '对方'} 私聊。"
                ),
            )
            self.sessions[message.chat_key] = session

        quota = self.settings.daily_token_quota
        if quota > 0:
            with session_scope() as db:
                remaining = UsageService(db).remaining(quota)
            if remaining == 0:
                today = datetime.now().strftime("%Y-%m-%d")
                if self._quota_notice_day == today:
                    return None
                self._quota_notice_day = today
                self.log.warning(
                    "用量配额已用尽",
                    extra={"fields": {"quota": quota, "chat": message.chat_key}},
                )
                return [OutgoingPart(text="今天聊得有点多了，我先歇会儿，明天再找你。")]

        def _run():
            with session_scope() as db:
                return session.ask(
                    message.text,
                    memory=MemoryService(db),
                    store=MessageStore(db),
                    usage=UsageService(db),
                )

        result = await asyncio.to_thread(_run)
        hour = datetime.now().hour
        decision = self.media.sticker_for(
            chat_key=message.chat_key,
            reply_text=result.reply,
            day=datetime.now().strftime("%Y-%m-%d"),
            actor=f"qq:{message.sender_id}",
            is_group=message.is_group,
        )
        media = None
        if decision.pick is not None:
            media = OutgoingMedia(
                kind="sticker",
                path=decision.pick.path,
                sha256=decision.pick.sha256,
            )
        parts = plan_media(result.reply, hour=hour, rng=random.Random(), media=media)
        self.log.info(
            "生成回复",
            extra={
                "fields": {
                    "chat": message.chat_key,
                    "provider": result.provider,
                    "in_tokens": result.input_tokens,
                    "out_tokens": result.output_tokens,
                    "parts": len(parts),
                    "sticker": decision.reason,
                }
            },
        )
        return parts

    # ── 学习线（M1.5）─────────────────────────────────────────
    def _should_learn(self, message: InboundMessage) -> bool:
        if not self.settings.media_learn_enabled or message.is_group:
            return False
        if not message.media:
            return False
        owner = self.settings.owner_qq
        if not owner or message.sender_id != owner:
            return False  # 只学主人自己发的
        return message.sender_id != self.settings.onebot_self_id

    def _spawn_learn(self, message: InboundMessage) -> None:
        """旁路收录，不阻塞回复；任何异常只记日志。"""
        if not self._should_learn(message):
            return
        task = asyncio.create_task(asyncio.to_thread(self._learn_sync, message))
        self._learn_tasks.add(task)
        task.add_done_callback(self._learn_tasks.discard)

    def _learn_sync(self, message: InboundMessage) -> None:
        from .media.fetcher import MediaFetchError

        for ref in message.media[:3]:
            item = None
            try:
                item = fetch(ref, out_dir=self._media_tmp)
                status, reason = self.quarantine.offer(
                    item,
                    actor=f"qq:{message.sender_id}",
                    chat_key=message.chat_key,
                    context_text=message.text,
                )
                self.log.info(
                    "学习线收录",
                    extra={
                        "fields": {
                            "chat": message.chat_key,
                            "mime": item.mime,
                            "bytes": item.size_bytes,
                            "status": status,
                            "reason": reason,
                            "tag_guess": "",
                        }
                    },
                )
            except MediaFetchError as exc:
                self.log.warning("学习线跳过：%s", exc.code)
            except Exception as exc:  # noqa: BLE001 - 学习失败不能影响聊天
                self.log.warning("学习线异常：%s", exc)
            finally:
                if item is not None:
                    item.local_path.unlink(missing_ok=True)

    def _audit_media(self, **payload: object) -> None:
        """媒体动作留痕。写库失败只告警：审计不能反向阻断聊天。"""
        try:
            with session_scope() as db:
                AuditService(db).record(**payload)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            self.log.warning("媒体审计写入失败：%s", exc)

    def _ensure_user(self, sender_id: str) -> uuid.UUID:
        with session_scope() as db:
            return _user_for(db, f"qq:{sender_id}").id

    def start(self) -> None:
        if not (self.settings.onebot_ws_url and self.settings.onebot_http_url):
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self.runner.run(stop=self._stop))

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # 主动取消，属于正常关闭路径
            except Exception as exc:  # noqa: BLE001 - 关闭阶段的异常不应阻止退出
                self.runner.log.warning("QQ 入口关闭异常：%s", exc)
        self.sender.close()
