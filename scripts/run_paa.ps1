# 常驻运行入口：由计划任务在登录时调用。
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# PowerShell 5.1 默认按系统代码页解码子进程输出，会把 Python 的 UTF-8 日志变成乱码
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
# 子进程 stdout 被重定向时 Python 会退回系统代码页，必须显式指定
$env:PYTHONIOENCODING = 'utf-8'

$env:PAA_LOG_FILE = 'logs/paa-serve.log'
Set-Location $root
$log = Join-Path $logDir 'paa-serve.log'

# 常驻循环：进程退出后 5 秒重启，替代"计划任务失败重启"
# 日志由 Python 自己写（logs/paa-serve.log），不经 PowerShell 重定向，避免编码问题
while ($true) {
    & (Join-Path $root '.venv\Scripts\python.exe') -m paa.serve
    $code = $LASTEXITCODE
    Start-Sleep -Seconds 5
}
