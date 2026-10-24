# 架构

## 定位

单用户、单机优先的私人智能体。核心是**两条互不干扰的通道**：聊天要快、要像人；任务要稳、要有边界。两者共享记忆与人格，但不共享执行路径。

## 两条通道

```
        ┌── 聊天通道 ──► Model Provider Adapter ──► 流式回复
入口 ───┤
        └── 任务通道 ──► Task Engine ──► Harness Adapter ──► dsh 子进程（沙箱内执行）
```

聊天通道不碰工具、不碰文件系统；任务通道不参与闲聊。混在一起会让「回一句话」也背上工具定义的开销，也会让任务失败拖垮聊天。

## 模块与依赖方向

依赖只能向下，不能反向或横向调用。

```
入口层    API / QQ Adapter / CLI
              ↓
核心层    Agent Core（上下文组装、路由）   Policy（权限裁决、审批）
              ↓
服务层    Memory Service   Task Engine   Token Meter   Audit
              ↓
适配层    Model Adapter    Harness Adapter    Executor
              ↓
基础设施  PostgreSQL       文件系统          日志
```

| 模块 | 职责 | 明确不做 |
|---|---|---|
| Agent Core | 组装上下文（人格 + 记忆 + 最近对话 + 处境）、选择通道 | 不直接调模型、不发消息 |
| Policy | 判定一次操作属于 L1/L2/L3，签发一次性授权 | 不执行操作 |
| Memory Service | 按人存记忆、检索、撤销 | 不做向量库抽象 |
| Task Engine | 任务状态机、超时、取消、重试 | 不解释任务内容 |
| Harness Adapter | 拉起 `dsh`、解析 NDJSON、映射成内部事件 | 不判断任务该不该做 |
| Model Adapter | OpenAI 兼容调用、重试、用量统计 | 不拼提示词 |
| Executor | 受限命令与文件操作、工作目录隔离 | 不自行提权 |

## 关键约束

1. **Harness 是可选执行器，不是核心。** 它走 nightly 通道、CLI 仍是 rc 版本，必须能被替换。
2. **记忆按人存，不按会话存。** 同一个人换入口不该失忆。
3. **人格底线写在代码里**，用户角色卡只能补充，不能覆盖安全规则。
4. **任何工具调用先过 Policy，再落审计**；没有审计记录的执行视为缺陷。
5. **服务账号隔离**：agent 运行时不得使用具备 sudo 的账号（服务器上的 `paa` 仅用于人工运维）。

## 目录现状

```
src/paa/
  main.py        HTTP 入口（当前只有 /healthz）
  config.py      环境变量配置
  db.py          引擎/会话（懒加载）
  models.py      ORM 模型（users, memories）
migrations/      Alembic 迁移
tests/
docs/            设计与运维文档
```

后续新增模块时按上面的分层建包，不要平铺在 `src/paa` 根下。

## 模块登记

新增模块先在表里登记职责与依赖，再写代码。

| 模块 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `paa.config` | 读取环境变量与 `.env` | 无 | 所有层 |
| `paa.db` | 引擎、会话、事务边界 | `config` | `models`、服务层 |
| `paa.models` | ORM 表定义 | `db` | 迁移、仓储层 |
| `paa.memory` | 记忆的写入/检索/撤销 | `models` | 未来的 Agent Core |
| `paa.llm` | OpenAI 兼容调用、用量提取、错误归一 | `config` | 未来的 Agent Core |
| `paa.llm.router` | 主通道（本地）/ 备用通道（云端）切换与迟滞 | `llm.client` | Agent Core |
| `paa.persona` | 人格卡加载与提示词装配（底线规则不可覆盖） | `config` | 未来的 Agent Core |
| `paa.chat` | 唤醒判定与消息合并（纯逻辑，无 I/O） | 无 | 入口层与 Agent Core |
| `paa.chat.history` | 消息落库与按人回放 | `models` | `ChatSession`、未来的同步接口 |
| `paa.tasks` | 任务状态机（不含执行） | `models` | 未来的执行器与审批层 |
| `paa.tasks.harness` | dsh 子进程执行与 NDJSON 解析 | 标准库 | 未来的任务执行编排 |
| `paa.policy` | 动作分级（L1/L2/L3） | 无 | 执行器与入口 |
| `paa.audit` | 只追加的审计记录 | `models` | 所有需要留痕的调用方 |
| `paa.tasks.approval` | L3 一次性授权 | `models` | 执行器 |
| `paa.tasks.executor` | 策略 → 审批 → 执行 → 审计的编排 | 全部任务模块 | 入口层 |
| `paa.main` | HTTP 入口与生命周期（启动预检、任务恢复） | `config`、`db`、`tasks` | uvicorn |
| `paa.serve` | 常驻服务入口 | `main` | 运维脚本 |

