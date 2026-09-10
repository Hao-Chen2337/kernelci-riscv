#!/usr/bin/env bash
# kernelci-riscv one-command entry: deploy -> run -> inspect.
# Usage: ./run.sh <subcommand> [args]; ./run.sh help for the full list.
# Details: docs/RUNBOOK.md (how to run it) and docs/INTERNAL-NOTES.md (deep dive).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIPE="$ROOT/kernelci-pipeline"
TUXRUN_BIN="${TUXRUN_BIN:-$(command -v tuxrun || echo "$HOME/.local/bin/tuxrun")}"
CALLBACK_TOKEN="${PULL_LABS_CALLBACK_TOKEN:-labtoken-callback}"
API_URL="${KCI_API_URL:-http://127.0.0.1:${KCI_API_PORT:-8001}}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

# Proxy handling lives in scripts/net-preflight.sh.  It probes the network with
# the configuration exactly as the user set it and only bypasses a proxy when
# asked (KCI_BYPASS_PROXY=1) or when the proxy is demonstrably broken - it never
# silently unsets a working proxy configuration the way the old no_proxy_setup()
# did (that function hardcoded one machine's dead proxy into the repository).
# shellcheck source=scripts/net-preflight.sh
. "$ROOT/scripts/net-preflight.sh"

cmd_help() {
  cat <<EOF
Subcommands:
  setup             One-time deploy: clone the 3 upstream repos + apply the
                    PR1/bullseye/nginx patches + run validate_yaml + generate
                    the deployment-local config (API .env + admin token, SSH
                    key pair - nothing secret is ever committed)
  provision         Produce/reuse the artifacts the runs need (kernel Image
                    under work/serve/, rootfs ext4 under work/env/) without
                    running any test
  fetch [--kvm] [--kvm-full] [--job name]
                    Tier A: re-run the newest production riscv build locally
                    (--kvm = the curated 8-test subset; --kvm-full = all)
  stack [--seed]    Start the local full stack: api/db/redis/storage/ssh +
                    artifact server + real callback + official scheduler
                    (--seed dispatches a kbuild node)
  worker [--once] [worker args...]
                    Take jobs, execute, report back (--once exits after the
                    queue; default --since takes only today's new jobs).
                    Other worker flags (--kvm-full/--kvm-tests/...) pass through.
  report            Latest baseline/kselftest node states
  verify            Full gate: validate_yaml + verify-lava-body +
                    verify-worker-guards + ruff (any failure fails this command)
  drift             Config drift between the newest two kbuild .config files
                    (any two via config_drift.py --older/--newer)
  trend             Regression pass-rate trend (reads KCI_API_URL: local =
                    accumulated history, production = current status)
  stop              Stop the whole local stack (incl. docker compose)
Env vars: TUXRUN_BIN, PULL_LABS_CALLBACK_TOKEN, KCI_API_URL, SINCE,
          KCI_BYPASS_PROXY=1 (ignore a broken proxy configuration)
EOF
}

cmd_setup() {
  # Only demand a working network when something actually has to be cloned:
  # re-running setup on a machine that already has the upstream checkouts must
  # not fail just because the network is down.
  local repo missing=0
  for repo in core api pipeline; do
    [ -d "$ROOT/kernelci-$repo" ] || missing=1
  done
  if [ "$missing" = 1 ]; then
    kci_net_preflight "upstream clone" || die \
      "cannot reach the upstream repositories; fix the network/proxy above first (KCI_BYPASS_PROXY=1 ignores a dead proxy)"
  fi
  for repo in core api pipeline; do
    if [ -d "$ROOT/kernelci-$repo" ]; then
      ok "kernelci-$repo present"
    else
      echo "-> cloning kernelci-$repo"
      kci_git_clone "https://github.com/kernelci/kernelci-$repo" \
        "$ROOT/kernelci-$repo" || die "cloning kernelci-$repo failed after retries"
    fi
  done
  # PR1 config patch; skipped once upstream contains it (same command
  # before/after the PR merges).  The patch landing is VERIFIED afterwards:
  # `git apply` failing quietly used to leave a stack with no riscv platform
  # at all, which validate_yaml cannot detect.
  if git -C "$PIPE" grep -q "qemu-riscv64" -- config/platforms.yaml 2>/dev/null; then
    ok "PR1 config present (pipeline already has the riscv platform, patch skipped)"
  else
    git -C "$PIPE" apply "$ROOT/config/pr1-config.patch" 2>/dev/null || \
      git -C "$PIPE" apply --3way "$ROOT/config/pr1-config.patch" 2>/dev/null || true
    if git -C "$PIPE" grep -q "qemu-riscv64" -- config/platforms.yaml 2>/dev/null; then
      ok "PR1 config patch applied"
    else
      die "PR1 config patch did not land: kernelci-pipeline/config/platforms.yaml has no qemu-riscv64 platform. Upstream moved - see docs/INTERNAL-NOTES.md"
    fi
  fi
  # bullseye archive-source patch (official Debian archive issue; needed to build the local ssh container)
  if grep -q archive.debian.org "$ROOT/kernelci-api/docker/ssh/Dockerfile" 2>/dev/null; then
    ok "bullseye patch present"
  else
    git -C "$ROOT/kernelci-api" apply "$ROOT/config/kernelci-api-bullseye-archive.patch" \
      && ok "bullseye patch applied" \
      || die "bullseye patch failed to apply; the ssh container will not build (inspect kernelci-api/docker/ssh/Dockerfile)"
  fi
  # storage nginx uid patch (jobdefs uploaded via scp must be readable by nginx as uid 1000)
  if grep -q "user: '1000:1000'" "$ROOT/kernelci-api/docker-compose.yaml" 2>/dev/null; then
    ok "storage nginx patch present"
  else
    git -C "$ROOT/kernelci-api" apply "$ROOT/config/kernelci-api-storage-nginx-user.patch" \
      && ok "storage nginx patch applied" \
      || die "storage nginx patch failed to apply; jobdef uploads will 404 (inspect kernelci-api/docker-compose.yaml)"
  fi
  # tuxlava patch (site-packages, cannot be applied here - just report)
  TUXLAVA_DIR="$(python3 -c 'import tuxlava,os;print(os.path.dirname(tuxlava.__file__))' 2>/dev/null || true)"
  if [ -n "$TUXLAVA_DIR" ] && grep -q "KselftestRiscv\|kselftest-riscv" "$TUXLAVA_DIR/tests/kselftest.py" 2>/dev/null; then
    ok "tuxlava patch applied"
  else
    # Derived, not hardcoded: "python3.10" is whatever Python this machine has,
    # and the path differs on 3.11/3.12 - which made the documented patch
    # command fail on any other machine.
    TUXLAVA_SITE="$(python3 -c 'import site;print(site.getusersitepackages())' 2>/dev/null \
      || echo "$HOME/.local/lib/python$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)/site-packages")"
    echo "  !! tuxlava patch missing: patch -p1 -d $TUXLAVA_SITE < $ROOT/config/tuxlava-kselftest-riscv.patch"
  fi
  [ -f "$PIPE/.env" ] || cat > "$PIPE/.env" <<'EOF'
KCI_API_TOKEN=fill in the local kernelci-api admin JWT (see kernelci-api local-instance docs)
NO_DOCKER_PULL=1
KCI_TREES=riscv
EOF
  # SOW Phase 1 acceptance clause: "First validation script successfully parsed locally"
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml failed"
  # Everything the runtime needs that is NOT in git: the API's .env (with its
  # own SECRET_KEY), the SSH key pair used to publish job definitions, and a
  # real API token.  Generated per deployment - no secrets are ever committed.
  if [ -f "$ROOT/scripts/local-instance-init.sh" ]; then
    echo "-> generating deployment-local configuration (API .env, SSH keys, API token)"
    bash "$ROOT/scripts/local-instance-init.sh" || die "local-instance-init.sh failed"
  else
    echo "  !! scripts/local-instance-init.sh missing; generate kernelci-api/.env, the SSH key pair and KCI_API_TOKEN before ./run.sh stack"
  fi
  ok "setup done"
}

