# 参与开发

## 可以怎么参与

| 方式 | 说明 |
|---|---|
| 提 Issue | 描述现象 + 复现步骤 + 日志片段，不要贴凭据 |
| 提 PR | 小而聚焦，一个 PR 解决一个问题 |
| 给建议 | "这里可以更简单"同样是有价值的贡献 |

如果你只是想用它，不需要改代码——按 `docs/deployment.md` 走一遍即可。

## 环境

需要 Python 3.13+。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 常用命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 测试
.\.venv\Scripts\ruff.exe check src tests          # 静态检查
.\.venv\Scripts\python.exe -m uvicorn paa.main:app --reload --port 8000
```

## 提交前

1. `pytest` 全绿、`ruff check` 无报错。
2. 没有 `.env`、数据文件、密钥进入暂存区。
3. 新增配置项时同步更新 `.env.example`。

## 仓库初始化顺序（硬性准则）

新建仓库、迁移仓库或重建历史时，顺序不可调换：

| 步骤 | 动作 | 通过标准 |
|---|---|---|
| 1 | 写 `.gitignore` | 覆盖 `.env`、`.venv`、`data/`、`logs/`、`*.pem`/`*.key` |
| 2 | 写 `.env.example` | 只有空占位，无任何真实值 |
| 3 | 跑 `pwsh -File scripts/secret-scan.ps1` | 输出 `OK: no secrets or identifying info found` |
| 4 | `git init` | 前三步全部通过之后才执行 |
| 5 | `git status --short` 复核 | 看不到 `.env`、`.venv`、`data/`、`logs/` |
| 6 | 首次提交 | 提交信息说明这是初始骨架 |

为什么顺序不能反：`.gitignore` 是**事后无效**的——一旦文件被跟踪，加规则不会让它消失；进入历史后只能重写历史或轮换凭据。

误提交后的正确处理：先轮换已泄露的凭据（视为已泄露），再重写历史；只删文件等于没处理。

## 不要提交

- 任何真实凭据、服务器地址、个人路径
- `.venv/`、`data/`、`logs/`
- 与本次改动无关的格式化噪音

## 代码约定

- 模块按 `ARCHITECTURE.md` 的分层放置，依赖只向下。
- 新增分支/循环/解析逻辑时同时提交测试。
- 已知限制用 `shortcut: <限制>, <何时升级>` 注释标注。
- `alembic.ini` 等被工具以本地编码读取的配置文件，注释只用 ASCII——中文 Windows 下会以 GBK 解码而报错。
