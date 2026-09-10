#!/usr/bin/env bash
# kernelci-riscv 一键入口:部署 → 运行 → 看结果
# 用法: ./run.sh <子命令> [参数];./run.sh help 看全部
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIPE="$ROOT/kernelci-pipeline"
TUXRUN_BIN="${TUXRUN_BIN:-$(command -v tuxrun || echo /home/hao/.local/bin/tuxrun)}"
CALLBACK_TOKEN="${PULL_LABS_CALLBACK_TOKEN:-labtoken-callback}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

cmd_help() {
  sed -n '3,60p' "$ROOT/run.sh" | sed 's/^# \{0,1\}//' | grep -v '^!/' | head -50
  cat <<EOF
子命令:
  setup            一次性部署:克隆 3 个上游仓库 + 打 PR1/bullseye 补丁 + validate_yaml
  fetch [--kvm]    档位 A:抓生产最新 riscv 构建,tuxrun 本地复跑(--kvm = kvm 子集)
  stack [--seed]   起本地全栈:kernelci-api + 构件服务 + 真实回调 + 官方调度器(--seed 派单)
  worker           前台接单执行(先 stack --seed)
  report           看结果:最近 baseline/kselftest 节点状态
  verify           全套校验:validate_yaml + verify-lava-body + verify-worker-guards
  drift            配置漂移检测(对比最近两次生产 kbuild .config)
  trend            回归通过率趋势(本地/生产 pull-labs)
  stop             停本地全栈
参数(环境变量):TUXRUN_BIN、PULL_LABS_CALLBACK_TOKEN、KCI_API_URL
EOF
}

cmd_setup() {
  [ -d "$ROOT/kernelci-core" ] || git clone --depth 1 https://github.com/kernelci/kernelci-core
  [ -d "$ROOT/kernelci-api" ] || git clone --depth 1 https://github.com/kernelci/kernelci-api
  [ -d "$ROOT/kernelci-pipeline" ] || git clone --depth 1 https://github.com/kernelci/kernelci-pipeline
  # PR1 配置补丁
  git -C "$PIPE" apply "$ROOT/config/pr1-config.patch" 2>/dev/null || \
    git -C "$PIPE" apply --3way "$ROOT/config/pr1-config.patch" 2>/dev/null || \
    { echo "  PR1 补丁未应用(可能已打或上游变更);当前状态:"; git -C "$PIPE" status --short | head; }
  # bullseye 归档源补丁
  if grep -q archive.debian.org "$ROOT/kernelci-api/docker/ssh/Dockerfile" 2>/dev/null; then
    ok "bullseye 补丁已存在"
  else
    git -C "$ROOT/kernelci-api" apply "$ROOT/config/kernelci-api-bullseye-archive.patch" \
      && ok "bullseye 补丁已应用" || echo "  !! bullseye 补丁应用失败,ssh 容器 build 可能失败"
  fi
  # tuxlava 补丁提示
  TUXLAVA_DIR="$(python3 -c 'import tuxlava,os;print(os.path.dirname(tuxlava.__file__))' 2>/dev/null || true)"
  if [ -n "$TUXLAVA_DIR" ] && grep -q "KselftestRiscv\|kselftest-riscv" "$TUXLAVA_DIR/tests/kselftest.py" 2>/dev/null; then
    ok "tuxlava 补丁已打"
  else
    echo "  !! tuxlava 补丁未打:cd ~/.local/lib/python3.10/site-packages && patch -p1 < $ROOT/config/tuxlava-kselftest-riscv.patch"
  fi
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml 失败"
  [ -f "$PIPE/.env" ] || cat > "$PIPE/.env" <<'EOF'
KCI_API_TOKEN=请填入本地 kernelci-api admin JWT(见 kernelci-api local-instance 建号流程)
NO_DOCKER_PULL=1
KCI_TREES=riscv
EOF
  ok "setup 完成;档位 B 还需在 kernelci-pipeline/.env 填 KCI_API_TOKEN"
}

