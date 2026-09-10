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
TOKEN="$(grep '^KCI_API_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
SERVE_DIR="$ROOT/work/serve"
SERVE_PORT=8999
CB_PORT=8003

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

[ -n "$TOKEN" ] || die "KCI_API_TOKEN not in $ENV_FILE"

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
  (cd "$PIPE_DIR/src" && KCI_SETTINGS="$ROOT/config/local-callback.toml" KCI_API_TOKEN="$TOKEN" PYTHONPATH="$ROOT/kernelci-core" setsid nohup python3 -m uvicorn lava_callback:app --port $CB_PORT --host 0.0.0.0 >/tmp/cb$CB_PORT.log 2>&1 < /dev/null &)
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
  (cd "$KCFG" && KCI_SETTINGS="$ROOT/config/local-callback.toml" KCI_API_TOKEN="$TOKEN" KCI_INSTANCE_CALLBACK="http://127.0.0.1:$CB_PORT" PYTHONPATH="$ROOT/kernelci-core" setsid nohup python3 "$PIPE_DIR/src/scheduler.py" --yaml-config "$KCFG/config" --settings "$ROOT/config/local-callback.toml" loop --runtimes pull-labs-riscv --name local-full-stack --output /tmp/sched-output >/tmp/sched-local.log 2>&1 < /dev/null &)
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
  # The whole seed is env-overridable: when production storage prunes the
  # original build, point SEED_*_URL at a newer build and replay.
  # CONSISTENCY RULE: work/serve/Image must be the SAME build as
  # SEED_MODULES_URL - the worker bakes those modules into the rootfs and
  # modprobe matches them by kernel release; a mismatch makes every kvm
  # test skip ("Cannot open /dev/kvm").
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
  # Drop the dead 7890 proxy so the preflight reflects real reachability.
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null || true
  for u in "$SEED_MODULES_URL" "$SEED_KSELFTEST_URL" "$SEED_CONFIG_URL"; do
    # HEAD, not a Range probe: files.kernelci.org ignores Range and streams
    # the whole file, so a range check on a big artifact always times out.
    curl -s -m 15 -o /dev/null -I "$u" || echo "  !! seed artifact unreachable: $u (override via SEED_*_URL)"
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
fi

if [ "${1:-}" = "--worker" ]; then
  echo '-> worker taking jobs (Ctrl-C to stop):'
  PATH=/usr/local/sbin:/usr/sbin:$PATH PULL_LABS_CALLBACK_TOKEN=labtoken-callback python3 "$ROOT/scripts/riscv_pull_worker.py" --api-url http://127.0.0.1:8001 --tuxrun-bin /home/hao/.local/bin/tuxrun --container-runtime docker --output-dir /tmp/official-loop-out --state-file /tmp/official-loop-state.json --poll-period 5 --max-timeout 1200
else
  echo 'next step (manual):'
  echo "  PULL_LABS_CALLBACK_TOKEN=labtoken-callback python3 $ROOT/scripts/riscv_pull_worker.py --api-url http://127.0.0.1:8001 --tuxrun-bin /home/hao/.local/bin/tuxrun --container-runtime docker --poll-period 5"
fi
