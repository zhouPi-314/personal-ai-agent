"""本地表情包素材库：索引、校验、检索、去重、限频。

版权可追踪是硬要求：没有 index.json 就不算有素材库（不做目录裸扫），
每条素材必须带来源与许可，缺一条就跳过一条。
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

from .contracts import StickerPick

INDEX_NAME = "index.json"
TAGS = ("卖萌", "委屈", "开心", "得意", "无语", "生气", "震惊")
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
MAX_ENTRIES = 60
MAX_BYTES = 2 * 1024 * 1024

log = logging.getLogger("paa.media.stickers")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class StickerEntry:
    tag: str
    path: Path
    sha256: str
    size_bytes: int
    source_url: str
    license: str
    captured_at: str


class StickerLibrary:
    """只读素材库。加载时校验，运行期只做选择。"""

    def __init__(self, entries: tuple[StickerEntry, ...] = ()) -> None:
        self.entries = entries

    def __len__(self) -> int:
        return len(self.entries)

    def tags(self) -> tuple[str, ...]:
        return tuple(sorted({entry.tag for entry in self.entries}))

    def pick(
        self,
        tag: str,
        *,
        recent: tuple[str, ...] = (),
        rng: random.Random | None = None,
    ) -> StickerPick | None:
        """按标签挑一张；优先避开 recent 里的哈希。"""
        candidates = [entry for entry in self.entries if entry.tag == tag]
        if not candidates:
            return None
        fresh = [entry for entry in candidates if entry.sha256 not in recent]
        if not fresh:
            # 该标签下全部刚发过：本次不发，而不是无视去重
            return None
        chosen = (rng or random.Random()).choice(fresh)
        return StickerPick(
            tag=chosen.tag,
            path=chosen.path,
            sha256=chosen.sha256,
            size_bytes=chosen.size_bytes,
        )

    @classmethod
    def load(
        cls,
        root: Path | str,
        *,
        max_entries: int = MAX_ENTRIES,
        max_bytes: int = MAX_BYTES,
    ) -> StickerLibrary:
        base = Path(root).resolve()
        index_path = base / INDEX_NAME
        if not index_path.is_file():
            if base.is_dir():
                log.warning("素材库缺少 %s，按空库处理", INDEX_NAME)
            return cls()

        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("素材索引无法解析：%s", exc)
            return cls()

        raw_entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(raw_entries, list):
            log.warning("素材索引格式不对：缺少 entries")
            return cls()

        entries: list[StickerEntry] = []
        seen: set[str] = set()
        for raw in raw_entries:
            entry = _build_entry(raw, base, max_bytes=max_bytes)
            if entry is None:
                continue
            if entry.sha256 in seen:
                continue
            seen.add(entry.sha256)
            entries.append(entry)
            if len(entries) >= max_entries:
                break
        return cls(tuple(entries))

    @classmethod
    def add_entry(
        cls,
        root: Path | str,
        *,
        file_rel: str,
        tag: str,
        sha256: str,
        source_url: str,
        license: str,
        captured_at: str,
    ) -> bool:
        """向索引追加一条（学习线晋级用）。已存在同一哈希则不动。"""
        if not license.strip():
            raise ValueError("license 不能为空")
        base = Path(root).resolve()
        index_path = base / INDEX_NAME
        payload: dict[str, object] = {"version": 1, "entries": []}
        if index_path.is_file():
            try:
                loaded = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("entries"), list):
                    payload = loaded
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("索引无法解析，将重建：%s", exc)

        entries = list(payload["entries"])  # type: ignore[arg-type]
        if any(str(item.get("sha256") or "") == sha256 for item in entries if isinstance(item, dict)):
            return False

        entries.append(
            {
                "file": file_rel,
                "tag": tag,
                "sha256": sha256,
                "source_url": source_url,
                "license": license,
                "captured_at": captured_at,
            }
        )
        payload["entries"] = entries
        tmp = index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(index_path)
        return True

    @classmethod
    def rebuild_index(
        cls,
        root: Path | str,
        *,
        license: str,
        source_url: str,
        captured_at: str,
    ) -> int:
        """按目录扫描重建索引。许可是必填项，强制可追溯。"""
        if not license.strip():
            raise ValueError("license 不能为空：没有许可的素材不允许入库")
        base = Path(root).resolve()
        if not base.is_dir():
            raise ValueError(f"素材目录不存在：{base}")

        entries = []
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name == INDEX_NAME:
                continue
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if path.stat().st_size > MAX_BYTES:
                log.warning("跳过超大素材：%s", path.name)
                continue
            tag = path.parent.name
            if tag not in TAGS:
                log.warning("跳过未知标签的素材：%s", path.relative_to(base))
                continue
            entries.append(
                {
                    "file": path.relative_to(base).as_posix(),
                    "tag": tag,
                    "sha256": _sha256(path),
                    "source_url": source_url,
                    "license": license,
                    "captured_at": captured_at,
                }
            )

        payload = {"version": 1, "entries": entries}
        (base / INDEX_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return len(entries)


def _build_entry(raw: object, base: Path, *, max_bytes: int) -> StickerEntry | None:
    if not isinstance(raw, dict):
        return None
    rel = str(raw.get("file") or "").strip()
    tag = str(raw.get("tag") or "").strip()
    license_name = str(raw.get("license") or "").strip()
    if not rel or not tag or not license_name:
        log.warning("跳过缺字段的素材条目：%r", raw)
        return None
    if tag not in TAGS:
        log.warning("跳过未知标签：%s", tag)
        return None

    path = (base / rel).resolve()
    if not path.is_relative_to(base):
        log.warning("跳过越界素材路径：%s", rel)
        return None
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        log.warning("跳过非图片素材：%s", rel)
        return None
    if not path.is_file():
        log.warning("跳过不存在的素材：%s", rel)
        return None
    size = path.stat().st_size
    if size > max_bytes:
        log.warning("跳过超大素材：%s", rel)
        return None

    return StickerEntry(
        tag=tag,
        path=path,
        sha256=str(raw.get("sha256") or "").strip() or _sha256(path),
        size_bytes=size,
        source_url=str(raw.get("source_url") or "").strip(),
        license=license_name,
        captured_at=str(raw.get("captured_at") or "").strip(),
    )


class StickerRateLimiter:
    """按会话限频：冷却时间 + 每日上限。时间由调用方注入，便于测试。"""

    def __init__(self, *, cooldown_seconds: float = 60.0, daily_cap: int = 20) -> None:
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.daily_cap = max(0, int(daily_cap))
        self._last_at: dict[str, float] = {}
        self._day: dict[str, str] = {}
        self._count: dict[str, int] = {}

    def take(self, chat_key: str, *, now: float, day: str) -> tuple[bool, str]:
        """检查并占用一次配额。返回 (是否允许, 原因)。"""
        if self._day.get(chat_key) != day:
            self._day[chat_key] = day
            self._count[chat_key] = 0
        if self.daily_cap and self._count.get(chat_key, 0) >= self.daily_cap:
            return False, "daily_cap"

        last = self._last_at.get(chat_key)
        if last is not None and self.cooldown_seconds > 0 and (now - last) < self.cooldown_seconds:
            return False, "cooldown"

        self._last_at[chat_key] = now
        self._count[chat_key] = self._count.get(chat_key, 0) + 1
        return True, "ok"


if __name__ == "__main__":  # 素材整理用的小工具，不参与服务运行
    import argparse

    parser = argparse.ArgumentParser(description="重建表情包索引（必须声明许可）")
    parser.add_argument("root", help="素材根目录，例如 data/stickers")
    parser.add_argument("--license", required=True, help="素材许可，例如 CC0-1.0")
    parser.add_argument("--source", required=True, help="来源 URL 或说明")
    parser.add_argument("--captured-at", default="", help="采集日期 YYYY-MM-DD")
    args = parser.parse_args()
    count = StickerLibrary.rebuild_index(
        args.root,
        license=args.license,
        source_url=args.source,
        captured_at=args.captured_at,
    )
    print(f"已写入 {count} 条素材索引")
