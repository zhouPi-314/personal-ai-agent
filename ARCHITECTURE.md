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
| `paa.main` | HTTP 入口 | `config` | — |
