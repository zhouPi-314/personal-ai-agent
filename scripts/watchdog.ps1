# 看门狗：每分钟检查 PAA 的服务进程与守护循环，缺哪个补哪个。
# 由启动文件夹的 VBS 以隐藏窗口启动；自身崩溃后只能等下次登录恢复。
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$runner = Join-Path $PSScriptRoot 'run_paa.ps1'
$logPath = Join-Path $root 'logs\watchdog.log'
$lastNapcatAttempt = [datetime]::MinValue
$lastDshAttempt = [datetime]::MinValue
$dshExe = 'D:\DeepSeek Harness\DeepSeek Harness.exe'

function Write-Log([string]$message) {
    "$(Get-Date -Format o) $message" | Out-File -FilePath $logPath -Append -Encoding utf8
}

# 单实例：登录触发器与手动启动叠加时，两个看门狗会各自拉起一套 NapCat。
$mutex = New-Object System.Threading.Mutex($false, 'Global\PaaWatchdog')
if (-not $mutex.WaitOne(0)) {
    Write-Log '另一个看门狗已在运行，本次退出'
    exit 0
}

while ($true) {
    try {
        $serve = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -match 'paa\.serve' }
        $loop = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
            Where-Object { $_.CommandLine -match 'run_paa\.ps1' }

        if (-not $serve -and -not $loop) {
            # 路径含空格，必须整体加引号，否则 powershell 会把 -File 截断
            $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`""
            Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList $arguments
            Write-Log "已重新拉起 PAA"
        }

        # NapCat：连 WebUI 端口(6099)一起看。只查 3000/3001 会在 OneBot 配置变更时误判成没启动，
        # 从而反复触发计划任务、叠出多套实例。
        $napcatPort = Get-NetTCPConnection -State Listen -LocalPort 3000, 3001, 6099 -ErrorAction SilentlyContinue
        $qqProcess = Get-Process QQ -ErrorAction SilentlyContinue
        if (-not $napcatPort -and -not $qqProcess -and
            ((Get-Date) - $lastNapcatAttempt).TotalMinutes -ge 5) {
            Start-ScheduledTask -TaskName 'NapCat Bot' -ErrorAction SilentlyContinue
            $lastNapcatAttempt = Get-Date
            Write-Log "NapCat 未运行，已触发计划任务"
        }

        # 本机 DSH：18900 不通且进程不在时拉起（DSH 自身没有自启动配置）
        $dshPort = Get-NetTCPConnection -State Listen -LocalPort 18900, 18899 -ErrorAction SilentlyContinue
        $dshProcess = Get-Process 'DeepSeek Harness' -ErrorAction SilentlyContinue
        if (-not $dshPort -and -not $dshProcess -and (Test-Path $dshExe) -and
            ((Get-Date) - $lastDshAttempt).TotalMinutes -ge 5) {
            Start-Process -FilePath $dshExe -ErrorAction SilentlyContinue
            $lastDshAttempt = Get-Date
            Write-Log "本机 DSH 未运行，已启动"
        }
    } catch {
        Write-Log "看门狗异常：$($_.Exception.Message)"
    }
    Start-Sleep -Seconds 60
}
