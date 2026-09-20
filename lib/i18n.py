# SPDX-License-Identifier: LGPL-2.1-or-later
"""The console's own words, in English and Chinese: one catalogue, one lookup.

`lib/gui.py` is the only reader.  Every sentence a page prints is looked up here
by a dot-named key -- `t(lang, "remote.asked")` -- and **the English column is
today's gui.py wording, word for word**, so wiring a page changes which language
it speaks and never what it says.  The Chinese column is written for an operator:
short sentences, and the one vocabulary `src/GUI.md` already fixed (远端 / 本地 /
对应 / 拉取 / 账本 / 判决 / 缺口 / 回归 / 登记 / 轮转).  An English mode renders
byte for byte what the page renders today.

Three things the caller has to know:

* **Nothing here is escaped, and nothing here escapes.**  A value carries the
  HTML the English carries (`&mdash;`, `&ldquo;…&rdquo;`, `<code>Build.make()</code>`)
  and is put into the page as written.  Every *value* interpolated into it -- a
  build id, a path, a query -- is still escaped by the caller with
  `html.escape()` and passed bare: `t(lang, "remote.asked", query=html.escape(q))`.
  Markup that wraps a whole string (`<h2>`, `<span>`, `<p class="query">`) stays
  in gui.py; a sentence that contains a link takes it as `{link}`.
* **Placeholders are `str.format`'s**: `t(lang, "count.rows", n=3)`.  No gettext,
  no plural rule -- English keeps its own `row(s)` spelling, Chinese counts
  without one.  A missing or malformed placeholder never raises: the row comes
  back as it stands, because a page that dies is worse than a page with `{n}` in
  it.  An unknown key comes back as the key itself, for the same reason.
* **What is not language is not translated.**  Command names, flags, paths,
  `build_id`, and the vocabulary the record itself uses (`tree`, `pulled`, `pass`,
  `resident`) stay as they are.  The code-form words that a page does show live
  in `word.*`, with the same string in both columns, so a mechanical replacement
  has somewhere to point and `--check` can tell "same on purpose" from "not
  translated".

Keys are named after where the words are read:

    nav.*        the eight pages, as navigation and as the page's <h1>
    page.*       one page's <h2> heading and its <span> sub-line
    filter.*     a select box's label
    col.*        a table's column headers
    label.*      a word used in both roles (a label somewhere, a header elsewhere)
    word.*       code-form words: identical in both columns, on purpose
    btn.* link.* a button's and a link's own text
    state.*      the words a fact is put in ("yes", "ready", "card only")
    state_text.* the sentences `Local.state_text()` builds
    evidence.*   the six meanings of the 「本地证据」 column (src/GUI.md §1.4)
    count.* empty.* header.* js.*  phrases a page or the poll script assembles
    error.*      what a refused request answers on the wire (409/404)

The command line is the only way in without a page:

    python3 lib/i18n.py --check lib/gui.py   # 缺失 / 未使用 / zh 与 en 相同
    python3 lib/i18n.py --map lib/gui.py     # key -> 它在 gui.py 的第几行

`--check` exits 1 when a key the file *uses* is not in the catalogue, or when an
entry has no `zh` at all.  An entry whose `zh` equals its `en` is listed
separately and is not a failure -- that is what `word.*` is for.

接口形状（C++，只有声明）：include/kci/view.hpp §20 页面文案（中英两份）。
"""

# No `import re`: this file has to answer `python3 lib/i18n.py --check …`, which
# puts `lib/` itself on `sys.path`, where `re` is this package's ledger reader
# (`lib/re.py`, imported by gui.py as `re_mod`) and not the stdlib module.  The
# handful of scans below are spelled out by hand instead.
import sys

# The two columns, in the order a request negotiates them.
LANGS = ("en", "zh")
DEFAULT_LANG = "en"

