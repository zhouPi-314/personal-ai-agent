"""发消息的媒体能力与转义回归（审计 P-01、P-13）。"""

import base64
import json
import random
from pathlib import Path

import httpx
import pytest

from paa.adapters.onebot import (
    MAX_SEGMENTS,
    OneBotSender,
    escape_cq,
    image_segment,
)
from paa.adapters.runner import OneBotRunner
from paa.chat.humanize import OutgoingMedia, OutgoingPart, plan, plan_media


# ── CQ 转义 ────────────────────────────────────────────────────
def test_escape_cq_covers_all_four_chars():
    assert escape_cq("a&b[c]d,e") == "a&amp;b&#91;c&#93;d&#44;e"


def test_escape_cq_keeps_plain_text_untouched():
    assert escape_cq("今天天气不错") == "今天天气不错"


def test_escape_cq_neutralises_at_all():
    escaped = escape_cq("[CQ:at,qq=all]")
    assert "[CQ" not in escaped
    assert "&#91;" in escaped and "&#93;" in escaped


# ── 发送 ──────────────────────────────────────────────────────
def _sender(handler) -> OneBotSender:
    return OneBotSender(
        http_url="http://127.0.0.1:3000",
        access_token="secret",
        transport=httpx.MockTransport(handler),
    )


def _capture(status: str = "ok") -> tuple[dict, callable]:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"status": status})

    return captured, handler


def test_send_escapes_model_output():
    captured, handler = _capture()
    _sender(handler).send("private:1", "看图[CQ:at,qq=all]")
    assert captured["path"] == "/send_private_msg"
    assert "[CQ" not in captured["body"]
    assert "&#91;CQ:at&#44;qq=all&#93;" in captured["body"]


def test_send_segments_posts_array():
    captured, handler = _capture()
    _sender(handler).send_segments(
        "group:2", [{"type": "text", "data": {"text": "在的"}}]
    )
    assert captured["path"] == "/send_group_msg"
    assert json.loads(captured["body"])["message"] == [
        {"type": "text", "data": {"text": "在的"}}
    ]


def test_send_segments_truncates_instead_of_dropping():
    captured, handler = _capture()
    segments = [{"type": "text", "data": {"text": str(i)}} for i in range(10)]
    _sender(handler).send_segments("private:1", segments)
    assert len(json.loads(captured["body"])["message"]) == MAX_SEGMENTS


def test_send_segments_ignores_empty_list():
    captured, handler = _capture()
    _sender(handler).send_segments("private:1", [])
    assert captured == {}


def test_image_segment_uses_base64_not_local_path(tmp_path: Path):
    picture = tmp_path / "a.png"
    picture.write_bytes(b"PNG" + b"0" * 32)
    captured, handler = _capture()
    _sender(handler).send_image("private:1", picture)

    expected = base64.b64encode(picture.read_bytes()).decode("ascii")
    assert "base64://" + expected in captured["body"]
    assert str(tmp_path) not in captured["body"]


def test_image_segment_rejects_oversized_file(tmp_path: Path):
    picture = tmp_path / "big.jpg"
    picture.write_bytes(b"x" * 64)
    with pytest.raises(ValueError):
        image_segment(picture, max_bytes=8)


def test_send_failure_still_raises_for_callers():
    _, handler = _capture(status="failed")
    with pytest.raises(RuntimeError):
        _sender(handler).send("private:1", "hi")


# ── 发送计划 ──────────────────────────────────────────────────
def test_plan_media_puts_media_first_then_text():
    rng = random.Random(0)
    media = OutgoingMedia(kind="sticker", path=Path("a.jpg"), sha256="abc")
    parts = plan_media("在呢", hour=10, rng=rng, media=media)
    assert isinstance(parts[0], OutgoingMedia)
    assert [p.text for p in parts[1:] if isinstance(p, OutgoingPart)] == ["在呢"]


def test_plan_media_without_media_equals_plan():
    rng_a, rng_b = random.Random(7), random.Random(7)
    assert plan_media("在呢", hour=10, rng=rng_a) == plan("在呢", hour=10, rng=rng_b)


# ── 接收循环里的分发 ──────────────────────────────────────────
class _Sender:
    def __init__(self, *, fail_image: bool = False, fail_text: bool = False) -> None:
        self.texts: list[tuple[str, str]] = []
        self.images: list[tuple[str, str]] = []
        self.fail_image = fail_image
        self.fail_text = fail_text

    def send(self, chat_key: str, text: str) -> None:
        if self.fail_text:
            raise RuntimeError("网关拒绝")
        self.texts.append((chat_key, text))

    def send_image(self, chat_key: str, path: Path) -> None:
        if self.fail_image:
            raise RuntimeError("图片太大")
        self.images.append((chat_key, str(path)))


def _event():
    return {
        "post_type": "message",
        "message_type": "private",
        "self_id": 100,
        "user_id": 200,
        "message": [{"type": "text", "data": {"text": "在吗"}}],
    }


def _runner(respond, sender, *, owner="200"):
    return OneBotRunner(
        ws_url="ws://127.0.0.1:3001",
        access_token="",
        self_id="100",
        sender=sender,
        respond=respond,
        owner_ids=frozenset({owner}),
    )


@pytest.mark.asyncio
async def test_runner_dispatches_media_to_send_image():
    sender = _Sender()

    async def respond(_message):
        return [
            OutgoingMedia(kind="sticker", path=Path("disguise.jpg")),
            OutgoingPart(text="在的", typing_seconds=1.0),
        ]

    await _runner(respond, sender).handle(_event(), now=0.0)

    assert sender.images == [("private:200", "disguise.jpg")]
    assert sender.texts == [("private:200", "在的")]


@pytest.mark.asyncio
async def test_runner_degrades_to_caption_when_image_fails():
    sender = _Sender(fail_image=True)

    async def respond(_message):
        return [OutgoingMedia(kind="sticker", path=Path("x.jpg"))]

    await _runner(respond, sender).handle(_event(), now=0.0)

    assert ("private:200", "想给你发张图，没发出去") in sender.texts


@pytest.mark.asyncio
async def test_runner_swallows_send_failure_instead_of_reconnecting():
    sender = _Sender(fail_text=True)

    async def respond(_message):
        return [OutgoingPart(text="在的", typing_seconds=1.0)]

    result = await _runner(respond, sender).handle(_event(), now=0.0)

    assert result == "在的"
    assert sender.texts == []
