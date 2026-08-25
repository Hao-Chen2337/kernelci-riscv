#!/usr/bin/env bash
# Phase 1 最小闭环：下载内核 -> 编译 selftests -> 跑 -> 统计 pass/fail
set -euo pipefail

# ===== 可配置项 =====
KERNEL_VER="${KERNEL_VER:-v6.18}"          # 要测的内核版本（tag）
KERNEL_URL="${KERNEL_URL:-https://mirrors.aliyun.com/linux-kernel/v6.x/linux-${KERNEL_VER#v}.tar.xz}"  # 国内 tar 源，快
WORKDIR="${WORKDIR:-$HOME/kci}"            # 工作目录
RESULT_DIR="${RESULT_DIR:-$WORKDIR/results}" # 结果输出目录

mkdir -p "$WORKDIR" "$RESULT_DIR"

# ===== 1. 下载内核源码（tar 包，单文件下载比 git clone 快） =====
cd "$WORKDIR"
if [ ! -d linux ]; then
  echo "==> 下载内核源码 ${KERNEL_VER} (tar.xz, 154MB)"
  wget -O linux.tar.xz "$KERNEL_URL"
  echo "==> 解压"
  tar xf linux.tar.xz
  mv "linux-${KERNEL_VER#v}" linux
  rm linux.tar.xz
fi

# ===== 2. 生成 headers 并编译安装 riscv selftests =====
echo "==> 生成 headers + 编译安装 selftests/riscv"
cd "$WORKDIR/linux"
make ARCH=riscv headers
make ARCH=riscv -C tools/testing/selftests TARGETS=riscv install

# ===== 3. 跑测试 =====
echo "==> 运行 riscv selftests"
cd tools/testing/selftests/kselftest_install
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"   # root 登录时不需要 sudo
$SUDO ./run_kselftest.sh 2>&1 | tee "$RESULT_DIR/riscv.log"

# ===== 4. 统计结果 =====
echo ""
echo "===== 结果统计 ====="
OK=$(grep -c '^ok ' "$RESULT_DIR/riscv.log" || true)
FAIL=$(grep -c '^not ok ' "$RESULT_DIR/riscv.log" || true)
SKIP=$(grep -c '^ok .*# SKIP' "$RESULT_DIR/riscv.log" || true)
echo "通过(ok): $OK  失败(not ok): $FAIL  跳过(skip): $SKIP"
echo "完整日志: $RESULT_DIR/riscv.log"

# ===== 5. 写入回归趋势表 =====
PLATFORM="${PLATFORM:-$(uname -m)}"   # 可用 PLATFORM=qemu / PLATFORM=k3 覆盖
CHIP="$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | sed 's/.*:[[:space:]]*//' | tr -d ' ' || echo unknown)"
TREND="$RESULT_DIR/trend.md"
if [ ! -f "$TREND" ]; then
  { echo "# 回归趋势表"; echo ""; \
    echo "| 日期 | 内核 | 平台 | 芯片 | 通过 | 失败 | 跳过 |"; \
    echo "|---|---|---|---|---|---|---|"; } > "$TREND"
fi
echo "| $(date +%F) | $KERNEL_VER | $PLATFORM | $CHIP | $OK | $FAIL | $SKIP |" >> "$TREND"
echo "趋势已更新: $TREND"

# 失败则非零退出，方便 CI 判断
[ "$FAIL" = "0" ] || exit 1
