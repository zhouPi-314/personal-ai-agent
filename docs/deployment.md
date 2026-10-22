# 部署指南

## 一、本地部署（当前唯一支持的形态）

适用：Windows 10/11，单用户，电脑开机时在线。

### 1. 准备软件

| 软件 | 版本 | 用途 |
|---|---|---|
| Python | 3.13 | 运行 PAA |
| PostgreSQL | 16+ | 记忆、消息、任务、审计 |
| Node.js | 22+ | NapCat 运行时 |
| Git | 任意 | 拉取代码 |

### 2. 建库

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -U postgres -d postgres
```

```sql
CREATE ROLE paa_dev LOGIN PASSWORD '<自定义口令>';
CREATE DATABASE paa_dev OWNER paa_dev;
\q
```

### 3. 安装项目

```powershell
git clone <仓库地址> && cd personal-ai-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
```

`.env` 关键项：

```ini
PAA_DATABASE_URL=postgresql+psycopg://paa_dev:<口令>@127.0.0.1:5432/paa_dev
PAA_LOCAL_BASE_URL=http://127.0.0.1:18900/v1   # 本机 DSH 的 OpenAI 兼容端口
PAA_LOCAL_API_KEY=<DSH 的 forwardKey>
PAA_LOCAL_MODEL=<模型名>
PAA_PERSONA_PATH=persona.md
PAA_USER_NAME=owner
```

### 4. 初始化

```powershell
.\.venv\Scripts\alembic.exe upgrade head
copy persona.example.md persona.md     # 改成你自己的人格
.\.venv\Scripts\python.exe -m pytest -q
```

### 5. 启动

```powershell
.\.venv\Scripts\python.exe -m paa.serve
```

访问 `http://127.0.0.1:8000/`。

### 6. 接 QQ（可选）

1. 安装 NapCat（推荐使用自带 QQ 的一键包，避免版本不匹配）
2. 用小号登录，配置 OneBot v11：HTTP `127.0.0.1:3000`、WebSocket `127.0.0.1:3001`
3. `.env` 填 `PAA_ONEBOT_*` 与 `PAA_OWNER_QQ`
4. 重启 PAA

### 7. 常驻运行（可选）

- `scripts/run_paa.ps1`：自重启循环
- `scripts/watchdog.ps1`：每分钟检查 PAA / NapCat / DSH，缺哪个补哪个
- 把指向 watchdog 的 `.vbs` 放进启动文件夹即可开机自启
- 电源设置：插电时永不待机，屏幕可熄灭

### 8. 备份（可选）

```powershell
pwsh -File scripts/backup.ps1        # 本地，保留 7 份
```

建议用计划任务每天凌晨执行。恢复演练：

```powershell
pg_restore -d <临时库> backups\paa_dev-<时间>.dump
```

## 二、云端部署（未实现）

状态：**已取消**。当前版本不依赖任何云服务，云端相关代码以注释形式保留。

若将来重新考虑，需要先验证以下前提：

| 前提 | 说明 |
|---|---|
| NapCat 能在 Linux 登录 | 未验证，是最大不确定性 |
| 模型改为官方 API | 本机 DSH 云上不可达 |
| 数据迁移 | `pg_dump` / `pg_restore`，需重新做恢复演练 |
| QQ 风控 | 云 IP + Linux 客户端可能触发验证 |

历史方案与估算见 [migration-plan.md](migration-plan.md)（已标记取消）。
