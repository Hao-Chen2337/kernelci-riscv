#!/usr/bin/env bash
# 源码编译 QEMU 11.1.1（只编 riscv64-softmmu，支持 vector + ssnpm 指针掩码扩展）
# 为什么 11.1.1：8.2 的 TCG rvv 模拟有 bug（vstate_* selftest 在 guest 里非法指令崩溃），
# 11.1.1 实测整个 riscv kselftest collection 只有 pointer_masking 一项如实报不支持。
# 用法: bash build-qemu.sh
set -euo pipefail

VER=11.1.1
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

echo "==> 编译（$(nproc) 核，约 5-15 分钟）"
make -j"$(nproc)"

echo "==> 安装到 $PREFIX"
make install

echo ""
echo "完成！新 QEMU 在: $PREFIX/bin/qemu-system-riscv64"
"$PREFIX/bin/qemu-system-riscv64" --version
