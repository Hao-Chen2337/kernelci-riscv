# kernelci-riscv

承接 [riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49)
SOW 的 RISC-V KernelCI 自动化:在 QEMU 上对 Linux riscv 的
Vector/Hypervisor 扩展做持续回归测试,并把测试配置合入上游
kernelci-pipeline。

**怎么跑:** 见 [docs/RUNBOOK.md](docs/RUNBOOK.md)。

## 状态(2026-09-10)

如实状态,非完工声明:本地流水线已端到端跑通;riscv 回归历史刚开始积累。

| 方面 | 状态 |
|---|---|
| PR1 测试配置(4 个 YAML,63 行) | 就绪 — validate_yaml 全绿;官方调度器能据此渲染 3 份任务书 |
| 本地全栈闭环(seed → 调度器 → worker → 真实回调) | baseline **pass** · kselftest-kvm **pass**(8 项白名单:6 pass / 2 skip)· kselftest-riscv **fail**(9 pass / 1 fail,如实上报) |
| 配置漂移 + 回归趋势工具 | 漂移:同 commit 两次构建 5412 项 0 漂移;趋势已在生产 arm64 数据上验证(2303 条) |
| 上游步骤 | #49 回帖、tracking issue、PR1 — 草稿就绪,尚未发出(SOW 红线 2026-09-14) |

已知环境限制(如实上报,非内核回归):pointer_masking 在 QEMU TCG 下
PMLEN=16 处失败;irqfd_test、sbi_pmu_test 在 TCG 下跳过;
kvm_page_table_test 在 TCG 下拖死整轮,已移出默认白名单。

## 仓库布局

| 路径 | 内容 |
|---|---|
| `docs/RUNBOOK.md` | 运行命令与操作说明 |
| `scripts/` | 全部代码:worker、drift、trend、fetch、verify、stack |
| `config/` | PR1 配置补丁 + tuxlava/bullseye/nginx 补丁 |
| `kernelci-*/` | 上游克隆(gitignore,由 `./run.sh setup` 创建) |
| `work/` | 运行时工作区(gitignore,可再生) |