# Every sentence a page can say.  `en` is the wording gui.py uses today, verbatim
# except that a computed part became a `{placeholder}`; `zh` is the same fact in
# an operator's Chinese.  Keys are grouped the way gui.py prints them, so a page
# and its words can be read side by side.
CATALOGUE: dict[str, dict[str, str]] = {

    # --- the shell: navigation, counts, banners (gui.py _PAGE / _shell) -----

    "nav.builds": {"en": "builds", "zh": "构建"},
    "nav.jobs": {"en": "jobs", "zh": "测试"},
    "nav.runs": {"en": "runs", "zh": "运行"},
    "nav.worker": {"en": "worker", "zh": "轮转"},
    "nav.analysis": {"en": "analysis", "zh": "分析"},
    # --- the numbers strip: every number a link, every number read uncapped ----

    # The counts line was three sentences and three absolute paths.  Its replacement is
    # seven chips, and a chip is a noun plus a number: `cards 27`.  The noun is *not*
    # pluralised from the number, because no rule in this catalogue could agree an
    # English noun with an arbitrary count (`05-i18n-prose.md` §A.4), and a reader gets
    # the same information from a word that never changes shape.
    # --- / : the merged builds page ---------------------------------------

    # The h2 is the one place this page names what its rows *are*, because the table
    # is a union of two sources and a reader who does not know that will read a
    # card-less row as a bug.  The sub-line says which two, in one clause.
    "page.builds.title": {"en": "builds", "zh": "构建"},
    # The view axis, as the three numbers the h2's sub-line carries.  They replaced
    # the sentence that used to sit here ("the API's window and this disk, one row per
    # build id"), which was a description of the section rather than of its contents.
    "view.cards": {"en": "cards {n}", "zh": "卡片 {n}"},
    "view.window": {"en": "API window {n}", "zh": "API 窗口 {n}"},
    "view.union": {"en": "both {n}", "zh": "并集 {n}"},
    "page.builds.ledger_title": {"en": "the ledger's own numbers", "zh": "账本自己的数"},
    "page.builds.acts_title": {"en": "what has been pulled", "zh": "拉过什么"},
    "page.builds.acts_sub": {"en": "the acts Build.make() recorded, newest first",
                             "zh": "Build.make() 记下的 act，新的在前"},
    "page.builds.image_title": {"en": "a local origin", "zh": "本地自己产的"},
    "page.builds.image_sub": {"en": "how a card with no remote counterpart is made",
                              "zh": "没有远端对应物的卡片是怎么来的"},

    "counts.cards": {"en": "cards", "zh": "卡片"},
    "counts.here": {"en": "here", "zh": "在本地"},
    "counts.bytes": {"en": "with bytes", "zh": "有字节"},
    "counts.acts": {"en": "pull acts", "zh": "拉取记录"},
    "counts.records": {"en": "records", "zh": "账本记录"},
    "counts.gap": {"en": "in the gap", "zh": "缺口"},
    "counts.activities": {"en": "activities", "zh": "活动"},
    "counts.shown": {"en": "shown", "zh": "显示"},
    # The one label an act cell needs inside a row: `acts 2` and not `2 act(s)`.
    "counts.act_n": {"en": "acts {n}", "zh": "act {n}"},
    # A heading's sub-line is data: this is how many acts the section below holds, and
    # the file they are written in is the heading's tooltip.
    "count.acts_in_record": {"en": "{n} acts", "zh": "{n} 条 act"},
    # What the pull bar owes the reader: how many of these rows that command cannot
    # take (it reads the local table, so a directory with no card is not tickable).
    "counts.without_card": {"en": "{n} not tickable", "zh": "{n} 行勾不了"},
    # The paths the counts line printed are these two tooltips now: a path is a fact
    # about a number, and a fact about a number is a `title=`.
    "counts.title_bytes": {"en": "an artifact is on disk here (Build.present())",
                           "zh": "磁盘上确实有构件（Build.present()）"},
    "counts.title_acts": {"en": "every act Build.make() recorded, in {provenance}",
                          "zh": "Build.make() 记下的每一条 act，在 {provenance} 里"},

    "header.api_down": {"en": "the API did not answer: {note}", "zh": "API 没有应答：{note}"},
    "header.busy": {
        "en": "writing right now: {writers} &mdash; another writer is refused until it ends",
        "zh": "正在写：{writers} &mdash; 它结束之前，第二个写者会被拒"},
    "header.tagline": {"en": "every button below runs a command you could type yourself.",
                       "zh": "下面每个按钮跑的都是你自己能打的那条命令。"},

    # --- / : three things, the record, the ledger, what is running ----------

    "label.records_in_ledger": {"en": "records in the ledger", "zh": "账本里的记录"},
    "label.verdicts": {"en": "verdicts", "zh": "判决"},
    "label.gap": {"en": "the gap: (build, test) with no record",
                  "zh": "缺口：还没有记录的 (build, test)"},
    "label.regressions": {"en": "regressions", "zh": "回归"},

    # --- /remote : what the API has ----------------------------------------

    "remote.asked": {"en": "asked the API", "zh": "问过 API"},
    # A label and a number, never `row(s)`: this catalogue has no plural rule, and
    # `行` needs none - the English noun is `rows` because a queue this page prints
    # is never exactly one row in practice, and the number is beside it either way.
    "remote.rows": {"en": "&mdash; rows {n}", "zh": "&mdash; {n} 行"},
    # Which API was asked opens the question itself, and what is printed is the
    # *address*, never the short name a URL carries (`api=production`): the page
    # says what it read, so the name in the address bar hides nothing.
    "remote.query_from": {"en": "{api}: {query}", "zh": "{api}：{query}"},
    # The query is printed as code (`kind=kbuild … last 30 days`), so its window
    # is here only for a deployment that wants the question itself in Chinese.
    "remote.query_window": {"en": "last {days} days", "zh": "最近 {days} 天"},
    "remote.index_hint": {"en": "cards only: it downloads nothing", "zh": "只登记卡片：什么都不下载"},
    "filter.rows": {"en": "rows", "zh": "行数"},
    "col.remote_says": {"en": "remote says", "zh": "远端说"},
    "col.here": {"en": "here", "zh": "本地"},
    # The two facts an empty table may mean, kept apart (gui.py `_empty_remote` /
    # `_empty_queue`): "did not answer" is not "answered with nothing".
    "empty.remote_no_answer": {
        "en": "<b>the API did not answer this query</b> ({note}), so this table is empty "
              "because nothing arrived &mdash; not because the API has no such build",
        "zh": "<b>API 没有应答这次查询</b>（{note}），所以这张表是空的，因为什么都没回来 "
              "&mdash; 不是 API 没有这个 build"},
    "empty.remote_empty": {
        "en": "<b>the API answered, and the answer is empty</b> for this query ({query}) "
              "&mdash; an empty answer, not a missing one",
        "zh": "<b>API 答了，答案是空的</b>，这次查询是（{query}） &mdash; 空答案，不是没有"},

    # --- /local : what we hold ---------------------------------------------

    "col.card": {"en": "card", "zh": "卡片"},
    "col.act": {"en": "act", "zh": "act"},
    "col.api_says": {"en": "api says", "zh": "API 说"},
    "col.tick": {"en": "tick", "zh": "勾选"},
    "col.registered": {"en": "registered", "zh": "登记"},
    "filter.evidence": {"en": "the record says", "zh": "记录怎么说"},
    "filter.origin": {"en": "origin", "zh": "来源"},
    "filter.missing": {"en": "missing", "zh": "缺什么"},
    "col.bytes_on_disk": {"en": "bytes on disk", "zh": "磁盘上的字节"},
    "col.correspondence": {"en": "correspondence (the recorded facts)", "zh": "对应（记录下来的事实）"},
    "btn.publish_image": {"en": "publish var/serve/Image as a build",
                          "zh": "把 var/serve/Image 发布成一个 build"},
    "local.image_state": {"en": "{path} is there", "zh": "{path} 在"},
    "local.image_state_missing": {"en": "{path} is not there", "zh": "{path} 不在"},
    # The sentence keeps the one fact that is not on the screen - how much the filter
    # hid - as the number in it, and drops the recap of which values are in force: the
    # chips above the table are that recap, and they are links.
    "empty.filter_hides": {
        "en": "<b>nothing matches this filter</b> - {n} local copies are hidden by it. "
              "{link}",
        "zh": "<b>没有一行过得了这个筛选</b> - 它挡住了本地 {n} 份拷贝。{link}"},
    "empty.nothing_local": {
        "en": "nothing local: no cards in the table and nothing under {downloads}",
        "zh": "本地什么都没有：表里没有卡片，{downloads} 下也没有东西"},
    "link.clear_filter": {"en": "clear the filter", "zh": "清掉筛选"},

    # --- /local/<build_id> : one copy, and what the record says ------------

    "page.correspondence.card_title": {"en": "the card", "zh": "卡片"},
    "page.correspondence.card_sub": {"en": "what we registered, and which node it came from",
                                     "zh": "我们登记了什么，它来自哪个 node"},
    "page.correspondence.bytes_title": {"en": "the bytes", "zh": "字节"},
    "page.correspondence.bytes_sub": {"en": "Build.present(): what is on disk, and how big",
                                      "zh": "Build.present()：磁盘上有什么、有多大"},
    "page.correspondence.record_title": {"en": "the pull record", "zh": "拉取记录"},
    "page.correspondence.remote_title": {"en": "the remote row", "zh": "远端那一行"},
    # The record table's own heading: `Records.for_build()` is the code that produced it,
    # so it is the heading's tooltip (`_h2(hint=)`), and the title is what the table holds.
    "page.correspondence.acts_title": {"en": "what this record says", "zh": "这条记录里有什么"},
    # A drill-down heading: the words `col.detail_title` was reserved for, printed on the
    # detail table's own heading so the reader knows the rows are the record's own text.
    "col.detail_title": {"en": "the record's own words, printed as stored",
                         "zh": "记录自己写的字，原样摆出来"},
    "page.correspondence.remote_sub": {"en": "from {query}", "zh": "来自 {query}"},
    "page.correspondence.ledger_title": {"en": "the ledger", "zh": "账本"},
    "page.correspondence.activities_title": {"en": "activities", "zh": "活动"},
    "page.correspondence.activities_sub": {
        "en": "whose command names this build (a text match, said so)",
        "zh": "命令里提到这个 build 的（纯文本匹配，明说）"},
    "col.field": {"en": "field", "zh": "字段"},
    "col.value": {"en": "value", "zh": "值"},
    "label.artifact_urls": {"en": "artifact URLs, as the API spells them",
                            "zh": "构件 URL，按 API 的写法"},
    "state.no_node_id": {"en": "no node id: this card was not registered from an API node",
                         "zh": "没有 node id：这张卡片不是从 API 的 node 登记来的"},
    "state.not_in_table": {"en": "not in the local table", "zh": "不在本地表里"},
    "empty.no_bytes": {"en": "nothing on disk under {path}", "zh": "{path} 下面什么都没有"},
    "empty.no_pull_record": {
        "en": "no pull recorded for this copy: the bytes (if any) got here some other way - "
              "a job preparing one artifact, an older version of this tree, or a copy made "
              "by hand. An equal build id is not evidence of anything.",
        "zh": "这份拷贝没有拉取记录：这些字节（如果有）是别的路子来的 - 跑 job 时铺下来的一个"
              "构件、旧版本的这棵树、或者手工拷的。build id 相等不是证据。"},
    "empty.no_ledger_record": {"en": "no record in the ledger for this build",
                               "zh": "账本里没有这个 build 的记录"},
    "empty.no_activity_match": {"en": "no activity's command names this build",
                                "zh": "没有哪条活动的命令提到这个 build"},
    "btn.pull_recheck": {"en": "pull (re-check the sizes)", "zh": "拉取（重新核对大小）"},
    "btn.run_pending": {"en": "run the pending tests", "zh": "跑还没跑的 test"},
    "correspondence.pull_hint": {"en": "a pull appends an act to the record above",
                                 "zh": "一次拉取会往上边那条记录里追加一条 act"},
    "col.artifact_urls": {"en": "artifact URLs", "zh": "构件 URL"},
    "state.no_remote_counterpart": {"en": "no remote counterpart", "zh": "没有远端对应物"},
    # Added while gui.py was being reworked: the remote line says how much of the
    # answer it is showing, and a clamped URL says what it asked for and did not get.
    "remote.showing": {"en": "showing {shown} of the {kept} this window kept",
                       "zh": "这个窗口留下 {kept} 行，这里显示 {shown} 行"},
    "remote.rows_cap": {"en": "(rows={n})", "zh": "（rows={n}）"},
    # The punctuation of the one line that is a sentence plus a quoted count: an
    # English clause ends with `; ` and a Chinese one with `；`, and a full-width
    # bracket in Chinese does not want the space English puts before it.  The three
    # values are the same keys the page reads everywhere else.
    "remote.line_tail": {"en": "{showing} {cap}",
                         "zh": "{showing}{cap}"},
    "remote.coverage_unknown": {
        "en": "the API did not say how many rows it has for this query",
        "zh": "API 没说这次查询一共有多少行"},
    # Three counts, said separately (`Remote.coverage()` builds the sentence with
    # `+=`, so the keys mirror its pieces - each one is a whole clause in Chinese).
    "remote.coverage_base": {"en": "the API counts {total} for this query",
                             "zh": "API 说这次查询有 {total} 行"},
    "remote.coverage_all": {"en": ", so this cap covers all of them",
                            "zh": "，这个上限把它们全盖住了"},
    "remote.coverage_capped": {
        "en": ", so {n} older rows are outside the {limit}-row cap",
        "zh": "，所以有 {n} 行更旧的落在 {limit} 行上限之外"},
    "remote.coverage_filtered": {
        "en": "; {n} of the rows inside the cap are not in this table - this page's own "
              "filter, not the API",
        "zh": "；上限之内还有 {n} 行没进这张表 - 那是本页自己的筛选干的，不是 API"},
    "remote.query_all": {"en": "no window (all)", "zh": "不限窗口（全部）"},
    "filter.day_all": {"en": "all", "zh": "全部"},
    "filter.capped_rows": {"en": "rows={limit} (asked {asked}, capped)",
                           "zh": "rows={limit}（问的是 {asked}，夹到上限了）"},
    "filter.capped_days": {"en": "last={days} (asked {asked}, capped)",
                           "zh": "last={days}（问的是 {asked}，夹到上限了）"},
    # The API key: `filter.api` is the box's label, `filter.api_hint` says what may
    # be typed in it, and `filter.api_refused` is the clamp note for a value this
    # deployment cannot resolve (it is ignored, and the page says which value).
    "filter.api": {"en": "api", "zh": "api"},
    "filter.api_refused": {
        "en": "api={value} is not a name here and not an http(s) URL; this page reads the base "
              "it started on",
        "zh": "api={value} 不是这里认识的名字，也不是 http(s) 地址；这一页读的是它启动时的基址"},
    # One name per base a URL may carry.  The names are values - they appear in
    # `?api=production` and in a chip - so both columns are the same word, like
    # `word.*`: what a reader needs translated is the sentence around them.
    "api.name.local": {"en": "local", "zh": "local"},
    "api.name.production": {"en": "production", "zh": "production"},
    "api.name.launch": {"en": "launch", "zh": "launch"},
    # The one warning a page owes a reader who moved it off its own API, said in
    # the filter bar's notes and not as a banner of its own.
    # B2/§d.9: the merged page names the API's window as the window, and never as
    # "no remote counterpart" - the row exists, this query's answer just does not
    # reach it, and the cap that stopped it is printed as a number.
    "state.outside_window": {
        "en": "outside window (cap {limit})",
        "zh": "窗口外（上限 {limit}）"},
    "state.outside_window_title": {
        "en": "the API answered {total} rows for this query; this page read the newest "
              "{limit}, and this build is older than that",
        "zh": "API 为这次查询答了 {total} 行，本页读的是最新的 {limit} 行，这个 build 比那更旧"},
    "remote_detail.none": {
        "en": "<b>no remote counterpart</b> in the answer to <code>{query}</code>. The window "
              "is the API's only way of being asked, so this means &ldquo;not in that "
              "answer&rdquo;, not &ldquo;nowhere&rdquo;.",
        "zh": "<b>没有远端对应物</b>：这次查询的答案里没有它（查询是 <code>{query}</code>）。"
              "API 只能按窗口问，所以这句话的意思是&ldquo;那个答案里没有&rdquo;，"
              "不是&ldquo;哪里都没有&rdquo;。"},
    "remote_detail.node_mismatch": {
        "en": "the record names node {record}, the API now names {api} under this build id: "
              "same id, different thing.",
        "zh": "记录里写的是 node {record}，API 现在把这个 build id 算在 node {api} 上："
              "同一个 id，两样东西。"},

    # --- /pull : choose, tick, pull ----------------------------------------

    # Read from *another* API, most of a page's rows are not in this machine's table,
    # so almost nothing is tickable and the page looks broken.  This says why and
    # where to go next; `{link}` is the /remote link that carries this page's window.
    "empty.nothing_pulled": {
        "en": "nothing has been pulled here yet: no {provenance} exists under {downloads}",
        "zh": "这里还什么都没拉过：{downloads} 下没有 {provenance}"},
    # "no candidates are known" and "there are none" are two different answers.
    "pull.no_card_title": {
        "en": "not in the local table: table.py pull --build reads the table, so record this "
              "window first",
        "zh": "不在本地表里：table.py pull --build 读的是这张表，先把这一批登记进去"},
    "pull.not_tickable": {"en": "not tickable", "zh": "勾不了"},
    # No `(s)` anywhere in these two: `accept.py`'s W3 check calls a machine plural
    # invented by the page, and it is right - a reader who sees `artifact(s)` cannot tell
    # whether the page counted one or many.  `n:` selects the form in the caller
    # (`_plural`), which is the one place English's two forms are spelled.
    "pull.row_failed": {"en": "that pull failed - {n} artifact{s} on disk; pull again",
                        "zh": "那次拉取失败了 — 磁盘上有 {n} 个构件，可以重拉"},
    "link.tick_failed": {"en": "re-tick the {n} row{s} whose pull failed",
                         "zh": "重新勾上拉取失败的 {n} 行"},
    # The one press between "I can see which cards are incomplete" and "pull them": it
    # pre-ticks them on the same page with the same filter, so the set and its cost are
    # visible before anything is fetched.
    "link.tick_missing": {"en": "tick the {n} cards missing artifacts",
                          "zh": "把缺构件的 {n} 张卡片都勾上"},
    "link.tick_missing_title": {
        "en": "tick every card on this page that is missing one of the artifacts a test "
              "run needs; then press the button above - you will see the set before it runs",
        "zh": "把这一页上、缺少跑测试所需构件的卡片都勾上；然后按上面那个按钮 —— 跑之前你能先看到这一批是哪些"},
    # One row's own pull, next to its box: the same command as the bar, with one id.
    "pull.one": {"en": "pull", "zh": "拉取"},
    "pull.one_title": {"en": "python3 table.py pull --build {build}",
                       "zh": "python3 table.py pull --build {build}"},
    # A `/jobs` row whose test is not the one in force: no box, and the link that gives
    # it one.  The label is the test's own name - the shortest true word for "click to
    # run this one".
    "jobs.tick_other": {"en": "run {test}", "zh": "跑 {test}"},
    "jobs.tick_other_title": {
        "en": "this row's test is {test}: choose it above and every row of it gets its "
              "own tick box, in the same command",
        "zh": "这一行的 test 是 {test}：在上面选中它，它的每一行都会有各自的勾选框，"
              "而且是同一条命令"},
    "jobs.run_sub": {"en": "one command: the test chosen above, times every ticked build",
                     "zh": "一条命令：上面选的那个 test，乘以每一个勾上的 build"},
    "state.already_whole": {"en": "already whole", "zh": "已经完整"},
    "btn.pull_selected": {"en": "pull the selected", "zh": "拉取勾选的"},
    "pull.pull_hint": {
        "en": "takes only what is missing or not whole, and records an act for every artifact "
              "either way; rows without a card cannot be ticked, because that command reads "
              "the local table",
        "zh": "只拿缺的、或者不完整的，而且不管拿没拿，每个构件都记一条 act；没有卡片的行勾不了，"
              "因为那条命令读的是本地表"},
    "col.on_disk": {"en": "on disk", "zh": "磁盘上"},
    "col.would_fetch": {"en": "would fetch", "zh": "会拉什么"},
    "col.record_now": {"en": "the record now", "zh": "现在的记录"},

    # --- /jobs : the gap, one row per (build, test) -------------------------

    "filter.ran": {"en": "ran", "zh": "跑过"},
    "filter.verdict": {"en": "last verdict", "zh": "最近判决"},
    "col.needs": {"en": "needs", "zh": "需要"},
    "col.ready": {"en": "ready?", "zh": "就绪？"},
    "label.runs": {"en": "runs", "zh": "次数"},
    "label.last": {"en": "last", "zh": "最近"},
    "col.when": {"en": "when", "zh": "时间"},
    "col.in_gap": {"en": "in the gap?", "zh": "在缺口里？"},
    "state.ready": {"en": "ready", "zh": "就绪"},
    "state.already_recorded": {"en": "already recorded", "zh": "已经记过"},
    "empty.no_gap": {
        "en": "nothing to show for this filter: every (build, test) the local table can run "
              "already has a record",
        "zh": "这个筛选下没东西可看：本地表能跑的 (build, test) 都已经有记录了"},
    "page.jobs.run_title": {"en": "run a test over several builds", "zh": "一个 test 跑好几个 build"},
    "page.jobs.run_sub": {"en": "one command, so one test and any builds",
                          "zh": "一条命令，所以是一个 test 加任意几个 build"},
    "btn.run_ticked": {"en": "run the ticked builds", "zh": "跑勾选的那些 build"},
    # The gap's own two numbers, and the code that produced them in the tooltip: the
    # sentence this replaces named `re.todo()` and carried four machine plurals.
    "jobs.gap_title": {
        "en": "<code>re.todo()</code> reports {cards} cards and {records} records; this "
              "page shows the pairs with no record, capped at {limit} rows",
        "zh": "<code>re.todo()</code> 在 {cards} 张卡片和 {records} 条记录上算；"
              "这一页显示还没有记录的 pair，上限 {limit} 行"},
    # The fact this bar's note carries changed when `table.py run` started skipping:
    # it used to *document the bug* the operator reported ("这条命令连账本里已经有的
    # 也会跑"), which is `CHANGELOG.md` §4.  One rule now, two entry points
    # (`runday.py` had `--redo` first), so the note states it instead - and it is a
    # **badge with the explanation in its `title=`** (`05-i18n-prose.md` §B.2's badge
    # vocabulary), not the sentence it was: which of two behaviours a command has is
    # worth three words on screen, and the escape hatch (`--redo`) is worth the
    # tooltip.
    "jobs.run_hint": {
        "en": "skips what the ledger already has; <code>--redo</code> runs it again",
        "zh": "账本里已经有的跳过；要重跑就加 <code>--redo</code>"},
    "jobs.skips_badge": {"en": "skips recorded", "zh": "已记过的跳过"},
    "page.jobs.day_title": {"en": "a day's worth, skipping what the ledger has",
                            "zh": "一整天的量，账本里有的跳过"},
    # The ledger's own rows, printed under the gap they explain: a gap is a
    # difference between the table and the ledger, and the page listed only one side
    # of it - which is why the numbers strip's `records` chip pointed at a page that
    # showed none of the records it counts (`accept.py`'s S6).
    "page.jobs.ledger_title": {"en": "what the ledger has", "zh": "账本里有什么"},
    "counts.title_records": {"en": "{n} records in {dir}", "zh": "{dir} 里 {n} 条记录"},
    "filter.days": {"en": "days", "zh": "天数"},
    "filter.builds": {"en": "builds", "zh": "build 数"},
    "btn.run_day": {"en": "run a day", "zh": "跑一天"},
    "jobs.runday_hint": {"en": "this is the command that skips the pairs the ledger already has",
                         "zh": "跳过账本里已有那些 (build, test) 的，就是这条命令"},
    "page.jobs.elsewhere_title": {"en": "elsewhere", "zh": "别处"},
    "page.jobs.elsewhere_sub": {"en": "the one-shot line, and the ledger in full",
                                "zh": "一次性的那条命令，以及整本账本"},
    "btn.run_newest": {"en": "run the newest build once", "zh": "把最新的 build 跑一次"},
    "btn.ledger_full": {"en": "the ledger, in full", "zh": "整本账本"},
    "jobs.results_hint": {"en": "read-only, no API needed", "zh": "只读，不用 API"},

    # --- /runs : what is happening right now --------------------------------

    "empty.no_activity": {"en": "no activity matches this filter", "zh": "没有活动过得了这个筛选"},
    "col.age": {"en": "age", "zh": "多久了"},
    "col.exit": {"en": "exit", "zh": "退出码"},
    "col.what_run": {"en": "what", "zh": "说明"},
    "word.argv": {"en": "argv", "zh": "argv"},
    "word.id": {"en": "id", "zh": "id"},
    "word.kind": {"en": "kind", "zh": "kind"},
    "word.state": {"en": "state", "zh": "state"},

    # --- /worker : the queue, the worker's file, how to start it ------------

    "filter.name": {"en": "name", "zh": "名字"},
    "col.definition": {"en": "definition", "zh": "有定义"},
    "col.claimed": {"en": "claimed by this worker", "zh": "本 worker 认领过"},
    "empty.queue_no_answer": {
        "en": "<b>the API did not answer this query</b> ({note}), so nothing is known about the "
              "queue &mdash; this is not the same as a queue that is empty",
        "zh": "<b>API 没有应答这次查询</b>（{note}），所以队列的情况根本不知道 "
              "&mdash; 这和队列是空的不是一回事"},
    "empty.queue_empty": {
        "en": "<b>the API answered, and its queue holds nothing for this filter</b> "
              "(state <code>{state}</code>, name <code>{job}</code>) &mdash; an empty answer, "
              "not a missing one",
        "zh": "<b>API 答了，它的队列在这个筛选下什么都没有</b>"
              "（state <code>{state}</code>、name <code>{job}</code>） &mdash; 空答案，不是没有"},
    "page.worker.state_title": {"en": "the worker's own state", "zh": "worker 自己的状态"},
    "page.worker.state_sub": {"en": "poller.py's file, displayed and not interpreted",
                              "zh": "poller.py 的那个文件，只摆出来，不做解释"},
    "col.cursor": {"en": "cursor", "zh": "游标"},
    "col.seen": {"en": "seen", "zh": "已见"},
    "col.pending": {"en": "pending", "zh": "待办"},
    "page.worker.start_title": {"en": "start it", "zh": "起 worker"},
    "page.worker.start_sub": {"en": "the exact commands, with the claim filters as select boxes",
                              "zh": "原样的命令，认领条件全用选择框"},
    "filter.mode": {"en": "mode", "zh": "模式"},
    "btn.start_worker": {"en": "start the worker", "zh": "起 worker"},
    "worker.start_hint": {
        "en": "<code>resident</code> drops <code>--once</code> and keeps polling (cancel it on "
              "the runs page)",
        "zh": "<code>resident</code> 会去掉 <code>--once</code>，一直轮询下去"
              "（在运行页取消它）"},
    "state.any": {"en": "any", "zh": "不限"},
    "state.any_paren": {"en": "(any)", "zh": "（不限）"},

    # --- /analysis : config drift, and the regression timeline --------------

    "page.analysis.drift_title": {"en": "config drift", "zh": "config 漂移"},
    # Reworded by step 6.  It said "two builds, chosen in select boxes; Drift does the
    # reading", which is a sentence about the page (`05-i18n-prose.md` §B.1's first
    # forbidden class: how the page works) and was false the moment the chooser stopped
    # being two select boxes.  What it says now is the one number a reader weighing a
    # reload wants: how many configs this render actually read.
    "page.analysis.drift_sub": {"en": "config reads {n}", "zh": "读 config {n}"},
    "btn.run_drift": {"en": "run drift.py", "zh": "跑 drift.py"},
    "analysis.drift_hint": {
        "en": "one activity; its exit code is the answer (0 no drift, 1 drift)",
        "zh": "一次活动；退出码就是答案（0 没漂移，1 有漂移）"},
    "analysis.choose_two": {"en": "choose two builds above, or tick exactly two rows on {link}.",
                            "zh": "在上面选两个 build，或者在 {link} 上正好勾两行。"},
    # A typed id the page did not read: refused, because looking it up is a 1 000-node
    # scan inside a GET (116.8-137.9 s measured, `06-analysis.md` §D3).
    "analysis.not_read": {
        "en": "{build} is not a build this page read; the API cannot be asked for a build by id",
        "zh": "{build} 不在这一页读到的 build 里；API 没法按 id 查一个 build"},
    "page.analysis.trend_title": {"en": "the regression timeline", "zh": "回归时间轴"},
    # Reworded by step 6 for the same reason: the sort in force and the two counts are
    # the facts, and `one block per run; a pass&rarr;fail point is ringed` was a
    # definition of the page's own chart.
    "page.analysis.trend_sub": {"en": "{test} · {n} runs · {order}",
                                "zh": "{test} · {n} 次 · {order}"},
    "col.timeline": {"en": "timeline", "zh": "时间轴"},
    # Kept although no page prints the bare word any more: the skin pass merged the
    # drift page's two select boxes into that page's one GET form, so its button is
    # `btn.compare_config` below and the tick-two-rows transition on /local is a
    # link.  Reserved for the "compare" *action* (src/GUI.md §2.3) rather than
    # deleted, so a future bar has the word it needs.
    "btn.compare": {"en": "compare", "zh": "比对"},
    "filter.older": {"en": "older", "zh": "旧的"},
    "filter.newer": {"en": "newer", "zh": "新的"},

    # --- step 6: the one list, its sort, its +/-, and its chart -------------
    #
    # The model these words serve is the operator's own: selection decides the content,
    # the order decides what is compared with what, each row carries the `+`/`-` against
    # its neighbours in that order, and a horizontal chart is drawn in the same order.

    "filter.sort": {"en": "sort", "zh": "排序"},
    "filter.point": {"en": "run", "zh": "运行"},
    "sort.date": {"en": "date ↓", "zh": "日期 ↓"},
    # The multi-key vocabulary: one word per key, and the two arrows as units beside it
    # (`tree-branch ↑, date ↓`).  A unit, not a sentence - the label is printed in the
    # axes strip, in a chip and in a heading's sub-line, and none of those is a place for
    # prose.
    "sort.k.date": {"en": "date", "zh": "日期"},
    "sort.k.tree": {"en": "tree", "zh": "树"},
    "sort.k.branch": {"en": "branch", "zh": "分支"},
    "sort.k.tree_branch": {"en": "tree-branch", "zh": "总分支"},
    "sort.k.series": {"en": "series", "zh": "系列"},
    "sort.k.verdict": {"en": "verdict", "zh": "判决"},
    "sort.k.id": {"en": "id", "zh": "id"},
    "sort.dir.asc": {"en": "↑", "zh": "↑"},
    "sort.dir.desc": {"en": "↓", "zh": "↓"},
    "sort.add": {"en": "+{key}", "zh": "+{key}"},
    "sort.drop_title": {"en": "remove this key from the order", "zh": "把这个键从排序里去掉"},
    "sort.flip_title": {"en": "reverse this key's direction", "zh": "把这个键的方向反过来"},
    # The neighbour cell: a comparison that was not made still names its neighbours, and
    # each of those names is the door to the comparison (`/analysis/<id>?vs=<other>`).
    # The regression chart (`_wave_chart`): three lanes over the page's own order.
    "chart.band_title": {"en": "{test} over this order", "zh": "{test} 在这一个排序上"},
    "chart.band_sub": {
        "en": "{n} slots: {ran} with a record, {gap} with none - the horizontal "
              "axis is the order above, not time",
        "zh": "{n} 个位置：{ran} 个有记录，{gap} 个没有 —— 横轴是上面的顺序，不是时间"},
    "chart.lane_verdict": {"en": "verdict", "zh": "判决"},
    "chart.lane_cases": {"en": "cases", "zh": "用例"},
    "chart.lane_at": {"en": "#", "zh": "#"},
    "chart.gap_title": {
        "en": "{build} has no {test} record: the local table has the build and the "
              "ledger has nothing for this test - open /jobs to fill the gap",
        "zh": "{build} 没有 {test} 的记录：本地表里有这个 build，账本里这个 test 什么都没有 —— "
              "打开 /jobs 把这个缺口补上"},
    # The worker page: what the button would claim, before it is pressed.  A count, so a
    # worker start that finds nothing is readable as "nothing to claim" rather than as a
    # failure - which is the difference the operator could not see.
    "worker.would_claim": {"en": "{n} claimable now", "zh": "现在可领取 {n} 个"},
    # Where the available queue actually is, one click per pair: the default pair on this
    # deployment claims nothing, and "nothing to claim" is not a useful thing to leave a
    # reader holding.
    "worker.pairs_lead": {"en": "the queue has work on these", "zh": "队列里有活的组合"},
    "worker.pair": {"en": "{platform} / {runtime}: {n}", "zh": "{platform} / {runtime}：{n} 个"},
    "delta.before": {"en": "before", "zh": "上一行"},
    "delta.after": {"en": "after", "zh": "下一行"},
    "delta.door_title": {"en": "compare with {build} - open the comparison",
                         "zh": "和 {build} 比较 — 打开这次比较"},
    # `/analysis/<id>`: one build, and one comparison.
    "page.one.title": {"en": "one build", "zh": "一个 build"},
    "page.one.sub": {"en": "{build} - its record, and what it compares with",
                     "zh": "{build} —— 它的记录，以及它和谁比"},
    "one.compare_title": {"en": "the comparison", "zh": "这一对比较"},
    "one.vs_choose": {
        "en": "name the other build with {link} - the order and the filter above came "
              "with you, so the neighbours are the ones this row had",
        "zh": "用 {link} 指定另一个 build —— 上面的排序和筛选跟着你过来了，所以邻行还是这一行"
              "原来的那两行"},
    "one.compare_line": {"en": "{older} &rarr; {newer}", "zh": "{older} &rarr; {newer}"},
    "one.all_rows": {"en": "the whole comparison, every changed option",
                     "zh": "完整比较，每一条变化的选项"},
    "one.back": {"en": "back to the list", "zh": "回到列表"},
    "one.neighbours": {"en": "its neighbours in this order", "zh": "在这个排序里的相邻行"},
    "one.no_neighbours": {
        "en": "this build is not in the list this page's filter and order produce, so it "
              "has no neighbours here",
        "zh": "这个 build 不在这页筛选和排序产生的那张表里，所以在这里没有相邻行"},
    "filter.sort_refused": {
        "en": "the order in this URL named {value}, which is not a sort key I know; the keys "
              "I know are {options}",
        "zh": "这个 URL 里的排序写了 {value}，不是我知道的排序键；我知道的是 {options}"},
    "sort.date_asc": {"en": "date ↑", "zh": "日期 ↑"},
    "sort.same_branch": {"en": "same branch first", "zh": "同分支优先"},
    "sort.verdict": {"en": "by verdict", "zh": "按判决"},
    "sort.build": {"en": "by id", "zh": "按 id"},
    "delta.cap": {"en": "delta", "zh": "差异"},
    "delta.none_prev": {"en": "— the first row in this order",
                        "zh": "— 这个排序里的第一行"},
    "delta.none_next": {"en": "— the last row in this order",
                        "zh": "— 这个排序里的最后一行"},
    "delta.cannot": {"en": "cannot compare", "zh": "比不了"},
    "delta.beyond": {"en": "beyond the delta cap ({n})", "zh": "超出差异上限（{n}）"},
    "delta.why_no_config": {
        "en": "no <code>_config</code> artifact, and the storage fallback answered {code}",
        "zh": "没有 <code>_config</code> 产物，本地存储的兜底也答了 {code}"},
    "delta.why_not_found": {"en": "not among the newest {scan} nodes",
                            "zh": "不在最新 {scan} 个节点里"},
    "delta.why_not_config": {"en": "what that URL served is not a kernel config",
                             "zh": "那个地址给的不是 kernel config"},
    "delta.cache_short": {"en": "the kept copy does not match its record",
                          "zh": "留下的那份和它的记录对不上"},
    # Literal arrows and minus signs, not entities: these two are printed inside an
    # **escaped** attribute (`title=`) and in the axes strip, where `t()`'s value is
    # escaped by the caller - `&rarr;` there reaches the reader as `&amp;rarr;`.  The
    # catalogue's own rule still holds for the strings the page inserts raw
    # (`drift.summary`, `drift.no_drift`): those carry their markup.
    "delta.pair_title": {"en": "{older} → {newer}: +{added} −{removed} ~{changed}",
                         "zh": "{older} → {newer}：+{added} −{removed} ~{changed}"},
    "delta.failed_title": {"en": "cases failing, against the neighbouring run",
                           "zh": "和相邻那次比，失败的用例数"},
    "col.delta": {"en": "config delta", "zh": "config 差异"},
    "col.delta_sub": {"en": "vs the row before (↑) and after (↓)",
                      "zh": "对着上一行（↑）和下一行（↓）"},
    "col.n": {"en": "#", "zh": "#"},
    "col.option": {"en": "option", "zh": "选项"},
    "col.cases": {"en": "cases", "zh": "用例"},
    "chart.title": {"en": "the same order, as bars", "zh": "同一个顺序，画成横条"},
    "chart.sub": {"en": "{n} adjacent pairs, {order}", "zh": "{n} 组相邻，{order}"},
    "page.analysis.picks_title": {"en": "the builds this page can name",
                                  "zh": "这一页能点名的 build"},
    "page.analysis.picks_sub": {"en": "{shown} of {pool} rows, {order}",
                                "zh": "{shown}/{pool} 行，{order}"},
    "page.analysis.runs_title": {"en": "the runs of {test}", "zh": "{test} 的每一次运行"},
    "page.analysis.runs_sub": {"en": "{n} runs, cap {cap}", "zh": "{n} 次，上限 {cap}"},
    "page.analysis.point_title": {"en": "the run this cell came from",
                                  "zh": "这一格是哪次运行"},
    "page.analysis.point_sub": {"en": "click a block in a timeline above",
                                "zh": "点上面时间轴里的一格"},
    "mark.records": {"en": "records", "zh": "记录"},
    "empty.no_builds": {"en": "no build matches this filter", "zh": "这个筛选下没有 build"},
    "word.commit": {"en": "commit", "zh": "commit"},
    "word.log": {"en": "log", "zh": "日志"},
    "word.config": {"en": "config", "zh": "config"},

    # --- the three columns of a config comparison ---------------------------

    "drift.cannot_compare": {"en": "cannot compare: {error}", "zh": "比不了：{error}"},
    "drift.no_drift": {
        "en": "no drift between <code>{older}</code> and <code>{newer}</code>: the two configs "
              "hold the same options.",
        "zh": "<code>{older}</code> 和 <code>{newer}</code> 之间没有漂移：两份 config 的选项一样。"},
    "drift.added": {"en": "added", "zh": "新增"},
    "drift.removed": {"en": "removed", "zh": "删除"},
    "drift.changed": {"en": "changed", "zh": "改动"},
    "drift.more": {"en": "... {n} more", "zh": "……还有 {n} 条"},
    # Step 6: the counts are said **once**, on the summary line above, so a category
    # head is a plain word (`drift.added`) and a category with no rows is a phrase
    # instead of a head over an empty list.  The `({n})` in the old heads is also what
    # the operator read as one broken string, `新增 (616 删除 (618))`.
    "drift.nothing": {"en": "nothing {what}", "zh": "{what}：没有"},
    "drift.all_rows": {"en": "all {n} rows", "zh": "全部 {n} 条"},
    "drift.badge": {"en": "+{added} −{removed} ~{changed}",
                    "zh": "+{added} −{removed} ~{changed}"},
    "drift.same_branch": {"en": "same tree/branch", "zh": "同一个 tree/branch"},
    # The engine compares two trees happily (`06-analysis.md` §D1) and the numbers are
    # real either way - this is the label that stops 616/618/99 being read as one
    # kernel moving.
    "drift.cross_tree": {"en": "different tree/branch: two kernels, not one build's drift",
                         "zh": "tree/branch 不同：这是两个内核，不是一个 build 的漂移"},
    "drift.summary": {
        "en": "<code>{older}</code> &rarr; <code>{newer}</code>: {added} added, "
              "{removed} removed, {changed} changed",
        "zh": "<code>{older}</code> &rarr; <code>{newer}</code>：新增 {added}、"
              "删除 {removed}、改动 {changed}"},

    # --- what a fact is called, in one cell ---------------------------------

    "state.pulled_recorded": {"en": "pulled (recorded)", "zh": "pulled（有记录）"},
    "state.bytes_no_pull": {"en": "bytes, no pull record", "zh": "有字节，没有拉取记录"},
    "state.card_only": {"en": "card only", "zh": "只有卡片"},
    "state.made_here": {"en": "made here", "zh": "本地造的"},
    "state.empty": {"en": "empty", "zh": "空的"},
    "state.not_here": {"en": "not here", "zh": "本地没有"},
    "state.not_held_here": {"en": "not held here", "zh": "本地没有"},
    "state.node": {"en": "node {node}", "zh": "node {node}"},
    # The card column's fallback: a copy the local table has never heard of, but
    # whose pull record names the node it came from.  That is a fact about the copy,
    # and it is the fact the old cell threw away while printing "no card in the local
    # table" beside 30 MiB of bytes (`03-structure.md` §A3).
    "state.node_from_act": {"en": "act: node {node}", "zh": "act 里的 node {node}"},
    "state.no_node_id_made_here": {"en": "no node id (made here)", "zh": "没有 node id（本地造的）"},
    "state.no_card_in_table": {"en": "no card in the local table", "zh": "本地表里没有卡片"},
    "state.remote_cell": {"en": "{state}/{result} (node {node})",
                          "zh": "{state}/{result}（node {node}）"},
    "state.remote_cell_mismatch": {"en": "{said} &ne; record node {node}",
                                   "zh": "{said} &ne; 记录 node {node}"},
    "state.already_whole_proven": {
        "en": "already whole: size proven, nothing transferred",
        "zh": "已经完整：大小核对过，没有传输"},
    "state.no_error": {"en": "no error", "zh": "没有错误"},
    "state.no_runs": {"en": "(no runs yet)", "zh": "（还没跑过）"},
    "state.yes": {"en": "yes", "zh": "是"},
    "state.no": {"en": "no", "zh": "否"},
    "label.error_prefix": {"en": "error: {what}", "zh": "错误：{what}"},
    "count.artifacts_act": {"en": "{n} artifacts", "zh": "{n} 个构件"},
    "col.that_pull": {"en": "that pull", "zh": "这次拉取"},
    "col.artifacts": {"en": "artifacts", "zh": "构件"},
    "col.artifact": {"en": "artifact", "zh": "构件"},
    "col.file": {"en": "file", "zh": "文件"},
    "col.bytes": {"en": "bytes", "zh": "字节"},
    "col.transferred": {"en": "transferred", "zh": "已传输"},
    "col.hosts": {"en": "hosts", "zh": "主机"},
    "col.error": {"en": "error", "zh": "错误"},

    # --- code-form words: the same string in both columns, on purpose -------
    #
    # These are what the record calls things: an API field, a path, a flag, a
    # vocabulary word a select box offers.  They are in the catalogue so that a
    # page has one place to read every word it prints, and so that `--check` can
    # say "same on purpose" instead of "not translated".  A word that a select
    # box offers as a *value* (`pulled`, `pass`, `resident`) is not here: the
    # value is the vocabulary, and one vocabulary has one spelling (src/GUI.md §5).

    "word.build_id": {"en": "build_id", "zh": "build_id"},
    "word.tree": {"en": "tree", "zh": "tree"},
    "word.branch": {"en": "branch", "zh": "branch"},
    "word.arch": {"en": "arch", "zh": "arch"},
    "word.defconfig": {"en": "defconfig", "zh": "defconfig"},
    "word.compiler": {"en": "compiler", "zh": "compiler"},
    # The one word a date needs when it is not the build's own: the pull record's.
    "created.from_act": {"en": "the pull record's own time: no card names this build",
                         "zh": "拉取记录里的时间：没有卡片给这个 build 命名"},
    "word.created": {"en": "created", "zh": "created"},
    "word.node_id": {"en": "node_id", "zh": "node_id"},
    "word.describe": {"en": "describe", "zh": "describe"},
    "word.test": {"en": "test", "zh": "test"},
    "word.result": {"en": "result", "zh": "result"},
    "word.url": {"en": "url", "zh": "url"},
    "word.platform": {"en": "platform", "zh": "platform"},
    "word.runtime": {"en": "runtime", "zh": "runtime"},
    "word.build": {"en": "build", "zh": "build"},
    "word.owner": {"en": "owner", "zh": "owner"},
    "word.state_result": {"en": "state / result", "zh": "state / result"},
    "word.tree_branch": {"en": "tree / branch", "zh": "tree / branch"},
    "word.arch_defconfig_compiler": {"en": "arch / defconfig / compiler",
                                     "zh": "arch / defconfig / compiler"},

    # --- the sentences Local.state_text() builds (src/GUI.md §1.4) ----------

    "evidence.pulled_text": {
        "en": "pulled {n} artifacts from {hosts} ({size}) at {at} - {moved} transferred, "
              "{whole} already whole",
        "zh": "从 {hosts} 拉了 {n} 个构件（{size}），时间 {at} - 传输了 {moved} 个，"
              "{whole} 个本来就在"},
    "evidence.failed": {"en": "{said}; that attempt failed: {error}",
                        "zh": "{said}；那次拉取失败了：{error}"},
    "evidence.unrecorded_text": {"en": "no pull recorded for these bytes ({where})",
                                 "zh": "这些字节没有拉取记录（{where}）"},
    "evidence.card_in_table": {"en": "a card in the local table", "zh": "本地表里有卡片"},
    "evidence.registered_text": {"en": "registered from the API node {node}, nothing pulled yet",
                                 "zh": "从 API 的 node {node} 登记来的，还没拉过"},
    "evidence.made_here_text": {
        "en": "made here (published locally): no pull, and no node id to tie it to",
        "zh": "本地造的（本地发布的）：没有拉取，也没有 node id 可以对应"},
    "evidence.empty_text": {"en": "nothing on disk and no card", "zh": "磁盘上没有东西，也没有卡片"},

    # --- what each state of the record means (src/GUI.md §1.4) -------------


    # --- buttons and links the rendering helpers draw -----------------------

    "btn.apply": {"en": "apply", "zh": "应用"},
    "btn.clear": {"en": "clear", "zh": "清除"},
    "btn.refresh": {"en": "refresh", "zh": "刷新"},
    "btn.run": {"en": "run", "zh": "跑"},
    "btn.record_window": {"en": "record this window in the local table",
                          "zh": "把这一批登记进本地表"},
    "link.log": {"en": "log", "zh": "日志"},
    # The select-all in a tick column's header.  `{n}` is how many boxes this page
    # drew, because that is exactly what the box ticks: `table.py`'s commands read
    # the ids a form posts, and a control that claimed to tick rows the page did not
    # draw would be promising a command nobody wrote.
    "tick.all": {"en": "tick the {n} on this page", "zh": "勾选本页 {n} 行"},
    "tick.all_title": {
        "en": "ticks every box this page drew - only those; the filter may have matched "
              "more rows than the cap printed, so raise rows to widen it",
        "zh": "只勾这一页画出来的框；筛选匹配的行可能比上限印出来的多，要更多就把「行数」调大"},
    # `/runs/<id>/log` is the log as a page: two lines of header, then the file.
    # "Open it yourself" (`我要的是类似自己打开那种`) needs the activity to be named in
    # the tab, and an activity with no output yet to say so rather than serve nothing.
    "log.head": {"en": "activity {run} - state {state}, exit {exit_code}",
                 "zh": "活动 {run} — 状态 {state}，退出 {exit_code}"},
    "log.empty": {"en": "this activity has written nothing to its log yet",
                  "zh": "这个活动还没往日志里写任何东西"},
    # The refresh control and the age of what this page last read (`gui._refresh`).
    # A unit beside a number and a `title=` - never a sentence: an API answer may be
    # reused for a few seconds, and a page that hid that would be pretending it had
    # just asked (`docs/gui-rework/01-perf.md` §D2, `05-i18n-prose.md` §B.1).
    "refresh.now": {"en": "read now", "zh": "刚刚读到"},
    "refresh.age": {"en": "read {age} ago", "zh": "{age} 前读到"},
    "refresh.title": {"en": "read the files and ask the API again; an answer already read "
                            "is reused for up to {ttl}",
                      "zh": "重新读文件并再问一次 API；已经读到的答案最多复用 {ttl}"},
    "js.cancel": {"en": "cancel", "zh": "取消"},
    "js.loading": {"en": "loading {id}...", "zh": "正在读 {id}…"},
    "run.this_deployment": {"en": "this deployment", "zh": "这个部署"},

    # --- the live panel and the finish notice -------------------------------
    #
    # The shell's own panel (`gui._live_panel`, `gui._live_chip`) and the notice the
    # poll script writes into `#notice` (`_JS_WORDS` names the ones the script reads).
    # Numbers, units, control text and `title=` only: the panel is a list of
    # activities, so every line it prints is a state, a duration, an exit code or a
    # link - `05-i18n-prose.md` §B.1's rule, and the reason there is no sentence here
    # about *why* a panel exists.
    #
    # `{n} running` and `nothing running` are the tab and the header chip; the count
    # is in the number, so the word does not repeat it.
    "live.tab_running": {"en": "{n} running", "zh": "{n} 在跑"},
    "live.tab_idle": {"en": "nothing running", "zh": "没有在跑的"},
    "live.head_running": {"en": "running now", "zh": "正在跑"},
    "live.head_recent": {"en": "just ended", "zh": "刚结束"},
    # An exit code is a number; "no code was seen" is the honest spelling of the case
    # `Run._settle` turns into `failed` whatever the child really exited with - the
    # notice and the panel's ended rows both print this rather than repeat a verdict
    # nobody can check (`07-shell.md` §A3).
    "live.exit": {"en": "exit {code}", "zh": "退出 {code}"},
    "live.exit_unknown": {"en": "exit code not seen", "zh": "没看到退出码"},
    "live.none": {"en": "no activity on disk has run today", "zh": "磁盘上没有今天跑过的活动"},
    "live.noscript": {
        "en": "JavaScript is off: this list is from when the page was drawn",
        "zh": "JavaScript 关着：这个列表是页面画出来时的样子"},
    "live.notify_on": {"en": "desktop notices on", "zh": "桌面通知已开"},
    "live.notify_off": {"en": "desktop notices off", "zh": "桌面通知已关"},
    "notice.done": {"en": "{kind} finished - exit {code}", "zh": "{kind} 跑完了 - 退出 {code}"},
    "notice.failed": {"en": "{kind} failed - exit {code}", "zh": "{kind} 失败了 - 退出 {code}"},
    "notice.nocode": {"en": "{kind} ended - no exit code was seen",
                      "zh": "{kind} 结束了 - 没看到退出码"},
    # A cancel is the one finish the reader caused: neither done nor failed, and the
    # exit code (`-15`) is the signal, not a verdict.
    "notice.cancelled": {"en": "{kind} cancelled", "zh": "{kind} 已取消"},
    "notice.gone": {"en": "{kind} {id} is no longer on disk",
                    "zh": "{kind} {id} 已经不在磁盘上了"},
    "notice.dismiss": {"en": "dismiss", "zh": "知道了"},

    # --- a request that was refused (409/404, plain text on the wire) -------

    "error.not_an_option": {"en": "{key}={value} is not one of: {options}",
                            "zh": "{key}={value} 不在这些里面：{options}"},
    "error.not_a_name": {"en": "{key}={value} is not a name; use the select boxes",
                         "zh": "{key}={value} 不是名字；请用选择框"},
    "error.two_build_ids": {"en": "two build ids are needed", "zh": "需要两个 build id"},
    "error.unknown_action": {"en": "unknown action {name}; known: {known}",
                             "zh": "不认识的动作 {name}；认识的有：{known}"},
    "error.pull_needs_build": {"en": "pull needs at least one ticked build",
                               "zh": "拉取至少要勾一个 build"},
    # A POST body this page cannot read is a POST whose fields are all missing, and
    # a missing field silently becomes a default (`_first(form, "tree")`).  Refusing
    # is the only honest answer; the page's own script sends `URLSearchParams` and a
    # plain form sends the same encoding, so this is a hand-made request.
    "error.body_not_a_form": {
        "en": "a POST body of type {kind} is not a form; send "
              "application/x-www-form-urlencoded or multipart/form-data",
        "zh": "{kind} 类型的 POST body 不是表单；请发 application/x-www-form-urlencoded "
              "或 multipart/form-data"},
    "error.body_no_boundary": {
        "en": "a multipart/form-data body without a boundary names no fields",
        "zh": "multipart/form-data 的 body 没有 boundary，读不出任何字段"},
    "error.run_needs_build": {"en": "run needs at least one ticked build",
                              "zh": "跑至少要勾一个 build"},
    "error.drift_needs_two": {"en": "drift needs two build ids, one in each select box",
                              "zh": "drift 要两个 build id，两个选择框各一个"},
    "error.writer_busy": {
        "en": "{writer} is writing right now; one writer at a time - the ledger, the download "
              "tree and the table have one writer each",
        "zh": "{writer} 现在正在写；一次只允许一个写者 - 账本、下载目录和本地表各自只有一个写者"},
    "error.no_activity": {"en": "no activity {run_id}", "zh": "没有这条活动 {run_id}"},
    "error.no_page": {"en": "no page {page}; the pages are {routes} and /local/<build_id>",
                      "zh": "没有这个页面 {page}；页面有 {routes}，以及 /local/<build_id>"},
    "error.no_local_copy": {"en": "no local copy {build_id} (see /local)",
                            "zh": "没有这份本地拷贝 {build_id}（见 /local）"},
    "error.no_such_action": {"en": "no such action", "zh": "没有这个动作"},
    "error.port_taken": {
        "en": "cannot listen on {host}:{port} ({why}); another page may already be there - "
              "choose another port with --port",
        "zh": "监听不了 {host}:{port}（{why}）；可能已经有页面在那里了 - 用 --port 换一个端口"},

    # --- the words the bilingual wiring pass added -------------------------
    #
    # Everything below was read off `lib/gui.py` while `lang` was threaded through
    # it: the fifteen strings the skin pass left in English, the four sentences of
    # the "which of the two empty answers is this" branches, and the value -> label
    # maps a select box needs so that a *value* is never translated.

    "filter.in_force": {"en": "in force:", "zh": "生效中："},
    # --- the axes strip (`_axes`) ------------------------------------------
    #
    # Labels and units only, never a sentence: the strip prints `key: value` for
    # every axis a page reads, its default included, so `?api=production` stops
    # rendering byte-identically to a URL with no `api` key at all
    # (`docs/gui-rework/02-filters.md` §A5).  A page may print a word only where a
    # number, a column, a link or a `title=` cannot carry the fact (`05` §B.1), so
    # every entry here is a field label, a unit, or a `title=`.
    "filter.window": {"en": "window", "zh": "窗口"},
    "filter.axis_count": {"en": "{n} of {total} rows match", "zh": "{total} 行里有 {n} 行"},
    "filter.axis_applied": {"en": "applied to the rows this page read",
                            "zh": "在本页读到的行里筛"},
    # The cap's own cost: 3.5 KB a row, measured (175 082 bytes for 50 rows,
    # `docs/gui-rework/01-perf.md` §D1c).  A `rows` control that does not say what
    # a row costs is a control the reader cannot price.
    "filter.cap_bytes": {"en": "{kb} KB", "zh": "{kb} KB"},
    "filter.cap_rows": {"en": "{n} rows", "zh": "{n} 行"},
    "filter.cap_title": {"en": "{bytes} bytes for {rows} rows, measured",
                         "zh": "{rows} 行实测 {bytes} 字节"},
    "filter.api_total": {"en": "API", "zh": "API"},
    "filter.outside_cap": {"en": "outside the cap", "zh": "在上限之外"},
    "filter.filtered_here": {"en": "filtered here", "zh": "本页筛掉的"},
    "filter.no_answer": {"en": "no answer", "zh": "没有回答"},
    "filter.branch_of_tree": {"en": "the branches {tree} binds in the pipeline config",
                              "zh": "pipeline 配置里 {tree} 绑的分支"},
    "filter.drop_condition": {"en": "drop", "zh": "去掉这个条件"},
    "filter.own": {"en": "this page's own filter: ", "zh": "本页自己的筛选："},
    "filter.none": {"en": "(none)", "zh": "（无）"},
    "filter.noscript": {"en": "JavaScript is off: change a value, then press apply.",
                        "zh": "JavaScript 没开：改一个值，然后按「应用」。"},
    # The window's own label.  `label.last` is the *column* "last" (the newest
    # verdict); a number box whose name is `days` reads better spelled out, and the
    # English stays the one word it always was.
    "filter.last": {"en": "last", "zh": "最近（天）"},
    "action.details": {"en": "what this button sends", "zh": "这个按钮发出去什么"},
    "action.refused": {"en": "nothing to run: {reason}", "zh": "没有可跑的命令：{reason}"},
    # What an action bar's own line says, written by the page's script into
    # `[data-status]` (`_JS`) - so these four go through `textContent` and carry no
    # markup: the ellipsis and the colons are the characters themselves.
    # `action.rejected` is the *server's* answer to a POST (a 409's one plain-text
    # sentence), while `action.refused` above is the page refusing to print a
    # command line it cannot build - two different things, said differently.
    "action.sending": {"en": "sending…", "zh": "正在发…"},
    "action.started": {"en": "started {id}: {argv}", "zh": "已起 {id}：{argv}"},
    "action.rejected": {"en": "refused: {reason}", "zh": "被拒：{reason}"},
    "action.unreachable": {"en": "this page's own server did not answer: {error}",
                           "zh": "连不上页面自己的服务：{error}"},
    # What a tick-driven bar prints in place of the ids it cannot know until a box
    # is ticked (`Gui._argv_of_ticked`).  A bar that printed its own refusal there
    # was printing "no command to run" under a heading that promised a command
    # (`docs/gui-rework/04-actions.md` §2, the operator's second sentence).
    "action.ticked_build": {"en": "<each ticked build>", "zh": "<每个勾选的 build>"},
    # One activity's `what` column, read off its argv (`_what_of`): a flag repeated
    # more than twice collapses to this, so "run twenty builds" is a line and not a
    # page.  Code-form on purpose in both columns - it is a flag and a count.
    "run.n_of": {"en": "{flag} ×{n}", "zh": "{flag} ×{n}"},
    # A finished activity with no bytes in its log is not "loading…" for ever.
    "js.empty": {"en": "(no output)", "zh": "（没有输出）"},
    # The two sentences `?test=` gets instead of silence: a value this page cannot
    # run is *reported* (`Filter.clamps`), and `kbuild` - the one value an operator
    # is most likely to try - is named for what it is.
    # Both are printed inside `_shell`'s `capped` span, which **escapes** what it is
    # given (the `api_refused` note next to them is an address a reader typed): no
    # markup here, or the reader sees `&lt;code&gt;`.
    "filter.test_refused": {
        "en": "test={value} is not a test this page can run; it can run: {options}",
        "zh": "test={value} 不是本页能跑的 test；能跑的有：{options}"},
    "filter.test_is_job": {
        "en": "{value} is a build job (kind=kbuild), not a test; the builds it made are "
              "what index/pull/run read",
        "zh": "{value} 是 build 的 job（kind=kbuild），不是 test；它产出的 build 才是 "
              "index/pull/run 读的东西"},
    # The activity table's bookkeeping is folded by default, as *page filter state*
    # (`04` §P8a), and this is the one line that says so and undoes it in one click.
    "runs.folded_note": {
        "en": "the <code>table</code> activities are folded away — {link}",
        "zh": "<code>table</code> 活动折起来了 — {link}"},
    "runs.show_all": {"en": "show everything", "zh": "都显示"},
    "runs.group": {"en": "{kind} ({n})", "zh": "{kind}（{n}）"},
    # `runs.intro` was deleted here (accept.py's W1 found it after the first prose
    # pass): "Every activity is a directory with run.json and run.log; the argv column
    # is the exact command an operator would type, so a restart loses nothing. drift
    # activities exit 1 when the two configs differ: that exit code is the answer, not
    # a failure."  Four facts, none of them a number, a column, a link or a verdict -
    # every one of them belongs in a `title=`, and that is where they went: the
    # activity's own directory and its two files are the `title=` of its id cell
    # (`runs.dir_title`), the argv cell's title has always been the full argv, and the
    # drift exit code is the `title=` of a `drift` row's exit cell
    # (`analysis.drift_hint`).  05 §B.1: a page may print a word only where a number,
    # a column, a link or a tooltip cannot carry the fact.
    "runs.dir_title": {"en": "{dir}/run.json + run.log", "zh": "{dir}/run.json + run.log"},
    "col.name": {"en": "name", "zh": "名称"},
    # The overview's "how much" cell for the remote half: two counts, side by side,
    # and the row cap is not one of them (that is `remote.showing`'s sentence).
    # The counterpart of `col.here`: what the API says about a build, as a column
    # heading on /local, and the three columns of the ledger table on a copy's page.
    "col.remote": {"en": "remote", "zh": "远端"},
    "col.verdict": {"en": "verdict", "zh": "判决"},
    "col.source": {"en": "source", "zh": "来源"},
    "col.detail": {"en": "detail", "zh": "详情"},
    "state.current_paren": {"en": "{value} (current)", "zh": "{value}（当前）"},
    # A language's name is written in that language, in both columns, on purpose:
    # the switcher is the one thing a reader must be able to use *before* choosing.
    "lang.en": {"en": "English", "zh": "English"},
    "lang.zh": {"en": "中文", "zh": "中文"},

    # --- the branches that say "the API did not answer" --------------------
    #
    # Four places distinguish "nothing arrived" from "the answer was empty"
    # (src/GUI.md §1.5, §9); each one gets its own key rather than a shared tail.
    "remote.no_answer_line": {
        "en": "the API did not answer this query: {note} &mdash; there are no rows, and nothing "
              "is known about this window either way",
        "zh": "API 没有应答这次查询：{note} &mdash; 一行都没有，这个窗口的情况也无从得知"},
    "worker.no_answer": {"en": "the API did not answer this query: {note}",
                         "zh": "API 没有应答这次查询：{note}"},
    "state.no_answer_remote": {
        "en": "the API did not answer this query: nothing is known about the remote side",
        "zh": "API 没有应答这次查询：远端那一侧的情况无从得知"},
    "remote_detail.no_answer": {
        "en": "<b>the API did not answer this query</b> ({note}), so nothing is known about this "
              "copy's remote side &mdash; neither that it is there nor that it is not.",
        "zh": "<b>API 没有应答这次查询</b>（{note}），所以这份拷贝的远端一侧无从得知 "
              "&mdash; 既不知道它在，也不知道它不在。"},

    # --- value -> label, one map per word list -----------------------------
    #
    # A select box shows a label and submits a *value*; the value is what
    # `Filter.accepts()`, `Records` and `Run` compare, so it is never translated
    # (src/GUI.md §5, and `PILL_WORDS` colours it).  These keys are the label only.
    # A column that repeats its value is not laziness: `pass`/`fail`/`incomplete`/
    # `error` are `judge`'s vocabulary and `available`/`done`/... are the API's job
    # states, and a page that re-spelled them would be a second vocabulary for one
    # fact - it would also stop `datacheck.py`'s verdict probe from finding the word
    # in the class.  Everything a *reader chooses* is translated.

    "evidence.label.pulled": {"en": "pulled", "zh": "有拉取记录"},
    "evidence.label.unrecorded": {"en": "unrecorded", "zh": "有字节、没记录"},
    "evidence.label.registered": {"en": "registered", "zh": "只有卡片"},
    "evidence.label.made_here": {"en": "made-here", "zh": "本地自造"},
    # `bytes` is the one value of the evidence box that is not a `Local.state`: it
    # asks the download tree, whatever the record says, which is what the numbers
    # strip's `with bytes` chip counts.
    "evidence.label.bytes": {"en": "bytes on disk", "zh": "磁盘上有字节"},    "evidence.label.empty": {"en": "empty", "zh": "空"},
    "origin.label.local": {"en": "local", "zh": "本地"},
    "origin.label.remote": {"en": "remote", "zh": "远端"},
    "origin.label.both": {"en": "both", "zh": "两个都要"},
    # The fourth answer to "where does this row's authority come from": a card in the
    # local table.  It is not a third place - it is the one selectable set that the
    # numbers strip's `cards` chip counts, and without it that chip was the one number
    # on the page whose link could not reproduce it (`accept.py`'s S6): `origin=local`
    # is cards OR bytes, which is a superset as soon as one directory has no card.
    "origin.label.card": {"en": "carded", "zh": "有卡片"},
    "ran.label.never": {"en": "never", "zh": "从没跑过"},
    "ran.label.ever": {"en": "ever", "zh": "跑过"},
    "ran.label.failing": {"en": "failing", "zh": "有失败"},
    "mode.label.once": {"en": "once", "zh": "跑一轮"},
    "mode.label.resident": {"en": "resident", "zh": "常驻"},
    "verdict.label.pass": {"en": "pass", "zh": "pass"},
    "verdict.label.fail": {"en": "fail", "zh": "fail"},
    "verdict.label.incomplete": {"en": "incomplete", "zh": "incomplete"},
    "verdict.label.error": {"en": "error", "zh": "error"},
    "job_state.label.available": {"en": "available", "zh": "available"},
    "job_state.label.done": {"en": "done", "zh": "done"},
    "job_state.label.running": {"en": "running", "zh": "running"},
    "job_state.label.reserved": {"en": "reserved", "zh": "reserved"},
    "job_state.label.closing": {"en": "closing", "zh": "closing"},
    "run_state.label.running": {"en": "running", "zh": "running"},
    "run_state.label.done": {"en": "done", "zh": "done"},
    "run_state.label.failed": {"en": "failed", "zh": "failed"},
    "run_state.label.cancelled": {"en": "cancelled", "zh": "cancelled"},
}

