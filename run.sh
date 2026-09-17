#!/usr/bin/env bash
# kernelci-riscv one-command entry: deploy -> run -> inspect.
# Usage: ./run.sh <subcommand> [args]; ./run.sh help lists them.
# Details: docs/RUNBOOK.md, docs/INTERNAL-NOTES.md; rationale: code-notes/W2b-entrypoints.md.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIPE="$ROOT/kernelci-pipeline"
TUXRUN_BIN="${TUXRUN_BIN:-$(command -v tuxrun || echo "$HOME/.local/bin/tuxrun")}"
CALLBACK_TOKEN="${PULL_LABS_CALLBACK_TOKEN:-labtoken-callback}"
API_URL="${KCI_API_URL:-http://127.0.0.1:${KCI_API_PORT:-8001}}"
# Storage service publishing build artifacts; config_drift falls back to it for a
# kbuild node with no _config artifact.  Must follow KCI_STORAGE_PORT too - a
# deployment on 18002 used to be read from the fixed 8002.
STORAGE_URL="${KCI_STORAGE_URL:-http://127.0.0.1:${KCI_STORAGE_PORT:-8002}}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

# Proxy handling lives in scripts/net-preflight.sh (bypass only on
# KCI_BYPASS_PROXY=1 or a demonstrably broken proxy - never silently).
# KCI_PROBE_URL is captured BEFORE sourcing; the preflight below honours it.
KCI_PROBE_URL_OVERRIDE="${KCI_PROBE_URL:-}"
# shellcheck source=scripts/net-preflight.sh
. "$ROOT/scripts/net-preflight.sh"

