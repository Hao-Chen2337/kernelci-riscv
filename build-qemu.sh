#!/usr/bin/env bash
# 源码编译 QEMU 8.2（只编 riscv64，支持 vector + -cpu max）
# 用法: bash build-qemu.sh
set -euo pipefail

VER=8.2.0
PREFIX="$HOME/qemu-install"

echo "==> 安装编译依赖"
sudo apt install -y build-essential ninja-build meson pkg-config \
  libglib2.0-dev libpixman-1-dev zlib1g-dev libfdt-dev libslirp-dev

cd "$HOME"
if [ ! -d "qemu-$VER" ]; then
  echo "==> 下载 QEMU $VER 源码"
  wget "https://download.qemu.org/qemu-$VER.tar.xz"
  tar xf "qemu-$VER.tar.xz"
fi

cd "qemu-$VER"
echo "==> 配置（只编 riscv64-softmmu，快很多）"
./configure --target-list=riscv64-softmmu --prefix="$PREFIX"

echo "==> 编译（8 核，约 10-20 分钟）"
make -j"$(nproc)"

echo "==> 安装到 $PREFIX"
make install

echo ""
echo "完成！新 QEMU 在: $PREFIX/bin/qemu-system-riscv64"
"$PREFIX/bin/qemu-system-riscv64" --version
