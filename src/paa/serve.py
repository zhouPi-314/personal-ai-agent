"""常驻服务入口：python -m paa.serve

绑定地址来自 PAA_HOST（常见是 Tailscale IP 或回环）。
如果该地址当前不可用（比如 Tailscale 掉线），自动退回 127.0.0.1 —— 
宁可维护台只能本机访问，也不要整个服务起不来。
"""

from __future__ import annotations

import socket

import uvicorn

from .config import get_settings
from .logging import get_logger

log = get_logger("paa.serve")


def can_bind(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
            return True
        except OSError:
            return False


def resolve_host(host: str, port: int) -> str:
    if can_bind(host, port):
        return host
    log.warning(
        "绑定地址不可用，退回回环",
        extra={"fields": {"want": host, "fallback": "127.0.0.1", "port": port}},
    )
    return "127.0.0.1"


def main() -> None:
    settings = get_settings()
    host = resolve_host(settings.host, settings.port)
    uvicorn.run("paa.main:app", host=host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
