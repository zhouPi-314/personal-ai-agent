"""学习线的隔离区：把主人私聊里发来的图片攒起来，等人工晋级。

设计原则（对应 docs/multimodal/learning-line.md）：
1. 只收主人自己发的图；别人的一律不进。
2. 收进来不等于能用：先进隔离区，晋级要人点头（"先攒着，不学太快"）。
3. 标签先用"发送前那句话"猜，猜不到就留空，晋级时必须人工指定。
4. 全部落在 data/ 下，不进 Git；可随时按 sha256 删除。
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .contracts import MediaInput
from .providers.sticker_local import intent_for
from .stickers import IMAGE_SUFFIXES, StickerLibrary

MANIFEST = "manifest.json"
DEFAULT_DAILY_CAP = 10
DEFAULT_TOTAL_CAP = 200

log = logging.getLogger("paa.media.quarantine")

PENDING = "pending"
PROMOTED = "promoted"
REJECTED = "rejected"


@dataclass(frozen=True)
class PendingSticker:
    sha256: str
    file: str
    mime: str
    size_bytes: int
    tag_guess: str
    actor: str
    chat_key: str
    created_at: str
    status: str = PENDING


class Quarantine:
    """隔离区。文件与状态都放在一个目录里，便于整体备份或删除。"""

    def __init__(
        self,
        root: Path | str,
        *,
        daily_cap: int = DEFAULT_DAILY_CAP,
        total_cap: int = DEFAULT_TOTAL_CAP,
    ) -> None:
        self.root = Path(root)
        self.daily_cap = max(0, int(daily_cap))
        self.total_cap = max(0, int(total_cap))

    # ── 状态读写 ──────────────────────────────────────────────
    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST

    def _load(self) -> list[PendingSticker]:
        if not self.manifest_path.is_file():
            return []
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("隔离区清单无法解析：%s", exc)
            return []
        items = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return []
        result: list[PendingSticker] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                result.append(PendingSticker(**item))
            except TypeError:
                log.warning("跳过格式不认识的隔离项")
        return result

    def _save(self, items: list[PendingSticker]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "items": [asdict(item) for item in items]}
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)

    # ── 收录 ──────────────────────────────────────────────────
    def offer(
        self,
        item: MediaInput,
        *,
        actor: str,
        chat_key: str,
        context_text: str = "",
        now: datetime | None = None,
    ) -> tuple[str, str]:
        """收录一张图。返回 (状态, 原因)，不抛异常给调用方。"""
        moment = now or datetime.now()
        items = self._load()

        if any(entry.sha256 == item.sha256 for entry in items):
            return "duplicate", "already_seen"

        live = [entry for entry in items if entry.status != REJECTED]
        if self.total_cap and len(live) >= self.total_cap:
            return "cap", "total_cap"

        today = moment.strftime("%Y-%m-%d")
        today_count = sum(1 for entry in live if entry.created_at.startswith(today))
        if self.daily_cap and today_count >= self.daily_cap:
            return "cap", "daily_cap"

        suffix = item.local_path.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            return "reject", "unsupported_format"

        target = self.root / f"{item.sha256[:16]}{suffix}"
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.local_path, target)

        items.append(
            PendingSticker(
                sha256=item.sha256,
                file=target.name,
                mime=item.mime,
                size_bytes=item.size_bytes,
                tag_guess=intent_for(context_text) or "",
                actor=actor,
                chat_key=chat_key,
                created_at=moment.isoformat(timespec="seconds"),
                status=PENDING,
            )
        )
        self._save(items)
        return "pending", "ok"

    # ── 查看 ──────────────────────────────────────────────────
    def pending(self) -> tuple[PendingSticker, ...]:
        return tuple(entry for entry in self._load() if entry.status == PENDING)

    def all(self) -> tuple[PendingSticker, ...]:
        return tuple(self._load())

    def stats(self) -> dict[str, int]:
        items = self._load()
        return {
            "total": len(items),
            "pending": sum(1 for entry in items if entry.status == PENDING),
            "promoted": sum(1 for entry in items if entry.status == PROMOTED),
            "rejected": sum(1 for entry in items if entry.status == REJECTED),
        }

    # ── 晋级 / 拒绝 ───────────────────────────────────────────
    def promote(
        self,
        sha256: str,
        *,
        sticker_root: Path | str,
        tag: str = "",
        license_name: str = "owner-provided",
        captured_at: str = "",
    ) -> str:
        """把隔离项晋级进素材库。tag 为空时用收录时猜到的标签。"""
        items = self._load()
        entry = _find(items, sha256)
        if entry is None:
            raise KeyError(f"隔离区里没有 {sha256[:12]}")
        if entry.status != PENDING:
            raise ValueError(f"状态是 {entry.status}，不能重复晋级")

        final_tag = (tag or entry.tag_guess).strip()
        if not final_tag:
            raise ValueError("没有可用标签，请用 --tag 指定")

        source = self.root / entry.file
        if not source.is_file():
            raise FileNotFoundError(f"隔离文件丢失：{entry.file}")

        dest_dir = Path(sticker_root) / final_tag
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"learned_{entry.sha256[:8]}{source.suffix.lower()}"
        shutil.move(str(source), dest)

        StickerLibrary.add_entry(
            sticker_root,
            file_rel=f"{final_tag}/{dest.name}",
            tag=final_tag,
            sha256=entry.sha256,
            source_url=f"chat:{entry.chat_key}",
            license=license_name,
            captured_at=captured_at or entry.created_at,
        )

        items[items.index(entry)] = _with_status(entry, PROMOTED)
        self._save(items)
        return str(dest)

    def reject(self, sha256: str) -> bool:
        items = self._load()
        entry = _find(items, sha256)
        if entry is None or entry.status != PENDING:
            return False
        file_path = self.root / entry.file
        if file_path.is_file():
            file_path.unlink()
        items[items.index(entry)] = _with_status(entry, REJECTED)
        self._save(items)
        return True


def _find(items: list[PendingSticker], sha256: str) -> PendingSticker | None:
    target = (sha256 or "").strip().lower()
    for entry in items:
        if entry.sha256.startswith(target) and target:
            return entry
    return None


def _with_status(entry: PendingSticker, status: str) -> PendingSticker:
    data = asdict(entry)
    data["status"] = status
    return PendingSticker(**data)
