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
# Everything that identifies THIS deployment - the compose project (which fixes
# the data volumes) and the host ports - is overridable, so a second deployment
# can be exercised on the same machine against its own empty database instead of
# the accumulated one:
#   KCI_COMPOSE_PROJECT=kcirv-clean KCI_API_PORT=18001 KCI_CB_PORT=18003 \
#   KCI_SERVE_PORT=18999 KCI_STORAGE_PORT=18002 KCI_SSH_PORT=18022 ./run.sh stack
# They cannot run *simultaneously*: kernelci-api's compose file hardcodes
# container_name (kernelci-api, kernelci-api-db, ...), so the first stack has to
# be stopped - but it is the volume, and therefore the database, that decides
# whether this is a fresh deployment or the old one.
PROJECT="${KCI_COMPOSE_PROJECT:-kcirv}"
API_PORT="${KCI_API_PORT:-8001}"
STORAGE_PORT="${KCI_STORAGE_PORT:-8002}"
SSH_PORT="${KCI_SSH_PORT:-8022}"
MONGO_PORT="${KCI_MONGO_PORT:-8017}"
CB_PORT="${KCI_CB_PORT:-8003}"
SERVE_PORT="${KCI_SERVE_PORT:-8999}"
API_URL="http://127.0.0.1:$API_PORT"
# The compose file already reads these (${API_HOST_PORT:-8001} ...), so no
# patching is needed to move a stack off the default ports.
export API_HOST_PORT="$API_PORT" STORAGE_HOST_PORT="$STORAGE_PORT"
export SSH_HOST_PORT="$SSH_PORT" MONGO_HOST_PORT="$MONGO_PORT"
# Runtime settings are rendered from the tracked templates (which use @NAME@
# tokens) into gitignored files under work/: kernelci's toml.load() does not
# expand environment variables, so a tracked file cannot refer to the checkout
# next to it or to this deployment's ports, and hardcoding one machine's values
# made every clone read another deployment's paths and endpoints.
SETTINGS="$ROOT/work/local-callback.toml"
CB_CONFIG="$ROOT/work/cb-config/pipeline.yaml"
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

# Render the settings templates for THIS deployment before anything reads them.
python3 "$ROOT/scripts/render-local-config.py" \
  --template "$ROOT/config/local-callback.toml" --output "$SETTINGS" >/dev/null \
  || die "could not render $SETTINGS from config/local-callback.toml"
python3 "$ROOT/scripts/render-local-config.py" \
  --template "$ROOT/config/cb-config/pipeline.yaml" --output "$CB_CONFIG" \
  --var API_PORT="$API_PORT" --var STORAGE_PORT="$STORAGE_PORT" \
  --var SSH_PORT="$SSH_PORT" >/dev/null \
  || die "could not render $CB_CONFIG from config/cb-config/pipeline.yaml"
ok "settings rendered ($SETTINGS, $CB_CONFIG; project=$PROJECT api=$API_PORT)"

# The ssh container stores job definitions and result logs through bind mounts
# into these two directories, as its own user `kernelci` - uid 1000, see
# kernelci-api/docker/ssh/Dockerfile.  A host directory owned by anybody else
# makes that upload fail, and it fails SILENTLY: kernelci-core's
# StorageSSH._upload runs `mkdir -p` fire-and-forget, so the scheduler sees only
# "submit error: Failed to store job definition", every job node is parked as
# incomplete and `stack --seed` reports "no job node appeared within 90s" - with
# nothing pointing at permissions.  Checked here so nobody has to find that out
# from a hang; root can simply fix it, another uid is told exactly what to run.
check_uid1000_dir() {
  local dir="$1" what="$2" owner
  mkdir -p "$dir" 2>/dev/null || true
  if [ ! -d "$dir" ]; then
    echo "  !! $dir does not exist and could not be created ($what)"
    return 0
  fi
  owner="$(stat -c %u "$dir" 2>/dev/null || echo '?')"
  if [ "$(id -u)" = "0" ]; then
    chown -R 1000:1000 "$dir" 2>/dev/null && \
      echo "  $dir -> uid 1000 ($what)"
    return 0
  fi
  if [ "$owner" = "1000" ]; then
    return 0
  fi
  echo "  !! $dir is owned by uid $owner, but the ssh container writes it as uid 1000 ($what)"
  echo "     Job definitions would not be stored and every job would stay incomplete"
  echo "     with 'submit error'.  Fix with: sudo chown -R 1000:1000 $dir"
}
check_uid1000_dir "$API_DIR/docker/storage/data" "job definitions and result logs"
check_uid1000_dir "$API_DIR/docker/ssh/user-data" "the scheduler's upload key"

