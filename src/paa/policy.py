"""权限判定：L1 只读 / L2 受限写入 / L3 需人工确认。

只做判断，不执行、不写库。调用方拿 Decision 去决定是否继续。
未知动作一律按 L3 处理——默认拒绝比默认放行安全。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

READ_ACTIONS = frozenset({"read", "list", "search", "status", "inspect", "recall"})
WRITE_ACTIONS = frozenset({"write", "edit", "move", "copy", "mkdir", "remember"})
DANGEROUS_ACTIONS = frozenset(
    {
        "delete",
        "execute",
        "shell",
        "sudo",
        "systemctl",
        "registry",
        "network",
        "install",
        "revoke",
    }
)


class Level(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass(frozen=True)
class Decision:
    level: Level
    allowed: bool
    needs_approval: bool
    reason: str


def classify(action: str) -> Decision:
    verb = (action or "").strip().lower()
    if verb in READ_ACTIONS:
        return Decision(Level.L1, True, False, "只读操作")
    if verb in WRITE_ACTIONS:
        return Decision(Level.L2, True, False, "写入操作，调用方须限定工作目录")
    if verb in DANGEROUS_ACTIONS:
        return Decision(Level.L3, False, True, "高危操作，需要人工确认")
    return Decision(Level.L3, False, True, "未知动作按最高权限处理")


# 媒体能力分级：(本机执行级别, 数据出境级别)。出境只会更严，不会更松。
MEDIA_ACTIONS: dict[str, tuple[Level, Level]] = {
    "select_sticker": (Level.L1, Level.L1),
    "analyze_sticker": (Level.L1, Level.L1),
    "analyze_image": (Level.L1, Level.L2),
    "recognize_audio": (Level.L2, Level.L3),
    "synthesize_speech": (Level.L2, Level.L3),
    "send_sticker": (Level.L2, Level.L2),
    "generate_music": (Level.L3, Level.L3),
}


def classify_media(capability: str, *, egress: bool = False) -> Decision:
    """媒体能力判定；未登记的能力沿用"未知动作按 L3"的默认拒绝。"""
    levels = MEDIA_ACTIONS.get((capability or "").strip().lower())
    if levels is None:
        return Decision(Level.L3, False, True, "未登记的媒体能力按最高权限处理")
    level = levels[1] if egress else levels[0]
    if level is Level.L3:
        return Decision(level, False, True, "媒体操作需要人工确认")
    return Decision(level, True, False, "媒体操作在授权范围内")
