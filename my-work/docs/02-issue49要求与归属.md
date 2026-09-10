# 02｜issue #49 归属判定：哪些交付物"在 KernelCI 里搞"，哪些在本地

> TL;DR：① issue #49 是 dev-partners 项目方的招募/协调帖，"Target Parent Community: KernelCI"（正文），真正进 KernelCI 的只有 Phase 3 的"RISC-V test profile suite"（= YAML 配置，上游 kernelci-pipeline）；② Phase 1 的"containerized pipeline"与"validation script"都不要求官方 docker-compose 全栈或 KernelCI 官方解析器，判据是措辞+同 SOW 先例；③ tracking issue 唯一正确坐标是 kernelci/kernelci-project（先例 #579，同 SOW 两实习生共同指向），不是 kernelci-pipeline（用户最新总结 §8 写错），也不是只在 dev-partners；④ 用户 64 行 pull_labs 配置=Phase 2+3 的主体交付，779 行 worker=②本地 lab 工具（上游只把 tuxrun 通用执行器 example_pull_lab.py 收进 tools/，见 kernelci-pipeline#1373）；⑤ 剩余缺口全是"行动缺口"（开 issue、发 PR、Phase 4 讲故事），无遗留技术债。

## 0. 坐标定义与判据

- ① KernelCI 上游主仓（kernelci-org：kernelci-pipeline / kernelci-project 等，改动要 PR 且会被 maintainer 评审）；② 本地/自己的部署与 lab 工具（用户自持仓库或本机，不进上游代码树）；③ 纯运营行为（发帖、开会、badge 申请等，无代码）。
- 判定原则：SOW 条目动词指向的对象 + "Target Parent Community: KernelCI Community / Linux Kernel mainline"（issue49_body.txt:6）+ KernelCI 各仓职能 + 同 SOW 先例（xjysiiau / Acidmoon 的实际做法）。

## 1. 四阶段 × 逐条归属表

| Phase | 原文条目（issue #49） | 归属 | 依据 | 用户现状 | 缺口 |
|---|---|---|---|---|---|
| P1 Setup | "Local development containerized testing pipeline initialized" | ② 为主（自建容器化 dev 流水线即可），官方 compose 全栈非强制 | 措辞是"local development pipeline"而非"KernelCI stack deployed"；P2 才写 "Primary KernelCI execution logic deployed"（见 §2a） | ✅ 早期 my-work/ harness（Dockerfile+CI）+ pull_labs 架构化 | 交付形态已转向 pull_labs（非容器内跑），建议 runbook 补"官方 docker-compose 本地栈跑通"佐证（未验证） |
| P1 Setup | "Initial tracking issue board established with parent community" | ① kernelci/kernelci-project（不是 dev-partners 或 kernelci-pipeline） | 先例 kernelci/kernelci-project#579；仓库职能；SOW 措辞 "with parent community"（见 §2b） | ❌ 未开 | 开 issue + #49 回帖挂链接 |
| P1 Setup | "First validation script successfully parsed locally" | ①+② 交界：被官方仓库自带校验器解析 | KernelCI 配置 PR 的门禁=tests/validate_yaml.py（见 §2c） | ✅ 本地跑通 "All yaml files are valid" | 无（把输出贴进 PR/tracking issue 作证据） |
| P2 Core | "Primary KernelCI execution logic deployed" | ② 部署侧 + ① 配置侧（pull_labs runtime+job 由上游 scheduler 渲染，lab 侧执行） | doc/connecting-pull-lab.md:18-95 分工：pipeline 管 config，lab 管执行 | ⏳ worker 已实测跑通生产 kbuild 产物；riscv scheduler 条目未合入=上游未真正在跑 | 合入后等上游结果回收接线（上游 future work，见总结 §4.1） |
| P2 Core | "Script automatically catches configuration drift" | ② 本地工具 | "Script"主语=交付者的脚本；KernelCI 上游有自身的 config 校验体系，无需带私货 | ✅ src/config_drift.py (188 行) | 不进 PR；建议挪出 src/（与 pipeline 服务模块混放，易被误会为要提交） |
| P2 Core | "…regression pass-rates…Vector/Hypervisor…QEMU/Spike" | ② 跑出来的数据 + ① 的 job 定义 | 实测数据（baseline PASS、riscv 9/9、kvm 7ok/2skip，总结 §1） | ✅ | 数据进 runbook/blog |
| P3 Upstream | "Formal PR…to integrate the RISC-V test profile suite" | ① kernelci-pipeline 主仓（唯一代码交付） | "test profile suite"= platform+job 配置（§3） | ⏳ 64 行配置+worker 就绪未提交 | PR1（纯配置）提交 |
| P4 Docs | "runbook finalized / blog / demo / LF Badges" | ③ 为主（runbook 可放①的 doc/ 或自持仓库） | 非代码交付 | ⏳ regression-tracking.md 有雏形；blog/demo/badges 缺 | Phase 4 补账 |

