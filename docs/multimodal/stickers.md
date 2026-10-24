# 表情包素材库（M1）

> 代码开源、素材私有：仓库里**没有任何图片**，素材只放 `data/stickers/`（已被 `.gitignore` 排除）。

## 1. 目录结构

```
data/stickers/
  index.json
  开心/  (jpg/png/gif/webp)
  委屈/
  得意/
  无语/
  生气/
  震惊/
  卖萌/
```

七个标签固定（与 `paa.media.stickers.TAGS` 一致）；不认识的标签目录一律跳过。

## 2. 索引格式

`index.json` 是唯一真相来源——**没有索引就没有素材库**，这是为了强制"版权可追踪"。

```json
{
  "version": 1,
  "entries": [
    {
      "file": "开心/a1b2c3.png",
      "tag": "开心",
      "sha256": "……（可省略，加载时现算）",
      "source_url": "https://example.invalid/pack",
      "license": "MIT",
      "captured_at": "2026-10-24"
    }
  ]
}
```

加载时逐条校验，任意一条不合格只跳过那一条：

| 校验 | 不合格时 |
|---|---|
| `tag` 属于七个标签 | 跳过 |
| `license` 非空 | 跳过（**没有许可就不入库**） |
| 路径不越出素材根目录 | 跳过（防路径穿越） |
| 扩展名是图片 | 跳过 |
| 文件存在 | 跳过 |
| ≤ 2MB | 跳过 |
| 同 `sha256` 只留一条 | 去重 |
| 最多 60 条 | 截断 |

## 3. 重建索引

把图片按标签放进目录后执行（`--license` 必填，不给许可就不生成索引）：

```powershell
.\.venv\Scripts\python.exe -m paa.media.stickers data/stickers --license MIT --source https://example.invalid/pack --captured-at 2026-10-24
```

## 4. 打开功能

```dotenv
PAA_MEDIA_ENABLED=true
PAA_MEDIA_STICKER_ENABLED=true
PAA_MEDIA_STICKER_DIR=data/stickers
PAA_MEDIA_STICKER_COOLDOWN_SEC=60
PAA_MEDIA_STICKER_DAILY_CAP=20
PAA_MEDIA_STICKER_RECENT=5
PAA_MEDIA_STICKER_PRIVATE_ONLY=true   # 先只私聊；群聊路径已实现但默认拒绝
```

默认全关；关着的时候连素材库都不加载。

## 5. 运行行为

1. 模型回复落库后，按关键词判断情绪标签（`INTENT_KEYWORDS`）。
2. 命中标签 → 查限频（每会话 60s 冷却 + 每日 20 张）→ 从该标签里挑一张**最近没发过**的。
3. 挑中则**先发图再发文字**；图片以 base64 发送，不把本机路径交给网关。
4. 发送失败自动降级为一句"想给你发张图，没发出去"，不影响文字回复，也不会让 WS 重连。
5. 每次**选择**写一条审计（`action=select_sticker`，`target=sha256 前 12 位`）；正文、路径、图片内容都不入库、不进日志。

## 6. 已知限制

- 情绪判定是关键词表，不是语义模型：宁可漏发，不会乱发。
- 只审计"选择"，未单独审计"投递成功"（`DEBT.md` D34）。
- 素材库为空时功能静默禁用，不报错、不阻塞聊天。
- 采集素材必须逐张记录来源与许可；无法证明许可的一律不入库（规范 §5.5）。

## 7. 当前素材库（2026-10-24）

| 项 | 值 |
|---|---|
| 来源 | Microsoft Fluent Emoji — https://github.com/microsoft/fluentui-emoji |
| 许可 | MIT（Copyright (c) Microsoft Corporation），逐张写入 `index.json` |
| 数量 | 39 张（开心 7 / 卖萌 6 / 委屈 6 / 得意 6 / 无语 5 / 生气 4 / 震惊 5） |
| 格式与体积 | 3D PNG，最大单张 52KB（上限 2MB） |
| 存放 | 仅本机 `data/stickers/`，**不在 Git 里**（`data/` 已忽略） |
| 采集方式 | 只取仓库原始 PNG，不做裁剪/改色；文件名改为 ASCII slug |

调整素材时：改目录 → 重跑第 3 步的索引命令即可；标签集合不变。