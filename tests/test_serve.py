"""启动时的绑定兜底：Tailscale 掉线不能把整个服务拖死。"""

import socket

from paa.serve import can_bind, resolve_host


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_can_bind_free_port():
    assert can_bind("127.0.0.1", _free_port()) is True


def test_resolve_host_keeps_available_address():
    port = _free_port()
    assert resolve_host("127.0.0.1", port) == "127.0.0.1"


def test_resolve_host_falls_back_when_unavailable():
    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        # 端口已被占用 → 认为该地址不可绑，退回回环
        assert resolve_host("127.0.0.1", port) == "127.0.0.1"
        # 无法解析/无法绑定 → 退回回环（用文档域名，避免写死公网 IP）
        assert resolve_host("paa-invalid.invalid", port) == "127.0.0.1"
    finally:
        holder.close()
