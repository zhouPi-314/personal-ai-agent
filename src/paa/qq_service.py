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
from .chat.history import MessageStore
from .chat.humanize import OutgoingPart, plan
from .chat.session import ChatSession
from .config import Settings
from .db import session_scope
from .llm import BrainRouter
from .logging import get_logger
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
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self.log = get_logger("paa.qq")
        self._quota_notice_day: str | None = None

    async def respond(self, message: InboundMessage) -> list[OutgoingPart] | None:
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
        parts = plan(result.reply, hour=hour, rng=random.Random())
        self.log.info(
            "生成回复",
            extra={
                "fields": {
                    "chat": message.chat_key,
                    "provider": result.provider,
                    "in_tokens": result.input_tokens,
                    "out_tokens": result.output_tokens,
                    "parts": len(parts),
                }
            },
        )
        return parts

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
