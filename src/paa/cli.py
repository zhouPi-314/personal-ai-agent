"""本地调试用的对话循环。

它存在的意义不是给用户聊天，而是让「人格 / 记忆 / 路由 / 格式」在一次真实
请求里同时跑起来，暴露接口层面的别扭之处。
"""

from __future__ import annotations

import argparse
import random
import socket
import sys
import time
from urllib.parse import urlparse

from sqlalchemy import select

from .chat import plan
from .chat.history import MessageStore
from .chat.session import ChatSession
from .config import get_settings
from .db import session_scope
from .llm import BrainRouter, ModelClient
from .memory import MemoryService
from .models import User
from .persona import load_default_card


def _probe(url: str, timeout: float = 1.0) -> bool:
    """只探端口，不调模型：判断本机通道是否在线的最便宜方式。"""
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _build_router() -> BrainRouter:
    settings = get_settings()
    primary = (
        ModelClient(
            base_url=settings.local_base_url,
            api_key=settings.local_api_key,
            model=settings.local_model or settings.model_name,
        )
        if settings.local_base_url
        else None
    )
    fallback = (
        ModelClient(
            base_url=settings.model_base_url,
            api_key=settings.model_api_key,
            model=settings.model_name,
        )
        if settings.model_base_url
        else None
    )

    if primary and fallback:
        return BrainRouter(primary=primary, fallback=fallback)
    if primary:
        # 只配了本机通道：单通道模式，主备指向同一端点
        return BrainRouter(primary=primary, fallback=primary)
    if fallback:
        return BrainRouter(primary=fallback, fallback=fallback)
    raise SystemExit("至少配置 PAA_LOCAL_BASE_URL 或 PAA_MODEL_BASE_URL 之一")


def _get_or_create_user(db, name: str) -> User:
    user = db.scalars(select(User).where(User.display_name == name)).first()
    if user is None:
        user = User(display_name=name)
        db.add(user)
        db.flush()
    return user


def _emit(reply: str, *, typing: bool) -> None:
    parts = plan(reply, hour=time.localtime().tm_hour, rng=random.Random())
    for index, part in enumerate(parts):
        if typing:
            time.sleep(min(part.typing_seconds, 3.0))
        print(f"她> {part.text}")
        if typing and part.pause_after:
            time.sleep(min(part.pause_after, 2.0))
        elif index < len(parts) - 1:
            print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PAA 本地调试对话")
    parser.add_argument("--typing", action="store_true", help="模拟打字节奏（默认瞬时输出）")
    args = parser.parse_args(argv)

    settings = get_settings()
    card = load_default_card()
    router = _build_router()

    if settings.local_base_url and not _probe(settings.local_base_url):
        router.demote()
        print(f"[预检] 本机通道不可达（{settings.local_base_url}），本次直接走备用通道")

    print(f"[启动] 人格={card.name} 用户={settings.user_name}")

    with session_scope() as db:
        user = _get_or_create_user(db, settings.user_name)
        user_id = user.id
        history = [
            {"role": m.role, "content": m.content}
            for m in MessageStore(db).recent(user_id, limit=20)
        ]

    chat = ChatSession(router=router, memory=None, card=card, user_id=user_id, history=history)
    if history:
        print(f"[续接] 已载入 {len(history) // 2} 轮历史")
    print("输入内容开始对话，/exit 退出。\n")

    total_in = 0
    total_out = 0
    providers: dict[str, int] = {}
    turns = 0

    while True:
        try:
            text = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text in {"/exit", "/quit"}:
            break
        if not text:
            continue

        try:
            with session_scope() as db:
                result = chat.ask(
                    text,
                    memory=MemoryService(db),
                    store=MessageStore(db),
                )
        except Exception as exc:  # noqa: BLE001 - 调试用的顶层兜底
            print(f"[出错] {exc}")
            continue

        _emit(result.reply, typing=args.typing)
        total_in += result.input_tokens
        total_out += result.output_tokens
        providers[result.provider] = providers.get(result.provider, 0) + 1
        turns += 1
        print()

    print(
        f"[结束] 轮次={turns} 输入token={total_in} 输出token={total_out} "
        f"路由={providers or '无'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