# Probe the endpoint(s) the NEXT command actually talks to, naming the URL really
# probed: a general "network is fine" verdict once hid a proxy that killed the
# next command (RUN-MODES-AND-BUGS.md #17); returns 1 when any endpoint failed.
kci_preflight() {
  local label="$1" url probe failed=0
  shift
  for url in "$@"; do
    probe="${KCI_PROBE_URL_OVERRIDE:-$url}"
    KCI_PROBE_URL="$probe" kci_net_preflight "$label @ $probe" || failed=1
  done
  if [ "$failed" = 1 ]; then
    echo "    note: only the endpoint(s) printed above were checked; this says"
    echo "          nothing about any other host the command may need."
  fi
  return "$failed"
}

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
  report            Latest baseline/kselftest node states (incl. the job's
                    data.error_type, which docs/RUNBOOK.md says to read first)
  results [--build ID] [--json] [--list]
                    What this machine has recorded: read the local result
                    ledger work/results/<build-id>/<test>.json (no API needed)
  build index [--days N] [--tree T]...
                    Pull the build index (work/builds.db) from the production
                    API: which kbuild-gcc-14-riscv builds exist and are usable.
                    Read-only, no token, no local stack.
  jobs [--build ID] [--test T]...
                    List the jobs a build would produce (default: the three the
                    pull-labs-riscv config claims). Runs nothing.
  todo [--build ID]
                    What is in the index but not in the result ledger yet.
  summary [--no-api]
                    The whole local job table at a glance: the build index, the
                    ledger's runs and verdicts, what is pending, and the local
                    API's node counts (skipped with --no-api).
  dashboard [--port N]
                    Serve the local job table as a read-only page
                    (http://127.0.0.1:8079/) - index, runs, pending, API counts
  run [--build ID] [--test T]... [--limit N] [--callback-url URL]
                    Run the pending jobs one at a time, recording each in the
                    ledger as it finishes. Without --callback-url nothing is
                    posted anywhere - the ledger is the only sink.
  prune [--keep N] [--dry-run]
                    Retention for work/downloads (one ~45 MB directory per
                    fetched build): keep the newest N (default 5) plus the
                    build work/env/build.env records.  Never touches the build
                    this deployment serves; --dry-run only reports
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
  # PR1 config patch, skipped once upstream carries it; the landing is verified
  # below - a silently failed `git apply` left a stack with no riscv platform.
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
  # bullseye archive-source patch: without it the local ssh container will not build.
  if grep -q archive.debian.org "$ROOT/kernelci-api/docker/ssh/Dockerfile" 2>/dev/null; then
    ok "bullseye patch present"
  else
    git -C "$ROOT/kernelci-api" apply "$ROOT/config/kernelci-api-bullseye-archive.patch" \
      && ok "bullseye patch applied" \
      || die "bullseye patch failed to apply; the ssh container will not build (inspect kernelci-api/docker/ssh/Dockerfile)"
  fi
  # storage nginx user patch: jobdefs scp'd in must be readable by nginx as uid 1000.
  if grep -q "user: '1000:1000'" "$ROOT/kernelci-api/docker-compose.yaml" 2>/dev/null; then
    ok "storage nginx patch present"
  else
    git -C "$ROOT/kernelci-api" apply "$ROOT/config/kernelci-api-storage-nginx-user.patch" \
      && ok "storage nginx patch applied" \
      || die "storage nginx patch failed to apply; jobdef uploads will 404 (inspect kernelci-api/docker-compose.yaml)"
  fi
  # tuxlava patch lives in site-packages: report it, cannot apply it here.
  TUXLAVA_DIR="$(python3 -c 'import tuxlava,os;print(os.path.dirname(tuxlava.__file__))' 2>/dev/null || true)"
  # Apply the patch where tuxlava IS, not this interpreter's user site-packages:
  # a virtualenv or a system install puts the two in different trees (N8).
  if [ -n "$TUXLAVA_DIR" ]; then
    TUXLAVA_SITE="$(dirname "$TUXLAVA_DIR")"
  else
    TUXLAVA_SITE="$(python3 -c 'import site;print(site.getusersitepackages())' 2>/dev/null \
      || echo "$HOME/.local/lib/python$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)/site-packages")"
  fi
  if [ -z "$TUXLAVA_DIR" ]; then
    # tuxlava missing entirely is a different problem with a different fix.
    echo "  !! tuxlava is not importable: run the jobs' guest setup needs it (pip install tuxrun pulls it in)"
  elif grep -q "KselftestRiscv\|kselftest-riscv" "$TUXLAVA_DIR/tests/kselftest.py" 2>/dev/null; then
    ok "tuxlava patch applied"
  else
    # Deferred to the END of setup on purpose: a hard prerequisite for the riscv
    # kselftest jobs (tuxlava missing = tuxrun exit 2 = filed as an infrastructure
    # error) whose `!!` line went unnoticed mid-setup; non-fatal for baseline only.
    TUXLAVA_PATCH_MISSING="$TUXLAVA_SITE"
  fi
  [ -f "$PIPE/.env" ] || cat > "$PIPE/.env" <<'EOF'
KCI_API_TOKEN=fill in the local kernelci-api admin JWT (see kernelci-api local-instance docs)
NO_DOCKER_PULL=1
KCI_TREES=riscv
EOF
  # SOW Phase 1 acceptance clause: "First validation script successfully parsed locally"
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml failed"
  # Everything the runtime needs that is NOT in git: the API's .env (own
  # SECRET_KEY), the SSH key pair and a real API token - never committed.
  if [ -f "$ROOT/scripts/local-instance-init.sh" ]; then
    echo "-> generating deployment-local configuration (API .env, SSH keys, API token)"
    bash "$ROOT/scripts/local-instance-init.sh" || die "local-instance-init.sh failed"
  else
    echo "  !! scripts/local-instance-init.sh missing; generate kernelci-api/.env, the SSH key pair and KCI_API_TOKEN before ./run.sh stack"
  fi
  ok "setup done"
  if [ -n "${TUXLAVA_PATCH_MISSING:-}" ]; then
    # Printed last, deliberately: its absence surfaces much later as an
    # unexplained "Infrastructure" job error.
    echo
    echo "================================ WARNING ================================"
    echo "tuxlava is NOT patched, so the kselftest-riscv job cannot run: tuxrun"
    echo "derives its --tests choices from tuxlava and exits 2 without the class."
    echo "Apply the one-time patch from docs/RUNBOOK.md now:"
    echo
    echo "  patch -p1 -d $TUXLAVA_PATCH_MISSING \\"
    echo "    < $ROOT/config/tuxlava-kselftest-riscv.patch"
    echo
    echo "setup itself succeeded (exit 0); only the kselftest-riscv job needs this."
    echo "========================================================================"
  fi
}

