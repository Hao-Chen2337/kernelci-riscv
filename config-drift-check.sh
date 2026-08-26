#!/usr/bin/env bash
# 配置漂移检测：检查内核 .config 的必需项（缺失/未开启 = FAIL）
# 用法: bash config-drift-check.sh [内核.config 路径]
set -uo pipefail

WORKDIR="${WORKDIR:-$HOME/kci}"
# 优先检查「正在运行的内核」的配置（selftests 就是在它上面跑的）
CONFIG_FILE="${1:-}"
if [ -z "$CONFIG_FILE" ]; then
  if [ -f "/boot/config-$(uname -r)" ]; then
    CONFIG_FILE="/boot/config-$(uname -r)"
  elif [ -f "$WORKDIR/linux/.config" ]; then
    CONFIG_FILE="$WORKDIR/linux/.config"
  fi
fi

# 必需项：这些选项必须开启(=y)
REQUIRED=(
  CONFIG_RISCV_ISA_V        # Vector 扩展
  CONFIG_EXT4_FS            # ext4 根文件系统
  CONFIG_DEVTMPFS           # /dev 自动填充
  CONFIG_DEVTMPFS_MOUNT     # 自动挂载 devtmpfs
  CONFIG_KVM                # KVM（真机 Hypervisor；无 H 平台会缺，属预期差异）
)

if [ ! -f "$CONFIG_FILE" ]; then
  echo "FAIL: 找不到内核配置文件 $CONFIG_FILE"
  echo "      先跑 run-tests.sh 下载并解压内核，或用参数指定路径"
  exit 1
fi

echo "==> 配置漂移检查: $CONFIG_FILE"
FAIL=0
for opt in "${REQUIRED[@]}"; do
  name="${opt%% *}"                    # 去掉行内注释
  val=$(grep -E "^${name}=" "$CONFIG_FILE" 2>/dev/null | head -1)
  if [ -z "$val" ]; then
    echo "FAIL: $name 缺失"
    FAIL=1
  elif echo "$val" | grep -q "=y$"; then
    echo "  ok: $name =y"
  else
    echo "FAIL: $name 未开启 (当前: ${val#*=})"
    FAIL=1
  fi
done

echo ""
if [ "$FAIL" = "0" ]; then
  echo "✅ 配置漂移检查通过"
else
  echo "❌ 配置漂移检查失败"
fi
exit $FAIL
