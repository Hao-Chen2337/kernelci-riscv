# kernelci-riscv

RISC-V KernelCI automation for the SOW in
[riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49):
continuous regression testing of the Linux riscv Vector/Hypervisor
extensions on QEMU, with the test profile upstreamed into kernelci-pipeline.

**How to run it:** [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Status (2026-09-10)

An honest status, not a completion claim: the pipeline runs end-to-end
locally; the riscv regression history itself is just starting to accumulate.

| Area | State |
|---|---|
| PR1 test profile (4 YAMLs, 63 lines) | ready — validate_yaml green; the official scheduler renders 3 job definitions from it |
| Local full-stack loop (seed → scheduler → worker → real callback) | baseline **pass** · kselftest-kvm **pass** (curated 8-test subset: 6 pass / 2 skip) · kselftest-riscv **fail** (9 pass / 1 fail, reported honestly) |
| Config drift + regression trend tooling | drift: two builds of one commit, 5412 options, 0 drift; trend proven on production arm64 (2303 entries) |
| Upstream steps | #49 reply, tracking issue, PR1 — drafts ready, not sent yet (SOW red line 2026-09-14) |

Known environment limits (reported honestly, not kernel regressions):
`pointer_masking` bails at PMLEN=16 under QEMU TCG; `irqfd_test` and
`sbi_pmu_test` skip under TCG; `kvm_page_table_test` is excluded from the
default subset (hangs under TCG).

## Repository

| Path | Contents |
|---|---|
| `docs/RUNBOOK.md` | Run commands and operating notes — the only public doc besides this file |
| `scripts/` | All code: worker, drift, trend, fetch, verify, stack |
| `config/` | PR1 config patch + tuxlava/bullseye/nginx patches |
| `kernelci-*/` | Upstream clones (gitignored, created by `./run.sh setup`) |
| `work/` | Runtime workspace (gitignored, regenerable) |

Everything else under `docs/` (tool deep dives, SOW snapshot, evidence,
issue/PR drafts, dev notes) is gitignored as internal working material.
