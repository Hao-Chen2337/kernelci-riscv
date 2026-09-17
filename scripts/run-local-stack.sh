#!/usr/bin/env bash
# Local KernelCI full stack, one command: API stack + artifact server + real
# callback + the official scheduler (reading our YAMLs).
# Usage: [--seed] (POST a kbuild seed node) | [--worker] (seed + foreground worker)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT/kernelci-api"
PIPE_DIR="$ROOT/kernelci-pipeline"
ENV_FILE="$PIPE_DIR/.env"
SERVE_DIR="$ROOT/work/serve"
# Everything that identifies THIS deployment is overridable (KCI_COMPOSE_PROJECT plus
# the KCI_*_PORT variables), so a second one can run against its own empty database.
# They cannot run at once (compose hardcodes container_name); the volume decides freshness.
PROJECT="${KCI_COMPOSE_PROJECT:-kcirv}"
API_PORT="${KCI_API_PORT:-8001}"
STORAGE_PORT="${KCI_STORAGE_PORT:-8002}"
SSH_PORT="${KCI_SSH_PORT:-8022}"
MONGO_PORT="${KCI_MONGO_PORT:-8017}"
CB_PORT="${KCI_CB_PORT:-8003}"
SERVE_PORT="${KCI_SERVE_PORT:-8999}"
API_URL="http://127.0.0.1:$API_PORT"
# Per-deployment scheduler config dir, or "is a scheduler already running?" matched
# (and ./run.sh stop killed) another deployment's scheduler too (#18).
KCFG="/tmp/kcisched-$PROJECT"
# Ownership record of the host services this deployment starts (record_service).
PID_FILE="$ROOT/work/env/stack-$PROJECT.pids"
# compose reads these (${API_HOST_PORT:-8001} ...): exporting moves the published ports.
export API_HOST_PORT="$API_PORT" STORAGE_HOST_PORT="$STORAGE_PORT"
export SSH_HOST_PORT="$SSH_PORT" MONGO_HOST_PORT="$MONGO_PORT"
# Rendered from the tracked @NAME@ templates into gitignored files under work/:
# toml.load() does not expand environment variables, so a tracked file cannot name
# the checkout next to it or this deployment's ports.
SETTINGS="$ROOT/work/local-callback.toml"
CB_CONFIG="$ROOT/work/cb-config/pipeline.yaml"
TUXRUN_BIN="${TUXRUN_BIN:-$(command -v tuxrun || echo "$HOME/.local/bin/tuxrun")}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

# shellcheck source=net-preflight.sh
. "$ROOT/scripts/net-preflight.sh"

# --- ports ------------------------------------------------------------------
# Every port is overridable (KCI_*_PORT) and nothing checked it was free first: a
# listener surfaced three layers down as "X artifact server failed".  The probe is
# kcilib/core/ports.py's (shared with scripts/fetch-and-run-latest.py; --host 0.0.0.0).
require_port_free() {   # port label override-var
  PYTHONPATH="$ROOT/scripts" python3 -m kcilib.core.ports \
    --require "$1" --label "$2" --override "$3" \
    --host 0.0.0.0 --project "$PROJECT" || exit 1
}

# --- service ownership ------------------------------------------------------
# ./run.sh stop used machine-global pkill patterns and killed another deployment's
# services (#18); here each service is recorded as role|pid|start-time|pattern and
# stop kills those pids after re-reading the start time (a recycled pid survives).
record_service() {   # role pattern
  local role="$1" pattern="$2" pid start
  mkdir -p "$(dirname "$PID_FILE")"
  for pid in $(pgrep -f "$pattern" 2>/dev/null); do
    start="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
    [ -n "$start" ] || continue          # pid vanished between pgrep and here
    printf '%s|%s|%s|%s\n' "$role" "$pid" "$start" "$pattern" >> "$PID_FILE"
  done
}

[ -f "$ENV_FILE" ] || die "$ENV_FILE missing; run ./run.sh setup first"
TOKEN="$(grep '^KCI_API_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
# setup's placeholder text ("fill in the local kernelci-api admin JWT ...") is
# non-empty, so it used to pass and then 401 on every API call: demand a JWT shape.
case "$TOKEN" in
  ""|fill\ in*|*" "*)
    die "KCI_API_TOKEN in $ENV_FILE is not a real token (found: '${TOKEN:0:48}'); run ./run.sh setup (or scripts/local-instance-init.sh) to generate one" ;;
  eyJ*) ;;
  *)
    echo "  !! KCI_API_TOKEN does not look like a local API JWT (no 'eyJ' prefix); continuing" ;;
