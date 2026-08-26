#!/usr/bin/env bash
# Phase 1 minimal loop: download kernel -> build selftests -> run -> tally pass/fail
set -euo pipefail

# ===== Configurable =====
KERNEL_VER="${KERNEL_VER:-v6.18}"          # kernel version (tag)
KERNEL_URL="${KERNEL_URL:-https://mirrors.aliyun.com/linux-kernel/v6.x/linux-${KERNEL_VER#v}.tar.xz}"  # China mirror, fast
WORKDIR="${WORKDIR:-$HOME/kci}"            # working directory
RESULT_DIR="${RESULT_DIR:-$WORKDIR/results}" # results output directory

mkdir -p "$WORKDIR" "$RESULT_DIR"

# ===== 1. Download kernel source (tar, single-file download faster than git clone) =====
cd "$WORKDIR"
if [ ! -d linux ]; then
  echo "==> Downloading kernel ${KERNEL_VER} (tar.xz, 154MB)"
  wget -O linux.tar.xz "$KERNEL_URL"
  echo "==> Extracting"
  tar xf linux.tar.xz
  mv "linux-${KERNEL_VER#v}" linux
  rm linux.tar.xz
fi

# ===== 2. Generate headers and build/install riscv selftests =====
echo "==> Generating headers + building selftests/riscv"
cd "$WORKDIR/linux"
make ARCH=riscv headers
make ARCH=riscv -C tools/testing/selftests TARGETS=riscv install

# ===== 3. Run tests =====
echo "==> Running riscv selftests"
cd tools/testing/selftests/kselftest_install
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"   # no sudo needed when root
$SUDO ./run_kselftest.sh 2>&1 | tee "$RESULT_DIR/riscv.log"

# ===== 4. Tally results =====
echo ""
echo "===== Results ====="
OK=$(grep -c '^ok ' "$RESULT_DIR/riscv.log" || true)
FAIL=$(grep -c '^not ok ' "$RESULT_DIR/riscv.log" || true)
SKIP=$(grep -c '^ok .*# SKIP' "$RESULT_DIR/riscv.log" || true)
echo "pass: $OK  fail: $FAIL  skip: $SKIP"
echo "full log: $RESULT_DIR/riscv.log"

# ===== 5. Append to regression trend table =====
PLATFORM="${PLATFORM:-$(uname -m)}"   # override with PLATFORM=qemu / PLATFORM=k3
CHIP="$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | sed 's/.*:[[:space:]]*//' | tr -d ' ' || echo unknown)"
TREND="$RESULT_DIR/trend.md"
if [ ! -f "$TREND" ]; then
  { echo "# Regression Trend"; echo ""; \
    echo "| Date | Kernel | Platform | Chip | Pass | Fail | Skip |"; \
    echo "|---|---|---|---|---|---|---|"; } > "$TREND"
fi
echo "| $(date +%F) | $KERNEL_VER | $PLATFORM | $CHIP | $OK | $FAIL | $SKIP |" >> "$TREND"
echo "trend updated: $TREND"

# non-zero exit on failure, for CI
[ "$FAIL" = "0" ] || exit 1
