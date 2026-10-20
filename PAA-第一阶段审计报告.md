# PAA 第一阶段：只读环境审计与可行性报告

审计日期：2026-10-18　｜　方式：只读命令 + 两次 Harness 能力探针（未安装、未改配置、未读取任何凭据内容）

> **归档说明（2026-10-19）**：本报告是 2026-10-18 的审计快照，其中的 `D:\AI-Assistant`
> 指当时计划但从未创建的项目根目录。全部 PAA 资料现存放于
> `D:\项目设计\Personal AI Agent（PAA）`；项目正式名称已改为 DSH Companion（DSHC）。

## 0. 结论先行

1. **环境够用，缺件明确**：缺 Docker、WSL2、Playwright、GitHub CLI、Tailscale；Python 栈里缺 FastAPI。其余（Node 24、Git 2.56、PostgreSQL 18.6、Codex CLI）齐备。
2. **Harness 可以当执行引擎用，接口是 CLI**：`dsh --profile <名> --json <任务>` 输出 NDJSON 事件流，支持会话续跑（`--session-id`）、stdin 传任务、独立 `DSH_HOME`。本机实测通过。
3. **Harness 的安全边界是可信的，但审批责任在 PAA 一侧**：headless 模式下沙箱拦截越权操作，且**没有审批通道时一律失败关闭**（实测：工作区外写入被拒，提权请求返回 "no approval channel is available"）。所以 PAA 不能指望 Harness 自己弹窗等人批，必须由 PAA 先做权限裁决。
4. **架构建议：模块化单体 + 两条独立通道**。聊天走直连模型 API（流式、便宜），任务走 Harness 子进程（带工具、带沙箱）。第一阶段不引入 Redis、微服务、云部署。
5. **三条硬风险**：免费模型上游明确可能记录 prompt；QQ 非官方接入有封号与兼容性风险；当前 Harness 更新通道是 `nightly`，CLI 行为可能变。

## 1. 环境清单（实测）

| 项 | 实测结果 | 备注 |
|---|---|---|
| 操作系统 | Windows 11 家庭版 10.0.26200，64 位 | 家庭版无 Hyper-V 管理功能，Docker 需走 WSL2 |
| 硬件 | Ryzen 7 8845H，8 核 16 线程，15.3 GB 内存 | 够本地开发，跑本地大模型不够 |
| 磁盘 | C: 剩 53.9 GB，D: 剩 124.0 GB | 项目放 D 盘没问题 |
| PowerShell | 7.6.5 | |
| Python | Anaconda base 3.14.6（PATH 首位）；py 启动器另有 3.13（`D:\Python\python`） | 已有 conda 环境：base / pt-dqn / pt-dqn-api（不动） |
| Python 包 | 已有 SQLAlchemy 2.0.51、pydantic 2.13.4、uvicorn 0.40.0、httpx、pytest 9.0.3、ruff 0.15.1；**无 FastAPI** | 未装 uv / poetry |
| Node.js | v24.16.0，npm 11.13.0 | 全局包只有 express@5.2.1；pnpm 只有 Codex 自带的那份，非全局安装 |
| Git | 2.56.0.windows.1 | 无 GitHub CLI |
| PostgreSQL | 18.6，服务 `postgresql-x64-18` 运行中（自动启动） | `listen_addresses='*'`，`pg_hba.conf` 只放行回环地址 → 见安全项 S6 |
| Docker | 未安装 | 无 docker 命令、无 Docker 服务 |
| WSL | 未安装（只有 wsl.exe 占位） | 虚拟机监控程序已在运行，装 WSL2 需重启 |
| Codex | codex-cli 0.162.0-alpha.17.2 | alpha 版本，接口可能变 |
| Playwright | 未安装（Python 与 Node 都没有） | 装浏览器内核约 +1 GB |
| Tailscale | 未安装 | 远程访问方案待定 |
| 项目目录 | `D:\AI-Assistant`（当时计划）不存在 | 尚未创建；现资料位于 `D:\项目设计\Personal AI Agent（PAA）` |

