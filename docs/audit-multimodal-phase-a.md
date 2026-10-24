# PAA 多模态扩展基线审计与风险清单

> 阶段：**A — 只读审计**（《PAA × DSH 多模态插件扩展：开发设计与安全执行规范》第 7 节）
> 审计日期：2026-10-24　审计对象：`D:\项目设计\Personal AI Agent（PAA）`（HEAD `da5b9e9`，38 次提交）
> 结论先行：**现有代码中不存在任何媒体处理能力**；本次扩展是"新建媒体层"，不是"改造已有媒体模块"。
> 本文件为审计交付物，不修改任何代码、依赖与环境。下一阶段需你逐项批准。

## 0. 证据等级

| 等级 | 含义 | 本次适用 |
|---|---|---|
| ✅ 已验证 | 我直接读了源码/文档/API 返回并核对 | 代码、测试、文档、Git 元数据、pip 包清单、GitHub/HF 许可元数据 |
| 📄 仅文档描述 | 只在项目文档里声明，未独立验证 | 硬件型号、测试全绿、真机 QQ 状态、备份演练结果 |
| ❓ 未验证 | 环境限制无法验证，需明确视为未知 | git 工作区是否干净、pytest 实际结果、显存/内存实测、模型权重许可 |

**环境限制说明（必须记录）**：本次会话中 DSH 的 `workspace-write` 沙箱无法启动
（`SetNamedSecurityInfoW failed (Win32 5): grantWrite(...)`），所有工具不可用；
随后运行时把会话改为 `danger-full-access`。因此本次审计**没有执行任何 shell 命令**
（无法跑 `git status` / `pytest` / `ruff` / `alembic`），全部结论来自静态阅读与只读文件访问。
本次未执行写入、未安装、未下载、未读取 `.env`、未联网推送。

## 1. 基线核对：文档声明 vs 代码事实

| 规范第 1 节的声明 | 核对结果 | 证据 |
|---|---|---|
| 仓库含 src/tests/docs/migrations/AGENTS/ARCHITECTURE/STATUS/ROADMAP/DEBT/SECURITY | ✅ 全部存在 | 根目录清单 |
| QQ/OneBot 入口 | ✅ 存在（WS 收 + HTTP 发） | `adapters/onebot.py`、`adapters/runner.py`、`qq_service.py` |
| PostgreSQL 记忆 | ✅ `memories` 表 + 按人召回 | `models.py:36-57`、`memory/service.py` |
| Harness 适配 | ✅ 子进程 + NDJSON + 超时/取消 | `tasks/harness.py` |
| 任务状态机 | ✅ 6 状态、非法转换拒绝、重启标中断 | `tasks/engine.py:19-27,127-140` |
| 分级审批 | ⚠️ 有，但只在任务通道生效 | `policy.py`、`tasks/approval.py`、`tasks/executor.py` |
| 审计 | ⚠️ 有表有服务，但**聊天/QQ 路径不写审计** | `audit.py`；仅 `executor.py` 调用 |
| 本地维护台 | ✅ 单文件前端 + 8 个 API | `static/index.html`、`api.py` |
| 阶段 0—5 已完成 | 📄 文档声明 100% | `STATUS.md`（更新时间 2026-10-22，之后仍有备份文件 2026-10-24） |
| README「153 passed」 | 📄 有 153 个 `def test_`，**是否全绿未验证** | 25 个测试文件、1902 行 |

**文档漂移（已在风险清单 P-14/P-15 登记）**：
1. `STATUS.md` 停在 2026-10-22，晚于它的备份文件已到 2026-10-24。
2. `ARCHITECTURE.md` 模块登记表缺 `api / health / qq_service / adapters / pricing / usage / runtime / logging / cli` 共 9 个已存在模块，违反 `AGENTS.md` 规则 6。
3. `SECURITY.md` 仍写"审计日志表尚未建表"，实际 `b9b08aa5896f` 迁移已建 `audit_logs`。
4. `docs/troubleshooting.md` 说维护台令牌在 `%USERPROFILE%\.paa\ui.token`，代码只读 `PAA_UI_TOKEN` 环境变量，文件方式**不存在**。
5. `.env.example` 缺 `PAA_LOG_LEVEL / PAA_LOG_FILE / PAA_UI_TOKEN / PAA_TIMEZONE` 四项。
6. `docs/design-vision.md` 仍称"DSH 是唯一 AI 引擎"，与现行双通道路由（本地优先 + 云端兜底）不符。

