# 中间层重构：设计、理由与实测记录

> **这份文件回答"为什么长这样、什么不能改、哪些话是被真跑证明的"。**
> 想知道怎么用，读 [`../README.md`](../README.md)；想知道接口形状，读
> [`../include/kci.hpp`](../include/kci.hpp)。
>
> 状态：**已实现并验证**（19 个模块 / 6,100 行，`ruff` 干净；三个测试真 QEMU 跑通，worker 线的结果
> 被真 pipeline 收下；GUI 可用）。第 8 节是当时定下的事，第 9 节是按时间排的实测记录 ——
> 里面每一条都写明了"谁验的、怎么验的"，没有一句是读代码推的。
>
> **代码在仓库根**：`lib/*.py` 是中间层，`run_latest.py` / `pull_worker.py` /
> `runday.py` / `table.py` / `results.py` / `gui.py` / `drift.py` 是入口。
>
> `lib/tests.py` 是测试目录（不是测试套件）：`TESTS` / `DEFAULT_TESTS` / `KVM_SKIP_TESTS`。
>
> **接口的 C++ 版在 `include/`**：`include/kci.hpp` 是总览（读它开始），
> `include/kci/{base,remote,local,engine,flow,view}.hpp` 按层拆开，只有声明和注释，
> `g++ -std=c++17` 能过。读接口看那里；读设计和理由看这份。
>
> **规矩：图纸可以领先实现，实现不许领先图纸。** 形状改了先改 `include/`，再改 `lib/`。
>
> `src/sketch/` 是你原来手写的那几个草稿（`kbuild`/`build`/`job`/`poller`…），一字未改，
> 留作对照；每个 `lib/*.py` 的模块 docstring 第一节就是对应草稿的原文。
>
> **GUI 方案在 `src/GUI.md`** —— 产品方向定在 GUI，那一篇回答「有哪些页、怎么选、在跑什么」。

## 0. 一句话

一次运行只有四件事：**挑一个 build → 把它变成本地的东西 → 在上面跑一个 test → 拿到一个 out**。
现在这棵树里，这四件事被摊在 7 个层、61 个模块、16.5k 行里；重写后它们是一个包、20 个模块、
大约 3k 行（含空行和 docstring），其中真正干活的 run path 约 2k 行。

## 1. 诊断：树为什么肿

### 1.1 数字

| 部分 | 行数 | 占比 |
|---|---|---|
| `scripts/` Python（68 个 `.py`） | 15,270 | |
| `scripts/*.sh` + `run.sh` | 1,863 | |
| 其中：`kcilib/`（库，39 个模块） | ~8,300 | 50% |
| 其中：五个入口 | ~1,965 | 12% |
| 其中：**守卫套件 `scripts/tools/guards/`** | **4,307 / 53 项检查 / 20 个模块** | **26%** |
| 其中：`tools/`（drift / trend / 验证） | ~1,000 | 6% |
| 真正跑一次 job 的 run path | ~2,900 | 18% |

守卫套件比 run path 还大——它不是"测试"，它是为了钉住一棵被拆得太细的树而长出来的第二棵树。

### 1.2 病根（每条都有坐标）

1. **层数 > 动词数。** `api / core / run / table / sink / model / deploy` 七层，动词只有三个（拉、跑、记）。同一个概念有第二份定义：`Build` 在 `table/build.py` 和 `model/builds.py` 各一份，`Job` 在 `table/` 和 `model/jobs.py` 各一份，`Outcome` 带一个给"已经不存在的 dict"用的兼容 shim（`model/jobs.py:1035-1066`）。
2. **为可测性造接缝，接缝反过来决定了代码形状。** 7 个"可以重新绑定的模块级名字"（`bake.stamp`、`jobrun.run_tuxrun`、`jobrun.run_command`、`poll.fetch_nodes`…），其中一个（`bake.download`）**没有任何人重绑**，注释还在引用一个已经被删掉的脚本（`run/delivery.py:139-141`）。`run_node` 必须写成模块级函数、不能用闭包，就是为了让测试能 `jobrun.run_command = stub`。
3. **同一件事有好几份实现**（这是"守卫"存在的原因，也是它们的上限）：
   - 两个下载器：`run/artifacts.py:151-253`（断点续传、416 恢复、大小证明）vs `run/delivery.py:46-66`（单发 urllib）
   - 两条 gunzip 路径：`delivery.py:207-231` vs `delivery.py:312-345`
   - 三个"这个缓存文件可信吗"：delivery 的 manifest、bake 的 sidecar、`artifacts.looks_complete` 读 gzip trailer
   - 三个 `/events` 读取点（一个活的、两个死的）、三个 job definition 抓取点（一个活的、两个死的）
   - 三个解析同一份 LAVA case 列表的地方（`callback.py` 三处）
   - 三个"没指定 timeout 时的默认值"：600 / 1800 / 1800
   - 两个 infra 判据（`jobrun.run_node` 直接 OR 三个谓词，`judge.is_infra_error` 再 OR 一遍同一组）
