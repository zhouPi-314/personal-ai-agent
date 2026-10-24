"""表情包链路自检：默认离线；加 --send 才真的给主人私聊发一张图。

离线部分检查：素材库能否加载、标签分布、能否挑出一张。
发送部分需要 NapCat 在线且 QQ 已登录；本脚本不打印任何 QQ 号或令牌。
"""

from __future__ import annotations

import argparse
import sys

from paa.adapters.onebot import OneBotSender
from paa.config import PROJECT_ROOT, get_settings
from paa.media.stickers import StickerLibrary


def main() -> int:
    parser = argparse.ArgumentParser(description="表情包链路自检")
    parser.add_argument("--send", action="store_true", help="真的发一张给主人（需要 QQ 在线）")
    parser.add_argument("--tag", default="开心", help="要挑的标签，默认开心")
    args = parser.parse_args()

    settings = get_settings()
    library = StickerLibrary.load(PROJECT_ROOT / settings.media_sticker_dir)

    print(f"素材库：{len(library)} 张")
    if len(library) == 0:
        print(f"空库。检查 {settings.media_sticker_dir}/index.json 是否存在且带 license。")
        return 1

    for tag in library.tags():
        count = sum(1 for entry in library.entries if entry.tag == tag)
        print(f"  {tag}: {count}")

    pick = library.pick(args.tag)
    if pick is None:
        print(f"标签 {args.tag} 下没有可用素材")
        return 1
    print(f"选中：tag={pick.tag} sha256={pick.sha256[:12]} bytes={pick.size_bytes}")

    if not args.send:
        print("（离线自检完成；加 --send 才会真的发到 QQ）")
        return 0

    if not (settings.onebot_http_url and settings.owner_qq):
        print("缺少 PAA_ONEBOT_HTTP_URL 或 PAA_OWNER_QQ，无法发送")
        return 2

    sender = OneBotSender(
        http_url=settings.onebot_http_url,
        access_token=settings.onebot_access_token,
    )
    try:
        sender.send_image(f"private:{settings.owner_qq}", pick.path)
    except Exception as exc:  # noqa: BLE001 - 自检脚本要把失败原因打出来
        print(f"发送失败：{type(exc).__name__}: {exc}")
        return 3
    finally:
        sender.close()

    print("已发送，请在 QQ 里确认是否收到图片。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