esac

python3 "$ROOT/scripts/tools/render-local-config.py" \
  --template "$ROOT/config/local-callback.toml" --output "$SETTINGS" >/dev/null \
  || die "could not render $SETTINGS from config/local-callback.toml"
python3 "$ROOT/scripts/tools/render-local-config.py" \
  --template "$ROOT/config/cb-config/pipeline.yaml" --output "$CB_CONFIG" \
  --var API_PORT="$API_PORT" --var STORAGE_PORT="$STORAGE_PORT" \
  --var SSH_PORT="$SSH_PORT" >/dev/null \
  || die "could not render $CB_CONFIG from config/cb-config/pipeline.yaml"
ok "settings rendered ($SETTINGS, $CB_CONFIG; project=$PROJECT api=$API_PORT)"

# --- seed inputs ------------------------------------------------------------
# Resolved BEFORE any service is started: a tree label that disagrees with the
# artifacts being booted used to cost a whole stack start plus the 90 s wait (#1).
# A seed that cannot work must cost a second.
seed_requested() {
  [ "${1:-}" = "--seed" ] || [ "${1:-}" = "--worker" ]
}

# Every value below is spliced into a JSON heredoc, so escape it: a quote or
# backslash used to make the body invalid and the API answered with a parse error.
seed_json() { python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1"; }

resolve_seed_inputs() {
  # CONSISTENCY RULE: work/serve/Image, the modules in work/env/rootfs-kvm.ext4 and
  # these URLs must be the SAME kbuild (modprobe matches by kernel release), so read
  # work/env/build.env; the SEED_* defaults below only cover a never-provisioned stack.
  if [ -f "$ROOT/work/env/build.env" ]; then
    # shellcheck disable=SC1091
    . "$ROOT/work/env/build.env"
    if [ -n "${KCI_BUILD_DIR:-}" ]; then
      echo "    seeding from the provisioned build: $KCI_BUILD_DIR"
      SEED_MODULES_URL="${SEED_MODULES_URL:-$KCI_BUILD_DIR/modules.tar.xz}"
      SEED_KSELFTEST_URL="${SEED_KSELFTEST_URL:-$KCI_BUILD_DIR/kselftest.tar.xz}"
      SEED_CONFIG_URL="${SEED_CONFIG_URL:-$KCI_BUILD_DIR/.config}"
    fi
    # The revision of that build, so the nodes name the kernel that actually boots:
    # the hardcoded defaults labelled a 7.3-rc2 deployment v7.3-rc1-516-gf217004a40c49.
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
  # The whole seed is env-overridable, so a pruned build can be replaced and replayed.
  SEED_TREE="${SEED_TREE:-riscv}"
  SEED_BRANCH="${SEED_BRANCH:-master}"
  SEED_TREE_URL="${SEED_TREE_URL:-https://git.kernel.org/pub/scm/linux/kernel/git/riscv/linux.git}"
  SEED_VERSION="${SEED_VERSION:-7}"
  SEED_PATCHLEVEL="${SEED_PATCHLEVEL:-3}"
  # No tag placeholder: defaulting to ["v7.3-rc1"] put a tag on a node whose
  # describe said v7.3-rc2-655-..., a self-contradicting record nobody notices.
  SEED_TAGS="${SEED_TAGS:-${KCI_BUILD_TAGS:-}}"
  SEED_COMMIT="${SEED_COMMIT:-f217004a40c49e787372e798785aecb983828d35}"
  SEED_DESCRIBE="${SEED_DESCRIBE:-v7.3-rc1-516-gf217004a40c49}"
  if [ -z "${KCI_BUILD_COMMIT:-}" ]; then
    # Seeding with the placeholder is allowed (a hand-made Image has no build
    # metadata) but must not happen quietly: every node will name a kernel that
    # was never booted.
    echo "  !! no build revision recorded: nodes from this seed will be labelled"
    echo "     $SEED_DESCRIBE, which is a placeholder, not the kernel in work/serve/Image."
    echo "     Fix: ./run.sh provision (records it), or set SEED_COMMIT/SEED_DESCRIBE."
  fi
  if [ -z "$SEED_TAGS" ] && [ -n "${KCI_BUILD_COMMIT:-}" ]; then
    echo "    (this build's node carries no commit_tags: the seeded nodes report none)"
  fi
  SEED_TREE_JSON="$(seed_json "$SEED_TREE")"
  SEED_TREE_URL_JSON="$(seed_json "$SEED_TREE_URL")"
  SEED_BRANCH_JSON="$(seed_json "$SEED_BRANCH")"
  SEED_COMMIT_JSON="$(seed_json "$SEED_COMMIT")"
  SEED_DESCRIBE_JSON="$(seed_json "$SEED_DESCRIBE")"
  SEED_TAGS_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1].split()))' "$SEED_TAGS")"
  SEED_MODULES_URL="${SEED_MODULES_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/modules.tar.xz}"
  SEED_KSELFTEST_URL="${SEED_KSELFTEST_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/kselftest.tar.xz}"
  SEED_CONFIG_URL="${SEED_CONFIG_URL:-https://files.kernelci.org/kbuild-gcc-14-riscv-6aa2170920239ade901a683f/.config}"
}

