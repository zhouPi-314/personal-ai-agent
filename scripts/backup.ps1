# PostgreSQL 备份：本地保留 7 份；带 -Upload 时加密后上传到 ECS。
# 密码来源：.env 的 PAA_DATABASE_URL；备份加密口令来源：%USERPROFILE%\.paa\backup.key
param(
    [switch]$Upload,
    [int]$KeepLocal = 7,
    [int]$KeepRemote = 8
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$backupDir = Join-Path $root 'backups'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$line = Select-String -LiteralPath (Join-Path $root '.env') -Pattern '^PAA_DATABASE_URL=' |
    Select-Object -First 1
if (-not $line) { throw '未找到 PAA_DATABASE_URL' }

$dsn = $line.Line.Substring('PAA_DATABASE_URL='.Length)
if ($dsn -notmatch '://([^:]+):([^@]+)@([^:/]+):(\d+)/(\S+)') {
    throw '无法解析 PAA_DATABASE_URL'
}
$dbUser = $Matches[1]; $dbPass = $Matches[2]
$dbHost = $Matches[3]; $dbPort = $Matches[4]; $dbName = $Matches[5]

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dump = Join-Path $backupDir "$dbName-$stamp.dump"

$env:PGPASSWORD = $dbPass
& 'D:\PostgreSQL\18\bin\pg_dump.exe' -Fc -h $dbHost -p $dbPort -U $dbUser -d $dbName -f $dump
if ($LASTEXITCODE -ne 0) { throw "pg_dump 失败（$LASTEXITCODE）" }

# 只验证不恢复：能列出目录说明归档结构可读
& 'D:\PostgreSQL\18\bin\pg_restore.exe' --list $dump | Out-Null
if ($LASTEXITCODE -ne 0) { throw '备份文件校验失败' }

$sizeMB = [math]::Round((Get-Item $dump).Length / 1MB, 2)
Write-Output "本地备份完成：$dump（$sizeMB MB）"

Get-ChildItem $backupDir -Filter "$dbName-*.dump" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $KeepLocal |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

if (-not $Upload) { return }

$keyFile = Join-Path $env:USERPROFILE '.paa\backup.key'
if (-not (Test-Path $keyFile)) {
    throw "缺少加密口令文件：$keyFile（先创建，内容自己定，不要和数据库密码相同）"
}

$gpg = 'D:\Git\usr\bin\gpg.exe'
$encrypted = "$dump.gpg"
& $gpg --batch --yes --passphrase-file $keyFile --symmetric `
    --cipher-algo AES256 --output $encrypted $dump
if ($LASTEXITCODE -ne 0) { throw 'gpg 加密失败' }

$remoteLine = Select-String -LiteralPath (Join-Path $root '.env') -Pattern '^PAA_BACKUP_REMOTE=' |
    Select-Object -First 1
if (-not $remoteLine) { throw '未配置 PAA_BACKUP_REMOTE（形如 user@host）' }
$remote = $remoteLine.Line.Substring('PAA_BACKUP_REMOTE='.Length).Trim()
& ssh $remote 'mkdir -p ~/paa-backups'
if ($LASTEXITCODE -ne 0) { throw '无法连接 ECS' }
& scp $encrypted "${remote}:~/paa-backups/"
if ($LASTEXITCODE -ne 0) { throw 'scp 上传失败' }

# 远端只保留最近 N 份加密包
$remoteClean = "ls -1t ~/paa-backups/*.dump.gpg 2>/dev/null | tail -n +$($KeepRemote + 1) | xargs -r rm -f"
& ssh $remote $remoteClean

Remove-Item -LiteralPath $encrypted -Force
Write-Output "已上传：$([IO.Path]::GetFileName($encrypted))"
