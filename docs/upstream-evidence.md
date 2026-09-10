# 上游先例铁证(2026-09-09 在线核验)

> 用途:PR 答辩时的"别人怎么写"证据。所有对象 2026-09-09 通过 api.github.com 实测核过
> (HTTP 200,原始 JSON 已删,git 历史 commit a387d6f 前可查)。
> 结论一句话:riscv 的 pull-lab 配置形态有 5 个已合并先例可照抄,pull_labs 是上游一等公民
> runtime,PR1 与它们同构。

## 一、对象清单(全部已核实存在)

| 对象 | 链接 | 状态 | 说明 |
|---|---|---|---|
| SOW issue #49 | riscv-admin/dev-partners/issues/49 | open | 作者 gsterlin;2026-08-11 创建;Sunset = 21 天无活动归档(最后评论 2026-08-24 → 红线 09-14) |
| tracking 先例 #579 | kernelci/kernelci-project/issues/579 | open | xjysiiau(KUBUDS 实习生)"seeking the upstream integration path"——tracking issue 就开在 kernelci-project,不是 pipeline |
| PR #1313 | kernelci/kernelci-pipeline/pull/1313 | merged 2025-10-23 | nuclearcat "Implementing pull-only labs"(基础设施,先例①) |
| PR #1357 | kernelci/kernelci-pipeline/pull/1357 | merged 2025-11-06 | "labs: Add pull-only labs support and demo"——**qemu-arm64 + kselftest 同款组合,我们的最像样板**(先例②) |
| PR #1477 | kernelci/kernelci-pipeline/pull/1477 | merged 2026-04-28 | "pull-labs: add AWS EC2 platform and scheduler config"(先例③) |
| PR #1509 | kernelci/kernelci-pipeline/pull/1509 | merged 2026-06-12 | "add first pull lab for pengutronix"(先例④) |
| PR core#3008 | kernelci/kernelci-core/pull/3008 | merged 2025-11-06 | "runtime: Add Pull-Only labs runtime implementation"(协议本体,先例⑤) |
| tuxrun riscv 支持 | kernelci/kernelci-pipeline#1373 | COMPLETED 2026-01-15 | "update example_pull_lab.py to boot qemu-* (arm64\|riscv etc)" |

## 二、关键数字与结论

- **生产 pull-labs-demo(arm64)现状**:12472 节点 = incomplete 480(node_timeout)/ pass 20 / fail 0——生产结果回收脆弱(96% 超时),我们的 worker 能把 selftest 失败如实翻成 fail,质量高于现状。
- **生产 trend(arm64 pull-labs,2303 条)**:2016 pass / 81 fail / 71 regressions。
- **#1357(样板)**:qemu-arm64 + kselftest 组合,真跑 1983 pass;PR1 提交前逐行对照它。
- **#49 评论区**只 5 条:两名 KUBUDS 实习生跟进 + gsterlin 认可;我们(用户)的进度更新帖即"#49 回帖"。
- **5 个先例 PR 全部零 review 评论**(reviews/comments 均为空数组)——受信任机构准入,配置 PR 不需要长篇 review。

## 三、口径(写 PR 描述用)

- 只 `git add` 4 个 config yaml;形态照 #1357 换 arch + `collection: riscv`。
- 首行引 "Part of riscv-admin/dev-partners#49";勿写 "first ever"(kernelci-core#2008 有先例)。
- 声明 tuxlava 补丁存在(config/tuxlava-kselftest-riscv.patch,计划推 kernelci/tuxrun)。
- token 值在部署侧 kernelci.toml,PR 只带名字。
