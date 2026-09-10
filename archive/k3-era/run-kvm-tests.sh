#!/usr/bin/env bash
# KVM selftests: real-hardware Hypervisor tests
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"   # repo root
WORKDIR="${WORKDIR:-$SCRIPT_DIR/kci}"         
RESULT_DIR="${RESULT_DIR:-$WORKDIR/results}"
CC="${CC:-gcc}"                               # compiler (build matrix: CC=clang)
mkdir -p "$WORKDIR" "$RESULT_DIR"
WORKDIR="$(cd "$WORKDIR" && pwd)"             # normalize to absolute

# 1. Preflight checks
[ -e /dev/kvm ] || { echo "SKIP: no /dev/kvm (no H extension, expected)"; exit 0; }
[ -d "$WORKDIR/linux" ] || { echo "FAIL: kernel source not found: $WORKDIR/linux"; exit 1; }

# 2. Build KVM selftests
echo "==> Building KVM selftests"
cd "$WORKDIR/linux"
# force recompile so CC is honored (kselftest clean leaves some objects)
make ARCH=riscv -C tools/testing/selftests/kvm clean >/dev/null 2>&1
find tools/testing/selftests/kvm -type f \( -name '*.o' -o -name '*.d' \) -delete
make ARCH=riscv CC="$CC" -C tools/testing/selftests/kvm -j"$(nproc)" 2>&1 | tail -25

# 3. Run each test binary (kselftest default 45s timeout; perf/stress timeout is expected)
cd tools/testing/selftests/kvm
echo ""
echo "==> Running KVM tests"
TIMEOUT="${TIMEOUT:-45}"
PASS=0; FAIL=0
while IFS= read -r b; do
  [ -n "$b" ] || continue
  name=$(basename "$b")
  echo "--- $name ---"
  if sudo timeout "$TIMEOUT" "$b" >>"$RESULT_DIR/kvm.log" 2>&1; then
    echo "PASS: $name"; PASS=$((PASS+1))
  else
    echo "FAIL: $name (exit=$?)"; FAIL=$((FAIL+1))
  fi
done < <(find . -maxdepth 2 -type f -executable ! -name '*.sh' 2>/dev/null)

echo ""
echo "===== KVM results ====="
echo "pass: $PASS  fail: $FAIL"
echo "log: $RESULT_DIR/kvm.log"

# 4. Append to KVM regression trend 
CHIP="$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | sed 's/.*:[[:space:]]*//' | tr -d ' ' || echo unknown)"
KERNEL_VER="$(uname -r)"
TREND="$SCRIPT_DIR/docs/trend-kvm.md"
mkdir -p "$(dirname "$TREND")"
if [ ! -f "$TREND" ]; then
  { echo "# KVM Regression Trend"; echo ""; \
    echo "| Timestamp | Kernel | Compiler | Platform | Chip | Pass | Fail |"; \
    echo "|---|---|---|---|---|---|---|"; } > "$TREND"
fi
echo "| $(date '+%F %T') | $KERNEL_VER | $CC | kvm | $CHIP | $PASS | $FAIL |" >> "$TREND"
echo "trend updated: $TREND"

# non-zero exit on failure, for CI
exit $FAIL
