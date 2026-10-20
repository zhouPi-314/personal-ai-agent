"""双通道模型路由：优先本地（免费），失败降级到云端（付费）。

降级带迟滞：连续失败到阈值才降级，恢复也要重新探活。
否则网络抖一下就来回切换，用户会看到两套语气交替出现。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .client import Completion, ModelClient, ModelError

# 这类错误说明是"我们发的东西不对"，换一条通道也一样失败，直接抛出。
NON_FALLBACK_STATUS = frozenset({400, 422})


@dataclass(frozen=True)
class RoutedCompletion:
    completion: Completion
    provider: str
    fell_back: bool


class BrainRouter:
    def __init__(
        self,
        *,
        primary: ModelClient,
        fallback: ModelClient,
        failure_threshold: int = 2,
        recovery_seconds: float = 60.0,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_seconds = recovery_seconds
        self._failures = 0
        self._demoted_at: float | None = None

    @property
    def primary_healthy(self) -> bool:
        return self._demoted_at is None

    def demote(self, *, now: float | None = None) -> None:
        """外部探测（如端口不可达）后直接降级，省掉一次必然失败的请求。"""
        self._demoted_at = time.monotonic() if now is None else now
        self._failures = 0

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 1.0,
        now: float | None = None,
    ) -> RoutedCompletion:
        moment = time.monotonic() if now is None else now

        if self._should_try_primary(moment):
            try:
                completion = self.primary.complete(messages, temperature=temperature)
            except ModelError as exc:
                if exc.status_code in NON_FALLBACK_STATUS:
                    raise
                self._record_failure(moment)
                return self._use_fallback(messages, temperature, moment)
            self._record_success()
            return RoutedCompletion(completion, "primary", False)

        return self._use_fallback(messages, temperature, moment)

    def _should_try_primary(self, now: float) -> bool:
        if self._demoted_at is None:
            return True
        return (now - self._demoted_at) >= self.recovery_seconds

    def _record_failure(self, now: float) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._demoted_at = now
            self._failures = 0

    def _record_success(self) -> None:
        self._failures = 0
        self._demoted_at = None

    def _use_fallback(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        now: float,
    ) -> RoutedCompletion:
        try:
            completion = self.fallback.complete(messages, temperature=temperature)
        except ModelError:
            # 两条都失败时按"已降级"处理，避免调用方以为还能继续用主通道
            self._demoted_at = now
            raise
        return RoutedCompletion(completion, "fallback", True)
