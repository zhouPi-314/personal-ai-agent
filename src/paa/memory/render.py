"""把记忆渲染成提示词片段。纯粹的表现层，不碰数据库。"""

from __future__ import annotations

from ..models import Memory

LABELS = {
    "trait": "性格习惯",
    "fact": "他说过的事",
    "topic": "聊过的话题",
    "pending": "没说出口的事",
}

MAX_PER_KIND = 5


def render_memories(rows: list[Memory]) -> str:
    if not rows:
        return ""

    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row.kind, []).append(row.content)

    lines = ["【关于这个人的记录】"]
    for kind, label in LABELS.items():
        items = grouped.get(kind, [])[:MAX_PER_KIND]
        if items:
            lines.append(f"- {label}：" + "；".join(items))
    return "\n".join(lines) if len(lines) > 1 else ""
