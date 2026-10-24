# 多模态扩展 · 阶段 B 设计（最小变更架构）

> 阶段：**B — 接口设计**（获批 A-01）｜日期：2026-10-24｜状态：草案，未实现任何代码
> 约束来源：《PAA × DSH 多模态插件扩展：开发设计与安全执行规范》＋《docs/audit-multimodal-phase-a.md》
> 本阶段只产出文档。**未安装依赖、未下载模型、未修改 src/ 实现、未触碰 .env。**

## 0. 阶段 B 的范围与不做的部分

| 做 | 不做 |
|---|---|
| 最小变更架构、模块登记、依赖方向 | 写任何 src/ 代码 |
| 6 个 Provider 接口契约 | 安装 pip 依赖 / 建 venv |
| 媒体权限分级与审计埋点 | 下载模型权重 |
| 资源调度（队列 / GPU 生命周期 / 熔断） | 接入真实 QQ 发图发语音 |
| 测试矩阵与用例清单（文档形态） | 直接新增 tests/ 下会失败的用例 |
| 目录、配置项、依赖预算、回滚方案 | 抓取任何素材 |

## 1. 决策记录（本轮已确认）

| 编号 | 决策 | 落地约束 |
|---|---|---|
| Q-01 | **REA 不装**；其他项目若要装与本项目无关，互不干涉 | 本项目内不留 REA 依赖、不写 REA 配置文件、不改任何 agent 全局配置 |
| Q-02 | Python 3.13 缺 ML 轮子时，允许**单建 3.11/3.12 venv** | 独立目录 `D:\项目设计\Personal AI Agent（PAA）\.venv-media`，不写系统 PATH、不改全局 Python、不碰 Conda、不影响其他项目的解释器 |
| Q-03 | 视觉**先走现有云端链路**（零新依赖），本地 VLM 只留接口 | M2 首个版本不下载任何视觉权重；云端外发必须有每类媒体的授权开关 |
| Q-04 | 允许 GPU 常驻，但**空闲必须卸载**、不得无故占资源 | 不随 PAA 启动预加载；空闲 300s 卸载；同时只驻留 1 个 GPU 模型；进程优先级低于正常；有硬性 VRAM 上限 |
| Q-05 | 媒体保留期按推荐值 | 原始入站 60 分钟；派生产物（缩略图/转写）24 小时；长期库只存 sha256 + 摘要 + 授权元数据 |
| Q-06 | 表情包素材**自行小量采集、新小而精** | 只从**明确可自由使用**的来源采集（CC0 / 公共领域 / 自制），逐张记录来源与许可；总量上限 60 张、单张 ≤ 2MB；素材只落 `data/`（已被 .gitignore 排除），**不进仓库** |
| Q-07 | 允许更新 `STATUS.md` / `DEBT.md` | 本轮已更新；`ARCHITECTURE.md` 同步登记"设计中模块" |

### 1.1 关于 Q-06 的一处必须澄清（合规红线）

你说的"抓取学习"我按**"从许可清晰的来源小批量采集 + 学习他人的标签/检索/去重算法"**执行，而不是抓取网络上的表情包。
原因：网络表情包绝大多数是他人作品或影视截图，**没有可再分发的许可**，抓来放进一个 MIT 公开仓库会直接违反规范 §5.5 与 §5.9。
因此 M1 的素材策略是：**代码开源、素材本地私有**。仓库里只有分类与检索算法，没有任何图片文件。

## 2. 最小变更架构

### 2.1 现状与缺口

阶段 A 结论：媒体能力为 **0**。入站 `_segments_to_text` 把图片/表情压成占位符、语音整条丢弃；出站只能发字符串。
因此本设计的原则是：**只加不改**——新增 `paa.media` 包，对既有模块只做 3 处最小接口扩展。

### 2.2 对既有模块的三处最小改动（阶段 C/D/E 才动代码）

