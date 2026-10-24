"""媒体能力插件层。

分层：contracts（纯数据）→ stickers（素材库）→ providers（具体能力）→ router（门面）。
依赖只能向下；本包不 import tasks、llm、内存/数据库模块。

刻意不在包级 __init__ 里 import 子模块：
一是避免 python -m paa.media.stickers 触发 runpy 重复导入警告，
二是让调用方显式写出依赖（from paa.media.router import ...）。
"""

__all__: list[str] = []