4. **一次 fetch 写两遍账本**（`run/jobrun.py:287-327` 和 `model/jobs.py:571-602`），而且两次的 verdict 来源不同（一个从 callback body 读回，一个从 console 重新判）。`log` 字段的含义取决于谁最后写。
5. **`local_server` 这一种投送模式吃掉 ~460 行。** 只有一次性 fetch 用它：本地下载构件 → 起 `http.server` → 探端口、证明端口是自己的、HEAD 比对字节 → 改写 definition 里 4 个 URL。worker 那条线完全不需要。
6. **烤盘缓存 483 行。** sidecar、按输入集 sha256 的键、tmp 老化、publish-by-rename、四条"缓存坏了就退化成不缓存"的分支——为了省一次 144MB 下载 + 一次 4GB mkfs。
7. **只被守卫调用的类。** `model/results.py`(225)、`model/dashboard.py`(194)、`model/stack.py`(285) 的生产调用者只有守卫和薄 CLI；`Results.text()` 甚至 `subprocess` 调 `./run.sh results`，就为了让"调用者看到的"和"运维看到的"措辞一致。
8. **为一次没发生的搬迁造的地基。** `core/layout.py` 4 个 Category、`legacy_map()`、`category_of()`（任何未登记路径直接 raise），其中 6 个 accessor 生产代码里没人用；`policy.py` 107 行常量表有 12 个字段没有读者。
9. **测试假件要手工同步。** `guards/support.py` 里的 `_FakeSession` / `stub_requests` / `_run_job_config` / `_poll_config` 是"run_node 和 handle_event 读到的每一个字段"的手抄副本——`RunConfig` 加一个字段，守卫不会红，只会失效。
10. **死了但没删的 API。** `KernelCI.events`、`KernelCI.post`、`JobPuller`（整个类）、两个 `get_node`、`_source_for`、`KbuildPuller.newest/last_days`、布局模块的一多半 accessor。

一句话概括：**不是代码写得烂，是每一件真事都被包了三层，而为了证明这三层没写错，又长出了第四层。**

## 2. 目标形状

```
   入口 / 查看器（选择器）        run_latest  pull_worker  runday  table  gui  results  drift
        |  只用中间层，不 import 任何实现细节
   中间层 lib/                    kbuild  build  kjob  job  out        <- 你要的那层
        |                          poller                         <- 轮转（最复杂，独立一个类）
        |                          judge  runner  sink             <- 三个"必须做对"的算法
        |                          api  layout  config  errors     <- 地板
   外面                          KernelCI HTTP · tuxrun/QEMU · 文件系统
```

四个动词，四个类，一对多关系一目了然：

| 动词 | 类 | 草稿里的名字 |
|---|---|---|
| API 里有哪些 build | `kbuild.Kbuild` / `Kbuilds` | `class kbuild` |
| 把它变成本地 | `build.Build` / `Builds` | `class build` |
| 在上面跑一个 test | `job.Job` / `Jobs` | `class job` |
| 结果 | `out.Outcome` | `class out` |
| 一次后台活动（跑/拉/worker…） | `run.Run` | 草稿里没有这个词 |
| 轮转（看队列、按天补跑、去重、重投） | `poller.Poller` | `class poller` |
| API 里有哪些 job | `kjob.Kjob` / `Kjobs` | `class kjob` |

上层是**选择器**和**查看器**，都只有一件事：

- 选择器：`run_latest`（最新的）、`runday`（某一天的）、`pull_worker`（API 队列）、`table`（本地表减账本）——**四个选择器，一个 executor（`Job.run()`）**。
- 查看器：`gui`、`results`、`drift`——只读同一批对象，不自己算数。