cmd_fetch() {
  local extra=""
  [ "${1:-}" = "--kvm" ] && extra="--test kselftest-kvm"
  # 本机 127.0.0.1:7890 代理若已失效会拒绝连接;生产 API/构件直连可用,先摘掉代理
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null || true
  # shellcheck disable=SC2086
  TUXRUN_BIN="$TUXRUN_BIN" python3 "$ROOT/tools/fetch-and-run-latest.py" $extra
}

cmd_stack() {
  if [ "${1:-}" = "--seed" ]; then
    bash "$ROOT/tools/run-local-stack.sh" --seed
  else
    bash "$ROOT/tools/run-local-stack.sh"
  fi
}

cmd_worker() {
  # --since: 默认只处理今天的新单,避免重放 09-08 手工伪造任务书时代的历史 available 事件
  local since="${SINCE:-2026-09-10T00:00:00}"
  # 生产构件直连;本机 127.0.0.1:7890 代理失效时会挂死下载,先摘掉
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null || true
  PYTHONUNBUFFERED=1 PULL_LABS_CALLBACK_TOKEN="$CALLBACK_TOKEN" python3 "$ROOT/tools/riscv_pull_worker.py" \
    --api-url http://127.0.0.1:8001 --tuxrun-bin "$TUXRUN_BIN" \
    --container-runtime docker --output-dir /tmp/official-loop-out \
    --state-file /tmp/official-loop-state.json --poll-period 5 --max-timeout 1200 \
    --since "$since"
}

cmd_report() {
  echo "--- baseline-riscv-pull-labs ---"
  curl -s "http://127.0.0.1:8001/latest/nodes?kind=job&name=baseline-riscv-pull-labs&limit=3" \
    | python3 -c 'import json,sys
d=json.load(sys.stdin)
for n in d.get("items",[]):
    r=(n.get("data") or {}).get("kernel_revision") or {}
    print(f"{n[\"id\"][:16]}  {n.get(\"state\"):12} {n.get(\"result\") or \"-\":14} {r.get(\"describe\",\"?\")[:30]}")'
  echo "--- kselftest-riscv-pull-labs ---"
  curl -s "http://127.0.0.1:8001/latest/nodes?kind=job&name=kselftest-riscv-pull-labs&limit=3" \
    | python3 -c 'import json,sys
d=json.load(sys.stdin)
for n in d.get("items",[]):
    r=(n.get("data") or {}).get("kernel_revision") or {}
    print(f"{n[\"id\"][:16]}  {n.get(\"state\"):12} {n.get(\"result\") or \"-\":14} {r.get(\"describe\",\"?\")[:30]}")'
}

cmd_verify() {
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml 失败"
  python3 "$ROOT/tools/verify-lava-body.py" | tail -1
  python3 "$ROOT/tools/verify-worker-guards.py" | tail -1
  (cd "$PIPE" && ruff check . 2>/dev/null | tail -1) || true
}

cmd_drift() {
  KCI_API_URL="${KCI_API_URL:-http://127.0.0.1:8001}" python3 "$ROOT/tools/config_drift.py" --json --job kbuild-gcc-14-riscv
}

cmd_trend() {
  KCI_API_URL="${KCI_API_URL:-http://127.0.0.1:8001}" python3 "$ROOT/tools/regression_tracker.py" trend
}

cmd_stop() {
  pkill -f "scheduler.py.*pull-labs-riscv" 2>/dev/null && echo "scheduler stopped"
  pkill -f "uvicorn lava_callback" 2>/dev/null && echo "callback stopped"
  pkill -f "http.server 8999" 2>/dev/null && echo "artifact server stopped"
}

case "${1:-help}" in
  setup)  cmd_setup ;;
  fetch)  cmd_fetch "${2:-}" ;;
  stack)  cmd_stack "${2:-}" ;;
  worker) cmd_worker ;;
  report) cmd_report ;;
  verify) cmd_verify ;;
  drift)  cmd_drift ;;
  trend)  cmd_trend ;;
  stop)   cmd_stop ;;
  help|*) cmd_help ;;
esac