## 2. 现有媒体能力盘点（核心结论）

**结论：媒体能力为 0。** 全量 grep `image|voice|audio|record|video|media|sticker|tts|asr` 于 `src/`，命中的只有占位符文本与无关词（`record()` 方法名）。

| 能力 | 现状 | 证据 |
|---|---|---|
| 入站图片 | 被压成字符串 `"[图片]"`，URL/file/base64 **全部丢弃** | `adapters/onebot.py:37-38` |
| 入站表情（face） | 压成 `"[表情]"`，表情 id 丢弃 | `adapters/onebot.py:39-40` |
| 入站语音（record） | **不识别 → 整条消息被丢弃** | `_segments_to_text` 无 `record` 分支；`parse_event:94-95` 空文本即 return None |
| 入站 mface/视频/文件/回复/转发 | 全部静默丢弃 | 同上，无对应分支 |
| 入站原始 payload | 不保留，解析后即丢 | `InboundMessage` 无 raw/媒体字段，`onebot.py:15-24` |
| 出站图片/表情/语音 | **没有任何发送路径** | `onebot.py:136-155` 只发字符串 |
| 出站消息格式 | 纯字符串 `{"message": text}`，未转义 CQ 码 | 同上 |
| 媒体存储/素材库/清理 | 不存在 | 无 `data/`、无媒体表 |
| 媒体相关配置 | 不存在 | `config.py` 无任何 media 项 |
| 媒体相关测试 | 不存在 | 25 个测试文件无一涉及 |

**两个直接后果（本次审计最重要的发现）**：
1. 用户现在发图片或表情，模型收到的字面量是 `"[图片]"` / `"[表情]"`，**却会照常组织回复**——等于被要求"对看不见的东西发表意见"，属于幻觉来源（P-02）。
2. 用户现在发语音，机器人**完全不响应**（不算错误，是消息被整条丢弃），不会有任何日志解释原因（P-03）。

## 3. 架构与可扩展点评估

### 3.1 分层是否支持"插件化接入媒体"

| 层 | 是否可无侵入扩展 | 说明 |
|---|---|---|
| 入口 `adapters/onebot.py` | ❌ 必须改 | `InboundMessage` 是媒体扩展的唯一入口；当前无媒体字段，且 `_segments_to_text` 是有损转换。**这是规范要求"识别媒体消息类型"的最小侵入点**（改接口而非改内部逻辑）。 |
| 唤醒 `chat/wake.py` | ✅ 可不动 | 纯逻辑，只吃 text/sender/at/poke。 |
| 会话 `chat/session.py` | ✅ 可不动 | 只吃文本；媒体理解结果可作为"文本前置块"注入，无需改签名。 |
| 模型路由 `llm/` | ⚠️ 需扩 | `ModelClient.complete` 只发纯文本 message，未实现 `image_url` 多模态消息体；VisionProvider 需要独立接口而非硬塞进 channel。 |
| 权限 `policy.py` | ⚠️ 需扩 | 动词白名单（L1/L2/L3），新动作默认落到"未知动作→L3 需审批"。**默认拒绝是好的**，但意味着媒体能力上线即被审批卡死，必须在阶段 B 显式登记动作与级别。 |
| 审计 `audit.py` | ✅ 可用 | 接口够用（actor/action/target/verdict/detail，detail 截断 2000），问题是**没人调用**。 |
| 任务 `tasks/` | ✅ 可复用 | 适合放 M4 唱歌这类长任务（独立队列、超时、取消、重启标中断）。 |
| 运维面板 `api.py` | ✅ 可加只读端点 | 现有 8 个端点风格统一。 |

