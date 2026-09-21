# kernelci-riscv

为 [riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49) 里的 SOW
做 RISC-V KernelCI 自动化：在 QEMU 上对 Linux riscv Vector/Hypervisor 扩展做持续回归测试，
测试 profile 提交给上游的 kernelci-pipeline。

一次运行是四件事：**挑一个构建、把它取到本地、在它上面跑一个测试、拿到一个结果。**
本仓库里的一切要么就是这件事本身，要么是一个决定*挑哪个*构建的选择器，
要么是一个展示拿回来了什么的查看器。

## 一棵树

这个仓库曾经装着同一件事的两份实现——`scripts/` 下随发布走的树，用 `run.sh` 当分发入口，
以及 `lib/` 下的重写版，一条命令一个文件。**重写赢了，旧树已删除**（2026-09-20）：
旧树最后的部分在一个提交大小的步骤里走掉，每一块被什么替换了列在下面的
[采用新树：什么替换了什么](#采用新树什么替换了什么) 里。一段简短的历史，
因为那些名字还会在文档里冒出来：

| 曾经 | 现在 |
|---|---|
| `run.sh <subcommand>`（唯一的命令界面，504 行） | 运行期用 `python3 <entry>.py`，部署用 `deploy/*.sh`，门禁用 `python3 verify.py` |
| `scripts/{local-jobs,results,riscv_pull_worker,fetch-and-run-latest}.py`、`supervise-run.sh`、`dashboard.py` | `table.py`、`results.py`、`pull_worker.py`、`run_latest.py` + `provision.py`、`runday.py`、`gui.py` |
| `scripts/run-local-stack.sh`、`stack-seed.sh`、`local-instance-init.sh`、`net-preflight.sh` | `deploy/stack.sh`、`deploy/seed.sh`、`deploy/instance-init.sh`、`deploy/net-preflight.sh` |
| `kcilib/`（36 个模块，约 8.1k 行） | `lib/`（同样的想法，一套词汇） |
| `work/`（旧工作区） | `var/` |
| `./run.sh verify`（validate_yaml + kcilib 守卫套件） | `python3 verify.py` |

工作区是 `var/`，而且只是 `var/`：`lib/layout.py` 拥有它里面的每一条路径，
`$KCI_WORK_DIR` 能把它移到任何地方。它的账本（`var/results/`）是历史，永不修剪；
里面其它一切都可以重新生成。

## 怎么跑起来

所有命令都在仓库根目录下运行。

```bash
# one test on the newest production riscv build (exit status IS the verdict:
# 0 pass, 1 test failure, 3 infrastructure)
python3 run_latest.py --test boot
python3 run_latest.py --test kselftest-riscv
python3 run_latest.py --test kselftest-kvm

# the resident worker: claim jobs from a KernelCI events API, run them, report
python3 pull_worker.py --api-url http://127.0.0.1:8001 --once
python3 pull_worker.py --api-url http://127.0.0.1:8001        # keep polling

# a day's builds, skipping whatever the ledger already has
python3 runday.py --days 1

# the local table, offline
python3 table.py index                 # ask the API which builds exist
python3 table.py pull --build <id>     # materialize one (repeatable)
python3 table.py jobs | todo | summary | run

# the ledger, read back; config drift between two builds
python3 results.py [--build ID] [--json]
python3 drift.py [--older ID] [--newer ID]

# the page
python3 gui.py --port 8080             # http://127.0.0.1:8080
python3 gui.py --port 8080 --api-url http://127.0.0.1:8001   # $KCI_API_URL works too
#   ... and it does not have to be restarted to ask a different API: the `api` box in
#       its filter bar switches to `production` (https://api.kernelci.org) or to any
#       http(s) address you type, one page load at a time

# the gate: everything that must be true before this tree is deployed
python3 verify.py                      # --quick skips the page renders; --base URL adds the HTTP sweep

# deployment: the local full stack (its own directory - see README's deploy/ row)
deploy/setup.sh                        # clones + patches + this deployment's local configuration
deploy/stack.sh --seed                 # api/db/redis/storage/ssh + artifact server + callback + scheduler, then seed
deploy/stop.sh                         # stop the host services it recorded, then the compose stack
```

页面是双语的：`?lang=zh`（或它头部里的开关，它会在 `kci_lang` cookie 里记住你的选择）
画出同一页的中文版。它问哪个 API 由过滤栏里的 `api` 框决定，它是一个 URL 键而不是设置：
`?api=production` 是公共 API（`https://api.kernelci.org`），`?api=local` 是本地栈，
`?api=http://127.0.0.1:8001` 是把同一件事写全——任何 `http(s)` 地址都行，
既不是已知名字也不是地址的值会被忽略（页面会这么说，并读取基址 `--api-url` /
`$KCI_API_URL` 给它的那个）。`api` 会搭在每一条链接上，所以你收藏或复制的页面回答的
就是它 URL 里写的问题，而它真正读到的地址会打印在它自己的查询行里
（`asked the API: https://api.kernelci.org: kind=kbuild …`）——在看到一行很小的行数之前，
这行值得先读。它打印的每一句话都住在 `lib/i18n/` 里；`python3 -m lib.i18n --check lib/gui`
是这个包的测试（缺键、没人用的键、没翻译的行），`--map` 会说明 `lib/gui/` 的哪一行
读了每一句。

**五个页面、一条过滤栏、一个实时面板。** `builds | jobs | runs | worker | analysis`。
`/` 是合并后的 builds 页面——一个构建 id 一行，三件事分成三个相邻的列
（`card | bytes | act`，每个都可能是 `-`）——而 `/remote`、`/local` 和 `/pull` 是
**302 重定向**，会把整个查询带上，所以一个老的收藏仍然问它一直在问的那个问题。
每个生效的轴都会打印出来，**包括它的默认值**，形式是 `key: value`；`rows` 和 `days`
是滑块，也可以直接输入；页面会打印它读了多少行、API 有多少行、它自己的过滤丢了多少行。
正在跑的活动带一个 spinner 出现在侧面板里，结束只播报一次——重新加载不会重播旧的。

**它被重做过，记录在 `docs/gui-rework/` 里。** 索引从
[`docs/gui-rework/README.md`](docs/gui-rework/README.md) 开始，操作者提出的每一点以及
它们的下落看 [`REQUIREMENTS.md`](docs/gui-rework/REQUIREMENTS.md)，每个结论背后的测量看
[`CHANGELOG.md`](docs/gui-rework/CHANGELOG.md)。
验收 harness 是 `docs/gui-rework/tools/accept.py`——十六项检查就是操作者自己的需求，
每项都打印决定它的证据；用 `--base` 对着一个活实例跑它。

任何入口上的 `--help` 列出它的旗标。worker 的 `--runtime` 是*实验室*名字
（`pull-labs-riscv`，也就是 job 节点的 `data.runtime` 说的那个）；`--container-runtime`
是 tuxrun 跑 dispatcher 镜像所用的东西（`docker`）。

这是快速上手。完整手册——环境、本地栈、worker、prune、verify，以及所有会出错的地方——
在 [`docs/RUNBOOK.md`](docs/RUNBOOK.md)。

## 验证了什么，怎么验证的

下面每一条断言都来自一次真实运行，而不是读代码。

| 断言 | 证据 |
|---|---|
| 单发那条线能启动一个真实内核 | `var/results/<build>/boot.json`——`pass`，控制台归档在 `var/logs/` 下 |
| 两个 kselftest 套件能跑 | `kselftest-kvm`：9 通过 / 3 跳过——跳过的 3 个要的是模拟 CPU 没有暴露的 ISA 扩展（`sbi-pmu`、`aia`、`h`），不是缺硬件。`kselftest-riscv`：10 个 TAP 测试，结论随构建而变——2026-09-20 的六个构建里有四个 `pointer_masking` 的 `constraint` 断言失败（PMLEN>=1），一个 10/10 通过 |
| worker 那条线能上报进真实流水线 | 本地栈种入 3 个 job 节点，`pull_worker.py --once` 跑掉它们，流水线自己的节点状态读出来是 `done/pass`，带我们的 `callback_data`、`lava_log`、`lava_logs` |
| callback body 被上游接受 | 生成的 body 用真实的 `kernelci.runtime.lava.Callback` 回放；它的 `get_job_status()`、逐测试层级和 infra 旗标都能正确读回——四个用例、23 项检查，`docs/gui-rework/tools/verify_callback_body.py` |
| 这棵树保持它的形状 | `docs/gui-rework/tools/check_structure.py`：每个入口把自己的 `KciError` 变成自己的退出码，只有一个模块写账本，只有一个模块给 tuxrun 二进制命名，只有 `lib/layout.py` 拼出工作区路径，只有一个 `lava_body`，每个入口都打印自己的用法 |
| 以上全部一次 | `python3 verify.py`——操作者跑的那条命令，它的退出码就是答案 |
| 退出码说到做到 | 0 通过、1 测试失败、3 基础设施——三种都在真实运行里见过；取不到的 artifact 或 API 会变成 `incomplete`，并且**仍然写账本** |
| 页面能用 | 用 HTTP 驱动：过滤、动作作为子进程、实时日志 tail、取消、单写者规则、drift 和 trend |
| 页面不用重启就能问公共 API | 在一个跑在本地栈上的实例上，`?api=production` 用 `showing 10 of …` 回答同一个查询，而本地栈回答 2，它的查询行写着 `https://api.kernelci.org`，而 `?api=https://api.kernelci.org` 渲染出逐字节相同的结果（34113），每条链接都写 `api=production` |
| 页面跟得上按钮做的事 | 另一个进程写一条账本记录，同一个 URL——不重启——从 `0 record(s)` 变成 `1 record(s)`，它的 `/jobs` 行从 `0 / - / -` 变成 `1 / pass / <time>`；有 300 张卡时，一次请求把表和账本各解析**一次**（0.035s），而不是 207 次 |
| 动作按钮就地汇报，从不倾倒 JSON | 把*渲染后*页面的脚本放进 node，对着手写的 DOM stub 跑：提交被拦截（`preventDefault`），POST 发往表单自己的 action，2xx 把 `started <id>: <argv>` 写进**那个表单的**状态行，409 把服务端自己的拒绝写在那里，GET 过滤表单留给浏览器——5/5 |
| 「register this window」真的注册了它 | 隔离的工作区：`table.py index --api-url https://api.kernelci.org --days 1 --limit 5` 把本地表从 3 张卡变成 7 张（`net-next`、`mainline/master`、`riscv/fixes`）；修复之前那个按钮跑 `index` 时没带 `--api-url`，读的是本地栈 |
| 面对生产规模的队列，页面不会挂住 | 对着 `api.kernelci.org` 的 `/worker`（`kind=job` 回答 **478 万**个节点）是 **2 个请求**——一次计数加队列的头部——12-18s；旧的读法会翻页到 `total`，然后一直画不出来 |

## 文档地图：想干什么，读哪一份

| 我想… | 读 | 它在说什么 |
|---|---|---|
| 把新树跑起来 | 本文件的「怎么跑起来」 | 17 条命令行，每条都真跑过 |
| 知道哪些话是被验证过的、哪些还没有 | 本文件的「验证了什么，怎么验证的」+「还没做的，以及值得知道的缺口」 | 证据与缺口，分开写 |
| 看懂接口的形状 | [`include/kci.hpp`](include/kci.hpp)（总览）→ `include/kci/*.hpp`（按层） | 只有声明和注释，`g++ -std=c++17` 能过 |
| **操作这个部署**（部署、起栈、worker、prune、verify） | [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | 部署与运行手册：环境、setup、stack、worker、prune、verify |
| 知道上游卡在哪、项目边界在哪 | [`docs/UPSTREAM-BLOCKERS.md`](docs/UPSTREAM-BLOCKERS.md) | 上游进展快照（§0）+ 未解问题 U1–U5；关于外部世界的事实，日期是测量日期 |
| 看旧树（已删除）曾经怎么分的层 | [`docs/archive/`](docs/archive/)（冻结的早期深挖） | 旧树的地图已随旧树删除：历史材料在 `archive/` |
| 翻历史 | `docs/archive/`（冻结） | 别当现状读 |

**两份文档集的分界**：`docs/` 是**这个部署**的运行手册加上关于上游与旧树的事实
（旧树 `scripts/` + `run.sh` 已于 2026-09-20 删除）；`include/` 讲的是
**这棵树的设计**（`lib/` + 根目录入口）。`docs/INDEX.md` 顶部有同样的路标。

## 实现了什么

一次运行是四件事——**挑一个构建、把它取到本地、在它上面跑一个测试、拿到一个结果**——
树里一个文件就干一件事：决定的是根目录入口，干活的是 `lib/` 的模块，展示拿回来了什么的是查看器。
下面每一个模块、每一条路径、每一个计数都是从树上读出来的。分层规矩（`lib/__init__.py`）：
选择器和查看器在 `lib/` 上面，外部世界（KernelCI HTTP、tuxrun/QEMU、文件系统）在它下面，
而且 **`lib/` 里没有任何模块 import 入口点或工具**。

### 根目录入口：十二个文件，十二条命令

根目录每个 `*.py` 都是一层薄薄的 `argparse` 壳：解析 argv → 把活交给 `lib/` →
把一个 `KciError` 变成一个退出码。`docs/gui-rework/tools/check_structure.py` 钉着这个形状
——一个入口、一条退出路径、一行用法。

| 入口 | 命令做什么 | 依赖的 `lib/` |
|---|---|---|
| `gui.py` | 走 HTTP 的网页：`gui.Gui(...).serve()`，默认端口 **8079**（`--port`、`--rows`、`--refresh`、`--api-url`） | `config`、`errors`、`gui` |
| `run_latest.py` | 最新的生产 riscv 构建在本机跑一次（fetch → build → job → verdict），跑完就退 | `api`、`build`、`config`、`errors`、`kbuild`、`job` |
| `pull_worker.py` | 常驻 worker：从 events API 领单 → 跑 → 回调；`--once` 只跑一轮 | `config`、`errors`、`poller` |
| `runday.py` | 一整天的构建，跳过账本里已有的（`--day`、`--days`、`--redo`） | `build`、`config`、`errors`、`kbuild`、`job`、`re` |
| `table.py` | 离线的本地构建表：`index`（问 API）/`pull`（取字节）/`jobs`/`todo`/`summary`/`run` | `build`、`config`、`errors`、`job`、`re` |
| `results.py` | 把账本（`var/results/`）读回来；`--build`、`--test`、`--list`、`--json` | `errors`、`re` |
| `drift.py` | 比两个构建的 `.config`；exit 0 无漂移、**1 有漂移**、3 基础设施 | `config`、`drift`、`errors` |
| `trend.py` | 从生产 API 的 `done` job 历史读出 pass/fail 与回归（pass → fail） | `config`、`errors`、`re`、`kjob`、`out` |
| `provision.py` | 钉住最新的**通过**的生产 riscv 构建：取内核、发布 `var/serve/Image`、写 `var/state/served.json` | `api`、`build`、`config`、`errors` |
| `prune.py` | `var/downloads/` 的保留策略：留最新 N 个加这个部署服务的那个；`--dry-run` | `errors`、`layout`、`retention` |
| `report.py` | 每个 pull-lab job 名的最新节点（state / result / created / 完整 id） | `config`、`errors` |
| `verify.py` | 总闸：ruff、i18n、structure、用真实上游解析器验 callback body、四项页面脚本与单元检查、两种语言下渲染每个页面、PR1 YAML，以及带 `--base` 时走 HTTP 的 `accept.py` | `errors`；每一项都是 `docs/gui-rework/tools/` 下自己的子进程 |

### 中间层，lib/

**地基**——谁都不依赖，或只依赖 `errors` 和 `layout`：

| 模块 | 是什么 | 关键名字 |
|---|---|---|
| `errors.py` | 一个异常根、三个退出码（0 pass / 1 test fail / **3 infra**） | `KciError`、`ConfigError`、`ApiError`、`ArtifactError`、`InfraError`、`LedgerError` |
| `out.py` | 一次 `(build, test)` 的结果 | `Outcome`、`RECORD_FIELDS`——落盘键集，一条契约 |
| `tests.py` | 测试目录（**不是**测试套件）：有哪些测试可跑 | `TESTS`、`DEFAULT_TESTS`、`KVM_SKIP_TESTS`、`ROOTFS_URL`、`DEFAULT_DEVICE`、`DEFAULT_LAB`、`device()`——一份定义自己的设备，`runner` 把它拼成 `--device`，`sink` 把它报成 `actual_device_id` |
| `layout.py` | **每一个项目会写的路径，只在这一个文件里拼** | `work()`（`var/` 或 `$KCI_WORK_DIR`）、`downloads/baked/configs/logs/serve/results/runs/state/workspaces`、`worker_state()`、`index()` |
| `atomic.py` | 一次原子写：文件写在自己旁边，再改名盖过自己——这前两步以前有七处手写 | `write_json()`、`write_text()` |
| `__init__.py` | 仓库根 | `repo_root()`——走上去找 `lib/layout.py` + `README.md`，**别数 `dirname()` 层数** |
| `ports.py` | 主机端口探测，`deploy/stack.sh` 用它 | `port_is_free`、`port_holder`、`require_port_free` |

**远端那一半**，只读——API 有什么：

| 模块 | 是什么 | 关键名字 |
|---|---|---|
| `api.py` | **整棵树里唯一的 KernelCI HTTP**：请求级 memo、进程级 TTL 缓存、每请求时间预算、只对 `ConnectionError` 重试、拒绝重定向而不是跟随 | `Api`（`get/post/text/nodes/count/node/events/counts`）、`PRODUCTION`、`LOCAL` |
| `kbuild.py` | 远端**构建**节点 | `Kbuild`、`Kbuilds`（`getnew/getdays/get`）、`build_id_of`、`KBUILD_JOB` |
| `kjob.py` | 远端 **job** 节点——同一个 node kind，无论它是队列条目还是已完成的运行 | `Kjob`、`Kjobs`（`getjob/available/done`）、`claimable()`、`definition()` |

**本地那一半**，有副作用——我们对它做什么：

| 模块 | 是什么 | 关键名字 |
|---|---|---|
| `build/`（**包**，6 个模块） | 构建的本地一半：字节、客户机磁盘、本地表 | `Build`、`Builds`（`var/state/builds.json`）、`download`、`bake_rootfs`、`publish_local`、`served`、`provision` |
| `job.py` | **唯一的执行器**——worker、一次性、`table.py` 和页面上的按钮全都走到这里 | `Job`、`Jobs`、`Job.run()` |
| `runner.py` | tuxrun 的 argv 构造与执行（**全程无 shell**；超时杀进程组） | `argv()`、`execute()` |
| `judge.py` | 控制台 → verdict（**判据是 TAP**，从来不是 tuxrun 的退出码） | `tap_summary`、`verdict`、`infra_reason`、`strip_ansi` |
| `sink.py` | 一条 outcome 去哪 | `Sink`（那个 ABC）、`Ledger`、`Callback`、`lava_body`、`deliver` |

**流与视图**——有东西跑起来之后：

| 模块 | 是什么 | 关键名字 |
|---|---|---|
| `poller.py` | **轮转本体**：盯着 API、领单、跑、回调——树里最复杂的一个类 | `Poller` |
| `run.py` | 一个后台活动：`var/runs/<id>/` 里的 `run.json` + `run.log` | `Run`、`start/load/load_all/reap/cancel/log_since`、`WRITERS`、`KINDS` |
| `config.py` | argv/env → 对象 | `RunConfig`、`PollConfig`、`client()`、`run_from`、`parse_poll` |
| `re.py` | 读账本 | `Records`（`load/for_build/for_test/last/series/tally`）、`todo()`、`transitions()`、`render` |
| `drift.py` | 配置漂移：取 `.config`、解析、比对；磁盘缓存在 `var/configs/` | `Drift`（`between/series/from_files`）、`parse`、`diff` |
| `retention.py` | 保留策略；**plan（决定留谁）与 prune（删）分开** | `plan()`、`prune()`、`DEFAULT_KEEP` |
| `gui/`（**包**，28 个模块） | **整个网页**；它的 `__init__.py` docstring 里有一张逐模块的布局表，从那里进。粗分：`schema.py` 是全部页面共用的词表（路由/动作/筛选/排序），`models.py` 是 `Apis/Filter/Local/Remote`，`server.py` 是 socket 循环与路由，`app.py` 是 `Gui` 本体，`pages/` 一页一个模块，`templates.py` 是内联的 CSS/JS/HTML | `Gui`、`Filter`、`Local`、`Remote`、`Apis` |
| `i18n/`（**包**，10 个模块） | 页面自己的话，**EN + ZH 一份目录**，只被 `lib/gui/` 读。`catalogue/` 按页面分 6 份数据（`shell`/`local`/`work`/`analysis`/`record`/`words`，每份 112–340 行），`__init__.py` 是查表，`check.py` 是 `--check`/`--map` | `t(lang, key, **fmt)`、`pick_lang`、`key_for` |

加一句新文案必须在同一次改动里落到 `lib/i18n/catalogue/`，否则
`python3 -m lib.i18n --check lib/gui` 会报缺键。（`-m` 跑的是这个包自己的
`lib/i18n/__main__.py`；它现在是包，不是 `lib/i18n.py`。）

**三条入口线，一个执行器。** 区别只在「job 从哪来」，而它们全部汇到同一个
`Job.run()`——它分不出 job 是自己造的还是上游派的，这是设计，不是巧合。
「结果去哪」由 sink 决定，不由调用方决定，而且账本**永远第一**。

| 线 | 入口 | job 从哪来 |
|---|---|---|
| 常驻 worker | `pull_worker.py` → `poller.Poller` | API 派单（`Kjobs.available()`） |
| 一次性 | `run_latest.py`、`runday.py` | 自己挑：最新的，或某一天的 |
| 本地表 | `table.py` | 本地表自己（`index − 账本 = todo`） |

```
Kbuilds.getnew() ──▶ Build.make() ──▶ Job.run() ──▶ sink.deliver()
Kjobs.available()    download()        argv()         Ledger.write() → var/results/
                     bake_rootfs()     execute()      Callback.post() → lava_body
                                       judge.verdict()
```

### 非 Python 的部分

| 路径 | 是什么 | 关键规矩 |
|---|---|---|
| `include/kci.hpp` + `include/kci/*.hpp` | **接口的 C++ 版本：图纸，不是程序**（只有声明和注释，`g++ -std=c++17` 能过） | 按层：`base`（退出码/路径/配置）→ `remote`（Api/Kbuild/Kjob）→ `local`（Build/Job/Outcome）→ `engine`（Runner/Judge/Sink）→ `flow`（Run/Poller）→ `view`（Filter/账本/Drift/GUI）。**图纸可以领先实现，实现不许领先图纸**——改形状先改 `include/` |
| `deploy/` | **部署那一半**：`setup.sh`（克隆 + 打补丁 + 这个部署的本地配置 + YAML 检查）、`stack.sh [--seed]`（本地完整栈：compose、artifact server、真实 callback、官方 scheduler）、`stop.sh`、`instance-init.sh`、`seed.sh`、`net-preflight.sh`、`render-local-config.py`、`repro-api-bugs.sh` | 它不做任何运行期决策——那是根入口的事——它像这棵树其余部分一样读写 `var/` |
| `config/` | 补丁与模板 | `pr1-config.patch`（PR1 测试配置）、`tuxlava-kselftest-riscv.patch`（PyPI 的 tuxlava 0.25.0 没有 riscv class，本机仍要打）、`local-callback.toml`（`@KCI_ROOT@` 模板）、`cb-config/pipeline.yaml`，以及两个 kernelci-api 补丁 |
| `docs/RUNBOOK.md` | 怎么操作这个部署：环境、`setup`、`stack`、worker、prune、verify | 完整手册；上面那几条 deploy/setup/stack/stop 只是快速上手 |
| `docs/` | 运行手册，外加关于上游与旧树的事实 | **整棵 gitignored，只放行 `docs/RUNBOOK.md`**，所以放进这里的东西不进版本库。想知道「某件事该读哪份」看 `docs/INDEX.md` |
| `kernelci-*/` | 上游克隆（**gitignored**，由 `deploy/setup.sh` 创建） | 判断上游行为**必须**用 `git show origin/<branch>:<path>`，不能用工作区文件 |
| `var/` | **工作区**，由 `lib/layout.py` 独占所有权，别的谁都不许拼它的路径 | `$KCI_WORK_DIR` 可以把它搬到任何地方；账本 `var/results/` 是历史、**永不清理**，其余都可再生。旧树的 `work/` 已删除；它的数据归档在 `/home/hao/kci-work-backup-*.tar.gz` |

## 还没做的，以及值得知道的缺口

* **采用已经完成；这些是一开始就一直在的缺口。** 这份列表以前开头的三条
  （dispatcher 没有被重新指向、部署那一半、旧账本）已经做完或已决定：旧树已删除，
  `deploy/` 就是部署，而 `work/results/` 的 378 条记录是归档而不是迁移
  （操作者不要它们——`/home/hao/kci-work-backup-*.tar.gz`）。
* **`runday.py` 从来没有端到端跑过**——它的代码路径（一天的构建减去账本）是通过
  `table.py` 和 poller 走到的，不是通过入口本身走到的。
* **KVM 跳过列表是一次测量，不是一条定律。** `lib/tests.py` 给在 TCG 下不可能通过的
  测试命名；更新的内核的 kselftest tarball 会带来新的这种测试，它们会以失败的形式出现，
  直到这个列表按证据更新。这是有意的——在这里跑不了的测试应该被*点名*，
  而不是被悄悄跳过——但事情发生时需要有人来处理。
* **`gui.py --refresh` 没有接线**；页面每 2 秒轮询一次。
* **新树里没有任何东西跑过生产 API 的写路径。** 读（`getnew`、`getdays`）是走过的；
  唯一的写是 callback，而它只被 POST 到过一个本地流水线。

## 重写逐字节保留的两条契约

其它一切都可以改；这些不行，因为破坏它们会静默失败：

* **LAVA callback body**——流水线的端点没有给任何其它形状的解析器，所以格式错了就会
  无声地丢掉结果。两棵树的构造器都用真实的上游解析器读回
  （`kernelci.runtime.lava.Callback`）：kcilib 的用 `scripts/tools/verify-lava-body.py`，
  新树的用 `docs/gui-rework/tools/verify_callback_body.py`——各四个用例（一个通过的
  boot 和一个失败的 boot、一行失败的 TAP 而 tuxrun 退出 0、一个没有 TAP 的 JobError、
  tuxrun 拒绝旗标）。`python3 verify.py` 跑新树的那个；kcilib 的那份随旧树走了。
* **退出码**——0 通过、1 测试失败、3 基础设施。`3` 是 LAVA 的*incomplete*：
  「我们从没拿到结论」，它必须与「测试失败了」保持可区分。

## 状态

重写已完成、已验证并被采用：旧树（`scripts/`、`run.sh` 和 `kcilib/`）已删除，
每条命令都是一个根入口，部署那一半住在 `deploy/`，`python3 verify.py` 是门禁。
下面的表记录了什么替换了什么。

上游状态（PR1 测试 profile、它的 review 讨论串、那些阻塞点，以及已经测过的东西的
诚实边界）住在 `docs/` 里——`UPSTREAM-BLOCKERS.md` 描述的是*随发布走*的树，它的数字
是它标明的日期的测量值，不是长期有效的断言。其中两条事实值得在这里重复，
因为它们才是交付物而不是工具：测试 profile（`config/pr1-config.patch`，4 个 YAML）
已经就绪，官方 scheduler 从它渲染出 3 个 job 定义；config-drift / 回归趋势工具
能正确读回生产历史。

## 采用新树：什么替换了什么

| 随发布走 | 新的 | 完成？ |
|---|---|---|
| `./run.sh fetch [--kvm]` | `python3 run_latest.py --test <name>` | **是** |
| `./run.sh worker [--once]` | `python3 pull_worker.py [--once]` | **是** |
| `./run.sh build index\|jobs\|todo\|summary` | `python3 table.py index\|jobs\|todo\|summary` | **是** |
| `./run.sh run` | `python3 table.py run` | **是** |
| `./run.sh results` | `python3 results.py` | **是** |
| `./run.sh drift` | `python3 drift.py` | **是** |
| `./run.sh dashboard` | `python3 gui.py` | **是** |
| `./run.sh prune [--keep N] [--dry-run]` | `python3 prune.py [--keep N] [--dry-run]` | **是** |
| `./run.sh provision` | `python3 provision.py` | **是** |
| `./run.sh report` | `python3 report.py` | **是** |
| `./run.sh trend` | `python3 trend.py` | **是** |
| `./run.sh verify` | `python3 verify.py` | **是**——旧门禁随 `kcilib` 走了；新的是 `verify.py` |
| `deploy/setup.sh` \| `deploy/stack.sh [--seed]` \| `deploy/stop.sh` | `deploy/`——部署那一半现在有自己的目录 |

**这些行里有两行看起来是一行的替换，其实不是**，在重新指向别的东西之前，
它们需要什么值得知道：

* `drift`：新的读取器和页面用的是同一个读取器，但它的 CLI 在没有
  `--older`/`--newer` 时把 `--job` 当作*树*传给了 `getdays()`（`lib/drift.py`），
  于是 `--job kbuild-gcc-14-riscv` 向生产要一个这个名字的树，被告知 `total=0`，
  最后落进一个 `ConfigError` traceback。它现在用 `state=done`/`result=pass` 问这个
  job 的整段历史——旧工具的选法。而且 `drift.py` 把方法 `drifted` 当属性读，
  所以**无论答案是什么它都退出 1**；而那条命令唯一承诺的就是退出码。在生产上验证过：
  两个读取器都挑出较老的 `6aaf2335…` / 较新的 `6aaf3175…`，都发现 0 处差异，都退出 0。
* `prune`：旧规则从 `work/env/build.env` 和每个目录的 `node.json` 里读被 serve 的构建。
  新树里这两个都不存在，所以 `publish_local()` 现在记录这个动作——
  `var/state/served.json` 写明 `var/serve/Image` 是哪个构建——而 `lib/retention.py`
  按那个 id 保护它。没有记录的镜像会被报告出来
  （`! … nothing is protected by provenance`），从不靠猜。

旗标集不同的地方，新入口自己的旗标说了算：worker 没有 `--tuxrun-bin`
（它从 PATH 解析 `tuxrun`）、没有 `--output-dir`（控制台进 `var/logs/`）、
没有 `--max-timeout`（`lib/config.py` 带着运行超时，`lib/runner.py` 带着 tuxrun 上限）；
页面没有 `--host`、`--db` 或 `--no-api`；`fetch` 没有 `--job` 或 `--kvm-full`。

