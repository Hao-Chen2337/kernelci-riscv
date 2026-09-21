# kernelci-riscv

RISC-V KernelCI automation for the SOW in
[riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49):
continuous regression testing of the Linux riscv Vector/Hypervisor extensions on QEMU,
with the test profile submitted upstream to kernelci-pipeline.

To run it, see **[docs/RUNBOOK.md](docs/RUNBOOK.md)**.

**Status.** The commands are the surface to rely on: they do the fetch, the run, the ledger
and the analysis, and `python3 verify.py` gates them. The web console (`gui.py`) is the newer
half and is still being polished, so expect rough edges there. It drives the same commands
and reads the same ledger, so an edge in the console does not change what the commands did.
