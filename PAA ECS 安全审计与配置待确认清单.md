# PAA ECS 安全审计与配置待确认清单

日期：2026-10-18　｜　阶段：独立安全初始化　｜　状态：**只读审计未完成（无访问权限，已阻塞）**

> **归档说明（2026-10-19）**：本文件已随 PAA 资料集中到
> `D:\项目设计\Personal AI Agent（PAA）`；文中“待实测”结论仍以服务器实际输出为准。

> 本文件按任务书第 5 节交付。因为当前没有可达的服务器访问路径，**第 4–8 节是待实测清单，不是审计结论**。凡标注「待实测」的项目都必须用脚本输出核对后才能确认。

## 1. 访问权限结论：不具备

三项检查全部为否，互相独立，任一项都足以阻断：

| 检查 | 结果 | 证据 |
|---|---|---|
| 本机是否有 SSH 密钥/配置 | 无 | `C:\Users\<用户名>\.ssh` 不存在，目录内文件数 0；无 config、无 id_rsa/id_ed25519 |
| 是否有阿里云 CLI / AccessKey 配置 | 无 | `aliyun` 命令不存在；`C:\Users\<用户名>\.aliyun` 不存在 |
| 是否能出网连接 | 不能 | `223.5.5.5:443`、阿里云官网解析地址 `:443`、`1.1.1.1:443` 均不可达；`curl https://www.aliyun.com` 返回 000；DNS 可解析 |

我没有对服务器、云账号或本地环境做任何写操作，也没有读取任何凭据。即使知道公网 IP，第二条和第三条仍然会让 SSH 连不上。

## 2. 授权与连接路径（三选一）

**方案 B（建议，今天就能推进）**：你在阿里云控制台用 Workbench 远程连接进服务器，执行我准备的只读脚本，把输出贴回来。

- 优点：零凭据传递，我立刻能给出真实审计结论。
- 代价：需要你操作几次复制粘贴。

**方案 A（后续要由我直接配置时需要）**：本机放一把专用 SSH 私钥 + 会话具备出网权限。

- 前提 1：本机生成密钥对（我可以给命令，私钥不出本机），公钥由你加到服务器。
- 前提 2：当前 Codex 会话的沙箱禁止出站 TCP，需在允许网络访问的会话中运行。
- 注意：私钥文件不要贴到聊天里，直接放在本机路径上即可。

**方案 C（不建议）**：用 AccessKey 走阿里云 CLI。AccessKey 权限过大、当前也无网络，收益低于风险，只有在需要 API 化批量核查时才值得考虑。

## 3. 只读审计执行步骤（方案 B）

1. 打开 ECS 控制台 → 「实例与镜像 > 实例」→ 打开该实例 → 「远程连接」→ **Workbench 远程连接**，以 root 登录。
2. 上传或粘贴 [ecs-audit.sh](ecs-audit.sh) 内容，保存为 `ecs-audit.sh`。
3. 执行：`sudo bash ecs-audit.sh > audit.txt 2>&1`，然后 `cat audit.txt`。
4. 把输出整段贴回来。

脚本只读：不装包、不改配置、不重启、不写业务文件；输出已屏蔽 IP、实例 ID、凭据，只保留脱敏摘要。

## 4. 现状核查表

### 4.1 已由登录横幅验证（2026-10-18 22:59 登录，MOTD 输出）

| 项目 | 实测值 |
|---|---|
| 系统盘 | 39.01 GB，已用 5.9%（≈2.3 GB），可用 ≈36.7 GB |
| 内存占用 | 15%（2 GiB 机型，空载约 300 MB） |
| 系统负载 | 0.0，进程 123 个 |
| Swap 使用 | 0%（是否存在待命令确认） |
| 可立即应用的更新 | 0 个 |
| 软件包索引 | 超过一周未刷新，实际可升级数量未知 |
| ESM Apps | 未启用；有 2 个安全更新只能通过 ESM Apps 获得 |
| 登录身份 | root，经 Workbench 免密连接 |
| 内网地址 | 172.30.x.x（VPC 内网，非公网） |
| 可升级软件包 | **80 个**（刷新索引后实测） |
| 是否需要重启 | 否（`/var/run/reboot-required` 不存在） |
| 时区 / 时间同步 | Asia/Shanghai（CST +0800），clock synchronized: yes，NTP active |
| Swap | **无**（SwapTotal 0 kB），MemTotal ≈ 1.7 GiB |
| 日志占用 | 8.0 MB（journald） |
| SSH 监听 | `0.0.0.0:22` 与 `[::]:22`（IPv4/IPv6 双栈） |
| 其他监听 | 仅回环：chronyd 323、systemd-resolved 53、阿里云 hbrclient 127.0.0.1:44943 |
| SSH 认证配置 | `passwordauthentication no`、`pubkeyauthentication yes`、`maxauthtries 6`、`port 22` |
| root 远程登录 | `permitrootlogin yes`（因密码认证已关，实际仅密钥可用） |
| UFW | `inactive` |
| 账户 | `sudo` 组成员为空；无 uid≥1000 的普通用户；唯一可用身份是 root |
| 访问路径 | **只有 Workbench 一条**（无本机私钥、密码认证已关） |
| `/root/.ssh` | 目录存在（700），`authorized_keys` 存在但为 **0 字节**；说明 Workbench 走会话管理通道，不靠 SSH 公钥 |

