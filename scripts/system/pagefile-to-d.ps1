<#
把分页文件迁到 D 盘（需管理员 + 重启）。

为什么用注册表而不是 WMI：
  Win32_PageFileSetting 在本机反复报「对象或属性已存在」（系统托管时它只给出占位
  PagingFiles=?:\pagefile.sys，New/Set-CimInstance 都写不进去）。
  真正生效的位置是注册表：
    HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles
  格式：每行 "<路径> <初始MB> <最大MB>"。

本机实测（2026-10-26）：
  ACE-Step 的 LM 模式要同时驻留 DiT + 1.7B LM + text encoder + VAE，
  提交内存峰值超过 26.8GB，会报 os error 1455（页面文件太小），
  并连带把 PostgreSQL 一起挤崩。故改为 C 8GB + D 32GB（约 40GB 提交额度）。

安全约束：
  - 只改「分页文件设置」，不删除任何文件；
  - D 盘剩余低于 36GB 直接中止；
  - 任何一步失败都会恢复「自动管理」，不会留下「无分页文件」的危险状态。
#>

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error '请以管理员身份运行本脚本。'
    exit 2
}

$regKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management'
$dFolder = 'D:\SystemCache'
$dFile = Join-Path $dFolder 'pagefile.sys'
$cInitMB = 8192
$cMaxMB = 8192
$dInitMB = 32768
$dMaxMB = 32768
$needGB = 36

$dFreeGB = [math]::Round((Get-PSDrive D).Free / 1GB, 1)
if ($dFreeGB -lt $needGB) {
    Write-Error "D 盘剩余仅 $dFreeGB GB，低于 $needGB GB 安全线，已中止。"
    exit 3
}

if (-not (Test-Path -LiteralPath $dFolder)) {
    New-Item -ItemType Directory -Path $dFolder -Force | Out-Null
    Write-Host "已创建目录 $dFolder"
}

function Restore-Auto {
    try {
        Set-CimInstance -InputObject (Get-CimInstance Win32_ComputerSystem) -Property @{ AutomaticManagedPagefile = $true }
        Write-Warning '已恢复「自动管理分页文件大小」。'
    }
    catch {
        Write-Warning '恢复自动管理失败，请手动在「系统属性 → 高级 → 性能 → 虚拟内存」里勾回自动管理。'
    }
}

try {
    $cs = Get-CimInstance Win32_ComputerSystem
    if ($cs.AutomaticManagedPagefile) {
        Set-CimInstance -InputObject $cs -Property @{ AutomaticManagedPagefile = $false }
        Write-Host '已关闭「自动管理分页文件大小」'
    }

    $entries = @(
        "C:\pagefile.sys $cInitMB $cMaxMB"
        "$dFile $dInitMB $dMaxMB"
    )
    Set-ItemProperty -Path $regKey -Name 'PagingFiles' -Value $entries -Type MultiString -Force
    Write-Host '已写入分页文件配置：'
    foreach ($line in $entries) { Write-Host "  $line" }
}
catch {
    Write-Warning "配置失败：$($_.Exception.Message)"
    Restore-Auto
    Write-Error '本次未改动分页文件设置。'
    exit 4
}

$applied = (Get-ItemProperty -Path $regKey -Name 'PagingFiles').PagingFiles
# 注意：$applied 是数组时，-notmatch 会「过滤」而不是返回布尔值，必须先 join。
$joined = ($applied -join ' ')
if (-not $joined -or $joined -notmatch 'SystemCache') {
    Write-Warning "写入后回读校验失败（当前值：$joined），正在恢复自动管理..."
    Restore-Auto
    exit 5
}

Write-Host ''
Write-Host '当前注册表配置：'
foreach ($line in $applied) { Write-Host "  $line" }
Write-Host ''
Write-Host '完成。请重启生效：'
Write-Host "  - C:\pagefile.sys 收缩为 $($cInitMB / 1024) GB"
Write-Host "  - D:\SystemCache\pagefile.sys 为 $($dInitMB / 1024) GB"
Write-Host '回滚：把「自动管理分页文件大小」勾回去，或执行'
Write-Host '  Set-CimInstance (Get-CimInstance Win32_ComputerSystem) -Property @{AutomaticManagedPagefile=$true}'
exit 0