## 2. DeepSeek Harness 兼容性

### 2.1 已确认的事实

- 安装形态：Electron 桌面应用，位于 `D:\DeepSeek Harness`，带内置运行时（Node 24.18.1、pnpm 11.7.0）。
- 版本：安装目录 `version` 文件内容 `44.0.0`；CLI `dsh --version` 为 `0.2.0-rc.2`；更新通道 `nightly`（来自 `app-update.yml`）。
- CLI 位置：`D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd`，**不在 PATH 上**。
- 运行模型：`dsh` 启动一个 profile（插件包的叠加层）。可用 app：`headless`、`web`、`tui`；配置文件可用 `--dump-config` / `--dump-config-schema` 导出。
- 两个 home 互相独立：
  - `C:\Users\<用户名>\.dsh`（桌面端，329 MB / 9390 文件，内含 `.credentials.yaml` 登录凭据——**不读、不复制、不进仓库**）
  - `D:\dsh-home`（headless 测试 profile `ofmtest`，自己的会话与插件数据）
- 会话持久化：jsonl，落在 `DSH_HOME/sessions`；`--session-id` 可续跑同一会话。
- 遥测：默认走 OTLP 上报到 DeepSeek 自建收集器，可用 `DSH_TELEMETRY_DISABLED=1` 关闭（本次已关闭）。

### 2.2 headless 能力（从组合后的配置读出，非猜测）

工具面：`pwsh`（Windows 下替代 bash）、文件读写、文件搜索、web 搜索/抓取、skill、todo、goal、subagent（spawn/fork）、workflow、MCP resources、token 计量、上下文压缩。

权限面：三档预设 —— `read-only`、`workspace-write`（默认）、`danger-full-access`；`workspaceRoot` 取进程当前目录；由 `DSH_PERMISSION_MODE` 环境变量覆盖。

### 2.3 实测结果

| 探针 | 结果 |
|---|---|
| `dsh --profile ofmtest --json "Reply with exactly: OK"` | 通过。事件类型：`session` → `status` → `text` → `status(usage)` → `final`。单轮 6032 输入 / 3 输出 token |
| 工作区内写文件再读回 | 通过，8.6 秒，两次工具调用，无权限询问 |
| 写工作区外文件（`..\escape.txt`） | 沙箱拒绝；模型按提示提权重试，返回 `sandbox escalation ... requires approval, but no approval channel is available`，**失败关闭，文件未创建** |

### 2.4 缺口与适配方案

| 缺口 | 影响 | 适配方案 |
|---|---|---|
| 没有公开稳定的 SDK，只有 CLI + NDJSON | 事件格式可能随版本变（nightly） | Harness Adapter 只依赖 `type` 字段的最小集合，未知事件忽略并落原始日志；锁定一个可用版本 |
| headless 无审批通道 | L3 操作无法在 Harness 内部等人工批准 | 审批前移到 PAA：先裁决，再以合适预设派发；L3 永不自动提权 |
| 无内建 HTTP 任务接口 | 无法像调 API 一样并发塞任务 | 每任务一个子进程，进程即并发单元（单用户够用） |
| 桌面端转发端口（127.0.0.1:18899）只在 GUI 运行时可用 | 不能当服务依赖 | 只做可选加速通道，不作为架构基础 |

## 3. 推荐架构

### 3.1 总体形态

模块化单体：一个 FastAPI 进程 + 一个 Postgres + 一个前端构建产物。任务执行以子进程方式外挂 Harness。不上 Redis、不上消息队列、不上微服务。

```
Web (Vue 3)  ──HTTP/WS──┐
QQ Adapter (Phase 3) ───┤
                        ├──> API / Agent Core
                        │      ├─ Policy & Approval（权限裁决、审计）
                        │      ├─ Conversation Service（聊天、人格）
                        │      ├─ Memory Service（长期/项目记忆）
                        │      ├─ Task Engine（队列、超时、取消）
                        │      └─ Token Meter
                        ├──> Model Provider Adapter（OpenAI 兼容）
                        └──> Harness Adapter ──子进程──> dsh headless（沙箱内执行）
```