# rules.tree is an ALLOW-LIST the scheduler enforces with should_create_node: a tree
# it refuses started everything, waited the full 90 s and ended with "no job node
# appeared".  Asking the scheduler's own code and config cannot drift from it.
seed_tree_guard() {
  local out allowed_trees reason
  if ! out="$(PYTHONPATH="$ROOT/kernelci-core" \
      KCI_SEED_TREE="$SEED_TREE" KCI_SEED_BRANCH="$SEED_BRANCH" \
      python3 - "$PIPE_DIR" 2>&1 <<'PY'
import os
import sys

import yaml
from kernelci.api.helper import APIHelper

pipe_dir = sys.argv[1]
tree = os.environ["KCI_SEED_TREE"]
branch = os.environ["KCI_SEED_BRANCH"]
with open(os.path.join(pipe_dir, "config", "pipeline-pull-labs.yaml")) as handle:
    config = yaml.safe_load(handle)
runtime = (config.get("runtimes") or {}).get("pull-labs-riscv") or {}
rules = runtime.get("rules") or {}
# Rules are pure data; a real APIHelper would need an API connection.
helper = APIHelper.__new__(APIHelper)
node = {"data": {"kernel_revision": {"tree": tree, "branch": branch}}}
allowed = helper.should_create_node(rules, node)
print("RULES_TREE: " + " ".join(rules.get("tree") or []))
print("VERDICT: " + ("ALLOWED" if allowed else "REFUSED"))
PY
)"; then
    # kernelci-core not importable or config unreadable: carry on - the wait below
    # prints the scheduler's own rejection reason, so a refusal is still visible.
    echo "  !! pre-seed tree check could not run (kernelci-core importable?):"
    printf '%s\n' "$out" | tail -3 | sed 's/^/     /'
    echo "     continuing; if the scheduler rejects this seed, it says why after the wait."
    return 0
  fi
  case "$out" in
    *"VERDICT: ALLOWED"*) return 0 ;;
    *"VERDICT: REFUSED"*) ;;
    *)
      echo "  !! unexpected output from the pre-seed tree check:"
      printf '%s\n' "$out" | tail -3 | sed 's/^/     /'
      return 0
      ;;
  esac
  allowed_trees="$(printf '%s\n' "$out" | sed -n 's/^RULES_TREE: //p')"
  reason="$(printf '%s\n' "$out" | grep 'rules\[' | head -1)"
  die "refusing to seed tree '$SEED_TREE': the pull-labs-riscv runtime does not accept it
    ${reason:-(the runtime rules refused the node)}
    allowed trees: ${allowed_trees:-?}  (kernelci-pipeline/config/pipeline-pull-labs.yaml)
    work/env/build.env records this deployment's build as tree '${KCI_BUILD_TREE:-?}',
    so a seed labelled '$SEED_TREE' is created and then dropped by the scheduler: the
    run would wait ${SEED_WAIT_S:-90}s and end with 'no job node appeared'.
    Two honest ways out:
      * keep the artifacts and label the seed with an accepted tree (the node's tree
        then disagrees with the kernel that boots - recorded in work/env/seed.env):
          SEED_TREE=${allowed_trees%% *} ./run.sh stack --seed
      * or let this runtime accept the build's tree, in the scheduler's own config:
          add '${KCI_BUILD_TREE:-<tree>}' to runtimes.pull-labs-riscv.rules.tree in
          kernelci-pipeline/config/pipeline-pull-labs.yaml"
}