| 项目 | 判定方式 | 当前结论 |
|---|---|---|
| 地域/可用区/实例规格 | 元数据 `placement/region`、`instance-type` | 待实测（预期：西南1 成都，2 vCPU / 2 GiB） |
| 系统版本/内核 | `/etc/os-release`、`uname -r` | 待实测 |
| 磁盘容量与剩余 | `df -h`、`lsblk` | 待实测（预期：40 GiB ESSD Entry 系统盘） |
| 公网 IP 是否分配 | 元数据 `eipv4` 是否为空 | 待实测（只输出 assigned / none） |
| 安全组关联数量 | 元数据 `security-group-ids` 计数 | 待实测 |
| SSH 服务状态与策略 | `systemctl is-active ssh`、`sshd -T` | 待实测 |
| 系统账户与 sudo 成员 | `passwd`、`getent group sudo` | 待实测 |
| UFW 状态 | `ufw status verbose` | 待实测（Aliyun 镜像通常未启用） |
| 更新状态/是否需重启 | `apt list --upgradable`、`/var/run/reboot-required` | 待实测 |
| 时间同步 | `timedatectl` | 待实测（预期 UTC，同步开启） |
| Swap | `swapon --show`、`/proc/meminfo` | 待实测（2 GiB 机型常无 swap） |
| 已装服务 | `dpkg-query` 逐个查 | 待实测（预期 docker/postgres/redis 均未装） |

**控制台侧必须由你看的**（脚本读不到）：

- 安全组入/出方向规则与优先级。
- 计费方式：实例预付费到期日、带宽是否按流量计费、¥0.80/GB 的计费方向（通常只计出方向，需以账单页为准）。
- 自动续费状态、余额、是否已配置任何预算或预警。

## 5. 安全组审计表（实测）

> 只有一个安全组（系统创建，普通安全组，2026-10-18 22:38 创建），关联 1 台实例，出方向未查看。
> 阿里云安全组是白名单模型，未显式放行的一律拒绝。

| 优先级 | 协议 | 端口 | 授权对象 | 用途 | 风险 | 建议 |
|---|---|---|---|---|---|---|
| 100 | 自定义 TCP | 3389 | `0.0.0.0/0` | 无（Ubuntu 上没有 RDP 服务） | **高**：公网暴露 RDP 端口，扫描器必扫，纯攻击面 | 删除 |
| 100 | ICMP-IPv4 | 全部 | `0.0.0.0/0` | ping | 低 | 保留（排查连通性有用） |
| 100 | 自定义 TCP | 22 | `0.0.0.0/0` | SSH | 中：密码认证已关闭，实际仅密钥可爆破 | 本次先保留供我们接入，验证密钥后收敛到固定 IP /32 |

补充结论：

- **无 IPv6 入方向规则**，因此 sshd 虽然监听 `[::]:22`，公网 IPv6 实际进不来。
- 无 80/443/5432/6379/8000 规则，符合预期，不需要改动。
- 3 条规则互相独立，删除 3389 不影响 SSH。
| 出方向 | 保持默认全放行 | 低 | 本阶段不动，避免影响 apt/API |

判断要点：若存在 `0.0.0.0/0` 的 22 端口，那是当前唯一直接的风险面；在启用密钥登录并验证 Workbench 可用之前，**不要动它**。

## 6. 拟修改清单（未执行，逐项待批）

顺序不可打乱：先建立新入口，再收紧旧入口，最后才动系统层。

