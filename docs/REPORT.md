# KernelCI RISC-V SOW 报告(riscv-admin/dev-partners#49)

> 生成:2026-09-09 复核口径,2026-09-10 随仓库整合更新。本文档是唯一权威报告:整合了
> 此前的交接研究、SOW 总结与复核结论,其余过程性文档已归档于 git 历史
> (commit a387d6f 之前的快照),不再单独保留。
> SOW 原文:docs/SOW-issue49-body.md(verbatim 存档)。先例铁证:docs/upstream-evidence/。

## TL;DR

SOW 必做项已完成并按实测口径验证——QEMU 上 Vector/Hypervisor 定向扩展持续回归
(baseline PoC done/pass;riscv collection 本地复跑 10 项 **9 ok / 1 not ok**,not ok 为
pointer_masking 的 PMLEN constraint 子项,TCG 模拟限制)+ 配置漂移检测(同 commit 两次构建
5412 项 0 漂移)+ 回归通过率追踪 + 本地容器化流水线。交付物 = 上游 pull_labs 形态的
**4 文件 63 行配置** + 一个经双轮代码评审加固的 lab worker(不进 PR)。
剩下的是"发出去"(tracking issue、PR)和"讲故事"(runbook/blog/demo/badges)。

⚠️ 口径:早期"QEMU 11.1.1 + ssnpm 9/9 全绿、6s/27s/167s、kvm 7 ok/2 skip"**无原始日志,
一律不采信**。可复现口径以 docs/RUNBOOK.md 实测为准。

## 1. 四阶段对账