cmd_provision() {
  # Two hosts: the production API picks the newest passing kbuild, then the
  # artifacts come from files.kernelci.org - probe both, separately.
  kci_preflight "provisioning" \
    "https://api.kernelci.org/latest/" "https://files.kernelci.org/" \
    || die "no usable network for provisioning (see the proxy advice above)"
  TUXRUN_BIN="$TUXRUN_BIN" kci_run python3 \
    "$ROOT/scripts/fetch-and-run-latest.py" --provision-only
}

cmd_fetch() {
  # --kvm is run.sh's shortcut; --kvm-full/--job/--test pass through as they are.
  local args=()
  local a
  for a in "$@"; do
    if [ "$a" = "--kvm" ]; then
      args+=("--test" "kselftest-kvm")
    else
      args+=("$a")
    fi
  done
  # fetch discovers the build on the production API and downloads the kernel,
  # modules and kselftest from files.kernelci.org - probe both, separately.
  if ! kci_preflight "fetch" \
      "https://api.kernelci.org/latest/" "https://files.kernelci.org/"; then
    echo "    !! continuing anyway: the endpoint(s) marked X above cannot carry this"
    echo "       run, so fetch will fail or report its own download/API errors -"
    echo "       the exit status below is fetch's, not this preflight's."
  fi
  TUXRUN_BIN="$TUXRUN_BIN" kci_run python3 "$ROOT/scripts/fetch-and-run-latest.py" "${args[@]}"
}

cmd_stack() {
  bash "$ROOT/scripts/run-local-stack.sh" "$@"
}

cmd_worker() {
  local since="${SINCE:-$(date -u +%Y-%m-%d)T00:00:00}"
  local extra=()
  local a
  # Every argument passes through (this used to keep only "$2" and drop the rest).
  for a in "$@"; do
    [ -n "$a" ] && extra+=("$a")
  done
  # The worker polls THIS deployment's API and downloads production artifact URLs
  # from files.kernelci.org - two hosts, probed and named separately.
  if ! kci_preflight "worker" "$API_URL/latest/" "https://files.kernelci.org/"; then
    echo "    !! continuing anyway: the worker retries and reports infra errors honestly,"
    echo "       but a run whose endpoints are marked X above cannot do useful work."
  fi
  # PATH needs /usr/sbin for mkfs.ext4 on Debian/Ubuntu (only the stack's worker
  # invocation used to add it).
  #
  # The state file and workspace carry the compose project name: a shared "already
  # seen" set would make one of two deployments skip its own queue.
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
  # The node name is the job name, so the kvm entry is the shared
  # kselftest-kvm-pull-labs definition, not a riscv-specific one.
  for name in baseline-riscv-pull-labs kselftest-riscv-pull-labs kselftest-kvm-pull-labs; do
    echo "--- $name (newest 3) ---"
    # Robust against an unreachable API, an empty result and a node without an id -
    # it used to traceback exactly when the stack was down.  limit stays generous:
    # the API orders nodes its own way, so a small page can miss the newest.
    kci_curl -s -m 10 "$API_URL/latest/nodes?kind=job&name=$name&limit=100" \
      | python3 -c '
import json, sys
try:
    items = json.load(sys.stdin).get("items", [])
except Exception as error:
    print("  (no usable response from the API: %s)" % error)
    raise SystemExit(0)
# Full 24-character id: a [:16] truncation made two nodes of one name print identically.
items = sorted(items, key=lambda n: n.get("created") or "", reverse=True)
if not items:
    print("  (no nodes)")
for n in items[:3]:
    data = n.get("data") or {}
    revision = data.get("kernel_revision") or {}
    # error_code AND error_type on purpose: the runbook names error_type, the
    # kernelci-core lava runtime writes error_code, and one spelling alone shows
    # "-" for real infra failures.  No apostrophes: single-quoted shell string.
    error_type = data.get("error_type") or data.get("error_code") or "-"
    print("  {:24s} {:12s} {:14s} {:14s} {} ({})".format(
        n.get("id") or "?", n.get("state") or "-", n.get("result") or "-",
        error_type,
        (revision.get("describe") or "?")[:30], (n.get("created") or "")[:10]))
if len(items) > 3:
    print("  (%d node(s) matched, newest 3 shown)" % len(items))' \
      || true
    # `|| true`: curl fails when the API is down, and under pipefail that became
    # the exit status of the report even though the message above is what is needed (N6).
  done
}

