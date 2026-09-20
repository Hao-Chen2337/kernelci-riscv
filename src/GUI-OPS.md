# GUI 操作手册（新树）

> 这份是**给人用的**：怎么起、怎么切、每个按钮会跑哪条命令、出错时那句话什么意思。
> 想看**设计**（为什么是九个页面、为什么"值相同"不是"同一个东西"）读 [`GUI.md`](GUI.md)；
> 想看**接口形状**读 [`../include/kci/view.hpp`](../include/kci/view.hpp)；
> 想自己复核本文任何一个数字，命令都在 §8。

## 1. 起一台

```bash
cd ~/kernelci-riscv

# 问本地那套栈（默认；$KCI_API_URL 也能改基址）
python3 gui.py --port 8080

# 问公开 API（看真实数据用这台）
python3 gui.py --port 8080 --api-url https://api.kernelci.org
```

* 只监听 `127.0.0.1`（§6「明确不做」：不做多用户、不做登录）。端口被占会**报出来**，不会偷偷换一个。
* `--port` 不传时是 **8079**。
* 想让它活过后台会话：`setsid nohup python3 gui.py --port 8080 > /tmp/kci-gui-8080.log 2>&1 < /dev/null &`
* 停：`kill <pid>`（日志第一行会印出它监听的地址）。

**这台页面是只读的，除了按钮** —— 按钮只是把你本来会手打的那条命令作为一次活动起起来（§3 那张表是唯一一份对照）。

## 2. 两个旋钮：`api` 和语言

| 旋钮 | 怎么用 | 它是什么 |
|---|---|---|
| **`api`** | 筛选栏最左边那个框：点药丸 `local` / `production`，或手打任意 `http(s)://…` | **"我在看哪份数据"**。它和 `tree`/`days` 一样是 URL 里的一个键（`?api=production`），不是设置项：没有 cookie，跟着每个链接走，可复制、可分享 |
| **语言** | 页头 `English / 中文`，或 `?lang=zh` | "读者想被怎么称呼"。这个**会记住**（cookie `kci_lang`），因为它是偏好 |

两件事都**只影响这一次页面读谁**，不改任何磁盘上东西。

**地址永远印在页面上**：顶部那行是

```
asked the API: https://api.kernelci.org: kind=kbuild job=kbuild-gcc-14-riscv tree=any branch=any …
```

—— 印的是**真正被问的地址**，不是那个短名字。所以你不可能搞混自己在看哪家。
当 `api` 不是启动时那个基址时，筛选栏的说明里会多一句：下面命令行带 `--api-url` 的按钮**真的会把活派到那家**（生产上点 `index`/`pull` 就是真的往生产登记/拉取）。

## 3. 九个页面，各回答一个问题

| 路由 | 回答什么 | 主要按钮（= 它跑的那条命令） |
|---|---|---|
| `/` | 三样东西各有多少、缺口多大、现在在跑什么 | 没有按钮，只是导航 |
| `/remote` | API 这一批有哪些 build | **把这一批登记进本地表** = `table.py index --api-url … --days … --limit … --tree …` |
| `/local` | 我们手上有哪些、各自对应的**证据**是什么 | **compare config**（勾两行 → `/analysis`）；**publish var/serve/Image as a build** = `run_latest.py --provision-only` |
| `/local/<id>` | 这一份副本：卡片、字节、拉取记录、远端那一行、账本 | **pull (re-check the sizes)** = `table.py pull --build <id>`；**run the pending tests** = `table.py run --build <id>` |
| `/pull` | 条件怎么选、候选有哪些、拉了什么、留下什么记录 | 勾行 → **pull the ticked builds** = `table.py pull --build …` |
| `/jobs` | 本地表减账本 = 还没跑的；怎么跑 | 每行 **run boot / run kselftest-riscv / run kselftest-kvm**；**跑最新一个 build** = `run_latest.py`；**跑一整天** = `runday.py`；**the ledger, in full** = `results.py` |
| `/runs` | 现在在跑什么、日志、取消 | 每行 **cancel** = `POST /api/runs/<id>/cancel` |
| `/worker` | 远端队列里有什么、worker 处理过什么 | **start the worker** = `pull_worker.py [--once] --platform … --runtime …` |
| `/analysis` | config 漂移、回归时间轴 | **run drift.py** = `drift.py --older … --newer …`（只读比对在页面上直接渲染） |

**每个按钮下面都印着它会跑的那条命令**，还有一个 `what this button sends` 折叠出真实的参数表 ——
页面不许有第二套行为，所以能看到的就是会跑的。

## 4. 三条常用流程

**① 看真实数据（不碰本地状态）**

```
api = production  →  /remote  →  看行、点某行的 pull…（只是页面跳转）
```
`tree` 框可以直接打 `next`、`mainline`、`stable`…（50 个固定名字，来自
`kernelci-pipeline/config/trees.yaml`），`last` / `rows` 也可以直接填数字。

**② 把远端的 build 变成"我们手上的"**

```
/remote（api 选好）→ 点「把这一批登记进本地表」   # 卡片进 var/state/builds.json
/pull   → 勾要的 → 「pull the ticked builds」      # 字节进 var/downloads/<id>/
```
**拉取只认本地表里的卡片** —— 勾不上的行会明说"N 行在本地表里没有卡片，所以勾不上：
先到 `/remote` 登记这一批，再回来"。这是设计，不是毛病（`table.py pull --build` 读的就是那张表）。

**③ 跑测试、看判决**

```
/jobs → 那一行 → run boot        # 起一个活动；退出码就是判决
/runs → 看它跑到哪、日志、必要时 cancel
/jobs → 那一行会变成「已跑过 + 判决」；/local 的 ran 列同理
```
判决由 `judge` 写进账本（`var/results/<build_id>/<test>.json`），页面只转述。

