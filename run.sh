#!/usr/bin/env bash
# kernelci-riscv 一键入口:部署 → 运行 → 看结果
# 用法: ./run.sh <子命令> [参数];./run.sh help 看全部
# 详见 README.md 第 2 节。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIPE="$ROOT/kernelci-pipeline"
TUXRUN_BIN="${TUXRUN_BIN:-$(command -v tuxrun || echo /home/hao/.local/bin/tuxrun)}"
CALLBACK_TOKEN="${PULL_LABS_CALLBACK_TOKEN:-labtoken-callback}"
API_URL="${KCI_API_URL:-http://127.0.0.1:8001}"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }
no_proxy_setup() {
  # 本机 127.0.0.1:7890 代理已失效,生产 API/构件直连可用;带代理会挂死下载
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null || true
}

cmd_help() {
  cat <<EOF
子命令:
  setup            一次性部署:克隆 3 个上游仓库 + 打 PR1/bullseye 补丁 + validate_yaml
  fetch [--kvm] [--kvm-full] [--job 名]
                   档位 A:抓生产最新 riscv 构建,tuxrun 本地复跑(--kvm=kvm 9 项子集;--kvm-full=全集)
  stack [--seed]   起本地全栈:api/db/redis/storage/ssh + 构件服务 + 真实回调 + 官方调度器(--seed 派单)
  worker [--once]  接单执行回传(--once:处理完现存单就退;默认 --since 只接今天新单)
  report           看结果:最近 baseline/kselftest 节点状态
  verify           全套校验:validate_yaml + verify-lava-body + verify-worker-guards + ruff
  drift            配置漂移(相邻两次生产 kbuild .config 增删改;任意两版用脚本 --older/--newer)
  trend            回归通过率趋势(读 KCI_API_URL,本地=积累历史,生产=对比现状)
  stop             停本地全栈
参数(环境变量):TUXRUN_BIN、PULL_LABS_CALLBACK_TOKEN、KCI_API_URL、SINCE
EOF
}

cmd_setup() {
  [ -d "$ROOT/kernelci-core" ] || git clone --depth 1 https://github.com/kernelci/kernelci-core
  [ -d "$ROOT/kernelci-api" ] || git clone --depth 1 https://github.com/kernelci/kernelci-api
  [ -d "$ROOT/kernelci-pipeline" ] || git clone --depth 1 https://github.com/kernelci/kernelci-pipeline
  # PR1 配置补丁(已含则跳过:PR 合并前后同一条命令)
  if git -C "$PIPE" grep -q "qemu-riscv64" -- config/platforms.yaml 2>/dev/null; then
    ok "PR1 配置已在(pipeline 已含 riscv 平台,跳过补丁)"
  else
    git -C "$PIPE" apply "$ROOT/config/pr1-config.patch" 2>/dev/null || \
      git -C "$PIPE" apply --3way "$ROOT/config/pr1-config.patch" 2>/dev/null || \
      { echo "  PR1 补丁未应用(可能已打或上游变更);当前状态:"; git -C "$PIPE" status --short | head; }
  fi
  # bullseye 归档源补丁(官方 Debian 归档问题,本地 ssh 容器 build 必需)
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
  [ -f "$PIPE/.env" ] || cat > "$PIPE/.env" <<'EOF'
KCI_API_TOKEN=请填入本地 kernelci-api admin JWT(见 kernelci-api local-instance 建号流程)
NO_DOCKER_PULL=1
KCI_TREES=riscv
EOF
  # SOW Phase 1 验收条款:"First validation script successfully parsed locally"
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml 失败"
  ok "setup 完成;档位 B 还需在 kernelci-pipeline/.env 填 KCI_API_TOKEN"
}

cmd_fetch() {
  # --kvm 是 run.sh 的快捷方式;其余参数原样透传给脚本(--kvm-full/--job/--test)
  local args=()
  for a in "$@"; do
    if [ "$a" = "--kvm" ]; then
      args+=("--test" "kselftest-kvm")
    else
      args+=("$a")
    fi
  done
  no_proxy_setup
  TUXRUN_BIN="$TUXRUN_BIN" python3 "$ROOT/scripts/fetch-and-run-latest.py" "${args[@]}"
}

cmd_stack() {
  if [ "${1:-}" = "--seed" ]; then
    bash "$ROOT/scripts/run-local-stack.sh" --seed
  else
    bash "$ROOT/scripts/run-local-stack.sh"
  fi
}

cmd_worker() {
  local since="${SINCE:-$(date -u +%Y-%m-%d)T00:00:00}"
  local extra=()
  [ "${1:-}" = "--once" ] && extra=("--once")
  no_proxy_setup
  PYTHONUNBUFFERED=1 PULL_LABS_CALLBACK_TOKEN="$CALLBACK_TOKEN" \
    python3 "$ROOT/scripts/riscv_pull_worker.py" \
    --api-url "$API_URL" --tuxrun-bin "$TUXRUN_BIN" \
    --container-runtime docker --output-dir /tmp/official-loop-out \
    --state-file /tmp/official-loop-state.json --poll-period 5 --max-timeout 1200 \
    --since "$since" "${extra[@]}"
}

cmd_report() {
  for name in baseline-riscv-pull-labs kselftest-riscv-pull-labs; do
    echo "--- $name (newest 3) ---"
    curl -s "$API_URL/latest/nodes?kind=job&name=$name&limit=100" \
      | python3 -c '
import json, sys
d = json.load(sys.stdin)
items = sorted(d.get("items", []), key=lambda n: n.get("created") or "", reverse=True)
for n in items[:3]:
    r = (n.get("data") or {}).get("kernel_revision") or {}
    print("  {:16s} {:12s} {:14s} {} ({})".format(
        n["id"][:16], n.get("state") or "-", n.get("result") or "-",
        (r.get("describe") or "?")[:30], (n.get("created") or "")[:10]))'
  done
}

cmd_verify() {
  (cd "$PIPE" && python3 tests/validate_yaml.py) || die "validate_yaml 失败"
  python3 "$ROOT/scripts/verify-lava-body.py" | tail -1
  python3 "$ROOT/scripts/verify-worker-guards.py" | tail -1
  (cd "$PIPE" && ruff check . 2>/dev/null | tail -1) || true
}

cmd_drift() {
  no_proxy_setup
  KCI_API_URL="$API_URL" python3 "$ROOT/scripts/config_drift.py" --json --job kbuild-gcc-14-riscv
}

cmd_trend() {
  no_proxy_setup
  KCI_API_URL="$API_URL" python3 "$ROOT/scripts/regression_tracker.py" trend
}

cmd_stop() {
  pkill -f "scheduler.py.*pull-labs-riscv" 2>/dev/null && echo "scheduler stopped"
  pkill -f "uvicorn lava_callback" 2>/dev/null && echo "callback stopped"
  pkill -f "http.server 8999" 2>/dev/null && echo "artifact server stopped"
}

case "${1:-help}" in
  setup)  cmd_setup ;;
  fetch)  shift; cmd_fetch "$@" ;;
  stack)  cmd_stack "${2:-}" ;;
  worker) cmd_worker "${2:-}" ;;
  report) cmd_report ;;
  verify) cmd_verify ;;
  drift)  cmd_drift ;;
  trend)  cmd_trend ;;
  stop)   cmd_stop ;;
  help|*) cmd_help ;;
esac