# 1) KernelCI API stack
#
# `docker compose up -d` runs even when the API already answers, because only
# compose knows whether the running containers still match the requested port
# mappings: skipping it left containers on the default ports while the rendered
# cb-config pointed at this deployment's ports, and the scheduler then failed to
# store any job definition ("unable to connect to port 18022").  With nothing to
# change this is a no-op that costs about a second.
if curl -s -m 3 -o /dev/null "$API_URL/latest/"; then
  ok "API stack already up ($API_URL)"
  (cd "$API_DIR" && docker compose -p "$PROJECT" up -d api db redis storage ssh >/dev/null) \
    || echo "  !! compose could not reconcile the running containers; ports may be stale"
else
  echo "-> starting: docker compose -p $PROJECT up -d api db redis storage ssh"
  if ! (cd "$API_DIR" && docker compose -p "$PROJECT" up -d api db redis storage ssh >/dev/null); then
    # After a machine/docker restart, stale Exited containers cause compose
    # name conflicts; data lives in volumes, so removing them is safe.
    echo "  compose conflict; removing stale stopped containers and retrying"
    for c in kernelci-api kernelci-api-db kernelci-api-redis kernelci-api-storage kernelci-api-ssh; do
      docker rm -f "$c" >/dev/null 2>&1 || true
    done
    (cd "$API_DIR" && docker compose -p "$PROJECT" up -d api db redis storage ssh >/dev/null) || die "compose failed"
  fi
fi
for i in $(seq 1 40); do
  curl -s -m 2 -o /dev/null "$API_URL/latest/" && break
  sleep 2
done
curl -s -m 3 -o /dev/null "$API_URL/latest/" || die "API not ready at $API_URL"
ok "API stack up"

# Which artifact is actually running - recorded, not inferred afterwards.
# kernelci-api/docker-compose.yaml pulls a *mutable* tag
# (${KERNELCI_API_IMAGE:-kernelci/staging-kernelci}:${KERNELCI_API_TAG:-api}), so
# the image this deployment tested can change under it overnight; without this
# line no report can name the artifact it verified.  Read it back from the
# running container rather than from the tag we asked for.
API_IMAGE_ID="$(docker inspect -f '{{.Image}}' kernelci-api 2>/dev/null || true)"
if [ -n "$API_IMAGE_ID" ]; then
  ok "API image: ${API_IMAGE_ID#sha256:} (${KERNELCI_API_IMAGE:-kernelci/staging-kernelci}:${KERNELCI_API_TAG:-api})"
  mkdir -p "$ROOT/work/env"
  {
    echo "# Written by ./run.sh stack - the artifact this deployment runs."
    echo "# kernelci-api's compose file pulls a mutable tag, so this is the only"
    echo "# durable record of what was tested; re-read on every stack start."
    echo "KCI_API_IMAGE_ID=$API_IMAGE_ID"
    echo "KCI_API_IMAGE_REF=${KERNELCI_API_IMAGE:-kernelci/staging-kernelci}:${KERNELCI_API_TAG:-api}"
    echo "KCI_STACK_STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "KCI_COMPOSE_PROJECT=$PROJECT"
  } > "$ROOT/work/env/images.env"
else
  # Say so instead of silently writing nothing: this record is the only way a
  # later report can name the artifact it verified, and a renamed container
  # (KCI_COMPOSE_PROJECT, an override) would otherwise vanish without a trace.
  echo "  !! could not read the running API image id (docker inspect kernelci-api failed);"
  echo "     work/env/images.env was NOT written, so this run's artifact is unrecorded"
fi

# `stop` + `stack` used to truncate the previous round's service logs, because
# every service logs to a fixed /tmp path - so after a restart the round that
# produced a result was no longer auditable.  Rotate one generation instead,
# and ONLY when the service is about to be started below: rotating here
# unconditionally moved the log file of an ALREADY RUNNING service to .prev,
# leaving the live round with no log path at all while the service kept writing
# to the moved inode (caught by an adversarial review, then observed live).
rotate_log() {
  [ -f "$1" ] && mv -f "$1" "$1.prev"
  return 0
}

