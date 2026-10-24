"""媒体拉取与隔离校验。

只做一件事：把 `MediaRef` 变成一个"可信的本地文件"，并把所有不信任的东西挡在门外：
协议白名单、私网/回环地址拦截、大小上限、真实 MIME 判定、随机文件名。

阶段 M1.5 只处理图片（学习线）；M2 会复用同一套校验。
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .contracts import MediaInput, MediaRef

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 5.0
ALLOWED_SCHEMES = frozenset({"http", "https"})

# 真实类型只看文件头，不信任扩展名与 Content-Type。
_MAGIC: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"RIFF", "image/webp", ".webp"),  # 仅当 RIFF....WEBP 时确认
)

_DATA_URI = re.compile(r"^base64://", re.IGNORECASE)


class MediaFetchError(ValueError):
    """拉取或校验失败；code 与设计文档的错误码对齐。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def sniff(data: bytes) -> tuple[str, str] | None:
    """返回 (mime, 后缀)；认不出就返回 None。"""
    for magic, mime, suffix in _MAGIC:
        if data.startswith(magic):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime, suffix
    return None


def _is_blocked(host: str) -> bool:
    """私网、回环、链路本地、保留地址一律拒绝（防 SSRF）。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise MediaFetchError("E_DNS", f"无法解析 {host}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            return True
    return False


def fetch(
    ref: MediaRef,
    *,
    out_dir: Path,
    max_bytes: int = MAX_BYTES,
    timeout: float = TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> MediaInput:
    """把 ref 落成 out_dir 下的随机文件名，并返回校验后的元数据。"""
    data = _read(ref, max_bytes=max_bytes, timeout=timeout, transport=transport)
    if len(data) > max_bytes:
        raise MediaFetchError("E_TOO_LARGE", f"{len(data)} > {max_bytes}")
    if not data:
        raise MediaFetchError("E_EMPTY", "空文件")

    kind = sniff(data)
    if kind is None:
        raise MediaFetchError("E_MIME_MISMATCH", "不是可识别的图片格式")
    mime, suffix = kind

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(data)

    return MediaInput(
        ref=ref,
        local_path=target,
        mime=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _read(
    ref: MediaRef,
    *,
    max_bytes: int,
    timeout: float,
    transport: httpx.BaseTransport | None = None,
) -> bytes:
    if ref.source == "base64":
        payload = _DATA_URI.sub("", ref.locator)
        try:
            return base64.b64decode(payload, validate=False)[: max_bytes + 1]
        except (ValueError, TypeError) as exc:
            raise MediaFetchError("E_DECODE_FAILED", "base64 解码失败") from exc

    if ref.source == "file":
        path = Path(ref.locator)
        if not path.is_file():
            raise MediaFetchError("E_NOT_FOUND", "文件不存在")
        if path.stat().st_size > max_bytes:
            raise MediaFetchError("E_TOO_LARGE", "文件超过上限")
        return path.read_bytes()

    if ref.source == "url":
        parsed = urlparse(ref.locator)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise MediaFetchError("E_SCHEME_NOT_ALLOWED", parsed.scheme)
        host = parsed.hostname or ""
        if not host:
            raise MediaFetchError("E_SCHEME_NOT_ALLOWED", "缺少主机名")
        if _is_blocked(host):
            raise MediaFetchError("E_PRIVATE_ADDRESS", host)

        chunks: list[bytes] = []
        total = 0
        with (
            httpx.Client(
                timeout=timeout, follow_redirects=False, trust_env=False, transport=transport
            ) as client,
            client.stream("GET", ref.locator) as response,
        ):
            if response.status_code >= 400:
                raise MediaFetchError("E_HTTP", str(response.status_code))
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise MediaFetchError("E_TOO_LARGE", f"> {max_bytes}")
                chunks.append(chunk)
        return b"".join(chunks)

    raise MediaFetchError("E_SCHEME_NOT_ALLOWED", f"未知来源 {ref.source}")
