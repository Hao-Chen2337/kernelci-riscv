# GUI v2：远端 · 本地 · 对应（三样东西）

> 谁该读这份：想知道页面"为什么这样分"的人。想改页面先读第 1 节（模型）与第 3 节
> （控件→命令对照）；第 9 节与第 11 节是两次真实故障的排查记录，别当设计读。
>
> **只想把它用起来**（起哪台、切 `api`、每个按钮跑什么、出错那句什么意思）读
> [`GUI-OPS.md`](GUI-OPS.md) —— 那一份是操作者的一页纸，这一份是设计。

> 接口在 `include/kci/*.hpp`（这一篇对应 `view.hpp` §16 Filter、§17 账本、§18 Drift、
> §19 GUI、§20 页面文案）。这一篇回答五件事：**为什么 id 相同不等于同一个东西**、
> **有哪些页**、**每个控件对应哪条命令**、**页面凭什么敢说自己没算数**、
> **同一句话凭什么有两种语言**（§10）。
>
> v1 被否掉的那一句：「一行一个 build_id，本地列和远端列合成一行」。理由写在 §1.1。

> 这一版的行号、常量名、文案原文与数字，全部对着当前代码核过一遍（怎么核的写在 §8）。
> 页面今天说的每一句话都住在 `lib/i18n.py`（§10）：§1–§7 引用的英文原文就是它的 en 那一列，
> 只是按页面上**渲染出来**的样子写（目录里的 `&mdash;` 在这里写成 `—`）。

## 0. 一句话

上一次的页面把三件不同的事压成了一张表：**远端有什么**、**本地有什么**、**两者是不是同一个东西**。
压力点在第三件上 —— 表里只有 `build_id` 一列，而 `build_id` 相同**证明不了**任何事。
这一版把它们分开，并且给第三件一个**落盘的记录**：

```
        远端（API 说的）            本地（我们手上的）           对应（拉取时记下来的）
     ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────────────┐
     │ 一次查询的一组行   │      │ 本地表卡片 + 字节  │      │ var/downloads/<id>/       │
     │ 窗口、结果、node   │      │ 谁在磁盘上、多大   │      │   provenance.json         │
     └──────────────────┘      └──────────────────┘      └──────────────────────────┘
            只读                        只读                        只读（写发生在拉取时）
```

页面把三者**并排显示**，但**不合并**，也不靠 id 相等去暗示它们是同一个东西。

## 1. 身份：为什么「值相同」不是「同一个东西」

### 1.1 两个相等的值

`build_id` 是**从构件 URL 里解析出来的字符串**（`kbuild.py: build_id_of()`）。它是远端自己的一部分，
本地表里也存了它 —— 于是「本地有一个叫 X 的目录」和「远端有一个叫 X 的 build」看起来就能对上。

但这两句话各自都只是**值**：

* 本地目录名可以是任何人起的（`--provision-only` 发布的内核、手工拷进来的、上一次查询留下的）；
* 远端的 `X` 是**那一次查询**里的一条，换一个窗口、换一个 API，它可能就不在；
* 两个值相等，只说明两张纸上写了同样的字。**同一性是要建立出来的，不是读出来的。**

所以规矩是：

> **`build_id` 相同不是证据。页面只显示两种证据：卡片里的 `node_id`（这条本地卡片登记自哪个远端节点），
> 和 `var/downloads/<id>/provenance.json`（这些字节是从哪些 URL 拉来的）。没有证据就写「没有记录」。**

### 1.2 对应是**建立**出来的，两次

| 动作 | 建立了什么 | 证据落在哪 | 命令 |
|---|---|---|---|
| **登记**（index） | 本地表里这张卡片的字段来自远端的哪个节点 | `var/state/builds.json` 里的 `node_id` + 构件 URL | `python3 table.py index --tree … --days …` |
| **拉取**（pull） | `var/downloads/<id>/` 里的字节来自远端的哪些 URL | `var/downloads/<id>/provenance.json` | `python3 table.py pull --build <id>` |

两次都只写自己那一半：登记**不碰字节**，拉取**不改卡片**。所以两句话可以各自真、各自假：

* 登记过、没拉过 → 「远端有这条 build，我们只抄了它的名片」；
* 拉过、卡片里的 `node_id` 为空 → 「字节是从这些 URL 拉来的，但没人告诉我它们是哪个节点的」。

### 1.3 拉取时落下的记录

`lib/build.py: Build.make()` 每被调用一次（= 一次 `table.py pull`），就在
`var/downloads/<build_id>/provenance.json` 里追加一条 **act**。下面这份是在本机真跑
`python3 table.py pull --build 6aadee70d96a8203de6e8452` 之后文件里的原文：

```json
{
 "acts": [
  {
   "at": "2026-09-19T11:56:10Z",
   "entries": [
    {"artifact": "kernel", "bytes": 27520512, "transferred": true,
     "url": "http://172.17.0.1:8999/Image"},
    {"artifact": "modules", "bytes": 4339104, "transferred": true,
     "url": "https://files.kernelci.org/kbuild-gcc-14-riscv-6aadee70d96a8203de6e8452/modules.tar.xz"},
    {"artifact": "kselftest", "bytes": 8917000, "transferred": false,
     "url": "https://files.kernelci.org/kbuild-gcc-14-riscv-6aadee70d96a8203de6e8452/kselftest.tar.xz"}
   ],
   "error": ""
  }
 ],
 "build_id": "6aadee70d96a8203de6e8452",
 "node_id": "6aae46c2c429a2b4feeddf12"
}
```

注意 `kselftest` 那行 `transferred: false`：本地本来就有一份、大小与 host 一致，所以这次
**没有搬字节，只核对了大小**——「拉过」和「核过」在记录里是两件事。

字段的意思，一个不多一个不少：

| 字段 | 是什么 | 为什么必须记 |
|---|---|---|
| `url` | 这次真的去取的那个 URL（API 卡片里的原样拼法） | 「从哪拉的」只有这一句是事实 |
| `bytes` | **证明过**的字节数（下载时对过 host 报的长度，或本地已有文件与 host 一致） | 半截文件也会「存在」，大小是唯一证明 |
| `transferred` | 这次是不是真的搬了字节：`false` = 本地已有且大小对，只核对了没重下 | 「拉过」和「核过」不是一回事，不能混成一句 |
| `artifact` | **我们**的构件名（`kernel` / `modules` / `kselftest` / `config`） | 页面按我们的词汇显示，不按 API 的拼法 |
| `at` / `error` | 这条 act 记下的时刻；`error` 非空 = 这一轮有构件没拿到，原因写在这里 | 失败那次最值得留；`error` 不空也照样写记录 |

写记录的时机与纪律：

* `make()` 里记录写在收尾处（`try/except` 加一次收尾调用）：**拿到了几个构件就记几个**，一个失败也留下 act（`error` 写明），然后照旧抛 `ArtifactError`；
* 记录写不下去（磁盘满、目录只读）**就是这次拉取失败** —— 这次拉取的证据和字节一样重要，不许悄悄省掉；
* `acts` 只留最近 `PROVENANCE_ACTS = 20` 条：这个文件描述的是**这份副本的现在**，拉取的历史本身在 `var/runs/<id>/`（每个按钮都是一次 Run）。

**为什么记录放在 `var/downloads/<id>/` 里，而不是 `var/state/`**：它描述的是**这些字节**。
`Build.remove()` 删目录时记录跟着走，绝不会出现「有拉取记录、却没有副本」这种谎。
反过来，一个没有 `provenance.json` 的目录就是**诚实的「不知道」** —— 老版本拉的、worker 铺的、
手工拷的，全都长这样。

### 1.4 于是页面只能说出这几句话

对应这一列（`lib/gui.py: Local.state` / `Local.state_text()`）只有五种取值，全部由上面的事实决定：

| 状态 | 什么时候 | 页面写的字 |
|---|---|---|
| `pulled` | 有 act，且 act 里有 entries | `pulled 3 artifact(s) from 172.17.0.1:8999, files.kernelci.org (38.9 MiB) at 2026-09-19T11:56:10Z - 2 transferred, 1 already whole` |
| `unrecorded` | 有字节，没有 act | `no pull recorded for these bytes (a card in the local table)` / `(no card in the local table)` |
| `registered` | 有卡片（带 `node_id`），没有字节 | `registered from the API node 6aabdf20…, nothing pulled yet` |
| `made-here` | 有卡片，**没有** `node_id` | `made here (published locally): no pull, and no node id to tie it to` |
| `empty` | 目录在，但既没有卡片也没有字节 | `nothing on disk and no card` |

远端那一列有**四种**取值，每一种都是一件不同的事（`_remote_cell`，`lib/gui.py:2526`），
而且**永远带着查询条件**（见 §1.5）：

| 状态 | 页面写的字 | 什么时候 |
|---|---|---|
| 在这一次查询的答案里 | `available/- (node 6aabdf20…)` | 这一行的远端那一条取回来了 |
| 答案里没有，但查询答全了 | `no remote counterpart` | API 答了、答案也完整，就是没有它 |
| 答案里没有，是因为行数上限 | `not in the newest 25 row(s) this query answered` | API 自报的 `total` 比这一页取的 `limit` 大 —— **不是"远端没有"** |
| 这一次查询 API 没应答 | `the API did not answer this query: nothing is known about the remote side` | 什么都没问到，所以什么都不能说 |

另外，当拉取记录里的 `node_id` 与远端这一行的 `node_id` **不同**时，页面直接写出来，两处各有一句：
表格里是 `available/- (node X) - but the record names node Y`（`state.remote_cell_mismatch`），
对应页上是 `the record names node A, the API now names node B under this build id: same id,
different thing.`（`remote_detail.node_mismatch`）—— 这是「同名不同物」在数据里的样子，
比任何注释都值钱。两边都没有 `node_id` 时就不写这一句（那种情况下没有"不同"可说）。

### 1.5 已知的边界（必须写在页面上，否则就是撒谎）

1. **远端没有「全集」这回事**：`Kbuilds.getdays()` 只能按窗口问（`created__gte`），
   所以「远端」永远是**一次查询的答案**。因此远端页、本地页、拉取页都把查询条件印在那一行上，
   一行里同时有"问了什么"和"摆了多少"：
   `asked the API: kind=kbuild job=kbuild-gcc-14-riscv tree=any branch=any last 30 days —
   showing 43 of 43 row(s) this window kept (rows=50); the API counts 1772 for this query, …`。
   `no remote counterpart` 精确的含义是「**在这次查询的答案里没有，而且这次答案问全了**」——
   另外三种"没有"各有各的话（§1.4）。
2. **worker 那条线没有拉取记录，而且不该有**：`Job._make_given()` 为了读 KVM 测试名单，
   会直接把 definition 里的 `kselftest` tarball 放一份到 `var/downloads/<id>/`。
   那是一次**跑 job**，不是一次**拉 build**：它的记录是账本 + 那次 Run。
   所以这种目录会显示成 `unrecorded`，那是**正确**的答案，不是缺陷。
3. **本地自造靠 `node_id` 为空识别**：`publish_local()`（`run_latest.py --provision-only`）
   造出来的卡片没有 `node_id`（节点的 id 只有 `Kbuild.from_node()` 才有）。
   远端后来出现一个同 id 的节点，**不会**把这张卡片变成「拉取过」—— 那正是 §1.1 要说的事。

## 2. 九个路由

> **2026-09-20 起：五个路由。** 路由表已重写取代（细节见 §12）：`/remote`、`/local`、
> `/pull` 现在是 **302**，`/` 从「总览」变成合并后的 **builds** 页。
> 另：本文件通篇的行号写在重写之前（`lib/gui.py` 从 4 062 行长到约 6 000 行），
> **以符号名为准，不以行号为准**：`_axes`（原 `_chips`）、`_form`、`_datalist`、
> `_rail`、`_live_panel`、`_state_poll`。§2.1–§2.9 作为历史保留。

一页一件事（你说的「每一个功能起码单独配置一些页面转换或者按钮」）。导航条固定在顶上，
当前页加粗；每页的正文都在同一段模板里，样式和轮询脚本共用一份。

**现状（重写后）**：

| 路由 | 页面 | 回答什么 |
|---|---|---|
| `/` | **builds**（合并页） | 一个 build id 一行：卡片、字节、拉取记录、API 怎么说、跑过什么 |
| `/jobs` | 测试 | 每个 `(build, test)` 对长什么样、哪些还在缺口里 |
| `/runs` | 运行 | 现在在跑什么、日志、取消 |
| `/worker` | 轮转 | 远端队列里有什么、worker 处理过什么 |
| `/analysis` | 分析 | config 漂移、回归时间轴 |
| `/local/<id>` | 对应（一条） | 这一份副本的卡片、字节、拉取记录、远端那一行 |
| `/remote` → `/?origin=remote` | **302** | 老地址：远端那一侧 |
| `/local` → `/?origin=local` | **302** | 老地址：本地那一侧 |
| `/pull` → `/?origin=remote&missing=…` | **302** | 老地址：能拉的那些 |

302 而不是 301 —— 这是**这一版**的决定；重定向带上原来的整条查询串（`?tree=` `?branch=`
`?days=` `?limit=` `?api=` 原样带走），所以书签和历史里的链接仍然问同一个问题。

**历史（重写前的九个路由）**：

| 路由 | 页面 | 回答什么 | 起步动作 |
|---|---|---|---|
| `/` | 总览 | 三样东西各有多少、缺口多大、现在在跑什么 | 只是导航 |
| `/remote` | 远端 | API 这一批有哪些 build | `table.py index`（把这一批登记进本地表） |
| `/local` | 本地 | 我们手上有哪些 build、各自对应的证据是什么 | 勾两个 → 比 config；`--provision-only` |
| `/local/<id>` | 对应（一条） | 这一份副本的卡片、字节、拉取记录、远端那一行 | `pull` / `run` |
| `/pull` | 拉取 | 条件怎么选、候选有哪些、拉了什么、留下了什么记录 | `table.py pull --build …` |
| `/jobs` | 测试 | 每个 `(build, test)` 对长什么样、哪些还在缺口里；怎么跑 | `table.py run` / `runday.py` |
| `/runs` | 运行 | 现在在跑什么、日志、取消 | 每条活动都显示它那条 argv |
| `/worker` | 轮转 | 远端队列里有什么、worker 处理过什么 | `pull_worker.py`（跑一轮 / 常驻） |
| `/analysis` | 分析 | config 漂移、回归时间轴 | `drift.py`（只读的比对在页面上直接渲染） |


