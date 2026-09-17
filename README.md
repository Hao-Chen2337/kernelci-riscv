# kernelci-riscv

RISC-V KernelCI automation for the SOW in
[riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49):
continuous regression testing of the Linux riscv Vector/Hypervisor
extensions on QEMU, with the test profile submitted upstream to kernelci-pipeline.

**How to run it:** see [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Status (2026-09-17)

An honest status, not a completion claim: the local pipeline runs end-to-end;
the riscv regression history is just starting to accumulate.

| Area | State |
|---|---|
| PR1 test profile (4 YAMLs, 49 insertions, one commit) | ready — validate_yaml green; the official scheduler renders 3 job definitions from it, and the config was run end-to-end on the local stack |
| Local full-stack loop (seed → scheduler → worker → real callback) | baseline **pass** · kselftest-kvm **pass** (8-test subset: 6 pass / 2 skip) · kselftest-riscv **fail** (9 pass / 1 fail, reported honestly); every run is recorded in `work/results/` and read back with `./run.sh results` |
| Config drift + regression trend tooling | drift: two builds of one commit, 5412 options, 0 drift; trend proven on production arm64 data (2303 entries) |
| Upstream steps | #49 progress reply posted 2026-09-10 (per the local notes, not re-verified); PR1 open as [kernelci-pipeline#1599](https://github.com/kernelci/kernelci-pipeline/pull/1599) (rebased on `main` after [kernelci-pipeline#1600](https://github.com/kernelci/kernelci-pipeline/pull/1600) landed, duplicate kvm job dropped, squashed to one commit; waiting on the reviewer); the riscv kselftest support it needs is [kernelci/tuxlava#50](https://github.com/kernelci/tuxlava/pull/50) (**merged** 2026-09-16); the tracking issue opened as [kernelci/kernelci-project#585](https://github.com/kernelci/kernelci-project/issues/585) (also per the local notes, not re-verified) |

Known environment limits (reported honestly, not kernel regressions):
pointer_masking fails at PMLEN=16 under QEMU TCG; irqfd_test and
sbi_pmu_test skip under TCG; kvm_page_table_test is out of the default
subset (hangs under TCG).

## Repository

| Path | Contents |
|---|---|
| `docs/RUNBOOK.md` | Run commands and operating notes |
| `scripts/` | All code: worker, drift, trend, fetch, results, verify, stack |
| `code-notes/` | Engineering notes: the reasoning behind the code, one file per area |
| `config/` | PR1 config patch + tuxlava/bullseye/nginx patches |
| `kernelci-*/` | Upstream clones (gitignored, created by `./run.sh setup`) |
| `work/` | Runtime workspace (gitignored, regenerable) |
