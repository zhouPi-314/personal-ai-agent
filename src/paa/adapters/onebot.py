"""OneBot v11 适配器：收事件、发消息。

只做翻译和传输，不判断"要不要回"——那是 `paa.chat.WakePolicy` 的事。
这样换平台（Telegram/微信）时，业务逻辑一行都不用改。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..media.contracts import MediaRef

MAX_SEGMENTS = 5
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024

# OneBot v11 转义规则；顺序不能变，& 必须最先替换。
_CQ_ESCAPES = (("&", "&amp;"), ("[", "&#91;"), ("]", "&#93;"), (",", "&#44;"))


@dataclass(frozen=True)
class InboundMessage:
    chat_key: str  # private:<uid> / group:<gid>
    text: str
    sender_id: str
    sender_name: str = ""
    is_group: bool = False
    is_at_me: bool = False
    is_poke: bool = False
    # 入站媒体：只描述位置，不下载、不校验（那是 media 层的事）
    media: tuple[MediaRef, ...] = ()


def _media_ref(segment: dict[str, Any]) -> MediaRef | None:
    """把 image/mface 段翻成 MediaRef；拿不到可定位的来源就放弃。"""
    kind = segment.get("type")
    if kind not in {"image", "mface", "record", "video"}:
        return None
    data = segment.get("data") or {}
    url = str(data.get("url") or "").strip()
    name = str(data.get("file") or "").strip()
    media_kind = {"image": "image", "mface": "sticker", "record": "audio", "video": "video"}[kind]

    if url.lower().startswith(("http://", "https://")):
        return MediaRef(kind=media_kind, source="url", locator=url, name=name)
    if name.lower().startswith("base64://"):
        return MediaRef(kind=media_kind, source="base64", locator=name[len("base64://") :], name=name)
    if name.lower().startswith("file://"):
        return MediaRef(kind=media_kind, source="file", locator=name[len("file://") :], name=name)
    if len(name) > 2 and name[1] == ":" and name[2] in "\\/":
        return MediaRef(kind=media_kind, source="file", locator=name, name=name)
    return None


def escape_cq(text: str) -> str:
    """把文本转义成"不会被网关当成 CQ 码"的形式。

    模型输出是不可信内容；不转义就等于让它可以构造 @全员、远程取图等指令。
    """
    out = str(text or "")
    for raw, encoded in _CQ_ESCAPES:
        out = out.replace(raw, encoded)
    return out


def image_segment(path: Path, *, max_bytes: int = MAX_IMAGE_BYTES) -> dict[str, Any]:
    """把本地图片变成 base64 段：不把本机绝对路径交给网关。"""
    data = Path(path).read_bytes()
    if len(data) > max_bytes:
        raise ValueError(f"图片超过 {max_bytes} 字节：{len(data)}")
    return {
        "type": "image",
        "data": {"file": "base64://" + base64.b64encode(data).decode("ascii")},
    }


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
        elif kind in {"face", "mface"}:
            parts.append("[表情]")
        elif kind == "record":
            parts.append("[语音]")
        elif kind == "video":
            parts.append("[视频]")
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

    media = tuple(
        ref
        for ref in (
            _media_ref(seg)
            for seg in (segments if isinstance(segments, list) else [])
            if isinstance(seg, dict)
        )
        if ref is not None
    )

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
        media=media,
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

    def _post(self, chat_key: str, message: object) -> None:
        kind, _, target = chat_key.partition(":")
        action = "send_private_msg" if kind == "private" else "send_group_msg"
        payload: dict[str, Any] = {"message": message}
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

    def send(self, chat_key: str, text: str) -> None:
        """发纯文本；文本一律先转义。"""
        self._post(chat_key, escape_cq(text))

    def send_segments(self, chat_key: str, segments: list[dict[str, Any]]) -> None:
        """发消息段数组；超过上限截断，不整条丢弃。"""
        if not segments:
            return
        self._post(chat_key, segments[:MAX_SEGMENTS])

    def send_image(self, chat_key: str, path: Path) -> None:
        """发一张本地图片。"""
        self.send_segments(chat_key, [image_segment(path)])

    def send_record(self, chat_key: str, path: Path, *, max_bytes: int = MAX_RECORD_BYTES) -> None:
        """发语音。传 WAV 即可，NapCat 会自行转码（真机验证过 QQ 能正常播放）。"""
        data = Path(path).read_bytes()
        if len(data) > max_bytes:
            raise ValueError(f"语音超过 {max_bytes} 字节：{len(data)}")
        payload = "base64://" + base64.b64encode(data).decode("ascii")
        self.send_segments(chat_key, [{"type": "record", "data": {"file": payload}}])