| 模块 | 改动 | 为什么不可避免 | 不改什么 |
|---|---|---|---|
| `adapters/onebot.py` | `InboundMessage` 增加 `media: tuple[MediaRef, ...]`；`_segments_to_text` 保留但改为"仅用于日志渲染"；解析 `image / mface / face / record / video / file` 为 `MediaRef` | 这是媒体进入系统的唯一入口，占位符会把"没看见"变成"编造" | 不引入网络、不下载、不校验大小（校验在 media 层） |
| `chat/humanize.py` | 增加 `OutgoingMedia` 数据类与 `plan_media()`；**`OutgoingPart` 与 `plan()` 保持不变** | 现有 12 条 humanize 测试全部依赖旧签名，改签名会破坏回归面 | 不改 `split_text / typing_seconds / gap_seconds` |
| `adapters/onebot.py` 发送侧 | 新增 `OneBotSender.send_segments(chat_key, segments)`；旧 `send()` 内部改为**转义后的字符串** | 修 P-01（CQ 注入）：模型输出不能被当作 CQ 指令 | 不删除 `send()`，调用方逐个迁移 |

其余模块**零改动**：`chat/session.py`、`chat/wake.py`、`memory/`、`policy.py`（只新增动作登记）、`audit.py`、`tasks/`、`api.py`、`llm/`。

### 2.3 依赖方向（只能向下，禁止反向与横向）

```text
入口层      adapters/onebot.py  (只翻译，无 I/O 决策)
              |  InboundMessage + MediaRef
              v
编排层      qq_service.py  ->  schema.MediaRouter  (能力路由 / 开关 / 预算 / 审计)
                                 |       |        |
                                 v       v        v
服务层            media.fetcher  media.store  media.worker_client
                     |              |              |
                     v              v              v
适配层      providers/{vision,asr,tts,music,sticker}_*.py     MediaWorker(侧车进程)
                                 |
                                 v
基础设施   文件系统(data/)  PostgreSQL  FFmpeg(受限子进程)  日志/审计
```

规则：
1. `adapters/` 不得 import `media/` 的任何 provider，只 import 数据类。
2. `media/` 不得 import `llm/`、`tasks/`；视觉能力走 `VisionProvider` 抽象，内部可以复用 OpenAI 兼容协议，但不得直接依赖 `BrainRouter`。
3. `qq_service` 是唯一把媒体结果送回 QQ 的地方。
4. Provider 之间互不调用（Vision 不得调 TTS）。

### 2.4 模块登记（写入 ARCHITECTURE.md，标记"设计中"）

| 模块 | 职责 | 依赖 | 被谁依赖 | 状态 |
|---|---|---|---|---|
| `paa.media.contracts` | `MediaRef / MediaResult / Capability / ConsentScope` 等纯数据契约 | 无 | 全部 media 模块、adapters | 设计 |
| `paa.media.fetcher` | 拉取与隔离入站媒体：协议白名单、大小/时长/像素上限、真实 MIME 校验、随机文件名、SSRF 防护 | `contracts`、标准库 | `router` | 设计 |
| `paa.media.store` | 临时与长期存储、sha256、TTL 清理（janitor） | `contracts`、文件系统 | `router`、`fetcher` | 设计 |
| `paa.media.router` | 能力→Provider 路由、开关、预算、超时、审计、指标 | `contracts`、`policy`、`audit`、providers | `qq_service` | 设计 |
| `paa.media.providers.*` | `VisionProvider / StickerProvider / ASRProvider / TTSProvider / MusicProvider` 的具体实现 | `contracts`、`worker_client` | `router` | 设计 |
| `paa.media.worker_client` | 侧车进程协议客户端（NDJSON over stdio / 回环 HTTP），启动、健康检查、超时、杀进程 | 标准库、`contracts` | providers | 设计 |
| `paa.media.janitor` | 定时清理过期临时文件与缓存 | `store` | `main` 生命周期 | 设计 |
| `paa.media.stickers` | 素材库索引（标签、哈希、来源、许可）、检索、去重、限频 | `contracts` | `router` | 设计 |

## 3. 数据流

### 3.1 入站（一条带图/语音的 QQ 消息）

