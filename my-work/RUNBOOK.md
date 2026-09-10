# RUNBOOK — 复现指南(两档)

> 目标:任何人拿到这个仓库,按档位 A 或 B 跑,能得到与本仓库文档口径一致的结果。
> ⚠️ 口径(2026-09-09):早期文档中的「QEMU 11.1.1、9/9 全绿、6s/27s/167s、ssnpm 全绿」
> **无原始日志支撑**;以下以本文件实测口径为准(宿主 QEMU 8.2.0 有 rvv bug,tuxrun 容器 QEMU
> 11.0.2,riscv collection 10 项 9 ok / 1 not ok)。

## 档位 A:复现"测试结果"(0 个上游仓库,2 条命令)

只需:tuxrun(装一次:`pip install tuxrun`)+ docker + 打一次 tuxlava 补丁。
补丁在 `my-work/tools/lab/tuxlava-kselftest-riscv.patch`(lab 工具目录:
worker / config_drift.py / regression_tracker.py / regression-tracking.md 同处)。
不装 KernelCI 任何东西,不要 token,不要节点。

```bash
git clone <本仓库>
cd <本仓库>
python3 my-work/tools/fetch-and-run-latest.py            # riscv collection,自动抓生产最新构建
python3 my-work/tools/fetch-and-run-latest.py --test kselftest-kvm   # kvm 精选子集
```

实测输出(2026-09-09,生产最新构建 = `kbuild-gcc-14-riscv` 节点
`6aa0b795e41d7f97d618c887`,kernel `v7.3-rc1-474-g548b86839f7f`;本地复跑,`ssnpm=true`):

- riscv collection:**10 项 → 9 ok / 1 not ok**;not ok = `pointer_masking` 的
  PMLEN constraint 子项(TCG 模拟限制)。
- v6.18 对照:**7 ok / 1 not ok**(`pointer_masking` 51/61 SKIP)。
- baseline PoC:节点 `6a9fb8bfdb925f2f584f0771`、`6aa11653fa416dea4a15a0bf`
  均 done/pass;防假绿节点 `6aa114ef…`(incomplete + Infrastructure)。
- 配置漂移:6.18 同 commit 两次构建 **5412 项 0 漂移**;6.18 vs 7.3-rc1 =
  **+274/−103/41**(总 5583 项)。

产出与原始日志自动存 `my-work/evidence/latest-runs/<node_id>/`。

## 档位 B:复现"完整闭环"(3 个上游仓库,4 条命令)

前提:docker。步骤:

```bash
bash my-work/tools/setup-repro.sh        # 克隆 core/api/pipeline + 打 PR1 配置补丁 + validate_yaml
bash my-work/tools/run-local-stack.sh --seed   # 起 API/回调/官方调度器,并触发派单
# 另开终端:worker 接单(命令 run-local-stack.sh 会打印)
curl -s 'http://127.0.0.1:8001/latest/nodes?kind=job&name=baseline-riscv-pull-labs&limit=3'  # 看结果
```

说明:
- 闭环=官方调度器读我们的 **4 个 YAML(63 行;pyproject 的 C901 行已随 worker 移出撤销,
  随 worker PR 再带)** → 自动渲染任务书
  (`pull_labs_jobs/<日期>/<uuid>.json`)-> 自动建节点 → worker 接单 → tuxrun/QEMU 跑 →
  LAVA body 回传真实 lava_callback → 节点 done/pass。
- lab 工具现役路径:`my-work/tools/lab/` —— riscv_pull_worker.py、tuxlava 补丁、
  config_drift.py、regression_tracker.py、regression-tracking.md(5 个文件,均不属 PR1)。
- KCI_API_TOKEN:本地 API 的 admin JWT,按 kernelci-api 官方 local-instance 文档建号后填入
  `kernelci-pipeline/.env`;该文件已被 .gitignore 排除,永不提交。
- 网络依赖:构件来自 files.kernelci.org(公开),rootfs 来自 storage.kernelci.org(公开)。

## 验证套件(每次改动后跑一遍)

```bash
(cd kernelci-pipeline && python3 tests/validate_yaml.py)   # 配置门禁
python3 my-work/tools/verify-lava-body.py                        # 生产解析器契约
python3 my-work/tools/verify-worker-guards.py                    # 防假绿守卫
# drift / trend 是 GET(本地或生产均可,无需 token);track/watch 仅本地 API + token
KCI_API_URL=http://127.0.0.1:8001 python3 my-work/tools/lab/config_drift.py --json --job kbuild-gcc-14-riscv
KCI_API_URL=http://127.0.0.1:8001 python3 my-work/tools/lab/regression_tracker.py trend
```

## 已知限制(诚实清单)

- `pointer_masking` 的 PMLEN constraint 子项在 TCG 下 not ok(QEMU 模拟限制,
  真机行为可能不同;K3 真机已归档,无法复验);
- 宿主 QEMU(`~/qemu-install`)= 8.2.0,有 rvv bug(vstate 相关),`ssnpm` 需 QEMU ≥ 9.1;
  tuxrun dispatcher 容器 QEMU = 11.0.2,是档位 A/worker 的实际执行路径。早期「11.1.1
  已实测、9/9 全绿」无原始日志;
- kvm 集合用 TST_CASENAME 白名单 9 项(perf/stress 在 TCG 下无意义;早期 7 ok/2 skip 无日志);
- 网络抖动会截断 144MB rootfs 下载 → worker 如实报 Infrastructure(Content-Length 校验),重跑即可;
- Debian bullseye 已归档(官方问题):setup-repro.sh 会自动给 kernelci-api 打
  `my-work/config/kernelci-api-bullseye-archive.patch`,否则 ssh 容器 build 会失败。