cmd_dashboard() {
  # A read-only page over the local job table - what ./run.sh summary prints.
  # Not the upstream kernelci-frontend: that is a 2024 Flask app showing its own
  # data (its config lives in another repo, with its own MongoDB connection).
  python3 "$ROOT/scripts/dashboard.py" "$@"
}

cmd_local_jobs() {
  # The local job table (build index + ledger view) you look at - deliberately
  # not 'worker', which is the resident claimer.  Everything here works without
  # the local stack and without the upstream config being merged.
  python3 "$ROOT/scripts/local-jobs.py" "$@"
}

cmd_results() {
  # The durable record this machine produced, read back from local files:
  # work/results/<build>/<test>.json, written by ./run.sh fetch and by the
  # resident worker.  Works with the stack stopped - NOT the API report above.
  python3 "$ROOT/scripts/results.py" "$@"
}

cmd_prune() {
  # Retention for work/downloads/<node_id>/ (~45 MB per fetched build; a daily
  # fetch loop is ~16 GB/year).  Keeps the newest --keep builds and the one
  # work/env/build.env records; --dry-run prints the list and deletes nothing.
  local keep=5 dry=0 want_keep=0 arg
  for arg in "$@"; do
    if [ "$want_keep" = 1 ]; then
      case "$arg" in
        ''|*[!0-9]*) die "prune: --keep takes a whole number of builds, got '$arg'" ;;
        *) keep="$arg" ;;
      esac
      want_keep=0
      continue
    fi
    case "$arg" in
      --keep) want_keep=1 ;;
      --dry-run) dry=1 ;;
      *) die "prune: unknown argument '$arg' (usage: ./run.sh prune [--keep N] [--dry-run])" ;;
    esac
  done
  [ "$want_keep" = 0 ] || die "prune: --keep needs a value"
  [ "$keep" -ge 1 ] || die "prune: --keep must be at least 1 - the newest build is the one ./run.sh stack --seed serves"
  python3 - "$ROOT/work/downloads" "$keep" "$dry" "$ROOT/work/env/build.env" <<'PY'
import json
import os
import re
import shutil
import sys
import time

downloads, keep, dry, build_env = (
    sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1", sys.argv[4]
)
if not os.path.isdir(downloads):
    print(f"nothing to prune: {downloads} does not exist")
    raise SystemExit(0)

# The build this deployment serves, as ./run.sh provision recorded it.
commit = build_dir_id = ""
if os.path.exists(build_env):
    text = open(build_env).read()
    match = re.search(r"^KCI_BUILD_COMMIT=(\S+)", text, re.M)
    commit = match.group(1) if match else ""
    match = re.search(r"^KCI_BUILD_DIR=(\S+)", text, re.M)
    build_dir_id = os.path.basename(match.group(1)) if match else ""

entries = []
for name in sorted(os.listdir(downloads)):
    path = os.path.join(downloads, name)
    if not os.path.isdir(path):
        continue
    size = 0
    for root, _dirs, files in os.walk(path):
        for filename in files:
            try:
                size += os.path.getsize(os.path.join(root, filename))
            except OSError:
                pass
    entries.append((os.path.getmtime(path), name, path, size))
entries.sort(reverse=True)

