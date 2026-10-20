"""OneBot v11 适配器：收事件、发消息。

只做翻译和传输，不判断"要不要回"——那是 `paa.chat.WakePolicy` 的事。
这样换平台（Telegram/微信）时，业务逻辑一行都不用改。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class InboundMessage:
    chat_key: str  # private:<uid> / group:<gid>
    text: str
    sender_id: str
    sender_name: str = ""
    is_group: bool = False
    is_at_me: bool = False
    is_poke: bool = False


def _segments_to_text(segments: Any) -> str:
    if not isinstance(segments, list):
        return str(segments or "")
    parts: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        kind = segment.get("type")
        data = segment.get("data") or {}
        if kind == "text":
            parts.append(str(data.get("text") or ""))
        elif kind == "image":
            parts.append("[图片]")
        elif kind == "face":
            parts.append("[表情]")
        elif kind == "at":
            parts.append(f"@{data.get('qq')}")
    return "".join(parts).strip()


def parse_event(payload: dict[str, Any], *, self_id: str | None = None) -> InboundMessage | None:
    """把 OneBot 事件翻译成内部消息；无关事件返回 None。"""
    if not isinstance(payload, dict):
        return None

    post_type = payload.get("post_type")
    me = str(self_id or payload.get("self_id") or "")

    if post_type == "notice" and payload.get("sub_type") == "poke":
        user_id = str(payload.get("user_id") or "")
        group_id = payload.get("group_id")
        if group_id:
            chat_key = f"group:{group_id}"
            is_group = True
        else:
            chat_key = f"private:{user_id}"
            is_group = False
        return InboundMessage(
            chat_key=chat_key,
            text="",
            sender_id=user_id,
            is_group=is_group,
            is_poke=True,
        )

    if post_type != "message":
        return None

    message_type = payload.get("message_type")
    sender = payload.get("sender") or {}
    segments = payload.get("message")
    text = _segments_to_text(segments)
    user_id = str(payload.get("user_id") or "")

    is_at_me = any(
        isinstance(seg, dict)
        and seg.get("type") == "at"
        and str((seg.get("data") or {}).get("qq")) == me
        for seg in (segments if isinstance(segments, list) else [])
    )

    if message_type == "group":
        chat_key = f"group:{payload.get('group_id')}"
        is_group = True
    else:
        chat_key = f"private:{user_id}"
        is_group = False

    if not text and not is_at_me:
        return None

    return InboundMessage(
        chat_key=chat_key,
        text=text,
        sender_id=user_id,
        sender_name=str(sender.get("card") or sender.get("nickname") or ""),
        is_group=is_group,
        is_at_me=is_at_me,
    )


class OneBotSender:
    def __init__(
        self,
        *,
        http_url: str,
        access_token: str = "",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.http_url = http_url.rstrip("/")
        self.access_token = access_token
        self._transport = transport
        self.timeout = timeout
        self._client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                transport=self._transport,
                trust_env=False,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def send(self, chat_key: str, text: str) -> None:
        kind, _, target = chat_key.partition(":")
        action = "send_private_msg" if kind == "private" else "send_group_msg"
        payload = {"message": text}
        if kind == "private":
            payload["user_id"] = int(target)
        else:
            payload["group_id"] = int(target)

        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        response = self._http().post(
            f"{self.http_url}/{action}", json=payload, headers=headers
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") not in {None, "ok"}:
            raise RuntimeError(f"OneBot 发送失败：{body}")