### 关于"抽象接口"

**只在真的有两个实现的地方留接口**（`sink.Sink`：账本 + 回调）。其余不设 ABC / Protocol：
只有一个实现的抽象接口，唯一作用就是给假件留门——那正是要去掉的东西。

**唯一必须保持"不像对象"的边界是 job definition**：它继续是一个普通 dict，和上游模板渲染出来的
同构。理由不是偷懒，是旧树用血写下的：`run_node` 一旦能分辨"这个定义是我们造的"还是"API 派发的"，
本地那条线的绿就不再是 worker 那条线的证据（`REFACTOR-C-BRIEF.md` 拒绝清单第 1 条）。
所以 `job.Job` 可以**包**一个 definition，但 `run()` 不允许看它是哪来的。

### 与 REFACTOR-C／D 的关系（要说清）

这次的草稿和当年被否掉的东西长得很像，所以先把账对清楚。

**C 轮明确拒绝、这份设计同样拒绝的：**

1. ~~把 `JobDefinition` 换成模型类 / 给 `run_node` 换 dataclass 返回值~~ → 不换：definition 仍是普通 dict，
   和上游模板渲染同构；`Job` 只是外壳，`run()` 不允许分辨它是谁造的。
2. ~~补 `ABC`/`Protocol`/`isinstance` 断言~~ → 不补：只有一个实现的抽象接口，唯一作用是给假件留门。
3. ~~造统一的 `wiring.py` / 组合根 / 容器~~ → 不造：入口各自组装，`config.py` 只把 flag 变成小对象。
4. ~~把 callback token 放进配置对象~~ → 不放：投递那一刻才从环境读。
5. ~~给账本的 `source` 加闭集校验~~ → 不加：那里 raise 会让**整条记录消失**，比写歪一个可见字段糟得多。

**D 轮 phase 2 把并排的接口层 `scripts/kci/` 合并回 `kcilib/model/`，理由是数据：**
`kci` 2,501 行 vs `kcilib` 5,521 行；**0** 个生产模块只 import `kci`；**5/5** 个入口同时 import 两者；
60 处纯转发的调用点。结论写在 brief 里：**「`kci` 不是把 `kcilib` 藏起来的那张脸，而是并排的第二套词汇。」**

**这份设计为什么不是那个 `kci`：**

- `lib/` 是**替换**整个库，不是包在 `kcilib` 外面的一层皮。没有下层可以转发，也就没有第二种词汇：
  入口拿到的是 `Kbuild`／`Build`／`Job`／`Outcome` 本身，不是「`BuildRef` → `Kbuild` → `Job` + 18 行胶水」。
- 规模上它是 19 个模块对 4 个概念，没有门面模块、没有注册表、没有 `sources.py` 那种 chooser 层：
  选择器（谁该跑）就是四个入口，各自 40–70 行。
- D 轮 phase 2 的失败模式是「**同一个概念两个名字**」；这里的失败模式只可能是「概念又被拆细」，
  所以规矩写成一条：**一个事实一个 owner，出现第二份就是 bug**（见 §6）。

**唯一回来的东西是 C 轮没否的那一件：一层薄的、有名字的中间层词汇。**
C 轮否的是「再加一层 class 化的转发」，不是「给四件事起名字」。

### 判决的基准：仓库里那两份真 console

`scripts/fixtures/tuxrun-pass.log`（74KB）与 `tuxrun-fail.log`（13KB）是仓库里唯一的真实 tuxrun console
基准，`.gitignore` 为它们留了例外，**不许删**（删过一次，新克隆上 `verify-lava-body.py` 直接
`FileNotFoundError`，而闸门把 traceback 当成了绿）。实测它们的形状：

| | 内容 | 对 `judge.py` 的意义 |
|---|---|---|
| pass | 714 行；剥掉 ANSI 后是 `2026-09-10T00:50:50 ok 1 selftests: riscv: hwprobe` 这种形状，共 4 条 TAP | 解析必须容忍「时间戳 + 空格」前缀；label 形如 `selftests: riscv: <name>` |
| fail | 137 行，**一条 TAP 都没有**，结尾是 `JobCanceled: The job was canceled` + `error_type: Canceled` | 直接落进「没有 TAP 就是 fail、永不为 pass」那条规则 |

