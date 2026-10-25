"""媒体临时文件清理：按 TTL 删 data/media 下的中间产物。

规则：
- data/media/tmp        —— 中间文件（拉取的图、合成语音、生成音乐），默认 6 小时；
- data/media/music      —— 音乐成品，默认 24 小时（发送后就没必要留）；
- 只删这两个目录下的普通文件，不递归删除目录本身；
- 只删比 TTL 更旧的；正在写的文件（更新时间在 10 分钟内）一律跳过。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("paa.media.janitor")

DEFAULT_TMP_TTL_SECONDS = 6 * 3600
DEFAULT_MUSIC_TTL_SECONDS = 24 * 3600
MIN_AGE_GUARD = 600


@dataclass(frozen=True)
class CleanupReport:
    scanned: int
    removed: int
    freed_bytes: int


def sweep(
    media_root: Path | str,
    *,
    now: float | None = None,
    tmp_ttl: int = DEFAULT_TMP_TTL_SECONDS,
    music_ttl: int = DEFAULT_MUSIC_TTL_SECONDS,
) -> CleanupReport:
    root = Path(media_root)
    moment = time.time() if now is None else now
    targets = ((root / "tmp", tmp_ttl), (root / "music", music_ttl))

    scanned = removed = freed = 0
    for folder, ttl in targets:
        if not folder.is_dir():
            continue
        for entry in folder.rglob("*"):
            if not entry.is_file():
                continue
            scanned += 1
            try:
                stat = entry.stat()
            except OSError:
                continue
            age = moment - stat.st_mtime
            if age < max(MIN_AGE_GUARD, ttl):
                continue
            try:
                entry.unlink()
                removed += 1
                freed += stat.st_size
            except OSError as exc:
                log.warning("清理失败：%s（%s）", entry.name, exc)
    return CleanupReport(scanned=scanned, removed=removed, freed_bytes=freed)


def sweep_quietly(media_root: Path | str) -> CleanupReport:
    try:
        report = sweep(media_root)
        if report.removed:
            log.info(
                "已清理媒体临时文件",
                extra={"fields": {"removed": report.removed, "freed_mb": round(report.freed_bytes / 1024 / 1024, 1)}},
            )
        return report
    except Exception as exc:  # noqa: BLE001 - 清理失败不能影响主流程
        log.warning("清理异常：%s", exc)
        return CleanupReport(scanned=0, removed=0, freed_bytes=0)
