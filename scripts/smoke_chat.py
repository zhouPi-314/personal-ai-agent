"""链路烟雾测试：用本机 DSH 真实跑两轮对话。

前置：DeepSeek Harness 桌面端在运行（它会开一个本机 OpenAI 兼容端口）。
用法：.venv\\Scripts\\python.exe scripts\\smoke_chat.py
"""

import json
import os
from pathlib import Path

from sqlalchemy import select

from paa.chat.session import ChatSession
from paa.config import get_settings
from paa.db import session_scope
from paa.llm import BrainRouter, ModelClient
from paa.memory import MemoryService
from paa.models import User
from paa.persona import load_card

SETTINGS_FILE = Path(os.environ["USERPROFILE"]) / ".dsh" / "our-free-model" / "settings.json"


def build_local_client(model: str) -> ModelClient:
    config = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return ModelClient(
        base_url=f"http://127.0.0.1:{config['forward']['port']}/v1",
        api_key=config["forwardKey"],
        model=model,
    )


def main() -> None:
    settings = get_settings()
    client = build_local_client(os.environ.get("SMOKE_MODEL", "big-pickle"))
    router = BrainRouter(primary=client, fallback=client)
    card = load_card(settings.persona_path)

    with session_scope() as db:
        user = db.scalars(select(User).where(User.display_name == settings.user_name)).first()
        if user is None:
            user = User(display_name=settings.user_name)
            db.add(user)
            db.flush()

        session = ChatSession(router=router, memory=MemoryService(db), card=card, user_id=user.id)
        for text in ("今天好累", "你觉得我该早点睡吗"):
            result = session.ask(text)
            print(f"你> {text}")
            print(f"她> {result.reply}")
            print(f"   [{result.provider}] in={result.input_tokens} out={result.output_tokens}")


if __name__ == "__main__":
    main()
