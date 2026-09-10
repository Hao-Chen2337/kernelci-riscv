#!/usr/bin/env bash
# Local KernelCI full stack, one command: API stack + artifact server + real
# callback + the official scheduler (reading our YAMLs).
# Usage:
#   run-local-stack.sh            # start services only, print status + next step
#   run-local-stack.sh --seed     # start services + POST a kbuild seed node (triggers dispatch)
#   run-local-stack.sh --worker   # start services + seed + run the worker in the foreground
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT/kernelci-api"
PIPE_DIR="$ROOT/kernelci-pipeline"
ENV_FILE="$PIPE_DIR/.env"
SERVE_DIR="$ROOT/work/serve"
SERVE_PORT=8999
CB_PORT=8003
# Runtime settings are rendered from the tracked template
# (config/local-callback.toml, which uses @KCI_ROOT@) into this gitignored
# file: kernelci's toml.load() does not expand environment variables, so the
# template cannot refer to the checkout next to it, and hardcoding one machine's
# home made every clone read another deployment's config and SSH key.
SETTINGS="$ROOT/work/local-callback.toml"
TUXRUN_BIN="${TUXRUN_BIN:-$(command -v tuxrun || echo "$HOME/.local/bin/tuxrun")}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

# shellcheck source=net-preflight.sh
. "$ROOT/scripts/net-preflight.sh"

[ -f "$ENV_FILE" ] || die "$ENV_FILE missing; run ./run.sh setup first"
TOKEN="$(grep '^KCI_API_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
# A non-empty check is not enough: setup's placeholder text
# ("fill in the local kernelci-api admin JWT ...") is non-empty, so it used to
# pass, start the whole stack, and then 401 on every single API call.  Demand
# something that at least looks like the JWT the API hands out.
case "$TOKEN" in
  ""|fill\ in*|*" "*)
    die "KCI_API_TOKEN in $ENV_FILE is not a real token (found: '${TOKEN:0:48}'); run ./run.sh setup (or scripts/local-instance-init.sh) to generate one" ;;
  eyJ*) ;;
  *)
    echo "  !! KCI_API_TOKEN does not look like a local API JWT (no 'eyJ' prefix); continuing" ;;
esac

# Render the settings template for THIS checkout before anything reads it.
python3 "$ROOT/scripts/render-local-config.py" --output "$SETTINGS" >/dev/null \
  || die "could not render $SETTINGS from config/local-callback.toml"
ok "settings rendered ($SETTINGS)"

# 1) KernelCI API stack
if curl -s -m 3 -o /dev/null http://127.0.0.1:8001/latest/; then
  ok "API stack already up (127.0.0.1:8001)"
else
  echo "-> starting: docker compose -p kcirv up -d api db redis storage ssh"
  if ! (cd "$API_DIR" && docker compose -p kcirv up -d api db redis storage ssh >/dev/null); then
    # After a machine/docker restart, stale Exited containers cause compose
    # name conflicts; data lives in volumes, so removing them is safe.
    echo "  compose conflict; removing stale stopped containers and retrying"
    for c in kernelci-api kernelci-api-db kernelci-api-redis kernelci-api-storage kernelci-api-ssh; do
      docker rm -f "$c" >/dev/null 2>&1 || true
    done
    (cd "$API_DIR" && docker compose -p kcirv up -d api db redis storage ssh >/dev/null) || die "compose failed"
  fi
  for i in $(seq 1 40); do
    curl -s -m 2 -o /dev/null http://127.0.0.1:8001/latest/ && break
    sleep 2
  done
  curl -s -m 3 -o /dev/null http://127.0.0.1:8001/latest/ || die "API not ready"
  ok "API stack started"
fi

# 2) artifact server (8999)
if curl -s -m 3 -o /dev/null "http://127.0.0.1:$SERVE_PORT/Image"; then
  ok "artifact server already up (:$SERVE_PORT)"
else
  (cd "$SERVE_DIR" && setsid nohup python3 -m http.server $SERVE_PORT --bind 0.0.0.0 >/tmp/fs$SERVE_PORT.log 2>&1 < /dev/null &)
  sleep 2
  curl -s -m 3 -o /dev/null "http://127.0.0.1:$SERVE_PORT/Image" && ok "artifact server started (:$SERVE_PORT)" || die "artifact server failed"
fi

# 3) real lava_callback (8003, validates token)
if curl -s -m 3 -o /dev/null "http://127.0.0.1:$CB_PORT/"; then
  ok "lava_callback already up (:$CB_PORT)"
else
  (cd "$PIPE_DIR/src" && KCI_SETTINGS="$SETTINGS" KCI_API_TOKEN="$TOKEN" PYTHONPATH="$ROOT/kernelci-core" setsid nohup python3 -m uvicorn lava_callback:app --port $CB_PORT --host 0.0.0.0 >/tmp/cb$CB_PORT.log 2>&1 < /dev/null &)
  sleep 4
  curl -s -m 3 -o /dev/null "http://127.0.0.1:$CB_PORT/" && ok "lava_callback started (:$CB_PORT)" || die "callback failed (see /tmp/cb$CB_PORT.log)"