### 2.0 共同规矩（一次写在这里，省得每页重复）

* **能枚举的用选择框，枚举不了的用候选列表，数字用数字框**。三种形状各有各的理由，
  页面不许把一种写成另一种：
  * `<select>`：值来自这份代码认识的词表 —— `evidence`（`any/pulled/unrecorded/registered/
    made-here/empty`，`lib/gui.py:104`）、`origin`（`lib/gui.py:102`）、`missing`（`ARTIFACTS`）、
    `test`（`TESTS`）、`ran`（`lib/gui.py:103`）、`verdict`（`lib/gui.py:107`）、`kind`、`state`、
    `job`、`older` / `newer`。**不在表里的当前值会被追加成一个 `(current)` 选项**
    （`lib/gui.py:2990`），绝不被悄悄换掉 —— 为什么见 §11。
  * `<input list="…">` + `<datalist>`：`tree`、`branch` 与 `api`。名字是开放集，API 收得下一个
    这份仓库没听说过的树、`api` 收得下一个这份仓库没听说过的地址，所以只能**建议**不能**限制**
    （`lib/gui.py:3135`、`:3155`）。
  * `<input type="number">` + 一排药丸：`days`（`min=0 max=3650`）与 `limit`
    （`min=1 max=1000`）。药丸就是链接（`_quick`，`lib/gui.py:2754`）：Firefox 只在按
    下箭头时开 datalist，而链接本身就是 URL。
* **没有任何一页要求输入 build id 或 node id**：id 只显示、可复制、可作为链接；
  `/analysis` 的两个 build 是选择框，不是文本框。手打的 URL 仍然是入口（§4），
  只是页面不靠它做事。
* **每页只有一个 GET 筛选表单**（`_form`，`lib/gui.py:2996`）：底下是 `apply` 与 `clear`
  两个控件，`data-auto="1"` 让改一个值就自动提交（`_JS` 的 `change` 监听，`lib/gui.py:2350`），
  JavaScript 没开时 `<noscript>` 明写「改一个值，然后按 apply」（`lib/gui.py:3045`）。
  它在隐藏域里带上**这一页读了、但没给控件的每一个条件**，所以 `apply` 之后的问题
  和 URL 上写的还是同一个（`offset` 故意不带：换了条件就从头看）。
  `/local` 是唯一有第二个 GET 表单的页面（`#compare-form`，`lib/gui.py:1546`）——
  那是个没有控件的空表单，只当勾选框的 owner 用，因为一行勾选框要跳到另一个路由（`/analysis`）。
  它带的两个隐藏域是**跨路由必须带走的页面状态**：读者的语言（`lang`）和这一页在读的 API
  （`api`，`_hidden()`，`lib/gui.py:3068`）。**`api` 不另起表单**：它是筛选栏里的一个控件，
  和 `tree` / `days` 并排（`_api_field`，`lib/gui.py:1600`）。
* **生效中的条件写在 chips 里，`×` 是重建出来的 URL**：`关键词=值` 一条一个，
  点 `×` 去掉的是它自己那一个键，别的键原样留着（`_chips`，`lib/gui.py:2692`）。
  所以地址栏和服务器读到的是同一个东西 —— 没有第二套状态，浏览器也就没有别的办法反驳。
* **一次一个写者**：写动作（`index pull run runday fetch worker provision drift`）在另一个写者
  正在跑时被拒（HTTP 409，说清是谁在写）；只读动作（`results`）可以并行。
  页面顶部有横幅说明现在谁在写。
* **每一页都印出它问了什么**：远端查询、目录、文件路径、命令原文都显示出来。
  **问句以 API 的地址开头**：`asked the API: <code>https://api.kernelci.org: kind=kbuild …</code>`
  （`remote_query()`，`lib/gui.py:1105`；`/worker` 自己拼的那句在 `:2243`）—— 于是
  "远端只有 2 行"自己就带着解释：那两行是*这家* API 答的。页头不再重复它：设置它的地方是
  筛选栏，叙述它的地方是问句，同一件事不说两遍。
* **`api` 是筛选栏里的一个键**：`?api=production`、`?api=https://api.kernelci.org`。
  它和 `tree` / `days` 是同一类东西 —— 决定"我在看哪份数据"，所以它住在 URL 里、住在筛选栏里、
  跟着每个链接走，**不进 cookie**。值可以是**名字**（`local` / `production` / `launch`）
  或者**任何 `http(s)` 地址**；能对上名字时链接和地址栏写名字，页面上印的永远是**地址**
  （§4）。等于启动基址时不写进 URL，所以今天所有 URL 逐字不变。
* **语言是 URL 的一个键，cookie 是唯一的客户端状态**：`?lang=zh|en`，没有 URL 里的 `lang=`
  时读 `kci_lang` cookie，再没有就看 `Accept-Language`，最后落到 `en`。只有 URL 里真的
  出现过 `?lang=` 才写 cookie（§4）。**机器接口不翻译**：`/summary.json` 与 `/api/*`
  无论如何都答英文。
* **勾选即选择**：需要选择对象的动作（拉取、跑、比 config）用勾选框，不用文本框。
  勾选框属于**一个**动作：`/local` 的勾跳 `/analysis`，`/pull` 与 `/jobs` 的勾进各自那个
  POST 表单（`form="pull-now"`，`lib/gui.py:3097`）。
* **按钮就是命令**：每个按钮 → `POST /api/actions/<name>` → `Gui.command()` 拼出**运维手打的那一条**
  （见 §3），作为一次 `Run` 起子进程。页面没有第二套行为，连参数都来自这一页的控件。
  一次点不到的事，命令行也做不到：页面**不许**假装能一次做完（最明显的例子是 §3 的 `run`）。
  拼不出来时按钮旁边写 `nothing to run: <原因>`（`_argv_of`，`lib/gui.py:1257`）——
  一句"缺什么"是真答案，编一条命令不是。
  **这个按钮是个普通表单**（`<form method="post" action="/api/actions/<name>">`），浏览器默认会
  跳到那个 JSON 答案上；页面的脚本用 `fetch` 把它接管（`_JS` 里挂在 `document` 上的 submit
  委托监听），把答案写进**这个表单自己的** `[data-status]` 行：`started <id>：<argv>`，
  被拒就把服务端那句纯文本原样写出来。关掉 JavaScript 就还是跳 JSON —— 那**正是**
  `POST /api/actions/<name>` 的契约（§4），不是要修的毛病。
* **页面不算任何东西**：见 §5。

### 2.1 `/` 总览

一行三块的「三样东西」：远端（这一批 N 行）、本地（M 行：其中 k 行有字节、j 行有卡片）、
对应（`pulled` p / `unrecorded` q / `registered` r / `made-here` s，以及 `no remote counterpart` 的行数）。
下面是**现在在跑什么**（`Run.load_all()`，2 秒轮询）和三个 owner 给的数：
账本 `Records.tally()`、缺口 `len(todo())`、每条 test 的回归 `transitions()`。
一个按钮都没有 —— 总览只负责让人知道该去哪一页。

### 2.2 `/remote` 远端

**这一个 GET 表单**（本页唯一，`_remote` 的 `_filter_bar`，`lib/gui.py:1475`）：
`tree`（`<input list="trees">`）、
`branch`（`<input list="branches">`）、`last`（`<input type="number" min=0 max=3650>` +
药丸 `all 1 3 7 14 30 90 180 365 1095`）、`rows`（`<input type="number" min=1 max=1000>` +
药丸 `25 50 100 200 500 1000`）；右边 `apply` 与 `clear`。

表单**上面**是本页生效的条件（chips）。表单**下面**三句话，一句一个事实：

| 那句话（英文原样） | 说的是 |
|---|---|
| `tree: 50 fixed names, and what has answered here so far (<code>mainline, riscv</code>)` | tree 候选 = `kernelci-pipeline/config/trees.yaml` 的 50 个固定名（`TREES_FIXED`，`lib/gui.py:144`）∪ 本地表见过的 ∪ 本次取到的 ∪ 当前值（`_vocabulary`，`lib/gui.py:2566`）；括号里是**这一台机器见过的**，不是全部 |
| `branch: the API cannot list branches, so these are the ones seen here (<code>main</code>); any name can be typed` | branch 是开放集：API 只能按 branch 过滤、列不出来（`lib/api.py`），所以这里只是输入便利 |
| `rows is this page's print cap; the window is what chooses the rows` | 两个数字各管一件事（§5）；这句话是常量 `ROWS_NOTE`（`lib/gui.py:219`），每个有这两个框的页面都印同一句 |

**表格**（`Kbuilds.getdays()` 的答案，一行一个远端 build）：
`build_id`（可复制）、`tree`、`branch`、`arch`、`defconfig`、`compiler`、`created`、
`remote says`（远端 `state` + `result` 两个 pill）、`node_id`、`here`（本地有没有卡片/字节），
末列一个 `pull…`。

**页首那一行**是"我问了什么 + 我摆了多少"（`_remote_line`，`lib/gui.py:3228`）：
`asked the API: kind=kbuild job=kbuild-gcc-14-riscv tree=any branch=any last 30 days —
showing 43 of 43 row(s) this window kept (rows=50); the API counts 1772 for this query, so
1722 older row(s) are outside the 50-row cap; 7 of the row(s) inside the cap are not in this
table - this page's own filter, not the API`。三个数各自的 owner 见 §5。

**动作**：

| 控件 | 命令 | 说明 |
|---|---|---|
| `record this window in the local table` | `python3 table.py index --tree T --days D --limit L` | 把当前这一批的**卡片**登记进本地表（写 `var/state/builds.json`）；按钮旁原话是 `cards only: it downloads nothing` |
| 行内 `pull…` | —— | 页面转换：跳到 `/pull?...&tick=<id>`，并在那一页**预勾选**这一行 |

远端页**没有勾选框**：登记是一条按条件走的命令，不是按选中的行走的命令
（`table.py index` 只认条件）。勾选属于拉取页。

### 2.3 `/local` 本地

**页首两行**，一行一个来源，别混：

* `the remote column comes from: <code>kind=kbuild job=… tree=any branch=any no window (all)</code>
  — showing …` —— 远端那一列问的是**什么查询**；
* `this page's own filter: <code>tree=riscv&amp;limit=37</code>` —— **这张表自己**筛的是什么
  （`filter.own`，`lib/gui.py:1525`；没有条件时写 `(none)`）。

**这一个 GET 表单**（`lib/gui.py:1528`）：`tree`（候选列表）、`the record says`（`evidence`：
`any/pulled/unrecorded/registered/made-here/empty`）、`origin`（`any/local/remote/both`）、
`missing`（`(any)/kernel/modules/kselftest/config`）、`rows`；下面两条 note（tree 候选说明 +
`rows` 的含义），以及 `<noscript>`。

**表格**（一行一个本地 `build_id`；行来自**两个**本地来源的并集：本地表的卡片 ∪ `var/downloads/*` 目录）：

| 列 | 内容 | 事实来源 |
|---|---|---|
| 勾选框 | 这个表单属于 `#compare-form`，不是上面那个筛选表单 | —— |
| `build_id` / `describe` | 可复制 | 本地表卡片 |
| `registered` | `node <短号>`，或 `no node id (made here)`，或 `no card in the local table` | 卡片字段（`kbuild.py` 填的） |
| `bytes` | `kernel ✓ modules ✓ kselftest ✗  38.9 MiB` | `Build.present()` + 文件大小 |
| `correspondence` | §1.4 的那几句话（本身就是到 `/local/<id>` 的链接，语言跟着页面走） | `provenance.json` |
| `remote` | `available/- (node …)` 或 `no remote counterpart`，或 `not in the newest N row(s) this query answered`，或 `the API did not answer this query: nothing is known about the remote side` | 本页那一次远端查询（`_remote_cell`，`lib/gui.py:2526`）—— **四种说法，四种事实** |
| `ran` | 三个 test 的最近判决（`records.last()`） | 账本 |
| `pull…` | 跳到 `/pull?...&tick=<id>` | —— |

**动作**：

| 控件 | 命令 / 效果 |
|---|---|
| 勾**正好两个** → `compare config` | GET `/analysis?pick=a&pick=b` → 分析页渲染三栏差异（不是命令，是页面转换；`Drift` 只读）。旁边那句是 `tick exactly two rows — their configs are compared on the analysis page (<code>Drift</code>, read-only)` |
| 行内的对应那句话 | 跳到 `/local/<id>`（对应页：卡片 / 字节 / 拉取记录 / 远端行 / 账本） |
| 行内 `pull…` | 跳 `/pull?...&tick=<id>`（在那一页预勾选这一行） |
| `publish var/serve/Image as a build` | `python3 run_latest.py --provision-only --tree T`（本地自造那条路）。按钮旁边**当面**说这个文件在不在：`<code>/…/var/serve/Image</code> is there` 或 `<code>…</code> is not there`（`lib/gui.py:1584`），不是等点了才知道 |

空表格有两种说法（`_empty_local`，`lib/gui.py:3276`）：**"这台机器什么都没有"**，和
**"条件把 N 行挡住了，点这里清掉"**——后者带着 `clear the filter` 链接和三个当前值。

### 2.4 `/local/<build_id>` 对应（一条）

**这一页不读筛选条件**：URL 上只有 `lang` 与这个 id（`render()` 把路径尾巴交给
`_correspondence`，`lib/gui.py:1293`）。它的远端那一行来自**默认窗口**的一次查询，
所以第 4 段的标题写 `the remote row — from <code>kind=kbuild job=… no window (all)</code>`，
把这次问的是什么摆出来。

正文六段，全部是摆出来的事实：

1. **`the card`**（`what we registered, and which node it came from`）：`build_id`、`describe`、
   `node_id`、tree / branch、arch / defconfig / compiler、created、`artifact URLs, as the API
   spells them`；没卡片就写 `not in the local table`，有卡片但没有 `node_id` 就写
   `no node id: this card was not registered from an API node`。
2. **`the bytes`**（`Build.present(): what is on disk, and how big`）：构件名 → 路径 → 字节数；
   没有就写 `nothing on disk under <路径>`。
