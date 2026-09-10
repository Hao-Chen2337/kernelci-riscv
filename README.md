# kernelci-riscv

RISC-V KernelCI automation — implementing the KernelCI Statement of Work
([riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49)):
automated regression testing of the Linux `riscv` selftests (Vector/Hypervisor) on QEMU
via a KernelCI `pull_labs` runtime.

**状态(2026-09-09)**:PR1(4 个 YAML,63 行)就绪未提交;官方全栈本地闭环跑通
(baseline done/pass);剩余三件事是"发出去"(tracking issue → PR → Phase 4)。
详见 [docs/REPORT.md](docs/REPORT.md)。

## 快速开始

```bash
./run.sh setup              # 一次性:克隆上游仓库 + 打补丁 + validate_yaml
./run.sh fetch              # 档位 A:抓生产最新 riscv 构建,tuxrun 本地复跑
./run.sh stack --seed       # 档位 B:起本地 KernelCI 全栈并派单
./run.sh worker             # 接单执行(另一终端)
./run.sh report             # 看结果
./run.sh verify             # 全套校验
./run.sh help               # 全部子命令与参数
```

## 目录

| 路径 | 内容 |
|---|---|
| `docs/` | 全部文档:REPORT(报告)、RUNBOOK(复现)、SOW 原文、upstream-evidence(先例铁证) |
| `tools/` | 全部代码:worker、fetch、drift/trend、verify、callback-catcher、stack/setup 脚本 |
| `config/` | 全部配置与补丁:PR1、bullseye、tuxlava、cb-config、local-callback.toml |
| `runs/` | 运行日志与产物(14GB,gitignore) |
| `artifacts/` | 下载构件(Image/kselftest.tar.xz,gitignore) |
| `archive/k3-era/` | K3 真机时代脚本(板子已不在,仅历史) |
| `kernelci-*/` | 上游仓库克隆(gitignore,setup 自动创建) |

## 环境

- 一次:`pip install tuxrun` + 打 config/tuxlava-kselftest-riscv.patch(见 RUNBOOK)
- 档位 B:kernelci-pipeline/.env 填 `KCI_API_TOKEN`(本地 API admin JWT,不提交)
- docker;QEMU 走 tuxrun 容器(11.0.2),宿主 ~/qemu-install 8.2.0 有 rvv bug 勿用
