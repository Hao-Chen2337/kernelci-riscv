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
# Where the stack's storage service publishes build artifacts.  config_drift
# falls back to it for a kbuild node that carries no _config artifact, so it is
# derived from the same KCI_STORAGE_PORT run-local-stack.sh moves the stack
# with - a deployment on 18002 used to be read from 8002.
STORAGE_URL="${KCI_STORAGE_URL:-http://127.0.0.1:${KCI_STORAGE_PORT:-8002}}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

# Proxy handling lives in scripts/net-preflight.sh.  It probes the network with
# the configuration exactly as the user set it and only bypasses a proxy when
# asked (KCI_BYPASS_PROXY=1) or when the proxy is demonstrably broken - it never
# silently unsets a working proxy configuration the way the old no_proxy_setup()
# did (that function hardcoded one machine's dead proxy into the repository).
# An explicit KCI_PROBE_URL is captured BEFORE sourcing: net-preflight.sh
# defaults it to files.kernelci.org, and the per-endpoint preflight below must
# both honour a user-supplied probe and name the URL it really probed.
KCI_PROBE_URL_OVERRIDE="${KCI_PROBE_URL:-}"
# shellcheck source=scripts/net-preflight.sh
. "$ROOT/scripts/net-preflight.sh"

# Probe the endpoint(s) the NEXT command actually talks to, one line each, and
# name the URL that was probed.  The preflight probes a single endpoint while
# its message used to read "kernelci API" (it probed files.kernelci.org): an OK
# verdict then looked like a general network verdict and the next command could
# still time out through the same proxy - measured, api.kernelci.org answered
# 000/exit 28 while files.kernelci.org answered 200 (docs/RUN-MODES-AND-BUGS.md
# #17).  So: probe per endpoint, say which one, and keep the verdict as narrow
# as the check.  Returns 1 when at least one endpoint failed.
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
  # The patch has to be applied where tuxlava IS, not in this interpreter's
  # user site-packages: a virtualenv or a system-wide install put the two in
  # different trees, and the printed command then either patched nothing or
  # reported "Reversed (or previously applied) patch detected" (N8).
  if [ -n "$TUXLAVA_DIR" ]; then
    TUXLAVA_SITE="$(dirname "$TUXLAVA_DIR")"
  else
    TUXLAVA_SITE="$(python3 -c 'import site;print(site.getusersitepackages())' 2>/dev/null \
      || echo "$HOME/.local/lib/python$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)/site-packages")"
  fi
  if [ -z "$TUXLAVA_DIR" ]; then
    # tuxlava missing entirely is a different problem with a different fix,
    # and the banner below would have blamed the patch for it.
    echo "  !! tuxlava is not importable: run the jobs' guest setup needs it (pip install tuxrun pulls it in)"
  elif grep -q "KselftestRiscv\|kselftest-riscv" "$TUXLAVA_DIR/tests/kselftest.py" 2>/dev/null; then
    ok "tuxlava patch applied"
  else
    # Reported at the END of setup instead of where it is detected: this is a
    # hard prerequisite for the riscv kselftest jobs (tuxrun builds its --tests
    # choices from tuxlava, so without it the job dies with exit 2 and the node
    # is filed as an infrastructure error), and as one `!!` line in the middle
    # of ~145 lines of setup output nobody noticed it until the worker failed
    # ~20 minutes later.  Still non-fatal: a deployment that only runs
    # `baseline` does not need it.
    TUXLAVA_PATCH_MISSING="$TUXLAVA_SITE"
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
  if [ -n "${TUXLAVA_PATCH_MISSING:-}" ]; then
    # Last thing on screen, deliberately: this is the prerequisite whose
    # absence surfaces much later as an unexplained "Infrastructure" job error.
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
  # Provisioning picks the newest passing kbuild from the production API and
  # then downloads that build's artifacts: two different hosts, two probes.
  kci_preflight "provisioning" \
    "https://api.kernelci.org/latest/" "https://files.kernelci.org/" \
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
  # Every argument passes through: this used to keep only "$2", so `--kvm-full`
  # or `--kvm-tests ...` were dropped without a word.
  for a in "$@"; do
    [ -n "$a" ] && extra+=("$a")
  done
  # The worker polls THIS deployment's API (KCI_API_URL) and then downloads
  # the artifacts of every job it takes, which are production URLs
  # (files.kernelci.org) - both are probed and named separately.
  if ! kci_preflight "worker" "$API_URL/latest/" "https://files.kernelci.org/"; then
    echo "    !! continuing anyway: the worker retries and reports infra errors honestly,"
    echo "       but a run whose endpoints are marked X above cannot do useful work."
  fi
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
  # The kvm entry is the shared kselftest-kvm-pull-labs job definition that
  # kernelci-pipeline#1600 added for sasha-lab and #1599 reuses; the node name
  # is the job name, so it is not riscv-specific any more.
  for name in baseline-riscv-pull-labs kselftest-riscv-pull-labs kselftest-kvm-pull-labs; do
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
# The full 24-character id is printed: the previous [:16] truncation made two
# different nodes of the same name print identically in one report.
items = sorted(items, key=lambda n: n.get("created") or "", reverse=True)
if not items:
    print("  (no nodes)")