| # | 项目 | 拟改内容 | 前提 | 风险 | 回滚 | 验证 |
|---|---|---|---|---|---|---|
| 1 | SSH 公钥登录 | 本机生成 ed25519 密钥对（私钥留本机），公钥写入**新建的管理用户**；密码认证已是 `no`，**没有公钥就等于没有 SSH** | 你本机生成，我只给命令 | 公钥/权限位写错仍然只能靠 Workbench | 删掉 `authorized_keys` 中该行 | 新开终端用密钥登录成功 |
| 2 | 管理用户 | 新建普通用户并加入 sudo 组（当前 sudo 组为空、无 uid≥1000 用户） | #1 已验证 | 组配置错误导致 sudo 不可用 | 用 root 经 Workbench 修正 | `id`、`sudo -l`、密钥登录均正常 |
| 3 | 关闭 root 远程登录 | `PermitRootLogin no`（`PasswordAuthentication` 已是 no，无需改动） | #1 #2 验证通过，且 Workbench 冷启动可登录 | **锁死风险**：只剩 Workbench 一条路 | Workbench 改回配置并 `systemctl reload ssh` | 重载前 `sshd -t`；重载后另开终端验证 |
| 4 | 安全组 22 收敛 | 入方向 22 从 `0.0.0.0/0` 改为你的固定 IP /32 | 确认你的出口 IP 是否固定 | IP 变动会失去 SSH | 控制台把规则改回 | 用新规则登录一次 |
| 5 | 安全组清理 | 关闭 3389/80/443/5432/6379/8000 等无业务端口 | 先导出现有规则快照 | 误删必要规则 | 按快照逐条恢复 | 端口扫描/`nc` 探测确认关闭 |
| 6 | UFW | 当前 `inactive`。启用时默认拒绝入站、放行出站，仅放 22（含 IPv6） | **先确认安全组已放行 22** | 两层策略不一致会锁死 | Workbench 执行 `ufw disable` | `ufw status verbose` + 新终端登录 |
| 7 | 系统更新 | 实测 **80 个包可升级**；先只升安全更新，`unattended-upgrades` 启用 | 先列出安全类包清单 | 一次性全量升级在 2 GiB 内存下有 OOM 风险；内核更新会要求重启 | `apt` 日志 + 逐包回退 | 升级后 `reboot-required` 状态、服务正常 |
| 8 | 日志上限 | `journald` 设 `SystemMaxUse=500M` | 磁盘余量确认 | 历史日志被裁剪 | 恢复配置并 `systemctl restart systemd-journald` | `journalctl --disk-usage` |
| 9 | 时区 | **不改**，已是 Asia/Shanghai 且 NTP 正常 | — | 改回 UTC 反而与你本地时间脱节 | — | — |
| 10 | Swap | 本阶段**只评估不启用**；后续建议加 2 GiB swapfile | 有 PAA 服务常驻时 | 无 swap 时 OOM 直接杀进程 | `swapoff` + 删文件 | `swapon --show` |
| 11 | 费用预警 | 控制台设月度预算 ¥10 / ¥20 两档 | 你确认档位 | 预警不等于停服 | 删除预算规则 | 预算页显示生效 |
| 12 | 自动续费 | 只核查，不改 | — | 误关续费可能导致到期停机 | 控制台改回 | 续费管理页状态 |
| 13 | Ubuntu Pro / ESM Apps | 挂接免费订阅以获取 2 个待发安全更新 | 你同意创建 Ubuntu One 账号 | 引入第三方账号依赖；离线订阅令牌需妥善保存 | 控制台 detach 订阅 | `pro status` 显示 ESM Apps 已启用 |

## 7. 费用与资源核查（控制台，待填）

路径以控制台当前名称为准：

- 账单：右上角「费用」→ 费用与成本 → 账单详情。
- 预算：费用与成本 → 成本管理 → 预算管理 → 新建预算（月度 ¥10 / ¥20，仅提醒）。
- 续费：用户中心 → 续费管理 → 查看自动续费与到期日。
- 流量：ECS 实例 → 监控 → 公网流量；按量明细在账单里。

必须区分两件事：**实例是包年包月（预付费，¥0/小时）**，**公网流量是按量计费（¥0.80/GB，3 Mbps 为带宽上限）**。预警不会自动停机，超量照样计费。

粗算：QQ 文本消息流量极小，正常使用每月出方向大概率 < 1 GB；但系统更新、日志外传、备份上传都会计入，仍建议设 ¥10–20 的月预算提醒。

## 8. 资源现状与基础风险（2 vCPU / 2 GiB / 40 GiB）

