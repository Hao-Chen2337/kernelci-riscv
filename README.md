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
| Local full-stack loop (seed → scheduler → worker → real callback) | baseline **pass** · kselftest-kvm **pass** (8-test whitelist, 14 cases pass / 2 skip) · kselftest-riscv **fail** (9 of its 10 test programs pass, `pointer_masking` fails: 98 cases pass / 7 skip / 17 fail, and all 17 failures are inside that one program - QEMU TCG has no pointer-masking semantics), reported honestly; every run is recorded in `work/results/` (program level) and read back with `./run.sh results` |
| Config drift + regression trend tooling | drift: two builds of one commit, 5412 options, 0 drift (re-checked 2026-09-17); trend reads the production history back correctly — `baseline-arm64-pull-labs-demo` 5673 pass / 429 fail (281 regressions), `kselftest-arm64-pull-labs` 2075 pass / 175 fail, both measured 2026-09-17 |

## Repository

| Path | Contents |
|---|---|
| `docs/RUNBOOK.md` | Run commands and operating notes |
| `scripts/` | All code: worker, drift, trend, fetch, results, verify, stack |
| `config/` | PR1 config patch + tuxlava/bullseye/nginx patches |
| `kernelci-*/` | Upstream clones (gitignored, created by `./run.sh setup`) |
| `work/` | Runtime workspace (gitignored, regenerable) |