# Every key, in catalogue order - what `--check` walks and what `--map` prints.
KEYS: tuple[str, ...] = tuple(CATALOGUE)


# ---------------------------------------------------------------------------
# The two reads: one string, and one language
# ---------------------------------------------------------------------------

def t(lang: str, key: str, /, **fmt) -> str:
    """One string, in `lang`; an unknown key is returned as itself, never raised.

    The fallback chain is the whole robustness story of a page: the asked language
    -> English -> the key.  Values in `fmt` are interpolated with `str.format`,
    and are **not escaped** - the caller escapes what it interpolates.  A row that
    is missing a placeholder, or that has a stray brace, comes back as written.

    `lang` and `key` are positional-only (the `/`) so that a row may use `{key}`
    as a placeholder - `error.not_a_name` does - without the call colliding with
    this signature.  A collision is not a bad string: it is a `TypeError` at the
    raise site, which is a 500 on a request that meant to be a 409.
    """
    row = CATALOGUE.get(key)
    if row is None:
        return key
    text = row.get(lang) or row.get(DEFAULT_LANG) or key
    if not fmt:
        return text
    try:
        return text.format(**fmt)
    except (IndexError, KeyError, ValueError):
        return text


def is_key(key: str) -> bool:
    """Is this a key the catalogue knows?  (`key_for()` is the other direction.)"""
    return key in CATALOGUE