顺带：pass 那份的头部写着 `Validating that http://172.17.0.1:8998/Image exists` —— 那就是本地
artifact server 当年存在的证据，也正是实验 1 拿掉的东西（构件现在用 `file://` 由 tuxrun
只读 bind-mount 进容器）。

## 3. 模块对照表

| 新 | 行数（骨架） | 取代旧树里的（文件行数） |
|---|---|---|
| `lib/api.py` | 84 | `kcilib/api.py`(217) + `api.client()`/`node_counts()` |
| `lib/kbuild.py` | 109 | `model/nodes.py`(454) + `table/build.BuildQuery`(40) + `builds_from_production_api` |
| `lib/kjob.py` | 96 | 同上（`nodes.py` 的 `KernelCINode`/`JobPuller`，其中 `from_events` 是死代码） |
| `lib/build.py` | 163 | `table/build.py`(295) + `table/buildindex.py`(88) + `model/builds.py`(139) + `deploy/provision.py`(132) |
| `lib/tests.py` | 60 | 测试目录 + 跑它的环境默认值（device/runtime）。它不 import 任何东西，所以 `build`/`job`/`config`/`sink` 都能用它 —— 这条"谁都能用的叶子模块"是消掉 import 环的关键 |
| `lib/job.py` | 127 | `model/jobs.py`(1,070) + `model/sources.py`(107) + `core/params.py`(47) + `policy.DEFAULT_TESTS` |
| `lib/out.py` | 79 | `model/jobs.Outcome`(141，含 dict shim) + `core/ledger.py`(196) 的键集 |
| `lib/judge.py` | 67 | `run/judge.py`(387) |
| `lib/runner.py` | 39 | `run/runner.py`(109) |
| `lib/sink.py` | 113 | `sink.py`(162) + `run/callback.py`(344) + 账本读写 |
| `lib/poller.py` | 107 | `run/poll.py`(411) + `core/state.py`(177) + 投递分类 |
| `lib/layout.py` | 96 | `core/layout.py`(274，去掉 Category/legacy_map) + `core/retention.py`(197) 的路径部分 |
| `lib/config.py` | 130 | `core/cli.py`(190) + `core/config.py`(169) + `core/ports.py`(163) |
| `lib/re.py` | 71 | `model/results.py`(225) + `model/views.py`(45) + `tools/regression_tracker.py`(360) 的读侧 |
| `lib/drift.py` | 66 | `tools/config_drift.py`(352) |
| `lib/gui.py` | 84 | `dashboard.py`(958) + `model/dashboard.py`(194) |
| `lib/errors.py` | 53 | 散在 `judge.py` 的 `EXIT_*` + `Callback*Error` + `ArtifactServerError` |
| 入口 7 个 | 38–79 | 5 个入口(1,965) + `supervise-run.sh` + `run.sh` 里的内联 Python |

## 4. 建议直接删掉的东西

| 删什么 | 行数 | 为什么 |
|---|---|---|
| `scripts/tools/guards/**` 整个 | 4,307 | 它钉的是"这棵树被拆成这样"这件事本身；树重写后 53 项检查里绝大多数没有对象。留下 2 个：`verify-lava-body.py`（把真 body 喂给上游真 parser）和 ruff |
| `local_server` 投送模式 + artifact server | ~460 | 只服务一次性 fetch 一条线。**先做实验 1**：tuxrun 的 `--kernel/--tests` 能不能吃 `file://`（烤出来的 rootfs 已经是这么传的） |
| 烤盘缓存（`run/bake.py` 的缓存机制） | ~350 | 保留 `mkfs.ext4 -d` 本身（这是真的需要）；去掉 sidecar / 键 / 老化 / 降级，只留"文件在就复用" |
| sqlite build index | ~380 | `work/downloads/<id>/build.json` 就能推导出整张表 |
| 双写账本 + `record_fields` 机制 | ~90 | 一次运行一个 verdict，一个写者 |
| `layout` 的 Category / `legacy_map` / 未使用 accessor | ~120 | 一次没发生的搬迁的地基 |
| `core/policy.py` 常量表 | 107 | 每个数字回到使用它的地方；只留部署级旋钮 |
| 7 个可重绑接缝 | ~60 | 没有守卫就没有接缝的消费者 |
| `model/results.py` / `model/dashboard.py` / `model/stack.py` | 704 | 只被守卫调用的类 |
| 死 API 面（`KernelCI.events/post`、`JobPuller`、`get_node`×2、`_source_for`、`KbuildPuller.newest/last_days`） | ~180 | 没有调用者 |
| `Outcome` 的 dict 兼容 shim | ~35 | 兼容目标（`table/localrun.py`）已被删除 |
| `run.sh` 里内联的 76 行 Python（prune） | 76 | `retention.plan()` 已经把它接走了 |

