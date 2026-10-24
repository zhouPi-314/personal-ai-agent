"""拟人化发送：只决定「分几条、每条打多久、间隔多少」，不碰内容。

所有随机量与当前小时由调用方传入，保证可复现、可测试。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MAX_CHARS = 40
MIN_MERGE_CHARS = 6
MAX_MERGED_CHARS = 24
SENTENCE_END = re.compile(r"(?<=[。！？!?…~])\s*")


@dataclass(frozen=True)
class HumanizeConfig:
    max_parts: int = 4
    ms_per_char: int = 85
    min_typing: float = 1.2
    max_typing: float = 6.0
    jitter: float = 0.2
    gap_range: tuple[float, float] = (0.7, 2.6)
    long_gap_chance: float = 0.25
    long_gap_range: tuple[float, float] = (3.0, 9.0)
    night_slowdown: float = 1.6
    night_hours: tuple[int, int] = (2, 7)


@dataclass(frozen=True)
class OutgoingPart:
    text: str
    typing_seconds: float
    pause_after: float = field(default=0.0)


@dataclass(frozen=True)
class OutgoingMedia:
    """一条要发出去的媒体。只描述，不读文件——发送由适配器负责。"""

    kind: str  # sticker / image / voice
    path: Path
    sha256: str = ""
    caption: str = ""
    typing_seconds: float = 0.0
    pause_after: float = 0.0


# 一条回复里可以混排文字与媒体；入口层按类型分发。
Outgoing = OutgoingPart | OutgoingMedia


DEFAULT_CONFIG = HumanizeConfig()


def split_text(
    text: str,
    *,
    max_parts: int = 4,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []

    chunks: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= max_chars:
            # 用户自己敲的换行是明确的停顿，不参与碎片合并
            chunks.append(line)
            continue
        sentences = [part.strip() for part in SENTENCE_END.split(line) if part.strip()]
        chunks.extend(_merge_short(sentences))

    if max_parts > 0 and len(chunks) > max_parts:
        chunks = chunks[: max_parts - 1] + ["".join(chunks[max_parts - 1 :])]
    return chunks


def _merge_short(sentences: list[str]) -> list[str]:
    """把被标点切得过碎的相邻碎片拼回去，避免出现"嗯。""好。"这种连发。"""
    merged: list[str] = []
    for sentence in sentences:
        previous = merged[-1] if merged else None
        if (
            previous
            and len(previous) < MIN_MERGE_CHARS
            and len(previous) + len(sentence) <= MAX_MERGED_CHARS
        ):
            merged[-1] = previous + sentence
        else:
            merged.append(sentence)
    return merged


def typing_seconds(
    text: str,
    *,
    hour: int,
    rng: random.Random,
    config: HumanizeConfig = DEFAULT_CONFIG,
) -> float:
    chars = len(text)
    seconds = config.min_typing + chars * config.ms_per_char / 1000
    seconds = max(config.min_typing, min(config.max_typing, seconds))
    seconds *= 1 + (rng.random() * 2 - 1) * config.jitter

    start, end = config.night_hours
    if start <= hour < end:
        seconds *= config.night_slowdown
    return round(max(0.1, seconds), 2)


def gap_seconds(*, rng: random.Random, config: HumanizeConfig = DEFAULT_CONFIG) -> float:
    low, high = config.gap_range
    seconds = low + rng.random() * max(0.0, high - low)
    if rng.random() < config.long_gap_chance:
        slow_low, slow_high = config.long_gap_range
        seconds += slow_low + rng.random() * max(0.0, slow_high - slow_low)
    return round(seconds, 2)


def plan(
    text: str,
    *,
    hour: int,
    rng: random.Random,
    config: HumanizeConfig = DEFAULT_CONFIG,
) -> list[OutgoingPart]:
    """把一段回复变成"分几条发、每条打多久、间隔多少"的计划。"""
    parts = split_text(text, max_parts=config.max_parts)
    result: list[OutgoingPart] = []
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        result.append(
            OutgoingPart(
                text=part,
                typing_seconds=typing_seconds(part, hour=hour, rng=rng, config=config),
                pause_after=0.0 if is_last else gap_seconds(rng=rng, config=config),
            )
        )
    return result


def plan_media(
    text: str,
    *,
    hour: int,
    rng: random.Random,
    media: OutgoingMedia | None = None,
    config: HumanizeConfig = DEFAULT_CONFIG,
) -> list[Outgoing]:
    """文字计划 + 可选的一条媒体；媒体排在最前面，像先甩张图再说话。"""
    parts: list[Outgoing] = list(plan(text, hour=hour, rng=rng, config=config))
    if media is None:
        return parts
    return [media, *parts]
