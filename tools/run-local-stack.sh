#!/usr/bin/env bash
# 本地 KernelCI 全栈一键起:API 栈 + 构件服务 + 真实回调 + 官方调度器(读我们的 YAML)
# 用法:
#   run-local-stack.sh            # 只起服务,打印状态和下一步命令
#   run-local-stack.sh --seed     # 起服务 + 自动 POST kbuild 种子节点(触发派单)
#   run-local-stack.sh --worker   # 起服务 + seed + 前台跑 worker 接单
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT/kernelci-api"
PIPE_DIR="$ROOT/kernelci-pipeline"
# repo root layout: tools/ config/ runs/ artifacts/ docs/ archive/
ENV_FILE="$PIPE_DIR/.env"
TOKEN="$(grep '^KCI_API_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
SERVE_DIR="$ROOT/runs/kvm-loop/serve"
SERVE_PORT=8999
CB_PORT=8003

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

[ -n "$TOKEN" ] || die "KCI_API_TOKEN not in $ENV_FILE"

# 1) KernelCI API stack
if curl -s -m 3 -o /dev/null http://127.0.0.1:8001/latest/; then
  ok "API stack already up (127.0.0.1:8001)"
else
  echo "-> starting: docker compose -p kapi2 up -d api db redis storage ssh"
  (cd "$API_DIR" && docker compose -p kapi2 up -d api db redis storage ssh >/dev/null) || die "compose failed"
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
  PARENT="$(curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8001/latest/nodes?kind=checkout&data.kernel_revision.tree=riscv&limit=1" | python3 -c 'import json,sys;print(json.load(sys.stdin)["items"][0]["id"])')"
  curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" --data @- http://127.0.0.1:8001/latest/node <<EOF
{
  "name": "kbuild-gcc-14-riscv", "kind": "kbuild", "state": "available",
  "parent": "$PARENT",
  "group": "kbuild-gcc-14-riscv", "path": ["checkout", "kbuild-gcc-14-riscv"],
  "data": {"arch": "riscv", "defconfig": "defconfig", "compiler": "gcc-14",
           "kernel_revision": {"tree": "riscv",
             "url": "https://git.kernel.org/pub/scm/linux/kernel/git/riscv/linux.git",
             "branch": "master",
             "commit": "548b86839f7fb819a4d6c83b71c73ec378d24275",
             "describe": "v7.3-rc1-474-g548b86839f7fb",
             "version": {"version": 7, "patchlevel": 3},
             "commit_tags": ["v7.3-rc1"], "tip_of_branch": true}},
  "artifacts": {
    "kernel": "http://172.17.0.1:$SERVE_PORT/Image",
    "modules": "https://files.kernelci.org/kbuild-gcc-14-riscv-6aa0b795e41d7f97d618c887/modules.tar.xz",
    "kselftest_tar_xz": "https://files.kernelci.org/kbuild-gcc-14-riscv-6aa0b795e41d7f97d618c887/kselftest.tar.xz",
    "_config": "https://files.kernelci.org/kbuild-gcc-14-riscv-6aa0b795e41d7f97d618c887/.config"
  }
}
EOF
  echo "    seeded; scheduler will auto-create the 3 job nodes"
fi

if [ "${1:-}" = "--worker" ]; then
  echo '-> worker taking jobs (Ctrl-C to stop):'
  PATH=/usr/local/sbin:/usr/sbin:$PATH PULL_LABS_CALLBACK_TOKEN=labtoken-callback python3 "$ROOT/tools/riscv_pull_worker.py" --api-url http://127.0.0.1:8001 --tuxrun-bin /home/hao/.local/bin/tuxrun --container-runtime docker --output-dir /tmp/official-loop-out --state-file /tmp/official-loop-state.json --poll-period 5 --max-timeout 1200
else
  echo 'next step (manual):'
  echo "  PULL_LABS_CALLBACK_TOKEN=labtoken-callback python3 $ROOT/tools/riscv_pull_worker.py --api-url http://127.0.0.1:8001 --tuxrun-bin /home/hao/.local/bin/tuxrun --container-runtime docker --poll-period 5"
fi