# Note on the service launches below: each one redirects the SUBSHELL's own
# stdout/stderr as well as the service's.  Redirecting only the service left the
# subshell holding the caller's stdout, so `./run.sh stack | tee log` never saw
# EOF and appeared to hang long after the stack was up.
# 2) artifact server (8999)
if curl -s -m 3 -o /dev/null "http://127.0.0.1:$SERVE_PORT/Image"; then
  ok "artifact server already up (:$SERVE_PORT)"
else
  rotate_log "/tmp/fs$SERVE_PORT.log"
  (cd "$SERVE_DIR" && setsid nohup python3 -m http.server $SERVE_PORT --bind 0.0.0.0 >/tmp/fs$SERVE_PORT.log 2>&1 < /dev/null &) >/dev/null 2>&1
  sleep 2
  curl -s -m 3 -o /dev/null "http://127.0.0.1:$SERVE_PORT/Image" && ok "artifact server started (:$SERVE_PORT)" || die "artifact server failed"
fi

# 3) real lava_callback (validates the token)
if curl -s -m 3 -o /dev/null "http://127.0.0.1:$CB_PORT/"; then
  ok "lava_callback already up (:$CB_PORT)"
else
  # lava_callback runs on the HOST (not in a container) and imports the cloned
  # kernelci-core, so its imports have to be installed here.  Importing the
  # module is the honest check: listing four packages missed what the callback
  # actually needs transitively (kernelci-core wants elftools, and a machine
  # with only PyJWT/toml/uvicorn/fastapi still died here with a bare
  # "callback failed (see /tmp/cb8003.log)").
  #
  # KCI_SETTINGS must be set for the check to mean anything: lava_callback.py
  # reads it AT IMPORT TIME (toml.load), and it is otherwise only set inline on
  # the launch line - so an import check without it fails with
  # FileNotFoundError: 'config/kernelci.toml' on a perfectly healthy machine and
  # blames dependencies that are installed.  (Caught by adversarial review of
  # this very check, N11.)
  if ! CALLBACK_IMPORT_ERROR="$(cd "$PIPE_DIR/src" && KCI_SETTINGS="$SETTINGS" \
      PYTHONPATH="$ROOT/kernelci-core" python3 -c 'import lava_callback' 2>&1)"; then
    echo "$CALLBACK_IMPORT_ERROR" | tail -3 >&2
    die "the callback service cannot be imported (see the traceback above); install the host deps with: python3 -m pip install -r requirements.txt && python3 -m pip install -r kernelci-core/requirements.txt"
  fi
  rotate_log "/tmp/cb$CB_PORT.log"
  (cd "$PIPE_DIR/src" && KCI_SETTINGS="$SETTINGS" KCI_API_TOKEN="$TOKEN" PYTHONPATH="$ROOT/kernelci-core" setsid nohup python3 -m uvicorn lava_callback:app --port $CB_PORT --host 0.0.0.0 >/tmp/cb$CB_PORT.log 2>&1 < /dev/null &) >/dev/null 2>&1
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
  PIPE_CONF="$PIPE_DIR/config/pipeline.yaml" CB_CONF="$CB_CONFIG" \
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
  rotate_log "/tmp/sched-local.log"
  (cd "$KCFG" && KCI_SETTINGS="$SETTINGS" KCI_API_TOKEN="$TOKEN" KCI_INSTANCE_CALLBACK="http://127.0.0.1:$CB_PORT" PYTHONPATH="$ROOT/kernelci-core" setsid nohup python3 "$PIPE_DIR/src/scheduler.py" --yaml-config "$KCFG/config" --settings "$SETTINGS" loop --runtimes pull-labs-riscv --name local-full-stack --output /tmp/sched-output >/tmp/sched-local.log 2>&1 < /dev/null &) >/dev/null 2>&1
  sleep 10
  pgrep -f "scheduler.py.*pull-labs-riscv" >/dev/null && ok "scheduler started (pull-labs-riscv)" || die "scheduler failed (see /tmp/sched-local.log)"
fi