3. **`the pull record`**：标题的副行就是 `provenance.json` 的路径。每一条 act（新到旧）一块：
   时间、`{n} artifact(s)`、`error`（或 `no error`），每条 entry 的
   `artifact / url / bytes / transferred`（没搬字节的那行写 `already whole, size proven,
   nothing transferred`）。没有 act 就写 `no pull recorded for this copy: …`，并说明这意味着
   什么（§1.5 第 2 条：worker 铺的、老版本拉的、手工拷的，都是这个答案）。
4. **`the remote row`**：标题的副行是 `from <code>kind=kbuild job=kbuild-gcc-14-riscv tree=any
   branch=any no window (all)</code>` —— 这一页不问条件，所以把默认那次查询原样说出来。
   正文是本次查询里同 id 的那一条（`build_id`、`node_id`、tree/branch、created、
   `state/result`、构件 URL）；没有那一条时写 `no remote counterpart in the answer to <查询>`，
   并补一句：窗口是 API 唯一听得懂的提问方式，所以这句话的意思是「**不在那次答案里**」，
   不是「哪儿都没有」。两边 `node_id` 不同就明写
   `the record names node A, the API now names node B under this build id: same id, different thing.`
5. **`the ledger`**：`Records.for_build()` 的记录（test / 判决 / exit / 来源 / 时间 / detail）。
6. **`activities`**（`whose command names this build (a text match, said so)`）：
   argv 里出现这个 id 前 12 位的 Run —— 页面自己声明这是**文本匹配**，不是对应关系。

页尾两个动作：

| 控件 | 命令 | 旁边那句 |
|---|---|---|
| `pull (re-check the sizes)` | `python3 table.py pull --build <id>` | `a pull appends an act to the record above` |
| `run the pending tests` | `python3 table.py run --build <id>` | —— |

### 2.5 `/pull` 拉取（自己的页）

**第一步：选条件**（本页的 GET 表单，`lib/gui.py:1691`）：`tree`（候选列表）、`last`（数字 +
药丸）、`missing`、`origin`、`rows` —— 也就是把「哪些候选」说清楚。

**第二步：看候选**。页首那行在末尾多一句 `N candidate(s) among them`，再往下就是远端这一次
查询的答案，一行一个：`build_id`、`describe`、`created`、远端 `state/result`、
`on disk`（`Build.present()` 已经有的构件）、`would fetch`（缺哪几个；三个都齐写 `already whole`）、
`the record now`（`provenance.json` 现在怎么说）。

**第三步：勾 + 拉**。`pull the selected` 旁边那句话把规则写在按钮上：`takes only what is missing or
not whole, and records an act for every artifact either way; rows without a card cannot be ticked,
because that command reads the local table`。勾选框只出现在**本地表里有卡片**的行上
（`table.py pull --build` 读的就是本地表）；没有卡片的行写
`no card: record the window first`（悬停是 `not in the local table: table.py pull --build reads the
table, so record this window first`），而这一页上就有那个填表的按钮
（`record this window in the local table` → `python3 table.py index --tree T --days D --limit L`，
旁边的原话是 `a candidate without a card cannot be ticked: … and this is the command that fills it`）。
勾好之后那条命令是：

```
python3 table.py pull --build 6aadee70d96a8203de6e8452 --build 6aa3689720239ade90209d50
```

**第四步：拉完留下什么**（这一页的另外一半，刷新后一直在）：

* **`what has been pulled`**（`the acts Build.make() recorded, newest first`）：所有本地 id 的 act，
  一行一条：时间、`build_id`（链到 `/local/<id>`）、构件数、总字节、`transferred` 条数、
  来源主机、`error`（或 `no error`）。一条都没有就写
  `nothing has been pulled here yet: no <code>provenance.json</code> exists under <code>var/downloads</code>`。
* **`the pull activities`**（`every one of them is this command line`）：`Run.load_all()` 里
  `kind == pull` 的最近几条，带 argv（就是上面那条命令）和 `[log]`，说明「这一次拉取」是哪条
  命令干的。一条都没有就写 `no pull activity has run from this page`。

每个 build 那一份更细的 act 在 §2.4 的第三段（`/local/<id>` 上）。

### 2.6 `/jobs` 测试

**这一个 GET 表单**（`lib/gui.py:1742`）：`tree`（候选列表）、`test`（选择框，选项 = 这张表的
行里出现过的 test）、`ran`（`any/never/ever/failing`）、`last verdict`（`(any)/pass/fail/
incomplete/error`）、`rows`。

**第 0 行是本页自己的数**：`showing 6 row(s) in the gap for this filter, out of the 6 (build,
test) pair(s) <code>re.todo()</code> reports over 3 card(s) and 6 record(s); the table is capped
at 12 row(s).` —— `re.todo()` 是缺口的 owner，页面只说自己摆了几行（`jobs.gap_query`，
`lib/gui.py:1740`）。

**A. 每一行**是一个 `(build, test)` 对：`build_id`、`tree`、`test`、`needs`（`tests.needs()`）、
`ready?`（`build.missing(test)` 的原因原文，空 = 能跑，写 `ready`）、`runs`
（`records.for_build().for_test()` 条数）、`last`（`records.last()` 的判决）、`when`、
`in the gap?`（`todo()` 里有没有它：`yes` 或 `already recorded`）。
**默认视图是全部对，不是"还没跑的"** —— 缺口只是其中一列，页首那行的第二个数把缺口有多大
直说。行内按钮写的是**它要跑的 test**：`run boot` / `run kselftest-riscv` / `run kselftest-kvm`
（`jobs.row_run` = `run {test}`，`lib/gui.py:1766`）→ 每个按钮的 `title` 与 `data-argv`
就是它自己那条 `python3 table.py run --api-url U --build <b> --test <t>`。

**B. 批量**：`test` 从 URL 读 + **这一页摆出来的那些 build** 一个一行勾选框
（`bulk` 就是上面那张表的 build_id 去重，`lib/gui.py:1736`）→
`python3 table.py run --build <勾的> --build <勾的> --test <选的>`。这一页把规则写在按钮旁边：
`this command runs even what the ledger already has; the page adds no skip of its own` ——
批量和行内都只表达「一条命令」。因为勾选框在页面上而不在 URL 里，没勾之前那个位置写的是
`nothing to run: run needs at least one ticked build`（§3）。

**C. 补跑（跳过账本已有的）**：`run a day` → `python3 runday.py --days D --tree T --limit N`，
days 的药丸就在按钮那一行里（`lib/gui.py:1790`）。旁边那句是
`this is the command that skips the pairs the ledger already has`。

**D. 别的入口**：`run the newest build once` → `python3 run_latest.py --tree T [--test X]`；
`the ledger, in full` → `python3 results.py [--build …] [--test …]`（旁边写
`read-only, no API needed`）。

### 2.7 `/runs` 运行

`Run.load_all()` 的表格：`id`、`kind`、`state`、`age`、`exit`、`what`、`argv`（悬停看全）、
两个行内动作。筛选表单只有两个框：`kind`（选项 = 磁盘上出现过的 kind）与 `state`
（`(any)/running/done/failed/cancelled`）—— 这一页不读窗口：一条活动不是 build，
窗口在这里是没有人读的条件，所以表格上也没有那个控件。

行内 `[log]`（1 秒增量 tail `/api/runs/<id>/log?offset=N`）、`[cancel]`
（`POST /api/runs/<id>/cancel`，杀进程组）。2 秒轮询 `/api/runs`，轮询用的是
`_runs_table` 同一批类名（`_JS`，`lib/gui.py:2344`）。

页面顶部那一句必须写的话（`runs.intro`，`lib/gui.py:1823`）：
`Every activity is a directory with <code>run.json</code> and <code>run.log</code>; the
<code>argv</code> column is the exact command an operator would type, so a restart loses
nothing. <b>drift</b> activities exit 1 when the two configs differ: that exit code is the
answer, not a failure.`

### 2.8 `/worker` 轮转

**这一个 GET 表单**：`state`（`(any)/available/done/running/reserved/closing`）、`name`
（远端出现过的 job 名）、`rows`；另外三个键**不是框而是药丸**，并且以隐藏域跟着表单走：
`mode`（`once` / `resident`）、`platform`、`runtime`（候选 = 队列里出现过的 ∪
`tests.DEFAULT_DEVICE` / `DEFAULT_LAB`，`lib/gui.py:1859`）。

它们做成药丸而不是框，理由是这一页自己的：**命令能从 URL 上读出来**，
所以按钮下面印的 argv 不可能和按下去跑的那条不一样（`_worker` 的 docstring，`lib/gui.py:1833`）。
药丸一行一个键，点一个就是换一条 URL。

页首那行是队列这一侧的查询：`asked the API: <code>kind=job state=any name=any</code> — 12 row(s)`；
API 没应答时后半句换成 `the API did not answer this query: <note>`（`lib/gui.py:1852`）——
**"没应答"不是"队列是空的"**，这两件事在这一页上是两句话。

**表格**：远端 job 节点（`Kjobs.getjob()`）：`node_id`、`name`、`state`、`result`、`platform`、
`runtime`、`created`、`definition`（有没有 `job_definition`）、`claimed by this worker`
（这个节点 id 在 `var/state/worker-state.json` 的 `seen` 里 = 这个 worker 处理过）。

**`the worker's own state`**（`poller.py's file, displayed and not interpreted`）：
`var/state/worker-state.json` 摆成一行 —— `file`、`cursor`（`timestamp`）、`seen` 条数、
`pending` 条数。只显示，不改、不推断（读法归 `poller.py`）。

**动作**：**只有一个按钮** `start the worker` → `python3 pull_worker.py [--once]
--platform P --runtime L --api-url U`。`once` 那个药丸决定有没有 `--once`；
旁边那句话是 `<code>resident</code> drops <code>--once</code> and keeps polling (cancel it on
the runs page)`。

（`runday.py`、`run_latest.py`、`results.py` 的入口在 `/jobs` 上 —— 它们不是队列的事。）

### 2.9 `/analysis` 分析

**这一个 GET 表单**装了这一页的全部四个控件（`lib/gui.py:1944`）：`test`（选择框，选项 =
`DEFAULT_TESTS`：`boot` / `kselftest-riscv` / `kselftest-kvm`）、`rows`（数字 + 药丸，**它才是
时间轴读的那个数**）、`older`、`newer`（两个选择框，选项 = 已知的 build id，
**值是全 id、印出来的是前 16 位**，`lib/gui.py:1942`）。表单下面那句是
`read-only: <code>Drift</code> fetches both configs and says what differs`。

两个 build 有三个来源，最后都落到同样两个值上：在这个表单里选（`?older=&newer=`）、
从 `/local` 勾两行过来（`?pick=a&pick=b`，`render()` 收下，`lib/gui.py:1310`）、
或者都不给（取已知 id 里最新的两个，`lib/gui.py:1937`）。一个都没有时页面不装样子，
而是写 `choose two builds above, or tick exactly two rows on <a …>/local</a>.`

**config 漂移**：`_drift_block()` 当场渲染三栏（`added` / `removed` / `changed`，
每栏最多列 40 条，多出来的写 `... N more`）—— 只读，不发命令。
要留一份活动就按 `run drift.py` → `python3 drift.py --older A --newer B --api-url U`，
旁边那句是 `one activity; its exit code is the answer (0 no drift, 1 drift)`。

**这一页问 API 只问一次**：两个 id 和它们的 `Kbuild` 来自**同一次读**（`_known_builds()`，
`lib/gui.py:2468`）—— 本地卡片在前、远端那 200 行在后，按 build_id 去重；`Drift` 拿到的
就是这批对象，所以它**不再为了两个 id 各扫一遍窗口**（`lib/kbuild.py: SCAN` 里写着那次扫多少钱：
生产上 `kbuild-gcc-14-riscv` 有近两千个节点）。实测：生产视图 `/analysis` 从 33s（而且那两个 id
当时根本扫不到，块里是一句 `cannot compare`）降到 **11.5s**，剩下的时间是取两个 `.config` 并解析，
那是必要的；`/api/analysis/drift` 那条端点没有页面可依，就在 `drift()` 里**自己读一次**
（`limit=SCAN`，与它替掉的那次扫描一样宽）给两个 id 共用。

**回归时间轴**：`records.series(test)` 的每一个点画一格 —— pass 与 fail 都是实心 `■`，
其它判决是空心 `□`（`_timeline`，`lib/gui.py:3298`）；`transitions()` 命中的点**描边**
（`.timeline .point.regressed`，`lib/gui.py:2286`）。**样式表不给点单独配色**，所以 pass 和
fail 在颜色上是一样的，判决本身活在 `title` 与类名里 —— 悬停给
`build_id / 时间 / 判决 / 来源`。
每条 test 一行小表：`runs`（`len(series)`）、`last`（`Records.last()` 的判决）、
`regressions`（`transitions()` 的条数）、`timeline` —— 四个数全是 `Records` /
`transitions()` 给的，页面一个都不算。

（`/api/analysis/trend` 的参数仍然叫 `scope`，那是这个接口自己的契约，见 §4；
页面上的控件叫 `rows`，因为 `trend()` 读的就是 `Filter.limit`。这一页曾经摆了一个叫
`scope` 的控件而没有任何代码读它 —— 见 §11。）

## 3. 控件 → 命令对照表（唯一的一份）

`Gui.command(name, form)` 就是这张表的实现（`lib/gui.py:1144`）。每个值都来自这一页的控件
（选择框 / 候选列表 / 数字框，§2.0）或勾选行，没有一个是手打的；
每个 flag 都是入口脚本自己的 parser 声明的；`python3` 用 `sys.executable`。
表里的 flag 顺序不是它拼出来的顺序（`index` 拼的是 `--days --limit --tree`）——
flag 的集合与取值才是这段契约，顺序不是。

`D` 与 `L` 在这张表里也**已经夹过**：`command()` 用的是和页面同一个 `_clamp()`
（`lib/gui.py:1168`），`--limit -1` 不会再从尾部切掉最新的 build（§11）。

**拼不出来的时候**：按钮下面那个位置不写命令，写 `nothing to run: <原因>`
（`nothing to run: {reason}`，`_argv_of`，`lib/gui.py:1271`）。今天真会走到这条路的只有两处：
`/jobs` 那个"跑勾选的"按钮（勾选框在页面上、不在 URL 里，所以没勾之前它拼不出 argv，
写的是 `nothing to run: run needs at least one ticked build`），和 `/analysis` 的
`run drift.py`（一个已知 build id 都没有时）。
**回复的文案按读者的语言渲染**：409 的 `unknown action …` / `pull needs at least one ticked
build` 与 404 的 `no page …` 都从同一个目录取，`?lang=zh` 就是中文（§4）。

