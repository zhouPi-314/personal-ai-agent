"""连通性探测：NapCat / QQ / 本机 DSH / 云服务器 / 数据库。

每项都带超时，任何一项失败都不抛异常，只标记状态——面板要能显示"哪里坏了"。
"""

from __future__ import annotations

import socket
import time
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from .config import Settings
from .db import get_engine
from .runtime import STARTED_AT

TIMEOUT = 1.5


def _tcp(host: str, port: int, timeout: float = TIMEOUT) -> tuple[bool, float]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, round((time.perf_counter() - started) * 1000, 1)
    except OSError:
        return False, round((time.perf_counter() - started) * 1000, 1)


def _url_host_port(url: str) -> tuple[str, int] | None:
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _item(key: str, label: str, ok: bool | None, latency: float = 0.0, detail: str = "") -> dict:
    return {"key": key, "label": label, "ok": ok, "latency_ms": latency, "detail": detail}


def _check_db() -> dict:
    started = time.perf_counter()
    try:
        with get_engine().connect() as connection:
            connection.execute(text("select 1"))
        return _item("db", "数据库", True, round((time.perf_counter() - started) * 1000, 1))
    except Exception as exc:  # noqa: BLE001
        return _item("db", "数据库", False, detail=str(exc)[:120])


def _check_napcat(settings: Settings) -> dict:
    target = _url_host_port(settings.onebot_http_url)
    if target is None:
        return _item("napcat", "NapCat", None, detail="未配置")
    ok, latency = _tcp(*target)
    if not ok:
        return _item("napcat", "NapCat", False, latency, "端口不可达")
    return _item("napcat", "NapCat", True, latency, f"{target[0]}:{target[1]}")


def _check_qq(settings: Settings) -> dict:
    if not settings.onebot_http_url:
        return _item("qq", "QQ 账号", None, detail="未配置")
    started = time.perf_counter()
    try:
        response = httpx.post(
            settings.onebot_http_url.rstrip("/") + "/get_login_info",
            timeout=TIMEOUT,
            trust_env=False,
        )
        data = (response.json() or {}).get("data") or {}
        user_id = data.get("user_id")
        if user_id:
            return _item(
                "qq",
                "QQ 账号",
                True,
                round((time.perf_counter() - started) * 1000, 1),
                f"{user_id} {data.get('nickname', '')}".strip(),
            )
        return _item("qq", "QQ 账号", False, detail="未登录")
    except Exception as exc:  # noqa: BLE001
        return _item("qq", "QQ 账号", False, detail=str(exc)[:120])


def _check_dsh(settings: Settings) -> dict:
    target = _url_host_port(settings.local_base_url)
    if target is None:
        return _item("dsh", "本机 DSH", None, detail="未配置")
    ok, latency = _tcp(*target)
    return _item("dsh", "本机 DSH", ok, latency, "" if ok else "端口不可达")


# 云服务器检查（已停用，代码保留）：恢复时去掉每行开头的「# 」
# def _check_cloud(settings: Settings) -> dict:
#     remote = (settings.backup_remote or "").strip()
#     if not remote:
#         return _item("cloud", "云服务器", None, detail="未配置")
#     host = remote.split("@")[-1]
#     ok, latency = _tcp(host, 22)
#     return _item("cloud", "云服务器", ok, latency, "SSH 22" if ok else "端口不可达")


def check_all(settings: Settings) -> dict:
    items = [
        _item("paa", "PAA 服务", True, 0.0, f"运行 {int(time.time() - STARTED_AT)} 秒"),
        _check_db(),
        _check_napcat(settings),
        _check_qq(settings),
        _check_dsh(settings),
        # _check_cloud(settings),  # 云服务器已取消
    ]
    problem = any(item["ok"] is False for item in items)
    return {"status": "degraded" if problem else "ok", "items": items}