## 2. 重点一：Phase 1 三条逐条放大

### 2a "containerized testing pipeline" ≠ 必须官方 docker-compose 全栈
- 论据：(i) 条目原文只承诺 "Local development **containerized testing** pipeline initialized"，宾语是"本地开发用的、容器化的测试流水线"，不是"把 KernelCI 官方 api+core+pipeline 栈部署起来"——后者是 Phase 2 "**Primary KernelCI execution logic deployed**" 才出现的要求，说明 SOW 作者把"KernelCI 本体部署"放在 P2；(ii) 同 SOW 先例：xjysiiau 的 kernelci/kernelci-project#579 正文自述 Phase 1 完成=自建容器化闭环（GitHub Actions + self-hosted runner + QEMU guest，内核 cross-build 在容器里），未提官方 compose 栈，社区无人异议；(iii) 官方本地 dev 栈（kernelci-pipeline/docker-compose.yaml：monitor/scheduler/tarball/trigger/timeout/patchset 服务）是给开发者调 pipeline 用的，若 SOW 要求它必会写明 "official stack"。
- 结论：② 可满足；但"官方栈在 x86 本地 docker compose 跑通一次"目前**未验证**（经验笔记只记录了 riscv64 上被 MongoDB 卡死的失败，x86 侧从未留下成功记录），建议 runbook 补这一条作为无争议佐证。

### 2b tracking issue 开在 kernelci/kernelci-project（不是 dev-partners，更不是 kernelci-pipeline）
- 先例（铁证）：**kernelci/kernelci-project#579**（"RISC-V Development Partners: local QEMU boot + kselftest pipeline seeking the upstream integration path"，2026-08-21 由 **xjysiiau** 开，OPEN；正文含 Status 分节=当 tracking board 用，引用 dev-partners#49 与他的仓库）。dev-partners#49 评论区 Acidmoon（2026-08-24）明确称其为 "**the tracking issue at kernelci/kernelci-project#579**"——同 SOW 两位实习生已把 #579 当公共 tracking；这是本 SOW 的既定惯例。
- 为何不是 dev-partners：dev-partners README（raw.githubusercontent.com/riscv-admin/dev-partners/main/README.md）自述 "This repo is for tracking of RISC-V Development Partners **Activities**. All issues are managed via the DevPartners Work project"——它是 RISC-V 程序侧（SOW 发布+进度回帖，先例：xjysiiau/Acidmoon 均在 #49 回帖更新），而 SOW 要求的是 "established **with parent community**"，即 KernelCI 一侧，dev-partners 的 issue 不算数。
- 为何不是 kernelci-pipeline：其 issue 面板是 pipeline 代码工程 backlog（pull-labs 实现 #1371/#1372/#1375、job 故障 #1554 等，maintainer 分诊），放"SOW 状态跟踪"不是代码任务，语义不符、会被引导关闭；kernelci-project 才是 LF 项目的跨仓协调/运营 tracker（lab 注册 #559/#521、staging 访问 #530/#582、社区流程 #562/#560），#579 同列。
- 更正：用户总结 §8 待办写着"在 kernelci-pipeline 开 tracking issue"，与经验笔记（2026-08-27，结论 kernelci/kernelci-project）矛盾——**以 kernelci-project 为准**。操作建议：因 #579 是 xjysiiau 的（其交付路线与用户不同），用户可开自己的 kernelci-project issue（标题对齐"RISC-V pull-lab: qemu-riscv64 kselftest profile → kernelci-pipeline PR"）并互链 #579 与 dev-partners#49，避免与 #579 的提问重复。