| Phase | SOW 要求 | 状态 |
|---|---|---|
| 1 Setup | 本地容器化测试流水线 + 校验脚本 | ✅ tools/ 一键化(见 RUNBOOK) |
| 1 Setup | 父社区 tracking issue | ⏳ 待办(kernelci/kernelci-project,互链 #49/#579) |
| 2 Core | QEMU 上定向扩展回归(Vector/Hypervisor) | ✅ riscv collection 10 项 9 ok/1 not ok;baseline PoC done/pass |
| 2 Core | 配置漂移 + 通过率追踪 | ✅ tools/config_drift.py、tools/regression_tracker.py |
| 3 Upstream | 正式 PR 合入 kernelci-pipeline | ⏳ 4 YAML/63 行就绪未提交(validate_yaml 通过) |
| 4 Docs | runbook / blog / demo / badges | ⏳ runbook 定稿(RUNBOOK.md),其余待办 |

## 2. 交付物(全在本机)

| 东西 | 位置 | 状态 |
|---|---|---|
| PR1 本体 | kernelci-pipeline/config/{platforms,jobs-pull-labs,scheduler-pull-labs,pipeline-pull-labs}.yaml(4 个 M,63 insertions) | 就绪未提交 |
| PR1 补丁副本 | config/pr1-config.patch | 交付 |
| bullseye 归档源补丁 | config/kernelci-api-bullseye-archive.patch | setup 自动应用 |
| tuxlava 补丁 | config/tuxlava-kselftest-riscv.patch | 已打入已装 tuxlava 0.24.0;计划推 kernelci/tuxrun |
| lab worker | tools/riscv_pull_worker.py(tuxrun 引擎,1040 行) | lab 私有,不属 PR1 |
| 漂移/回归工具 | tools/config_drift.py、tools/regression_tracker.py | 双模式(本地/生产) |
| 校验脚本 | tools/verify-lava-body.py、tools/verify-worker-guards.py | 全绿 |
| 一键入口 | run.sh(setup/stack/fetch/verify/report/drift/trend) | 实测可用 |
| SOW 原文 | docs/SOW-issue49-body.md | verbatim 存档 |
| 先例铁证 | docs/upstream-evidence/(23 JSON + verify-report) | #1313/#1357/#1477/#1509/core#3008/#579/#49 在线核过 |
| 本地证据 | runs/(14GB 跑批日志,gitignore)、artifacts/(下载构件,gitignore) | 本地留档 |
| K3 真机归档 | archive/k3-era/(仅 .sh 脚本;真机已不在) | 历史,不采信数值 |

## 3. 已验证结果(对外口径)

- validate_yaml → "All yaml files are valid";两个 verify 脚本全绿。
- **baseline PoC**:节点 6a9fb8bfdb925f2f584f0771 done/pass;重放 6aa11653fa416dea4a15a0bf
  done/pass + setup 子节点 + 三构件入库;防假绿节点 6aa114ef…(EPERM → incomplete+Infrastructure,如实上报)。
- **官方调度器本地闭环**:种子 kbuild → scheduler 读我们 4 个 YAML → 渲染 3 份任务书
  (pull_labs_jobs/<日期>/<uuid>.json)→ 自动建 3 个 job 节点 → worker 接单 → 真实回调
  (8003)→ baseline done/pass;kselftest 两单因 storage 下载截断如实报 Infrastructure。
- **riscv collection**(v7.3-rc1,ssnpm=true,本地复跑):10 项 **9 ok / 1 not ok**
  (pointer_masking 的 PMLEN constraint,TCG 限制);v6.18 对照 7 ok/1 not ok(51/61 SKIP)。
- **2026-09-10 一键化复验**:`./run.sh fetch` 抓生产最新构建(v6.6.156-rt79,节点
  6aa1dfd2…)tuxrun 复跑 riscv collection = 4/4 ok(hwprobe/vstate_prctl/v_initval_nolibc/run_mmap);
  `./run.sh setup → stack --seed → worker` 全链路:官方调度器渲染 3 份任务书 → worker 接单 →
  真实回调 → **baseline done/pass、kselftest-kvm done/pass**;kselftest-riscv 单因本机代理失效
  如实报 Infrastructure fail(worker 已改为直连,重跑即可)。
- **配置漂移**:6.18 同 commit 两次 5412 项 0 漂移;生产两次 5583 项 0 漂移;6.18→7.3-rc1 = +274/−103/41。
- **生产 trend**(arm64 pull-labs,2303 条)= 2016 pass / 81 fail / 71 regressions;
  pull-labs-demo 12472 节点(480 incomplete node_timeout / 20 pass / 0 fail)。
- QEMU:宿主 ~/qemu-install = 8.2.0(rvv bug,勿用);tuxrun 容器 = 11.0.2(实际执行路径)。

## 4. 关键技术认知(为什么长这样)

- **pull_labs 是上游一等公民 runtime**:"外部 lab poll 事件 → 下载 job 定义 → 本地跑 →
  callback 回传",默认执行器 tuxrun。上游已有 qemu+kselftest 先例
  `kselftest-arm64-pull-labs`(nfsroot),我们照抄换 riscv。docker-QEMU 是执行环境耦合进
  scheduler 的非标准路径,别当全仓库第一个 docker 测试 job。
- **worker 不提交**:上游把 lab 当黑盒(只要求"接得到单 + 按 LAVA body 回传真结果"),真 lab
  全没交执行器;PR1(纯配置)才是唯一必交。
- **结果回传契约 = LAVA body 5 字段**:status/definition/results.lava/results.<suite>/log,
  解析器是 kernelci-core 的 `kernelci.runtime.lava.Callback`,lava_callback.py 只认它。
  缺 log → 上游强制 incomplete。verify-lava-body.py 喂生产 Callback 全绿。
- **token = 门禁卡**:名字进 PR(pipeline-pull-labs.yaml),值在部署侧 kernelci.toml
  `[runtime.pull-labs-riscv] runtime_token=...`,lab 放环境变量 PULL_LABS_CALLBACK_TOKEN。
- **防假绿**:guest 自带断言 + 证据不足报 incomplete 不给 pass + 本地对生产同款解析器验证;
  上游无自动内容校验,信任靠"准入+公开+声誉"。

## 5. 已知坑/诚实清单

- Debian bullseye 已归档(官方问题):kernelci-api ssh 容器 Dockerfile 需打
  config/kernelci-api-bullseye-archive.patch(setup 自动打);不进任何 PR。
- api.kernelci.org 时通时断;files/storage.kernelci.org/github/staging 正常。
- 144MB rootfs 下载可能截断 → worker 如实报 Infrastructure(Content-Length 校验),重跑即可。
- tuxlava 补丁重装 tuxrun 后需重打(patch -p1 到已装包)。
- 生产工具只读:drift/trend 免 token;track/watch 仅本地 API+token。

## 6. K3 真机归档(2026-08-27,板子已不在;仅历史)

riscv 回归:K3/X100 上 7 pass / 1 fail / 0 skip(gcc 与 clang 同)。KVM:3 pass / 17
timeout/SKIP/drift;核心结论是 Hypervisor 可用、进阶特性当时不成熟。sbi_pmu/irqfd 两个
SKIP 是平台现状(测试按设计降级),不修。真机脚本留 archive/k3-era/*.sh,数值不再采信。

## 7. 待办

1. kernelci/kernelci-project 开 tracking issue(标题 "RISC-V pull-lab: qemu-riscv64
   kselftest profile → kernelci-pipeline PR",互链 #49/#579)。
2. 发 PR1:fork → 分支 riscv-qemu-pull-labs → 只 add 4 个 YAML → commit
   "config: add RISC-V QEMU pull-lab test profile"。描述:首行 Part of … #49;validate_yaml
   输出;PoC 节点号;token 值在部署侧;声明 tuxlava 补丁存在;禁写 "first ever"。
3. Phase 4:blog、demo、LF badges。
