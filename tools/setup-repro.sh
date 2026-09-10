#!/usr/bin/env bash
# 档位 B 复现:克隆最少的 3 个上游仓库 + 打上 PR1 配置补丁 + 起本地全栈
# 前置:docker 可用;网络可访问 github.com
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo '== 1/4 克隆上游仓库(depth=1,只需 3 个;frontend/project 不需要)=='
for repo in kernelci-core kernelci-api kernelci-pipeline; do
  [ -d "$repo" ] && { echo "  已存在: $repo"; continue; }
  git clone --depth 1 "https://github.com/kernelci/$repo" || exit 1
done

echo '== 2/4 应用 PR1 配置补丁(4 个 YAML,63 行)=='
git -C kernelci-pipeline apply "$ROOT/config/pr1-config.patch" || \
  git -C kernelci-pipeline apply --3way "$ROOT/config/pr1-config.patch" || \
  { echo "补丁失败:请检查 kernelci-pipeline 版本"; exit 1; }
echo "   已打补丁:"; git -C kernelci-pipeline status --short | head -8

echo '== 2b/4 应用 kernelci-api ssh 容器 bullseye 归档源补丁(官方 Debian 归档问题,本地 build 必需)=='
if grep -q 'archive.debian.org' kernelci-api/docker/ssh/Dockerfile 2>/dev/null; then
  echo "   已含修复,跳过"
else
  git -C kernelci-api apply "$ROOT/config/kernelci-api-bullseye-archive.patch" \
    && echo "   已应用" || echo "   !! 应用失败(可能上游已修复),如 ssh 容器 build 失败请人工核对"
fi

echo '== 3/4 验证配置(上游官方门禁)=='
(cd kernelci-pipeline && python3 tests/validate_yaml.py) || exit 1

echo '== 4/4 生成 pipeline/.env(KCI_API_TOKEN 等)=='
if [ ! -f kernelci-pipeline/.env ]; then
  cat > kernelci-pipeline/.env <<EOF
KCI_API_TOKEN=请填入你本地 kernelci-api 的 admin JWT(见 kernelci-api 的 local-instance 建号流程)
NO_DOCKER_PULL=1
KCI_TREES=riscv
EOF
  echo "   已生成 .env 模板;KCI_API_TOKEN 需按 kernelci-api 官方 local-instance 文档创建 admin 后填入"
else
  echo "   kernelci-pipeline/.env 已存在,跳过"
fi

echo
echo '完成。下一步:'
echo '  bash tools/run-local-stack.sh --seed   # 起 API+回调+官方调度器并派单'
echo '  # 然后在另一个终端跑 worker 接单(见 run-local-stack.sh 输出的命令)'
