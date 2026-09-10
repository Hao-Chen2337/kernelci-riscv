#!/usr/bin/env bash
# kernelci-riscv one-command entry: deploy -> run -> inspect.
# Usage: ./run.sh <subcommand> [args]; ./run.sh help for the full list.
# Details: README.md section 2 (quick) and docs/tools-guide.md (deep dive).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIPE="$ROOT/kernelci-pipeline"
TUXRUN_BIN="${TUXRUN_BIN:-$(command -v tuxrun || echo /home/hao/.local/bin/tuxrun)}"
CALLBACK_TOKEN="${PULL_LABS_CALLBACK_TOKEN:-labtoken-callback}"
API_URL="${KCI_API_URL:-http://127.0.0.1:8001}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }
no_proxy_setup() {
  # The local 127.0.0.1:7890 proxy is dead; direct access works. Drop it
  # before any production-API/artifact download or the request hangs.
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null || true
}

cmd_help() {
  cat <<EOF
Subcommands:
  setup             One-time deploy: clone the 3 upstream repos + apply the
                    PR1/bullseye/nginx patches + run validate_yaml
  fetch [--kvm] [--kvm-full] [--job name]
                    Tier A: re-run the newest production riscv build locally
                    (--kvm = the curated 9-test subset; --kvm-full = all)
  stack [--seed]    Start the local full stack: api/db/redis/storage/ssh +
                    artifact server + real callback + official scheduler
                    (--seed dispatches a kbuild node)
  worker [--once]   Take jobs, execute, report back (--once exits after the
                    queue; default --since takes only today's new jobs)
  report            Latest baseline/kselftest node states
  verify            Full gate: validate_yaml + verify-lava-body +
                    verify-worker-guards + ruff (our own scripts/)
  drift             Config drift between the newest two kbuild .config files
                    (any two via config_drift.py --older/--newer)
  trend             Regression pass-rate trend (reads KCI_API_URL: local =
                    accumulated history, production = current status)
  stop              Stop the whole local stack (incl. docker compose)
Env vars: TUXRUN_BIN, PULL_LABS_CALLBACK_TOKEN, KCI_API_URL, SINCE
EOF
}

cmd_setup() {
  [ -d "$ROOT/kernelci-core" ] || git clone --depth 1 https://github.com/kernelci/kernelci-core
  [ -d "$ROOT/kernelci-api" ] || git clone --depth 1 https://github.com/kernelci/kernelci-api
  [ -d "$ROOT/kernelci-pipeline" ] || git clone --depth 1 https://github.com/kernelci/kernelci-pipeline
  # PR1 config patch; skipped once upstream contains it (same command
  # before/after the PR merges).
  if git -C "$PIPE" grep -q "qemu-riscv64" -- config/platforms.yaml 2>/dev/null; then
    ok "PR1 config present (pipeline already has the riscv platform, patch skipped)"
  else
    git -C "$PIPE" apply "$ROOT/config/pr1-config.patch" 2>/dev/null || \
      git -C "$PIPE" apply --3way "$ROOT/config/pr1-config.patch" 2>/dev/null || \
      { echo "  PR1 patch not applied (maybe already applied or upstream changed); current state:"; git -C "$PIPE" status --short | head; }
  fi
  # bullseye archive-source patch (official Debian archive issue; needed to build the local ssh container)
  if grep -q archive.debian.org "$ROOT/kernelci-api/docker/ssh/Dockerfile" 2>/dev/null; then
    ok "bullseye patch present"
  else
    git -C "$ROOT/kernelci-api" apply "$ROOT/config/kernelci-api-bullseye-archive.patch" \
      && ok "bullseye patch applied" || echo "  !! bullseye patch failed; the ssh container build may fail"
  fi
  # storage nginx uid patch (jobdefs uploaded via scp must be readable by nginx as uid 1000)
  if grep -q "user: '1000:1000'" "$ROOT/kernelci-api/docker-compose.yaml" 2>/dev/null; then
    ok "storage nginx patch present"
  else
    git -C "$ROOT/kernelci-api" apply "$ROOT/config/kernelci-api-storage-nginx-user.patch" \
      && ok "storage nginx patch applied" || echo "  !! storage nginx patch failed; jobdef uploads may 404"
  fi
  # tuxlava patch (site-packages, cannot be applied here - just report)
  TUXLAVA_DIR="$(python3 -c 'import tuxlava,os;print(os.path.dirname(tuxlava.__file__))' 2>/dev/null || true)"
  if [ -n "$TUXLAVA_DIR" ] && grep -q "KselftestRiscv\|kselftest-riscv" "$TUXLAVA_DIR/tests/kselftest.py" 2>/dev/null; then
    ok "tuxlava patch applied"
  else
    echo "  !! tuxlava patch missing: cd ~/.local/lib/python3.10/site-packages && patch -p1 < $ROOT/config/tuxlava-kselftest-riscv.patch"
  fi
  [ -f "$PIPE/.env" ] || cat > "$PIPE/.env" <<'EOF'
KCI_API_TOKEN=fill in the local kernelci-api admin JWT (see kernelci-api local-instance docs)
NO_DOCKER_PULL=1
KCI_TREES=riscv
EOF
  # SOW Phase 1 acceptance clause: "First validation script successfully parsed locally"
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml failed"
  ok "setup done; tier B still needs KCI_API_TOKEN in kernelci-pipeline/.env"
}

cmd_fetch() {
  # --kvm is run.sh's shortcut; every other arg passes through
  # (--kvm-full/--job/--test).
  local args=()
  for a in "$@"; do
    if [ "$a" = "--kvm" ]; then
      args+=("--test" "kselftest-kvm")
    else
      args+=("$a")
    fi
  done
  no_proxy_setup
  TUXRUN_BIN="$TUXRUN_BIN" python3 "$ROOT/scripts/fetch-and-run-latest.py" "${args[@]}"
}

cmd_stack() {
  if [ "${1:-}" = "--seed" ]; then
    bash "$ROOT/scripts/run-local-stack.sh" --seed
  else
    bash "$ROOT/scripts/run-local-stack.sh"
  fi
}

cmd_worker() {
  local since="${SINCE:-$(date -u +%Y-%m-%d)T00:00:00}"
  local extra=()
  [ "${1:-}" = "--once" ] && extra=("--once")
  no_proxy_setup
  PYTHONUNBUFFERED=1 PULL_LABS_CALLBACK_TOKEN="$CALLBACK_TOKEN" \
    python3 "$ROOT/scripts/riscv_pull_worker.py" \
    --api-url "$API_URL" --tuxrun-bin "$TUXRUN_BIN" \
    --container-runtime docker --output-dir /tmp/official-loop-out \
    --state-file /tmp/official-loop-state.json --poll-period 5 --max-timeout 1200 \
    --since "$since" "${extra[@]}"
}

cmd_report() {
  for name in baseline-riscv-pull-labs kselftest-riscv-pull-labs kselftest-kvm-riscv-pull-labs; do
    echo "--- $name (newest 3) ---"
    curl -s "$API_URL/latest/nodes?kind=job&name=$name&limit=100" \
      | python3 -c '
import json, sys
d = json.load(sys.stdin)
items = sorted(d.get("items", []), key=lambda n: n.get("created") or "", reverse=True)
for n in items[:3]:
    r = (n.get("data") or {}).get("kernel_revision") or {}
    print("  {:16s} {:12s} {:14s} {} ({})".format(
        n["id"][:16], n.get("state") or "-", n.get("result") or "-",
        (r.get("describe") or "?")[:30], (n.get("created") or "")[:10]))'
  done
}

cmd_verify() {
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml failed"
  python3 "$ROOT/scripts/verify-lava-body.py" | tail -1
  python3 "$ROOT/scripts/verify-worker-guards.py" | tail -1
  # ruff checks our own scripts/ (upstream clones and work/ are gitignored)
  (cd "$ROOT" && ruff check . 2>/dev/null | tail -1) || true
}

cmd_drift() {
  no_proxy_setup
  KCI_API_URL="$API_URL" python3 "$ROOT/scripts/config_drift.py" --json --job kbuild-gcc-14-riscv
}

cmd_trend() {
  no_proxy_setup
  KCI_API_URL="$API_URL" python3 "$ROOT/scripts/regression_tracker.py" trend
}

cmd_stop() {
  pkill -f "scheduler.py.*pull-labs-riscv" 2>/dev/null && echo "scheduler stopped"
  pkill -f "uvicorn lava_callback" 2>/dev/null && echo "callback stopped"
  pkill -f "http.server 8999" 2>/dev/null && echo "artifact server stopped"
  # API stack (api/db/redis/storage/ssh) runs under docker compose; data stays
  # in volumes, `stack` brings it back as-is.
  if [ -d "$ROOT/kernelci-api" ] && docker compose -p kcirv -f "$ROOT/kernelci-api/docker-compose.yaml" down >/dev/null 2>&1; then
    echo "API stack stopped"
  fi
}

case "${1:-help}" in
  setup)  cmd_setup ;;
  fetch)  shift; cmd_fetch "$@" ;;
  stack)  cmd_stack "${2:-}" ;;
  worker) cmd_worker "${2:-}" ;;
  report) cmd_report ;;
  verify) cmd_verify ;;
  drift)  cmd_drift ;;
  trend)  cmd_trend ;;
  stop)   cmd_stop ;;
  help|*) cmd_help ;;
esac