fi

# 4) official scheduler (reads our 4 YAMLs, renders jobdefs in real time)
if pgrep -f "scheduler.py.*pull-labs-riscv" >/dev/null; then
  ok "scheduler already running (pull-labs-riscv)"
else
  KCFG=/tmp/kcisched
  mkdir -p "$KCFG/config/runtime"
  ln -sfn "$PIPE_DIR/config/logger.conf" "$KCFG/config/logger.conf" 2>/dev/null
  ln -sfn "$ROOT/kernelci-core/config/runtime/base" "$KCFG/config/runtime/base" 2>/dev/null
  for f in "$PIPE_DIR"/config/runtime/*.jinja2; do ln -sfn "$f" "$KCFG/config/runtime/" 2>/dev/null; done
  for f in "$PIPE_DIR"/config/*.yaml; do
    [ "$(basename "$f")" = "pipeline.yaml" ] && continue
    ln -sfn "$f" "$KCFG/config/" 2>/dev/null
  done
  PIPE_CONF="$PIPE_DIR/config/pipeline.yaml" CB_CONF="$ROOT/config/cb-config/pipeline.yaml" \
    python3 - "$KCFG/config/pipeline.yaml" <<'PYEOF'
import os, sys, yaml
def merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            merge(a[k], v)
        else:
            a[k] = v
    return a
a = yaml.safe_load(open(os.environ["PIPE_CONF"]))
b = yaml.safe_load(open(os.environ["CB_CONF"]))
open(sys.argv[1], "w").write(yaml.safe_dump(merge(a, b), sort_keys=False))
PYEOF
  (cd "$KCFG" && KCI_SETTINGS="$SETTINGS" KCI_API_TOKEN="$TOKEN" KCI_INSTANCE_CALLBACK="http://127.0.0.1:$CB_PORT" PYTHONPATH="$ROOT/kernelci-core" setsid nohup python3 "$PIPE_DIR/src/scheduler.py" --yaml-config "$KCFG/config" --settings "$SETTINGS" loop --runtimes pull-labs-riscv --name local-full-stack --output /tmp/sched-output >/tmp/sched-local.log 2>&1 < /dev/null &)
  sleep 10
  pgrep -f "scheduler.py.*pull-labs-riscv" >/dev/null && ok "scheduler started (pull-labs-riscv)" || die "scheduler failed (see /tmp/sched-local.log)"
fi

echo
echo '--- local full stack ---'
echo '  API:        http://127.0.0.1:8001'
echo "  artifacts:  http://127.0.0.1:$SERVE_PORT"
echo "  callback:   http://127.0.0.1:$CB_PORT (real lava_callback)"
echo '  scheduler:  pull-labs-riscv (official code, our YAMLs)'
echo

if [ "${1:-}" = "--seed" ] || [ "${1:-}" = "--worker" ]; then
  echo "-> seeding kbuild node to trigger scheduling..."
  # CONSISTENCY RULE: work/serve/Image, the modules baked into
  # work/env/rootfs-kvm.ext4 and the URLs in this seed must all be the SAME
  # kbuild - the worker bakes modules.tar.xz into /lib/modules and modprobe
  # matches them by kernel release, so a mismatch makes every kvm test skip
  # ("Cannot open /dev/kvm").
  #
  # ./run.sh provision records the build it provisioned in work/env/build.env;
  # seeding from it is what keeps the three places from drifting apart.  The
  # SEED_* defaults below are only a fallback for a deployment that never ran
  # provision (their pinned hash is old: storage prunes builds, which is why
  # provision discovers the newest one instead of pinning anything).
  if [ -f "$ROOT/work/env/build.env" ]; then
    # shellcheck disable=SC1091
    . "$ROOT/work/env/build.env"
    if [ -n "${KCI_BUILD_DIR:-}" ]; then
      echo "    seeding from the provisioned build: $KCI_BUILD_DIR"
      SEED_MODULES_URL="${SEED_MODULES_URL:-$KCI_BUILD_DIR/modules.tar.xz}"
      SEED_KSELFTEST_URL="${SEED_KSELFTEST_URL:-$KCI_BUILD_DIR/kselftest.tar.xz}"
      SEED_CONFIG_URL="${SEED_CONFIG_URL:-$KCI_BUILD_DIR/.config}"
    fi
  fi
  # The whole seed is env-overridable: when production storage prunes the
  # original build, point SEED_*_URL at a newer build and replay.
  SEED_TREE="${SEED_TREE:-riscv}"
  SEED_BRANCH="${SEED_BRANCH:-master}"
  SEED_COMMIT="${SEED_COMMIT:-f217004a40c49e787372e798785aecb983828d35}"
  SEED_DESCRIBE="${SEED_DESCRIBE:-v7.3-rc1-516-gf217004a40c49}"
  SEED_MODULES_URL="${SEED_MODULES_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/modules.tar.xz}"
  SEED_KSELFTEST_URL="${SEED_KSELFTEST_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/kselftest.tar.xz}"
  SEED_CONFIG_URL="${SEED_CONFIG_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/.config}"
  # Preflight: the local Image is a hard requirement; broken production URLs
  # only warn (that job will report Infrastructure honestly; override and retry).
  [ -f "$SERVE_DIR/Image" ] || die "seed needs $SERVE_DIR/Image (run ./run.sh fetch or drop one there)"
  # Probe the seed artifacts with the user's proxy configuration as-is.
  # (This used to unset http_proxy/https_proxy unconditionally, with a comment
  # about "the dead 7890 proxy" - one machine's temporary state.  Someone whose
  # proxy works would have it silently removed; KCI_BYPASS_PROXY=1 is the
  # explicit opt-in for a broken one.)
  for u in "$SEED_MODULES_URL" "$SEED_KSELFTEST_URL" "$SEED_CONFIG_URL"; do
    # HEAD, not a Range probe: files.kernelci.org ignores Range and streams
    # the whole file, so a range check on a big artifact always times out.
    kci_curl -s -m 15 -o /dev/null -I "$u" \
      || echo "  !! seed artifact unreachable: $u (override via SEED_*_URL; KCI_BYPASS_PROXY=1 ignores a dead proxy)"
  done
  PARENT="$(curl -s -m 15 -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8001/latest/nodes?kind=checkout&data.kernel_revision.tree=riscv&limit=1" | python3 -c 'import json,sys;print(json.load(sys.stdin)["items"][0]["id"])')"
  # -m 30: the first POST after an API restart can stall mid-response; curl
  # must not wait forever. (The node may already exist server-side; re-running
  # only adds one more seed node, harmless in the dev DB.)
  if curl -s -m 30 -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" --data @- http://127.0.0.1:8001/latest/node <<EOF
{
  "name": "kbuild-gcc-14-riscv", "kind": "kbuild", "state": "available",
  "parent": "$PARENT",
  "group": "kbuild-gcc-14-riscv", "path": ["checkout", "kbuild-gcc-14-riscv"],
  "data": {"arch": "riscv", "defconfig": "defconfig", "compiler": "gcc-14",
           "kernel_revision": {"tree": "$SEED_TREE",
             "url": "https://git.kernel.org/pub/scm/linux/kernel/git/riscv/linux.git",
             "branch": "$SEED_BRANCH",
             "commit": "$SEED_COMMIT",
             "describe": "$SEED_DESCRIBE",
             "version": {"version": 7, "patchlevel": 3},
             "commit_tags": ["v7.3-rc1"], "tip_of_branch": true}},
  "artifacts": {
    "kernel": "http://172.17.0.1:$SERVE_PORT/Image",
    "modules": "$SEED_MODULES_URL",
    "kselftest_tar_xz": "$SEED_KSELFTEST_URL",
    "_config": "$SEED_CONFIG_URL"
  }
}
EOF
  then
    echo "    seeded; scheduler will auto-create the 3 job nodes"
  else
    echo "  !! seed POST got no response (the node may still exist - check /latest/nodes; re-running is harmless)"
  fi
  # Wait for the scheduler to actually render the job nodes.  Seeding and then
  # immediately running `./run.sh worker --once` used to hit an empty queue:
  # the worker printed "batch processed, exiting" having run nothing at all,
  # which looks like success and is deeply confusing.
  echo "-> waiting for the scheduler to create the job nodes..."
  deadline=$((SECONDS + ${SEED_WAIT_S:-90}))
  while [ "$SECONDS" -lt "$deadline" ]; do
    pending="$(kci_curl -s -m 5 "http://127.0.0.1:8001/latest/nodes?kind=job&state=available&limit=50" \
      | python3 -c 'import json, sys
try:
    items = json.load(sys.stdin).get("items", [])
except Exception:
    items = []
print(sum(1 for n in items if (n.get("name") or "").endswith("pull-labs")))' 2>/dev/null || true)"
    if [ "${pending:-0}" -ge 1 ] 2>/dev/null; then
      echo "    $pending job node(s) available - the worker can start now"
      break
    fi
    sleep 3
  done
  [ "${pending:-0}" -ge 1 ] 2>/dev/null \
    || echo "  !! no job node appeared within ${SEED_WAIT_S:-90}s; check /tmp/sched-local.log"
fi

if [ "${1:-}" = "--worker" ]; then
  echo '-> worker taking jobs (Ctrl-C to stop):'
  PYTHONUNBUFFERED=1 PATH=/usr/local/sbin:/usr/sbin:$PATH PULL_LABS_CALLBACK_TOKEN=labtoken-callback \
    kci_run python3 "$ROOT/scripts/riscv_pull_worker.py" \
    --api-url http://127.0.0.1:8001 --tuxrun-bin "$TUXRUN_BIN" \
    --container-runtime docker --output-dir /tmp/official-loop-out \
    --state-file /tmp/official-loop-state.json --poll-period 5 --max-timeout 1200
else
  echo 'next step (manual):'
  echo "  ./run.sh worker --once            # same state file, one batch, then exit"
  echo "  # or directly: ./run.sh worker     # keep polling"
fi
