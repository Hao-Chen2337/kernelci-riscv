#!/usr/bin/env bash
# Config drift detection: check required kernel config options (missing/disabled = FAIL)
# Usage: bash config-drift-check.sh [path/to/.config]
set -uo pipefail

WORKDIR="${WORKDIR:-$HOME/kci}"
# Prefer the running kernel's config (selftests run against it)
CONFIG_FILE="${1:-}"
if [ -z "$CONFIG_FILE" ]; then
  if [ -f "/boot/config-$(uname -r)" ]; then
    CONFIG_FILE="/boot/config-$(uname -r)"
  elif [ -f "$WORKDIR/linux/.config" ]; then
    CONFIG_FILE="$WORKDIR/linux/.config"
  fi
fi

# Required options: must be =y
REQUIRED=(
  CONFIG_RISCV_ISA_V        # Vector extension
  CONFIG_EXT4_FS            # ext4 root filesystem
  CONFIG_DEVTMPFS           # auto-populate /dev
  CONFIG_DEVTMPFS_MOUNT     # auto-mount devtmpfs
  CONFIG_KVM                # KVM (real-hardware Hypervisor; missing on no-H platforms, expected)
)

if [ ! -f "$CONFIG_FILE" ]; then
  echo "FAIL: kernel config not found: $CONFIG_FILE"
  echo "      run run-tests.sh first, or pass a path"
  exit 1
fi

echo "==> Config drift check: $CONFIG_FILE"
FAIL=0
for opt in "${REQUIRED[@]}"; do
  name="${opt%% *}"                    # strip inline comment
  val=$(grep -E "^${name}=" "$CONFIG_FILE" 2>/dev/null | head -1)
  if [ -z "$val" ]; then
    echo "FAIL: $name missing"
    FAIL=1
  elif echo "$val" | grep -q "=y$"; then
    echo "  ok: $name =y"
  else
    echo "FAIL: $name disabled (current: ${val#*=})"
    FAIL=1
  fi
done

echo ""
if [ "$FAIL" = "0" ]; then
  echo "PASS: config drift check"
else
  echo "FAIL: config drift check"
fi
exit $FAIL
