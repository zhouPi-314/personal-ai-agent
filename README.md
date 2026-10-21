# Personal AI Agent（PAA）

## 当前状态

- 阶段：阶段 0（环境与边界）完成，进入阶段 1（骨架与记忆）。
- 代码：骨架已建立，可运行一个健康检查接口；无业务逻辑、无数据库连接。
- 现行项目根目录：`D:\项目设计\Personal AI Agent（PAA）`
- 历史名称与编号：原“基于 DeepSeek Harness 的云端记忆与跨设备协同私人智能体系统03”；
  正式名称为 **DSH Companion（DSHC，DSH 灵犀）**，PAA 为历史项目代号。

## 文件说明

| 文件 | 内容 |
| --- | --- |
| [DSH_Companion_项目设计构想.md](DSH_Companion_项目设计构想.md) | 产品定位、总体架构、能力边界与风险 |
| [PAA-第一阶段审计报告.md](PAA-第一阶段审计报告.md) | 2026-10-18 的本机环境、Harness 兼容性与推荐架构 |
| [PAA ECS 安全审计与配置待确认清单.md](PAA%20ECS%20安全审计与配置待确认清单.md) | 阿里云 ECS 的只读审计记录与待确认项 |
| [PAA-参考分析-ai-companion-kit.md](PAA-参考分析-ai-companion-kit.md) | 开源陪聊项目的设计拆解：可借鉴项、不可照搬项、PAA 的差异点 |
| [ecs-audit.sh](ecs-audit.sh) | ECS 只读审计脚本 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 双通道架构、模块职责与依赖方向 |
| [SECURITY.md](SECURITY.md) | 威胁模型、权限分级、凭据与仓库卫生 |
| [ROADMAP.md](ROADMAP.md) | 阶段划分与退出条件 |
| [STATUS.md](STATUS.md) | 当前阶段、进度与待办（每次会话更新） |
| [DEBT.md](DEBT.md) | 技术债台账：推迟了什么、什么时候必须解决 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 本地环境、测试与提交约定 |
| [docs/database.md](docs/database.md) | 数据库表设计与取舍理由 |
| [AGENTS.md](AGENTS.md) | 对 AI 代理的硬性约束（建仓库顺序、禁止项） |
| [scripts/secret-scan.ps1](scripts/secret-scan.ps1) | 提交前的密钥与信息扫描 |

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn paa.main:app --port 8000
```

接口：`GET /healthz` → `{"status":"ok"}`。

配置全部来自环境变量（前缀 `PAA_`），见 `.env.example`；`.env` 不会入库。

## 常驻运行

`scripts/run_paa.ps1` 是一个自重启循环（进程退出后 5 秒重拉），日志由 Python 直接写入
`logs/paa-serve.log`（UTF-8 JSON）。

开机自启：把指向它的 `.vbs` 放进 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`，
这样登录后不弹窗口直接运行。停掉服务 = 结束 `run_paa.ps1` 的 powershell 进程。

看门狗 `scripts/watchdog.ps1` 每分钟检查三件事，缺哪个补哪个：PAA 服务、NapCat、本机 DSH。

电源要求（否则息屏后会掉线）：

```powershell
powercfg /change standby-timeout-ac 0     # 插电时永不待机
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 10    # 屏幕 10 分钟熄灭，系统保持运行
```

锁屏（Win+L）不影响进程；**待机/休眠会挂起进程**，NapCat 与 PAA 都会掉线。

## 备份

```powershell
pwsh -File scripts/backup.ps1            # 本地备份（保留 7 份，自动校验归档）
pwsh -File scripts/backup.ps1 -Upload    # 额外加密上传到 ECS（远端保留 8 份）
```

- 本地文件落在 `backups/`（已 gitignore）
- 加密口令读取 `%USERPROFILE%\.paa\backup.key`，**不要**与数据库密码相同，也不要提交到仓库
- 备份文件用 `pg_restore --list` 校验结构；真正的恢复演练记录在 `STATUS.md`

## 工具

- REA（逆向分析 MCP）：装在 `D:\Tools\rea`，已注册到 Codex 的 `mcp_servers.rea`，`D:\Tools\rea` 已加入用户 PATH。
- 原生分析引擎（Ghidra/IDA/Hopper/JADX）未安装；JS/Electron/网页分析不需要它们。

## 迁移说明

2026-10-19，原编号 03 的设计文档与此前的 PAA 审计材料已集中到本目录。
原任务书计划的项目根目录 `D:\AI-Assistant` 从未创建；审计报告中“该目录不存在”是
2026-10-18 的历史事实，不代表当前路径。当前没有代码或部署，因此本次迁移不涉及运行路径。

今后新增代码时，应直接放在本目录下，并通过仓库相对路径或环境变量定位资源；
不要硬编码旧的 `D:\AI-Assistant` 或本次迁移前的目录。

## 边界

- QQ 接入、ECS 部署、模型凭据配置均**尚未实施**。
- 服务器已完成基础加固；agent 运行时**不得**使用具备 sudo 的运维账号。
