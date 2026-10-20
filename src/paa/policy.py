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