### 2c "First validation script" 被"谁"解析 → 官方仓库自带校验器
- KernelCI 配置改动的事实门禁是仓库内 **tests/validate_yaml.py**（递归 merge config/*.yaml 后做 schema 校验，通过打印 "All yaml files are valid"，validate_yaml.py:347/363；用法 :374；pyproject.toml:23 已为其豁免 C901）。用户 4 处 config 改动（platforms/jobs-pull-labs/scheduler-pull-labs/pipeline-pull-labs）用 `python3 tests/validate_yaml.py` 本地解析通过（经验笔记 2026-08-31 有"官方校验通过"记录）。PR 提交后上游 CI 会跑同一工具。
- 注意区分：用户自研的 config-drift 检查（对照两份 .config）与 xjysiiau 的 "17-option contract + config diff" 是 **Phase 2 的 drift 工具**，不属于 P1c 这一条——P1c 的"validation script"在 KernelCI 语境指官方配置校验门。

## 3. 重点二：当前交付物 × Phase 对账（别再迷路）

| 交付物 | 归属 | 对应 Phase 条目 | 结论 |
|---|---|---|---|
| 64 行配置（platforms.yaml qemu-riscv64 / jobs-pull-labs 3 job / scheduler-pull-labs 3 条目 / pipeline-pull-labs runtime pull-labs-riscv，git diff --stat 实测 5 文件 64+） | ① | **Phase 3 "test profile suite" 主体**，同时是 Phase 2 "execution logic" 的上游配置侧 | 这就是要 PR 的东西（PR1）；其中 scheduler 复用生产已有 `kbuild-gcc-14-riscv` 事件（scheduler.yaml:344-347 同款事件），平台/job 形态照抄上游 kselftest-arm64-pull-labs（jobs-pull-labs.yaml:211-217） |
| tools/riscv_pull_worker.py（779 行） | ② lab 侧执行器（上游可选项） | Phase 2 "execution logic" 的本地执行端 | **不是** Phase 3 原文要的东西（原文只写 "test profile suite"）；但上游把执行器 example 收进 tools/（example_pull_lab.py/_pytest/_lava + doc/connecting-pull-lab.md:12），且上游自己的方向是让 tuxrun 通用执行器支持 qemu-riscv（kernelci-pipeline#1373，2025-11-25，CLOSED/COMPLETED）→ worker 可作 PR2 附带征求 reviewer 意见，随时可撤为纯 lab 工具 |
| src/config_drift.py / src/regression_tracker.py / doc/regression-tracking.md | ② | Phase 2 "catches configuration drift / regression pass-rates" | 不进 PR。⚠️ 它们现躺在 kernelci-pipeline 工作区的 src/ 下（与 lava_callback/send_kcidb 等服务模块混放），PR 前应收走，避免误入提交集 |
| baseline/kselftest 实测数据（9/9、7ok/2skip） | ② 证据 | Phase 2 "regression pass-rates … Vector/Hypervisor" | 进 runbook/blog 即可 |

行数账（对照总结 §7）：worker 779 行≈650 行有效代码，其中 ~170 行 PTY 串口驱动是 example_pull_lab.py（361 行、外包给 tuxrun）没有的——这正说明"执行器私有、协议公开"：协议侧（poll available → job_definition → callback，PULL_LABS）由上游定义，QEMU 驱动细节（ext4 烘焙/PTY/DONE 标记）是 lab 本地实现，上游不关心（总结 §4.3）。"模板≠简单"（经验 4）与"Phase 3 = 配置"不冲突：模板管生成、执行器管跑，两者按协议解耦。

## 4. 结论（3-5 条）

1. **tracking issue 应开在 kernelci/kernelci-project**（先例 #579，同 SOW 既成惯例；dev-partners 只做程序侧回帖，kernelci-pipeline issue 面板只收代码工程任务）——修正总结 §8 的 kernelci-pipeline 写法。
2. **Phase 1 判定**：1a（容器化 dev 流水线）与 1c（官方 validate_yaml.py 本地解析通过）✅ 算完成（按宽松措辞+先例）；1b（tracking issue）❌——**Phase 1 完整完成还差"开 kernelci-project tracking issue + #49 回帖"这一条**，是纯运营动作，当天可闭环。
3. **Phase 3 的"主仓交付物"严格等于配置（test profile suite）**，worker 只属 lab 侧（上游执行器方向是 tuxrun 通用化，#1373 已闭环）；建议 PR1（纯配置）先发，worker 视 review 反馈决定是否并 PR2。
4. **当前无技术缺口**：剩余项（开 issue、PR1、Phase 4 的 runbook/blog/demo/badges、PR 里注明 callback token `kernelci-pull-labs-riscv` 需运维配置——doc/connecting-pull-lab.md:79-95 的接入流程）全部是"发出去/讲故事"类行动项；上游结果回收未闭环（lava_callback.py:525 硬编码 LAVA Callback）是上游 future work，不阻塞交付验收。
5. **宣传口径提醒**："上游第一个 riscv QEMU 测试"不成立——legacy kernelci-core 时代（2023-07）qemu-riscv kselftest 已在 lab-baylibre 跑（kernelci-core#2008，CLOSED/COMPLETED，montjoie）；准确说法是"**补齐 modular kernelci-pipeline 的 riscv QEMU kselftest 覆盖**（pull_labs 形态）"，避免 maintainer 一句"已有先例"打回。

## 5. 留给综合代理的关键判断/数字

- 判断 1：tracking issue 坐标 = kernelci/kernelci-project（先例 #579，2026-08-21 xjysiiau OPEN；Acidmoon 2026-08-24 在 dev-partners#49 评论称其为 "the tracking issue"），用户最新总结 §8"kernelci-pipeline 开 issue"是笔误需修正。
- 判断 2：Phase 1a 官方 compose 全栈**非强制**（措辞+xjysiiau 先例）；但"官方栈本地跑通"证据缺失（未验证），建议 runbook 补齐。Phase 1 完成判定=1a✅ 1b❌ 1c✅。
- 判断 3：Phase 3 提交物 = 64 行配置（5 文件：platforms/jobs-pull-labs/scheduler-pull-labs/pipeline-pull-labs + pyproject 1 行 C901）；worker 779 行=②lab 工具，上游执行器方向=tuxrun 通用化（kernelci-pipeline#1373 CLOSED），worker 至多作可选 PR2。
- 判断 4：src/config_drift.py(188)/src/regression_tracker.py(233)/doc/regression-tracking.md(54) 属 Phase 2 本地工具，PR 前从 kernelci-pipeline 工作区 src/ 收走。
- 判断 5：上游"riscv qemu 覆盖缺失"仅对 modular pipeline 成立；legacy 先例 kernelci-core#2008（2023-07-12，CLOSED）——PR 描述勿写 "first ever"。
- 关键 URL：github.com/kernelci/kernelci-project/issues/579；github.com/riscv-admin/dev-partners/issues/49；github.com/kernelci/kernelci-pipeline/issues/1373、/2008（kernelci-core）；github.com/riscv-admin/dev-partners（README）。