# Provenance for the seed, written even when the run dies later: the nodes say
# tree=$SEED_TREE while the artifacts come from the tree=$KCI_BUILD_TREE build,
# and that difference is invisible in the API.
write_seed_provenance() {
  mkdir -p "$ROOT/work/env"
  {
    echo "# Written by ./run.sh stack --seed.  What the seeded nodes claim, and"
    echo "# which build the artifacts they boot come from: read this before"
    echo "# trusting a node's tree label."
    echo "KCI_SEED_TREE=$SEED_TREE"
    echo "KCI_SEED_BRANCH=$SEED_BRANCH"
    echo "KCI_SEED_BUILD_TREE=${KCI_BUILD_TREE:-}"
    echo "KCI_SEED_BUILD_DIR=${KCI_BUILD_DIR:-}"
    echo "KCI_SEED_COMMIT=$SEED_COMMIT"
    echo "KCI_SEED_DESCRIBE=$SEED_DESCRIBE"
    echo "KCI_SEED_MODULES_URL=$SEED_MODULES_URL"
    echo "KCI_SEED_KSELFTEST_URL=$SEED_KSELFTEST_URL"
    echo "KCI_SEED_CONFIG_URL=$SEED_CONFIG_URL"
    echo "KCI_SEED_TREE_MISMATCH=$1"
    echo "KCI_SEED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$ROOT/work/env/seed.env"
  if [ "$1" = 1 ]; then
    # Loud on purpose: the run is real, the attribution is not.
    echo "  !! these nodes will say tree=$SEED_TREE, but the kernel and modules they"
    echo "     boot come from the tree=${KCI_BUILD_TREE:-?} build (${KCI_BUILD_DIR:-no build.env})"
    echo "     recorded in work/env/seed.env (KCI_SEED_TREE_MISMATCH=1)."
  else
    echo "    seed provenance recorded in work/env/seed.env"
  fi
}


# The ssh container stores job definitions through these bind mounts as uid 1000
# (see kernelci-api/docker/ssh/Dockerfile).  Any other owner makes every job stay
# incomplete with "submit error": StorageSSH._upload's `mkdir -p` fails SILENTLY.
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


# The worker's callback token: the environment first, else this deployment's rendered
# settings ([runtime].pull-labs-riscv.callback_token).  The literal "labtoken-callback"
# that used to sit here 401/403'd every one of them - a PERMANENT failure (#10).
CALLBACK_TOKEN="${PULL_LABS_CALLBACK_TOKEN:-}"
TOKEN_SOURCE="built-in default (config/local-callback.toml's literal)"
if [ -z "$CALLBACK_TOKEN" ] && [ -f "$SETTINGS" ]; then
  CALLBACK_TOKEN="$(python3 - "$SETTINGS" <<'PY'
import re
import sys

# python3 here is 3.10 (no tomllib), and the renderer emits one line per runtime.
with open(sys.argv[1]) as handle:
    text = handle.read()
match = re.search(
    r"^\s*pull-labs-riscv\s*=\s*\{[^}]*callback_token\s*=\s*\"([^\"]*)\"",
    text,
    re.M,
)
print(match.group(1) if match else "")
PY
)"
  if [ -n "$CALLBACK_TOKEN" ]; then
    TOKEN_SOURCE="$SETTINGS ([runtime] pull-labs-riscv callback_token)"
    case "$CALLBACK_TOKEN" in
      "Token "*) CALLBACK_TOKEN="${CALLBACK_TOKEN#Token }" ;;
      *)
        echo "  !! the configured callback_token does not start with 'Token ', but the"
        echo "     worker sends 'Token <PULL_LABS_CALLBACK_TOKEN>': this cannot match, so"
        echo "     every result would come back 401.  Fix the token in $SETTINGS"
        ;;
    esac
  fi
