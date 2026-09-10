#!/usr/bin/env bash
# 在 WSL 里建立到 K3 的 stunnel 隧道（复刻你 Windows 上的 stunnel 配置）
# 用法: bash k3-tunnel.sh   然后另开终端 ssh -p 2223 bianbu@localhost
set -euo pipefail

REMOTE="8aaa88a59e96940c019fd62b65790a76.gdriscv.com:2222"
LOCAL_PORT="${LOCAL_PORT:-2223}"   # 用 2223，避开 QEMU 虚拟机占用的 2222

# ---- 1. 装 stunnel4（没有才装） ----
if ! command -v stunnel4 >/dev/null 2>&1 && ! command -v stunnel >/dev/null 2>&1; then
  echo "==> 安装 stunnel4"
  sudo apt install -y stunnel4 || sudo apt-get install -y stunnel4
fi
STUNNEL="$(command -v stunnel4 || command -v stunnel)"

# ---- 2. 写配置（和 Windows 上那段 spacemit-ssh 完全一致） ----
CFG="/tmp/k3-tunnel.conf"
cat > "$CFG" <<EOF
foreground = no
pid = /tmp/k3-tunnel.pid
output = /tmp/k3-tunnel.log

[spacemit-ssh]
client = yes
accept = 127.0.0.1:$LOCAL_PORT
connect = $REMOTE
EOF
echo "==> 配置已写: $CFG"

# ---- 3. 启动隧道 ----
# 如果之前有旧实例，先停
if [ -f /tmp/k3-tunnel.pid ]; then
  kill "$(cat /tmp/k3-tunnel.pid)" 2>/dev/null || true
  sleep 0.5
fi
"$STUNNEL" "$CFG"
sleep 1

# ---- 4. 确认 ----
if ss -tlnp 2>/dev/null | grep -q ":$LOCAL_PORT "; then
  echo ""
  echo "✅ 隧道已建立: 本机 $LOCAL_PORT -> $REMOTE"
  echo "   现在另开终端执行:"
  echo "     ssh -p $LOCAL_PORT bianbu@localhost"
  echo "     scp -P $LOCAL_PORT run-tests.sh bianbu@localhost:~/"
else
  echo "⚠️  隧道可能没起来，看日志:"
  echo "     tail -20 /tmp/k3-tunnel.log"
fi