def pick_lang(query_lang: str, cookie_lang: str, accept_language: str) -> str:
    """Which of LANGS to draw a page in: query, then cookie, then the header.

    A value nobody knows is skipped rather than refused, so `?lang=fr` still
    renders - in the next language that *is* known.  `Accept-Language` is
    negotiated by q value (ties go to the earlier tag), `zh-CN`/`zh-Hans`/`zh-TW`
    all count as `zh`, and a tag with `q=0` is a tag the client refused: it is
    dropped before it can be chosen.

    A region tag counts the same way in a URL and in the cookie as it does in the
    header: `?lang=zh-CN` asks for `zh`, not for the default.  The page itself
    only ever writes `zh`/`en`, so this costs nothing, and a pasted or bookmarked
    URL then means what whoever wrote it meant.
    """
    for asked in (query_lang, cookie_lang):
        found = _asked(asked)
        if found:
            return found
    return _negotiate(accept_language) or DEFAULT_LANG


def _asked(value: str) -> str:
    """A URL or cookie value as one of LANGS, or `""` when it names nothing we have.

    `zh-CN`, `ZH-cn` and `zh_Hans` are all `zh`.  `*` is *not* the default here:
    it names no language this function can pick, so the caller falls through to
    the next source instead of the negotiation stopping on it.
    """
    text = (value or "").strip().lower().replace("_", "-")
    for lang in LANGS:
        if text == lang or text.startswith(f"{lang}-"):
            return lang
    return ""


