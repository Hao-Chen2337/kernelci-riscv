# 08｜worker 演进账本与三轮审查经验(2026-09-08 晚)

> 写作目的:回答两个问题——① worker 为什么从 499 行越改越厚到 1008 行;② 三轮独立子代理审查教给我们什么。给下一个会话/下一个项目当镜子用。

---

## 0. TL;DR

1. **每一行增长背后都有一条"实跑失败"或"审查发现"**,没有任何一行是预防性虚胖;行数账本见 §1。
2. **越改越厚的根因是"演示 → 生产"的距离**:上游把结果回收+判读逻辑写在 lava_callback.py(数百行)、kernelci-core 运行时、tuxlava 模板、LKFT 脚本里,而 `example_pull_lab.py` 根本不回传结果——lab 侧想真正闭环,就必须自己重写这些判读逻辑,再加一层"面向不可信输入"的防御。
3. **真实环境会惩罚每一条想当然**:`rw` 引导参数、`/dev/kvm`、python3-tap、tuxrun 退出码语义——四条假设全被实跑打脸,每条都长了几十行。
4. **独立审查 + 对抗实测抓到了读代码抓不到的东西**:CRITICAL 级反斜杠 SSRF(token 泄露)、tar 硬链接基准目录错误,都是"看起来显然没问题"的代码。
5. 减重路线存在但都在上游侧(§5);当前形态是"lab 侧自足"的合理代价。

---

## 1. 行数账本(499 → 1008,按驱动归因)

| 阶段 | 总行数(纯代码) | 增长驱动 | 代表改动 |
|---|---|---|---|
| V3 起点(9-07) | 499(361) | tuxrun 外包执行层 | 轮询/下载/烤盘/回调骨架 |
| 结果回报层(9-08 白天) | 601→744 | **端点只认 LAVA body + tuxrun 退出码撒谎** | `lava_body()` 回放 login/kernel-messages、TAP→逐项 case、`status=2` 层级判读、infra 走 job stage metadata |
| KVM/环境适配(9-08 傍晚) | 744→800± | **三个环境事实** | TST_CASENAME allow-list、modules-load.d 注入、`--boot-args rw`、9 项精选常量 |
| 三轮审查加固(9-08 晚) | 800→1008 | **面向不可信输入 + 失败语义完备化** | URL 白名单(含反斜杠归一)、tar 逐成员逃逸检查、下载/日志上限、重定向拒绝、Permanent/Transient 错误分类 + report 缓存重发、游标重叠窗口、原子状态、超时保日志、LAVA 自报 error_type 解析 |

其中**文档/docstring 约 170 行**(模块头 120 行 + 各函数 docstring):因为"下一个 agent 必须不重走弯路",知识不写进代码就会被丢——这也是厚度的一部分,但集中在头部,不摊薄逻辑。

对照:上游 `example_pull_lab.py` 361 行(纯 ~310)是"玩具"(不 POST、state=done 过时、要按回车);等价的回收+解析+判读职责在上游分布在 `lava_callback.py`(~1000 行)、`kernelci-core/kernelci/runtime/lava.py`(数百行)、`tuxlava/templates/*.jinja2`、LKFT `kselftest.sh`/`modules.sh`。**我们 1008 行 ≈ example + 上游那几块里 lab 侧必须自持的部分。**

---

## 2. "为什么越改越厚"的五个根源

### 根源一:演示与生产的差距 = 结果回报层
example 演示"能跑";生产要求"跑完的结果正确、可见、不丢"。后者需要:
- **判读**:tuxrun 在 selftest 失败时退出码仍是 0,必须自己读 console TAP;TAP 还带 ANSI/时间戳/`# SKIP`/`# TIMEOUT`/畸形变体。
- **翻译**:端点只认 LAVA body,要把 TAP 翻成 `results.lava` case 层级(套件 stage + 逐项 case),还要回放 boot 的 login/kernel-messages 让 `setup` 层级成立。
- **真伪**:TAP 为空不能 pass(假绿)、rc=0 但无 boot case 不能 pass、LAVA 自报 `error_type: Infrastructure` 才认 infra。
这三件事就是 ~150 行,且每一行都对着 `kernelci.runtime.lava.Callback` 的真解析器验证过。

### 根源二:真实环境会惩罚每一条想当然
| 想当然 | 实跑打脸 | 长出的代码 |
|---|---|---|
| rootfs 能写 | debian fstab 是 UNCONFIGURED 占位 → 根挂 ro,LAVA 测试壳写结果报 Read-only | 统一 `--boot-args rw` |
| kvm 模块装了就行 | LKFT modules 测试是"装完即卸"往返测试 → /dev/kvm 缺失 9 项全 SKIP | modules-load.d 烤盘注入 + S11modules 机制验证 |
| 根文件系统有解析工具 | buildroot 无 python3-tap → LKFT 结果文件空、tuxrun 退 2 | 退出码语义表 + "有 TAP 就按层级判" |
| 退出码=结果 | 0=全过/1=有 fail/2=无 LAVA 结果(读 tuxrun 源码确认) | `tuxrun_invocation_error`/`tuxrun_job_error`/`tuxrun_infra_error` 三层 |

教训:**先跑生产同款 rootfs,再谈"已闭环"**。buildroot 跑通只证明了机制,trixie 才暴露 ro 挂载和 python3-tap 问题。