## 5. 什么时候需要重启页面

**只有改代码才需要。** 数据永远不用：卡片、账本、判决、缺口都是**每个请求现读**的 ——
按钮起的子进程（`table.py index/pull/run`、`runday.py`、`pull_worker.py`）写下的东西，
**下一次刷新就看得见**。这一条是特意改的：早先版本在启动时读一次就冻住，于是"我跑了 boot，
页面还是显示没跑过"，而磁盘上 `boot.json` 明明在。

**唯一一次例外**：升级了代码本身（`lib/*.py`）要重启才生效 —— 你正在读的这轮改动就属于这种。

## 6. 出错时，页面说的那句话是什么意思

| 你看到 | 意思 | 怎么办 |
|---|---|---|
| 按钮旁 **`已起 <活动号>：<命令>`** | 命令**已经开始跑**了；回执不是结果 | 去 `/runs` 看进度与退出码；或点它打开日志框 |
| **`被拒：<原因>`** | 这次 POST 被服务端拒了（409） | 原因通常就写在后面：`有写者在跑` / `参数不在词表里` / `至少要勾一个 build` |
| 顶栏 **`writing right now: <活动>`** | **一次一个写者**：写动作（`index pull run runday fetch worker provision drift`）同时只能有一个 | 等它结束，或在 `/runs` 取消它；只读的 `results` 可以并行 |
| **`the API did not answer this query (…)`** | 上游**没应答**（连不上/超时） | 这和"答复里没有"是两件事：页面会分开说，不会拿一句"没有"糊过去 |
| **`the API answered, and the answer is empty for this query (…)`** | API 答了，答案就是空的 | 检查 `tree`/`branch`/`last`；或换 `api` |
| 页头 **`rows=1000 (asked 99999, capped)`** | 你的值被夹到上限了，**页面会说**（不悄悄改） | 上限：`rows` 1–1000、`last` 0–3650 天（`0` = 全部历史） |
| **`showing 2 of 2 row(s) this window kept …; the API counts 1782 for this query`** | 三个数分别属于三处：本页摆出来的行 / 过了本页过滤的行 / **API 自己报的**总数 | 只想看更多行：加大 `rows`；行少但 API 说得多：是本页过滤挡的 |
| 手动改了 URL 里的 `tree`/`api` 等，页面显示 `(current)` | 不在候选里的值会被**原样保留**并追加一个选项 | 旧版会悄悄改成默认值，这一版不会 |

## 7. 已知边界（都是量过的，不是猜的）

| 事实 | 数字/说明 |
|---|---|
| 生产上 `/worker` 慢 | `kind=job` 有 **478 万**个节点，一次页面要问 `count` + 队首页 ≈ **12–18s**（以前是"翻到 total 为止"，等于永久转圈）。本地栈上是 **0.0s** |
| 生产上 `/analysis` 慢 | ≈ **11.5s**：取两个 `.config` 并解析的固有时间；它现在用的是**这一页已经读到的**构建，不再为两个 id 各扫一遍窗口（那时是 33s 且可能算不出结果） |
| "按 build_id 找 build" 有上限 | `lib/kbuild.py` 的 `SCAN = 1000`：API 没法按 build_id 查，只能扫窗口，所以只扫最新的 1000 个；找不到时错误会写明"在最新 1000 个里没有" |
| `rows` 是**显示**上限，不是查询条件 | 决定"看哪些行"的是 `last`（窗口）；`rows` 同时是 `/remote`「登记」那条命令的 `--limit`，所以调小它会少登记卡片 |
| 判决词与 job/run 状态词**保留英文** | `pass/fail/incomplete/error`、`available/done/…` 是 `judge` 与 API 自己的词表，页面不重造；证据状态（`pulled/unrecorded/…`）的标签已翻中文 |
| 关掉 JavaScript | 页面照常能用（筛选栏有「应用」按钮），但**动作按钮会把浏览器甩到 JSON 回执上**——那是 `POST /api/actions/<name>` 的契约本身，不是毛病 |
| 机器接口不翻译 | `/summary.json`、`/api/*` 任何语言下都是英文 |

## 8. 自己复核（三条命令，不用读代码）

```bash
# 文案的"测试"：每个页面用到的 key 都在目录里，且中英两列齐全
python3 lib/i18n.py --check lib/gui.py        # 缺失 0 / zh 缺失 0 才算过

# lib/api.py 与 lib/build.py 是 worker 共用的，改完必跑
python3 scripts/tools/verify-worker-guards.py # 期望最后一行 ALL GUARD CHECKS PASSED

# 风格
ruff check lib/ *.py
```

页面本身按 `GUI.md` §8 的规矩验：**打 HTTP，不是读代码**。常用几条：

```bash
B=http://127.0.0.1:8080
curl -s "$B/remote?api=production&days=1" | grep -o 'asked the API: <code>[^<]*'   # 它问的是谁
curl -s "$B/remote?days=1000000000000" | grep -o 'last=[0-9]*'                     # 夹住而不是 500
curl -s -o /dev/null -w '%{http_code}\n' "$B/remote?tree=%E6%A0%91"                 # 坏名字 404，不是 500
for p in / /remote /local /pull /jobs /runs /worker /analysis; do
  curl -s -o /dev/null -w "%{http_code} $p\n" "$B$p"; done                          # 八页全 200
```

> 会话里用过的那批一次性探针（`accept.sh`、`datacheck.py`、node 的 DOM 桩等）在 `/tmp` 下，
> **不是仓库的一部分**；要长期保留的话应当先按 `docs/INDEX.md` §2 的规矩过一遍再决定放哪。
