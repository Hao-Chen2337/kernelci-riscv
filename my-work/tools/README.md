# kernelci-tools —— 工具清单(my-work/tools)

> 路径规则:下面命令都从仓库根 `/home/hao/kernelci-riscv` 跑;归档/旧工具在
> `my-work/archive/k3-era/`,lab 执行工具在 `my-work/tools/lab/`。

## 现役(RUNBOOK 引用)

| 文件 | 用途 | 用法(仓库根) |
|---|---|---|
| `fetch-and-run-latest.py` | 档位 A:抓生产最新 `kbuild-gcc-14-riscv` 构件,tuxrun 本地跑 riscv / kvm 精选子集,产出存 `my-work/evidence/latest-runs/` | `python3 my-work/tools/fetch-and-run-latest.py`(加 `--test kselftest-kvm` 跑 kvm) |
| `setup-repro.sh` | 档位 B:克隆 core/api/pipeline + 打 PR1 补丁(4 YAML/63 行)+ 打 bullseye 归档源补丁 + validate_yaml | `bash my-work/tools/setup-repro.sh` |
| `run-local-stack.sh` | 档位 B:起本地 API/构件服务/真实 lava_callback/官方调度器;`--seed` 派单;`--worker` 前台接单 | `bash my-work/tools/run-local-stack.sh --seed` |
| `verify-lava-body.py` | lava 契约校验(喂生产 Callback 解析器) | `python3 my-work/tools/verify-lava-body.py` |
| `verify-worker-guards.py` | worker 防假绿守卫对抗测试 | `python3 my-work/tools/verify-worker-guards.py` |
| `callback-catcher.py` | 本地回调抓包(调试用,绑 9999) | `python3 my-work/tools/callback-catcher.py` |

## lab 执行工具(`my-work/tools/lab/`)

| 文件 | 用途 | 用法(仓库根) |
|---|---|---|
| `riscv_pull_worker.py` | 现役 lab worker(tuxrun 引擎,PR2 候选);接单命令由 run-local-stack.sh 输出 | 见 `run-local-stack.sh --worker` |
| `tuxlava-kselftest-riscv.patch` | tuxrun kselftest-riscv 补丁(档位 A 需要) | 见 RUNBOOK 档位 A |
| `config_drift.py` | kbuild `.config` 漂移检测(GET,本地/生产均可,无 token 即可跑) | `KCI_API_URL=http://127.0.0.1:8001 python3 my-work/tools/lab/config_drift.py --json --job kbuild-gcc-14-riscv`;生产:`KCI_API_URL=https://api.kernelci.org python3 …` |
| `regression_tracker.py` | 回归趋势 `trend`(GET)+ `track`/`watch`(POST,仅本地 API+token) | 用法见 `my-work/tools/lab/regression-tracking.md` |
| `regression-tracking.md` | config_drift / regression_tracker 用法与本地/生产可用性 | — |

## 归档(`my-work/archive/k3-era/`,旧 K3/真机/容器阶段,保留备查)

| 文件 | 说明 |
|---|---|
| `boot-riscv-vm.sh` | 旧 WSL riscv64 Debian VM 启动脚本(历史) |
| `build-qemu.sh` | 旧 QEMU 源码构建脚本;头部默认 11.1.1,其“实测”无原始日志,当前执行路径以 tuxrun 容器 QEMU 11.0.2 为准 |
| `k3-tunnel.sh` | K3 真机 stunnel 隧道脚本(真机已不在) |
| `reset-vm-password.sh` | 旧 riscv64 VM 密码重置脚本(历史) |
| `riscv_pull_worker_qemu-779.py` | worker 旧版存档快照(qemu-779 版,本地对照,不直接运行) |
| `RISC-V-KernelCI-实战经验总结.md` | 实战经验/踩坑记录(含 11.1.1 等早期表述,参阅时以 RUNBOOK 口径为准) |
| `run-tests.sh` · `run-kvm-tests.sh` · `config-drift-check.sh` · `Dockerfile` · `.dockerignore` · `.github/` · `docs/` | Phase-1 K3/容器/自托管 CI 阶段的脚本与证据(真机已不在,全部只存档不运行) |

## 仓库根归档

- `my-work/archive/riscv-test-profile.patch`:旧 V1 测试 profile 补丁(已被 PR1 4-YAML 配置取代)。

## 实战经验

见 `my-work/archive/k3-era/RISC-V-KernelCI-实战经验总结.md`:14 个踩坑记录 + 完整技术路线 + 环境速查(历史口径以 RUNBOOK 为准)。
