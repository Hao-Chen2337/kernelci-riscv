# kernelci-riscv

RISC-V KernelCI automation — implementing the KernelCI Statement of Work from
[riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49).

Automated build and regression testing of the Linux kernel's `riscv` selftests
on QEMU emulation and SpacemiT K3 real hardware.

## Environments

| Environment | Description |
|---|---|
| QEMU 8.2 (`-cpu rv64,v=true`) | Software emulation on x86, for fast pipeline bring-up |
| SpacemiT K3 (X100, RVA23) | Real silicon with full Vector (RVV 1.0) and Hypervisor (RVH) |
| riscv64 Docker container | Reproducible toolchain + scripts |

## Results

### riscv selftests (v6.18)

```
passed: 7   failed: 1   skipped: 0
```

| Test | Result | Notes |
|---|---|---|
| hwprobe / cbo / which-cpus / run_mmap / sigreturn / v_initval / vstate_prctl | ✅ pass | |
| pointer_masking | ⏭️ not ok (expected) | X100 lacks Zpm; test reports honestly |

**Key finding**: Vector tests (`vector_restore`, `vstate_prctl`) crash or skip on
QEMU due to emulator limitations, but genuinely pass on K3 real hardware.

### KVM selftests (real hardware)

```
passed: 3   timeout/SKIP/drift: 17
```

- ✅ `set_memory_region_test`, `kvm_create_max_vcpus`, `kvm_binary_stats_test` → KVM can create and run VMs
- 📋 `get-reg-list` → version drift (kernel 6.18.3 newer than test's blessed list)
- ⏭️ `irqfd_test` → SKIP (riscv64 has no default irqchip, expected)
- ⏱️ perf/stress tests → timeout (riscv64 KVM maturity gap)

**Conclusion**: K3's Hypervisor is functional (core tests pass); advanced
features are still immature on riscv64 — an observation unique to this project
(the reference K1 board lacks the H extension and cannot run KVM at all).

## Usage

### Real hardware / container

```bash
./run-tests.sh                            # bare-metal
docker build -t riscv-selftests .         # containerized
docker run --rm -v ~/kci:/root/kci riscv-selftests
```

### Config drift check

```bash
bash config-drift-check.sh
```

### KVM selftests (requires H extension + /dev/kvm)

```bash
sudo bash run-kvm-tests.sh
```

## Files

| File | Purpose |
|---|---|
| `run-tests.sh` | Core: download kernel → build selftests → run → write trend table |
| `config-drift-check.sh` | Detect config drift (required kernel options) |
| `run-kvm-tests.sh` | KVM selftests (real-hardware Hypervisor) |
| `Dockerfile` | riscv64 test container image |
| `.github/workflows/ci.yml` | CI (self-hosted runner) |

## Progress

- [x] Phase 1: validation script runs
- [x] Phase 1: containerized pipeline
- [ ] Phase 1: tracking issue (kernelci-project)
- [x] Phase 2: regression trend table
- [x] Phase 2: config drift detection
- [x] Phase 2: KVM real-hardware test
- [ ] Phase 2: build matrix (GCC/Clang)
- [ ] Phase 2: self-hosted runner CI (workflow ready, not deployed)
