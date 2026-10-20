# 看门狗：每分钟检查 PAA 的服务进程与守护循环，缺哪个补哪个。
# 由启动文件夹的 VBS 以隐藏窗口启动；自身崩溃后只能等下次登录恢复。
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$runner = Join-Path $PSScriptRoot 'run_paa.ps1'

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
            "$(Get-Date -Format o) 已重新拉起 PAA" |
                Out-File -FilePath (Join-Path $root 'logs\watchdog.log') -Append -Encoding utf8
        }
    } catch {
        "$(Get-Date -Format o) 看门狗异常：$($_.Exception.Message)" |
            Out-File -FilePath (Join-Path $root 'logs\watchdog.log') -Append -Encoding utf8
    }
    Start-Sleep -Seconds 60
}