**合计约 7,000 行（不含注释与空行）在这张表里。**

## 5. 必须逐字节保住的东西

重写不等于可以随便改契约。下面这些一旦变了，坏的是"没人会报错的错"：

| 契约 | 位置 | 谁在依赖 |
|---|---|---|
| 退出码 0 / 1 / 3 | `errors.py` | `./run.sh fetch` 的退出码**就是**判决本身；3 对齐 LAVA 的 incomplete |
| **callback body（LAVA 兼容）** | `sink.body()` | pipeline 的 callback 端点没有第二种格式的 parser，格式不对结果**静默消失**；`verify-lava-body.py` 用真 parser 回放 |
| **退出码 0 / 1 / 3** | `errors.py` | `./run.sh fetch` 的退出码**就是**判决本身；3 对齐 LAVA 的 incomplete |
| **body 的 `status` 不许出现「账本说红、pipeline 说绿」** | `sink._status()` | 只有 console 真的有证据（一条失败的 TAP 行、一条失败的 boot case）才 Complete；否则 Incomplete。合成出来的 suite case 不算证据 |
| 回调 `Authorization: Token <token>`，token 只在投递那一刻从环境读 | `sink.callback_token()` | token 一旦进 state 文件，state 文件就变成凭据 |
| 三条线共用同一个 executor | `job.Job.run()` | 本地那条线是 worker 那条线的证据，这是整棵树最重要的结构事实 |
| `--api-config-name` / `--storage-config-name` 必须与部署一致 | `sink.lava_body()` | 不一致时回调端找不到节点，结果静默丢失 |

**其余按你的决定自由**（这笔账要认）：

| 放开的东西 | 后果 |
|---|---|
| 账本键集与路径（旧：`work/results/<build-id>/<test>.json`，13 键） | 新树写 `var/results/...`，**旧的 `work/results/` 历史不会被新读者读到**；切换时需要迁移或认了重跑 |
| `work/` 路径布局 | 新树用 `var/`（见 §7），旧树继续用 `work/`；两棵树不共享目录，互不污染 |
| worker state 文件形状 | 只影响 worker 自己；`--state-file` 仍然给运维一个显式入口 |
| tuxrun argv 的顺序与省略规则 | 由新树自己重新定一次，并用一次真跑验证（这是唯一能证明它的方法） |
| 五个入口的 flag 名 | 新入口是 `run_latest.py` / `pull_worker.py` / `runday.py`（+ 后续 table/results/gui/drift）；`run.sh` 暂时不动，切换那一次再改指向 |
| `run.sh` 子命令表 | 同上，切换时一起改 |

## 6. 新树的三条规矩

1. **一层一件事，一个事实一个 owner。** 没有第二个 `Build`，没有第二个下载器，没有第二处拼 argv。
2. **不为测试造接缝。** 需要假件时把对象**传进去**（`Job.run(sink_=...)`、`Poller(api, run=...)`），
   绝不重新绑定模块级名字，也绝不为了可测性把一个函数拆成两个模块。
3. **docstring 说"是什么"，不说"为什么长这样"。** 一个模块 1–3 行，一个方法 1 行；长理由进
   `docs/`，不进代码。

## 7. 三个实验的结论（已经做过）

1. **`file://` 喂 tuxrun：可以，而且比预期更好。** tuxrun 1.10.0 的每一个 artefact 选项
   （`--kernel` `--rootfs` `--modules` `--dtb` `--job-definition` …）都走 `tuxrun.utils.pathurlnone`：
   接受本地路径或 `file://`，并且**只读 bind-mount 进容器**（`__main__.py:315`）。
   `--parameters KSELFTEST=<path>` 同样过 `pathurlnone`（`argparse.py:97`）。
   实测：`tuxrun --kernel file:///nonexistent/Image` 报 `no such file or directory`（证明走的就是这条路径）。
   **结论：本地 HTTP artifact server 整块不需要了** —— 下载到本地、把 `file://` 路径递给 tuxrun 即可。
   连带删掉：`delivery.py` 的服务器生命周期、端口探测、gateway 探测、"服务出去的字节必须一致"的证明、
   改 definition URL 的那套（合计约 460 行，占旧 run path 的六分之一）。
