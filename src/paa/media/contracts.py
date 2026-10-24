"""媒体能力的数据契约。

只放纯数据与枚举：不 import 本项目其他模块、不做 I/O。
这样 adapters 可以只依赖契约，而不依赖任何 provider 实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Capability(StrEnum):
    """能力名。名称即审计里的 action，改名视为破坏性变更。"""

    SELECT_STICKER = "select_sticker"
    ANALYZE_STICKER = "analyze_sticker"
    ANALYZE_IMAGE = "analyze_image"
    RECOGNIZE_AUDIO = "recognize_audio"
    SYNTHESIZE_SPEECH = "synthesize_speech"
    GENERATE_MUSIC = "generate_music"


class ResultStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    REJECTED = "rejected"
    DENIED = "denied"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ResourceUse:
    """一次能力的资源开销；没有measurement就留空，不猜。"""

    elapsed_ms: int
    vram_peak_mb: int | None = None


@dataclass(frozen=True)
class MediaResult:
    """能力调用的统一返回。永不包含原始媒体字节。"""

    status: ResultStatus
    capability: Capability
    text: str = ""
    data: dict[str, object] = field(default_factory=dict)
    confidence: float | None = None
    limitations: tuple[str, ...] = ()
    error_code: str = ""
    error_detail: str = ""
    resource: ResourceUse | None = None


@dataclass(frozen=True)
class MediaRef:
    """入站媒体的最小描述：只描述位置，不持有字节，也不可信。"""

    kind: str  # image / sticker
    source: str  # url / file / base64
    locator: str
    name: str = ""


@dataclass(frozen=True)
class MediaInput:
    """已通过校验、落在本地临时目录的媒体。"""

    ref: MediaRef
    local_path: Path
    mime: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class StickerPick:
    """一次表情包选择的结果：只描述，不持有字节。"""

    tag: str
    path: Path
    sha256: str
    size_bytes: int