fi
if [ -z "$CALLBACK_TOKEN" ]; then
  CALLBACK_TOKEN="labtoken-callback"
fi

# Resolve the seed and check its tree label BEFORE a single service is started:
# a seed the runtime will reject must cost one second, not a stack start (#1).
if seed_requested "${1:-}"; then
  echo "-> resolving the seed (checked against the runtime's rules before starting)"
  resolve_seed_inputs
  seed_tree_guard
  SEED_TREE_MISMATCH=0
  if [ -n "${KCI_BUILD_TREE:-}" ] && [ "$KCI_BUILD_TREE" != "$SEED_TREE" ]; then
    SEED_TREE_MISMATCH=1
  fi
  write_seed_provenance "$SEED_TREE_MISMATCH"
fi

# Fresh ownership record: ./run.sh stop stops exactly the services this run (re)started.
mkdir -p "$(dirname "$PID_FILE")"
: > "$PID_FILE"

# 1) KernelCI API stack
#
# Run `up -d` even when the API answers: only compose knows whether the running
# containers still match the requested port mappings, and skipping it left them on
# the default ports while the rendered cb-config pointed at this deployment's.
if curl -s -m 3 -o /dev/null "$API_URL/latest/"; then
  ok "API stack already up ($API_URL)"
  (cd "$API_DIR" && docker compose -p "$PROJECT" up -d api db redis storage ssh >/dev/null) \
    || echo "  !! compose could not reconcile the running containers; ports may be stale"
else
  # Bindability first, and name the conflict: a compose that cannot publish 8001
  # reports it in its own words, sending the reader through the API's logs instead.
  require_port_free "$API_PORT" "kernelci API" KCI_API_PORT
  require_port_free "$STORAGE_PORT" "artifact storage" KCI_STORAGE_PORT
  require_port_free "$SSH_PORT" "job-definition ssh" KCI_SSH_PORT
  require_port_free "$MONGO_PORT" "mongo" KCI_MONGO_PORT
  echo "-> starting: docker compose -p $PROJECT up -d api db redis storage ssh"
  if ! (cd "$API_DIR" && docker compose -p "$PROJECT" up -d api db redis storage ssh >/dev/null); then
    # After a machine/docker restart, stale Exited containers cause compose name
    # conflicts; the data lives in volumes, so removing them is safe.
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

# Which artifact is actually running - recorded, not inferred: compose pulls a
# *mutable* tag, so the image this deployment tested can change overnight, and no
# report could otherwise name what it verified.  Read back from the container.
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
  # Say so rather than write nothing: this record is the only way a later report can
  # name the artifact it verified (a renamed container would vanish without a trace).
  echo "  !! could not read the running API image id (docker inspect kernelci-api failed);"
  echo "     work/env/images.env was NOT written, so this run's artifact is unrecorded"
fi

# `stop` + `stack` used to truncate the previous round's logs (every service logs to
# a fixed /tmp path).  Rotate one generation, and ONLY just before starting the service:
# rotating an already-running one left the live round writing to a moved inode.
rotate_log() {
  [ -f "$1" ] && mv -f "$1" "$1.prev"
  return 0
}

# Every launch below redirects the SUBSHELL too: redirecting only the service left
# it holding the caller's stdout, so `./run.sh stack | tee log` never saw EOF.
# 2) artifact server (8999)
if curl -s -m 3 -o /dev/null "http://127.0.0.1:$SERVE_PORT/Image"; then
  ok "artifact server already up (:$SERVE_PORT)"
  record_service "artifact server" "http\.server $SERVE_PORT"