| action | 命令 | 写 | 值从哪来 |
|---|---|---|---|
| `index` | `python3 table.py index --api-url U --tree T --days D --limit L` | ✓ | 选择框 |
| `pull` | `python3 table.py pull --build A [--build B …]` | ✓ | 勾选行（只出现在本地表有的行上） |
| `run` | `python3 table.py run --build A [--build B …] --test T [--api-url U]` | ✓ | 勾选行 + `test` 选择框 |
| `runday` | `python3 runday.py --days D --tree T --limit N [--test X --api-url U]` | ✓ | 选择框 |
| `fetch` | `python3 run_latest.py --tree T [--test X] [--api-url U]` | ✓ | 选择框 |
| `worker` | `python3 pull_worker.py [--once] --platform P --runtime L --api-url U` | ✓ | 选择框（`mode` 决定有没有 `--once`） |
| `provision` | `python3 run_latest.py --provision-only --tree T [--api-url U]` | ✓ | 选择框 |
| `results` | `python3 results.py [--build A] [--test X]` | – | 选择框 |
| `drift` | `python3 drift.py --older A --newer B [--api-url U]` | ✓ | 两个选择框 |

写者名单：`index pull run runday fetch worker provision drift`。只读：`results`。
`--api-url` 出现在**七条**上（`index` / `run` / `runday` / `fetch` / `worker` / `provision` /
`drift`），而且一律是**这一页正在读的那个基址**（`Apis.base()`，`lib/gui.py:481`；
筛选栏里选中哪家就是哪家，§4）—— 所以页面显示的命令和页面读的是同一个 API，
复制下来手打，得到的是同一件事。
`pull` 与 `results` **不带**：前者读本地表、下载走卡片里那些绝对 URL，后者读本地账本，
两个都不问 API，带上这个 flag 就是假话。

`index` **带**，而这一条是修出来的，值得写清楚：`table.py index` 自己是要问 API 的
（`table.fetch(config.client(args))`，`table.py:60`），它本来就认 `--api-url`
（`config.run_flags()`，`lib/config.py:107`）。以前 §3 这一行没有它，于是生产视图上点
「把这一批登记进本地表」跑的是不带 flag 的命令，`config.client()` 回落到 `$KCI_API_URL` /
`LOCAL` —— **它去问本地那个只有两个 build 的库，卡片永远加不进去**，而页面上那句
"这一页读的是 X" 与此直接矛盾（它是唯一真会写卡片的那条命令）。现在它与另外六条一致：
当前选中哪家，就打到哪家；本地视图上带的也是同一个地址，无害。

**没有 `table.py jobs` / `table.py todo` 按钮**：那一页本身就是 `todo()` 摆出来的表，
再放一个「打印同一张表」的按钮就是第二套行为。而且 `Run` 的 kind 词表
（`lib/run.py: KINDS`）里 `table` 是**写者**（`index`/`provision` 用它），
只读的 `table.py jobs` 也挂 `table` 会让写者闸门认错人 —— 少一个按钮换一个不含糊的闸门。

## 4. HTTP 契约

| 端点 | 干什么 |
|---|---|
| `GET /`、`/remote`、`/local`、`/local/<id>`、`/pull`、`/jobs`、`/runs`、`/worker`、`/analysis` | 九张页面（服务端渲染，无框架） |
| `GET /summary.json` | 首屏那份数据：`remote` / `local` / `correspondence` / `pulls` / `jobs` / `runs` / `ledger` / `table` / `note` / `actions` |
| `GET /api/runs[?kind=&state=]` | 所有活动（kind、state、age、exit、what、argv）—— 2 秒轮询这个 |
| `GET /api/runs/<id>/log?offset=N` | 增量 tail（新字节 + 新 offset + state） |
| `GET /api/analysis/drift?older=&newer=` | 三栏差异（只读，`Drift`） |
| `GET /api/analysis/trend?test=&scope=` | 时间轴点 + `transitions()` 数 |
| `POST /api/actions/<name>` | 起一个 `Run`，回 `{"started", "argv", "kind"}`；写者冲突 **409** |
| `POST /api/runs/<id>/cancel` | 取消（杀进程组） |

**`POST /api/actions/<name>` 回的是 JSON，而按钮是普通表单** —— 这两件事都要保持原样。
服务端答 `{"started", "argv", "kind"}`（写者冲突、坏参数是 **409 + 一句纯文本**），
所以**关掉 JavaScript 时点按钮就会看到那坨 JSON**：那是这个端点自己的契约，
不是"点了没反应"，也不该为了好看改成重定向（一个会重定向的写端点，就没有第二种用法了）。
页面开 JavaScript 时由脚本用 `fetch` 接管这次提交（`_JS` 里 `document` 上的 submit 委托监听，
只认 `form[method="post"][action^="/api/actions/"]`），把答案写进那个表单自己的 `[data-status]`
里，人不再离开页面。**筛选栏那个 GET 表单不在里面**：它靠 `data-auto` 的 `change` 监听
自己提交，本来就要跳转；`/api/runs/<id>/cancel` 也不是 `/api/actions/**`，同样不拦。

**语言**：九张页面都读 `?lang=`。协商链是 `?lang=zh|en` → cookie `kci_lang` →
`Accept-Language`（`zh-CN` / `zh-Hans` / `zh-TW` 都算 `zh`，`q=0` 是"不要这个"）→ 默认 `en`
（`pick_lang`，`lib/i18n.py:811`；`Handler._lang`，`lib/gui.py:788`）。
没听说的值**跳过而不是拒绝**（`?lang=fr` 画一张页，不是 500）。

只有 URL 里真的出现过 `?lang=` 才写 cookie，原文一个字不差：

```
Set-Cookie: kci_lang=zh; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly
```

`Secure` 没有，页面监听的是 `127.0.0.1` 上的 http。**`/summary.json` 与 `/api/*` 不受语言影响**：
它们照旧答英文（`render()` 的 docstring，`lib/gui.py:1282`）。所以 `/summary.json?lang=zh`
会写那条 cookie（`_lang()` 在分发之前跑），但**正文与非 zh 请求逐字节相同**。

**基址**：哪家 API 由 URL 的一个键 `api` 决定（`Filter.api`，`lib/gui.py:562`）。它**没有 cookie**：
"我在看哪份数据"必须在地址栏里看得见，而"读者想被怎么称呼"才是可以粘住的东西 ——
这个页面只有一个客户端状态，就是上面那条 `kci_lang`。

协商顺序只有两步，没有第三步：

```
?api=<名字或地址>  →  启动值（--api-url / $KCI_API_URL / lib/api.py 的 LOCAL，Api.url() :60）
```

**值可以是两种东西**，两种都是这一页真正接受的（`Apis.base()`，`lib/gui.py:481`）：

| 写法 | 例子 | 结果 |
|---|---|---|
| 名字 | `?api=local`、`?api=production`、`?api=launch` | `local` = `lib/api.py` 的 `LOCAL`、`production` = 它的 `PRODUCTION`（两个常量都是 import 来的，不重抄）；`launch` = 这次进程启动时那个基址 —— 只在它跟前两个都不一样时才会作为一个药丸列出来，但名字一直认得 |
| 地址 | `?api=https://api.kernelci.org`、`?api=http://127.0.0.1:9/` | 原样接受（去掉结尾的 `/`） |

两种写法**落在同一个页面上**：`?api=production` 与 `?api=https://api.kernelci.org` 渲染出来
逐字节相同（实测 34113B 两边一致），链接里统一写成 `api=production`（`Apis.of()`，
`lib/gui.py:518`）。页面**印出来**的是地址（`asked the API: https://api.kernelci.org: …`），
所以短名字没有藏起任何东西。`?api=local` 在本地栈上等于**没写**（那就是启动值），URL 里不留痕。

**校验与拒绝**（`_api_url()`，`lib/gui.py:404`）：只接受 `http` / `https`、netloc 非空、
长度 ≤ 200（`API_MAX`）、纯可打印 ASCII。别的**一律忽略并回落**到启动值，页面 **200**：

```
$ curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8090/remote?api=file:///etc/passwd'
200
```

那一页同时把丢掉的值写在页头的 clamp 位置（`filter.api_refused`）：
`api=file:///etc/passwd is not a name here and not an http(s) URL; this page reads the base it
started on` —— 一个被悄悄换掉的值，就是读者在看另一家 API 却没人告诉他。
`file:` / `javascript:` / `ftp:` / `http://`（没有 host）/ 含空格或换行的串 / 500 个字符的长串
都走这条路，而且**一个都进不了命令行**：`Gui.command()` 读的 `api` 走的是同一个
`Apis.base()`（`lib/gui.py:1427`），拒绝的值在那里得到的是启动基址。
**死端口不一样**：`?api=http://127.0.0.1:9/` 是一个**合法地址**，所以页面真的去问它，
问不通就照旧说 `the API did not answer this query (…)`（两句判据没变，§1.5），
而按钮的 `--api-url` 也跟着写这个地址 —— 页面说的和它做的是同一件事。

**跟着谁走**：`api` 在 `ROUTE_KEYS` 与 `NAV_KEYS` 的**每一项**里（`lib/gui.py:209`、`:224`），
所以 nav / chip 的 `×` / 预设药丸 / 语言开关 / 筛选表单都带着它；`_url()` 还额外**无条件**带上它
（`lib/gui.py:3022`）—— 它是唯一一个路由白名单不许否决的键，因为 `/local/<build_id>` 根本不在
`ROUTE_KEYS` 里，而它要读 API 找远端的对应物。于是 `?api=production` 下每个链接、
每个表单、每个 × 都带着 `production`，只有两个地方故意不带：`api` 自己的那个 `×`，
和筛选栏那个 `clear`（"重新开始"就是回到这台部署自己的 API）。

**动作按钮跟着走**：命令里带 `--api-url` 的那七条（§3）拿到的是**当前选中的**基址，
`_action_bar(..., api=…)` 与 `_argv_of(..., api=…)` 成对传：按钮打印的命令和它真跑的
是同一份表单（实测九条逐一相同）。本地视图（基址 = 启动值 = `local`）下这些命令带的是
`--api-url http://127.0.0.1:8001`；原来就带这个 flag 的那六条与今天**逐字节相同**：
`python3 table.py run --api-url http://127.0.0.1:8001 --build … --test boot`，
唯一变长的是 `index`（`python3 table.py index --api-url http://127.0.0.1:8001 --days …`）——
它以前不带，正是"生产视图上卡片加不进去"的原因。

**机器接口也收**：`GET /summary.json?api=production` 与
`GET /api/analysis/drift?older=&newer=&api=production` 读的是同一个键、同一套回落规则。

**规矩**：

* 未知页 → **404**，正文是 `no page '/nope'; the pages are /, /remote, /local, /pull, /jobs,
  /runs, /worker, /analysis and /local/<build_id>`；`/local/<瞎写>` 也是 404
  （`no local copy 'zzz' (see /local)`）。
* 未知动作、写者冲突、勾选为空 → **409**（`KciError` 从 `POST` 出去一律 409）。
  取消一个不存在的活动也是 **409**（`no activity 'nope'`）；
  读一个不存在的活动的 log 是 **404**（同一个 `ConfigError`，从 GET 出去）。
* 一个**不是名字**的值（`?tree=<不是名字>`，`_named`）从 GET 出去是 **404**、从 POST 出去是 409；
  动作里一个不在词表里的 `test` / `mode` / `platform` / `runtime`（`_chosen`）是 **409**，
  正文就是那句拒绝（`tree='树' is not a name; use the select boxes`，中文
  `tree='树' 不是名字；请用选择框`）。
  这两句曾经因为占位符叫 `{key}`、撞上 `t(lang, key, **fmt)` 自己的参数名而变成
  `TypeError` → **500**；`t()` 现在把 `lang` / `key` 声明成**位置专用**
  （`def t(lang, key, /, **fmt)`，`lib/i18n.py:802`），占位符可以继续叫 `{key}`，撞不上了
  （§11 第 12 条；验收脚本把这条契约钉成一项检查：正文里出现 `TypeError`/`Traceback` 即失败）。
* 任何处理器的意外异常 → **500 + 消息，并打到 stdout**（静默死掉是最坏的一种死法）。
* 只监听 `127.0.0.1`；端口被占就报出来，不偷偷换一个。

## 5. 页面凭什么说「我没算数」

| 页面上那个数 | owner | 页面做什么 |
|---|---|---|
| 判决（pass/fail/incomplete/error） | `judge`（写进账本） | 读 `Outcome.verdict` |
| 统计（跑了几次、最近一次、tally） | `re.Records` | 调 `tally()` / `for_build()` / `for_test()` / `last()` / `series()` |
| 缺口（还没跑的） | `re.todo()` | 把三元组摆成表，另加一句"本页显示了几行" |
| 回归点 | `re.transitions()` | 给命中的点描边 |
| config 差异 | `drift.Drift` | 摆 `added/removed/changed` |
| 「哪些构件在磁盘上」 | `build.Build.present()` | 摆名字、路径、大小 |
| 「对应是什么」 | `build.Build.provenance()`（拉取时写的） | 摆事实，不推断 |
| **API 说这次查询有几行**（`total`） | API 自己 | **只引用**（`Api.last_total`，`lib/api.py:57`、`:104`；`Kbuilds.total`，`lib/kbuild.py:151`）。页面不许自己数一个来顶替 |
| 窗口留下了几行（`kept`） | 这一页的筛选（`Filter.accepts`）加在那个窗口上 | 数，但说清是"窗口留下的" |
| 本页摆出来几行（`shown`） | 页面自己 | 下面那个例子里的第一个数就是它 |
| 行数、字节合计 | —— | 页面**只数自己摆出来的行**：这不是重算判决，也不是重算统计 |

**三个数各有各的主人，所以页面上是三句话**（`_remote_line`，`lib/gui.py:3228`；
`Remote`，`lib/gui.py:650`）。生产 API 上 `?days=180&limit=50` 的原话：

