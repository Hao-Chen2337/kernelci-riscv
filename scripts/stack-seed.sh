#!/usr/bin/env bash
# The seed half of scripts/run-local-stack.sh, which SOURCES this file (never runs
# it): the resolve/write functions set SEED_* in the caller's scope, and the tree
# guard and the seed POST call the caller's die().
# Rationale: docs/code-notes/W2a-shell.md
set -uo pipefail

# --- seed inputs ------------------------------------------------------------
# Resolved BEFORE any service is started: a tree label that disagrees with the
# artifacts being booted used to cost a whole stack start plus the 90 s wait (#1).
# A seed that cannot work must cost a second.

# EVERY argument is scanned, not just $1: ./run.sh stack foo --seed used to start
# the stack with the flag silently ignored (#24).
seed_requested() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      --seed|--worker) return 0 ;;
    esac
  done
  return 1
}

worker_requested() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      --worker) return 0 ;;
    esac
  done
  return 1
}

resolve_seed_inputs() {
  # CONSISTENCY RULE: work/serve/Image, the modules and kselftest these URLs name
  # must be the SAME kbuild (modprobe matches by kernel release), so read
  # work/env/build.env; the SEED_* defaults below only cover a never-provisioned
  # stack.  The guest rootfs is not part of this rule: it is the lab's own image
  # (policy.POLICY.rootfs_url), baked per run into the bake cache.
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

# The seed used to be resolved after the whole stack was up, which turned a tree
# label this runtime rejects into a full start plus the 90 s wait (#1).
seed_prepare() {
  echo "-> resolving the seed (checked against the runtime's rules before starting)"
  resolve_seed_inputs
  seed_tree_guard
  SEED_TREE_MISMATCH=0
  if [ -n "${KCI_BUILD_TREE:-}" ] && [ "$KCI_BUILD_TREE" != "$SEED_TREE" ]; then
    SEED_TREE_MISMATCH=1
  fi
  write_seed_provenance "$SEED_TREE_MISMATCH"
}

# The node bodies are built by python's json.dumps, never by splicing escaped
# values into a heredoc: one quote in a SEED_* value made the body invalid, and
# the API answered with a parse error instead of a node.
seed_node_json() {   # kind (checkout|kbuild) -> the node body on stdout
  KCI_SEED_KIND="$1" \
    KCI_SEED_TREE="$SEED_TREE" KCI_SEED_TREE_URL="$SEED_TREE_URL" \
    KCI_SEED_BRANCH="$SEED_BRANCH" KCI_SEED_COMMIT="$SEED_COMMIT" \
    KCI_SEED_DESCRIBE="$SEED_DESCRIBE" KCI_SEED_VERSION="$SEED_VERSION" \
    KCI_SEED_PATCHLEVEL="$SEED_PATCHLEVEL" KCI_SEED_TAGS="$SEED_TAGS" \
    KCI_SEED_PARENT="${PARENT:-}" KCI_SEED_SERVE_PORT="$SERVE_PORT" \
    KCI_SEED_MODULES_URL="$SEED_MODULES_URL" \
    KCI_SEED_KSELFTEST_URL="$SEED_KSELFTEST_URL" \
    KCI_SEED_CONFIG_URL="$SEED_CONFIG_URL" \
    python3 - <<'PY'
import json
import os

env = os.environ


def as_number(text):
    # The old body spliced these raw, so "7" has to stay a JSON number.
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


revision = {
    "tree": env["KCI_SEED_TREE"],
    "url": env["KCI_SEED_TREE_URL"],
    "branch": env["KCI_SEED_BRANCH"],
    "commit": env["KCI_SEED_COMMIT"],
    "describe": env["KCI_SEED_DESCRIBE"],
    "version": {
        "version": as_number(env["KCI_SEED_VERSION"]),
        "patchlevel": as_number(env["KCI_SEED_PATCHLEVEL"]),
    },
    "commit_tags": env["KCI_SEED_TAGS"].split(),
    "tip_of_branch": True,
}
if env["KCI_SEED_KIND"] == "checkout":
    body = {
        "name": "checkout", "kind": "checkout", "state": "done", "result": "pass",
        "group": "checkout", "path": ["checkout"],
        "data": {"kernel_revision": revision},
    }
else:
    body = {
        "name": "kbuild-gcc-14-riscv", "kind": "kbuild", "state": "available",
        "parent": env["KCI_SEED_PARENT"], "group": "kbuild-gcc-14-riscv",
        "path": ["checkout", "kbuild-gcc-14-riscv"],
        "data": {"arch": "riscv", "defconfig": "defconfig", "compiler": "gcc-14",
                 "kernel_revision": revision},
        "artifacts": {
            "kernel": "http://172.17.0.1:%s/Image" % env["KCI_SEED_SERVE_PORT"],
            "modules": env["KCI_SEED_MODULES_URL"],
            "kselftest_tar_xz": env["KCI_SEED_KSELFTEST_URL"],
            "_config": env["KCI_SEED_CONFIG_URL"],
        },
    }
print(json.dumps(body))
PY
}

# The seed POSTs through the API's bearer token; the kbuild body below is posted
# with plain curl, exactly as before (the artifact probes are the other host).
api_get() { kci_curl -s -m 15 -H "Authorization: Bearer $TOKEN" "$API_URL/latest$1"; }

# --- the seed POST ----------------------------------------------------------
seed_stack() {
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
  PARENT="$(api_get "/nodes?kind=checkout&data.kernel_revision.tree=$SEED_TREE&limit=1" \
    | python3 -c 'import json,sys
try:
    items = json.load(sys.stdin).get("items", [])
except Exception:
    items = []
print(items[0]["id"] if items else "")')"
  if [ -z "$PARENT" ]; then
    echo "    no checkout node yet (fresh database); creating one"
    local checkout_body
    checkout_body="$(seed_node_json checkout)"
    PARENT="$(kci_curl -s -m 30 -X POST -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" --data "$checkout_body" \
      "$API_URL/latest/node" \
      | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("id", ""))
except Exception:
    print("")')"
    [ -n "$PARENT" ] || die "could not create a checkout node on $API_URL (is the API up and the token valid?)"
    echo "    checkout node created: $PARENT"
  fi
  # -m 30: the first POST after an API restart can stall mid-response, and curl must
  # not wait forever (re-running only adds one more seed node, harmless in a dev DB).
  local kbuild_body
  kbuild_body="$(seed_node_json kbuild)"
  if curl -s -m 30 -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" --data "$kbuild_body" "$API_URL/latest/node"; then
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
}
