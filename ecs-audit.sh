#!/usr/bin/env bash
# PAA · 阿里云 ECS 只读审计脚本（Ubuntu 24.04）
# 只读：不安装、不修改、不重启、不写业务文件；输出已脱敏（无 IP / 实例ID / 凭据）
# 用法：sudo bash ecs-audit.sh > audit.txt 2>&1   （请只在你自己可见的终端里执行）

set -u
[ "$(id -u)" -eq 0 ] || { echo "请用 sudo 运行：sudo bash ecs-audit.sh"; exit 1; }

MD=http://100.100.100.200/latest/meta-data
meta() { curl -s --max-time 3 "$MD/$1" 2>/dev/null || true; }

echo "===== 1. 系统 ====="
grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release
echo "kernel=$(uname -r) arch=$(uname -m)"
echo "uptime=$(uptime -p 2>/dev/null)"

echo "===== 2. 规格与磁盘 ====="
echo "vCPU=$(nproc)"
free -h
df -h / /var 2>/dev/null | sed -n '1,5p'
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT | sed -n '1,15p'

echo "===== 3. 实例元数据（脱敏）====="
IID="$(meta instance-id)"
echo "region=$(meta placement/region)"
echo "zone=$(meta placement/zone-id)"
echo "instance-type=$(meta instance-type)"
echo "instance-id=***${IID: -4}"
[ -n "$(meta eipv4)" ] && echo "eip=assigned" || echo "eip=none"
SG="$(meta security-group-ids | tr -d '[]' | tr ',' ' ' | wc -w)"
echo "security-groups=${SG}"
[ -n "$(meta vpc-id)" ] && echo "vpc=present" || echo "vpc=none"

echo "===== 4. SSH 服务 ====="
systemctl is-active ssh 2>/dev/null | sed 's/^/ssh.service=/'
sshd -T 2>/dev/null | grep -Ei '^(port|permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|maxauthtries|logingracetime|allowusers|allowgroups)' || echo "sshd -T 读取失败"
echo "-- /etc/ssh/sshd_config.d/ --"
ls -1 /etc/ssh/sshd_config.d/ 2>/dev/null || echo "(空)"

echo "===== 5. 账户与 sudo ====="
awk -F: '$3>=1000 && $3<65534 {print "user="$1" uid="$3" shell="$7}' /etc/passwd
echo "-- 在 sudo/wheel 组中的账户 --"
getent group sudo wheel 2>/dev/null | cut -d: -f1
echo "-- uid=0 的账户 --"
awk -F: '$3==0 {print $1}' /etc/passwd
echo "-- 最近登录（IP 已屏蔽）--"
last -n 5 2>/dev/null | sed -E 's/[0-9]{1,3}(\.[0-9]{1,3}){3}/<IP>/g' | head -6

echo "===== 6. 防火墙 ====="
ufw status verbose 2>/dev/null | sed -n '1,12p' || echo "ufw 不可用"
echo "-- nftables 规则条数 --"
nft list ruleset 2>/dev/null | wc -l

echo "===== 7. 监听端口 ====="
ss -tulpnH 2>/dev/null | awk '{print $1, $5, $NF}' | sort -u | sed -n '1,25p'

echo "===== 8. 系统更新 ====="
echo "upgradable=$(apt list --upgradable 2>/dev/null | grep -c upgradable)"
[ -f /var/run/reboot-required ] && cat /var/run/reboot-required || echo "reboot-required: no"
echo "unattended-upgrades enabled=$(systemctl is-enabled unattended-upgrades 2>/dev/null)"
echo "unattended-upgrades active=$(systemctl is-active unattended-upgrades 2>/dev/null)"
grep -E '^(APT::Periodic::Unattended-Upgrade)' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null || echo "20auto-upgrades: 未配置"

echo "===== 9. 时间同步 ====="
timedatectl 2>/dev/null | grep -E 'Time zone|System clock synchronized|NTP service'

echo "===== 10. 日志与内存 ====="
journalctl --disk-usage 2>/dev/null
grep -E '^(SystemMaxUse|MaxRetentionSec)' /etc/systemd/journald.conf 2>/dev/null || echo "journald: 使用默认上限"
echo "-- swap --"
swapon --show || true
grep -E '^(MemTotal|SwapTotal)' /proc/meminfo
echo "-- OOM 历史次数 --"
journalctl -k --since "30 days ago" 2>/dev/null | grep -ci 'out of memory' || true

echo "===== 11. 已装相关软件（只查不装）====="
for s in docker.io docker-ce postgresql redis-server fail2ban nginx ufw unattended-upgrades cloud-init; do
  v=$(dpkg-query -W -f='${Version}' "$s" 2>/dev/null)
  [ -n "$v" ] && echo "$s=$v" || echo "$s=未安装"
done

echo "===== 审计结束（本脚本未做任何写操作）====="
