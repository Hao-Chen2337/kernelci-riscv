# SPDX-License-Identifier: LGPL-2.1-or-later
"""`/local` and `/local/<build_id>`: what we hold, and what the record says.

One part of the catalogue; `lib/i18n/__init__.py` merges the parts in this
order.  The `# ---` banners below are the source's own grouping, kept as they
were written."""

PART: dict[str, dict[str, str]] = {
    # --- /local : what we hold ---------------------------------------------

    "col.card": {"en": "card", "zh": "卡片"},

    "col.act": {"en": "act", "zh": "act"},

    "col.api_says": {"en": "api says", "zh": "接口说"},

    "col.tick": {"en": "tick", "zh": "勾选"},

    "col.registered": {"en": "registered", "zh": "登记"},

    "filter.evidence": {"en": "evidence", "zh": "本地证据"},

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
    "empty.filter_hides": {"en": "<b>nothing matches this filter</b> - {n} local copies are hidden by it. {link}",
                             "zh": "<b>没有一行过得了这个筛选</b> - 它挡住了本地 {n} 份拷贝。{link}"},

    "empty.nothing_local": {"en": "nothing local: no cards in the table and nothing under {downloads}",
                              "zh": "本地什么都没有：表里没有卡片，{downloads} 下也没有东西"},

    "link.clear_filter": {"en": "clear the filter", "zh": "清掉筛选"},

    # --- /local/<build_id> : one copy, and what the record says ------------

    # The last panel on one copy's page: the two commands that are about *this* copy -
    # asking for its bytes again, and running the tests the ledger has no record for.  The
    # heading is the panel's own name and not a sentence about the page: two buttons and
    # the command line each of them runs is all the panel holds.
    "page.correspondence.commands_title": {"en": "commands", "zh": "命令"},

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

    "page.correspondence.activities_title": {"en": "activities", "zh": "后台活动"},

    "page.correspondence.activities_sub": {"en": "whose command names this build (a text match, said so)",
                                             "zh": "命令里提到这个 build 的（纯文本匹配，明说）"},

    "col.field": {"en": "field", "zh": "字段"},

    "col.value": {"en": "value", "zh": "值"},

    "label.artifact_urls": {"en": "artifact URLs, as the API spells them",
                              "zh": "构件 URL，按 API 的写法"},

    "state.no_node_id": {"en": "no node id: this card was not registered from an API node",
                           "zh": "没有 node id：这张卡片不是从 API 的 node 登记来的"},

    "state.not_in_table": {"en": "not in the local table", "zh": "不在本地表里"},

    "empty.no_bytes": {"en": "nothing on disk under {path}", "zh": "{path} 下面什么都没有"},

    "empty.no_pull_record": {"en": "no pull recorded for this copy: the bytes (if any) got here some other way - a job preparing one artifact, an older version of this tree, or a copy made by hand. An equal build id is not evidence of anything.",
                               "zh": "这份拷贝没有拉取记录：这些字节（如果有）是别的路子来的 - 跑 job 时铺下来的一个构件、旧版本的这棵树、或者手工拷的。build id 相等不是证据。"},

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
    "remote.line_tail": {"en": "{showing} {cap}", "zh": "{showing}{cap}"},

    "remote.coverage_unknown": {"en": "the API did not say how many rows it has for this query",
                                  "zh": "API 没说这次查询一共有多少行"},

    # Three counts, said separately (`Remote.coverage()` builds the sentence with
    # `+=`, so the keys mirror its pieces - each one is a whole clause in Chinese).
    "remote.coverage_base": {"en": "the API counts {total} for this query",
                               "zh": "API 说这次查询有 {total} 行"},

    "remote.coverage_all": {"en": ", so this cap covers all of them", "zh": "，这个上限把它们全盖住了"},

    "remote.coverage_capped": {"en": ", so {n} older rows are outside the {limit}-row cap",
                                 "zh": "，所以有 {n} 行更旧的落在 {limit} 行上限之外"},

    "remote.coverage_filtered": {"en": "; {n} of the rows inside the cap are not in this table - this page's own filter, not the API",
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
    "filter.api": {"en": "api", "zh": "接口"},

    "filter.api_refused": {"en": "api={value} is not a name here and not an http(s) URL; this page reads the base it started on",
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
    "state.outside_window": {"en": "outside window (cap {limit})", "zh": "窗口外（上限 {limit}）"},

    "state.outside_window_title": {"en": "the API answered {total} rows for this query; this page read the newest {limit}, and this build is older than that",
                                     "zh": "API 为这次查询答了 {total} 行，本页读的是最新的 {limit} 行，这个 build 比那更旧"},

    "remote_detail.none": {"en": "<b>no remote counterpart</b> in the answer to <code>{query}</code>. The window is the API's only way of being asked, so this means &ldquo;not in that answer&rdquo;, not &ldquo;nowhere&rdquo;.",
                             "zh": "<b>没有远端对应物</b>：这次查询的答案里没有它（查询是 <code>{query}</code>）。API 只能按窗口问，所以这句话的意思是&ldquo;那个答案里没有&rdquo;，不是&ldquo;哪里都没有&rdquo;。"},

    "remote_detail.node_mismatch": {"en": "the record names node {record}, the API now names {api} under this build id: same id, different thing.",
                                      "zh": "记录里写的是 node {record}，API 现在把这个 build id 算在 node {api} 上：同一个 id，两样东西。"},
}