### 补齐：已存在但此前未登记的模块（2026-10-24 审计发现）

| 模块 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `paa.api` | 维护台只读 API 与撤销记忆 | `db`、`memory`、`usage`、`health` | `main` |
| `paa.health` | 连通性探测（DB/NapCat/QQ/DSH） | `config`、`db` | `api` |
| `paa.qq_service` | QQ 入口编排：会话缓存、配额、回复计划 | `adapters`、`chat`、`llm`、`memory`、`usage` | `main` |
| `paa.adapters.onebot` | OneBot v11 事件翻译与发送（只翻译，不判断是否回复） | 标准库、`httpx` | `runner`、`qq_service` |
| `paa.adapters.runner` | OneBot 接收循环、唤醒判定、分段发送 | `chat.wake`、`adapters.onebot` | `qq_service` |
| `paa.pricing` | 价格表读取与费用估算 | 无 | `usage` |
| `paa.usage` | token 记录、按天聚合、配额 | `models`、`pricing` | `qq_service`、`api`、`cli` |
| `paa.logging` | JSON 结构化日志 | 标准库 | 所有入口 |
| `paa.runtime` | 进程级运行时信息（启动时刻） | 标准库 | `health` |
| `paa.cli` | 本地 REPL 入口 | `chat`、`memory`、`llm` | 人工 |

## 多模态媒体层（M1 + M1.5 已实现，M2—M4 设计中）

> 状态：**M1 表情包发送、M1.5 学习线已实现并通过测试**；M2/M3/M4 仅有设计。设计文档见 `docs/multimodal/`。
> 落地顺序：M1 表情包 → M2 图片理解 → M3 ASR/TTS → M4 唱歌；每个里程碑单独审批。

依赖方向：`adapters` → `qq_service` → `media.router` → `media.providers` → `media.worker_client` → 侧车进程。
`adapters` 不得 import 任何 provider；`media` 不得 import `llm` 与 `tasks`。

| 模块 | 职责 | 依赖 | 被谁依赖 | 状态 |
|---|---|---|---|---|
| `paa.media.contracts` | 媒体数据契约（Capability / MediaResult / StickerPick） | 无 | 全部 media 模块、`qq_service` | ✅ M1 |
| `paa.media.fetcher` | 拉取与隔离校验（协议白名单、MIME、大小、SSRF、随机文件名） | `contracts`、`httpx` | `quarantine`、`router` | ✅ M1.5 |
| `paa.media.quarantine` | 学习线隔离区：收录、去重、配额、晋级/丢弃 | `contracts`、`fetcher`、`stickers`、`providers.sticker_local` | `qq_service`、`scripts/sticker_learn.py` | ✅ M1.5 |
| `paa.media.store` | sha256、临时目录、长期摘要、TTL | `contracts`、文件系统 | `router`、`fetcher` | 设计 |
| `paa.media.router` | 能力路由、开关、限频、去重、审计（不碰数据库，审计由入口注入） | `contracts`、providers、`stickers` | `qq_service` | ✅ M1 |
| `paa.media.providers.*` | Vision / Sticker / ASR / TTS / Music 具体实现 | `contracts`、`worker_client` | `router` | 🚧 仅 `sticker_local` |
| `paa.media.worker_client` | 侧车进程协议（NDJSON over stdio），启动/健康/超时/回收 | 标准库 | providers | 设计 |
| `paa.media.janitor` | 过期临时文件清理 | `store` | `main` 生命周期 | 设计 |
| `paa.media.stickers` | 素材索引、检索、去重、限频、索引重建 | `contracts`、文件系统 | `router` | ✅ M1 |

### 媒体层硬约束

1. 媒体内容与其中文字**只进数据区**，不得拼进角色卡或底线规则区。
2. 媒体内容不得改变 L1/L2/L3 判定（见 `docs/multimodal/security-and-permissions.md`）。
3. 原始语音/图片不写长期记忆；长期只留 sha256 + 摘要。
4. 不把本机绝对路径交给 OneBot 网关（用 base64 或网关可访问的临时路径）。
5. 不复制、不逆向、不再分发 NapCat（其自定义限制性许可禁止修改与商用）。
6. 仓库内零图片、零音频素材；素材只落 `data/`（已被 `.gitignore` 排除）。
7. 媒体能力默认全关，`PAA_MEDIA_*` 显式打开。