### 3.2 现有 DB schema（8 表）

`users / memories / messages / agent_tasks / approvals / audit_logs / tool_calls / token_usage`（`models.py`，与 7 个 Alembic 迁移一致）。
媒体扩展的缺口：`messages` 无 `media_kind / mime / size / sha256 / duration_ms / storage_ref` 列；
无媒体任务表；无素材库表；无保留期字段（`DEBT.md` D05 已到期未处理）。

### 3.3 配置与依赖现状（已验证）

- venv：Python **3.13.1**（`D:\Python\python`），49 个包。
- 已装：fastapi 0.150 / uvicorn 0.54 / sqlalchemy 2.1.5 / psycopg 3.3.6 / alembic / httpx 0.28.1 / websockets 17.3 / pytest 9.1.1 / ruff 0.17.1。
- **未装**：torch、onnxruntime、numpy、Pillow、soundfile、ctranslate2、ffmpeg 绑定、任何 ASR/TTS/VLM 库。
- ⇒ 媒体功能必然引入新依赖，**每一项都需要单独批准**。

## 4. 代码级风险清单

严重度：🔴 高 / 🟠 中 / 🟡 低。所有条目均为静态阅读所得，未经运行验证。

| ID | 严重度 | 问题 | 证据 | 对多模态扩展的影响 |
|---|---|---|---|---|
| P-01 | 🔴 | **出站 CQ 码未转义**：`message` 传纯字符串，网关会按 CQ 字符串解析。模型输出若含「远程取图」或「@全员」类的 CQ 片段，会被当作指令执行 | `onebot.py:136-155` | M1/M3 上线后必须改用 segment 数组格式并转义文本，否则"发图"能力天然带着 SSRF/广播面 |
| P-02 | 🔴 | **占位符幻觉**：`[图片]`/`[表情]` 文本进入模型，模型会编造图片内容 | `onebot.py:37-40` + `session.py:83` | 阶段 D 之前必须先让占位符"不可被当作已知内容"，否则先上线反而降低可信度 |
| P-03 | 🟠 | 语音消息被整条丢弃，无日志无回执 | `onebot.py:94-95` | M3 的入口障碍：用户发语音"没反应"，且查不到原因 |
| P-04 | 🔴 | **接收循环内联调模型**：`respond()` 在 `async for` 内直接 await，无队列、无并发上限、无背压 | `runner.py:105-110`、`qq_service.py:68-135` | ASR/TTS 是秒级操作，会阻塞整个 QQ 收包；必须引入媒体专用队列（规范第 3 节"独立队列"） |
| P-05 | 🟠 | 无出站限速、无去重、无长度上限 | `onebot.py:136-155`、`humanize.py:120` | 表情包连发会刷屏（M1 验收项"重复抑制/频率限制"目前无地基） |
| P-06 | 🟠 | **QQ 路径不写审计**：`AuditService` 只被任务执行器调用 | `audit.py` vs `qq_service.py` | M1—M4 的每次媒体动作都将无留痕，违反规范"无审计即拒绝" |
| P-07 | 🟠 | 权限动词白名单无法表达媒体动作（`analyze_image`→未知→L3） | `policy.py:12-26,43-51` | 设计上安全（默认拒绝），但操作上会导致媒体功能全部卡审批，需在阶段 B 显式建模 |
| P-08 | 🟠 | 审批未绑定发起人：`consume()` 只校验状态/时效/是否用过 | `approval.py:55-68` | 若媒体触发审批，别人拿到的审批 id 可能被复用（当前单用户风险低，扩展后需修） |
| P-09 | 🟠 | 日志无脱敏过滤器：`fields` 原样合并进 JSON | `logging.py:20-22` | 媒体路径、ASR 转写文本、图片 URL 会直接进日志，与规范第 5.9 条冲突 |
| P-10 | 🟠 | 每轮无条件写 topic 记忆（取前 40 字） | `session.py:98` | 媒体占位符与转写全文会污染长期记忆，与"禁止默认保存原始语音"冲突 |
| P-11 | 🟡 | 死代码：`MessageBatcher` 从未被使用；`WakePolicy` 冷却读 `last_wake_at` 但生产代码从不设置 | `chat/__init__.py:10`、`wake.py:82-86` | 连发多张图不会合并；冷却等于不存在（群里可能过密插话） |
| P-12 | 🟡 | `include_router(api_router)` 注册了两次；`/api/status` 无鉴权；令牌用 `!=` 比较 | `main.py:104,120`、`api.py:23-37` | 维护台后续加媒体端点时会重复踩 |
| P-13 | 🟠 | 发送失败 `raise_for_status` 穿透 `handle()` → 触发整条 WS 重连 | `onebot.py:152`、`runner.py:113-116` | 图片/语音发送失败率高于文本，会放大"一条失败=一次重连"的抖动 |
| P-14 | 🟡 | 配置/文档漂移（见 §1） | — | 新增 `PAA_MEDIA_*` 时必须同步 `.env.example` |
| P-15 | 🟡 | 架构登记表落后 9 个模块 | `ARCHITECTURE.md` 末表 | 新模块必须先登记再写代码（AGENTS 规则 6），当前基线本身不合规 |
| P-16 | 🟠 | **Python 3.13 + ML 生态兼容性**：torch/CTranslate2/FunASR/onnxruntime 的 Windows 3.13 轮子覆盖未经核实 | `pyvenv.cfg` | 可能被迫引入第二套 Python 环境，而规范禁止动全局/Conda（需你决策 Q-02） |
| P-17 | 🟠 | 无媒体元数据 schema、无保留期、无清理任务（D05 到期） | `models.py`、`DEBT.md` | 媒体文件会无限堆积；备份体积与隐私面同时变大 |
| P-18 | 🔴 | NapCat 是**非 OSI 自定义许可**且属非官方协议端 | 见 §5.1 | 既有法律/账号风险，不得因"加媒体"而扩大（见 §5.1 红线段） |

