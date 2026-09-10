#!/usr/bin/env bash
# Tier B reproduction: clone the 3 minimal upstream repos + apply the PR1
# config patch + start the local full stack.
# Prerequisites: docker available; network access to github.com.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo '== 1/4 clone upstream repos (depth=1; only 3 - frontend/project not needed) =='
for repo in kernelci-core kernelci-api kernelci-pipeline; do
  [ -d "$repo" ] && { echo "  already present: $repo"; continue; }
  git clone --depth 1 "https://github.com/kernelci/$repo" || exit 1
done

echo '== 2/4 apply the PR1 config patch (4 YAML, 63 lines) =='
git -C kernelci-pipeline apply "$ROOT/config/pr1-config.patch" || \
  git -C kernelci-pipeline apply --3way "$ROOT/config/pr1-config.patch" || \
  { echo "patch failed: check the kernelci-pipeline version"; exit 1; }
echo "  applied:"; git -C kernelci-pipeline status --short | head -8

echo '== 2b/4 bullseye archive-source patch for the kernelci-api ssh container (Debian archive issue; required for the local build) =='
if grep -q 'archive.debian.org' kernelci-api/docker/ssh/Dockerfile 2>/dev/null; then
  echo "   fix already present, skipping"
else
  git -C kernelci-api apply "$ROOT/config/kernelci-api-bullseye-archive.patch" \
    && echo "   applied" || echo "   !! failed (upstream may have fixed it); if the ssh container build fails, check manually"
fi

echo '== 2c/4 storage nginx uid patch (jobdefs uploaded via scp must be readable by nginx as uid 1000) =='
if grep -q "user: '1000:1000'" kernelci-api/docker-compose.yaml 2>/dev/null; then
  echo "   fix already present, skipping"
else
  git -C kernelci-api apply "$ROOT/config/kernelci-api-storage-nginx-user.patch" \
    && echo "   applied" || echo "   !! failed (upstream may have fixed it); if jobdef uploads 404, check manually"
fi

echo '== 3/4 validate config (upstream official gate) =='
(cd kernelci-pipeline && python3 tests/validate_yaml.py) || exit 1

echo '== 4/4 write pipeline/.env (KCI_API_TOKEN etc.) =='
if [ ! -f kernelci-pipeline/.env ]; then
  cat > kernelci-pipeline/.env <<EOF
KCI_API_TOKEN=fill in your local kernelci-api admin JWT (see kernelci-api local-instance docs)
NO_DOCKER_PULL=1
KCI_TREES=riscv
EOF
  echo "   .env template written; create an admin per the kernelci-api local-instance docs, then fill KCI_API_TOKEN"
else
  echo "   kernelci-pipeline/.env already exists, skipping"
fi

echo
echo 'Done. Next steps:'
echo '  bash scripts/run-local-stack.sh --seed   # start API+callback+official scheduler and dispatch'
echo '  # then run the worker in another terminal (command printed by run-local-stack.sh)'