- **内存是瓶颈**。Ubuntu 24.04 空闲约 400–600 MB，Postgres + FastAPI + 反代常驻约 500–700 MB；无 swap 时余量很薄。后续要么加 2 GiB swap，要么把数据库放外部。
- **磁盘够用但不宽裕**。系统约 8–10 GB，journald 默认上限是磁盘的 10%（≈4 GB），建议显式设 500 MB。
- **3 Mbps 是峰值带宽**，不是月流量包；按量计费下大文件传输要留意账单。
- **2 vCPU** 编译型任务慢，`pip install` 有 wheel 的包没问题；不要在这台机上构建大型镜像。
- 中国内地地域：后续对公网提供服务的备案与合规问题，本阶段只记录，不处理。

## 9. 执行计划（待批准，尚未执行任何一条）

### 批次 A：建立可验证的 SSH 入口（建议先批这一批）

在 Workbench（root）中执行：

```bash
adduser paa                        # 交互式；密码只用于 sudo，不能用于 SSH 登录
usermod -aG sudo paa
install -d -m 700 -o paa -g paa /home/paa/.ssh
echo '<你的公钥>' > /home/paa/.ssh/authorized_keys
chown paa:paa /home/paa/.ssh/authorized_keys && chmod 600 /home/paa/.ssh/authorized_keys
```

验证（本机 Windows，公网 IP 从控制台复制，不必发给任何人）：

```powershell
ssh -i "$env:USERPROFILE\.ssh\paa_ecs" paa@<公网IP>
```

通过标准：能登录、`id` 显示在 sudo 组、`sudo -v` 通过。这一步不改任何现有配置，失败也不影响 Workbench。

### 批次 B：收敛安全组（A 通过后）

1. 删除 3389 规则（控制台「管理规则 → 入方向 → 删除」）。
2. 22 端口：出口 IP 固定则改为该 IP `/32`；动态 IP 先保留 `0.0.0.0/0`，密码认证已关，风险可接受。

### 批次 C：系统层加固（B 通过后逐项再确认）

1. `PermitRootLogin no`：先 `sshd -t`，再 reload；改完用 Workbench 与 VNC 双重验证。
2. UFW 启用：默认拒绝入站、放行出站、仅放 22。
3. 80 个包先只升安全类，观察内存，不立即重启。
4. journald `SystemMaxUse=500M`。
5. Ubuntu Pro / ESM Apps 挂接。

## 10. 状态清单

| 项 | 状态 |
|---|---|
| 本地环境审计（第一阶段） | 已完成 |
| 服务器只读审计 | **已完成**（Workbench 会话内实测） |
| 安全组审计 | **已完成**：3 条入方向规则，3389 公网开放待处理 |
| SSH 现状 | 密码认证已关、root 可密钥登录、`/root/.ssh/authorized_keys` 为空 |
| SSH 密钥 | 本机已生成 ed25519 密钥对（带 passphrase），公钥待部署 |
| SSH / 账户 / UFW 修改 | 未执行，待批准（批次 A） |
| 安全组修改 | 未执行，待批准（批次 B） |
| 系统更新 | 未执行，待批准 |
| 费用与续费核查 | **未完成**，需你在控制台核对 |
| 本阶段禁止项（Docker/数据库/QQ/PAA 部署） | 均未触碰 |

## 11. 中断点与恢复指引（2026-10-18 暂停）

**当前实机状态**：实例保持运行，`paa` 用户已建并加入 sudo，但 `/home/paa/.ssh/authorized_keys` 为空（公钥未成功写入），因此 SSH 仍不可用；root 的 `authorized_keys` 也是空的，实际访问路径仍只有 Workbench。

**下次开机后按此顺序继续**：

1. Workbench 登录，确认 `/home/paa/.ssh/authorized_keys` 有 1 行、88–89 字节。
2. `ssh-keygen -lf /home/paa/.ssh/authorized_keys` 输出必须为 `SHA256:yUn/NKZg4O6guPoJzEbvnZpq79hVHr5LgXfHe9E16k4`。
3. 指纹对上后从 Windows 用 `ssh -i ~/.ssh/paa_ecs paa@<公网IP>` 验证，再继续批次 B（删 3389）与批次 C。

**未完成且不可跳过**：安全组 3389 仍对公网开放；`PermitRootLogin` 仍为 `yes`；UFW 仍为 `inactive`；80 个包未升级。

## 12. 执行记录（2026-10-20）