def _negotiate(header: str) -> str:
    """The best of an Accept-Language header, or `""` when it names nothing we have."""
    best: tuple[float, int, str] | None = None
    for order, item in enumerate((header or "").split(",")):
        tag, _, params = item.partition(";")
        weight = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value.strip())
                except ValueError:
                    weight = 1.0
        if weight <= 0:
            continue                        # q=0 is "not acceptable", not "least wanted"
        lang = _from_tag(tag.strip().lower())
        if not lang:
            continue
        rank = (weight, -order)
        if best is None or rank > best[:2]:
            best = (rank[0], rank[1], lang)
    return best[2] if best else ""


def _from_tag(tag: str) -> str:
    """One language tag as one of LANGS: `zh-TW` is `zh`, `*` is the default."""
    if not tag:
        return ""
    if tag == "*":
        return DEFAULT_LANG
    for lang in LANGS:
        if tag == lang or tag.startswith(lang + "-"):
            return lang
    return ""


def key_for(text: str) -> str | None:
    """The key a piece of today's English belongs to - how gui.py gets wired.

    Whitespace is normalised on both sides first, so a sentence that gui.py builds
    from two source lines is still found.  A hit is an exact match on an English
    row, a whole-template match (`{n}` standing for whatever is there), or an
    unambiguous prefix (`"asked the API"` is enough).  Anything ambiguous - the
    word `what`, which is two headers, say - is `None`: the mapping in LOCATIONS,
    not a guess, is what a mechanical replacement should follow.
    """
    wanted = _normalize(text)
    if not wanted:
        return None
    rows = _index()
    exact = rows["exact"].get(wanted) or ()
    if len(exact) == 1:
        return exact[0]
    whole = [key for key, english in rows["templates"] if _template_match(english, wanted)]
    if len(whole) == 1:
        return whole[0]
    near = sorted({key for key, english in rows["prefixes"].items()
                   if english.startswith(wanted)},
                  key=KEYS.index)
    return near[0] if len(near) == 1 else None