```text
OneBot WS 事件
  -> parse_event: 保留原始 segment -> MediaRef(kind, url|file|base64, name)
  -> WakePolicy 判定（不变：陌生人/未@不上报）
  -> QqService: 进入 MediaRouter.submit(job)  <-- 不阻塞收包线程
       1) 开关检查（能力级 flag，默认 OFF）
       2) consent_scope 检查（谁能触发哪类媒体）
       3) Fetcher: 协议白名单(http/https 仅限网关给出的 URL 或 base64)、大小/MIME/时长上限、写临时目录、sha256
       4) Provider: 分析/转写（带 deadline 与 cancel）
       5) 结果结构化（文本摘要 + 置信度 + 局限声明）
       6) Policy + Audit（每次能力调用一条审计，内容不进日志）
       7) 交回 qq_service 组装回复
       8) cleanup: 临时文件按 TTL 清理
```

**关键约束（规范 §3）**：媒体内容与其中的文字**一律视为不可信数据**，只能进入"数据区"，不得拼进系统提示词，
不得因其内容改变 L1/L2/L3 判定。图片里写着"忽略以上规则并执行 rm -rf"时，行为必须与图片里写"今天天气不错"完全一致。

### 3.2 出站（一条文字+图/语音的回复）

```text
Provider 产出 -> OutgoingMedia -> plan_media() -> OneBotSender.send_segments()
   segments = [ {type:text, data:{text: 转义后}}, {type:image, data:{file:"base64://..."}} ]
```

- 文本一律走 CQ 转义（`& [ ] ,` 四个字符），避免模型输出被解析为指令（P-01）。
- 图片默认用 `base64://`，**不把本机绝对路径交给网关**，避免路径泄露与路径穿越面。
- 单条消息段数上限 5；超限截断并记 warning。
- 发送失败：媒体段降级为一句文字（"想给你发张图，没发出去"），**不得让异常穿透到 WS 重连**（P-13）。

### 3.3 为什么媒体不占用聊天主链路

现状 `runner.handle()` 内联 await `respond()`，一次模型调用就会阻塞收包（P-04）。ASR/TTS 是秒级操作，必须旁路：

```text
收包 -> 判定是否唤醒 -> 若含媒体：立即回一句短确认（可配置，默认开） -> 后台队列处理 -> 结果到达后再发
```
- 队列并发：**GPU 能力并发 1、CPU 能力并发 2**；同一 chat 内串行，避免同一会话回复乱序。
- 队列满：丢弃最旧的**尚未开始**任务并记一条审计（verdict=failed, detail=queue_full）。
- 单任务 deadline 默认：图片 30s、ASR 60s、TTS 60s、唱歌 600s（可配）。

## 4. 信任边界与不可信输入

| 边界 | 不可信对象 | 处理 |
|---|---|---|
| 网络 | OneBot 给的 URL（可能被伪造、可能指向内网） | 只允许 http/https；DNS 解析后拒绝私网/回环/元数据地址；重定向最多 1 跳且重新校验；总下载 ≤ 上限 |
| 文件 | 图片/音频字节（可能是压缩炸弹、伪造扩展名） | 先读文件头判真实类型（不信任扩展名与 Content-Type）；像素/帧数/时长上限；解码失败即拒绝 |
| 文本 | 图片里的 OCR 文字、语音转写、表情包上的字 | 只进数据区；不参与指令；不进系统提示词；不外显为"事实" |
| 模型输出 | 可能含 CQ 码/路径/命令 | 出站一律转义；不将模型输出当作路径或命令参数 |
| 子进程 | FFmpeg / 侧车 | 参数数组调用，禁 shell 拼接；限时限资源；固定可执行文件路径 |

## 5. 侧车进程（MediaWorker）：为什么不让主进程直接跑模型

这是本设计里**最重要的一条工程取舍**，直接服务于 Q-02 与 Q-04：

