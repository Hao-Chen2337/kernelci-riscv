# SPDX-License-Identifier: LGPL-2.1-or-later
"""The pages that do the work: `/pull`, `/jobs`, `/runs`, `/worker`.

One part of the catalogue; `lib/i18n/__init__.py` merges the parts in this
order.  The `# ---` banners below are the source's own grouping, kept as they
were written."""

PART: dict[str, dict[str, str]] = {
    # --- /pull : choose, tick, pull ----------------------------------------

    # Read from *another* API, most of a page's rows are not in this machine's table,
    # so almost nothing is tickable and the page looks broken.  This says why and
    # where to go next; `{link}` is the /remote link that carries this page's window.
    "empty.nothing_pulled": {"en": "nothing has been pulled here yet: no {provenance} exists under {downloads}",
                               "zh": "这里还什么都没拉过：{downloads} 下没有 {provenance}"},

    # "no candidates are known" and "there are none" are two different answers.
    "pull.no_card_title": {"en": "not in the local table: table.py pull --build reads the table, so record this window first",
                             "zh": "不在本地表里：table.py pull --build 读的是这张表，先把这一批登记进去"},

    # Beside the box, on a row this machine holds no card for.  It is a fact about the
    # row's *card* and no longer about the box: every row is tickable, and a tick on one
    # of these is exactly what the bar's "index, then pull" is for.  What it still
    # explains is why this row has no pull of its own - pressing one could only refuse.
    "pull.no_card": {"en": "no card", "zh": "无卡片"},

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

    "link.tick_missing_title": {"en": "tick every card on this page that is missing one of the artifacts a test run needs; then press the button above - you will see the set before it runs",
                                  "zh": "把这一页上、缺少跑测试所需构件的卡片都勾上；然后按上面那个按钮 —— 跑之前你能先看到这一批是哪些"},

    # One row's own pull, next to its box: the same command as the bar, with one id.
    "pull.one": {"en": "pull", "zh": "拉取"},

    "pull.one_title": {"en": "python3 table.py pull --build {build}",
                         "zh": "python3 table.py pull --build {build}"},

    "jobs.run_sub": {"en": "one command: every ticked (build, test) pair, in the order the rows were drawn",
                       "zh": "一条命令：每一个勾上的 (build, test) 对，按行的顺序"},

    "state.already_whole": {"en": "already whole", "zh": "已经完整"},

    "btn.pull_selected": {"en": "pull the selected", "zh": "拉取勾选的"},

    # The third button of that bar, and the one that answers a ticked row with no card
    # on disk: registering the window is what gives those rows something to pull.
    "btn.index_pull": {"en": "index, then pull the selected",
                         "zh": "登记并拉取"},

    "pull.pull_hint": {"en": "takes only what is missing or not whole, and records an act for every artifact either way; a row with no card can be ticked, but pulling it while it has none fails - that command reads the local table, so index this window first, which is what the button beside this one does",
                         "zh": "只拿缺的、或者不完整的，而且不管拿没拿，每个构件都记一条 act；没有卡片的行也能勾上，但这样直接拉会失败 —— 那条命令读的是本地表，先用旁边那个「登记」把这一批登记进去"},

    "col.on_disk": {"en": "on disk", "zh": "磁盘上"},

    "col.would_fetch": {"en": "would fetch", "zh": "会拉什么"},

    "col.record_now": {"en": "the record now", "zh": "现在的记录"},

    # --- /jobs : the gap, one row per (build, test) -------------------------

    "filter.ran": {"en": "ran", "zh": "跑过"},

    "filter.verdict": {"en": "verdict", "zh": "判决"},

    "col.needs": {"en": "needs", "zh": "需要"},

    "col.ready": {"en": "ready?", "zh": "能跑?"},

    # **One question, two words, and the negative is a statement, not a question.**
    # 「能跑」 and 「跑不了」 are the two answers to 能跑?, which is the operator's own pair
    # of words (「能跑 vs 没下载资源」) and the reason the negative is a key of its own:
    # the cell used to print `filter.missing` - the *filter's* label for the axis, which
    # reads 缺什么, a question about a resource rather than a verdict about the row - in
    # the neutral `idle` tone, so a pair that can run and a pair waiting for bytes were
    # two grey-ish cells a reader had to read twice to tell apart.  The reason is not
    # repeated here: *which* artifact is missing, and which of the two ways it is missing
    # (no URL / not downloaded yet), is the 构件 column's own answer
    # (`col.artifact.no_url` / `col.artifact.no_bytes`) and the 需要 column names what
    # the test wanted in the first place.
    "state.cannot_run": {"en": "cannot run", "zh": "跑不了"},

    # What 能跑? means, in both of its answers, as the header's own tooltip: the column
    # is short and the two states it tells apart are the ones the operator opened this
    # page for, so the sentence that says where the missing pieces are named travels
    # with the heading rather than being guessed from the words.
    "col.ready_title": {"en": "can this pair be run here now? ready: every artifact this test needs is on this disk. cannot run: at least one is not - the 构件 column names it and says which of the two ways it is missing (the card has no URL for it, or it has one and the file is not here yet, which a pull fixes).",
                          "zh": "这个 (build, test) 对现在能不能在这台机器上跑。「能跑」：这个 test 要的产物全在这块盘上。「跑不了」：至少有一个不在 —— 构件那一列会点名是哪个，并说清是哪一种缺法（卡片里没有它的网址，或者有网址但文件还没到，拉一次就好）。"},

    "label.runs": {"en": "runs", "zh": "跑了几次"},

    "label.last": {"en": "last", "zh": "最近"},

    "col.when": {"en": "when", "zh": "何时"},

    # The column's two values are `state.not_run` and `state.already_recorded` - two
    # answers to *one* question, and the header asked a third one: a row in the gap
    # printed "是" under 「在缺口里？」, whose other answer was 「已经记过」, so neither
    # word answered the heading and the reader had to know `re.todo()` to use the
    # column at all (the operator's 「这个列的意思不说清楚」).  The heading now asks
    # what both words answer - still to run, or already in the ledger.
    #
    # **The first answer is 还没跑 and not 能跑.**  It was 能跑, and that word is what the
    # 能跑? column beside this one answers - so one row could print 跑不了 (this pair's
    # files are not all here) and 能跑 (this pair has no record) in two adjacent cells,
    # and the operator's 「能跑 vs 没下载资源」 is exactly that collision: on this page
    # 能跑 now means one thing, "this pair can actually be run", and the gap's own
    # question is answered in words that are about the *record* (还没跑 / 已经记过),
    # which is what this column is about (`row["gap"]` is `re.todo()`'s answer).
    "col.in_gap": {"en": "to run, or recorded?", "zh": "要跑，还是记过？"},

    "state.ready": {"en": "ready", "zh": "能跑"},

    "state.not_run": {"en": "not yet run", "zh": "还没跑"},

    "state.already_recorded": {"en": "already recorded", "zh": "已经记过"},

    # --- the 构件 column's two ways of missing an artifact -------------------
    #
    # An artifact a test needs can be absent in two states, and they ask the reader for
    # two different things: the card names no URL for it (nothing will ever fetch it -
    # no run of this pair can start from the API's answer) or it is named and not here
    # yet (a pull fixes it).  The operator asked for the difference
    # (「区分一下没有下载和没有网址」), and `Build.lacking` answers it; these are the two
    # words a reader gets, and the hint is what makes the first state actionable rather
    # than final - a file put in place by hand is used as it stands (`Build.make`).
    "col.artifact.no_url": {"en": "no URL", "zh": "没有网址"},

    "col.artifact.no_bytes": {"en": "not downloaded", "zh": "没下载"},

    "col.artifact.no_url_hint": {"en": "the card names no URL for it, so nothing will fetch it - put the file in the build's directory by hand and the run uses it as it stands",
                                  "zh": "卡片里没有它的网址，所以没人会去拉 —— 手动把文件放进这个 build 的目录里，跑的时候就直接用它"},

    # --- the 卡片 column's legend, drawn above the table that holds it --------
    #
    # The key belongs with `col.card`, `col.card_title` and the two `card.tick_*` words, and
    # those live in `local.py`; it is written here because the two marks it explains are the
    # two the 构件 column of this screen already draws (`col.artifact`), and one part of the
    # catalogue is one hand's to edit.  A page moving the legend later moves one key.
    #
    # The tooltip (`col.card_title`) was the first answer to 「卡片这里为什么要显示三个钩或者×」
    # and it is not enough: a reader who does not hover never sees it, and the operator asked
    # again this round - so this is the same fact **on the page**, above the column it is
    # about, with the two marks drawn in their own colours ({yes}/{no} are the `<span
    # class="tick">`/`<span class="cross">` the cells themselves use) rather than described.
    # It is `t()`-only and not `both()`: the two values are markup, and the swap writes text
    # (`words.both` says why the two halves would then disagree).
    "col.card_legend": {"en": "the 卡片 column's three marks are kernel, kselftest, modules, left to right: {yes} this file is on this disk, {no} it is not here. The column counts bytes on this disk, never what the card claims - a card naming three artifacts it does not hold shows three crosses. The 资源 column beside it names the same files, and config too.",
                          "zh": "卡片列从左到右三个记号是 kernel、kselftest、modules：{yes} 这个文件在这块盘上，{no} 本地没有。这一列数的是盘上的字节，不是卡片声明了什么 —— 声明了三个却一个都没拉的卡片就是三个×。旁边资源那一列把同样的文件按名字列出来，另外还多一个 config。"},

    "empty.no_gap": {"en": "nothing to show for this filter: every (build, test) the local table can run already has a record",
                       "zh": "这个筛选下没东西可看：本地表能跑的 (build, test) 都已经有记录了"},

    "page.jobs.run_title": {"en": "run a test over several builds",
                              "zh": "一个 test 跑好几个 build"},

    "page.jobs.run_sub": {"en": "one command, so one test and any builds",
                            "zh": "一条命令，所以是一个 test 加任意几个 build"},

    "btn.run_ticked": {"en": "run the ticked pairs", "zh": "跑勾选的对"},

    "jobs.gap_title": {"en": "<code>re.todo()</code> reports {cards} cards and {records} records; this page shows the pairs with no record, capped at {limit} rows",
                         "zh": "<code>re.todo()</code> 在 {cards} 张卡片和 {records} 条记录上算；这一页显示还没有记录的 pair，上限 {limit} 行"},

    # The fact this bar's note carries changed when `table.py run` started skipping:
    # it used to *document the bug* the operator reported ("这条命令连账本里已经有的
    # 也会跑"), which is `CHANGELOG.md` §4.  One rule now, two entry points
    # (`runday.py` had `--redo` first), so the note states it instead - and it is a
    # **badge with the explanation in its `title=`** (`05-i18n-prose.md` §B.2's badge
    # vocabulary), not the sentence it was: which of two behaviours a command has is
    # worth three words on screen, and the escape hatch (`--redo`) is worth the
    # tooltip.
    # …and the escape hatch is now a **button** rather than a flag the reader has to
    # know how to type: 「难道就不能默认增加重跑？」.  The sentence still names the flag,
    # because the two printed command lines under these buttons differ by exactly it -
    # but it points at the button, since that is what the reader who does not read
    # command lines has to press.
    "jobs.run_hint": {"en": "skips what the ledger already has; the re-run button beside it sends <code>--redo</code>",
                        "zh": "账本里已经有的跳过；旁边那个重跑按钮就是加 <code>--redo</code>"},

    "jobs.skips_badge": {"en": "skips recorded", "zh": "已记过的跳过"},

    "page.jobs.ledger_title": {"en": "the ledger", "zh": "账本"},

    "counts.title_records": {"en": "{n} records in {dir}", "zh": "{dir} 里 {n} 条记录"},

    "filter.days": {"en": "days", "zh": "天数"},

    # The builds bar's free-text box: the one word the board prints for it, and the only
    # axis of that bar whose label was not already in the catalogue.  What may be typed in
    # it (an id, a describe string, a path) is the box's `placeholder=`, which is a value
    # and not a word.
    "filter.text": {"en": "text", "zh": "文字"},

    "filter.builds": {"en": "builds", "zh": "build 数"},

    "btn.run_day": {"en": "run a day", "zh": "按天跑"},

    "jobs.runday_hint": {"en": "this is the command that skips the pairs the ledger already has",
                           "zh": "跳过账本里已有那些 (build, test) 的，就是这条命令"},

    "page.jobs.elsewhere_title": {"en": "elsewhere", "zh": "别处"},

    "page.jobs.elsewhere_sub": {"en": "the one-shot line, and the ledger in full",
                                  "zh": "一次性的那条命令，以及整本账本"},

    "btn.run_newest": {"en": "run the newest build once", "zh": "最新的构建跑一次"},

    "btn.ledger_full": {"en": "the ledger, in full", "zh": "完整账本"},

    "jobs.results_hint": {"en": "read-only, no API needed", "zh": "只读，不用 API"},

    # --- /runs : what is happening right now --------------------------------

    "empty.no_activity": {"en": "no activity matches this filter", "zh": "没有活动过得了这个筛选"},

    "col.age": {"en": "age", "zh": "多久了"},

    "col.exit": {"en": "exit", "zh": "退出码"},

    "col.what_run": {"en": "what", "zh": "跑了什么"},

    "word.argv": {"en": "argv", "zh": "命令行"},

    "word.id": {"en": "id", "zh": "编号"},

    "word.kind": {"en": "kind", "zh": "种类"},

    "word.state": {"en": "state", "zh": "状态"},

    "filter.name": {"en": "name", "zh": "名字"},

    "col.definition": {"en": "definition", "zh": "定义"},

    # The column that used to be `claimed`, with the question mark the operator asked
    # to have removed (「领过? 的问号去掉」).  It is a different word and not the same
    # word fixed, because the column is a different column: `claimed` asked one
    # yes/no question about the `seen` list, and the cells below answer four -
    # `local.cell.*` - because `seen` cannot tell a node this loop ran from one it
    # looked at and put down.  The header names the axis (`local`, 本机) rather than
    # any one of the four answers.
    "col.local": {"en": "local", "zh": "本机"},

    # The filter box's own label: the same axis as the column, and the same word.
    "filter.local": {"en": "local", "zh": "本机"},

    # The five values of that axis, as the box offers them.  `any` is the catalogue's
    # own `state.any` where a box needs "no condition"; these are the four answers,
    # and each is a sentence about *this machine* and not about the node's health -
    # `held` is a run whose report is still owed, and a reader who takes it for a
    # failure will go looking for a fault where there is a post office.
    "local.label.never": {"en": "never looked at", "zh": "没碰过"},
    "local.label.ran": {"en": "dealt with, nothing against it", "zh": "碰过，没记下问题"},
    "local.label.held": {"en": "ran here, report not posted", "zh": "跑了，报告没回传"},
    "local.label.refused": {"en": "put down unrun", "zh": "碰过，没跑"},

    # The cells.  Short, because they sit in a table beside seven other columns; the
    # long-form wording lives in the box above and in the tooltip.
    #
    # `ran` is deliberately **not** the word "ran".  Nothing on this disk keys a run to
    # a node id, so a node in `seen` with nothing recorded against it is "no evidence
    # either way" and not "it ran" - and the six nodes this deployment never ran are
    # exactly what a confident `ran` would have lied about.
    "local.cell.never": {"en": "never", "zh": "没碰过"},
    "local.cell.ran": {"en": "dealt with", "zh": "碰过"},
    "local.cell.held": {"en": "not posted", "zh": "没回传"},
    "local.cell.refused": {"en": "put down", "zh": "没跑"},

    "empty.queue_no_answer": {"en": "<b>the API did not answer this query</b> ({note}), so nothing is known about the queue &mdash; this is not the same as a queue that is empty",
                                "zh": "<b>API 没有应答这次查询</b>（{note}），所以队列的情况根本不知道 &mdash; 这和队列是空的不是一回事"},

    "empty.queue_empty": {"en": "<b>the API answered, and its queue holds nothing for this filter</b> (state <code>{state}</code>, name <code>{job}</code>) &mdash; an empty answer, not a missing one",
                            "zh": "<b>API 答了，它的队列在这个筛选下什么都没有</b>（state <code>{state}</code>、name <code>{job}</code>） &mdash; 空答案，不是没有"},

    # **Two APIs, one screen.**  The queue table is drawn from this page's `?api=` key and
    # its query line says so; the worker in the live panel was started with its own
    # `--api-url`, and nothing on the page said the two need not be the same base.  An
    # operator read `asked the API: https://api.kernelci.org … rows 0` beside a worker
    # that had run against the local stack as "the worker never claimed anything" - it
    # had claimed, from the other queue.  The sentence names the disagreement, and the
    # link is the way out of it: it *is* the base the worker used, and pressing it moves
    # this page's key there so the table below becomes the queue that worker claims from.
    "worker.other_api": {"en": "<b>the worker is not on this page's API</b>: it was started against {link} &mdash; the queue below is not the one it claims from",
                           "zh": "<b>这里的 worker 不在这一页的 API 上</b>：它起在 {link} 上 &mdash; 下面那张队列表不是它认领的那个"},

    # The link's own `title=`: what pressing a base does.  The sentence above cannot say
    # it without becoming prose about a control (`05-i18n-prose.md` §B.1 class 4).
    "worker.other_api_act": {"en": "read that queue here - this page's api key moves to it, and the table below becomes the queue this worker claims from",
                               "zh": "在这里看那个队列 —— 这一页的 api 键会切过去，下面的表就是这个 worker 认领的队列"},

    # The state-file panel's five keys went with the panel (`page.worker.state_title`,
    # `page.worker.state_sub`, `col.cursor`, `col.seen`, `col.refused`, `col.pending`,
    # and the two notes under it).  They are not kept "in case": a key nothing renders
    # is a sentence nobody can check, and the argument for the panel - that the counts
    # answer 「这六个到底是跑了还是没跑」 - is the argument the queue's own `local`
    # column already makes, in the place where the six are named (`_queue`).

    # The return-path panel: where a report goes and what signs it.  Placed between the
    # start bar and the queue because that is the order the question is asked in -
    # *what will this loop do* → *where does what it does go* → *what is left to do* -
    # and because it is the answer to the operator's own lost afternoon (a job ran, the
    # ledger has the row, the API says the node was never reported).
    "page.worker.return_title": {"en": "where a report goes", "zh": "报告往哪去"},

    "page.worker.return_sub": {"en": "read off one job definition and this deployment's own token, so the panel cannot disagree with what the worker will really send",
                                 "zh": "从一份 job 定义和这个部署自己的 token 读出来 —— 所以这一块跟 worker 真正会发的东西不会不一致"},

    # The empty state, and it is not decoration: the first render of this panel showed
    # four bare dashes under a subtitle that claimed a definition had been read.  A
    # queue whose nodes carry no `job_definition` artifact is a *different* answer from
    # a definition that was read and had no `callback` block, and the two looked
    # identical - which is the failure this whole page is being rewritten to stop
    # making.  Nothing was read here, and the panel says so in words.
    "worker.return_definition_none": {"en": "not read: no node in this queue carries a definition artifact",
                                      "zh": "没读：这个队列里没有节点带 definition 构件"},
    "page.worker.return_sub_empty": {"en": "the queue carried no definition to read, so only this deployment's own side of the answer is here",
                                     "zh": "队列里没有可读的定义，所以这里只有这个部署自己这一侧的答案"},

    "worker.return_definition": {"en": "definition read", "zh": "读的定义"},

    # **One row for the destination.**  It used to be two - the definition's
    # `callback.url` and *this deployment sends to* - and the reader had to work out
    # which was in force from two hints pointing at each other.  The operator asked for
    # the merge (「callback.url 和这个部署改发到这两个不能合并一下吗」), and the label
    # had to change with it: the field's own spelling named the old row's *value*, and
    # this row prints what a delivery will really use, which may be neither URL.
    "worker.return_destination": {"en": "a report goes to", "zh": "报告发到"},

    # The three states, said in words.  A box that is empty because nothing is set and a
    # box holding `off` look nothing alike, but an empty box and a *box being ignored*
    # did - which is what the old pair of hints existed to explain, and what one row
    # with one sentence per state replaces.
    "worker.return_where_definition": {"en": "this deployment has set nothing, so it is the <code>callback.url</code> inside the job definition above",
                                       "zh": "这个部署没有再指定，所以就是上面那份 job 定义里的 <code>callback.url</code>"},
    "worker.return_where_override": {"en": "<b>this deployment's own address</b>, in force instead of the definition's - the worker reads it at every delivery, including the re-post of a report that is still pending",
                                     "zh": "<b>这个部署自己指定的地址</b>，压过定义里的那个 —— worker 每次投递都重新读，包括重发还没送出去的待处理报告"},
    "worker.return_where_off": {"en": "<b>callbacks are off</b>: nothing is posted anywhere and the ledger still records every run. save an empty box to go back to the definition's <code>callback.url</code>.",
                                "zh": "<b>回调已关闭</b>：哪儿都不发，账本照记每一次运行。存一个空值就改回用定义里的 <code>callback.url</code>。"},

    # The value the row prints in that third state.  No markup: it goes through
    # `words.both`, which refuses a value carrying a tag - a swap has no `html` mode.
    "worker.return_where_off_value": {"en": "off - nothing is posted anywhere",
                                      "zh": "已关闭 —— 哪儿都不发"},

    # The box's own two strings.  `off` is in the placeholder because it is the one
    # value here a reader could not guess: the file is a URL, and "turn it off" is not.
    "worker.return_override_ph": {"en": "a URL to send them somewhere else, or off for nowhere",
                                  "zh": "填地址改发到别处，填 off 就是哪儿都不发"},

    # The answer the button prints, in the page's own words for the three outcomes.
    "worker.override.set": {"en": "now sending results to {url}", "zh": "现在把结果发到 {url}"},
    "worker.override.cleared": {"en": "override cleared: results go to the definition's callback.url again",
                                "zh": "覆盖已清除：结果重新发到定义里的 callback.url"},
    "worker.override.off": {"en": "callbacks are off: nothing will be posted anywhere",
                            "zh": "回调已关闭：哪儿都不发"},

    "worker.return_token": {"en": "token comes from", "zh": "token 从哪来"},

    # Four answers, and the fourth is the one that matters: an empty token is the
    # failure this row exists for (the callback goes out with no `Authorization`
    # header, the API answers 401, and the ledger records a run the API never heard
    # of).  Only the *source* is printed - never the value (`sink.token_source`).
    "worker.return_token.env": {"en": "<code>PULL_LABS_CALLBACK_TOKEN</code> in the environment",
                                "zh": "环境变量 <code>PULL_LABS_CALLBACK_TOKEN</code>"},
    "worker.return_token.settings": {"en": "this deployment's <code>local-callback.toml</code>",
                                     "zh": "这个部署的 <code>local-callback.toml</code>"},
    "worker.return_token.none": {"en": "<b>nowhere</b>: callbacks go out with no <code>Authorization</code> header and come back 401 while the ledger records the run",
                                 "zh": "<b>哪儿都没有</b>：回调不带 <code>Authorization</code> 头发出去，回来 401，而账本照样记下这次运行"},

    # The `token_name` row's sentence, and the reason the panel is worth reading at all:
    # the operator went looking for a token by this name.  Nothing in this tree reads
    # the field, and what is sent is `Authorization: Token <the token above>`.
    # A column header and not the field's own spelling: `callback.url` is correct on the
    # row above (that *is* the key in the definition) and looks like a symbol over a
    # table, which is the shape the gate's heading rule exists to catch.
    "col.callback": {"en": "callback url", "zh": "回调地址"},

    "worker.return_pending_lead": {"en": "reports written and not delivered - the worker re-posts these on its own, and never re-runs them:",
                                   "zh": "写好了但没回传的报告 - worker 自己会重发这些，但绝不会重跑它们："},
    "worker.return_pending_none": {"en": "nothing is waiting to be delivered.",
                                   "zh": "没有等着回传的东西。"},

    "page.worker.start_title": {"en": "start it", "zh": "起 worker"},

    "page.worker.start_sub": {"en": "the exact commands, with the claim filters as select boxes",
                                "zh": "原样的命令，认领条件全用选择框"},

    "filter.mode": {"en": "mode", "zh": "模式"},

    "filter.since": {"en": "since", "zh": "起于"},

    # **The two answers a reader actually has**, which is what this control is now built
    # from.  It used to offer "no --since" beside *the oldest `created` in this answer* -
    # a stamp that is a property of the window rather than a choice, so it moved every
    # time the reader changed anything and read as an unexplained date (「我不明白你那个
    # 起于那个有什么意义」).  "everything the queue has" and "from here on" are the two
    # things an operator picks between; a third, a date they have in mind, is the box.
    "worker.since_all": {"en": "anything", "zh": "不限"},

    # The stamp is written at the moment the page is drawn, so pressing it means "the
    # queue as it stands now, and nothing that was already in it" - which is what the
    # reader pressing it is asking for, and why it is not a fixed value in the catalogue.
    "worker.since_now": {"en": "from now on", "zh": "从现在起"},

    "worker.since_ph": {"en": "or a stamp you have in mind, 2026-09-24T05:31:49Z",
                        "zh": "或者填一个你记得的时刻，例如 2026-09-24T05:31:49Z"},

    # The badge beside the rail, and the flag's own meaning in its tooltip.  It said
    # "outranks the cursor" while `poller.start_cursor()` fell back to the state file's
    # cursor, which made the pill the only way to reach a job the cursor had already
    # walked past (a stack seeded with build timestamps from days ago).  The cursor is
    # not a floor any more - the worker asks for the whole `available` queue by default
    # - so what is left to say about the flag is that it is the *only* thing that bounds
    # the query: pressing it narrows the run, and leaving it out runs everything the
    # page is showing.
    "worker.since_badge": {"en": "the only floor", "zh": "唯一的下界"},

    "worker.since_hint": {"en": "the window opens at --since, fifteen minutes earlier than the stamp (the feed is not ordered, so it is re-scanned); left out, the worker asks for the whole available queue - which is what this page is showing you",
                            "zh": "窗口从 --since 开始，再往前多留十五分钟（事件流不保证顺序，所以要重扫一遍）；不加 --since 的话，worker 问的就是整个 available 队列 —— 也就是这一页正在显示的东西"},

    "btn.start_worker": {"en": "start the worker", "zh": "启动轮转"},

    "worker.start_hint": {"en": "<code>resident</code> drops <code>--once</code> and keeps polling (cancel it on the runs page)",
                            "zh": "<code>resident</code> 会去掉 <code>--once</code>，一直轮询下去（在运行页取消它）"},

    # What the two modes *do*, under the segment that chooses between them.  The
    # operator's own question about this page was 「once 和 resident 到底差在哪」 and the
    # page could not answer it: the segment said the two words, `start_hint` said what
    # `resident` drops, and neither said when the process ends - which is the whole
    # difference.  Both lines are drawn, not only the one in force: the question is
    # *between* the two answers, and a reader who can only see one of them at a time
    # has to flip the control to find out what they are choosing between.
    "worker.mode_note.once": {"en": "<b>once</b>: claims what is claimable now, then exits - an empty queue is a queue it leaves.",
                              "zh": "<b>跑一次</b>：把现在能领的领完就退出 &mdash; 队列是空的就空着退出。"},
    "worker.mode_note.resident": {"en": "<b>resident</b>: claims, then keeps watching the events feed - it does not exit until it is cancelled.",
                                  "zh": "<b>常驻</b>：领完之后继续盯着事件流，不取消就不退出。"},

    # The mode the *running* worker is in, on the status row.  Read off its argv
    # (`data._worker`'s `argv`, which is `Run.argv` as started), because that is what
    # the process is actually doing - the segment above is what the *next* button
    # would run, and the two are different questions.
    #
    # **Plain text, no markup.**  The word itself is a cell on the status row and the
    # sentence is that cell's `title=`, and a `title=` renders its value literally: a
    # `worker.forget.*` entry below is handed to the page script and written with
    # `textContent` for the same reason.  Markup in either would reach the reader as
    # its own characters (`words.both`'s comment says the same thing about the swap).
    "worker.mode_label": {"en": "mode", "zh": "模式"},
    "worker.mode_running": {"en": "--once is not in this worker's argv, so it is resident and will not exit on its own",
                            "zh": "这个 worker 的 argv 里没有 --once，所以它是常驻的，不会自己退出"},
    "worker.mode_once": {"en": "--once is in this worker's argv: it exits when the queue is empty",
                         "zh": "这个 worker 的 argv 里有 --once：队列空了它就退出"},

    # The queue's forget button.  `seen` is forever by design (`_drain` skips a seen id
    # before `handle` is reached), so without this the only way to undo a decision that
    # turned out to be wrong is to hand-edit `var/state/worker-state.json` - which is
    # exactly what the operator was doing.
    #
    # The four `worker.forget.*` sentences are the *answer* to the press and travel to
    # the page as JSON (`ActionsMixin.forget`), which the script writes with
    # `textContent` - so these are plain text like the two above, and none of them may
    # grow a tag.  Four of them and not one: "the worker holds the file", "the file is
    # not JSON", "nothing remembered it" and "done" are four different things to do
    # next, and a button that said "failed" for all four would be the same silence this
    # page has been complaining about all along.
    "btn.forget": {"en": "pick up again", "zh": "重新捡起来"},
    "col.forget": {"en": "again?", "zh": "重捡"},
    "worker.forget_hint": {"en": "takes this node id back out of seen, so the next poll reads it again; the refusal goes with it, a report that was written and not delivered does not",
                           "zh": "把这个节点 id 从 seen 里拿出来，下次轮询会重新看它；拒绝记录一起删，已经写好但没回传的报告不删"},
    # The same button on a `ran` row, where the page is offering to undo a decision it
    # cannot read.  Two outcomes, and the reader is the only one who can tell them
    # apart: the loop may never have run this node, or it may have run it and the
    # record of that run is what the new one would replace.
    "worker.forget_warn": {"en": "this node is in seen with nothing recorded against it, so this page cannot tell whether the loop ran it; picking it up again re-reads it, and if it did run, that record is what the new run replaces",
                           "zh": "这个节点在 seen 里、没有任何记录，所以这一页分不出它到底跑没跑；重新捡起来会再看它一次；如果它真跑过，新的一次会顶掉原来那条记录"},
    "worker.forget.done": {"en": "{node_id} is out of seen: the next poll will look at it again",
                           "zh": "{node_id} 已经从 seen 里拿出来了：下次轮询会重新看它"},
    "worker.forget.absent": {"en": "{node_id} was not in seen; nothing to undo",
                            "zh": "{node_id} 本来就不在 seen 里，没什么可撤销的"},
    "worker.forget.locked": {"en": "a worker holds the state file right now; stop it first, or the next flush will put {node_id} back",
                             "zh": "现在有 worker 占着状态文件；先把它停掉，否则下一次 flush 会把 {node_id} 写回去"},
    "worker.forget.unreadable": {"en": "the state file is not readable JSON; fix it by hand rather than letting a button rewrite it",
                                 "zh": "状态文件不是能读的 JSON；请手工处理，不要让一个按钮重写它"},

    # The poll loop's own words, moved in from the prototype's word store
    # (`proto/words.py`), which is keyed like this catalogue on purpose - the board
    # draws these sentences and the tree had no equivalent for four of them.
    # `cursor_note` and `where_results` carry markup, so they are `t()`-only:
    # `words.both()` refuses a value with a tag in it, because the swap writes
    # `textContent` and a tag would reach the reader as its own characters.
    "worker.pid": {"en": "process", "zh": "进程"},
    "worker.since": {"en": "started", "zh": "起于"},
    "worker.uptime": {"en": "uptime", "zh": "已经跑了"},
    "worker.queue": {"en": "the queue on the API", "zh": "接口上的队列"},
    # The route sentence.  It is here because the table cannot say it: every row is a
    # `job` node, so nothing in the table is a build, and a reader who wants to know
    # where the build went has only the `route` column's middle name to go on.  The
    # panel says the shape out loud - checkout, then the build, then the job - and says
    # the one consequence that matters before a button is pressed: the build step is
    # not in this queue and this worker will never claim it.
    "worker.queue_sub": {
        "en": "every row is a <code>job</code> node: the build step (<code>kbuild</code>) "
              "runs upstream, and each row's <b>route</b> names the build it was dispatched for",
        "zh": "每一行都是 <code>job</code> 节点：构建那一步（<code>kbuild</code>）在上游跑，"
              "每行的<b>路线</b>里写着它是为哪个构件派发的"},
    # A placeholder, so it holds field names rather than a sentence: the four things
    # `activities.job_node_rows` really matches, in its own order.
    "worker.text_hint": {"en": "name, node id, state, result", "zh": "名字、节点 id、状态、结果"},
    # The ledger rows below are the records whose **last writer was this worker**, which
    # is a narrower and a stranger thing than "this worker ran it": one `(build, test)`
    # has exactly one record file and every run of that pair overwrites it, so a pair
    # this worker ran an hour ago and the next loop re-ran is one row here and names the
    # second run.  The old wording promised a history the ledger cannot hold - the count
    # is the same either way, and only the reader's expectation changes.
    "worker.done_here": {"en": "last written by this worker (one file per (build, test))",
                         "zh": "账本里最后写者是 worker 的（一个 (build, test) 只有一个文件）"},
    # The three keys that used to sit here - `worker.cursor_age`, `worker.cursor_note`
    # and `worker.refused_note` - went with the state-file panel.  Every one of them was
    # a footnote on a number that panel printed, and the panel is the thing the operator
    # asked to stop showing; keeping the footnotes would be keeping the explanation of a
    # table that is no longer drawn.
    "worker.where_results": {"en": "results land in <a href=\"/jobs\">jobs</a> (the worker rows) and in the panel below", "zh": "跑完的结果在 <a href=\"/jobs\">测试</a>（worker 那几行）和下面那一块"},

    "state.any": {"en": "any", "zh": "不限"},

    "state.any_paren": {"en": "(any)", "zh": "（不限）"},

    # --- what the filter bar and the job tables needed ----------------------
    #
    # `btn.more` is the `<summary>` of the board's second filter row: the boxes a
    # reader needs rarely (`origin`, `evidence`, `days`, `rows`, `text`) live behind
    # one fold, so the bar that is read every time is the short one.
    "btn.more": {"en": "more filters", "zh": "更多筛选"},

    # How long a finished job took, on the tables that print a record's own
    # duration.  The board draws it (`took` / 耗时); no existing key said it -
    # `col.age` is how long ago, which is a different number.
    "col.took": {"en": "took", "zh": "耗时"},

    # The empty answer of a table that no filter emptied: the generic case, for a
    # page that has nothing more specific to say about why there is nothing here.
    "empty.no_rows": {"en": "no row matches this question", "zh": "这个问题没有符合的行"},

    # --- the smart run ------------------------------------------------------
    #
    # One press over `/builds`' ticked rows, and the four decisions it can take.  A
    # press starts **one** command (`lib/run.py`), so it takes the earliest step any
    # ticked row needs - register and pull the window, pull the bytes, or run the
    # tests - and the answer it prints names every ticked row and what this press does
    # for it.  A row it does not touch is in that answer with the reason, never
    # dropped: a silent skip is the failure this page already makes elsewhere.
    #
    # None of these carries `(s)` (`accept.py`'s W3 check) or a tag (`script.py` writes
    # the note with `textContent`, so markup here would be printed as characters).
    "btn.smart_run": {"en": "smart run", "zh": "智能运行"},

    "smart.hint": {"en": "one press over the ticked rows, taking the earliest step any of them needs: a row with no card in the local table is registered and pulled, a carded row with nothing on disk is pulled, and a row that is on disk is run (table.py skips the pairs the ledger already holds). The answer names every ticked row and what this press does, or does not do, for it.",
                     "zh": "对勾选的行按一次，做它们里最早需要做的那一步：本地表里没有卡片的行先登记再拉取，有卡片但磁盘上没有产物的行拉取，磁盘上有产物的行开跑（table.py 会跳过账本里已经有的对）。结果逐行点名，说明这一按为它做了什么、没做什么。"},

    # The button beside it, and the whole of what separates them.  It is the same
    # press - the same three steps, the same answer - so the sentence has to name the
    # difference and only the difference: the ledger is not consulted, and the rows
    # that still need their card or their bytes still get them first, because running
    # a pair whose artifact is not on disk is not a press that could work.
    "smart.rerun_hint": {"en": "the same press with the ledger ignored: whatever step it decides to take is taken the same way, and when it runs, every pair of the ticked builds runs again - the ones the ledger already holds included. A row that still needs its card or its bytes gets those first, exactly as above.",
                           "zh": "同一按，只是不看账本：该走哪一步还是哪一步，而一旦开跑，勾选的 build 的每一对都再跑一次 —— 账本里记过的也跑。还缺卡片或字节的行照样先把那一步做完，跟上面一样。"},

    "smart.plan_register": {"en": "this press registers this window and pulls the {n} of {total} ticked builds that need bytes",
                              "zh": "这一按先登记这个窗口，再拉取 {total} 个勾选的 build 里需要字节的 {n} 个"},

    "smart.plan_pull": {"en": "this press pulls the {n} of {total} ticked builds with nothing on disk",
                          "zh": "这一按拉取 {total} 个勾选的 build 里磁盘上什么都没有的 {n} 个"},

    "smart.plan_run": {"en": "this press runs the {n} of {total} ticked builds; table.py skips the pairs the ledger already holds",
                         "zh": "这一按跑 {total} 个勾选的 build 里的 {n} 个；账本里已经有的对 table.py 会跳过"},

    # The same sentence with the ledger taken out of it - the re-run button's press.
    # It is a key of its own rather than a flag on the one above because the two say
    # *opposite* things about the same count, and a reader who ticked ten rows has to
    # be able to tell from the answer whether ten pairs are about to run or none.
    "smart.plan_rerun": {"en": "this press re-runs the {n} of {total} ticked builds; the ledger is not consulted, so every pair of each of them runs again",
                           "zh": "这一按重跑 {total} 个勾选的 build 里的 {n} 个；不看账本，每一个的每一对都再跑一次"},

    "smart.will_register": {"en": "no card in the local table, registering and pulling it now",
                              "zh": "本地表里没有卡片，现在登记并拉取它"},

    "smart.will_pull": {"en": "carded, nothing on disk, pulling it now",
                          "zh": "有卡片，磁盘上没有，现在拉取它"},

    "smart.pull_failed": {"en": "carded, nothing on disk, and the last pull failed - pulling it again",
                            "zh": "有卡片，磁盘上没有，上次拉取失败了 —— 再拉一次"},

    "smart.will_run": {"en": "carded and on disk, running it now (the ledger decides what still has to run)",
                         "zh": "有卡片、磁盘上有，现在开跑（还该跑什么由账本决定）"},

    # …and the row clause for a redo press, which is the one place "the ledger decides"
    # was a promise this console would have broken by sending `--redo`.
    "smart.will_rerun": {"en": "carded and on disk, re-running it now (the ledger is not consulted)",
                           "zh": "有卡片、磁盘上有，现在重跑（不看账本）"},

    "smart.waits_run": {"en": "carded and on disk, not run by this press - the step it needs comes first",
                          "zh": "有卡片、磁盘上有，这一按不跑它 —— 它要的那一步在前面"},

    # The id of the activity this press started, at the end of the account: the note
    # takes the place of the script's own `started {id}` line (`script.py` prints the
    # note instead), and a reader who wants the log still needs the id to find it.
    "smart.activity": {"en": "activity {id}", "zh": "活动 {id}"},
}