for n in items[:3]:
    data = n.get("data") or {}
    revision = data.get("kernel_revision") or {}
    # The error type is printed because docs/RUNBOOK.md tells the reader to
    # look at it FIRST: "Infrastructure" means the run produced no usable data
    # (a boot or infra failure), not that the kernel regressed - without the
    # column the two were only distinguishable by querying the API by hand.
    # Both spellings are read on purpose.  The runbook names the field
    # data.error_type, while kernelci-core lava runtime writes the job error
    # type as data.error_code (runtime/lava.py: "error_code" = job_meta
    # error_type) and docs/UPSTREAM-BUILD-AND-DISPATCH.md documents error_code.
    # Printing only one of the two shows "-" for real infrastructure failures.
    # No apostrophes in this block: it is one single-quoted shell string.
    error_type = data.get("error_type") or data.get("error_code") or "-"
    print("  {:24s} {:12s} {:14s} {:14s} {} ({})".format(
        n.get("id") or "?", n.get("state") or "-", n.get("result") or "-",
        error_type,
        (revision.get("describe") or "?")[:30], (n.get("created") or "")[:10]))
if len(items) > 3:
    print("  (%d node(s) matched, newest 3 shown)" % len(items))' \
      || true
    # `|| true`: curl fails when the API is down, and under `set -o pipefail`
    # that failure became the report's exit status (7) even though the message
    # above is exactly what the reader needs (adversarial review, N6).
  done
}

cmd_dashboard() {
  # A read-only page over the local job table (build index + ledger + local API).
  # Not the upstream kernelci-frontend: that one is a 2024 Flask app with its
  # config in another repo and its own MongoDB connection, so it shows its data,
  # not this lab's table. This serves what ./run.sh summary prints.
  python3 "$ROOT/scripts/dashboard.py" "$@"
}

cmd_local_jobs() {
  # The local job table (build index + ledger view). Deliberately separate from
  # 'worker': the worker is the resident claimer, this is the table you look at.
  # Everything here works without the local stack and without the upstream
  # config being merged.
  python3 "$ROOT/scripts/local-jobs.py" "$@"
}

cmd_results() {
  # The durable record this machine produced, read back: work/results/<build>/
  # <test>.json, written by ./run.sh fetch and - since the worker was given the
  # same ledger - by the resident worker too.  Deliberately NOT the API report
  # above: this answers "what did this repo actually run and how did it end"
  # from local files, so it still works with the stack stopped, and it is the
  # reader the ledger never had (it was write-only until now).
  python3 "$ROOT/scripts/results.py" "$@"
}

cmd_prune() {
  # work/downloads/<node_id>/ is one directory per fetched build (~45 MB each:
  # Image + modules + kselftest + .config) and nothing ever removed them - a
  # daily fetch loop is ~16 GB/year, before the bounded rootfs bake cache.
  # This is the retention policy the entry point owns: explicit, bounded, and
  # it never removes the build this deployment is using.
  #   * the newest --keep builds (default 5) are kept,
  #   * a build whose commit is the one work/env/build.env records (the build
  #     ./run.sh stack --seed and work/serve/Image serve) is kept,
  #   * --dry-run prints the same list without deleting anything.
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

# The build this deployment serves, as recorded by ./run.sh provision: its
# commit (what every node names) and, when the directory happens to be the
# artifact directory itself, its build id.
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
  # Every gate must be able to fail this command.  Piping a check into
  # `tail -1` (or trailing it with `|| true`) throws its exit status away, so
  # this "full gate" used to print a traceback and still exit 0 - it reported
  # success precisely when it should have reported a crash.
  #
  # The tools the gates themselves need are checked first: `ruff: command not
  # found` from the last gate, after three others have already run, told a new
  # user nothing about what to install (ruff was in no requirements file).
  local missing=()
  command -v ruff >/dev/null 2>&1 || missing+=("ruff")
  python3 -c 'import yaml' >/dev/null 2>&1 || missing+=("PyYAML")
  [ "${#missing[@]}" -eq 0 ] || die \
    "verify needs: ${missing[*]} - install with: python3 -m pip install -r requirements.txt"
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml failed"
  python3 "$ROOT/scripts/tools/verify-lava-body.py" || die "verify-lava-body failed"
  python3 "$ROOT/scripts/tools/verify-worker-guards.py" || die "verify-worker-guards failed"
  # Compile the entry points and the library: the guards import the library only,
  # so before this gate a syntax error in riscv_pull_worker.py (or in a kcilib
  # module nobody exercises yet) reached the user as a runtime traceback.
  python3 -m compileall -q "$ROOT/scripts" >/dev/null || die "compileall failed"
  # ruff checks our own scripts/ (upstream clones and work/ are gitignored)
  (cd "$ROOT" && ruff check .) || die "ruff failed"
  ok "verify: all gates passed"
}

cmd_drift() {
  # The probe endpoint and the API used below are the same URL again: the old
  # "kernelci API" verdict was produced by probing files.kernelci.org.
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

# Stop the host services of ONE deployment from the records
# scripts/run-local-stack.sh wrote when it started them (role|pid|start|pattern).
# The pid's start time is re-read before killing: a record from an old run whose
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
  # Same overridable identity as the stack: one machine can host more than one
  # isolated deployment (its own compose project, volumes and ports), and
  # stopping one must not stop the other.
  local project="${KCI_COMPOSE_PROJECT:-kcirv}"
  local serve_port="${KCI_SERVE_PORT:-8999}"
  local cb_port="${KCI_CB_PORT:-8003}"
  local sched_conf="/tmp/kcisched-$project"
  local pid_file="$ROOT/work/env/stack-$project.pids"
  local rc=0
  # These used to be machine-global pkill patterns, so stopping one deployment
  # killed another deployment's scheduler, callback and artifact server - while
  # the compose teardown right below was already project-scoped (#18).
  if [ -f "$pid_file" ]; then
    stop_recorded_services "$pid_file"
  else
    # No record (the stack was started before pids were recorded, or by another
    # checkout).  Say so, show exactly what pattern matching is about to hit,
    # and then do it - a stop that quietly stops nothing would be worse.
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
      # The branch had no else: a failed compose down printed nothing at all
      # and the reader believed the stack was down while its containers kept
      # running (#14).
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