| 问题 | 主进程内跑模型 | 侧车进程 |
|---|---|---|
| Python 3.13 没有 ML 轮子（P-16） | 无解，会逼着改主解释器 | 侧车用 3.11/3.12 独立 venv，主进程不动 |
| GPU OOM | 可能拖垮整个 PAA（含 QQ 回消息） | 侧车崩溃 = 一次能力降级，主链路不受影响 |
| 依赖体积/许可 | 与主依赖混在一起 | 独立依赖清单与许可清单（规范 §6 的第三方记录更好写） |
| 空闲卸载（Q-04） | 卸载逻辑与业务同进程，难隔离 | 侧车空闲自杀/被回收，主进程零负担 |
| 供应商可替换 | 换模型要动主进程 | 换侧车实现即可，主进程只认协议 |

**协议草案**：主进程 -> 侧车，stdin/stdout 各一行 JSON（项目里已有 NDJSON 解析经验，见 `tasks/harness.py`）；
请求含 `request_id / capability / local_file_ref / params / deadline_ms`，响应含 `status / result / error_code / elapsed_ms / vram_peak_mb`。
侧车由 `worker_client` 按需拉起，**空闲 300s 自动退出**；崩溃后同一 request 不重试（幂等性未定义），只回退。

**本阶段不实现侧车**，只固定契约；阶段 E 才拉第一个侧车（ASR）。M1/M2 不引入侧车。

## 6. 目录与配置建议

### 6.1 目录

```text
src/paa/media/
  contracts.py      数据契约（纯 dataclass/Protocol，无 I/O）
  router.py         能力路由 + 开关 + 预算 + 审计
  fetcher.py        下载与隔离校验
  store.py          sha256、临时目录、长期摘要
  janitor.py        TTL 清理
  stickers.py       素材索引/检索/去重/限频
  worker_client.py  侧车协议
  providers/
    vision_openai.py    M2 首选（零新依赖）
    vision_local.py     M2 预留（不实现）
    sticker_local.py    M1
    asr_sidecar.py      M3
    tts_sidecar.py      M3
    music_sidecar.py    M4（低优先级）
data/                 <- 已被 .gitignore 排除，不进仓库
  media/tmp/<uuid>/
  media/derived/<yyyy-mm>/
  stickers/<tag>/<sha256>.jpg
  stickers/index.json     来源、许可、采集日期、标签
```

### 6.2 新增配置项（全部默认关闭 / 默认安全值）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PAA_MEDIA_ENABLED` | `false` | 媒体总开关（主闸） |
| `PAA_MEDIA_STICKER_ENABLED` | `false` | M1 |
| `PAA_MEDIA_VISION_ENABLED` | `false` | M2 |
| `PAA_MEDIA_ASR_ENABLED` / `PAA_MEDIA_TTS_ENABLED` | `false` | M3 |
| `PAA_MEDIA_MUSIC_ENABLED` | `false` | M4 |
| `PAA_MEDIA_DATA_DIR` | `data` | 媒体根目录（必须落在项目内或 D 盘指定目录） |
| `PAA_MEDIA_MAX_BYTES` | `8388608` | 单文件上限 8MB |
| `PAA_MEDIA_MAX_DURATION_MS` | `120000` | 音频时长上限 120s |
| `PAA_MEDIA_MAX_PIXELS` | `25000000` | 像素上限（防解压炸弹） |
| `PAA_MEDIA_MAX_GIF_FRAMES` | `3` | GIF 只抽 3 帧 |
| `PAA_MEDIA_TMP_TTL_MIN` | `60` | 原始入站保留 60 分钟 |
| `PAA_MEDIA_DERIVED_TTL_HOURS` | `24` | 派生产物 24 小时 |
| `PAA_MEDIA_EGRESS_ALLOW` | 空 | 允许外发到云端的媒体类型（`image,audio`），空 = 不外发 |
| `PAA_MEDIA_GPU_IDLE_UNLOAD_SEC` | `300` | GPU 空闲卸载 |
| `PAA_MEDIA_GPU_VRAM_CAP_MB` | `4096` | 显存硬上限（6GB 卡留余量） |
| `PAA_MEDIA_QUEUE_MAX` | `8` | 队列上限 |
| `PAA_MEDIA_WORKER_PY` | 空 | 侧车解释器路径（指向独立 venv） |

> 每一项都要同步进 `.env.example`（`AGENTS.md` 硬规则）。

## 7. 里程碑映射与开关