## 5. 第三方技术：许可与安全核查

> 许可结论以**官方仓库元数据 + LICENSE 全文**为准；**模型权重许可能拿到的是仓库声明，权重本体的许可标记本次未能访问（❓未验证）**。

### 5.1 NapCat（既有链路，风险最高）

- 仓库：`NapNeko/NapCatQQ`，11,367★，TypeScript，NOASSERTION。
- LICENSE 原文要点（自定义"Limited Redistribution License"，Copyright © 2024 Mlikiowa）：
  - 未经作者明确许可，**禁止使用、复制、修改、分发**；
  - 允许再分发但必须附全文许可与来源，**修改后的代码不得公开发布**；
  - **禁止任何商业用途**；
  - 未明示的权利须向作者申请。
- 判定：这是**非开源许可**，比 GPL 严格得多。PAA 是 MIT 公开仓库。
- **红线（建议写入 `ARCHITECTURE.md`）**：
  1. 只通过 OneBot v11 HTTP/WS 公开接口通信，**零源码依赖、零代码复制、零二进制再分发**；
  2. 不在 PAA 仓库内放置 NapCat 安装包、补丁、`napcat.bat`、silk 转换脚本等衍生文件；
  3. 文档只写"需要用户自行安装 NapCat"，不提供一键安装脚本。
- 账号风险：非官方协议端，QQ 侧可能风控/封号——这条既有风险**不因多模态而新增**，但媒体发送频率提高会放大暴露面（P-05）。

### 5.2 REA（`github.com/morluto/rea`）— 你最关心的"借鉴来源"

