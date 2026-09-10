#!/usr/bin/env bash
# 重置 riscv64 Debian 虚拟机密码（绕过 cloud-init，直接改 shadow）
# 用法: 先 Ctrl+C 关掉虚拟机，再跑本脚本
set -euo pipefail

IMAGE="${IMAGE:-$HOME/debian-13-nocloud-riscv64.qcow2}"
NEWPASS="${NEWPASS:-riscv}"

echo "==> 生成密码 hash"
HASH=$(openssl passwd -6 "$NEWPASS")

echo "==> 加载 nbd 并挂载镜像"
sudo modprobe nbd max_part=8
sudo qemu-nbd -c /dev/nbd0 "$IMAGE"
sleep 1
sudo mkdir -p /mnt/k3root
sudo mount /dev/nbd0p1 /mnt/k3root

echo "==> 修改 root / debian 密码"
sudo HASH="$HASH" python3 - <<'PY'
import os
h = os.environ["HASH"]
p = "/mnt/k3root/etc/shadow"
out = []
for ln in open(p).read().splitlines():
    if ln.startswith("root:") or ln.startswith("debian:"):
        user, _, rest = ln.partition(":")
        parts = rest.split(":")
        parts[0] = h          # 替换密码字段
        ln = user + ":" + ":".join(parts)
    out.append(ln)
open(p, "w").write("\n".join(out) + "\n")
print("shadow 已更新")
PY

echo "==> 开启 SSH 密码登录 + root 登录"
sudo mkdir -p /mnt/k3root/etc/ssh/sshd_config.d
sudo tee /mnt/k3root/etc/ssh/sshd_config.d/99-local.conf >/dev/null <<'EOF'
PasswordAuthentication yes
PermitRootLogin yes
EOF

echo "==> 卸载"
sudo umount /mnt/k3root
sudo qemu-nbd -d /dev/nbd0
echo "完成！密码已重置为: $NEWPASS"