echo
echo '--- local full stack ---'
echo "  project:    $PROJECT (containers + data volumes)"
echo "  API:        $API_URL"
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
    # The revision of that build, so the nodes created below name the kernel
    # that actually boots.  These used to be hardcoded defaults, which meant a
    # deployment serving 7.3-rc2 created nodes labelled
    # v7.3-rc1-516-gf217004a40c49: the runs were real, the attribution was not.
    # An explicit SEED_* in the environment still wins over all of it.
    SEED_COMMIT="${SEED_COMMIT:-${KCI_BUILD_COMMIT:-}}"
    SEED_DESCRIBE="${SEED_DESCRIBE:-${KCI_BUILD_DESCRIBE:-}}"
    SEED_TREE="${SEED_TREE:-${KCI_BUILD_TREE:-}}"
    SEED_BRANCH="${SEED_BRANCH:-${KCI_BUILD_BRANCH:-}}"
    SEED_TREE_URL="${SEED_TREE_URL:-${KCI_BUILD_URL:-}}"
    SEED_VERSION="${SEED_VERSION:-${KCI_BUILD_VERSION:-}}"
    SEED_PATCHLEVEL="${SEED_PATCHLEVEL:-${KCI_BUILD_PATCHLEVEL:-}}"
    SEED_TAGS="${SEED_TAGS:-${KCI_BUILD_TAGS:-}}"
  fi
  # The whole seed is env-overridable: when production storage prunes the
  # original build, point SEED_*_URL at a newer build and replay.
  SEED_TREE="${SEED_TREE:-riscv}"
  SEED_BRANCH="${SEED_BRANCH:-master}"
  SEED_TREE_URL="${SEED_TREE_URL:-https://git.kernel.org/pub/scm/linux/kernel/git/riscv/linux.git}"
  SEED_VERSION="${SEED_VERSION:-7}"
  SEED_PATCHLEVEL="${SEED_PATCHLEVEL:-3}"
  # No tag placeholder: a build whose node carries no commit_tags reports none.
  # Defaulting to ["v7.3-rc1"] (the previous behaviour) put a tag on a node
  # whose describe said v7.3-rc2-655-... - a self-contradicting record nobody
  # would notice, since only the describe is displayed.
  SEED_TAGS="${SEED_TAGS:-${KCI_BUILD_TAGS:-}}"
  SEED_COMMIT="${SEED_COMMIT:-f217004a40c49e787372e798785aecb983828d35}"
  SEED_DESCRIBE="${SEED_DESCRIBE:-v7.3-rc1-516-gf217004a40c49}"
  if [ -z "${KCI_BUILD_COMMIT:-}" ]; then
    # Seeding with the placeholder is allowed (a hand-made Image has no build
    # metadata), but it must not happen quietly: every node this creates, and
    # every line ./run.sh report prints for them, will name a kernel that was
    # never booted.
    echo "  !! no build revision recorded: nodes from this seed will be labelled"
    echo "     $SEED_DESCRIBE, which is a placeholder, not the kernel in work/serve/Image."
    echo "     Fix: ./run.sh provision (records it), or set SEED_COMMIT/SEED_DESCRIBE."
  fi
  if [ -z "$SEED_TAGS" ] && [ -n "${KCI_BUILD_COMMIT:-}" ]; then
    echo "    (this build's node carries no commit_tags: the seeded nodes report none)"
  fi
  # Every value below is spliced into a JSON heredoc, so each one is escaped for
  # JSON rather than interpolated raw: a quote or backslash in a branch name or
  # a describe string used to produce an invalid body, and the API answered with
  # a parse error instead of a node.
  seed_json() { python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1"; }
  SEED_TREE_JSON="$(seed_json "$SEED_TREE")"
  SEED_TREE_URL_JSON="$(seed_json "$SEED_TREE_URL")"
  SEED_BRANCH_JSON="$(seed_json "$SEED_BRANCH")"
  SEED_COMMIT_JSON="$(seed_json "$SEED_COMMIT")"
  SEED_DESCRIBE_JSON="$(seed_json "$SEED_DESCRIBE")"
  SEED_TAGS_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1].split()))' "$SEED_TAGS")"
  SEED_MODULES_URL="${SEED_MODULES_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/modules.tar.xz}"
  SEED_KSELFTEST_URL="${SEED_KSELFTEST_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/kselftest.tar.xz}"
  SEED_CONFIG_URL="${SEED_CONFIG_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/.config}"
  # Preflight: the local Image is a hard requirement; broken production URLs
  # only warn (that job will report Infrastructure honestly; override and retry).
  [ -f "$SERVE_DIR/Image" ] || die "seed needs $SERVE_DIR/Image (run ./run.sh fetch or drop one there)"
  # Probe the seed artifacts with the user's proxy configuration as-is.
  # (This used to unset http_proxy/https_proxy unconditionally, with a comment
  # about "the dead local proxy" - one machine's temporary state.  Someone whose
  # proxy works would have it silently removed; KCI_BYPASS_PROXY=1 is the
  # explicit opt-in for a broken one.)
  for u in "$SEED_MODULES_URL" "$SEED_KSELFTEST_URL" "$SEED_CONFIG_URL"; do
    # HEAD, not a Range probe: files.kernelci.org ignores Range and streams
    # the whole file, so a range check on a big artifact always times out.
    kci_curl -s -m 15 -o /dev/null -I "$u" \
      || echo "  !! seed artifact unreachable: $u (override via SEED_*_URL; KCI_BYPASS_PROXY=1 ignores a dead proxy)"
  done
  # A kbuild node hangs off a checkout node, so the seed needs one to exist.
  # On a fresh database there is none - and the old lookup crashed (IndexError
  # from items[0] on an empty list) and carried on with an empty parent, so the
  # very first `./run.sh stack --seed` of a new deployment died.  Create the
  # checkout node when the database has none.
  api_get() { kci_curl -s -m 15 -H "Authorization: Bearer $TOKEN" "$API_URL/latest$1"; }
  PARENT="$(api_get "/nodes?kind=checkout&data.kernel_revision.tree=$SEED_TREE&limit=1" \
    | python3 -c 'import json,sys