else
  # A listener that does not answer /Image is the case the old "X artifact server
  # failed" hid; require_port_free names the port and the holder instead.
  require_port_free "$SERVE_PORT" "artifact server" KCI_SERVE_PORT
  rotate_log "/tmp/fs$SERVE_PORT.log"
  (cd "$SERVE_DIR" && setsid nohup python3 -m http.server $SERVE_PORT --bind 0.0.0.0 >/tmp/fs$SERVE_PORT.log 2>&1 < /dev/null &) >/dev/null 2>&1
  sleep 2
  if curl -s -m 3 -o /dev/null "http://127.0.0.1:$SERVE_PORT/Image"; then
    ok "artifact server started (:$SERVE_PORT)"
    record_service "artifact server" "http\.server $SERVE_PORT"
  else
    # The service's own log is the evidence; print it, not just its path.
    tail -3 "/tmp/fs$SERVE_PORT.log" 2>/dev/null | sed 's/^/     /'
    die "artifact server failed on port $SERVE_PORT (see /tmp/fs$SERVE_PORT.log)"
  fi
fi

# 3) real lava_callback (validates the token)
if curl -s -m 3 -o /dev/null "http://127.0.0.1:$CB_PORT/"; then
  ok "lava_callback already up (:$CB_PORT)"
  record_service "lava_callback" "uvicorn lava_callback:app --port $CB_PORT"
else
  require_port_free "$CB_PORT" "lava_callback" KCI_CB_PORT
  # lava_callback runs on the HOST against the cloned kernelci-core, so import it to
  # check the deps.  KCI_SETTINGS is read AT IMPORT TIME (toml.load): without it a
  # healthy machine dies with FileNotFoundError 'config/kernelci.toml'.
  if ! CALLBACK_IMPORT_ERROR="$(cd "$PIPE_DIR/src" && KCI_SETTINGS="$SETTINGS" \
      PYTHONPATH="$ROOT/kernelci-core" python3 -c 'import lava_callback' 2>&1)"; then
    echo "$CALLBACK_IMPORT_ERROR" | tail -3 >&2
    die "the callback service cannot be imported (see the traceback above); install the host deps with: python3 -m pip install -r requirements.txt && python3 -m pip install -r kernelci-core/requirements.txt"
  fi
  rotate_log "/tmp/cb$CB_PORT.log"
  (cd "$PIPE_DIR/src" && KCI_SETTINGS="$SETTINGS" KCI_API_TOKEN="$TOKEN" PYTHONPATH="$ROOT/kernelci-core" setsid nohup python3 -m uvicorn lava_callback:app --port $CB_PORT --host 0.0.0.0 >/tmp/cb$CB_PORT.log 2>&1 < /dev/null &) >/dev/null 2>&1
  sleep 4
  if curl -s -m 3 -o /dev/null "http://127.0.0.1:$CB_PORT/"; then
    ok "lava_callback started (:$CB_PORT)"
    record_service "lava_callback" "uvicorn lava_callback:app --port $CB_PORT"
  else
    tail -3 "/tmp/cb$CB_PORT.log" 2>/dev/null | sed 's/^/     /'
    die "callback failed on port $CB_PORT (see /tmp/cb$CB_PORT.log)"
  fi
fi

# 4) official scheduler (reads our 4 YAMLs, renders jobdefs in real time)
if pgrep -f "scheduler\.py.*--yaml-config $KCFG/" >/dev/null; then
  ok "scheduler already running (pull-labs-riscv, config $KCFG)"
  record_service "scheduler" "scheduler\.py.*--yaml-config $KCFG/"
