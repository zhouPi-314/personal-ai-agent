"""OneBot 接收循环：连网关、解析事件、按策略决定是否回复。

回复逻辑通过 `respond` 回调注入，所以这个类不知道模型、记忆、人格的存在——
换掉回调就能换掉整个"大脑"，而入口代码不动。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from ..chat.humanize import Outgoing, OutgoingMedia, OutgoingPart
from ..chat.wake import ChatMessage, WakePolicy
from .onebot import InboundMessage, OneBotSender, parse_event

Respond = Callable[[InboundMessage], Awaitable[list[Outgoing] | None]]


class OneBotRunner:
    def __init__(
        self,
        *,
        ws_url: str,
        access_token: str,
        self_id: str,
        sender: OneBotSender,
        respond: Respond,
        policies: dict[str, WakePolicy] | None = None,
        owner_ids: frozenset[str] = frozenset(),
        logger: logging.Logger | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.access_token = access_token
        self.self_id = self_id
        self.sender = sender
        self.respond = respond
        self.policies = policies or {}
        self.owner_ids = owner_ids
        self.log = logger or logging.getLogger("paa.onebot")

    def policy_for(self, chat_key: str) -> WakePolicy:
        if chat_key not in self.policies:
            # 私聊同样默认潜水：只有 owner_ids 里的号码能唤醒。
            # 否则陌生人私聊机器人就能白嫖模型、写记忆、消耗配额。
            self.policies[chat_key] = WakePolicy(mode="diving", owner_ids=self.owner_ids)
        return self.policies[chat_key]

    async def handle(self, payload: dict, *, now: float) -> str | None:
        message = parse_event(payload, self_id=self.self_id)
        if message is None:
            return None

        policy = self.policy_for(message.chat_key)
        verdict = policy.should_wake(
            ChatMessage(
                text=message.text,
                sender_id=message.sender_id,
                is_at_me=message.is_at_me,
                is_poke=message.is_poke,
            ),
            now=now,
        )
        if not verdict.wake:
            return None

        try:
            parts = await self.respond(message)
        except Exception as exc:  # noqa: BLE001 - 模型/数据库失败不能打断接收循环
            # 以前这里会把异常抛出去，导致每失败一条消息就重连一次 WS。
            self.log.warning("生成回复失败：%s", exc)
            return None
        if not parts:
            self.log.debug("决定不回复", extra={"fields": {"chat": message.chat_key}})
            return None

        for index, part in enumerate(parts):
            await self._deliver(message.chat_key, part)
            if index < len(parts) - 1 and part.pause_after > 0:
                await asyncio.sleep(part.pause_after)
        self.log.info(
            "已回复",
            extra={
                "fields": {
                    "chat": message.chat_key,
                    "parts": len(parts),
                    "chars": sum(len(p.text) for p in parts if isinstance(p, OutgoingPart)),
                }
            },
        )
        return "".join(part.text for part in parts if isinstance(part, OutgoingPart))

    async def _deliver(self, chat_key: str, part: Outgoing) -> None:
        """发一段。失败只降级，绝不把异常抛回接收循环（否则会触发整条重连）。"""
        try:
            if isinstance(part, OutgoingMedia):
                await asyncio.to_thread(self.sender.send_image, chat_key, part.path)
                return
            await asyncio.to_thread(self.sender.send, chat_key, part.text)
        except Exception as exc:  # noqa: BLE001 - 发送失败不能拖垮接收循环
            self.log.warning("发送失败：%s", exc)
            if isinstance(part, OutgoingPart):
                return  # 文字已经尽力，不再重试
            fallback = part.caption or "想给你发张图，没发出去"
            try:
                await asyncio.to_thread(self.sender.send, chat_key, fallback)
            except Exception as again:  # noqa: BLE001
                self.log.warning("降级发送也失败：%s", again)

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        backoff = 1.0
        while stop is None or not stop.is_set():
            try:
                # proxy=None：网关永远在回环，走系统代理只会拿到 502/握手失败
                async with websockets.connect(
                    self.ws_url, additional_headers=headers, proxy=None
                ) as ws:
                    backoff = 1.0
                    self.log.info("已连接 OneBot 网关")
                    async for raw in ws:
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await self.handle(payload, now=asyncio.get_running_loop().time())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 断线要重连而不是退出
                self.log.warning("网关连接中断：%s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
