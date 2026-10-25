<#
把分页文件迁到 D 盘（需以管理员身份运行，改完需重启）。

设计取舍（基于本机实测，2026-10-25）：
  RAM 15.3GB，分页文件当前系统托管、已分配 11,776MB，但峰值只用了 159MB。
  崩溃转储设置为"内核内存转储"(CrashDumpEnabled=3)，需要引导卷上仍有分页文件。
  因此：C 保留固定 4GB（够写内核转储、也保住提交上限），D 新增固定 8GB。
  合计 12GB ≈ 现状 11.5GB，不降低提交上限，同时给 C 释放约 7.7GB。

安全约束：
  - 只修改分页文件设置，不删除任何文件；
  - C 上的 pagefile.sys 由系统在重启时自动收缩；
  - 若已配置过则直接退出（幂等）；
  - D 盘剩余空间不足 12GB 则拒绝执行。
#>

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error '请以管理员身份运行本脚本。'
    exit 2
}

$dFolder = 'D:\SystemCache'
$dFile = Join-Path $dFolder 'pagefile.sys'
$cInitMB = 4096
$dInitMB = 8192
$dMaxMB = 8192

$dFreeGB = [math]::Round((Get-PSDrive D).Free / 1GB, 1)
if ($dFreeGB -lt 12) {
    Write-Error "D 盘剩余仅 $dFreeGB GB，低于 12GB 安全线，已中止。"
    exit 3
}

if (-not (Test-Path -LiteralPath $dFolder)) {
    New-Item -ItemType Directory -Path $dFolder -Force | Out-Null
    Write-Host "已创建目录 $dFolder"
}

$cs = Get-CimInstance Win32_ComputerSystem
if ($cs.AutomaticManagedPagefile) {
    Set-CimInstance -InputObject $cs -Property @{ AutomaticManagedPagefile = $false }
    Write-Host '已关闭"自动管理分页文件大小"'
}

function Set-PageFile([string]$path, [uint32]$initial, [uint32]$maximum) {
    # Win32_PageFileSetting 的 InitialSize/MaximumSize 是 uint32，传 Int32 会报「类型不匹配」
    $existing = Get-CimInstance Win32_PageFileSetting -Filter "Name='$path'" -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.InitialSize -eq $initial -and $existing.MaximumSize -eq $maximum) {
            Write-Host "已符合目标，无需修改：$path"
            return
        }
        Set-CimInstance -InputObject $existing -Property @{
            InitialSize = [uint32]$initial
            MaximumSize = [uint32]$maximum
        }
        Write-Host "已调整：$path -> $initial / $maximum MB"
    }
    else {
        New-CimInstance -ClassName Win32_PageFileSetting -Property @{
            Name        = $path
            InitialSize = [uint32]$initial
            MaximumSize = [uint32]$maximum
        } | Out-Null
        Write-Host "已创建：$path -> $initial / $maximum MB"
    }
}

try {
    Set-PageFile -path 'C:\pagefile.sys' -initial $cInitMB -maximum $cInitMB
    Set-PageFile -path $dFile -initial $dInitMB -maximum $dMaxMB
}
catch {
    # 中途失败时恢复自动管理，避免「自动管理已关、又没配置任何分页文件」的危险状态
    Write-Warning "配置失败：$($_.Exception.Message)，正在恢复自动管理..."
    Set-CimInstance -InputObject (Get-CimInstance Win32_ComputerSystem) -Property @{ AutomaticManagedPagefile = $true }
    Write-Error '已恢复自动管理，本次未改动分页文件。'
    exit 4
}

Write-Host ''
Write-Host '当前分页文件设置：'
Get-CimInstance Win32_PageFileSetting | ForEach-Object {
    Write-Host ("  {0}  {1} / {2} MB" -f $_.Name, $_.InitialSize, $_.MaximumSize)
}
Write-Host ''
Write-Host '完成。请重启生效：重启后 C 盘 pagefile.sys 会收缩到 4GB，D 盘会生成新的 8GB 文件。'
Write-Host '回滚：把 AutomaticManagedPagefile 设回 $true 并重启即可。'
exit 0