### 3.2 关键决策

1. **聊天与任务分两条路**。聊天直连模型 API（流式、上下文可控）；任务交给 Harness。理由：实测 headless 单轮基线就 ~6k 输入 token（系统提示 + 工具定义），拿它做闲聊既慢又贵。
2. **Harness 的沙箱不要自己重造**。PAA 只负责「给不给这个任务这个目录」，执行期边界交给 DSH 的 `workspace-write` + 每任务独立工作目录。
3. **Harness Adapter 是唯一的 Harness 依赖点**。其他模块只认 PAA 自己的 `TaskEvent` 抽象（status / text / tool_call / tool_result / usage / final / error）。
4. **记忆存 Postgres，向量后置**。先用全文检索 + 标签 + 明确的项目归属；确有效果瓶颈再上 pgvector（届时需先确认 PG18 的扩展可用性）。
5. **Security Center 只监听 127.0.0.1**，凭据用 Windows DPAPI（或 keyring）加密落盘，API 只暴露「已配置/未配置」和指纹后四位。
6. **QQ 适配器独立进程、独立凭据**，只做消息收发，不具备直接调用工具的权限——所有意图统一进 Policy 层。

### 3.3 目录建议（第二阶段再创建）

```
D:\项目设计\Personal AI Agent（PAA）\
  apps/api/            FastAPI 应用（按模块分包，不拆服务）
  apps/web/            Vue 3 + TS
  paa/adapters/harness Harness 子进程适配器（唯一 DSH 依赖）
  paa/adapters/model   模型供应商适配
  paa/adapters/qq      消息适配（Phase 3）
  paa/core             Agent Core、策略、审批
  paa/services         memory / tasks / security / usage
  paa/executor/win     Windows 执行器（白名单 + 审计）
  migrations/          Alembic
  tests/
  docs/
```

## 4. 数据库规划（Postgres 18）

| 表 | 作用 | 关键点 |
|---|---|---|
| `users` | 单用户起步 | 预留多用户，不自建密码体系 |
| `conversations` / `messages` | 聊天与人格上下文 | 消息带 `source`（web/qq/task）与 `trust_level` |
| `memories` | 长期记忆 | 类型（事实/偏好/事件）、置信度、来源消息、可删除 |
| `project_memories` | 项目级记忆 | 绑定项目路径 hash，不存绝对私人路径 |
| `agent_tasks` | 任务 | 状态机、超时、取消、工作目录、权限等级 |
| `tool_calls` | 工具调用明细 | 关联任务、参数摘要、结果摘要、是否被拒 |
| `devices` | 设备授权 | 设备指纹、公钥、最后在线 |
| `approvals` | 人工审批 | 请求快照、批准人、有效期、一次性 |
| `audit_logs` | 审计 | 只追加，含拒绝原因 |
| `token_usage` | 用量与费用 | 按供应商/模型/会话/任务聚合 |

迁移用 Alembic；备份用 `pg_dump` 定时任务 + 校验脚本（第三阶段）。

## 5. 安全审查

