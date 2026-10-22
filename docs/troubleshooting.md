# 常见问题

> 每条都来自真实踩坑记录。日志默认在 `logs/paa-serve.log`（JSON，一行一条）。

## 机器人显示在线，但不回复

1. 打开维护台，看顶部状态条：**NapCat / QQ 账号** 是不是红的
2. 红 → NapCat 未启动或未登录；灰 → `.env` 没配
3. 都绿但仍不回 → 查 `logs/paa-serve.log` 有没有 `收到消息`
4. 看是否是配额熔断：`/api/usage` 的 `remaining` 是否为 0

## NapCat 启动报 `Cannot find module ... loadNapCat.js`

NapCat 与 QQ 版本不匹配。用 **自带 QQ 的一键包**，不要手改 QQ 安装目录。

## `NapCatWinBootMain.exe 不是内部或外部命令`

以管理员身份运行时工作目录变成 `System32`。在 `napcat.bat` 开头加：

```bat
cd /d "%~dp0"
```

## WebSocket 连不上，提示 `did not receive a valid HTTP response`

系统代理劫持了回环连接。代码已固定 `proxy=None`；自写脚本时同样要禁用代理。

## 维护台打不开 / 401

- 401：需要令牌，见 `%USERPROFILE%\.paa\ui.token`
- 页面是旧版：Ctrl+F5；服务已发送 `no-store`
- 地址：默认 `http://127.0.0.1:8000/`，若绑定 Tailscale 则用对应 IP

## PowerShell 脚本报"字符串缺少终止符"

脚本存成了无 BOM 的 UTF-8，Windows PowerShell 5.1 按 GBK 解码。用「UTF-8 with BOM」重新保存。

## `alembic.ini` 报 UnicodeDecodeError

该文件被工具以本地编码读取，注释只能写 ASCII。

## 模型返回 404 / 已下线

免费模型池会下线。改 `dsh-home/profiles/<name>/cordis.patch.yml` 里的 `model:` 为当前可用值。

## 数据库口令丢失

1. 备份 `pg_hba.conf`
2. 临时把 `127.0.0.1/32` 改为 `trust`，`SELECT pg_reload_conf()`
3. `ALTER ROLE ... PASSWORD '...'`
4. 恢复 `pg_hba.conf` 并再次 reload

## 重启后服务没起来

看 `logs/watchdog.log`。看门狗每分钟检查 PAA / NapCat / DSH；若它自己没运行，检查启动文件夹里的 `.vbs`。
