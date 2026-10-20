"""OpenAI 兼容客户端。

只做一件事：发一次对话请求、把结果标准化。任何供应商差异都应收敛在这里，
上层不感知 URL、鉴权头或响应结构。
"""

from __future__ import annotations

import ipaddress
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import urlparse

import httpx

from ..config import get_settings

DEFAULT_TIMEOUT = 60.0
MAX_ERROR_BODY = 200
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_BACKOFF_CAP = 8.0

# 只有这些状态码值得重试：限流、超时、上游抖动。
# 4xx 里的参数错误与鉴权失败重试多少次都一样，重试只会拖慢失败反馈。
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _is_loopback(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ModelError(RuntimeError):
    """模型调用失败：配置缺失、网络错误或上游非 2xx。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class ModelClient:
    # shortcut: 只实现非流式调用；接入 Web/QQ 的实时输出时再加 stream 分支。
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self._transport = transport
        self.max_attempts = max(1, max_attempts)
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._sleep = sleep
        self._client: httpx.Client | None = None
        # 回环地址绝不走系统代理：本机端口被代理转发会得到 502
        self.trust_env = not _is_loopback(self.base_url)

    @classmethod
    def from_settings(cls) -> ModelClient:
        settings = get_settings()
        return cls(
            base_url=settings.model_base_url,
            api_key=settings.model_api_key,
            model=settings.model_name,
        )

    # ── 连接复用 ────────────────────────────────────────────────
    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self._transport,
                trust_env=self.trust_env,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 1.0,
    ) -> Completion:
        if not self.api_key:
            raise ModelError("未配置 PAA_MODEL_API_KEY")
        if not self.base_url:
            raise ModelError("未配置 PAA_MODEL_BASE_URL")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        last_error: ModelError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._http().post("/chat/completions", json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = ModelError(f"请求失败：{exc}")
                if attempt == self.max_attempts:
                    raise last_error from exc
                self._sleep(self._delay(attempt))
                continue

            if response.status_code < 400:
                return self._parse(response)

            last_error = ModelError(
                f"模型返回 {response.status_code}：{response.text[:MAX_ERROR_BODY]}",
                status_code=response.status_code,
            )
            if response.status_code not in RETRYABLE_STATUS or attempt == self.max_attempts:
                raise last_error
            self._sleep(self._delay(attempt, response))

        raise last_error or ModelError("请求未执行")

    def _delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        """指数退避 + 抖动；上游给了 Retry-After 就听它的（有上限）。"""
        if response is not None:
            header = response.headers.get("retry-after")
            if header and header.strip().isdigit():
                return min(self.backoff_cap, float(header.strip()))
        base = self.backoff_base * (2 ** (attempt - 1))
        jitter = 0.5 + random.random() / 2
        return min(self.backoff_cap, base * jitter)

    def _parse(self, response: httpx.Response) -> Completion:
        try:
            data = response.json()
            message = data["choices"][0]["message"]
            text = str(message.get("content") or "").strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"响应结构不符合预期：{response.text[:MAX_ERROR_BODY]}") from exc

        usage = data.get("usage") or {}
        return Completion(
            text=text,
            model=str(data.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )
