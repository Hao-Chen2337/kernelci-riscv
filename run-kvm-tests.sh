#!/usr/bin/env bash
# KVM selftests：在真机（有 H 扩展 + /dev/kvm）上编译并运行
# 用法: bash run-kvm-tests.sh
set -euo pipefail

WORKDIR="${WORKDIR:-$HOME/kci}"
RESULT_DIR="${RESULT_DIR:-$WORKDIR/results}"

# 1. 前置检查：/dev/kvm 是否存在
if [ ! -e /dev/kvm ]; then
  echo "SKIP: 本机无 /dev/kvm（无 Hypervisor 扩展或 KVM 未启用）"
  echo "      QEMU 模拟平台或 K1 板子会走这里，属于预期"
  exit 0
fi

if [ ! -d "$WORKDIR/linux" ]; then
  echo "FAIL: 找不到内核源码 $WORKDIR/linux，先跑 run-tests.sh"
  exit 1
fi

mkdir -p "$RESULT_DIR"

# 2. 编译 KVM selftests
echo "==> 编译 KVM selftests"
cd "$WORKDIR/linux"
make ARCH=riscv -C tools/testing/selftests/kvm -j"$(nproc)" 2>&1 | tail -8

# 3. 运行 KVM selftests
echo "==> 运行 KVM selftests"
cd tools/testing/selftests/kvm
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
$SUDO ./run_tests.sh 2>&1 | tee "$RESULT_DIR/kvm.log" || true

# 4. 统计
echo ""
echo "===== KVM 结果统计 ====="
OK=$(grep -c '^ok ' "$RESULT_DIR/kvm.log" 2>/dev/null || true)
FAIL=$(grep -c '^not ok ' "$RESULT_DIR/kvm.log" 2>/dev/null || true)
echo "通过: $OK  失败: $FAIL"
echo "完整日志: $RESULT_DIR/kvm.log"