| 项 | 事实（✅ 已验证） |
|---|---|
| 官方地址 | https://github.com/morluto/rea （另有 rea.tools、npm `rea-agents`） |
| 许可 | **MIT**（LICENSE 全文已读，Copyright © 2026 morluto） |
| 版本 | `rea-agents@6.7.0`，TypeScript，Node `^22.23.4 \|\| ^24.22.1 \|\| >=26.12.1` |
| 定位 | "Reverse engineer anything with agents" —— 面向**逆向工程**的本地 MCP 工具集（二进制/Electron/.NET/网站/APK） |
| 运行方式 | `npx rea-agents setup` 把 MCP server 与工作流指令**写进 agent 配置**（改配置前会备份）；可选用 Hopper(专有)/Ghidra(Apache-2.0)/IDA(专有)/JADX 等外部引擎 |
| 第三方件 | 子模块 `jadx-headless-mcp`(第三方)、`binwalk`、`unblob`、`ghidra-nativeaot`、`wakaru`；依赖含 openpgp、playwright-core、node-pty、isomorphic-git、msgpack、evmole；仓库含 `frida-verification` 相关构建配置 |
| 安全自述 | 明确写"**这不是沙箱**"；Hopper/Ghidra 桥用一次性随机能力令牌；Windows Ghidra 用仅当前用户可访问的私有 NTFS 运行时；Linux 装依赖走 apt/dnf/pacman + pkexec，**从不 sudo** |
| DISCLAIMER | 禁止规避 DRM/许可校验/反作弊、禁止绕过未授权系统的鉴权、禁止复制专有软件 |

**判定（关键）**：

1. **REA 不是多模态组件，也不是 QQ 组件。** 它与"看图/听懂/说人话/唱歌"没有直接技术重叠。
2. 它唯一可以合法贡献的是**设计思想**：MCP 式工具契约、结论必须带证据与局限、一次性能力令牌、受限启动/消息上限、私有运行时目录。这些可以零拷贝地写进 PAA 的 `MediaProvider` 接口设计。
3. **不安装**。理由：`npx rea-agents setup` 会改写 agent 配置（属"修改系统环境"）、会按需拉取/调用外部逆向引擎、npm 供应链风险、且要 Node 22+/24+。规范 §5.4 与 §6 都要求"研究阶段仅浏览源码/文档/提交历史/许可"。
4. **绝对不用于 NapCat 或 QQ 客户端**：那同时违反 REA 自己的 DISCLAIMER（规避鉴权/复制专有软件）、本任务书 §6（不得破解绕过授权）与 NapCat 许可。这条建议写成硬红线。
5. 若你仍希望用 REA 辅助"读懂某个开源项目的实现"，那是**独立的一次性分析动作**，需单独批准，且目标必须是**已授权、开源、非 QQ 客户端**的代码。

### 5.3 候选组件许可矩阵

| 组件 | 代码许可 | 权重许可 | 维护状态 | 与 6GB 显存的关系 | 建议 |
|---|---|---|---|---|---|
| **SenseVoiceSmall**（FunAudioLLM） | MIT | ❓未验证（HF 不可达） | 2026-09 活跃 | ONNX/int8 可纯 CPU，内存约数百 MB | ASR 首选（中文强） |
| **faster-whisper** | MIT（CTranslate2 亦 MIT） | Whisper 权重 MIT（📄 上游声明，❓未本地核实） | 2026-10 活跃 | CPU int8 可跑 small；GPU 更快 | ASR 备选/兜底 |
| **Qwen3-TTS** | Apache-2.0 | ❓未验证 | 2026-03 后未再推（相对静止） | 0.6B 需 GPU（显存占用未实测） | TTS 候选，注意"音色克隆"授权红线 |
| **Kokoro-82M** | Apache-2.0 | ❓未验证 | 2025-08 后未再推（偏旧） | 82M，CPU 可跑 | 轻量 TTS 兜底 |
| **ACE-Step 1.5** | MIT | ❓未验证 | 2026-10 活跃 | 官方称 base <4GB VRAM；XL(4B) 需 ≥12GB | M4 唯一候选，**必须先做 6GB 基线测试** |
| **qq-ai-bot** | MIT | 素材版权 ❓（仓库内 7 张"示例"图，来源未注明） | 5★，单人，2026-09 | 无模型 | **只借鉴分类思路**，不取素材、不取代码 |
| **NoneBot2** | MIT | — | 活跃 | — | 不引入（框架重量），只看插件事件设计 |
| **AstrBot** | **AGPL-3.0** | — | 活跃 | — | **只借思想**：AGPL 代码进入 MIT 仓库会传染整仓许可 |
| **FFmpeg** | LGPL-2.1+（默认）/ **GPL**（含 x264 等构建） | — | 活跃 | CPU | 外部子进程调用，参数用数组、禁 shell；分发前确认构建许可 |
| **pip-audit / osv-scanner / bandit / gitleaks** | Apache-2.0 / Apache-2.0 / Apache-2.0 / MIT | — | 活跃 | — | 阶段 G 前接入 |