try:
    items = json.load(sys.stdin).get("items", [])
except Exception:
    items = []
print(items[0]["id"] if items else "")')"
  if [ -z "$PARENT" ]; then
    echo "    no checkout node yet (fresh database); creating one"
    # The body goes through a file rather than piping a heredoc into python:
    # a pipe after a heredoc terminator inside a command substitution is a
    # syntax error bash only reports when it reaches the line.
    CHECKOUT_BODY="$(mktemp)"
    cat > "$CHECKOUT_BODY" <<EOF
{
  "name": "checkout", "kind": "checkout", "state": "done", "result": "pass",
  "group": "checkout", "path": ["checkout"],
  "data": {"kernel_revision": {"tree": $SEED_TREE_JSON,
            "url": $SEED_TREE_URL_JSON,
            "branch": $SEED_BRANCH_JSON,
            "commit": $SEED_COMMIT_JSON,
            "describe": $SEED_DESCRIBE_JSON,
            "version": {"version": $SEED_VERSION, "patchlevel": $SEED_PATCHLEVEL},
            "commit_tags": $SEED_TAGS_JSON, "tip_of_branch": true}}
}
EOF
    PARENT="$(kci_curl -s -m 30 -X POST -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" --data @"$CHECKOUT_BODY" \
      "$API_URL/latest/node" \
      | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("id", ""))
except Exception:
    print("")')"
    rm -f "$CHECKOUT_BODY"
    [ -n "$PARENT" ] || die "could not create a checkout node on $API_URL (is the API up and the token valid?)"
    echo "    checkout node created: $PARENT"
  fi
  # -m 30: the first POST after an API restart can stall mid-response; curl
  # must not wait forever. (The node may already exist server-side; re-running
  # only adds one more seed node, harmless in the dev DB.)
  if curl -s -m 30 -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" --data @- "$API_URL/latest/node" <<EOF
{
  "name": "kbuild-gcc-14-riscv", "kind": "kbuild", "state": "available",
  "parent": "$PARENT",
  "group": "kbuild-gcc-14-riscv", "path": ["checkout", "kbuild-gcc-14-riscv"],
  "data": {"arch": "riscv", "defconfig": "defconfig", "compiler": "gcc-14",
           "kernel_revision": {"tree": $SEED_TREE_JSON,
             "url": $SEED_TREE_URL_JSON,
             "branch": $SEED_BRANCH_JSON,
             "commit": $SEED_COMMIT_JSON,
             "describe": $SEED_DESCRIBE_JSON,
             "version": {"version": $SEED_VERSION, "patchlevel": $SEED_PATCHLEVEL},
             "commit_tags": $SEED_TAGS_JSON, "tip_of_branch": true}},
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
    pending="$(kci_curl -s -m 5 "$API_URL/latest/nodes?kind=job&state=available&limit=50" \
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
    --api-url "$API_URL" --tuxrun-bin "$TUXRUN_BIN" \
    --container-runtime docker --output-dir "/tmp/kci-worker-$PROJECT-out" \
    --state-file "/tmp/kci-worker-$PROJECT-state.json" --poll-period 5 --max-timeout 1200
else
  echo 'next step (manual):'
  echo "  ./run.sh worker --once            # same state file, one batch, then exit"
  echo "  # or directly: ./run.sh worker     # keep polling"
fi
