# kernelci-riscv

RISC-V KernelCI 自动化——实现 riscv-admin/dev-partners#49 的 SOW:在 QEMU 上对 Linux
riscv 的 Vector/Hypervisor 定向扩展做持续回归测试,并合入上游 kernelci-pipeline。

> **状态(2026-09-10)**:PR1(4 个 YAML,63 行)就绪未提交;本地全栈闭环实测
> baseline/kselftest-kvm done/pass;剩下三件事是"发出去"(#49 回帖 → tracking issue → PR)。
> **给下一个 AI 的一句话:先读本文档第 4 节"交接",再动手;所有命令在仓库根执行 `./run.sh`。**

## 1. 是什么:SOW 四阶段对账

| Phase | SOW 要求(原文) | 我们的实现 | 状态 |
|---|---|---|---|
| 1 Setup | Local development containerized testing pipeline initialized | tuxrun(docker 容器)+ run.sh 一键化 | ✅ |
| 1 Setup | First validation script successfully parsed locally | `./run.sh setup` 末尾跑上游 validate_yaml.py,打印 "All yaml files are valid" | ✅ |
| 1 Setup | Initial tracking issue board established with parent community | kernelci/kernelci-project 开 tracking issue(先例 #579) | ⏳ 待办 |
| 2 Core | tests regression pass-rates for targeted extensions (Vector/Hypervisor) on QEMU | riscv collection(Vector)10 项 9 ok/1 not ok;kvm collection(Hypervisor)9 项全过 | ✅ |
| 2 Core | automatically catches configuration drift | scripts/config_drift.py(同 commit 两次构建 5412 项 0 漂移) | ✅ |
| 2 Core | tests regression pass-rates | scripts/regression_tracker.py(生产 arm64 2303 条 trend 实测) | ✅ |
| 3 Upstream | Formal PR to integrate the RISC-V test profile suite | 4 个 YAML/63 行,validate_yaml 通过 | ⏳ 就绪未提交 |
| 4 Docs | runbook finalized / blog / demo / badges | 本文档即 runbook | ⏳ 其余待办 |

**红线**:SOW 有 21 天无活动归档条款(#49 最后评论 2026-08-24 → 红线 2026-09-14)。

## 2. 怎么跑(run.sh 一键)

环境:docker + `pip install tuxrun`;档位 B 另需 kernelci-pipeline/.env 里填
`KCI_API_TOKEN`(本地 API admin JWT,永不提交)。一次性给已装 tuxlava 打补丁:

```bash
cd ~/.local/lib/python3.10/site-packages && patch -p1 < /home/hao/kernelci-riscv/config/tuxlava-kselftest-riscv.patch
```

| 命令 | 干什么 | 结果落哪 |
|---|---|---|
| `./run.sh setup` | 克隆 core/api/pipeline + 打 PR1/bullseye 补丁(已含则跳过,PR 合并前后同一条命令)+ 跑 validate_yaml | 屏幕 "All yaml files are valid" |
| `./run.sh fetch [--job 名] [--kvm] [--kvm-full]` | 档位 A:抓生产最新 riscv 构建,tuxrun 容器复跑 | TAP 汇总打印;构件 work/downloads/、日志 work/logs/ |
| `./run.sh stack [--seed]` | 档位 B:起本地全栈(api/db/redis/storage/ssh + 构件服务 + 真实回调 + 官方调度器);--seed 派单 | 节点进本地 API(mongo 卷持久积累) |
| `./run.sh worker [--once]` | 接单执行回传;--once = 处理完现存单就退(一次性闭环测试用) | 节点状态 → 本地 API |
| `./run.sh report` | 看最近 baseline/kselftest 节点状态 | 屏幕 |
| `./run.sh verify` | validate_yaml + 两个 verify 脚本 + ruff | 全绿门禁 |
| `./run.sh drift` / `./run.sh trend` | 配置漂移 / 回归通过率 | 屏幕摘要;--json 存 work/logs/ |
| `./run.sh stop` | 停本地全栈 | — |

**三种 worker 模式 = 一个文件**:①一次性本地闭环(`stack --seed` + `worker --once`)= 测自己;
②本地长期全栈(worker 常驻)= 积累回归历史;③远程官方(改 --api-url 和 token)= 真 lab。
不拆两份文件,因为三模式差异全是参数——拆了,本地测试就不再验证生产路径。

**两个编译器的事实**:生产 riscv 主线只有 gcc-14 出 kselftest 构建(kbuild-gcc-14-riscv);
clang 只有 android-defconfig 且无 kselftest。所以 fetch 做成 `--job` 参数化,默认 gcc-14;
clang 是上游缺口(记档,不是我们的默认路径会失败)。

**KVM 全测还是 9 项白名单**:默认 9 项精选(KVM 功能路径全覆盖);perf/stress 在 TCG 模拟器里
测的是模拟器速度不是内核回归,必然超时且超时≠失败,掺进回归数据只会造噪音。`--kvm-full`
可跑全集(长超时,超时如实报 incomplete、绝不报 fail)——保留这个入口是"需要时能证明全集
也能跑",不是默认用它。

## 3. 已验证事实卡(对外口径,2026-09-09 复核)

- validate_yaml → "All yaml files are valid";verify-lava-body / verify-worker-guards 全绿。
- **baseline PoC**:节点 6a9fb8bfdb925f2f584f0771 done/pass;重放 6aa11653fa416dea4a15a0bf
  done/pass + setup 子节点 + 三构件入库;防假绿节点 6aa114ef…(EPERM → incomplete+Infrastructure,如实上报)。
- **官方调度器本地闭环(9-10 一键化实测,多批次复验)**:seed kbuild → 官方调度器读我们 4 个
  YAML → 渲染 3 份任务书 → 自动建 3 个 job 节点 → worker 接单 → tuxrun/QEMU → LAVA body →
  真实 lava_callback(8003)→ baseline **done/pass**、kselftest-kvm **done/pass**;
  kselftest-riscv **done/fail**(如实上报:riscv collection 10 项 8 pass / 2 fail,
  fail = which-cpus、validate_v_ptrace——TCG 模拟环境的 CPU 拓扑/ptrace 语义差异;
  pointer_masking 在 ssnpm=true 下 pass;每项结果都挂在节点子层级)。
- **riscv collection(Vector)**:v7.3-rc1(ssnpm=true)本地复跑 10 项 **9 ok / 1 not ok**
  (not ok = pointer_masking 的 PMLEN constraint,TCG 限制);v6.18 对照 7 ok/1 not ok(51/61 SKIP)。
- **配置漂移**:6.18 同 commit 两次构建 5412 项 0 漂移;生产两次 5583 项 0 漂移;
  6.18→7.3-rc1 = +274/−103/41。
- **生产 trend(arm64 pull-labs,2303 条)**:2016 pass / 81 fail / 71 regressions;
  pull-labs-demo 12472 节点(480 incomplete node_timeout / 20 pass / 0 fail)。
- QEMU:宿主 ~/qemu-install = 8.2.0(rvv bug,勿用);tuxrun 容器 = 11.0.2(实际执行路径)。
- ⚠️ **口径红线**:早期"QEMU 11.1.1、9/9 全绿、6s/27s/167s、kvm 7 ok/2 skip"全部无原始日志,
  一律不采信;以本节可复现数字为准。

## 4. 交接给下一个 AI

**交付物(全部在本机,绝对路径)**:

| 东西 | 位置 | 状态 |
|---|---|---|
| PR1 本体 | kernelci-pipeline/config/{platforms,jobs-pull-labs,scheduler-pull-labs,pipeline-pull-labs}.yaml(4 个 M,63 insertions) | 就绪未提交 |
| PR1 补丁副本 | config/pr1-config.patch | 交付 |
| bullseye 归档源补丁 | config/kernelci-api-bullseye-archive.patch | setup 自动应用;官方 Debian 归档问题,不进 PR |
| tuxlava 补丁 | config/tuxlava-kselftest-riscv.patch | 已打入 tuxlava 0.24.0;计划推 kernelci/tuxrun |
| lab worker | scripts/riscv_pull_worker.py(tuxrun 引擎;--once/--kvm-full/--kvm-tests/--since) | lab 私有,不属 PR1 |
| 工具 | scripts/config_drift.py、regression_tracker.py、fetch-and-run-latest.py、verify-*.py | 双模式(本地/生产) |
| SOW 原文 | docs/SOW-issue49-body.md | verbatim 存档 |
| 先例铁证 | docs/upstream-evidence.md | 5 个已合并先例 + 生产现状,PR 答辩弹药 |
| 本地证据 | work/(14G 已瘦身;日志/构件/环境镜像,gitignore) | 可重跑再生 |

**还差三件事(按顺序,每件 2 分钟到半天)**:
1. **#49 回帖**:进度更新(Phase 1-2 done,Phase 3 ready;validate_yaml 通过;PoC 节点号;
   drift 5412/0;tracking issue 链接;PR 本周)→ 清零 21 天倒计时。
2. **开 tracking issue**(kernelci/kernelci-project):标题 "RISC-V pull-lab: qemu-riscv64
   kselftest profile → kernelci-pipeline PR",互链 #49 与 #579,附 Status checkbox。
3. **发 PR1**:fork → 分支 riscv-qemu-pull-labs → 只 add 4 个 YAML(严禁 git add -A)→
   commit "config: add RISC-V QEMU pull-lab test profile"。描述:首行 Part of … #49;
   validate_yaml 输出;PoC 节点号;token 值在部署侧;声明 tuxlava 补丁;禁写 "first ever";
   推送前对照 docs/upstream-evidence.md 里 #1357/#1477 的 commit 风格。

**已知坑**:api.kernelci.org 时通时断(直连可用,本机 7890 代理已死,run.sh 已默认摘代理);
144MB rootfs 下载会截断 → 如实报 Infrastructure,重跑即可;tuxlava 补丁重装 tuxrun 后需重打;
worker 默认 `--since` 只接当天新单,不重放历史。

## 5. 目录说明

| 路径 | 内容 |
|---|---|
| `docs/` | 文档:SOW 原文、上游证据 |
| `scripts/` | 全部代码(9 个文件平铺)+ fixtures/(verify 用的真实日志样本) |
| `config/` | 全部补丁与配置:PR1、bullseye、tuxlava、cb-config、local-callback.toml |
| `work/` | 运行时工作区(gitignore,可再生):downloads(下载构建)、env(guest 镜像)、logs、jobs、serve |
| `kernelci-*/` | 上游仓库克隆(gitignore,setup 自动创建) |