**许可结论**：M1—M4 的**实现路径许可干净**（MIT/Apache），唯一法律风险点是 NapCat（不碰源码即规避）与**素材/音色版权**（表情包图片、克隆音色、唱歌输出的歌词与旋律）。

## 6. 资源与可行性

| 项 | 声明 | 验证 |
|---|---|---|
| Windows 11 / 16GB RAM / RTX 4050 Laptop 6GB | 任务书 §0 | 📄 仅文档；`nvidia-smi.exe` 与 `C:\Program Files\NVIDIA Corporation` 存在 → **驱动已装**，型号/显存 ❓未验证 |
| D 盘存放模型 | 任务书 §0 | 📄 未验证剩余空间 |
| 峰值显存/内存 | — | ❓ 未测（阶段 A 不下载模型，无法测） |
| Python 3.13.1 | 代码验证 | ✅ 但 ML 轮子兼容性 ❓（P-16） |

**预判**：M1/M2 以 CPU 与现有云端视觉为主，资源无压力；M3 的 ASR 可纯 CPU；TTS 用 Kokoro/Piper 级可 CPU，用 Qwen3-TTS 0.6B 则需 GPU；**M4 在 6GB 上属于"可能可行但必须实测"**——ACE-Step 官方 base 模型号称 <4GB，但 6GB 笔记本还要同时承载 Windows 桌面与浏览器，实际余量很小，XL 明确不可行。

## 7. 测试现状

- 规模：25 个文件 / 1902 行 / **153 个测试函数**（与 README 徽章一致）。
- 风格：`httpx.MockTransport` 打桩网络；DB 用例通过 `conftest.py` 事务回滚；DB 不可用时 `pytest.skip`。
- 缺口（对多模态直接相关）：
  1. 无媒体类型识别、MIME 伪造、路径穿越、大小/时长上限、GIF 帧数炸弹测试；
  2. 无"图片内提示注入不得提权"测试（规范 §8 明确要求）；
  3. 无发送失败回退测试（`onebot.py` 的异常路径只有"抛错"一条断言）；
  4. 无并发/队列/超时取消测试（因为还没有队列）；
  5. `test_api.py` 6 条，未覆盖令牌鉴权分支。
- **无法验证**：本次未运行 `pytest`，`153 passed` 属 📄 文档声明。

## 8. 风险矩阵

| 风险 | 严重度 | 可能性 | 结论 |
|---|---|---|---|
| 表情包素材/音色/歌词版权 | 🔴 高 | 高（默认会踩） | 只用自有或明确授权素材；表情包先建"空库 + 导入工具"，不预置任何第三方图片 |
| NapCat 许可与账号风控 | 🔴 高 | 中 | 严守 §5.1 三条红线 |
| 媒体层拖垮 QQ 主链路（P-04） | 🔴 高 | 高 | 阶段 B 必须设计独立队列 + 熔断；媒体失败不得影响文字回复 |
| 出站 CQ 注入（P-01） | 🔴 高 | 中 | M1 前置修复，先改 segment 数组 + 转义 |
| 隐私外流（图片/语音发给第三方 API） | 🔴 高 | 中 | 视觉/ASR 若走云端，必须先有"每类媒体的外发授权"开关 |
| 占位符幻觉（P-02） | 🟠 中 | 已发生 | 阶段 D 前先修占位语义 |
| Python 3.13 生态（P-16） | 🟠 中 | 中 | 阶段 E 前先做"仅安装可行性"验证（不下载权重） |
| 6GB 显存不足（M4） | 🟠 中 | 中高 | 阶段 F 先离线基准，不达标即停，不采购 GPU/云 |
| 审计缺失（P-06） | 🟠 中 | 高 | 媒体动作上线前补审计埋点 |
| 日志/记忆泄漏媒体内容（P-09/P-10） | 🟠 中 | 高 | 阶段 B 一并设计脱敏与"仅存摘要" |