else
  # A second scheduler on the same API dispatches every job twice (both subscribe to
  # the same node events), so a scheduler that is not ours is a conflict to report.
  if pgrep -af "scheduler\.py.*pull-labs-riscv" | grep -qv "$KCFG/"; then
    echo "  !! a scheduler for the same runtime is already running without this"
    echo "     deployment's config directory ($KCFG):"
    pgrep -af "scheduler\.py.*pull-labs-riscv" | sed 's/^/       /'
    die "starting a second one would create every job node twice; stop that one (./run.sh stop, or kill the pid above) and re-run"
  fi
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
  if pgrep -f "scheduler\.py.*--yaml-config $KCFG/" >/dev/null; then
    ok "scheduler started (pull-labs-riscv, config $KCFG)"
    record_service "scheduler" "scheduler\.py.*--yaml-config $KCFG/"
  else
    tail -3 /tmp/sched-local.log 2>/dev/null | sed 's/^/     /'
    die "scheduler failed on config $KCFG (see /tmp/sched-local.log)"
  fi
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
  # The seed was resolved and its tree label checked before any service started
  # (resolve_seed_inputs / seed_tree_guard).  Left: the local preflight, the checkout
  # parent and the POST.  Image is required; broken artifact URLs only warn.
  [ -f "$SERVE_DIR/Image" ] || die "seed needs $SERVE_DIR/Image (run ./run.sh fetch or drop one there)"
  # Probe with the user's proxy configuration as-is (KCI_BYPASS_PROXY=1 is the explicit
  # opt-in for a broken one - this used to unset the proxies silently).  These are the
  # ARTIFACT host, not the API endpoint: a green line here is not a verdict on the API.
  for u in "$SEED_MODULES_URL" "$SEED_KSELFTEST_URL" "$SEED_CONFIG_URL"; do
    # HEAD, not Range: files.kernelci.org ignores Range and streams the whole file.
    kci_curl -s -m 15 -o /dev/null -I "$u" \
      || echo "  !! seed artifact unreachable: $u (override via SEED_*_URL; KCI_BYPASS_PROXY=1 ignores a dead proxy)"
  done
  # A kbuild node hangs off a checkout node; a fresh database has none, and the old
  # lookup crashed on an empty list (IndexError from items[0]) and carried on with an
  # empty parent, so the first --seed of a new deployment died.  Create one.
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
    # Body via a file: piping a heredoc into python inside a command substitution
    # is a syntax error bash only reports when it reaches the line.
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
  # -m 30: the first POST after an API restart can stall mid-response, and curl must
  # not wait forever (re-running only adds one more seed node, harmless in a dev DB).
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
    # The node's own tree label is what the API and every report show: name where
    # the difference from the served artifacts is recorded (#1).
    echo "    (seed provenance: work/env/seed.env; tree label $SEED_TREE, build tree ${KCI_BUILD_TREE:-none recorded})"
  else
    echo "  !! seed POST got no response (the node may still exist - check /latest/nodes; re-running is harmless)"
  fi
  # Wait for the scheduler to render the job nodes: `worker --once` straight after
  # seeding hit an empty queue and printed "batch processed, exiting" - having run
  # nothing at all, which looks like success and is deeply confusing.
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
  if ! [ "${pending:-0}" -ge 1 ] 2>/dev/null; then
    echo "  !! no job node appeared within ${SEED_WAIT_S:-90}s"
    # The scheduler's own reason first: a rule rejection is one stdout line in a log
    # full of paramiko debug, so "check /tmp/sched-local.log" explains nothing (#4).
    reasons="$(grep -aE 'rules\[|not allowed|Not creating node' /tmp/sched-local.log 2>/dev/null | tail -5 || true)"
    if [ -n "$reasons" ]; then
      echo "     the scheduler refused to create them:"
      printf '%s\n' "$reasons" | sed 's/^/       /'
      echo "     (the seed's tree label is $SEED_TREE; runtimes.pull-labs-riscv.rules"
      echo "      in kernelci-pipeline/config/pipeline-pull-labs.yaml is the allow-list)"
    else
      echo "     no rule rejection in the scheduler log; look for 'submit error',"
      echo "     'unable to connect' or a traceback near the end of /tmp/sched-local.log"
    fi
    echo "     full log: /tmp/sched-local.log"
  fi
fi

if [ "${1:-}" = "--worker" ]; then
  echo '-> worker taking jobs (Ctrl-C to stop):'
  echo "   callback token from: $TOKEN_SOURCE"
  # The token comes from CALLBACK_TOKEN above, not the literal that used to sit here:
  # the callback validates the header it receives against the configured token (#10).
  PYTHONUNBUFFERED=1 PATH=/usr/local/sbin:/usr/sbin:$PATH PULL_LABS_CALLBACK_TOKEN="$CALLBACK_TOKEN" \
    kci_run python3 "$ROOT/scripts/riscv_pull_worker.py" \
    --api-url "$API_URL" --tuxrun-bin "$TUXRUN_BIN" \
    --container-runtime docker --output-dir "/tmp/kci-worker-$PROJECT-out" \
    --state-file "/tmp/kci-worker-$PROJECT-state.json" --poll-period 5 --max-timeout 1200
else
  echo 'next step (manual):'
  echo "  ./run.sh worker --once            # same state file, one batch, then exit"
  echo "  # or directly: ./run.sh worker     # keep polling"
fi
