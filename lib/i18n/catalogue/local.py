# SPDX-License-Identifier: LGPL-2.1-or-later
"""`/local` and `/local/<build_id>`: what we hold, and what the record says.

One part of the catalogue; `lib/i18n/__init__.py` merges the parts in this
order.  The `# ---` banners below are the source's own grouping, kept as they
were written."""

PART: dict[str, dict[str, str]] = {
    # --- /local : what we hold ---------------------------------------------

    "col.card": {"en": "card", "zh": "卡片"},

    # The 卡片 column asked its own question - 「卡片这里为什么要显示三个钩或者×」 - and the
    # answer was only in the cells' markup, where the artifact's name was shadowed by the
    # state drawn over it.  One key for the column and one per mark (`card.tick_*`) is
    # where a fact about a cell lives in this design.
    "col.card_title": {"en": "one mark per artifact of the card (kernel, kselftest, modules): a tick is that file on this disk, a cross is not here. The column is about the bytes, never about what the card claims - a card naming three artifacts it does not hold shows three crosses. Hover a mark for its name; hover the group for what the record says about this copy.",
                         "zh": "卡片声明的每个产物一个记号（kernel、kselftest、modules）：钩是这个文件在本地磁盘上，×是本地没有。这一列说的是字节，不是卡片声明了什么——声明了三个却一个都没拉下来的卡片，就是三个×。悬停某个记号看它是哪个产物，悬停整组看记录说这份拷贝处在哪个状态。"},

    "card.tick_here": {"en": "{name}: this file is on this disk",
                         "zh": "{name}：这个文件在本地磁盘上"},

    "card.tick_absent": {"en": "{name}: this file is not here",
                           "zh": "{name}：本地没有这个文件"},

    "col.act": {"en": "act", "zh": "act"},

    "col.api_says": {"en": "api says", "zh": "接口说"},

    "col.tick": {"en": "tick", "zh": "勾选"},

    "col.registered": {"en": "registered", "zh": "登记"},

    "filter.evidence": {"en": "evidence", "zh": "本地证据"},

    # **What each of the six means, because the box is the one place the page cannot say
    # it.**  `filter.evidence`'s values are `Local.state`'s five words plus `bytes`, and a
    # reader who has to choose among 拉取过/未记录/已登记/本地自产/空/磁盘上有字节 has to
    # know that the first four are statements about the *record*, the fifth is about the
    # *card*, and the sixth asks the disk alone.  `accept.py`'s S7 is the same fact read
    # back: `?evidence=bytes` is a superset of 本地, because bytes are not a record.
    "filter.evidence_title": {"en": "which of the five things this machine knows about a copy the row must be. pulled: a pull act names it. unrecorded: it was pulled and the act was not kept - a copy in the tree with no record of how it got there. registered: a card in the local table covers it. made-here: this machine published it, so no API will ever answer for it. empty: a directory with nothing in it. bytes on disk is not a state: it asks the disk alone and ignores the record, which is why it is the widest of the six.",
                               "zh": "这一行必须是本地对这份拷贝的哪一种说法。拉取过：有拉取动作点了它的名。未记录：拉下来了但动作没留档——树里有这份拷贝，却没有它是怎么来的记录。已登记：本地表里有一张卡片盖住它。本地自产：这台机器自己发布的，接口永远不会为它作答。空：目录在，里面什么都没有。磁盘上有字节不是状态：它只问磁盘，不看记录，所以是六个里最宽的一个。"},

    "filter.origin": {"en": "origin", "zh": "来源"},

    # The 来源 axis, in the reader's terms.  It is two sides - 本地 and 远端 - and ticking
    # both is "either"; 有卡片 and 两个都要 are not among them (`builds._origin_boxes` says
    # why each one went), so this is where a reader who knew the old box learns where
    # those two answers went.
    "filter.origin_title": {"en": "which side of the union this row must come from. local: this machine holds something for it - a card, bytes, or both. remote: the API this page is reading answered for it. Tick both for either. A card is narrower than local and has no box of its own: the 卡片 preset above and the 已登记 chip both ask for it, and when either is in force the note beside these boxes says so.",
                             "zh": "这一行必须来自并集的哪一边。本地：这台机器有它的东西——卡片、字节，或两者都有。远端：这个页面正在读的接口为它作了答。两个都钩就是两边都要。有卡片比本地窄，没有自己的钩选框：上面的卡片预设和已登记那枚数字链接要的都是它，哪一个在生效，框旁边那句话就说。"},

    "origin.card_only": {"en": "only rows with a card in the local table",
                           "zh": "只取本地表里有卡片的行"},

    "filter.missing": {"en": "missing", "zh": "缺什么"},

    "col.bytes_on_disk": {"en": "bytes on disk", "zh": "磁盘上的字节"},

    "col.correspondence": {"en": "correspondence (the recorded facts)", "zh": "对应（记录下来的事实）"},

    "btn.publish_image": {"en": "publish var/serve/Image as a build",
                            "zh": "把 var/serve/Image 发布成一个 build"},

    "local.image_state": {"en": "{path} is there", "zh": "{path} 在"},

    # The provision panel's sixth box: an artifact's address, when the thing being
    # published is one this workspace is not serving itself.  It is a label and not a
    # path - the value is a URL the reader pastes, and `forms._parameter_url` is the one
    # judge of whether it can reach a command line.
    "word.kernel_url": {"en": "kernel url", "zh": "内核地址"},

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

    # The last panel on one copy's page: the three commands that are about *this* copy -
    # asking for its bytes again, running the tests the ledger has no record for, and
    # running them again whatever the ledger says.  The heading is the panel's own name
    # and not a sentence about the page: three buttons and the command line each of them
    # runs is all the panel holds.
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

    # The third button, and the two labels are the whole of what tells it from the one
    # beside it: both run the same pairs through the same command, and only `--redo`
    # separates them (`table.py --redo`).  A reader comparing the two printed command
    # lines can see the flag, and a reader who does not read command lines has to be
    # able to see it in the labels - 「跑还没跑的」 and 「重跑」 are one word apart, which
    # is exactly why the hint under the second one exists.
    "btn.run_redo": {"en": "re-run (even the recorded ones)",
                       "zh": "重跑（账本里记过的也再跑一次）"},

    "correspondence.pull_hint": {"en": "a pull appends an act to the record above",
                                   "zh": "一次拉取会往上边那条记录里追加一条 act"},

    # What separates this button from the one beside it, said where the button is: the
    # reader's own worry is that "re-run" and "run the pending tests" might be the same
    # press, and the answer is the ledger - one of them reads it and one of them does
    # not, and a re-run leaves a second record rather than replacing anything.
    "correspondence.redo_hint": {"en": "a re-run ignores the ledger: the pair runs again whatever it says, and the record it leaves is appended to the pair's history while the surviving record becomes the newest one. The button beside it skips whatever the ledger already has.",
                                   "zh": "重跑不看账本：这一对不管账本怎么记都会再跑一次，回来留下的记录追加到这一对的历史里，账本保留的那条变成最新的。旁边那个按钮跳过账本里已经有的。"},

    # --- the run history's own two sentences, added with the history --------
    #
    # `page.history.kept` / `overwritten` / `unrecorded` are `record.py`'s: they were
    # written when the ledger held one record per pair and a run's record was either
    # the surviving one or gone.  These two are what changed when the ledger started
    # keeping the runs it replaced.  `in_history` replaces `overwritten` for every row
    # whose record the history still holds - the three cells above it are filled from
    # that record, so "a later run overwrote it" would be a sentence about a loss the
    # reader can see has not happened - and `overwritten` is left for the rows where it
    # is still literally true: a record the ledger wrote before this tree kept
    # histories, or one whose history file is gone.
    "page.history.in_history": {"en": "its record is in the pair's history, but it is not the newest one",
                                  "zh": "它的记录在这一对的历史里，只是不是最新的那条"},

    # A history holds runs `var/logs/` no longer does: the consoles are pruned and the
    # ledger is not.  A count, because the rows are the answer to "how often did this
    # run" and a reader who is looking at five of them has to be told how many are not
    # there; a line and not a row, because a record with no console has no link and no
    # start stamp for the two columns beside it.
    "page.history.records_no_console": {"en": "the pair's history holds {n} more run(s) whose console is not in {dir} - a record outlives the log it names. The count above is the consoles there are, not the runs there have been.",
                                          "zh": "这一对的历史里还有 {n} 次运行的记录，它们的控制台已经不在 {dir} 里了 —— 记录比它点名的日志活得久。上面数是还在的控制台，不是跑过的次数。"},

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

    # --- /builds' three per-build facts -------------------------------------
    #
    # 来源, 卡片 and 资源, one column each.  Two of the three are about **this disk**
    # (the local table, the download tree) and the page has to say which "local" it
    # means, because the console's own API is local too: 本地 is `var/state/builds.json`
    # and `var/downloads/`, and 本地 API is the service on :8001.  One of these strings
    # names a host, and the words around it are what keeps the two apart - a header
    # alone would leave them to be guessed at.
    #
    # All five reach a `title=` (and no tag and no `&mdash;` here): `words.attr` writes
    # them into the attribute and the swap moves the attribute, so a tag would be read
    # as those characters.
    "col.provenance": {"en": "provenance", "zh": "出处"},

    "col.provenance_title": {"en": "where the bytes came from, read off the newest pull act's URLs: made here (a file:// artifact - this machine's own var/serve), local API (a host on this machine's own network: the stack's artifact server, or the console's own API on :8001), or an official pull (any other host). The card is not read: Build.merge() heals a card's URL, so the act is the only record of where the bytes really came from. 本地 here is the disk and the ledger; 本地 API is the service on :8001 - not the same thing.",
                              "zh": "这些字节从哪来，读的是最近一次拉取 act 里的 URL：手工建（file:// 的产物 —— 本机自己的 var/serve）、本地 API 生成（本机自己网络上的主机：本地栈的产物服务，或者 :8001 上控制台自己的 API）、官方拉取（其他任何主机）。这里不读卡片：Build.merge() 会补好卡片里的 URL，只有 act 记着字节真正从哪来。这里的「本地」指这块盘和账本；「本地 API」指 :8001 上的服务 —— 不是一回事。"},

    # `models.COPY_ORIGINS`' three values, in the words the plan gives them.  The fourth
    # case - a copy no act describes - is the dash the cell draws and has no word
    # here on purpose: "nothing recorded" is not a place the bytes came from.
    "source.made_here": {"en": "made by hand", "zh": "手工建"},

    "source.local_api": {"en": "local API", "zh": "本地 API 生成"},

    "source.official": {"en": "official pull", "zh": "官方拉取"},

    "col.in_table": {"en": "card in table", "zh": "表里的卡片"},

    "col.in_table_title": {"en": "is there a card for this build in the local table (var/state/builds.json on this disk)? yes / no. This is the 本地 side - the disk and the ledger - and it says nothing about the API: a build the API answers and the table has no card for is exactly the row a pull cannot work on yet.",
                             "zh": "这个 build 在本地表（这块盘上的 var/state/builds.json）里有卡片吗？有 / 没有。这是「本地」那一侧 —— 盘和账本 —— 跟 :8001 上的接口无关：接口答了、表里却没有卡片的那种行，正是现在还拉不动的行。"},

    "col.resource": {"en": "resource", "zh": "资源"},

    # The list is `Build.present()` widened by one: `config` is answered by
    # `Build.artifact_path()`, which reads this build's own copy **or** the shared
    # `var/configs/` cache the drift analysis fills.  Both are the same bytes from the
    # same URL, and a column that said "no config" about a build `/analysis` will happily
    # diff would be the page disagreeing with itself - the reason the widening is here
    # and the sentence has to say so.
    "col.resource_title": {"en": "what is on disk here right now, artifact by artifact: Build.present() (one os.path.isfile each) for the three a test needs, and for config either this build's own copy or the shared var/configs cache the drift analysis fills (Build.artifact_path) - both are the same bytes from the same URL. A row with nothing on disk says no; the files' paths are the cell's own tooltip. 本地 here is the download tree on this disk, plus that one shared cache.",
                             "zh": "这块盘上现在有什么，逐个数产物：三种测试要用的按 Build.present()（每个一次 os.path.isfile），config 则看这个 build 自己的副本或者配置漂移分析填的公共 var/configs 缓存（Build.artifact_path）—— 两边是同一个 URL 的同一份字节。磁盘上什么都没有的行直接说没有；文件的路径在单元格自己的提示里。这里的「本地」指这块盘上的下载目录，外加那一个公共缓存。"},

    # 有/没有 and not `state.yes`/`state.no`'s 是/否: these answer "is there one",
    # and the plan's own two words are what the two columns beside the ticks read
    # as.  One pair, two columns - the headers are what tell the two apart.
    "state.has": {"en": "yes", "zh": "有"},

    "state.has_not": {"en": "no", "zh": "没有"},
}
