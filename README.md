# kernelci-riscv

RISC-V KernelCI 自动化测试 —— 对应 [riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49) 的 KernelCI Statement of Work。

在 QEMU 模拟器和 SpacemiT K3 真机上，对 Linux 内核的 `riscv` selftests 做自动化构建与回归测试。

## 环境

| 环境 | 说明 |
|---|---|
| QEMU 8.2 (`-cpu rv64,v=true`) | x86 主机上的软件模拟，跑通流程用 |
| SpacemiT K3 真机 (X100, RVA23) | 真实硅片，带完整 Vector (RVV 1.0) 和 Hypervisor (RVH) 扩展 |
| riscv64 Docker 容器 | 封装工具链与脚本，保证可复现 |

## 测试结果 (v6.18, riscv selftests)

```
通过(ok): 7  失败(not ok): 1  跳过(skip): 0
```

| 测试 | 结果 | 说明 |
|---|---|---|
| hwprobe / cbo / which-cpus / run_mmap / sigreturn / v_initval / vstate_prctl | ✅ 通过 | |
| pointer_masking | ⏭️ not ok（预期） | K3 的 X100 无 Zpm 扩展，测试如实跳过 |

**关键差异**：`vector_restore`、`vstate_prctl` 等 Vector 测试在 QEMU 上因模拟器限制 SIGILL 崩溃或 SKIP，在 K3 真机上全部真正执行并通过。

## 用法

### 1. 真机 / 容器

```bash
# 裸机直接跑
./run-tests.sh

# 容器化（riscv64 镜像）
docker build -t riscv-selftests .
docker run --rm -v ~/kci:/root/kci riscv-selftests
```

### 2. QEMU 虚拟机

```bash
bash boot-riscv-vm.sh          # 启动 riscv64 虚拟机
ssh -p 2222 root@localhost     # 密码 riscv
```

### 3. 连 K3 真机（走 stunnel 隧道）

```bash
bash k3-tunnel.sh              # 建隧道
ssh -p 2223 bianbu@localhost   # 连 K3
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `run-tests.sh` | 核心：下载内核 → 编译 selftests → 跑 → 统计结果 → 写回归趋势表 |
| `config-drift-check.sh` | 配置漂移检测：检查内核 config 必需项 |
| `run-kvm-tests.sh` | KVM selftests（真机 H 扩展 + /dev/kvm） |
| `Dockerfile` | riscv64 测试容器镜像 |
| `.github/workflows/ci.yml` | CI：自托管 runner 自动跑测试 |
| `boot-riscv-vm.sh` | 在 WSL 上启动 riscv64 QEMU 虚拟机 |
| `k3-tunnel.sh` | 建立到 K3 真机的 stunnel 隧道 |
| `build-qemu.sh` | 源码编译 QEMU 8.2（支持 vector） |
| `reset-vm-password.sh` | 重置虚拟机镜像密码 |

## 进度

- [x] Phase 1: 验证脚本跑通
- [x] Phase 1: 容器化测试管线
- [ ] Phase 1: tracking issue（kernelci-project）
- [x] Phase 2: 回归趋势表脚本（待真机验证）
- [x] Phase 2: 配置漂移检测脚本
- [ ] Phase 2: KVM 真机测试（脚本已就绪，待跑）
- [ ] Phase 2: 编译矩阵（GCC/Clang）
- [ ] Phase 2: 自托管 runner CI（workflow 已就绪，待部署）