### 根源三:面向不可信输入(job 定义和构件是攻击面)
三轮审查把 worker 从"信任管道"推到"管道可能被投毒":
- URL 白名单 + **反斜杠归一**(`http://evil.com\@127.0.0.1/` 这种解析器混淆,对抗实测 token 会被泄给攻击者)——~20 行 + 测试;
- tar 逐成员逃逸检查(绝对路径/../设备/符号链接/**硬链接基准目录错误**)——~45 行 + 5 个恶意 tar 测试;
- 下载/日志上限、重定向拒绝(token 不随 3xx 跨 host)——~30 行。
安全防护的代码没有"够用",只有"被证明绕过之前够用"。

### 根源四:失败语义比成功复杂
成功只有一种;失败有"测试真挂 / 基建挂了 / 网络抖动 / 端点拒绝 / 超时 / 日志为空"六种,且各自的正确动作不同:
- 测试挂 → fail + 逐项明细;
- 基建挂 → incomplete + `error_type: Infrastructure`(回归系统据此排除);
- 回调 4xx → 永久放弃(重试无用);5xx/网络 → 缓存 body 只重发不重跑;
- 乱序事件 → 重叠窗口 + seen 去重。
这一块状态机 ~120 行,是三轮审查里被打最多的地方,也是"丢结果"风险最集中的地方。

### 根源五:文档厚度 = 会话记忆
每个环境事实(rw、/dev/kvm、退出码、token 前缀、容器网络)都写在 docstring 里,因为**不写进去,下一个 agent 就要重付一次学费**。这是有意的厚度。

---

## 3. 三轮独立子代理审查的经验

### 3.1 流程经验
1. **独立 + 对抗实测 >> 单轮读代码**:R1 三员独立审出 13 个严重项;R2 的对抗员用真实 HTTP 服务/tar 构造**抓到了读代码会漏掉的两个绕过**(反斜杠 SSRF、硬链接基准目录)。如果只做一轮"读代码",这两个会带进生产。
2. **每个修复都要回归测试**:三个绕过全部固化成 `my-work/tools/verify-worker-guards.py` 用例;测试文件是"审查成果"的唯一可靠载体。
3. **报告重复率高 = 信号可信**:R1 三员对 `_safe_members`、回调重试、状态文件三个问题独立命中——重复项优先修。
4. **给复审员看"上一轮发现清单"效率最高**:R2 逐条核验 + 找新问题,产出比重新漫读高得多。
5. **第三轮审的是"口径"而非"代码"**:63 vs 64 行、pyproject 归属、token 真实鉴权机制(YAML token 在 pull_labs 路径根本不生效)、kcidb 套件名——这些"提交时会出事"的问题只有站在"要发 PR 的人"视角才看得到。

### 3.2 具体教训(按血泪程度排序)
1. **两个解析器对同一 URL 的理解不同**(urlparse vs urllib3):校验与执行必须用同一套归一化规则。
2. **tar 的硬链接 linkname 相对归档根,符号链接相对成员目录**——统一处理必然错。
3. **"失败"文本的多样性超乎想象**:`not  ok`/`not\tok`/`NOT OK`/`not\x1b[31mok`/`notok` 全都要算失败,否则假绿。
4. **游标只进不退会在乱序事件流上永久跳单**;重叠窗口 + seen 去重是便宜且正确的解法。
5. **回调的共享 token 是最高价值资产**:所有"带 token 的请求"都要过三重门(URL 白名单、重定向拒绝、永久失败不重试)。

---

## 4. 当前已知残余(诚实清单,不阻塞提交)

- `reports` 缓存仅内存:回传前崩溃会重跑该 job(不丢结果,只重复执行)。
- kvm_page_table_test 内部 120s 超时在 TCG 高负载下 ~1/2 概率 TIMEOUT——非 worker 问题,对外口径写"偶发内部超时"。
- buildroot rootfs 缺 python3-tap(仅影响 LKFT 自身结果文件,worker 读 console TAP 不受影响)。
- 本地回调端点若节点无 parent/kernel_revision 会抛 telemetry 异常(结果已落库,仅日志报错;生产节点都有)。
- `notify.callback.token`(YAML)在 pull_labs 路径不参与鉴权——PR1 描述必须写真实机制(见 00 §8)。

---

## 5. 减重路线(如果要)

1. **把 TST_CASENAME 转发/kselftest-riscv 类推给上游 tuxrun**(PR2 就是干这个):worker 里相关注释与兜底可删 ~20 行。
2. **Python ≥3.12 用 `tarfile.extractall(filter="data")`**:手写逐成员检查可退化为纵深防御,删 ~40 行。
3. **把"拉取任务书+回传判读"抽成 kernelci-core 的通用 pull-lab 库**:这是上游该长的地方,不是 lab 侧该长的。
4. 保持现状也是合理的:lab 侧自足、可测试、单文件可审计,是"实习生交付物"的合理形态。

---

## 6. 交接清单(本轮所有产物)

- worker:`kernelci-pipeline/tools/riscv_pull_worker.py`(1008 行,本地闭环运行中)
- 补丁:`kernelci-pipeline/tools/tuxlava-kselftest-riscv.patch`(已打回 ~/.local 的 tuxlava 0.24.0)
- 测试:`my-work/tools/verify-lava-body.py`(契约)、`my-work/tools/verify-worker-guards.py`(守卫,新增)
- 工具:`kernelci-pipeline/src/config_drift.py`、`src/regression_tracker.py`、`doc/regression-tracking.md`
- 证据:`my-work/evidence/worker-out/kvm-run/`(直跑 7/2 ×2)、`my-work/evidence/worker-out/kvm-loop/`(闭环多单 + 服务脚本)
- 本地服务(若仍开着):8999 构件服务、8003 lava_callback、worker 轮询进程
- PR 路线图与口径:00 文档 §8(PR1=63 行 4 文件;worker PR;P2 工具 PR)

**一句话给下一个 agent:代码的厚度不是欠债,是"演示到生产"的学费已经付完;想减重,往上推,不往下砍。**
