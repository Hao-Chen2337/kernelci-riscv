#!/usr/bin/env bash
# KVM selftests: real-hardware Hypervisor tests
# Usage: sudo bash run-kvm-tests.sh   (root required to access /dev/kvm)
set -uo pipefail

WORKDIR="${WORKDIR:-}"
# Locate kernel source (sudo changes HOME to /root; fall back to real user's kci)
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

# 1. Preflight checks
[ "$(id -u)" -eq 0 ] || { echo "FAIL: run as root: sudo bash run-kvm-tests.sh"; exit 1; }
[ -e /dev/kvm ] || { echo "SKIP: no /dev/kvm (no H extension, expected)"; exit 0; }
[ -d "$WORKDIR/linux" ] || { echo "FAIL: kernel source not found: $WORKDIR/linux"; exit 1; }

echo "==> /dev/kvm ready"
ls -l /dev/kvm

# 2. Build KVM selftests
echo "==> Building KVM selftests"
cd "$WORKDIR/linux"
make ARCH=riscv -C tools/testing/selftests/kvm -j"$(nproc)" 2>&1 | tail -25

# 3. List built test binaries
cd tools/testing/selftests/kvm
echo ""
echo "==> Built test binaries"
BINS=$(find . -maxdepth 2 -type f -executable ! -name '*.sh' 2>/dev/null | head -20)
echo "$BINS"

# 4. Run each (official kselftest default 45s timeout; perf/stress timeout is expected)
echo ""
echo "==> Running KVM tests"
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
echo "===== KVM results ====="
echo "pass: $PASS  fail: $FAIL"
echo "log: $RESULT_DIR/kvm.log"
