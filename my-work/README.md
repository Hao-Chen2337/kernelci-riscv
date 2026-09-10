# kernelci-riscv

RISC-V KernelCI automation — implementing the KernelCI Statement of Work from
[riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49).

Automated build and regression testing of the Linux kernel's `riscv` selftests
via tuxrun/QEMU and a local KernelCI pull-lab stack. The SpacemiT K3
real-hardware track is **archived (the board is no longer available)**; its
section below is kept only as a historical record.

> ⚠️ **口径说明 (2026-09-09)**: 早期版本中 "QEMU 11.1.1 + `ssnpm=true` → 9/9 全绿"
> 与 "6 s / 27 s / 167 s" 等表述**无原始日志支撑**,一律不采信;可复现的实测口径见
> [RUNBOOK.md](./RUNBOOK.md) 与本文件 Results 节(宿主 QEMU 8.2.0 有 TCG rvv bug,
> 实际执行走 tuxrun 容器 QEMU 11.0.2;riscv collection 10 项为 9 ok / 1 not ok)。

## Environments

| Environment | Description |
|---|---|
| tuxrun dispatcher (container QEMU **11.0.2**) | Actual execution path for RUNBOOK level-A reruns and the pull-lab worker |
| Host QEMU (`~/qemu-install`, **8.2.0**) | Has the TCG rvv bug (vstate crashes); `ssnpm` needs QEMU ≥ 9.1. The earlier "11.1.1 verified" claim has no original logs |
| riscv64 Docker container | Reproducible toolchain + scripts (Phase-1 legacy, see archive below) |
| SpacemiT K3 (X100, RVA23) | 🗄️ 历史归档 — 真机已不在;下方 KVM/真机内容仅供历史参考 |

## Results (verified, 2026-09-09)

### Latest production build

- Job `kbuild-gcc-14-riscv`, node **`6aa0b795e41d7f97d618c887`**
- Kernel **v7.3-rc1-474-g548b86839f7f** (2026-09-09)
- Public artifacts:
  `https://files.kernelci.org/kbuild-gcc-14-riscv-6aa0b795e41d7f97d618c887/`
  (`Image.gz` · `kselftest.tar.xz` · `modules.tar.xz` · `.config`)

### riscv kselftest collection (local re-run, RUNBOOK-verified)

| Kernel | Result |
|---|---|
| v7.3-rc1 (`ssnpm=true`) | **10 items → 9 ok / 1 not ok**; the not-ok is `pointer_masking` (its **PMLEN constraint subitem**, a TCG emulation limitation) |
| v6.18 (reference) | **7 ok / 1 not ok** (`pointer_masking`: 51/61 subtests SKIP) |

### Baseline PoC nodes (local KernelCI stack)

| Node | Result | Note |
|---|---|---|
| `6a9fb8bfdb925f2f584f0771` | done / pass | baseline PoC |
| `6aa11653fa416dea4a15a0bf` | done / pass | replay run |
| `6aa114ef…` | incomplete + Infrastructure | anti-false-green node (failure honestly reported) |

### Config drift

- Same kernel commit built twice on 6.18: **5412 items, 0 drift**.
- 6.18 vs 7.3-rc1: **+274 / −103 / 41 changed** (total 5583 items).

> ⚠️ The earlier note "Vector tests pass on QEMU 11.1.1 and on K3; with
> `ssnpm=true` the whole collection is 9/9 green" is **not backed by original
> logs** and has been removed. The reproducible claim is the one in the table
> above.

## KVM selftests — 🗄️ 历史归档 (real hardware, SpacemiT K3)

> 真机已不在。以下为 2026-08-27 K3 (X100) 真机记录,仅存档;早期
> "QEMU 上 7 ok / 2 skip / ~150–167 s" 的说法无原始日志,不作为当前口径。

```
passed: 3   timeout/SKIP/drift: 17
```

- ✅ `set_memory_region_test`, `kvm_create_max_vcpus`, `kvm_binary_stats_test` → KVM can create and run VMs
- 📋 `get-reg-list` → version drift (kernel 6.18.3 newer than the test's blessed list)
- ⏭️ `irqfd_test` → SKIP (riscv64 has no default irqchip, expected)
- ⏱️ perf/stress tests → timeout (riscv64 KVM maturity gap)

**Historical conclusion (archive only)**: K3's Hypervisor was functional (core
tests passed); advanced features were still immature on riscv64.

## Usage

Entry point is [RUNBOOK.md](./RUNBOOK.md):

- **Level A** (0 upstream repos, tuxrun only):
  `python3 my-work/tools/fetch-and-run-latest.py` (riscv collection) /
  `--test kselftest-kvm` (curated KVM subset).
- **Level B** (full local KernelCI loop, 3 upstream repos):
  `my-work/tools/setup-repro.sh` → `my-work/tools/run-local-stack.sh --seed`.

Legacy Phase-1 scripts (`run-tests.sh`, `run-kvm-tests.sh`,
`config-drift-check.sh`, `Dockerfile`, `.dockerignore`, `.github/`, `docs/`)
are kept under `my-work/archive/k3-era/` as archive only — they target the
retired K3/self-hosted layout and are not the current entry points.

## Files

| Path | Purpose |
|---|---|
| `my-work/RUNBOOK.md` | 复现指南(档位 A/B),当前实测口径的唯一入口 |
| `my-work/docs/` | 全部文档:交接研究 00–10、SOW 总结与原文、文件账本 |
| `my-work/tools/` | 现役复现/闭环工具 + 校验脚本 + `lab/`(worker 等,清单见 `tools/README.md`) |
| `my-work/config/` | 全部补丁与本地配置:pr1-config.patch、kernelci-api-bullseye-archive.patch、cb-config、local-callback.toml |
| `my-work/evidence/` | 全部证据与产物:upstream-evidence(23 JSON + verify-report)、run-logs、worker-out(14GB,gitignore)、latest-runs |
| `my-work/archive/` | 归档:旧 V1 补丁、k3-era(K3 真机全套,含 trend 证据) |
| `kernelci-pipeline/config/*-pull-labs.yaml`(+platforms) | PR1 交付配置(4 个 YAML,63 行;pyproject 的 C901 行已随 worker 移出而撤销),见 SOW 总结 |

## Progress

- [x] Phase 1: validation script runs
- [x] Phase 1: containerized pipeline
- [ ] Phase 1: tracking issue (kernelci-project) — 仍待办
- [x] Phase 2: regression trend table (K3, archived)
- [x] Phase 2: config drift detection
- [x] Phase 2: KVM real-hardware test (archived, board gone)
- [ ] Phase 2: build matrix (GCC/Clang)
- [ ] Phase 2: self-hosted runner CI (workflow retired with the board)
- [ ] Phase 3: upstream PR — 4 个 YAML 63 行 validate_yaml 通过,未提交(pyproject C901 行已随 worker 移出撤销,随 worker PR 再带)