| # | 风险 | 现实依据 | 措施 |
|---|---|---|---|
| S1 | 免费模型上游记录 prompt | `D:\dsh-bridge\README.md` 明确写明 Kilo 免费池「prompt 可能被上游记录」 | 私人聊天、记忆内容只走官方 API 或本地模型；免费通道仅用于可公开的任务 |
| S2 | QQ 登录态泄露 / 封号 | 非官方协议，需常驻登录态 | 专用小号、独立配置目录、会话文件排除在 Git 外、可一键撤销；不作为唯一入口 |
| S3 | Prompt Injection（网页/QQ 内容注入指令） | Harness 工具体系可执行 pwsh | 外部内容标注来源且进「数据区」；工具白名单按入口分级；QQ 消息不得直接转成任务 |
| S4 | 任意命令执行 | `dsh-tool-pwsh` 存在且默认可用 | 按任务分配最小工作目录；L1 用 read-only 预设；命令白名单 + 审计；禁止 `danger-full-access` 自动授予 |
| S5 | 凭据泄露 | 桌面端有 `.credentials.yaml`，桥接脚本读 `settings.json` 里的 forwardKey | 项目内凭据只走 DPAPI/keyring；日志脱敏中间件；pre-commit 密钥扫描（gitleaks/detect-secrets） |
| S6 | 数据库暴露 | `listen_addresses='*'`，但 hba 仅回环 | 现阶段风险低（hba 已拦），建议后续改成 `localhost` 并重启一次；云上必须绑内网/仅回环 |
| S7 | 远程执行 | 未来 Windows Executor 暴露给云端 | 默认不监听公网；优先 Tailscale；每设备密钥 + 一次性审批 + 超时 |
| S8 | 日志泄露 | 任务日志天然含路径与内容 | 结构化日志 + 字段级脱敏；日志目录排除 Git；保留期策略 |
| S9 | GitHub 误提交 | 未来公开仓库 | `.gitignore` 先于首次提交；`.env.example` 只放占位；CI 跑密钥扫描 |

## 6. 资源需求

- **本地磁盘**：代码 + venv + node_modules ≈ 1.5 GB；Playwright 内核 ≈ 1 GB；合计留 5 GB 足够（D 盘现有 124 GB）。
- **本地内存**：开发期常驻 < 3 GB，15.3 GB 充裕。
- **云服务器（第四阶段）**：2 vCPU / 4 GB / 40 GB 起步即可（阿里云 Ubuntu 24.04），按量或包月约 ¥80–150/月。
- **域名与备案**：若走大陆公网域名需 ICP 备案；若只用 Tailscale 内网访问，可完全跳过。
- **模型费用**：以官方 API 为主；实测 headless 单任务基线 ~6k 输入 token，任务型调用要按「每任务 1–3 万 token」估算预算。

## 7. 需要你确认的操作（未执行）

1. 在 `D:\项目设计\Personal AI Agent（PAA）` 创建骨架与文档（当前仅有审计与设计资料）。
2. 建独立 conda 环境（建议 Python 3.13，命如 `paa`），装 FastAPI / SQLAlchemy / Alembic / pytest / ruff。
3. 为 PAA 建**独立的** DSH home（如 `D:\项目设计\Personal AI Agent（PAA）\runtime\dsh-home`）与专用 profile，与桌面端和 `ofmtest` 隔离。
4. 是否引入官方 DeepSeek API Key（你自己在 Security Center 里填，不经过对话）。
5. 是否安装 Docker Desktop + WSL2（需重启；第四阶段前可不装）。
6. Playwright 与 Tailscale 何时装（第三、四阶段）。

## 8. 与你原始描述的偏差（需要你知道）

1. **「云端长期记忆 / 云端调度」现在没法验证**。服务器未购买，第一阶段只能做本地可迁移设计；不要把云假设写进代码。
2. **把 Harness 当「AI 核心」有风险**。它是 `nightly` 通道的桌面应用，CLI 才 `0.2.0-rc.2`。PAA 的核心应是自己的 Agent Core，Harness 只是「执行适配器」之一。
3. **QQ 是合规与稳定性风险，不是工程量风险**。工程上几天能跑通，账号层面随时可能被封。
4. **Python 3.14 是 base 环境现状，不建议直接拿来建项目**。第三方 wheel（如 asyncpg、pgvector 驱动）在新版本上偶有滞后，专用环境固定 3.13 更稳。
5. **Docker 在 Windows 11 家庭版上必须先有 WSL2**，这会改系统并需要重启，属于「需确认」范围。

## 9. 本次跳过的

- 未读取任何凭据文件（`.credentials.yaml`、`settings.json`、`api-key`、`.env`）。
- 未安装任何软件、未修改 PATH/环境变量/服务配置、未重启服务。
- 未测试 `danger-full-access` 预设与 web/tui profile（无必要且会扩大权限面）。
- 未验证 PG18 上 pgvector 的可用性（第二阶段确有用量需求时再查）。
