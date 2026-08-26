#!/usr/bin/env bash
# KVM selftests：真机 Hypervisor 测试
# 用法: sudo bash run-kvm-tests.sh   （必须 root，因为要访问 /dev/kvm）
set -uo pipefail

WORKDIR="${WORKDIR:-}"
# 探测内核源码位置（sudo 下 HOME 变 /root，多级回退找真实用户的 kci）
if [ -z "$WORKDIR" ] || [ ! -d "$WORKDIR/linux" ]; then
  for d in "$HOME/kci" "${SUDO_USER:+"/home/$SUDO_USER/kci"}" /home/*/kci /kci; do
    if [ -d "$d/linux" ]; then
      WORKDIR="$d"
      break
    fi
  done
fi
RESULT_DIR="${RESULT_DIR:-$WORKDIR/results}"
mkdir -p "$RESULT_DIR"

# 1. 前置检查
[ "$(id -u)" -eq 0 ] || { echo "❌ 请用 root 跑: sudo bash run-kvm-tests.sh"; exit 1; }
[ -e /dev/kvm ] || { echo "SKIP: 本机无 /dev/kvm（无 H 扩展，预期）"; exit 0; }
[ -d "$WORKDIR/linux" ] || { echo "❌ 无内核源码 $WORKDIR/linux，先跑 run-tests.sh"; exit 1; }

echo "==> /dev/kvm 就绪"
ls -l /dev/kvm

# 2. 编译 KVM selftests
echo "==> 编译 KVM selftests"
cd "$WORKDIR/linux"
make ARCH=riscv -C tools/testing/selftests/kvm -j"$(nproc)" 2>&1 | tail -25

# 3. 找出编译出的测试二进制（排除源码/脚本）
cd tools/testing/selftests/kvm
echo ""
echo "==> 编译出的测试程序"
BINS=$(find . -maxdepth 2 -type f -executable ! -name '*.sh' 2>/dev/null | head -20)
echo "$BINS"

# 4. 逐个运行（官方 kselftest 默认 45 秒超时；perf/stress 测试超时属预期）
echo ""
echo "==> 运行 KVM 测试"
TIMEOUT="${TIMEOUT:-45}"
PASS=0; FAIL=0
while IFS= read -r b; do
  [ -n "$b" ] || continue
  name=$(basename "$b")
  echo "--- $name ---"
  if timeout "$TIMEOUT" "$b" >>"$RESULT_DIR/kvm.log" 2>&1; then
    echo "PASS: $name"; PASS=$((PASS+1))
  else
    echo "FAIL: $name (exit=$?)"; FAIL=$((FAIL+1))
  fi
done <<< "$BINS"

echo ""
echo "===== KVM 结果 ====="
echo "通过: $PASS  失败: $FAIL"
echo "日志: $RESULT_DIR/kvm.log"