cmd_provision() {
  kci_net_preflight "artifact download" \
    || die "no usable network for provisioning (see the proxy advice above)"
  TUXRUN_BIN="$TUXRUN_BIN" kci_run python3 \
    "$ROOT/scripts/fetch-and-run-latest.py" --provision-only
}

cmd_fetch() {
  # --kvm is run.sh's shortcut; every other arg passes through
  # (--kvm-full/--job/--test).
  local args=()
  local a
  for a in "$@"; do
    if [ "$a" = "--kvm" ]; then
      args+=("--test" "kselftest-kvm")
    else
      args+=("$a")
    fi
  done
  kci_net_preflight "artifact download" \
    || echo "    (continuing: fetch reports its own download errors)"
  TUXRUN_BIN="$TUXRUN_BIN" kci_run python3 "$ROOT/scripts/fetch-and-run-latest.py" "${args[@]}"
}

cmd_stack() {
  bash "$ROOT/scripts/run-local-stack.sh" "$@"
}

cmd_worker() {
  local since="${SINCE:-$(date -u +%Y-%m-%d)T00:00:00}"
  local extra=()
  local a
  # Every argument passes through: this used to keep only "$2", so `--kvm-full`
  # or `--kvm-tests ...` were dropped without a word.
  for a in "$@"; do
    [ -n "$a" ] && extra+=("$a")
  done
  kci_net_preflight "job polling" \
    || echo "    (continuing: the worker retries and reports infra errors honestly)"
  # mkfs.ext4 lives in /usr/sbin on Debian/Ubuntu; run-local-stack.sh's worker
  # invocation already added it, this one did not - two entry points, two
  # behaviours for the same job.
  #
  # The state file and workspace carry the compose project in their names: two
  # deployments on one machine do not share node ids, and a shared "already
  # seen" set would silently make one of them skip its own queue.
  local project="${KCI_COMPOSE_PROJECT:-kcirv}"
  PYTHONUNBUFFERED=1 PULL_LABS_CALLBACK_TOKEN="$CALLBACK_TOKEN" \
    PATH="/usr/local/sbin:/usr/sbin:$PATH" \
    kci_run python3 "$ROOT/scripts/riscv_pull_worker.py" \
    --api-url "$API_URL" --tuxrun-bin "$TUXRUN_BIN" \
    --container-runtime docker --output-dir "/tmp/kci-worker-$project-out" \
    --state-file "/tmp/kci-worker-$project-state.json" --poll-period 5 --max-timeout 1200 \
    --since "$since" "${extra[@]}"
}