```
showing 43 of 43 row(s) this window kept (rows=50); the API counts 1772 for this query,
so 1722 older row(s) are outside the 50-row cap; 7 of the row(s) inside the cap are not in
this table - this page's own filter, not the API
```

* `showing 43` —— 这一页摆出来的行（`shown`）；
* `of 43 row(s) this window kept` —— 取回来的那一窗经本页筛选后还剩几行（`kept`）；
* `the API counts 1772` —— API 自报的（`total`，引用）；
* `1722 older row(s) are outside the 50-row cap` —— 因为 `limit` 只取了最新的 50 个节点
  （`1722 = 1772 - 50`）；
* `7 of the row(s) inside the cap are not in this table` —— 50 个节点里 43 个是能用的 build
  （`Kbuilds.getdays()` 的 `usable()` 筛选），差的 7 个是**本页的**筛选干的，不是 API 少给了。

**`limit` 在这份文档里只有一个意思：显示上限。** 具体地：它同时是这一页读 API 的 cap
（只把最新的 `limit` 个节点取回来，`getdays(limit=)`），也是这一页最多摆几行
（`shown = kept[:limit]`）。同一段 URL 上的 `days` 决定"问哪些行"，`limit` 决定"看多少行"。

同一个数进命令就是另一件事，而且页面把命令原样印出来：`table.py index --limit 50` 是
"最多登记 50 个可用的 build"（`Builds.fetch()` 的 cap，`lib/build.py:661` —— 那里 `limit < 1`
**直接拒绝**，因为 `[:-5]` 会悄悄砍掉最新那 5 个），而那次读本身**不设限**。

页面不重新判分、不重新统计、不自己拼 verdict 词表（旧 GUI 里有四份实现，JS 里还有第四份），
也不从 `build_id` 相等去推断同一性。

**这些"owner 给的数"是每个请求现读的**（`Gui._state()`，`lib/gui.py:1119`）：`Builds.load()` 与
`Records.load()` 在**每个请求开头**读一次盘，请求之间不共享。页面上那些按钮起的子进程
（`index` / `pull` / `run` / `runday` / `worker`）写的正是这两份东西，所以"读完就冻住"的页面
会在第七条款写进账本之后继续说六条 —— 修掉那次事故的**症状**就是"跑了 boot 但是没更新"。
一次请求里只读一次（`/local` 摆 200 行时 `local_row()` 每行都要账本）：缓存放在
`threading.local()` 里，由 `Handler.handle_one_request` **每个请求开头清掉** ——
`protocol_version = "HTTP/1.1"`，同一条 keep-alive 连接上一个线程连着处理多个请求，
"一个请求一个线程"在这里不成立。也不放进 `Gui` 的字段：那是 `self.note` 竞态的同一类错误。
`builds=` / `records=` 两个构造参数还在，但只是**测试用的显式覆盖**，入口 `gui.py` 一个都不传。

**值不翻译，label 才翻译。** 表格里的 `pass` / `fail` / `pulled` / `running` 是
`judge` / API / 记录自己说的词，也是 `PILL_WORDS` 拿来配色的类名（`lib/gui.py:208`）
——第二个词表就是第二份实现，页面不许有。所以中文页面上
`<option value="pass">pass</option>`（值 `pass`，字也是 `pass`），
而 `<option value="pulled">有拉取记录</option>`（值还是 `pulled`，读的是中文）：
**变的是读到的字，不是发出去的值**。整句话当然是翻的（§10）。

## 6. 明确不做

* 不在页面里改远端状态（唯一的远端写入口还是 worker 的 callback）；
* 不做多用户 / 登录（只监听 `127.0.0.1`）；
* 不做 job 编辑器；
* 不用 WebSocket（2 秒轮询够用，一个人点的页面）；
* 不做「删除本地副本」按钮 —— 没有对应的入口命令，页面就不该有那个按钮
  （要先有命令，才有按钮）；
* 不把三样东西合成一张表（那正是 v1 被否掉的原因）；
* **不翻译机器接口**：`/summary.json` 与 `/api/*` 是契约，`?lang=zh` 下也答英文。
  唯一跟着语言走的是 404 / 409 的**拒绝句子**（那是给人读的），
  以及 `/runs` 里 `what` 那一列的目标名（`Gui.start()` 自己拼的，`lib/gui.py:1227`）——
  `argv` 永远不翻，那是命令；
* **不给判决词第二套词表**：`pass` / `fail` / `incomplete` / `error` 和 job / run 的状态词
  在两种语言里都是同一串字符（§10 那 39 条"两列相同"）。翻的是它们**旁边**的标签和句子，
  不是词本身 —— 一份词表配一份实现，第二份就是第二个真相；
* **不为语言新增端点，也不在仓库里新增状态文件**：语言只走 `?lang=` 和一条 cookie，
  页面里没有 `/{lang}/...` 路由、`var/` 里没有 `lang.json`、`lib/layout.py` 不知道语言这件事。
* **换基址是操作员的显式选择，所以允许**：`?api=` 可以指向任何 `http(s)` 地址，包括生产。
  这一条**不**跟上面"不翻译机器接口"那类"明确不做"相冲突 —— 页面本来就有按钮执行带
  `--api-url` 的真实命令（§3），把基址限制住只会让"页面显示的"和"真正跑的"分家，
  那正是这份文档一直在防的事。代价用别的方式付：地址印在问句里、选中非启动值时筛选栏
  明说"带 `--api-url` 的按钮会打到这家"、`api` 待在 URL 里所以可复制也可审计（§4）。
  **但也不多给一套机制**：没有 `kci_api` cookie、没有第二个表单、没有状态文件 ——
  `api` 就是一个筛选键，和 `tree` / `days` 同一个位置、同一套携带规则。

## 7. 与 `include/kci/view.hpp` 的差（需要在头文件里补的名字）

这一版落地后，`view.hpp` 里 §16/§19 的描述旧了，代码用的是这些：

| 名字 | 现在（`view.hpp`） | 应该长成（代码里已经是这样） |
|---|---|---|
| `Filter` | `tree/branch/arch/defconfig/job/days/origin/has/missing/ran/test/verdict/text/limit/offset` | 加 `evidence`（`any/pulled/unrecorded/registered/made-here/empty`）、`asked_days` / `asked_limit`（`optional<int>`：URL 上问的数，用来把"夹过"说出来）、`pick` / `tick`（页面状态，不是条件），其余照旧（`lib/gui.py:379`） |
| `Filter::accepts` | `accepts(Kbuild, Builds*)` | 加一个可选参数 `test`（`ran`/`verdict` 收到某一个 test 上，jobs 页的每一行就是这个语义），再加一个 `Local` 参数（`origin`/`evidence`/`has`/`missing` 读的是真实的本地拷贝，`accepts(Kbuild, Records, Local, test)`，`lib/gui.py:486`） |
| `Filter::clamps`（新） | 无 | `clamps(lang) -> vector<string>`：这个 URL 问了、但没拿到的数（`lib/gui.py:446`）—— 夹了就要说出来 |
| `Provenance`（新） | 无 | 一条 act：`at`、`error`、`entries[{artifact,url,bytes,transferred}]`；`Build::provenance()` 读它，`Build::make()` 写它 |
| `Build::present()`（新） | 无 | `map<string,string>`：构件名 → 本地文件（`files` 那个形状） |
| `Remote`（新） | 无 | 一次 API 答案的三个数：`query`、`shown`、`kept`、`total`、`limit`、`note`，外加 `coverage(lang)`（`lib/gui.py:650`） |
| `Local::state_text` | （§19 的注释里只有 `state`） | `state_text(lang)`：一句话说清记录说了什么、没说什么（`lib/gui.py:620`） |
| `Gui` | `serve()/summary()/render()/start()/status()/actions()` | 保留，`render(page, query, lang)` 变多页；页面从四个变九个（`view.hpp` §19 的注释要重写） |
| `Gui::command` / `start` | 无（`start(action, arg)`） | `command(name, form, lang)` / `start(name, form, lang)`：语言只到得了拒绝句子，argv 不翻（`lib/gui.py:1144`、`:1215`） |
| `Api::nodes` / `Api::count`（`remote.hpp` §4） | 分页读 | `nodes(kind, filters, limit=, offset=)` 的 `limit` 是**整次读的 cap**（page size 仍是 `PAGE=200`），`count()` 先问 API 自报的 `total`（`lib/api.py:80`、`:153`）—— "最新 N 条"是 API 答案的尾巴（它默认从旧到新，而且没有排序参数） |
| `i18n`（`lib/i18n.py`） | —— | **已经补上了**：`view.hpp` §20 有 `Lang`、`t`、`pick_lang`、`key_for`、`is_key`（中英两份、协商顺序、未知 key 的行为都写在那儿） |
| `Layout`（`base.hpp` §2） | 没有 provenance 的位置 | 加 `Layout::provenance(build_id)`（文件名常量现在暂时住在 `lib/build.py`） |

这一轮**只同步了文档**（`src/GUI.md`、`README.md`）：代码是上一轮定稿的，一行没动，
所以上面这些"应该长成"仍然是留给下一轮的去处 —— 除了 `i18n` 那一条，它已经在头文件里了。

## 8. 这一版对着真数据验过的（HTTP 打进去，不是看代码）

三台自己起的实例，全部 `127.0.0.1`，打完就 kill：

```bash
B=http://127.0.0.1:8090                                        # 本地栈 http://127.0.0.1:8001
B2=http://127.0.0.1:8091                                       # --api-url http://127.0.0.1:9/
B3=http://127.0.0.1:8092                                       # --api-url https://api.kernelci.org
python3 gui.py --port 8090
python3 gui.py --port 8091 --api-url http://127.0.0.1:9/
python3 gui.py --port 8092 --api-url https://api.kernelci.org
```

本地栈那一台当时的数据：本地表 3 张卡（`6aa3689…` / `6aadee70…` / `deadbeef1234`）、
账本 6 条、`var/downloads` 3 个目录 —— 卡片 ∪ 目录 = **4 行**，所以 `/local` 是 4 行不是 3 行。
本地栈只有 2 个 kbuild 节点：`2026-09-17T12:37` 与 `2026-09-19T08:24`（UTC，测量时刻 09-19 14:11）。

