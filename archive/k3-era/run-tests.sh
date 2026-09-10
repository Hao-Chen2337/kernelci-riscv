#!/usr/bin/env bash
# Phase 1 minimal loop: download kernel -> build selftests -> run -> tally pass/fail
set -euo pipefail

# ===== Configurable =====
KERNEL_VER="${KERNEL_VER:-v6.18}"          # kernel version
VER="${KERNEL_VER#v}"                      # v6.18 -> 6.18
MAJOR="${VER%%.*}"                         # 6.18 -> 6 (first component)
KERNEL_URL="${KERNEL_URL:-https://mirrors.aliyun.com/linux-kernel/v${MAJOR}.x/linux-${VER}.tar.xz}"  # aliyun mirror
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"  # repo root
WORKDIR="${WORKDIR:-$SCRIPT_DIR/kci}"        # working directory (project-local by default)
RESULT_DIR="${RESULT_DIR:-$WORKDIR/results}" # results output directory
TREND_FILE="${TREND_FILE:-$SCRIPT_DIR/docs/trend-riscv.md}"  # committed riscv regression trend
CC="${CC:-gcc}"                                # compiler (build matrix: CC=clang)

mkdir -p "$WORKDIR" "$RESULT_DIR"
WORKDIR="$(cd "$WORKDIR" && pwd)"          # normalize to absolute (safe for relative overrides)

# ===== 1. Download kernel source (tar, single-file download faster than git clone) =====
cd "$WORKDIR"
if [ ! -d linux ]; then
  echo "==> Downloading kernel ${KERNEL_VER} (tar.xz)"
  wget -O linux.tar.xz "$KERNEL_URL"
  echo "==> Extracting"
  tar xf linux.tar.xz
  mv "linux-$VER" linux
  rm linux.tar.xz
fi

# ===== 2. Generate headers and build/install riscv selftests =====
echo "==> Generating headers + building selftests/riscv"
cd "$WORKDIR/linux"
# force recompile so CC is honored (kselftest clean leaves some objects)
make ARCH=riscv -C tools/testing/selftests TARGETS=riscv clean >/dev/null 2>&1
find tools/testing/selftests/riscv -type f \( -name '*.o' -o -name '*.d' \) -delete
make ARCH=riscv CC="$CC" headers
make ARCH=riscv CC="$CC" -C tools/testing/selftests TARGETS=riscv install

# ===== 3. Run tests =====
echo "==> Running riscv selftests"
cd tools/testing/selftests/kselftest_install   
sudo ./run_kselftest.sh 2>&1 | tee "$RESULT_DIR/riscv.log"

# ===== 4. Tally results =====
echo ""
echo "===== Results ====="
OK=$(grep -c '^ok ' "$RESULT_DIR/riscv.log" || true)
FAIL=$(grep -c '^not ok ' "$RESULT_DIR/riscv.log" || true)
SKIP=$(grep -c '^ok .*# SKIP' "$RESULT_DIR/riscv.log" || true)
echo "pass: $OK  fail: $FAIL  skip: $SKIP"
echo "full log: $RESULT_DIR/riscv.log"

# ===== 5. Append to regression trend table =====
PLATFORM="${PLATFORM:-$(uname -m)}"   
CHIP="$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | sed 's/.*:[[:space:]]*//' | tr -d ' ' || echo unknown)"
TREND="$TREND_FILE"
mkdir -p "$(dirname "$TREND")"
if [ ! -f "$TREND" ]; then
  { echo "# Regression Trend"; echo ""; \
    echo "| Timestamp | Kernel | Compiler | Platform | Chip | Pass | Fail | Skip |"; \
    echo "|---|---|---|---|---|---|---|---|"; } > "$TREND"
fi
echo "| $(date '+%F %T') | $KERNEL_VER | $CC | $PLATFORM | $CHIP | $OK | $FAIL | $SKIP |" >> "$TREND"
echo "trend updated: $TREND"

# non-zero exit on failure, for CI
[ "$FAIL" = "0" ] || exit 1