2. **一次烤盘 66–124 秒**（`work/run-full.log` 里两次实测：66.1s、123.8s；144MB 下载 + 4GB `mkfs.ext4`）。
   所以缓存机制该删，但"同名文件在就复用"这 6 行该留：省下的是每次 1–2 分钟。
   不做 sidecar、不做键管理、不做老化、不做"缓存坏了退化成不烤"的四条分支。
3. **本地表可由 `var/downloads/*/build.json` 推导**：是。sqlite 索引（`buildindex` + `table/build.py`
   的查询部分，约 380 行）删掉，`table index` 变成"抓 API 清单、写 sidecar"。

**另外一条不是实验、是决定：新树的工作目录用 `var/` 而不是 `work/`。**
两棵树并行期间，旧读者（`./run.sh results`、`table todo`、GUI）遇到读不懂的记录会直接 raise，
共用一个目录等于让一棵树的运行变成另一棵树的故障。`KCI_WORK_DIR` 仍然可以整体挪。

## 8. 已定的事（2026-09-19）

| 问题 | 决定 |
|---|---|
| 新树落在哪 | **仓库根 `lib/` 包 + 仓库根入口脚本**（按你的草稿） |
| 旧树怎么办 | **原地不动**，两棵树并行跑一段时间再决定；`run.sh` 切换指向是最后一步 |
| 契约保到什么程度 | **只逐字节保 callback body + 退出码 0/1/3**（外加 token 读取时机与两条配置名），其余自由 |
| 这一轮做到哪 | **run path + poller**：`kbuild → build → job → out` 一条线跑通，再做 worker 线；`gui / results / drift / table / re` 的骨架先放着，实现留到下一轮 |
| 产品方向 | **GUI 是主要交付**（`src/GUI.md`）。所以 `Run`（一次后台活动）与 `Filter`（筛选条件）的形状现在就定下来 —— 它们会反过来影响 `Job`（`id()`）和 `Records`（`series()`），定晚了要返工 |
| 目录 | `s/` 已删（旧树的导读镜像，可再生）；`ss/` → `src/`（设计文档 + 你的草稿 `sketch/`）；C++ 接口 → `include/`；Python → 根目录 `lib/` + 根目录入口 |

## 9. 记录：一次真跑（Run.1 / Run.2）

`lib/` 全部实现（19 个模块、6,100 行），`ruff` 干净，`include/` 图纸同步（988 行）。**一次真跑**（生产 API → 真下载 →
真烤盘 → 真 QEMU → 真 TAP → 真账本）：

| test | 结果 | 证据 |
|---|---|---|
| `boot` | **pass / 0** | console 结尾 `{'definition': 'lava', 'case': 'job', 'result': 'pass'}` |
| `kselftest-riscv` | **pass / 0** | 10 个顶层 selftest 全过，132 条 TAP 无一条 `not ok`（含 `pointer_masking`） |
| `kselftest-kvm` | 12 个精选用例（3 个 SKIP） | 排除表按当天实测更新：`arch_timer`（aarch64 的测试，立刻 exit 254）、`demand_paging_test`（120s 超时） |

这次真跑证明了三件事：

1. **`file://` 那条路成立**：tuxrun 的 argv 里 kernel / rootfs / kselftest 全是本地路径
   （`--kernel file://... --rootfs file://... KSELFTEST=file://...`），本地 HTTP artifact server
   确实不需要了。
2. **烤盘 + 复用成立**：144MB 下载 → `mkfs.ext4 -d` → `var/baked/<key>.ext4`，第二次同输入直接复用。
3. **boot 不再烤盘**：旧 `build_command` 给每个 boot job 都塞 definition 里的 rootfs，于是每次都烤一张
   4GB 盘；新树按目录里 `boot.rootfs = False` 直接不传 `--rootfs`，tuxrun 用它自带的 buildroot 盘 ——
   真跑证明能启动（`guest booted`），每个 boot job 省下 144MB 下载 + 66~124s 烤盘。
