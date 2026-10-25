#!/usr/bin/env bash
# 提交前扫描（POSIX 版，供 CI 使用；本地仍走 scripts/secret-scan.ps1）
# 规则与 PowerShell 版保持一致；命中即退出码 1。

set -uo pipefail

cd "$(dirname "$0")/.."

EXCLUDES=(
  --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules
  --exclude-dir=__pycache__ --exclude-dir=.pytest_cache --exclude-dir=.ruff_cache
  --exclude-dir=runtime --exclude-dir=models --exclude-dir=work
  --exclude-dir=logs --exclude-dir=backups --exclude-dir=data
  --exclude=.env --exclude=secret-scan.ps1 --exclude=secret-scan.sh
)

declare -a PATTERNS=(
  "private key|BEGIN [A-Z ]*PRIVATE KEY"
  "api key|\bsk-[A-Za-z0-9]{20,}"
  "aws access|\bAKIA[0-9A-Z]{16}\b"
  "bearer token|Bearer [A-Za-z0-9._-]{20,}"
  "dsn password|[a-z0-9+]+://[^:/[:space:]]+:[^@[:space:]<][^@[:space:]]{3,}@"
  "public ipv4|\b(?!10\.|127\.|0\.0\.0\.0|192\.168\.|169\.254\.|172\.(1[6-9]|2[0-9]|3[01])\.|100\.100\.100\.200|223\.5\.5\.5|1\.1\.1\.1)[0-9]{1,3}(\.[0-9]{1,3}){3}\b"
  "user path|C:\\\\Users\\\\[^\\\\<]"
)

hits=0
for entry in "${PATTERNS[@]}"; do
  name="${entry%%|*}"
  pattern="${entry#*|}"
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    echo "HIT  $line [$name]"
    hits=1
  done < <(grep -rnPE "${EXCLUDES[@]}" -- "$pattern" . 2>/dev/null)
done

if [[ "$hits" -ne 0 ]]; then
  exit 1
fi

echo "OK: no secrets or identifying info found"
