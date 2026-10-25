# 系统运维：磁盘布局与分页文件

> 原则：**本项目的运行时、模型、缓存全部放 D 盘**，C 盘只保留系统与既有软件。

## 1. 当前磁盘归属

| 位置 | 内容 | 是否项目产生 |
|---|---|---|
| `D:\...\PAA\runtime\` | 便携 Python、ffmpeg、CUDA torch 环境、uv 缓存、ACE-Step 源码 | ✅ |
| `D:\...\PAA\models\` | SenseVoice、Kokoro 权重 | ✅ |
| `D:\...\PAA\runtime\acestep\runtime\` | ACE-Step 权重（9.4GB） | ✅ |
| `%LOCALAPPDATA%\pip\Cache` | **0 MB**（已用 PIP_CACHE_DIR 指向 D） | ❌ 未使用 |
| `%USERPROFILE%\.cache\huggingface` | **0 GB**（已用 HF_HOME 指向 D） | ❌ 未使用 |
| `C:\pagefile.sys` | 11.7GB（系统托管，峰值仅用 159MB） | ❌ 系统 |

## 2. 分页文件：实测与结论

**实测（2026-10-25）**：

| 指标 | 值 |
|---|---|
| 物理内存 | 15.3 GB |
| 提交上限 | 26.8 GB（= 15.3 内存 + 11.5 分页） |
| 分页文件已分配 | 11,776 MB（系统托管） |
| **峰值使用** | **159 MB** |
| 崩溃转储 | 内核内存转储（需要引导卷上有分页文件） |

**结论**：11.7GB 的预留几乎没有被用到，但**不能直接删**——
一是提交上限会从 26.8GB 掉到 15.3GB（加载 9GB 模型时容易触顶），
二是引导卷没有分页文件就写不了内核转储。

**方案**：C 保留固定 **4GB**，D 新增固定 **8GB**（`D:\SystemCache\pagefile.sys`）。
合计 12GB ≈ 现状 11.5GB，提交上限基本不变，同时给 C 释放约 **7.7GB**。

## 3. 执行（需要管理员 + 重启）

```powershell
# 以管理员身份打开 PowerShell，然后：
cd "D:\项目设计\Personal AI Agent（PAA）"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\system\pagefile-to-d.ps1
```

脚本的安全设计：

- **不删除任何文件**；C 的 pagefile.sys 由系统在重启时自动收缩；
- D 盘剩余 < 12GB 时直接拒绝执行；
- 已经是目标配置则跳过（幂等）；
- 做完打印当前设置，并提示重启。

**回滚**：把「自动管理分页文件大小」勾回去（或 `Set-CimInstance` 设 `AutomaticManagedPagefile=$true`）后重启。

## 4. 本机网络：GitHub 只能走系统代理

本机直连 github.com 与 codeload.github.com 会超时，但 api.github.com 正常。
git 默认不读 Windows 系统代理，需要显式指定一次：

```powershell
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' | Select-Object ProxyEnable, ProxyServer
git -c http.proxy=http://127.0.0.1:PORT -c https.proxy=http://127.0.0.1:PORT push
```

## 5. 为什么不把转储文件也搬到 D

Windows 的内核转储默认写引导卷（`C:\Windows\MEMORY.DMP`）。搬到 D 需要额外配置
`DedicatedDumpFile` + 专用转储类型，属于"改动面更大、收益很小"的改动，暂不做。
C 保留 4GB 分页已足够写内核转储。