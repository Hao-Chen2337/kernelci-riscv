#!/usr/bin/env bash
# Local KernelCI, one-time setup: the upstream clones, the patches this deployment
# needs, its own local configuration, and the pipeline YAML check.
#
#     deploy/setup.sh
#
# This is the body of `./run.sh setup`, moved out of the dispatcher when the
# deployment half got its own directory.  It is idempotent: `setup` on a machine
# that already has the checkouts reports them and re-runs only the checks (and it
# does not demand the network in that case).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIPE="$ROOT/kernelci-pipeline"
TUXRUN_BIN="${TUXRUN_BIN:-$(command -v tuxrun || echo "$HOME/.local/bin/tuxrun")}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

# shellcheck source=net-preflight.sh
. "$ROOT/deploy/net-preflight.sh"

  # Only demand a working network when something actually has to be cloned:
  # re-running setup on a machine that already has the upstream checkouts must
  # not fail just because the network is down.
repo=""
missing=0
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
  if [ -f "$ROOT/deploy/instance-init.sh" ]; then
    echo "-> generating deployment-local configuration (API .env, SSH keys, API token)"
    bash "$ROOT/deploy/instance-init.sh" || die "deploy/instance-init.sh failed"
  else
    echo "  !! deploy/instance-init.sh missing; generate kernelci-api/.env, the SSH key pair and KCI_API_TOKEN before deploy/stack.sh"
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
