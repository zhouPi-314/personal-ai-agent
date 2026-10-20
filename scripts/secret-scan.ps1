# 提交前扫描：密钥、凭据、可识别信息。命中即退出码 1。
# 用法：pwsh -File scripts/secret-scan.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$skip = '[\\/](\.venv|\.git|node_modules|__pycache__|\.pytest_cache|\.ruff_cache)[\\/]'

$patterns = [ordered]@{
    'private key'  = 'BEGIN [A-Z ]*PRIVATE KEY'
    'api key'      = '\bsk-[A-Za-z0-9]{20,}'
    'aws access'   = '\bAKIA[0-9A-Z]{16}\b'
    'bearer token' = 'Bearer [A-Za-z0-9._\-]{20,}'
    'dsn password' = '[a-z0-9+]+://[^:/\s]+:[^@\s<][^@\s]{3,}@'
    # 白名单：阿里云元数据服务、公共 DNS。这些是公开基础设施地址，不含个人信息。
    'public ipv4'  = '\b(?!10\.|127\.|0\.0\.0\.0|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.100\.100\.200|223\.5\.5\.5|1\.1\.1\.1)\d{1,3}(\.\d{1,3}){3}\b'
    'user path'    = 'C:\\Users\\[^\\<]'
}

$hits = @()
Get-ChildItem -LiteralPath $root -Recurse -File -Force |
    # .env 是本机凭据文件（已被 .gitignore 排除）；扫描器自身的正则不是秘密。
    Where-Object { $_.FullName -notmatch $skip -and $_.Name -notin @('.env', 'secret-scan.ps1') } |
    ForEach-Object {
        $file = $_
        foreach ($name in $patterns.Keys) {
            $found = Select-String -LiteralPath $file.FullName -Pattern $patterns[$name] `
                -AllMatches -ErrorAction SilentlyContinue
            foreach ($row in $found) {
                $rel = $file.FullName.Substring($root.Length + 1)
                $hits += "$rel`:$($row.LineNumber) [$name]"
            }
        }
    }

if ($hits) {
    $hits | Select-Object -Unique | ForEach-Object { "HIT  $_" }
    exit 1
}

"OK: no secrets or identifying info found"