| 验的什么 | 命令 | 结果 |
|---|---|---|
| 九个页面 | `for p in / /remote /local /pull /jobs /runs /worker /analysis /nope; do curl -s -o /dev/null -w "%{http_code} $p\n" "$B$p"; done`，再加一次 `curl "$B/local/6aadee70d96a8203de6e8452"`（第九页就是这个路由） | 那八个路由加 `/local/<id>` 都是 **200**，`/nope` **404** |
| 中英各一遍 | 同样九个，各加 `?lang=zh` | 九个都 **200**，`<html lang="zh">`，导航变「总览/远端/本地/拉取/测试/运行/轮转/分析」 |
| `days=0` 是"不限窗口" | `curl "$B/remote?days=0"` vs `?days=1` | 查询行分别是 `no window (all)` / `last 1 days`；行数 **2 vs 1**（`showing 2 of 2` / `showing 1 of 1`）—— 窗口真的传到了 API，不是被当成缺省值 |
| 手输的数字不被改写 | `curl "$B/remote?limit=37&days=365"` | `value="37"`、chip `limit=37`、按钮下的 argv `… --days 365 --limit 37` —— **37 原样活着**（旧版点一次 apply 会变成 50） |
| 夹上限要说出来 | `curl "$B/remote?limit=99999"` / `?days=1000000000000` | 都是 **200**；页头两段 `rows=1000 (asked 99999, capped)`、`last=3650 (asked 1000000000000, capped)`；`?lang=zh` 下是 `rows=1000（问的是 99999，夹到上限了）` |
| 一个没听说过的 tree 不是 500 | `curl "$B/remote?tree=next"` | **200**，`tree=next`，0 行，`the API answered, and the answer is empty`。`next` 就在那 50 个固定名里，所以它可提交 |
| "API 没应答"和"答案是空的" | `curl "$B/remote?tree=next"`（本地）与 `curl "$B2/remote"`（死端口） | 四句各不相同：`the API answered, and the answer is empty for this query (…)` / `the API did not answer this query (… is not answering after 3 attempt(s) …), so this table is empty because nothing arrived — not because the API has no such build` / `no candidates: the API answered, and nothing in this window passes the filter…` / `no candidates, because the API did not answer this query (…)` |
| `/pull?origin=local` 不再是 0 候选 | `curl "$B/pull?origin=local"` | **2 candidate(s) among them**，2 行（旧版把 `local=None` 读成"我们什么都没有"，恒 0） |
| §3 的 argv | 一个对照脚本：把 §3 的九行写成 `{flag: [values]}`，逐行调 `Gui.command()` 比对（**一个进程都不起**，所以没有副作用） | 九行 **ALL OK**：`table.py index --days 30 --limit 50 --tree riscv`、`table.py pull --build A --build B`、`table.py run --api-url U --build A --test boot`、`runday.py --days 1 --limit 50 --tree riscv --test boot --api-url U`、`run_latest.py --tree riscv --test boot --api-url U`、`pull_worker.py --once --platform qemu-riscv64 --runtime pull-labs-riscv --api-url U`、`run_latest.py --provision-only --tree riscv --api-url U`、`results.py --build A --test boot`、`drift.py --older B --newer A --api-url U` |
| 页面上的按钮和那条 argv 是同一个 | `curl "$B/jobs?limit=6" \| grep data-argv` | 行内按钮写 `run boot` / `run kselftest-riscv` / `run kselftest-kvm`（不再是一排一样的 `run`），`title` 与 `data-argv` 都是各自那条命令；`/jobs` 那个批量按钮的位置写 `nothing to run: run needs at least one ticked build` |
| 生产上一次页面加载要几个请求 | `Api._request` 打桩后跑 `Kbuilds.getdays("", 180, None, limit=50)` vs 不设 cap | 设 cap：**2 个请求**（`/count` + `/nodes?offset=1722`），2.5s；不设 cap：**9 个 `/nodes`**，4.3s —— 同一个窗口，7 个请求的差别 |
| API 没有排序参数 | `curl "https://api.kernelci.org/latest/count?kind=kbuild&name=kbuild-gcc-14-riscv&sort=created"` | **0** —— `sort` 被当成属性过滤了；同一个查询去掉 `sort` 是 **1782**。所以"最新 N 条"只能从尾巴取（API 默认从旧到新，本地栈 `offset=1` 拿到的就是最新的那条） |
| 三个数各说各的 | `curl "$B3/remote?days=180&limit=50"` | `showing 43 of 43 row(s) this window kept (rows=50); the API counts 1772 for this query, so 1722 older row(s) are outside the 50-row cap; 7 of the row(s) inside the cap are not in this table - this page's own filter, not the API` |
| 不在最新 N 行里 | `curl "$B3/local?limit=25"` | `not in the newest 25 row(s) this query answered` —— 第三种事实，不是 `no remote counterpart` |
| 语言协商 | `?lang=zh` / `?lang=zh-CN` / `?lang=ZH-cn` / `?lang=zh_Hans` / `?lang=fr` / `?lang=*` / `Cookie: kci_lang=zh-TW` / `Accept-Language: zh-CN,…` / `Accept-Language: zh;q=0` | 前四个都是 `zh`（**区域标签在 URL 和 cookie 上也归一化**）；`fr` 与 `*` 落到 `en`；cookie `zh-TW` → `zh`；头 `zh-CN` → `zh`；`q=0` → `en` |
| cookie 只在 `?lang=` 时写 | `curl -D - -o /dev/null "$B/remote?lang=zh"` vs 不带 `lang` | 有 `Set-Cookie: kci_lang=zh; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly`，**没有 `Secure`**；不带 `lang` 的请求一个 `Set-Cookie` 都没有 |
| 机器接口不翻 | `diff <(curl $B/summary.json) <(curl "$B/summary.json?lang=zh")` | **逐字节相同**（`/api/runs?lang=zh` 也是英文）。`remote` 那一块是 `query` / `shown` / `kept` / `total` / `limit` / `coverage` / `rows`；API 死掉时 `note` 有值、`total` 是 `null`、`shown` 与 `kept` 是 `0` |
| 语言只在非默认时进 URL | `curl "$B/remote?days=1"` vs `?days=1&lang=zh` | 英文页里唯一带 `lang=` 的链接是「中文」那一个；中文页里切回英文的链接是 `/remote?days=1`（不带 `lang`）—— 两种语言互切都不会把 `lang=en` 写进 URL |
| 页头说的是哪家 API | `KCI_API_URL=http://127.0.0.1:9/ python3 gui.py --port 8093` | 页头 `api: <code>http://127.0.0.1:9</code> (switch it with <code>python3 gui.py --api-url …</code> or <code>$KCI_API_URL</code>)` —— 环境变量和 `--api-url` 都落在这里 |
| 文案的测试 | `python3 lib/i18n.py --check lib/gui.py` | `327 个 key（en 327 条，zh 327 条）`、`351 处 t() 调用`、缺失 0、zh 缺失 0、未使用 46、`zh 与 en 相同 39 条`、退出码 0。那 46 条里 41 条是拼出来的名字（`nav.` + 页名、`lang.` + 语言、`_LABELS` / `_EVIDENCE_KEYS` 的值），真没人用的是 5 条（`count.builds`、`filter.builds`、`btn.compare`、`word.build`、`btn.run`） |
| 提示是每个请求自己的 | 一个 `Gui`、4 个线程、240 次渲染：两个线程的 API 一直答，两个线程的 API 一直立刻失败；每个页面拿它自己那一次读去对 | 这一轮之前的 `lib/gui.py`：**38 页串味**（"答了"的请求印着别人的"没应答"）；现在：**0 / 240** |
| 配色对比度 | 从 `lib/gui.py` 的 `_CSS` 里解出两套 27 个 token，逐对算 | 24 组配对（12 组 × 浅/深）全部 **≥ 4.5:1**；最低是浅色 `--muted` 落在 `--bg` 上，**5.5477:1**（写成 5.55）。样式表注释里那 8 个浅色数字（ok 7.95 / bad 7.48 / warn 6.62 / err 7.39 / info 7.22 / idle 8.09 / body 15.31 / muted 6.00）与实测**逐位相同** |
| 拒绝要有答案 | 见 §4 那张清单 | 未知页 404、未知动作 409、勾选为空 409、取消不存在的活动 409、不存在的 log 404、`/local/<瞎写>` 404、`?tree=树` 404（正文是那句拒绝）、动作里乱填的 `test` 409；任何一条的正文里都没有 `TypeError` / `Traceback` |
| 非 ASCII 的名字进不了命令行 | `curl "$B/local/%E6%A0%91"`、`POST /api/actions/pull -d selected=%E6%A0%91`、`gui._token('树')` | 404（`no local copy ''`）、409（`pull needs at least one ticked build`）、`_token('树') == ''`；`'../../etc'` 也是 `''`，`'riscv'` 与一个真 build id 原样通过 |
| 一个巨大的 `days` 撞不出 500 | `curl "$B/remote?days=1000000000000"` | **200** + `last=3650 (asked 1000000000000, capped)`。两层守卫各管一头：`Filter.from_query` 夹住（页面因此还能说话），`_iso_ago`（`lib/kbuild.py:277`）拒绝夹不住的那种调用方 —— 去掉那一行，同一个数在 `time.gmtime` 里是 `OSError: [Errno 75] Value too large for defined data type`，而 `OSError` 不是 `KciError`，处理器只会把它变成 500 |

一个和这一页无关但值得记下的事实：`var/runs/` 里那些空目录是**空的 job 工作目录**
（`Job.run()` 的 scratch，跑完就空了、没有 `run.json`），不是 `Run` 活动。
`/runs` 这一页只认 `Run.load_all()` 扫出来的 `var/runs/<id>/run.json` —— 那是正确读数，不是漏了。

### 8.1 第三轮（参数 / 交互 / 皮肤 / 双语全部落地后）重打一遍

| 验的什么 | 怎么验的 | 结果 |
|---|---|---|
| 八页 × 中英 | 每页 `curl` 一遍，`?lang=en` 与 `?lang=zh` | 全 **200** |
| 与**旧版代码基线**的数据差分 | 用本轮之前的 `lib/gui.py` + `lib/i18n.py` 起一台实例，同一批查询逐项比 build_id 集合、判决、行数 | **`0 differences`** |
| argv 仍等于 §3 表 | fake-spawn harness 上逐一 POST 九个动作（`Run.start` 换成假体，什么都不真跑） | **`ALL OK`**：`index` 现在也带 `--api-url`，`pull`/`results` 不带 |
| 拒绝要有答案 | 未知页 / 非名字的 tree / 词表外的过滤值 / 未知动作 / 空勾选 | 404、404、200（过滤值回落默认，不是错误页）、409、409；正文里没有 `TypeError` / `Traceback` |
| 结构 / 皮肤 | viewport、每页**一个** GET 筛选表单、无外链资源、每个控件有 label、18 个 pill 词都能产出色 | **0 失败** |
| 配色对比度 | 从 `_CSS` 解出两套 token，逐对算 WCAG | 24 组最低 **5.55:1**（全部过 AA 正文 4.5:1） |
| **按钮不再把浏览器甩到 JSON** | 手写最小 DOM 桩在 node 里跑**渲染后的**页面脚本，伪造一次 submit | **5/5**：提交被拦截（无跳转）、POST 打到表单自己的 action、2xx 的回执写进**该表单自己的**状态行、409 的原文落在那里、GET 筛选表单不受影响 |
| **页面是实时的（不用重启）** | 隔离实例 + **另一个进程**往账本写一条记录，然后同一个 URL 再取一次 | 计数 **0 → 1**；`/jobs` 那一行从 `0 / - / -` 变成 `1 / pass / 时间` |
| **生产上登记真能加卡片** | 隔离工作目录：`table.py index --api-url https://api.kernelci.org --days 1 --limit 5` | 卡片 **3 → 7**（新增的来自 `net-next` / `mainline(master)` / `riscv(fixes)`） |
| 一份数据一个请求只读一次 | 300 张卡的工作区，把 `Records.load` / `Builds.load` 包成计数版 | 带请求级缓存：**1 次**（0.035s）；不缓存：**207 次**（0.476s） |

这些探针（`accept.sh`、`datacheck.py`、node 的 DOM 桩、fake-spawn harness）都在 `/tmp` 下，
**不是仓库的一部分**；`GUI-OPS.md` §8 给了不依赖它们的复核命令（`lib/i18n.py --check`、
`verify-worker-guards.py`、几条 `curl`）。


## 9. 2026-09-19：一次真实的"点了没反应"排查

现象：页面上点 apply 没有任何反应。三个原因叠在一起，每个单独都够呛：

1. **启动页面时只 unset 了小写代理变量**（`http_proxy`/`https_proxy`），大写那对还在。
   页面对外的请求（files.kernelci.org 的 `.config`）于是走了本机那个坏掉的代理
   （`127.0.0.1:7899`：接受连接、不回话）—— 一次读超时 60 秒，`Api` 还会重试。
2. **服务器是单线程的**：那一个卡住的请求把后面所有请求都堵在队列里，
   包括用户点的那次 apply。证据：`ss` 上 `LISTEN` 的 Recv-Q 堆到 6，连接全在 CLOSE-WAIT。
3. **`--api-url` 是静默失效的**：入口把 URL 字符串传给了只吃 argparse 命名空间的
   `config.client()`，于是页面永远连本地 API（`getattr("http://…", "api_url", None)` → None）。
   而且 `Api` 会把 `requests` 的 `ReadTimeout` 原样漏出去，穿过所有 `except KciError`，
   所以既没人能报"API 不通"，也没人能把超时降下来。

修法（都在代码里，不是靠叮嘱）：

* `lib/gui.py` 换成 `ThreadingHTTPServer`，并给每个请求打一行"路径 + 耗时 + <-- slow"；
* 页面用的客户端 `timeout=10`（旧 dashboard 当年也是 10 秒/1 次重试的耐心）；
* `Api._request` 把**任何** `requests` 异常收成 `ApiError`（连接被拒仍重试，读超时不再重试）——
  API 层漏出别人的异常，就是让每个调用方都得认识 `requests`；
* `config.client()` 现在收到字符串会直接报错（"要的是解析过的命令行，不是 URL"），
  入口改成传命名空间；
* 值过滤改成**严格**：条件写 tree=x，一棵树都不知道的行就不该留在表里 ——
  这正是"我过滤了却像没生效"的来源；
* 空表格分两种说法：**"这台机器什么都没有"** 和 **"条件把 N 行挡住了，点这里清掉"**。

实测（指着 127.0.0.1:9999 上一个"接受连接但不回话"的假上游）：

| 页面 | 修之前 | 修之后 |
|---|---|---|
| `/runs`（不需要 API） | 被堵死 | 0.004s |
| `/remote`、`/local`（需要 API） | 卡住直到超时，且不说明原因 | 10s，0 行，并写明"the API did not answer: … did not answer: HTTPConnectionPool…" |

### 9.1 同一天的下一轮（参数 / 交互 / 皮肤 / 双语）之后，上面哪几条还成立

原记录不改，只补。逐条查过：

| 第 9 节的结论 | 现在 | 证据 |
|---|---|---|
| `ThreadingHTTPServer` | **仍然** | `lib/gui.py:837`；每个请求仍然打一行"路径 → 状态 耗时"，超过 2 秒加 `  <-- slow`（`lib/gui.py:826`） |
| 页面用的客户端 `timeout=10` | **仍然** | `API_TIMEOUT = 10`（`lib/gui.py:56`）、根入口 `GUI_TIMEOUT = 10`（`gui.py:24`）、`config.client(args, timeout=…)`（`lib/config.py:87`） |
| 值过滤是严格的 | **仍然** | `Filter.accepts`：没有卡片、却又有 tree/branch/arch/defconfig/text 条件的行**直接排除**（`lib/gui.py:495`）——"我过滤了却像没生效"的老毛病没有回来 |
| 空表格分两种说法 | **变多了，而且分得更细** | `/local` 仍是两种（`_empty_local`）；远端多了第三种：**"API 没应答"** 与 **"答案是空的"** 现在是两句不同的话（`_empty_remote`，`lib/gui.py:3256`），拉取页同理（`_pull_form`） |
| 横幅文案 | **同一句话，换了个住处** | 现在是 `header.api_down`（`lib/i18n.py`），而且**每个请求带自己那一份 reason**：旧的 `self.note` 在 `ThreadingHTTPServer` 下面会串味（§11 第 5 条） |
| 代理变量那段 | **仍然只是操作纪律** | 那一条从来没写进代码（代码只能把超时从 60 压到 10），启动前 `unset` 大写小写两对仍然要人做 |

## 10. 皮肤与双语

### 10.1 皮肤：一份带令牌的样式表（`_CSS`，`lib/gui.py:1999`）

一条规矩管住全部：**颜色只在 token 里出现**。`:root` 是浅色那一套，
`@media (prefers-color-scheme: dark)` 换掉同一批 27 个 token —— 换的只有 token，
**一个选择器都不动**。理由写在样式表里：某个主题漏掉一个选择器，就是一个没人看得出来的
不可读元素，而且没有第二种办法发现它。

| 东西 | 在哪 | 为什么 |
|---|---|---|
| 粘性页头 | `.site-head`（`lib/gui.py:2081`） | 翻到第 200 行还能切页 |
| 粘性表头 | `thead th { position: sticky; top: var(--head-h) }`（`:2213`） | `--head-h` 默认 96px，窄屏 120px / 600px 以下 168px（`:2308`、`:2317`）—— **页头高度一变，这个数就得跟着变**，否则表头会滑到导航底下 |
| **没有 `overflow-x` 包裹层** | 注释在 `:2205`，`_table` 的 docstring 在 `:2848` | 一张 `overflow-x` 的包裹层会自己变成滚动容器，粘性表头就只粘在那层里、不再粘在页面上。所以宽列**换行**（`td.wrap`），不横着滚 |
| 数字不跳 | `font-variant-numeric: tabular-nums`（`:2131`、`:2228`、`:2254`） | 2 秒轮询重画时，等宽数字不会让整列左右抖 |
| 状态块 | `.pill` 系列（`:2253`–`:2277`） | 第二个类是**值本身**（`pass` / `running` / `pulled` / `available`…），所以 JS 里没有第二份词表，两套主题都从 token 取色 |
| 窄屏 | `<meta name="viewport" content="width=device-width, initial-scale=1">`（`:2419`）+ 两个断点 | 900px 以下字段放宽、600px 以下单列、字号降一档 |
| 日志框 | `_log_box()` 直接渲染成 `hidden`（`:3359`，CSS `:2295`） | `showLog()` 才把属性摘掉：没有在看活动的页面，底下不该蹲着一个空的灰框（旧版四个页面都有） |
| 导航只有一份 | `_nav()`（`:3364`）；页脚只留 `summary.json` 和那句话（`:2432`） | 旧版页脚又抄了一遍导航 |
| 慢请求看得见 | `log_request`（`:826`） | 超过 2 秒打 `  <-- slow` |