def _normalize(text: str) -> str:
    """One line, one space between words - what a source line and a value agree on."""
    return " ".join(str(text or "").split())


def _template_match(english: str, text: str) -> bool:
    """Does `text` fill this English row's `{placeholders}`?  Each one matches anything."""
    head, sep, tail = _split_placeholder(english)
    if not sep:
        return text == head
    if not text.startswith(head):
        return False
    rest = text[len(head):]
    while True:                                 # the placeholder eats one more char at a time
        if _template_match(tail, rest):
            return True
        if not rest:
            return False
        rest = rest[1:]


def _split_placeholder(text: str) -> tuple[str, str, str]:
    """The first `{name}` of a value, split out as (before, `{name}`, after)."""
    start = text.find("{")
    while start != -1:
        end = text.find("}", start)
        if end == -1:
            break
        name = text[start + 1:end]
        if name and (name[0].isalpha() or name[0] == "_") \
                and all(one.isalnum() or one == "_" for one in name):
            return text[:start], text[start:end + 1], text[end + 1:]
        start = text.find("{", start + 1)
    return text, "", ""


_INDEX: dict[str, object] | None = None


def _index() -> dict[str, object]:
    """The lookup `key_for()` needs, built once: exact rows, templates, prefixes."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    exact: dict[str, list[str]] = {}
    prefixes: dict[str, str] = {}
    templates = []
    for key in KEYS:
        english = _normalize(CATALOGUE[key][DEFAULT_LANG])
        exact.setdefault(english, []).append(key)
        prefixes.setdefault(key, english)
        if "{" in english:
            templates.append((key, english))
    _INDEX = {"exact": {one: tuple(keys) for one, keys in exact.items()},
              "prefixes": prefixes, "templates": tuple(templates)}
    return _INDEX


# ---------------------------------------------------------------------------
# key -> the line of lib/gui.py it is today (a snapshot, for the wiring pass)
# ---------------------------------------------------------------------------

# Read off lib/gui.py at md5 3a10c0f1ee2b73621a48ec9189920f16 (2085 lines) - the file
# was rewritten by another pass while this catalogue was written, so the English in
# CATALOGUE, not a line number, is what identifies a string.  Lines move as soon as
# gui.py is edited again: `--map lib/gui.py` re-prints them against the file on disk
# and marks the ones that no longer look like a match.
LOCATIONS: dict[str, tuple[int, ...]] = {
    "nav.jobs": (78, 853, 1417),
    "nav.runs": (78, 760, 854, 1363, 1369, 1438, 1526, 1529),
    "nav.worker": (62, 68, 73, 78, 938, 1494),
    "nav.analysis": (79, 1538),
    "header.api_down": (1041,),
    "header.busy": (1045, 1046),
    "header.tagline": (1629,),
    "label.records_in_ledger": (1092,),
    "label.verdicts": (724, 1094),
    "label.gap": (1097,),
    "label.regressions": (1099, 1529),
    "remote.asked": (1116, 1304, 1453),
    "remote.rows": (1989, 1990),
    "remote.query_from": (1129, 2243),
    "remote.query_window": (631, 639),
    "remote.index_hint": (1133,),
    "filter.rows": (848, 1124, 1168, 1313, 1360, 1460),
    "col.remote_says": (1135, 1868),
    "col.here": (735, 1135),
    "empty.remote_no_answer": (2002, 2003, 2004),
    "empty.remote_empty": (2005, 2006),
    "col.registered": (100, 390, 429, 1175, 1648, 1715),
    "filter.evidence": (1086, 1165),
    "filter.origin": (255, 1166, 1312, 2035),
    "filter.missing": (257, 1167, 1311),
    "col.bytes_on_disk": (2, 1175),
    "col.correspondence": (1176,),
    "btn.publish_image": (1201,),
    "local.image_state": (1921,),
    "local.image_state_missing": (),
    "empty.filter_hides": (2031, 2032, 2033, 2034, 2035),
    "empty.nothing_local": (2036, 2037),
    "link.clear_filter": (2032,),
    "page.correspondence.card_title": (343, 394, 708, 1210, 1223),
    "page.correspondence.card_sub": (1223,),
    "page.correspondence.bytes_title": (2, 343, 677, 708, 1210, 1243, 1252),
    "page.correspondence.bytes_sub": (1243,),
    "page.correspondence.record_title": (343, 394, 677, 1250),
    "page.correspondence.remote_title": (1210, 1256),
    "page.correspondence.remote_sub": (2, 343, 420, 421, 430, 677, 894, 1029, 1229, 1256, 1332,
        1646, 1647, 1649),
    "page.correspondence.ledger_title": (616, 740, 964, 1090, 1092, 1210, 1258, 1268, 1340, 1389,
        1391, 1401, 1402, 1413),
    "page.correspondence.activities_title": (1269,),
    "page.correspondence.activities_sub": (1269,),
    "col.field": (1224,),
    "col.value": (1224,),
    "label.artifact_urls": (1238,),
    "state.no_node_id": (1229,),
    "state.not_in_table": (1230, 1845),
    "empty.no_bytes": (1249,),
    "empty.no_pull_record": (1252, 1253, 1254, 1255),
    "empty.no_ledger_record": (1268,),
    "empty.no_activity_match": (1270,),
    "btn.pull_recheck": (1274,),
    "btn.run_pending": (1279,),
    "correspondence.pull_hint": (1276,),
    "col.artifact_urls": (1238, 1933),
    "state.no_remote_counterpart": (1197, 1651, 1683, 1689, 1696, 1698, 1702, 1740, 1922),
    "remote.showing": (1990,),
    "remote.rows_cap": (1991,),
    "remote.coverage_unknown": (477,),
    "remote.coverage_base": (478,),
    "remote.coverage_all": (480,),
    "remote.coverage_capped": (482, 483),
    "remote.coverage_filtered": (486, 487),
    "remote.query_all": (639,),
    "filter.day_all": (97,),
    "filter.capped_rows": (277,),
    "filter.capped_days": (279,),
    "filter.api": (1631, 1635),
    "filter.api_refused": (646,),
    "api.name.local": (1634,),
    "api.name.production": (1634,),
    "api.name.launch": (1634,),
    "remote_detail.none": (1922, 1923, 1924),
    "remote_detail.node_mismatch": (1929, 1930, 1931),
    "empty.nothing_pulled": (1327, 1328, 1329),
    "pull.no_card_title": (1845, 1846),
    "state.already_whole": (423, 1858, 1905),
    "btn.pull_selected": (1864,),
    "pull.pull_hint": (1865, 1866, 1867),
    "col.on_disk": (2, 398, 434, 808, 1175, 1243, 1249, 1422, 1868),
    "col.would_fetch": (1868,),
    "col.record_now": (1869,),
    "filter.ran": (258, 1176, 1358),
    "filter.verdict": (1359,),
    "col.needs": (758, 1363, 1367),
    "col.ready": (1363,),
    "label.runs": (78, 760, 854, 1363, 1369, 1438, 1526, 1529),
    "label.last": (1122, 1309, 1363, 1529),
    "col.when": (762, 1259, 1363, 1372, 1874),
    "col.in_gap": (1364,),
    "state.ready": (1368,),
    "state.already_recorded": (1373,),
    "empty.no_gap": (1377, 1378),
    "page.jobs.run_title": (1379,),
    "page.jobs.run_sub": (1379,),
    "btn.run_ticked": (1387,),
    "jobs.run_hint": (1389, 1390),
    "page.jobs.day_title": (1391,),
    "filter.days": (249, 912, 1122, 1309, 1395, 1816),
    "filter.builds": (856, 857, 1397),
    "btn.run_day": (1399,),
    "jobs.runday_hint": (1400, 1401),
    "page.jobs.elsewhere_title": (1402,),
    "page.jobs.elsewhere_sub": (1402,),
    "btn.run_newest": (1407,),
    "btn.ledger_full": (1413,),
    "jobs.results_hint": (1414,),
    "runs.intro": (1431, 1432, 1433, 1434),
    "empty.no_activity": (1435,),
    "col.age": (810, 2056),
    "col.exit": (1259, 2056),
    "col.what_run": (809, 1074, 1091, 2056),
    "word.argv": (811, 970, 1221, 1432, 2056, 2060),
    "word.id": (809, 990, 2056),
    "word.kind": (534, 809, 970, 1016, 1331, 1424, 1427, 2056),
    "word.state": (534, 720, 733, 788, 809, 991, 1016, 1018, 1087, 1428, 1429, 1457, 1463, 1467),
    "filter.name": (788, 1458, 1459, 1463, 1466),
    "col.definition": (790, 1464, 1470),
    "col.claimed": (1464,),
    "empty.queue_no_answer": (2012, 2013, 2014),
    "empty.queue_empty": (2015, 2016, 2017, 2018),
    "page.worker.state_title": (1474,),
    "page.worker.state_sub": (1474,),
    "col.cursor": (1476,),
    "col.seen": (780, 1476, 1479),
    "col.pending": (1476, 1480),
    "page.worker.start_title": (1443, 1481),
    "page.worker.start_sub": (1481,),
    "filter.mode": (939, 1484),
    "btn.start_worker": (1489,),
    "worker.start_hint": (1491, 1492),
    "state.any": (98, 99, 100, 215, 218, 221, 255, 258, 261, 306, 319, 323, 1697),
    "state.any_paren": (),
    "page.analysis.drift_title": (1505,),
    "page.analysis.drift_sub": (1505,),
    "btn.run_drift": (1511,),
    "analysis.drift_hint": (1512, 1513),
    "analysis.choose_two": (1515, 1516),
    "page.analysis.trend_title": (1499, 1517),
    "page.analysis.trend_sub": (1517, 1518),
    "col.timeline": (1529,),
    "btn.compare": (1947,),
    "analysis.drift_form_hint": (1948,),
    "filter.older": (536, 864, 868, 869, 952, 966, 1021, 1509, 1946),
    "filter.newer": (536, 864, 868, 869, 952, 1022, 1510, 1946),
    "drift.cannot_compare": (1955,),
    "drift.no_drift": (1957, 1958, 1959),
    "drift.added": (870, 871, 1961),
    "drift.removed": (870, 871, 1961),
    "drift.changed": (870, 872, 1962),
    "drift.more": (1965,),
    "drift.summary": (1967, 1968, 1969, 1970),
    "state.pulled_recorded": (1714,),
    "state.bytes_no_pull": (1714,),
    "state.card_only": (1715,),
    "state.made_here": (433, 1715, 1723),
    "state.empty": (100, 389, 1650, 1715),
    "state.not_here": (737,),
    "state.not_held_here": (736,),
    "state.node": (394, 430, 433, 1223, 1229, 1648, 1649, 1720, 1723, 1741, 1744, 1929),
    "state.no_node_id_made_here": (1723,),
    "state.no_card_in_table": (427, 1722, 1861),
    "state.remote_cell": (1741,),
    "state.remote_cell_mismatch": (1744,),
    "state.already_whole_proven": (1905,),
    "state.no_error": (1898,),
    "state.no_runs": (2043,),
    "state.yes": (1373, 1470, 1471),
    "state.no": (1470, 1471),
    "label.error_prefix": (1553, 1898),
    "count.artifacts_act": (420, 1897),
    "col.that_pull": (375, 1900),
    "col.artifacts": (734, 1874),
    "col.artifact": (1244, 1900, 1901),
    "col.file": (857, 1244, 1476),
    "col.bytes": (438, 830, 1244, 1874, 1900),
    "col.transferred": (419, 1874, 1880, 1904),
    "col.hosts": (723, 1874),
    "col.error": (424, 826, 864, 868, 1874, 1884, 1898, 1954),
    "word.build_id": (302, 711, 730, 755, 825, 833, 881, 1134, 1145, 1175, 1188, 1225, 1348,
        1363),
    # Step 6's own block: the `/analysis` model - the sort, the `delta` cap, the editor's
    # `[older]`/`[newer]` columns, the `+`/`-` cells, the bars and the run's record.
    # Lines read off gui.py as it stood when step 6 landed (`--map` re-prints them
    # against the file on disk and marks the ones that no longer look like a match).
    "filter.sort": (3629,),
    "filter.point": (752,),
    "sort.date": (6392,),
    "sort.date_asc": (6385,),
    "sort.same_branch": (6387,),
    "sort.verdict": (6389,),
    "sort.build": (6391,),
    "delta.cap": (752,),
    "delta.none_prev": (6558,),
    "delta.none_next": (6562,),
    "delta.cannot": (3716,),
    "delta.beyond": (6566,),
    "delta.why_no_config": (6589,),
    "delta.why_not_found": (6584,),
    "delta.why_not_config": (6582,),
    "delta.cache_short": (6586,),
    "delta.pair_title": (6610,),
    "delta.failed_title": (6633,),
    "col.delta": (7205,),
    "col.delta_sub": (7053,),
    "col.n": (7051,),
    "col.option": (6734,),
    "col.cases": (6944,),
    "chart.title": (3648,),
    "chart.sub": (3648,),
    "page.analysis.picks_title": (3644,),
    "page.analysis.picks_sub": (3645,),
    "page.analysis.runs_title": (3672,),
    "page.analysis.runs_sub": (3673,),
    "page.analysis.point_title": (3683,),
    "page.analysis.point_sub": (3683,),
    "mark.records": (7182,),
    "empty.no_builds": (7237,),
    "word.commit": (6937,),
    "word.log": (6946,),
    "word.config": (7180,),
    "drift.nothing": (6744,),
    "drift.all_rows": (6751,),
    "drift.badge": (3712,),
    "drift.same_branch": (3710,),
    "drift.cross_tree": (3711,),
    "analysis.not_read": (3594,),
    "word.tree": (252, 289, 302, 713, 730, 756, 914, 967, 1118, 1119, 1134, 1138, 1163, 1164),
    "word.branch": (252, 289, 302, 714, 730, 1120, 1121, 1134, 1138),
    "word.arch": (253, 290, 715, 731, 1134, 1139),
    "word.defconfig": (253, 290, 716, 731, 1134, 1139),
    "word.compiler": (717, 732, 1134, 1140),
    "word.created": (718, 732, 790, 1134, 1141, 1237, 1463, 1469, 1868, 1932),
    "word.node_id": (302, 395, 719, 733, 788, 828, 1135, 1227, 1463, 1723, 1742, 1932),
    "word.describe": (302, 712, 734, 757, 1175, 1181, 1226, 1868),
    "word.test": (259, 538, 755, 880, 915, 966, 1259, 1347, 1357, 1363, 1366, 1374, 1382, 1383),
    "word.result": (733, 789, 1463, 1467),
    "word.url": (411, 1881, 1900),
    "word.platform": (789, 940, 1463, 1468, 1485, 1486),
    "word.runtime": (789, 941, 1463, 1468, 1487, 1488),
    "word.build": (949, 1410, 1411),
    "word.owner": (1091,),
    "word.state_result": (1932,),
    "word.tree_branch": (1231, 1932),
    "word.arch_defconfig_compiler": (1233,),
    "evidence.pulled_text": (420, 421, 422, 423),
    "evidence.failed": (425,),
    "evidence.unrecorded_text": (428,),
    "evidence.card_in_table": (427,),
    "evidence.registered_text": (430, 431),
    "evidence.made_here_text": (433,),
    "evidence.empty_text": (434,),
    "btn.apply": (1797,),
    "btn.clear": (1798,),
    "btn.run": (62, 67, 73, 925, 928, 1374, 1807),
    "btn.record_window": (1131, 1320),
    "link.log": (810, 1587, 2067),
    "js.cancel": (1587, 2069),
    "js.loading": (1587,),
    "action.sending": (2876,),
    "action.started": (2876,),
    "action.rejected": (2877,),
    "action.unreachable": (2877,),
    "run.this_deployment": (968,),
    # The live panel and the finish notice (step 5).  Only the keys the *server*
    # reads have a line here: `notice.*` and `live.notify_on` are written by the poll
    # script and named in `_JS_WORDS`, so `t()` never sees them literally.  Lines are
    # as of the wave that added them; `--map` prints an empty list rather than a
    # wrong one, which is why a missing entry is untidy rather than misleading.
    "live.tab_running": (6281, 6354),
    "live.tab_idle": (6281, 6355),
    "live.head_running": (6353,),
    "live.head_recent": (6353,),
    "live.exit": (6305,),
    "live.exit_unknown": (6306,),
    "live.none": (6376,),
    "live.noscript": (6377,),
    "live.notify_off": (6373,),
    "error.not_an_option": (173,),
    "error.not_a_name": (181,),
    "error.two_build_ids": (864,),
    "error.unknown_action": (901, 956),
    "error.pull_needs_build": (923,),
    "error.run_needs_build": (927,),
    "error.drift_needs_two": (954,),
    "error.writer_busy": (964, 965),
    "error.no_activity": (976, 983, 1435),
    "error.no_page": (1024, 1025),
    "error.no_local_copy": (1214,),
    "error.no_such_action": (567,),
    "error.port_taken": (601, 602),
}


# ---------------------------------------------------------------------------
# The self-check: python3 lib/i18n.py --check lib/gui.py
# ---------------------------------------------------------------------------

_KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.")
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyz")


def _calls(line: str) -> list[int]:
    """Where `t(` starts on this line - a call, not the tail of `format(` or `split(`."""
    found, at = [], 0
    while True:
        at = line.find("t(", at)
        if at < 0:
            return found
        before = line[at - 1] if at else " "
        if not (before.isalnum() or before in "_."):
            found.append(at)
        at += 2


def _literals(text: str) -> list[str]:
    """The string literals of a piece of source, in order, unescaped by halves."""
    out, at = [], 0
    while at < len(text):
        quote = text[at]
        if quote not in "'\"":
            at += 1
            continue
        end, chunk = at + 1, []
        while end < len(text) and text[end] != quote:
            if text[end] == "\\":
                chunk.append(text[end:end + 2])
                end += 2
                continue
            chunk.append(text[end])
            end += 1
        out.append("".join(chunk))
        at = end + 1
    return out


def _key_shape(text: str) -> bool:
    """Is this literal shaped like a key - dotted, lower-case, no spaces?"""
    return bool(text) and text[0] in _LETTERS and "." in text \
        and not text.startswith(".") and not text.endswith(".") and ".." not in text \
        and all(one in _KEY_CHARS for one in text)


def _used(path: str) -> tuple[list[tuple[int, str]], int]:
    """The keys a file hands to `t()`, with the line each one is on.

    Only literal keys can be read: `t(lang, key)` is counted, not guessed, and
    comes back as the second member.
    """
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()
    found: list[tuple[int, str]] = []
    unknown = 0
    for number, line in enumerate(lines, 1):
        for at in _calls(line):
            tail = line[at:at + 400]
            key = next((one for one in _literals(tail) if _key_shape(one)), None)
            if key is None:
                unknown += 1
                continue
            found.append((number, key))
    return found, unknown


def _check(paths: list[str]) -> int:
    """缺失的 key / 没被用到的 key / zh 缺了或与 en 一样的条目."""
    used: list[tuple[int, str, str]] = []
    computed = 0
    for path in paths:
        found, unknown = _used(path)
        used.extend((number, key, path) for number, key in found)
        computed += unknown
    missing = [one for one in used if not is_key(one[1])]
    seen = {key for _, key, _ in used}

    print(f"目录：{len(KEYS)} 个 key（en {len(KEYS)} 条，zh "
          f"{sum(1 for one in KEYS if CATALOGUE[one].get('zh'))} 条）")
    print(f"扫描：{', '.join(paths)} - {len(used)} 处 t() 调用"
          + (f"，另有 {computed} 处的 key 不是字面量（读不出来）" if computed else ""))

    print(f"\n[缺失] 文件里用了、目录里没有的 key：{len(missing)}")
    for number, key, path in missing:
        print(f"  {path}:{number}  {key}")
    if not missing:
        print("  （没有）")

    unused = [one for one in KEYS if one not in seen]
    print(f"\n[未使用] 目录里有、这个文件还没用到的 key：{len(unused)}")
    print("  " + (", ".join(unused) if unused else "（没有）"))

    blank = [one for one in KEYS if not CATALOGUE[one].get("zh")]
    same = [one for one in KEYS if CATALOGUE[one].get("zh") == CATALOGUE[one]["en"]]
    print(f"\n[zh 缺失] 有 en 没有 zh 的条目：{len(blank)}")
    print("  " + (", ".join(blank) if blank else "（没有）"))
    print(f"\n[zh 与 en 相同] {len(same)} 条 - 大部分是 word.* 里本来就该相同的词，"
          "逐条看过再定：")
    print("  " + (", ".join(same) if same else "（没有）"))

    print(f"\n退出码：{1 if missing or blank else 0}"
          f"（缺失 {len(missing)} + zh 缺失 {len(blank)}；未使用与 zh==en 不算失败）")
    return 1 if missing or blank else 0


def _map(path: str) -> int:
    """key -> 它在文件里的每一行，连同那一行的原文；行文已经不像那条英文的打一个 `?`."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for key in KEYS:
        print(f"{key}\t{CATALOGUE[key]['en']}")
        at = LOCATIONS.get(key, ())
        for number, one in enumerate(at):
            good = _looks(lines, one - 1, key)
            text = lines[one - 1].strip() if 0 < one <= len(lines) else ""
            flag = "" if good or number else "?"      # only the first line is judged
            print(f"    {one}{flag}\t{text[:110]}")
    return 0


