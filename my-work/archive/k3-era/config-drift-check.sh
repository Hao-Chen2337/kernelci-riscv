#!/usr/bin/env bash
# Config drift detection: required kernel options must be =y
set -uo pipefail

CONFIG_FILE="${1:-/boot/config-$(uname -r)}"
REQUIRED=(CONFIG_RISCV_ISA_V CONFIG_EXT4_FS CONFIG_DEVTMPFS CONFIG_DEVTMPFS_MOUNT CONFIG_KVM)

[ -f "$CONFIG_FILE" ] || { echo "FAIL: config not found: $CONFIG_FILE"; exit 1; }

FAIL=0
for opt in "${REQUIRED[@]}"; do
  if grep -q "^${opt}=y$" "$CONFIG_FILE" 2>/dev/null; then
    echo "  ok: $opt"
  else
    echo "FAIL: $opt missing or not =y"; FAIL=1
  fi
done
[ "$FAIL" = "0" ] && echo "PASS: config drift check" || echo "FAIL: config drift check"
exit $FAIL