def recorded_commit(path):
    """Commit of the kbuild the directory was downloaded from (node.json)."""
    try:
        with open(os.path.join(path, "node.json")) as handle:
            data = (json.load(handle).get("data") or {})
        return (data.get("kernel_revision") or {}).get("commit") or ""
    except (OSError, ValueError):
        return ""

newest = {name for _m, name, _p, _s in entries[:keep]}
print(
    f"work/downloads: {len(entries)} build(s); keeping the newest {keep}"
    + (f" and the build.env build ({commit[:12]})" if commit else "")
)
removed = freed = 0
for mtime, name, path, size in entries:
    if name in newest:
        why = "keep: newest"
    elif name == build_dir_id or (commit and recorded_commit(path) == commit):
        why = "keep: the build work/env/build.env records and work/serve/Image serves"
    else:
        why = "PRUNE"
    print(
        f"  {name}  {size / 1e6:8.1f} MB  "
        f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))}  {why}"
    )
    if why == "PRUNE":
        removed += 1
        freed += size
        if not dry:
            shutil.rmtree(path)
print(
    ("would remove" if dry else "removed")
    + f" {removed} build(s), {freed / 1e6:.1f} MB"
    + (" (dry run: nothing was deleted)" if dry else "")
)
PY
}

cmd_verify() {
  # Every gate must be able to fail this command: a `tail -1` or a trailing
  # `|| true` threw the exit status away and this "full gate" once exited 0 on a
  # traceback.  Their own tools are checked first, so a missing ruff says what to install.
  local missing=()
  command -v ruff >/dev/null 2>&1 || missing+=("ruff")
  python3 -c 'import yaml' >/dev/null 2>&1 || missing+=("PyYAML")
  [ "${#missing[@]}" -eq 0 ] || die \
    "verify needs: ${missing[*]} - install with: python3 -m pip install -r requirements.txt"
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml failed"
  python3 "$ROOT/scripts/tools/verify-lava-body.py" || die "verify-lava-body failed"
  python3 "$ROOT/scripts/tools/verify-worker-guards.py" || die "verify-worker-guards failed"
  # Compile the entry points and the library too: the guards import the library
  # only, so a syntax error elsewhere used to reach the user as a traceback.
  python3 -m compileall -q "$ROOT/scripts" >/dev/null || die "compileall failed"
  # ruff checks our own scripts/ (upstream clones and work/ are gitignored)
  (cd "$ROOT" && ruff check .) || die "ruff failed"
  ok "verify: all gates passed"
}

cmd_drift() {
  # The probe endpoint and the API used below are the same URL (the old "kernelci
  # API" verdict came from probing files.kernelci.org).
  if ! kci_preflight "config drift" "$API_URL/latest/"; then
    echo "    !! continuing anyway: drift reports its own API errors"
  fi
  # KCI_STORAGE_URL: config_drift's fallback for a node without a _config
  # artifact must point at THIS deployment's storage, not at its built-in 8002.
  KCI_API_URL="$API_URL" KCI_STORAGE_URL="$STORAGE_URL" \
    kci_run python3 "$ROOT/scripts/tools/config_drift.py" --json --job kbuild-gcc-14-riscv
}

cmd_trend() {
  if ! kci_preflight "regression trend" "$API_URL/latest/"; then
    echo "    !! continuing anyway: trend reports its own API errors"
  fi
  KCI_API_URL="$API_URL" kci_run python3 "$ROOT/scripts/tools/regression_tracker.py" trend
}

# Stop ONE deployment's host services from the records run-local-stack.sh wrote
# (role|pid|start|pattern).  The pid's start time is re-read first: a record whose
# pid was meanwhile reused by an unrelated process must not kill that process.
stop_recorded_services() {   # pid-file
  local file="$1" role pid start pattern now killed=0
  while IFS='|' read -r role pid start pattern; do
    [ -n "${pid:-}" ] || continue
    if [ ! -d "/proc/$pid" ]; then
      echo "  $role: pid $pid is gone already"
      continue
    fi
    now="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
    if [ "$now" != "$start" ]; then
      echo "  !! $role: pid $pid now belongs to an unrelated process (start time changed); NOT killing it"
      continue
    fi
    if kill "$pid" 2>/dev/null; then
      echo "  $role stopped (pid $pid)"
      killed=$((killed + 1))
    else
      echo "  !! $role (pid $pid) could not be killed - check it by hand: ps -p $pid -o args="
    fi
  done < "$file"
  echo "  $killed host service(s) stopped from $file"
}