## 9. 对任务书 M1—M4 的落地建议（供你决策，不是开工）

| 里程碑 | 我建议的最小可行路径 | 前置修复 | 不需要的东西 |
|---|---|---|---|
| **M1 表情包发送** | 素材库放 D 盘 `data/stickers/<tag>/`（`.gitignore` 已排除 `data/`）；标签取自 qq-ai-bot 的 7 类（卖萌/委屈/开心/得意/无语/生气/震惊）；由模型选标签 + 本地去重/限频；发送走 **segment 数组** | P-01 转义、P-05 限频、P-06 审计、P-13 发送失败降级为文字 | 不需要任何模型下载、不需要 GPU |
| **M2 图片/表情理解** | 先复用**现有 OpenAI 兼容链路的 image_url**（零新依赖、零权重）；`VisionProvider` 接口预留本地 VLM；GIF 只抽 3 帧 | P-02 占位语义、SSRF/大小/MIME 校验、外发授权开关 | 不需要 GPU，不需要下载权重 |
| **M3 语音** | ASR 用 SenseVoiceSmall(ONNX) 或 faster-whisper(small, int8) **纯 CPU**；TTS 先 Kokoro(82M, CPU) 打通链路，Qwen3-TTS 作为可选高质量档 | P-03 入站 record、P-04 队列、P-16 环境策略、silk/音频格式验证 | 不需要 GPU（若只用 CPU 档） |
| **M4 唱歌** | 独立低优先级任务队列 + 硬性开关默认 OFF；先只做离线基准（ACE-Step base） | 全部 M1—M3 稳定 | 未达 6GB 预算就不做 |

**共性建议**：新增模块按 `src/paa/media/`（+ `media/providers/`）独立成包，只通过 `MediaRouter` 接口被 `qq_service` 调用；先登记到 `ARCHITECTURE.md` 再写代码（AGENTS 规则 6）。

## 10. 阶段 B（接口设计）拟交付清单 — 需你批准后才执行

1. 《媒体能力接口设计》：`analyze_image / analyze_sticker / select_sticker / recognize_audio / synthesize_speech / generate_music` 的入出参，含规范 §3 要求的 `request_id / conversation_id / actor_id / capability / media_type / local_file_ref / size_bytes / duration_ms / timeout_ms / consent_scope / result_status`。
2. 媒体数据流与信任边界图（不可信输入 → 隔离 → 解码 → 结构化 → 语义 → 权限 → 发送 → 清理）。
3. `policy.py` 的媒体动作分级提案（哪些 L1、哪些 L2、哪些必须 L3 一次性审批）。
4. 资源调度与熔断设计（队列、并发上限、超时、GPU 串行、OOM 降级）。
5. 测试清单（含规范 §8 的恶意媒体/注入用例），中文用例名。
6. 目录与依赖预算（不安装，只列）。
7. 回滚方案（功能开关、默认关闭、零 schema 破坏性变更）。

交付形态：**只写文档 + 测试骨架草案，不动 `src/` 实现、不装依赖、不下模型。**

## 11. 需要你决策的问题