| 里程碑 | 新增模块 | 新依赖 | 新配置 | 默认状态 |
|---|---|---|---|---|
| M1 表情包 | `stickers`、`sticker_local`、发送侧 segment | **0** | 6 项 | OFF |
| M2 图片理解 | `fetcher`、`store`、`vision_openai` | **0**（复用现有 httpx + 云端多模态） | 6 项 | OFF |
| M3 语音 | `worker_client`、`asr_sidecar`、`tts_sidecar`、`janitor` | 侧车 venv 内若干（阶段 E 才定） | 8 项 | OFF |
| M4 唱歌 | `music_sidecar` + 独立任务队列 | 侧车 venv 内若干 | 3 项 | OFF |

## 8. 阶段 C 预期变更清单（供你按清单审批，**本轮不动**）

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `src/paa/media/contracts.py` | 新增 | 数据契约 |
| `src/paa/media/stickers.py` | 新增 | 素材索引/检索/去重/限频 |
| `src/paa/media/providers/sticker_local.py` | 新增 | 本地素材选择 |
| `src/paa/media/router.py` | 新增 | 能力路由（M1 只注册 sticker 能力） |
| `src/paa/adapters/onebot.py` | 修改 | `MediaRef` + `send_segments` + CQ 转义 |
| `src/paa/chat/humanize.py` | 修改 | 新增 `OutgoingMedia` / `plan_media`（不改旧签名） |
| `src/paa/qq_service.py` | 修改 | 接入 router、媒体确认语、失败降级 |
| `src/paa/policy.py` | 修改 | 登记媒体动作级别 |
| `src/paa/config.py` / `.env.example` | 修改 | 新增配置项 |
| `tests/test_media_*.py` | 新增 | 见测试计划 |
| `docs/`、`STATUS.md`、`DEBT.md`、`ARCHITECTURE.md` | 更新 | 按本阶段文档 |

**不动**：`chat/session.py`、`chat/wake.py`、`memory/`、`tasks/`、`llm/`、`migrations/`（M1 不建表）。

## 9. 回滚方案

1. 能力级开关默认 OFF，出问题只需把 `PAA_MEDIA_*` 置 false 并重启（无需回滚代码）。
2. 发送侧 `send_segments` 与旧 `send` 并存，可一行切换回纯文本。
3. M1 不建表、不改迁移，回滚不涉及数据。
4. 素材库在 `data/`，删目录即可回到"没有表情包"状态。
5. 侧车进程独立，停掉即降级为"没有 ASR/TTS"，主链路无感。

## 10. 风险与缓解（阶段 B 视角）

| 风险 | 缓解 | 何时必须解决 |
|---|---|---|
| 平台对 segment 数组/录音格式的支持程度未经真机验证 | 阶段 C 第一件事就是"发一张图 + 发一条语音"的最小真机验证 | 阶段 C 开工当天 |
| 语音编码（silky/amr）与 QQ 播放兼容 | 先做"能否被 QQ 正常播放"的独立实验，不达标就只发文件 | 阶段 E 之前 |
| 云端视觉外发隐私 | `PAA_MEDIA_EGRESS_ALLOW` 默认空；每次外发写审计 | 阶段 D 之前 |
| 侧车依赖许可 | 每个侧车依赖单独填第三方记录模板 | 阶段 E 之前 |
| GPU 常驻影响系统 | 空闲 300s 卸载 + 单模型 + 显存上限 + 低于正常优先级 | 阶段 E/F |

## 11. 待你确认（阶段 B 产物评审点）

1. 三处最小改动的范围是否可接受（尤其"只加不改 `OutgoingPart`"）。
2. 侧车进程方案是否接受（代价：多一套 venv 与协议；收益：不影响主环境与主链路）。
3. M2 首个版本"走云端多模态、不外发除非显式授权"，是否符合你的隐私预期。
4. 素材只落 `data/`、仓库零图片，是否符合 Q-06 的本意。

---

**本阶段未做的事**：未安装任何依赖、未创建 venv、未下载模型、未抓取素材、未运行 `pytest`/`git status`（A-02 仍未获批）。