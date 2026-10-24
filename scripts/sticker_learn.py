"""学习线管理：查看隔离区、晋级、拒绝（人工确认，不自动入库）。

用法：
    python scripts\\sticker_learn.py stats
    python scripts\\sticker_learn.py list
    python scripts\\sticker_learn.py promote <sha前几位> [--tag 开心]
    python scripts\\sticker_learn.py reject <sha前几位>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from paa.config import PROJECT_ROOT, get_settings
from paa.media.quarantine import Quarantine


def _quarantine(settings, root: Path) -> Quarantine:
    return Quarantine(
        root,
        daily_cap=settings.media_learn_daily_cap,
        total_cap=settings.media_learn_total_cap,
    )


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    quarantine_root = PROJECT_ROOT / settings.media_quarantine_dir
    sticker_root = PROJECT_ROOT / settings.media_sticker_dir
    store = _quarantine(settings, quarantine_root)

    parser = argparse.ArgumentParser(description="学习线隔离区管理")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats", help="统计")
    sub.add_parser("list", help="列出待确认条目")
    promote = sub.add_parser("promote", help="晋级进素材库")
    promote.add_argument("sha", help="sha256 前缀")
    promote.add_argument("--tag", default="", help="标签；不填则用收录时猜到的")
    reject = sub.add_parser("reject", help="丢弃")
    reject.add_argument("sha", help="sha256 前缀")
    args = parser.parse_args(argv)

    if args.cmd == "stats":
        for key, value in store.stats().items():
            print(f"{key}: {value}")
        return 0

    if args.cmd == "list":
        pending = store.pending()
        if not pending:
            print("隔离区是空的")
            return 0
        print(f"待确认 {len(pending)} 条：")
        for item in pending:
            guess = item.tag_guess or "-"
            print(
                f"  {item.sha256[:8]}  {item.size_bytes // 1024}KB  "
                f"猜测标签={guess}  {item.created_at}"
            )
        print("晋级：promote <sha> --tag 开心    丢弃：reject <sha>")
        return 0

    if args.cmd == "promote":
        try:
            dest = store.promote(args.sha, sticker_root=sticker_root, tag=args.tag)
        except (KeyError, ValueError, FileNotFoundError) as exc:
            print(f"晋级失败：{exc}")
            return 1
        print(f"已晋级：{Path(dest).name}")
        return 0

    if args.cmd == "reject":
        print("已丢弃" if store.reject(args.sha) else "没有这条待确认记录")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