| 编号 | 问题 | 我的建议 |
|---|---|---|
| Q-01 | REA 是否还要"用起来"？ | **建议不安装**，只借鉴其"证据化结论 + 一次性令牌"设计；若要用，目标须是已授权开源代码，单独批准 |
| Q-02 | Python 3.13 若缺少 ML 轮子怎么办？ | 允许为媒体单独建一个 3.11/3.12 venv（不碰全局与 Conda），需你批准 |
| Q-03 | M2 视觉走云端多模态还是本地 VLM？ | 先走现有链路（零下载），并加"图片外发需授权"开关；本地 VLM 留接口不实现 |
| Q-04 | M3 是否允许 GPU 常驻？ | 默认不允许；先 CPU 档打通，GPU 档按需加载、空闲卸载 |
| Q-05 | 媒体文件放哪、留多久？ | `D:\...\PAA\data\media\`，默认 24 小时后清理，仅留摘要与哈希 |
| Q-06 | 表情包素材从哪来？ | 你提供自有素材；我只做导入与校验工具，**不抓取、不内置任何第三方图片** |
| Q-07 | 本次是否允许我更新 `STATUS.md` / `DEBT.md`？ | 按 AGENTS.md 应更新；按任务书阶段 A"只读"我**没有动**，等你批准后再补 |

## 12. 本次"未验证"清单（不得当作已完成）

1. `git status`（工作区是否有未提交修改）——无 shell，未验证。
2. `pytest` / `ruff` 实际是否全绿——未验证。
3. `alembic` 当前版本与本地库结构是否一致——未验证。
4. NapCat / QQ / PAA 服务当前是否在线、真实收发是否正常——未验证。
5. GPU 型号与显存、可用内存、D 盘剩余空间——未验证（仅驱动存在）。
6. 全部模型**权重**的独立许可文件——HF 域名在本环境不可达，未验证。
7. DSH 侧 MCP 支持程度与本机插件版本（DEBT D02）——仅读到 DSH 0.2.1-rc.2 / Cordis 4.0.5，未验证插件差异。

## 13. 第三方引入记录（模板首条示例，按要求填写）

```
名称        | REA (rea-agents)
官方地址    | https://github.com/morluto/rea
固定版本    | 6.7.0（2026-10-24 读取的 package.json）
许可证      | 代码 MIT（LICENSE 全文已核对）；外部引擎各自许可（Hopper/IDA 专有，Ghidra Apache-2.0）
复用方式    | 【本轮】仅设计思想借鉴，零代码、零安装、零运行
CVE/安全问题 | 未检索（未安装，不进入依赖图）；已知特性：会改写 agent 配置、需 Node 22+/24+、"不是沙箱"
权限需求    | 安装则需：写 agent 配置、可调用本机逆向引擎、按需安装系统包（pkexec）
性能测量    | 不适用（未运行）
退出/替代   | 不引入即无退出成本；替代方案为直接读目标项目源码与官方文档
审批人      | 待你确认（当前结论：不引入）
```

## 14. 审批请求（逐项，未批准一律不做）

| # | 动作 | 风险 | 是否需要 |
|---|---|---|---|
| A-01 | 进入阶段 B，编写接口设计文档 + 测试骨架草案 | 低（纯文档） | **待批** |
| A-02 | 运行 `git status` / `pytest` / `ruff` 完成基线核验（只读命令） | 低 | 待批 |
| A-03 | 更新 `STATUS.md` / `DEBT.md`（补本次审计与 6 条漂移债务） | 低（改文档） | 待批 |
| A-04 | 安装任何 Python 依赖 / 下载任何模型权重 | 中（供应链、磁盘） | **不在本阶段** |
| A-05 | 安装或运行 REA | 高（改 agent 配置、npm 供应链） | 建议**不做** |
| A-06 | 接入真实 QQ 做媒体端到端测试 | 中（账号、隐私） | 不在本阶段 |

---

**审计结论一句话**：PAA 的骨架（消息、记忆、权限、审计、任务、路由）足以承载媒体插件，但**媒体能力是零起点**，
且现有 QQ 收发路径有 4 个必须在"发第一张图之前"修掉的缺陷（CQ 注入、占位符幻觉、接收阻塞、无审计）。
第三方许可整体干净（REA MIT、候选模型 MIT/Apache），唯一硬约束是 **NapCat 的自定义限制性许可**与**素材/音色版权**。