4. **失败分类成立**：一次 404（rootfs URL 写错）、一次 SSL 中断、一次 API 不通，全部变成
   `incomplete` / 退出码 3 并照样写账本 —— 没有一次变成"测试失败"。

回归（这次踩到的、已修）：代理坏掉时 `requests` 的 SSLError 会穿透成 traceback + 退出码 1
（现在下载层只抛自己的异常类型，入口把 `KciError`/`OSError` 变成 infra 退 3）；
`Kbuild.usable()` 曾要求真实节点根本不存在的 `data.arch`（会把 180/180 个生产 build 判死）。

## 9.1 记录：worker 线 + 真回调（Run.3）

本地全栈起来、种下 3 个 job 节点，然后**用新树的 worker** 跑：

```
python3 pull_worker.py --api-url http://127.0.0.1:8001 --once
```

pipeline 侧的结果（用旧树的读者 `./run.sh report` 交叉验证，两边一致）：

| 节点 | state | result | 内核 |
|---|---|---|---|
| `baseline-riscv-pull-labs` | done | **pass** | asoc-fix-v7.3-rc3-803-ge3bfd25 |
| `kselftest-riscv-pull-labs` | done | **pass** | 同上 |
| `kselftest-kvm-pull-labs` | done | **pass** | 同上 |

节点上还留着 `lava_log` / `lava_logs` / `callback_data` —— 那就是我们 POST 过去的 body 被真
`lava_callback` 收下、由上游代码解析后存下来的证据。账本里同一批是 6 条：
`source=fetch` 3 条（Run.1/Run.2）+ `source=worker` 3 条（Run.3）。

这一轮还顺带证明了三件只有走 definition 才会发生的事：

1. **API 派下来的 definition 用它的 URL，只有宿主必须准备的才本地化**：argv 是
   `--kernel http://172.17.0.1:8999/Image`（部署自己的构件服务）＋ `--rootfs file://…/var/baked/<key>.ext4`
   （我们在这个主机上烤的）＋ `KSELFTEST=https://files.kernelci.org/…`（远端）。容器里做不了 mkfs，
   所以只有盘是本地的。
2. **kvm 那份 definition 的 kselftest 被拉到本地**只为读测试名单，然后 tuxrun 拿到的是本地
   `file://` 加 12 个 `TST_CASENAME=kvm:…`（省掉容器里再下一次 100MB）。
3. **worker 的回调地址来自 definition，不是命令行**：`Run.sinks()` 在没有 `--callback-url` 时只有
   账本，所以 worker 必须自己带一个会从 definition 解析地址的 Callback —— 否则它跑完只会写账本，
   而 pipeline 和账本都是绿的。

## 9.2 记录：GUI 可用

`python3 gui.py --port 8080` → 一张页面，四个区：**filter / builds / jobs / runs**，外加分析块。

对着真数据验过（HTTP 打进去，不是看代码）：

| 验的什么 | 结果 |
|---|---|
| `GET /` | 2 个 build、6 条记录、活动数都渲染出来了；表格里的行来自真表＋真账本 |
| `GET /summary.json` | `{builds, jobs, runs, ledger, table, actions}` —— 页面和机器读的是同一份 |
| 过滤 `?ran=never` / `?tree=riscv` / `?test=…&ran=ever` / `?origin=local` | 各自返回 1 行（真过滤，不是摆设） |
| `POST /api/actions/results` | 起了一个活动，跑的是 `python3 results.py`（= 运维手打的那条） |
| `GET /api/runs/<id>/log?offset=0` | 返回那个活动的真实输出（账本报告），带新 offset（增量 tail 的接口） |
| 写者位被占时再起写动作 | **HTTP 409** + 说清是谁在写、为什么一次只能一个 |
| 只读动作在写者忙时 | 照常能起 |
| `POST /api/runs/<id>/cancel` | `stopped: true`，活动变成 `cancelled` |

后来又补上 `src/GUI.md` 里点名、第一版漏掉的三件：

* `GET /api/analysis/trend?test=&scope=` 与 `GET /api/analysis/drift?older=&newer=`；
* **勾两个 build → 点 compare → 就地看到三栏差异**（`POST /compare` 303 到 `/?pick=a&pick=b`，
  页面直接渲染 added/removed/changed，不用起命令）；