执行方式：`paa` 用户经 SSH 接入（本机 ssh-agent 持有带 passphrase 的 ed25519 密钥）；涉及特权操作时临时把同一公钥加入 root，完成后立即移除。

| # | 操作 | 结果 | 验证证据 | 回滚 |
|---|---|---|---|---|
| 1 | 部署 `paa` 公钥 | `/home/paa/.ssh/authorized_keys` 88 字节，权限 600 | `ssh-keygen -lf` → `SHA256:yUn/NKZ…E16k4` | 删除该文件内对应行 |
| 2 | 系统更新 | 21 个包升级完成；`cloud-init` 被 phased 更新保留 | `apt list --upgradable` 仅剩 1 条；`reboot-required` 不存在 | 无自动回滚，依赖云盘快照 |
| 3 | journald 上限 | 新增 `/etc/systemd/journald.conf.d/99-size.conf`，`SystemMaxUse=500M` | `journalctl --disk-usage` → 16.0M | 删除该 drop-in 并重启 journald |
| 4 | UFW | 启用：默认拒绝入站、放行出站、仅放 22/tcp（IPv4+IPv6） | `ufw status verbose`；`is-enabled=enabled` | `ufw disable` |
| 5 | 关闭 root 远程登录 | 新增 `/etc/ssh/sshd_config.d/99-hardening.conf`：`PermitRootLogin no` | `sshd -T` 回读 `permitrootlogin no`；新连接 root 返回 `Permission denied (publickey)` | 删除 drop-in → `sshd -t` → `systemctl reload ssh` |
| 6 | 移除 root 临时公钥 | `/root/.ssh/authorized_keys` 已删除 | 同上，root 无法登录 | — |
| 7 | `paa` 免密 sudo | `/etc/sudoers.d/90-paa-nopasswd`：`paa ALL=(ALL) NOPASSWD:ALL`，`visudo -c` 全绿 | `sudo -n id` → `uid=0(root)` | 删除该文件即可恢复密码验证 |
| 8 | Ubuntu Pro 挂接 | 浏览器配对方式 attach（不落地 token），`esm-apps` / `esm-infra` 已 enabled | `pro status` | `sudo pro detach` |
| 9 | ESM 安全更新 | 升级 4 个包：git、git-man、python3-pip、python3-wheel（来自 `-security` 与 `apps-security`） | `apt list --upgradable` 仅剩 cloud-init（phased） | 无自动回滚 |

原配置备份：`/etc/ssh/sshd_config.bak-20261020`。

收尾状态：仅 22 端口监听对外；`sshd` 由 `ssh.socket`（enabled/active）socket 激活，重启后自动恢复。

**访问通道变化（重要）**：关闭 root 远程登录后，阿里云 Workbench 的「免密连接」失效——它本质是往 root 注入临时密钥走 SSH。现有入口：

1. 日常：本机 `ssh paa@<公网IP>`（ssh-agent 持有密钥）。
2. 控制台 VNC：用户名 `paa` + 登录密码，进入后 `sudo -i` 提权（已免密）。
3. 控制台「云助手 → 发送命令」：以 root 执行，不经过 sshd（`aliyun.service` 运行中，已确认）。

`unattended-upgrades` 已确认启用（`APT::Periodic::Update-Package-Lists "1"`、`Unattended-Upgrade "1"`，含 `-security` 源），后续安全补丁会自动装。

`livepatch` 当前为 disabled（attach 时尝试启用但未生效）。不影响现有安全更新，只是内核 CVE 修复仍需要重启；需要时可执行 `sudo pro enable livepatch`。

**注意**：登录横幅提示可升级到 `26.04.1 LTS`。本阶段不执行 `do-release-upgrade`——跨大版本升级会更换内核与全部软件包，属于部署阶段决策，且与 2 GiB 内存下的风险评估绑定。

**仍未完成**：

1. 安全组入方向 3389（控制台操作，删除即可）。
2. Ubuntu Pro / ESM Apps 挂接（可选，补 2 个安全更新）。
3. `paa` 的 sudo 仍要求密码——这是有意的，意味着自动化脚本无法免密提权；若后续需要无人值守运维，再单独决定是否开 NOPASSWD。
   **更新（2026-10-20）**：已按用户要求开启 NOPASSWD。安全含义：持有 `paa` 私钥即等于 root，passphrase 成为唯一第二因素。
   **架构约束**：PAA 上线后，agent 必须运行在独立无 sudo 的服务账号（如 `paa-svc`）下，禁止以 `paa` 身份运行。
