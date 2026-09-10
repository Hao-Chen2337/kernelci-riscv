#!/usr/bin/env bash
# 在 WSL 上启动 riscv64 Debian 虚拟机（用你自己编的内核 + debian-13 镜像）
# 用法: ./boot-riscv-vm.sh
set -euo pipefail

KERNEL="${KERNEL:-$HOME/linux/arch/riscv/boot/Image}"
IMAGE="${IMAGE:-$HOME/debian-13-nocloud-riscv64.qcow2}"
DATA="${DATA:-$HOME/kci-data.qcow2}"   # 数据盘：放内核源码/测试，20G
ROOTDEV="${ROOTDEV:-/dev/vda1}"   # 你的镜像分区是 vda1(根) + vda15(EFI)

# 优先用 ruyi 装的新版 QEMU（支持 vector），否则回退到系统 qemu
QEMU="${QEMU:-$(find "$HOME/.local/share/ruyi" -name qemu-system-riscv64 2>/dev/null | head -1)}"
QEMU="${QEMU:-qemu-system-riscv64}"
echo "==> 使用 QEMU: $QEMU"

# 数据盘不存在则创建（20G）
if [ ! -f "$DATA" ]; then
  echo "==> 创建数据盘: $DATA (20G)"
  qemu-img create -f qcow2 "$DATA" 20G
fi

# ---- 1. 生成 cloud-init seed（给镜像设 root 密码，解决登录问题） ----
SEED="$HOME/seed.iso"
if [ ! -f "$SEED" ]; then
  if ! command -v cloud-localds >/dev/null 2>&1; then
    echo "==> 安装 cloud-image-utils"
    sudo apt install -y cloud-image-utils
  fi
  cat > /tmp/user-data <<'EOF'
#cloud-config
disable_root: false
ssh_pwauth: true
chpasswd:
  list: |
    root:riscv
    debian:riscv
  expire: false
EOF
  touch /tmp/meta-data
  cloud-localds "$SEED" /tmp/user-data /tmp/meta-data
  echo "==> seed 已生成: $SEED"
fi

# ---- 2. 启动 QEMU ----
exec "$QEMU" \
  -machine virt -m 4G -smp 8 \
  -cpu rv64,v=true \
  -no-reboot \
  -bios default \
  -kernel "$KERNEL" \
  -append "root=$ROOTDEV rw console=ttyS0 panic=-1" \
  -drive file="$IMAGE",format=qcow2,if=virtio \
  -drive file="$SEED",format=raw,if=virtio \
  -drive file="$DATA",format=qcow2,if=virtio \
  -device virtio-net-device,netdev=net0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -nographic
