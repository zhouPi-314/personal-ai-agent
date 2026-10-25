"""HTTP 入口与常驻服务生命周期。

启动时做三件事：连数据库、回收上次遗留的 running 任务、探测主通道。
任何一件失败都不阻止进程启动——服务要能起来，/healthz 才说得清哪里坏了。
"""

from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from sqlalchemy import text

from . import __version__
from .api import router as api_router
from .config import PROJECT_ROOT, get_settings
from .db import get_engine, session_scope
from .llm.factory import build_router
from .logging import configure
from .media import janitor
from .persona import PersonaCard, load_default_card
from .qq_service import QqService
from .tasks.engine import TaskEngine


def _probe(url: str, timeout: float = 1.0) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


def _warmup_sync(settings) -> None:
    """启动后台预热：清临时文件 + 把 TTS 模型先拉起来，省掉第一条语音的 5 秒冷启动。"""
    from .media.tts_factory import build_tts

    janitor.sweep_quietly(PROJECT_ROOT / "data" / "media")
    if not settings.media_tts_enabled:
        return
    try:
        provider = build_tts(settings, PROJECT_ROOT)
        provider.synthesize_speech("嗯。", out_dir=PROJECT_ROOT / "data" / "media" / "tmp")
    except Exception as exc:  # noqa: BLE001 - 预热失败不影响服务
        logging.getLogger("paa.main").warning("TTS 预热失败：%s", exc)


async def _housekeeping(settings) -> None:
    """每小时清理一次媒体临时文件。"""
    while True:
        await asyncio.sleep(3600)
        await asyncio.to_thread(janitor.sweep_quietly, PROJECT_ROOT / "data" / "media")


def create_app(router=None) -> FastAPI:
    state: dict[str, object] = {
        "db_ok": False,
        "primary_ok": None,
        "recovered": 0,
        "router_ready": False,
        "qq_enabled": False,
    }

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        settings = get_settings()
        logger = configure(
            settings.log_level,
            log_file=str(PROJECT_ROOT / settings.log_file) if settings.log_file else None,
        )
        logger.info("服务启动", extra={"fields": {"version": __version__, "env": settings.env}})

        try:
            with get_engine().connect() as connection:
                connection.execute(text("select 1"))
            state["db_ok"] = True
            with session_scope() as db:
                state["recovered"] = TaskEngine(db).recover_interrupted()
        except Exception as exc:  # noqa: BLE001 - 启动失败要记录而不是崩溃
            logger.error("数据库不可用", extra={"fields": {"error": str(exc)}})

        if settings.local_base_url:
            reachable = _probe(settings.local_base_url)
            state["primary_ok"] = reachable
            if not reachable and router is not None:
                router.demote()
            logger.info("主通道探测", extra={"fields": {"reachable": reachable}})

        card: PersonaCard | None = None
        try:
            card = load_default_card()
        except Exception:  # noqa: BLE001 - 人格卡缺失不阻止服务启动
            card = None

        active_router = router
        if active_router is None:
            try:
                active_router = build_router(settings)
            except Exception as exc:  # noqa: BLE001
                logger.error("模型链路未就绪", extra={"fields": {"error": str(exc)}})
        state["router_ready"] = active_router is not None
        if active_router is not None:
            try:
                import json as _json

                mode_file = PROJECT_ROOT / "data" / "model_route.json"
                if mode_file.is_file():
                    saved = _json.loads(mode_file.read_text(encoding="utf-8")).get("mode")
                    if saved:
                        active_router.set_mode(str(saved))
            except Exception as exc:  # noqa: BLE001 - 读不到就用默认 auto
                logger.warning("读取模型路由设置失败：%s", exc)

        app.state.router = active_router
        asyncio.create_task(asyncio.to_thread(_warmup_sync, settings))
        asyncio.create_task(_housekeeping(settings))

        qq: QqService | None = None
        app.state.qq = None
        if active_router is not None and card is not None and settings.onebot_ws_url:
            qq = QqService(settings=settings, router=active_router, card=card)
            qq.start()
            app.state.qq = qq
            state["qq_enabled"] = True
            logger.info("QQ 入口已启动", extra={"fields": {"ws": settings.onebot_ws_url}})

        yield

        if qq is not None:
            await qq.stop()
        logger.info("服务关闭")

    app = FastAPI(title="PAA", version=__version__, lifespan=lifespan)
    app.state.health = state
    app.state.router_holder = {"router": None}
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    def ui() -> FileResponse:
        # 维护台会随代码更新，禁止浏览器缓存旧页面
        return FileResponse(
            PROJECT_ROOT / "static" / "index.html",
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/ui", include_in_schema=False)
    def ui_alias() -> FileResponse:
        return FileResponse(
            PROJECT_ROOT / "static" / "index.html",
            headers={"Cache-Control": "no-store, must-revalidate"},
        )
    app.include_router(api_router)

    @app.get("/healthz")
    def healthz(response: Response) -> dict[str, object]:
        healthy = bool(state["db_ok"])
        if not healthy:
            response.status_code = 503
        return {
            "status": "ok" if healthy else "degraded",
            "version": __version__,
            "env": get_settings().env,
            "db": state["db_ok"],
            "primary_reachable": state["primary_ok"],
            "recovered_tasks": state["recovered"],
            "router_ready": state["router_ready"],
            "qq_enabled": state["qq_enabled"],
        }

    return app


app = create_app()