def _looks(lines: list[str], index: int, key: str) -> bool:
    """Is there still a distinctive word of this key's English on that line?

    A coarse test on purpose: a sentence gui.py builds from four source lines has
    its head words on the first one only, so requiring all of them would mark
    every continuation line.  Sharing one long word is enough to say "this is
    probably still the place"; sharing none means the line moved.
    """
    if not 0 <= index < len(lines):
        return False
    words = [one for one in _words(_normalize(CATALOGUE[key]["en"])) if len(one) > 3]
    if not words:
        return True
    return any(one.lower() in lines[index].lower() for one in words)


def _words(text: str) -> list[str]:
    """The words of a sentence, apostrophes kept - what a coarse match compares."""
    out: list[str] = []
    chunk: list[str] = []
    for one in text:
        if one.isalpha() or one == "'":
            chunk.append(one)
        elif chunk:
            out.append("".join(chunk))
            chunk = []
    if chunk:
        out.append("".join(chunk))
    return out


def _main(argv: list[str]) -> int:
    """`--check FILE…` / `--map FILE`; anything else is a usage line, not a traceback."""
    if len(argv) >= 2 and argv[0] == "--check":
        return _check(argv[1:])
    if len(argv) == 2 and argv[0] == "--map":
        return _map(argv[1])
    print(__doc__.strip().splitlines()[0])
    print("用法：python3 lib/i18n.py --check lib/gui.py   # 缺失 / 未使用 / zh 与 en 相同")
    print("      python3 lib/i18n.py --map lib/gui.py     # key -> gui.py 行号")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