* 回归**时间轴**：一次运行一格（绿 pass / 红 fail / 灰 skip），回归点描边，鼠标悬停给
  build/时间/判决/来源。

三件被实现钉住的设计：

1. **按钮就是命令**：`Gui.command()` 拼出来的是 `python3 table.py pull --build …`、
   `python3 runtime/…`，和运维手打的一字不差。页面能做的，命令行也能做。
2. **页面不算任何东西**：判决来自 `judge`、统计来自 `Records`、缺口来自 `todo()`、回归来自
   `transitions()`。旧 GUI 里同一份统计有四处实现，JS 里还抄了第四份判决词表。
3. **重启不丢**：活动落成 `var/runs/<id>/{run.json,run.log}`，`Run.load_all()` 扫目录；
   pid 已死的 `running` 在扫的时候就被结算掉。

## 9.3 记录：GUI 第二版 —— 对应关系是被建立的

第一版把本地和远端按 `build_id` 合成一行 —— 那等于**凭空假设**了两边是同一个东西。
两棵树上两个相等的值不是同一个东西：本地目录叫 `6aadee…` 只能说明名字一样。

第二版的模型：

| | 是什么 | 谁说了算 |
|---|---|---|
| 远端 | API 有什么（build / job），当前查询的条件是什么 | API 的回答 |
| 本地 | 我们握着什么字节、跑过什么、账本说什么 | 文件系统 + 账本 |
| **对应关系** | 这份本地拷贝来自哪个远端 build | **拉取时写下的记录**：`var/downloads/<id>/provenance.json`，每个构件一行（URL、证明的字节数、时间、是否真的传过） |

于是「本地」那一行必须说清自己属于哪一种，而页面不许含糊：

```
pulled 3 artifact(s) from 172.17.0.1:8999, files.kernelci.org (38.9 MiB) at 2026-09-19T11:58:04Z
no pull recorded for these bytes (a card in the local table)     ← 字节在，来源不明
registered from the API node …, nothing pulled yet
made here (published locally)                                     ← 从没从 API 拉过
empty
远端列：no remote counterpart                                      ← 且总紧挨着「这次问的查询」
```

页面因此按功能分开：`/` `/remote` `/local` `/local/<id>` `/pull` `/jobs` `/runs` `/worker`
`/analysis` —— 一个功能一页，每个条件都是选择框，每个对象都是勾选，**没有一处要你手打 id**。
「拉取」是它自己的一页：选条件 → 看候选 → 勾选 → 拉 → 拉完看得见留下的记录。

### 一句自我核对：GUI 比设计里估的大

设计里估页面约 400–600 行，实际 `lib/gui.py` 是 1,772 行（旧 dashboard 是 958 行，我批评过它）。
多出来的部分不是重复计算（"页面不算任何东西"这条守住了），而是**九个路由各自的表格渲染**
加上内联的 HTML/CSS/JS。这笔账值得记在这里：如果哪天要把它压小，压的应该是"页数"，
不是"把统计挪回页面里"。

## 10. 实施顺序（每一步都能单独验证）

```
1. 地板：errors / layout / api / config            ← 已可运行（flag 解析是真的）
2. judge + runner（纯函数，最好验：喂真 console 判分、拼 argv 但不跑）
3. kbuild / build / out / sink                     ← Run.1：run_latest 一条线端到端跑通一次真 QEMU
4. job 的 definition 渲染 + KVM 子集 + 烤盘复用     ← Run.2：boot / kselftest-riscv / kselftest-kvm 各一次
5. poller（cursor / seen / pending / flock / 重投）  ← Run.3：本地栈 + worker --once 跑通，回调真的被 pipeline 收下
6. run.sh 改指向新入口（旧树仍在），并行对跑一段时间
7. **GUI**（`src/GUI.md`）：先 `Run` + `Filter` + 账本读法，再四个页面，
   最后 C++ 那层（`include/` 已经画好）
8. 查看器 results / drift / table / runday 收尾
9. 切换：删旧树、删守卫套件、重写 README 与 ARCHITECTURE
```

验证纪律：第 3、4 步各要一次**真跑**（真下载、真 QEMU、真 TAP），第 5 步要一次**真回调**
（本地栈 + `verify-lava-body.py` 用上游真 parser 回放）。没有真跑的步骤不算完成。