配色对比度是**算出来的，不是看出来的**：从这份 `_CSS` 里解出两套 token，逐对算相对亮度比，
24 组（12 组配对 × 浅/深）全部在 AA 正文线 4.5:1 以上，最低的一组是浅色 `--muted` 落在 `--bg`
上的 **5.5477:1**。样式表注释里那 8 个浅色数字（`ok 7.95` … `muted 6.00`）与实测逐位相同。
**改一个颜色就要重算这一组数**，这句话也写在样式表里（`:2011`）。

### 10.2 双语：一份目录，两个方向

**页面说的每一句话都住在 `lib/i18n.py`**，按点分名字取：`t(lang, "remote.asked")`。
`lib/gui.py` 是唯一的读者（`from .i18n import DEFAULT_LANG, LANGS, pick_lang, t`，
`lib/gui.py:48`），渲染代码里不许再写死句子。目录的结构是：

* **`LANGS = ("en", "zh")`，默认 `en`**（`lib/i18n.py:67`）。333 个 key，en 333 条、
  zh 333 条，一条不缺。
* **en 那一列 = 页面今天说的那句话，逐字**。所以"接文案"这件事换个语言，不换内容：
  英文模式渲染出来和接文案之前一模一样。
* **zh 那一列是给运维读的**：短句，术语跟着这份文档（远端 / 本地 / 对应 / 拉取 / 账本 /
  判决 / 缺口 / 回归 / 登记 / 轮转）。
* 占位符就是 `str.format` 的 `{n}`，没有复数规则：英文保留 `row(s)` 的写法，中文不数复数。
* **未知 key 返回 key 本身，缺语言回落 en，占位符对不上就原样返回**（`t()`，`lib/i18n.py:781`）
  —— 页面不许因为一句话死掉。

**协商顺序**（`pick_lang`，`lib/i18n.py:811`）：

```
?lang=zh|en  →  cookie kci_lang  →  Accept-Language（按 q 值，同权重取靠前的标签）
             →  默认 en
```

`zh-CN` / `zh-Hans` / `zh-TW` / `zh_Hans` / `ZH-cn` 在**三个来源上都算 `zh`**
（`_asked()`，`lib/i18n.py:832`；`_from_tag()`，`:870`），`q=0` 是"不要这个"、直接丢掉。
没听说的值**跳过而不是拒绝**：`?lang=fr` 画一张英文页，不是 500。
（有人以为区域标签只在 `Accept-Language` 上归一化 —— 不是：URL 和 cookie 上一样归一化，
`?lang=zh-CN` 实测就是中文，而且写下来的 cookie 就是 `zh`。）

写 cookie 的原文（`Handler._send`，`lib/gui.py:1008`）：

```
Set-Cookie: kci_lang=zh; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly
```

只有 URL 里真的出现过 `?lang=` 才写；没有 `Secure`（页面在 127.0.0.1 上的 http）。
**这是这个页面唯一的客户端状态**（§6）：`api` 这一轮加进来的是**第二个 URL 键**，
不是第二条 cookie —— 它跟着每个链接和表单走，所以浏览器里没有什么要记的
（`Handler._send` 里只有一处 `Set-Cookie`，就是上面这条；`grep -rn kci_api lib/` 无输出）。

**值 / 标签分离的三条缝**，翻的是标签，不是值：

| 缝 | 在哪 | 干什么 |
|---|---|---|
| `_LABELS` + `labels=` | `lib/gui.py:239`、`_labels()` `:259`、`_select(..., labels=)` `:2967` | 一张 `值 → 目录 key` 的表；`<option value="pulled">有拉取记录</option>` —— 值还是 `pulled` |
| `_option(value, current, label)` | `:2954` | 选项的文字可以换，`value` 一个字符都不动；空值就是 `(any)` |
| `_pill(value, kind, label="")` | `:2796` | 类名永远是值（配色靠它），说的字可以换成 label；不传 label 就说话本身 |

**43 条"两列相同"是有意的**，`--check` 会把它们单独列出来让你逐条看。拆开是：
23 个 `word.*`（`argv`、`build_id`、`tree`、`test`、`platform`…）加 1 个 `state.node`
—— 代码里的词，两列本来就该一样；2 个 `lang.*`（`English` / `中文` 各自的名字）；
3 张词表的标签共 13 条：`verdict.label.*`（4 个判决词）、`job_state.label.*`（5 个）、
`run_state.label.*`（4 个）。后面这 13 条就是 §5 那条规矩：判决词与状态词是
`judge` 与 API 说的词，翻它们等于造第二份词表（`_LABELS` 上面的注释，`lib/gui.py:229`）。
这一轮多了 4 条同类：`filter.api`（框上的标签就是 `api` 三个字母）与 3 个 `api.name.*`
（`local` / `production` / `launch`）—— 它们是**URL 里的值**，出现在 `?api=production`
和 chip 上，翻它们等于让地址栏和页面对不上；要翻的是它们**旁边**的句子
（`filter.api_hint`、`api.switched`、`filter.api_refused`），那三条两列都不一样。

**命令行就是测试**：

```bash
python3 lib/i18n.py --check lib/gui.py   # 缺失 / 未使用 / zh 与 en 相同；缺失或 zh 缺失则退出 1
python3 lib/i18n.py --map lib/gui.py     # key -> 它在 gui.py 的第几行
```

今天的读数：`333 个 key（en 333 条，zh 333 条）`、`lib/gui.py - 362 处 t() 调用，另有 9 处的
key 不是字面量（读不出来）`、缺失 **0**、zh 缺失 **0**、`zh 与 en 相同` **43**、退出码 **0**。
"未使用 49" 不是缺陷：其中 44 条是**拼出来的名字**（`nav.` + 页名、`lang.` + 语言、
`api.name.` + 基址名、`_LABELS` / `_EVIDENCE_KEYS` 的值），扫描器只认字面量；
真正没人引用的是 5 条
（`count.builds`、`filter.builds`、`btn.compare`、`word.build`、`btn.run`）。

**两个坑，一个是真的，另一个是名字像真的**：

1. **`lib/i18n.py` 不许 `import re`。** 它要能被当脚本跑（`python3 lib/i18n.py --check …`），
   那一刻 `lib/` 自己进了 `sys.path`，`re` 就解析成**这个包自己的 `lib/re.py`**（账本读取器）。
   加了 `import re` 之后的原样报错（我在一份拷贝上复现过）：
   `AttributeError: partially initialized module 're' has no attribute 'compile'
   (most likely due to a circular import)`。这条禁令在文件头上写着（`lib/i18n.py:60`），
   手写的扫描函数就是它的代价。
2. **语言只在非默认时才写进 URL**（`_url()`，`lib/gui.py:3035`）。`lang=en` 不会被写出来：
   否则今天所有英文 URL 都会为了一个读者没提的要求而变样。中文页面上切回英文的那个链接
   是 `/remote?days=1`，不带 `lang`；中文页面上别的每个链接都带 `lang=zh`。
3. **基址也一样：只在非启动值时才写进 URL**（`Filter.to_query()`，`lib/gui.py:649`）。
   所以今天所有 URL 逐字不变，`?api=local` 在本地栈上等于没写（它*就是*启动值）。
   筛选栏那个框里放的是**键**（`production`），框的占位符是"空值是什么意思"
   （= 启动时的地址 `http://127.0.0.1:8001`），datalist 两种写法都给（`local` 与
   `http://127.0.0.1:8001` 互相标注），页面上印的则永远是**地址**（§4）——
   值可以短、可以翻，但"这一页到底读了谁"不许被短名字藏起来。

## 11. 2026-09-19（第二轮）：参数 / 交互 / 双语里修掉的真 bug

和 §9 一样，这一节不是设计，是记录：每一条都是"点了没反应"或"页面说了句假话"的亲戚。
下面写的都是**现在**的行为，每条都验过。

| # | 症状 | 现在 |
|---|---|---|
| 1 | `?days=1000000000000` 让页面 **HTTP 500** | `Filter.from_query` 把它夹到 `MAX_DAYS`（`lib/gui.py:428`），页面 **200** 并且写明 `last=3650 (asked 1000000000000, capped)`。第二层守卫在 `_iso_ago`（`lib/kbuild.py:286`）：夹不住的那种调用方拿到的是 `ConfigError` 而不是 `OSError`——而 `OSError` 不是 `KciError`，处理器只会把它变成 500 |
| 2 | 动作表单里的 `days` / `limit` **完全不夹**：`table.py index --limit -1` 会从尾部切掉最新的 build | `Gui.command()` 用和页面**同一个** `_clamp()`（`lib/gui.py:1168`）：`--limit -1` → `1`，`--days 99999999` → `3650`，`--limit 99999` → `1000`。第二层在 `Builds.fetch()`（`lib/build.py:672`）：`limit < 1` **直接拒绝**，因为它知道自己会拿 `[:-n]` 去切最新的几个 |
| 3 | `<select>` 里的当前值不在选项里时被**静默改写**：`?limit=37` 再点一次 apply 就变成 50 | 不在选项里的值**追加成一个 `(current)` 选项**并选中（`lib/gui.py:2990`）。今天 `?limit=37&days=365` 点多少次都还是 37；数字框本来就是自由输入（`_num`），没有这个毛病 |
| 4 | `?missing=kernel,modules` 因为没有匹配的 `<option>` 被**整条丢掉** | 同上：多选的值合成一个 `kernel,modules` 选项，标着 `(current)`（`_select` 的 docstring 里就写着这个例子）。`missing` / `has` 本来就是逗号分隔的一条 URL 值 |
| 5 | `self.note` 在 `ThreadingHTTPServer` 下面**串味**：A 请求的 API 失败印到 B 请求的页面上 | 提示跟着**这一次读**走（`Remote.note` / `job_node_rows()` 的第二个返回值），`Gui` 上没有 `note` 这个属性（注释在 `lib/gui.py:710`）。同一个脚本跑两遍（4 个线程、240 次渲染，两个线程的 API 一直失败）：这一轮之前的 `lib/gui.py` **38 页串味**，现在 **0** |
| 6 | API 完全不应答时，页面照样说"API 答复里没有这个 build" | 两句话分开了：`the API did not answer this query (…)` 与 `the API answered, and the answer is empty for this query (…)`（`_empty_remote`，`lib/gui.py:3256`；`_empty_queue`、`_pull_form` 同理）。`/local` 的远端列也多了第三种说法：`the API did not answer this query: nothing is known about the remote side` |
| 7 | `/analysis` 上那个 `scope` 控件**是死的**（`?scope=10` 什么也不做） | 控件换成 `limit`，也就是 `trend()` 真正读的那个字段。`?limit=10` 真的只画 10 个点；`?scope=10` 谁也不读它（`/api/analysis/trend` 仍然收 `scope`，那是接口自己的契约） |
| 8 | `/jobs` 的 `results` 表单读 `selected`，而那个框发的是 `build` —— 框是死的，账本永远打全套 | `command()` 读 `build`（`_first(form, "build")`，`lib/gui.py:1205`），勾选行仍然可用 |
| 9 | `/pull?origin=local` / `origin=both` 恒为 **0 候选** | 筛选改在**真实的本地拷贝**上跑（`remote_rows(check, held)`，`lib/gui.py:920`）。旧版把 `local=None` 读成"我们什么都没有"，于是 `origin=local` 一行都不匹配 —— 而 `/local` 上明明列着 4 份。今天 `?origin=local` 是 `2 candidate(s) among them` |
| 10 | `_token()` 用 `str.isalnum()`，那是 Unicode 感知的：`?tree=树` 会**原样进命令行** | 字符类写死成 `[A-Za-z0-9._+-]{1,64}`（`TOKEN`，`lib/gui.py:285`）。`_token('树')` 是 `''`，`'../../etc'` 也是 `''`，`riscv` 与真 build id 原样通过 |
| 11 | 页头不说是哪家 API，于是"远端只有 2 行"看着像 API 坏了 | 页头印 `api: <code>http://127.0.0.1:8001</code> (switch it with <code>python3 gui.py --api-url …</code> or <code>$KCI_API_URL</code>)`。那次困惑的一半来自：页面问的是本地那个只有 2 个 kbuild 节点的 seed 库 |

