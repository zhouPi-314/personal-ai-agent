# Personal AI Agent (PAA)

> 一个跑在自己电脑上的私人 AI 智能体：QQ 陪聊、长期记忆、受控任务执行。
> A self-hosted personal AI agent: QQ chat, long-term memory, sandboxed task execution.

![Python](https://img.shields.io/badge/python-3.13-3776ab)
![Tests](https://img.shields.io/badge/tests-153%20passed-2ea44f)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-v0.1%20usable-orange)

## 它是什么

PAA 不是一个"聊天框应用"，而是把 AI 放进日常通讯工具里的一层基础设施：

- **聊天在 QQ**，不在网页。你像跟人聊天一样跟它说话。
- **记忆在本地 PostgreSQL**，按人存储，可追溯来源、可撤销。
- **任务走沙箱**：模型可以读写工作目录，但出界会被拒绝。
- **所有操作留痕**：每次工具调用与权限决策都有审计记录。

## 功能

| 模块 | 能力 |
|---|---|
| 对话 | QQ 私聊全链路；群聊仅在被 @ 或主人发言时响应 |
| 记忆 | 性格 / 事实 / 话题 / 待办四类，带来源与置信度，可撤销 |
| 人格 | Markdown 角色卡 + 代码内置底线规则（不可被角色卡覆盖） |
| 模型 | OpenAI 兼容；本地优先、云端兜底的混合路由 |
| 任务 | 状态机、超时、取消、重启恢复；子进程沙箱执行 |
| 安全 | L1/L2/L3 分级、一次性审批、只追加审计 |
| 用量 | token 记录、按天聚合、可编辑价格表、每日配额熔断 |
| 运维 | 维护台（状态/消息/记忆/任务/审计）、看门狗、备份 |

## 架构

```
QQ ── OneBot v11 ── NapCat
                     │
              ┌──────┴──────┐
              │  PAA 服务    │  FastAPI (+ 维护台)
              └──────┬──────┘
        ┌────────────┼─────────────┐
     PostgreSQL   Harness 适配器   模型路由
     （记忆/消息）  （dsh 子进程）   本地 DSH / 云端 API
```

模块之间只通过接口通信，依赖单向向下。详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 快速开始

前置：Windows 10/11、Python 3.13、PostgreSQL 16+、Node.js（NapCat 需要）。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env          # 填写数据库与模型配置
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m paa.serve
```

打开 `http://127.0.0.1:8000/` 查看维护台。完整步骤见 [docs/deployment.md](docs/deployment.md)。

## 运行环境

| 项 | 最低 | 建议 |
|---|---|---|
| 内存 | 8 GB | 16 GB |
| 磁盘 | 5 GB 空闲 | 20 GB（含备份） |
| 系统 | Windows 10 | Windows 11 |
| Python | 3.13 | 3.13 |
| 数据库 | PostgreSQL 16 | PostgreSQL 18 |

不需要 GPU：默认使用本机 DSH 或云端 API，不在本地跑大模型。

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 环境审计与边界 | ✅ |
| 1 | 骨架与记忆 | ✅ |
| 2 | 聊天通道 | ✅ |
| 3 | 任务通道 | ✅ |
| 4 | 入口与部署 | ✅ |
| 5 | 用量与费用 | ✅ |
| 6 | 云端部署 | ❌ 已取消（改为纯本地） |

细节与检查项见 [STATUS.md](STATUS.md)，待办与技术债见 [DEBT.md](DEBT.md)。

## 已知问题

见 [docs/troubleshooting.md](docs/troubleshooting.md)。最常见的三个：

- NapCat 版本与 QQ 版本不匹配 → 用自带 QQ 的一键包
- 回环地址被系统代理劫持 → 代码已固定 `proxy=None`
- 重启后 NapCat 未自启 → 看门狗一分钟内自动拉起

## 路线图

见 [ROADMAP.md](ROADMAP.md)。近期方向：

- 多用户与多会话（当前单用户）
- 记忆检索升级（全文 → 可选向量）
- 定时任务与主动消息
- 图片理解、语音输入输出
- 插件式工具扩展

## 参与

欢迎提 Issue、发 PR、给建议：

- **反馈问题**：请附日志片段（`logs/paa-serve.log`）与复现步骤，**不要贴任何凭据**
- **贡献代码**：先读 [CONTRIBUTING.md](CONTRIBUTING.md)，提交前跑 `pytest` 与 `ruff`
- **安全披露**：见 [SECURITY.md](SECURITY.md)，不要公开提交漏洞细节

这个项目还很早期，1 人维护。任何"这里可以更简单"的建议都很受欢迎。

## 许可

[MIT](LICENSE)