cmd_report() {
  local name
  for name in baseline-riscv-pull-labs kselftest-riscv-pull-labs kselftest-kvm-riscv-pull-labs; do
    echo "--- $name (newest 3) ---"
    # Robust against an unreachable API, an empty result and a node without an
    # id: this used to traceback (json.load on an empty body, n["id"][:16] on
    # None) exactly when the stack was down and the answer mattered.
    # limit stays generous: the API returns nodes in its own order, so a small
    # page can miss the newest ones entirely.
    kci_curl -s -m 10 "$API_URL/latest/nodes?kind=job&name=$name&limit=100" \
      | python3 -c '
import json, sys
try:
    items = json.load(sys.stdin).get("items", [])
except Exception as error:
    print("  (no usable response from the API: %s)" % error)
    raise SystemExit(0)
if not items:
    print("  (no nodes)")
items = sorted(items, key=lambda n: n.get("created") or "", reverse=True)
for n in items[:3]:
    revision = (n.get("data") or {}).get("kernel_revision") or {}
    print("  {:16s} {:12s} {:14s} {} ({})".format(
        (n.get("id") or "?")[:16], n.get("state") or "-", n.get("result") or "-",
        (revision.get("describe") or "?")[:30], (n.get("created") or "")[:10]))'
  done
}

cmd_verify() {
  # Every gate must be able to fail this command.  Piping a check into
  # `tail -1` (or trailing it with `|| true`) throws its exit status away, so
  # this "full gate" used to print a traceback and still exit 0 - it reported
  # success precisely when it should have reported a crash.
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml failed"
  python3 "$ROOT/scripts/verify-lava-body.py" || die "verify-lava-body failed"
  python3 "$ROOT/scripts/verify-worker-guards.py" || die "verify-worker-guards failed"
  # ruff checks our own scripts/ (upstream clones and work/ are gitignored)
  (cd "$ROOT" && ruff check .) || die "ruff failed"
  ok "verify: all gates passed"
}

cmd_drift() {
  kci_net_preflight "kernelci API" \
    || echo "    (continuing: drift reports its own API errors)"
  KCI_API_URL="$API_URL" kci_run python3 "$ROOT/scripts/config_drift.py" --json --job kbuild-gcc-14-riscv
}

cmd_trend() {
  kci_net_preflight "kernelci API" \
    || echo "    (continuing: trend reports its own API errors)"
  KCI_API_URL="$API_URL" kci_run python3 "$ROOT/scripts/regression_tracker.py" trend
}

cmd_stop() {
  # Same overridable identity as the stack: one machine can host more than one
  # isolated deployment (its own compose project, volumes and ports), and
  # stopping one must not stop the other.
  local project="${KCI_COMPOSE_PROJECT:-kcirv}"
  local serve_port="${KCI_SERVE_PORT:-8999}"
  pkill -f "scheduler.py.*pull-labs-riscv" 2>/dev/null && echo "scheduler stopped"
  pkill -f "uvicorn lava_callback" 2>/dev/null && echo "callback stopped"
  pkill -f "http.server $serve_port" 2>/dev/null && echo "artifact server stopped"
  # API stack (api/db/redis/storage/ssh) runs under docker compose; data stays
  # in volumes, `stack` brings it back as-is.
  if [ -d "$ROOT/kernelci-api" ] && docker compose -p "$project" -f "$ROOT/kernelci-api/docker-compose.yaml" down >/dev/null 2>&1; then
    echo "API stack stopped (project $project)"
  fi
}

case "${1:-help}" in
  setup)     cmd_setup ;;
  provision) cmd_provision ;;
  fetch)     shift; cmd_fetch "$@" ;;
  stack)     shift; cmd_stack "$@" ;;
  worker)    shift; cmd_worker "$@" ;;
  report)    cmd_report ;;
  verify)    cmd_verify ;;
  drift)     cmd_drift ;;
  trend)     cmd_trend ;;
  stop)      cmd_stop ;;
  help|*)    cmd_help ;;
esac