| 12 | 双语接线后，两句拒绝（`?tree=<不是名字>`、动作里乱填的 `test` / `mode` / …）从 404 / 409 变成 **500**：占位符叫 `{key}`，撞上 `t(lang, key, **fmt)` 的参数名 → `TypeError: t() got multiple values for argument 'key'` | `t()` 的 `lang` / `key` 改成**位置专用**（`def t(lang, key, /, **fmt)`，`lib/i18n.py:802`），占位符可以继续叫 `{key}`。实测：`?tree=%E6%A0%91` → **404** + `tree='树' 不是名字；请用选择框`，`POST /api/actions/run -d test=bogus` → **409**。这类回归靠"读代码"看不出来，所以 `/tmp/accept.sh` 现在把它当成一项验收：每条拒绝都要答对码，且正文里不许出现 `TypeError` / `Traceback` |
| 13 | **页面启动时把两张表读一次就冻住**：卡片/账本由按钮起的子进程写，页面却再也不读盘 → "我跑了 boot，页面还是显示没跑过"，而 `var/results/<id>/boot.json` 明明在 | `_state()` 改成**每个请求现读**（`threading.local()` 请求级缓存，由 `handle_one_request` 在每个请求开头 `.clear()` —— `protocol_version="HTTP/1.1"`，一条 keep-alive 连接上同一线程连着处理多个请求，所以不能只靠线程隔离）。入口 `gui.py` 不再传 `builds=`/`records=`（那两个参数留作测试覆盖）。实测：另一个进程写一条记录 → 页面计数 0 → 1；300 张卡时一份数据只解析 **1 次**（不缓存是 207 次） |
| 14 | **`table.py run` 一点就崩**：`table.py` 的 run 分支把本地表里的 `Build` 又塞进 `Build()` 包了一层（改前那一行），`self.kbuild` 于是是个 `Build`，第一次取构件就 `AttributeError: 'Build' object has no attribute 'artifacts'` | 与上面 `pull` 分支同一句话（"the table holds cards"）：现在是 `made = build.make()`（`table.py:101`）。端到端复验：`table.py run --build 6aa36897… --test boot` → 下载构件 → 起 tuxrun → **`pass boot … guest booted`，退出码 0**。另外三个 `Build(kbuild)` 调用点（`runday.py`、`run_latest.py`、`lib/poller.py`）传的是**从 API 取回的 `Kbuild`**，包一层是对的，未动 |
| 15 | **子进程回收依赖页面轮询** → 在 A 页面起的活动、在 B 页面看，永远显示 `running`（B 不是父进程，只看到一个僵尸进程），而 `running` 的写者会让**写者闸门一直关着** | `Run.start()` 起一个**本进程的**守护线程等子进程并结算（`_LIVE` 表 + `reap()` 读它，不与 `waitpid` 抢）。实测：无人轮询时成功的一次 2.0s 内结算成 `done / 0`；`cancel()` 仍给出 `cancelled / -15`；写者闸门随之开合 |
| 16 | **`/worker` 在生产视图上永久转圈**：`Kjobs.getjob` 把 `limit` 当**页大小**塞进 filter，`Api.nodes` 便一路翻到 `total` —— 生产上 `kind=job` 是 **478 万**个节点 | `Api.nodes(..., newest=False)` 新增"取**队首** `limit` 条"的语义（默认仍取尾部 = 最新，给 kbuild 用），`Kjobs.getjob` 改用它并留下 `self.total` 供页面引用。实测：本地 **0.0s / 2 个请求**，生产 **12–18s / 2 个请求**（计数 + 队首页） |
| 17 | **`/analysis` 在生产上 33s 且算不出结果**：`Drift.between` 为两个 id 各做一次"按 id 找 build"的扫描，而那两个 id 已经滑出扫描范围 → 块里只有 `cannot compare` | 两层：`Kbuilds.get()` 的兜底扫描加上限（`SCAN = 1000`，错误信息写明扫了多远）；页面把**这一页本来就已经读到的**构建交给 `Drift.between(..., catalogue=…)`。实测：生产 **33.3s 无结果 → 11.5s 且 `added 3 / removed 0 / changed 1`**；本地视图上两边逐字段相同 |
| 18 | **生产视图上"登记这一批"登记的是本地库**：`table.py` 本来就认 `--api-url`（`config.run_flags` 加的），但页面给 `index` 拼命令时没带 → 回落到 `$KCI_API_URL`/LOCAL，于是"卡片永远加不进去" | `Gui.command()` 的 `index` 分支补上 `--api-url <当前基址>`（§3 表同步；`pull`/`results` 仍然不带，因为它们一个 API 都不问）。实测（隔离目录）：`table.py index --api-url https://api.kernelci.org --days 1 --limit 5` → 卡片 **3 → 7** |
| 19 | 回归：`gui.py` 的 `--port` 默认值被前几轮改动写成了 **`gui.ROWS`（=25）** —— 不传 `--port` 时会去 bind 25 | 改回 `gui.PORT`（**8079**），与入口 docstring 一致 |

---

## 12. 2026-09-20：按你的逐条意见重做一遍

一次完整的返工，起因是你对页面的书面意见。**逐条清单在
[`docs/gui-rework/REQUIREMENTS.md`](../docs/gui-rework/REQUIREMENTS.md)**，
每一项改动的证据在 [`docs/gui-rework/CHANGELOG.md`](../docs/gui-rework/CHANGELOG.md)，
研究过程在 `docs/gui-rework/01`–`09`。这一节只写**契约变了什么**。

### 12.1 最重要的一条：所有按钮都在发服务器读不懂的东西

页面的脚本用 `fetch(..., {body: new FormData(form)})` 提交，那会序列化成
`multipart/form-data`；而服务端用 `urllib.parse.parse_qs` 读 body —— 那只认
`application/x-www-form-urlencoded`。**它不报错，它返回空。** 于是：

* `_ticks()` 永远是空的，`run` / `pull` 无论勾几个都答「跑至少要勾一个 build」；
* 更糟的是**不需要勾选的动作照样跑**，但跑的是**默认值**而不是筛选栏上的值：
  `index` 实际执行 `--days 0 --limit 25`（服务器默认），**一次 10 个按钮里有 9 个
  跑的是另一条命令或者被拒**。

修法是两半：`_form_body()` 现在**两种编码都读**（`multipart/form-data` 用
`_multipart()` 解析，重复的 `selected` 按顺序全部保留），读不懂的 body **大声拒绝**
而不是变成一张空表单；脚本改成发 `URLSearchParams`。两半都要，因为**已经打开的标签页
里是旧脚本** —— 只改客户端只能修好刷新之后的页面。

端到端复验（浏览器真发的那条 multipart body）：

```
$ curl -X POST .../api/actions/index -F tree=riscv -F days=7 -F limit=3
argv: … table.py index --api-url https://api.kernelci.org --days 7 --limit 3 --tree riscv
```

改动前同一条 POST 得到的是 `--days 0 --limit 25` 且**退出码 0** —— 一条跑成功、
报了成功、回答的是另一个问题的命令。

### 12.2 页面慢的真正原因

不是渲染。实测**整个渲染过程占 29 秒里 0.03 秒（0.1%）**。慢是因为每次加载都从
一个「返回空也要 1.2–3.7 秒、带宽 20–35 KB/s」的 API 重新读 175–680 KB。三条措施：

* **同一个请求内不重复问**（`api.begin_request` 的 memo）：`/worker` 4 次调用 / 680 KB
  → **2 次 / 340 KB**。
* **API 读取的 5 秒 TTL + `?ttl=` + `?fresh=1`**（现在默认 20 秒，见 §12.5）；
  本地的四样东西（`builds.json`、`var/results`、`var/runs`、`var/downloads`）
  **从来不进这个缓存** —— 这就是「刷新要真的重读文件」。
* **`rows` 现在真的决定读多少行**（`ROW_BYTES = 3502`，页面上印成
  `170 KB · 50 行 · 1782 API · 1732 在上限之外`）。以前 `_known_builds` 写死 200 行：
  `/analysis` 无论你选 50 还是 200 都读 687 565 B。

`API_TIMEOUT` 现在是真的墙钟（按 32 KB 分块流式读、块间看表）：`timeout=5` 以前
**26.55 秒**才返回，现在 **6.20 秒**就报错。整页预算是 `API_BUDGET = 45`：10 秒在这家
API 上意味着**空表**（`/nodes` 返回空也要 1.2–3.7 秒），交白卷比慢更糟。

**最慢的页 61.278 s → 3.379 s**；热加载 `/analysis` 0.02 s、`/` 0.01 s、`/runs` 0.007 s。

### 12.3 五个路由（§2 已改）

`/remote`、`/local`、`/pull` 变 **302**，合并页 `/` 的每一行有三列相邻的事实：
**card | bytes | act**，三列各自可以为 `-`。这条设计正是为了让
`拉了运行了但还是显示卡片没拉取` 一眼可见 —— 而那个 bug 的根因在**写入端**：
`Build.make()` 写字节和 `provenance.json`，但**只有 `table.py index` 写卡片**，
所以 `runday`、`run_latest`（`fetch`/`provision` 按钮）、worker、每个 job 自己拉的
build 都没有卡片。现在 `Builds.remember()` 让**一次拉取也是一次登记**。

### 12.4 筛选栏：能选、能填，而且说的是真话

* **生效中的每一个轴都印出来，包括默认值。** 以前 `?api=production` 与「没有 `api` 键」
  **逐字节相同** —— 因为 chips 只印「非默认」的值，而服务器就是在 production 上启动的，
  于是 `production` 恰好是默认值。这不是 production 的特例，是把服务器换到 `local`
  启动症状就镜像过来。现在是 `_axes`：`api https://api.kernelci.org · tree riscv · 窗口 7 · 行数 50`。
* **滑条 + 手填**（`_rail`）：轨道是脚本生成的、**不带 `name`**（不可能重复提交），
  JavaScript 关掉就退化成今天那个输入框。回归测试 `tools/test_dom.js` 驱动**发布的**
  脚本，17/17 —— 其中一条抓到一个真 bug：规范里的合成 `change` 重派发会让它在松手时
  **提交两次**（原生 range 的 `change` 会冒泡到筛选栏自己的监听）。
* **`branch` 按树给**：`?tree=riscv` 现在只给 `["fixes", "for-next"]`（API 上实测答
  38 / 42 的那两个），而不是跨树的 12 个名字。
* **词表按实测给，并且每一个都追到线上**：`arch` 走 `data.arch=riscv`、`state=done`
  走 `state=done`、`result=pass` 走 `result=pass`。不缩小的那几个（`arch` 1771/1782）
  在控件旁印出可选值个数，读者自己看得出来。
* **问句印的是真的键**：`kind=kbuild name=kbuild-gcc-14-riscv data.kernel_revision.tree=riscv`
  —— 以前印 `job=` / `tree=`，而线上发的是 `name=` / `data.kernel_revision.tree`。
  你把这一行当作「这一页到底读了什么」的答案，所以那里不能是意译。

### 12.5 动作与运行

* **argv 预览只描述，不拒绝**：`/jobs` 以前在没勾任何东西时就一直印着
  `nothing to run: …`。
* **日志**（`某些日志点不开`）三个原因全修：链接是真的 `href="/api/runs/<id>/log"`
  （**24 个真链接，0 个 `href="#" onclick`**，JavaScript 关掉也能打开）；`showLog`
  **每次点击**都重置 `logOffset`（以前只在 id 变化时重置，所以再点一次会从文件末尾读，
  永远停在 `loading…`）；补上 `scrollIntoView`（日志框画在 50 行表格下面，
  以前点了「链接有效但读者看不到任何变化」）。
* **`table.py run` 现在跳过账本里已有的**（`--redo` 回到旧行为）。页面以前那句
  「这条命令连账本里已经有的也会跑」在改动之后**变成了假话**，已经删掉。
* **活动按 kind 分组**：`/runs` 50 行里 37 行是 `table.py index` 的记账。折叠是
  **页面筛选状态**（`kind` 默认「除了 table 之外的全部」），不是渲染技巧 ——
  否则 2 秒轮询会把它撤销。分组标题写在**某组第一行的第一个单元格里**，不是独立的
  `<tr>`：独立标题行会让 `活动 64` 这个数字**无法被链接复现**（70 个 `<tr>`）。

### 12.6 侧栏、转圈、提示

服务端渲染的 `<details class="live" id="live" open>`（有活动在跑时默认展开），
所以**关掉 JavaScript 它就是 `curl` 看到的那样**：真 `href` 的 log、真 POST 的 cancel、
`@keyframes spin` 的圈（`aria-hidden`，`prefers-reduced-motion` 下变成一个缺一角的环
而不是一个不动的空环）。完成提示是 `#notice`（`role="status"`），键是 `id@started`，
**刷新不会重播旧消息** —— 为此 `/api/state` 新增 `started` / `ended` 两个字段，
提示的第二条规则是 `ended > data-drawn`。`tools/test_notice.js` 在两种语言下
驱动**发布的**脚本，各 11/11。

### 12.7 分析页：选择决定内容，排序决定比较

按你说的做的：`sort` 是 URL 上的一个字段（所以链接和 chips 免费带上它）；一个列表按
那个顺序排，每行带**对前一行和后一行**的 `±`（两端如实写成「本序第一行」/「本序最后一行」，
不能比的**留在原位**并给出引擎自己的理由）；下面一个同序的横向图（`class="bar w0..w20"`，
数字照印，无内联样式、无 JavaScript）；选择框换成两行一行的列表加两个 `list="builds"` 输入
（原来两个 191 项的 `<select>` 是 25 KB 的 16 位十六进制、**没有任何 `title=`**，
全文 id 拿不回来）；**默认对比对**改成「最新 build vs 另一个内核系列的最新 build」，
标题上带漂移徽章 —— 默认视图的 `CONFIG_` 名字从 **1 个变成 2 338 个**。

`truncated kept copy` 那类错误也修了：`.config` 缓存按 URL 的 sha256 存，旁边一个
sidecar 记着字节数和 sha256，**对不上就拒绝**而不是拿去比 —— 一份截断到 5 000 字节的
config 仍然能解析出 166 个选项，会给出 `+5426 −8 ~1` 而不是 `+618 −616 ~99`，
零 HTTP 且没有任何迹象。

### 12.8 文案

`不要这种垃圾文字注释`：**两种语言**下 14 条禁用短语全部不存在（W1 检查会从
`lib/i18n.py` 目录里**推导出中文对照**，所以「英文删了、中文留着」也过不了）。
`build(s)` / `activit(ies)` / `cop(y|ies)` 这类机器复数没了；`新增 (616 删除 (618))`
查下来是**误读**（括号是配平的，那是两个相邻的表格单元格），真正的毛病是计数印了两遍、
零变更的类别还渲染一个空 `<ul>` —— 现在头部没有 `({n})`，零变更是 `nothing added` 一句话。

### 12.9 这一版凭什么说自己对

`docs/gui-rework/tools/accept.py`：**16/16，打的是你自己的 `http://127.0.0.1:8082`**。
每一项对应你的一条意见，并且每项都印出判定它的证据（不是"通过"两个字）。另外
`./run.sh verify` → all gates passed、`ruff check .`、`lib/i18n.py --check`，以及六个
回归测试，其中两个驱动**发布的** JavaScript（17/17 与 11/11）。

**没有做，或者知道只做了一半**（都记在 `CHANGELOG.md` 的 Still open 一节）：
`lib/run.py::_settle(None)` 把「没收到退出码」报成 `failed`（侧栏的做法是印
「没看到退出码」，底层的词表问题没解决）；`/analysis` 现在 390 KB（完整漂移表整份在
HTML 里，藏在 `<details>` 后面，无 gzip）；`kbuild` 到底在哪里被当成可选项，
仍然是个**待你回答的问题**（所有页面的 `<option>` / `<datalist>` 都倒出来过，
没有一个提供它）。