cmd_stop() {
  # Same overridable identity as the stack: one machine can host several isolated
  # deployments, and stopping one must not stop another.
  local project="${KCI_COMPOSE_PROJECT:-kcirv}"
  local serve_port="${KCI_SERVE_PORT:-8999}"
  local cb_port="${KCI_CB_PORT:-8003}"
  local sched_conf="/tmp/kcisched-$project"
  local pid_file="$ROOT/work/env/stack-$project.pids"
  local rc=0
  # These used to be machine-global pkill patterns that killed another deployment's
  # scheduler, callback and artifact server (the compose teardown below was already
  # project-scoped, #18).
  if [ -f "$pid_file" ]; then
    stop_recorded_services "$pid_file"
  else
    # No record (started before pids were recorded, or by another checkout): say
    # so, show what pattern matching is about to hit, then do it - a stop that
    # quietly stops nothing would be worse.
    echo "  !! no service ownership record at $pid_file: this deployment cannot prove"
    echo "     which processes are its own, so it falls back to pattern matching,"
    echo "     which can also match ANOTHER deployment's services:"
    pgrep -af "scheduler\.py.*--yaml-config $sched_conf/" 2>/dev/null | sed 's/^/       /'
    pgrep -af "uvicorn lava_callback.*--port $cb_port" 2>/dev/null | sed 's/^/       /'
    pgrep -af "http\.server $serve_port" 2>/dev/null | sed 's/^/       /'
    pkill -f "scheduler.py.*--yaml-config $sched_conf/" 2>/dev/null && echo "  scheduler stopped"
    pkill -f "uvicorn lava_callback.*--port $cb_port" 2>/dev/null && echo "  callback stopped"
    pkill -f "http.server $serve_port" 2>/dev/null && echo "  artifact server stopped"
  fi
  # API stack (api/db/redis/storage/ssh) runs under docker compose; data stays
  # in volumes, a later stack brings it back as-is.
  if [ ! -d "$ROOT/kernelci-api" ]; then
    echo "  (no kernelci-api checkout: no compose project to stop)"
  else
    local out
    if out="$(cd "$ROOT/kernelci-api" && docker compose -p "$project" -f docker-compose.yaml down 2>&1)"; then
      echo "API stack stopped (project $project)"
    else
      # The branch had no else: a failed compose down printed nothing and the
      # reader believed the stack was down while its containers kept running (#14).
      echo "X 'docker compose -p $project down' FAILED - containers of project $project may still be up:"
      printf '%s\n' "$out" | sed 's/^/    /'
      echo "    inspect with: docker compose -p $project -f $ROOT/kernelci-api/docker-compose.yaml ps"
      rc=1
    fi
  fi
  return "$rc"
}

case "${1:-help}" in
  setup)     cmd_setup ;;
  provision) cmd_provision ;;
  fetch)     shift; cmd_fetch "$@" ;;
  stack)     shift; cmd_stack "$@" ;;
  worker)    shift; cmd_worker "$@" ;;
  report)    cmd_report ;;
  results)   shift; cmd_results "$@" ;;
  build)     shift; cmd_local_jobs "$@" ;;
  jobs|todo|summary) cmd_local_jobs "$@" ;;
  run)       cmd_local_jobs "$@" ;;
  dashboard) shift; cmd_dashboard "$@" ;;
  prune)     shift; cmd_prune "$@" ;;
  verify)    cmd_verify ;;
  drift)     cmd_drift ;;
  trend)     cmd_trend ;;
  stop)      cmd_stop ;;
  help|*)    cmd_help ;;
esac
