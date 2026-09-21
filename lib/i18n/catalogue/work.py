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

    "link.tick_missing_title": {"en": "tick every card on this page that is missing one of the artifacts a test run needs; then press the button above - you will see the set before it runs",
                                  "zh": "把这一页上、缺少跑测试所需构件的卡片都勾上；然后按上面那个按钮 —— 跑之前你能先看到这一批是哪些"},

    # One row's own pull, next to its box: the same command as the bar, with one id.
    "pull.one": {"en": "pull", "zh": "拉取"},

    "pull.one_title": {"en": "python3 table.py pull --build {build}",
                         "zh": "python3 table.py pull --build {build}"},

    # A `/jobs` row whose test is not the one in force: no box, and the link that gives
    # it one.  The label is the test's own name - the shortest true word for "click to
    # run this one".
    "jobs.tick_other": {"en": "run {test}", "zh": "跑 {test}"},

    "jobs.tick_other_title": {"en": "this row's test is {test}: choose it above and every row of it gets its own tick box, in the same command",
                                "zh": "这一行的 test 是 {test}：在上面选中它，它的每一行都会有各自的勾选框，而且是同一条命令"},

    "jobs.run_sub": {"en": "one command: the test chosen above, times every ticked build",
                       "zh": "一条命令：上面选的那个 test，乘以每一个勾上的 build"},

    "state.already_whole": {"en": "already whole", "zh": "已经完整"},

    "btn.pull_selected": {"en": "pull the selected", "zh": "拉取勾选的"},

    "pull.pull_hint": {"en": "takes only what is missing or not whole, and records an act for every artifact either way; rows without a card cannot be ticked, because that command reads the local table",
                         "zh": "只拿缺的、或者不完整的，而且不管拿没拿，每个构件都记一条 act；没有卡片的行勾不了，因为那条命令读的是本地表"},

    "col.on_disk": {"en": "on disk", "zh": "磁盘上"},

    "col.would_fetch": {"en": "would fetch", "zh": "会拉什么"},

    "col.record_now": {"en": "the record now", "zh": "现在的记录"},

    # --- /jobs : the gap, one row per (build, test) -------------------------

    "filter.ran": {"en": "ran", "zh": "跑过"},

    "filter.verdict": {"en": "verdict", "zh": "判决"},

    "col.needs": {"en": "needs", "zh": "需要"},

    "col.ready": {"en": "ready?", "zh": "能跑?"},

    "label.runs": {"en": "runs", "zh": "跑了几次"},

    "label.last": {"en": "last", "zh": "最近"},

    "col.when": {"en": "when", "zh": "何时"},

    "col.in_gap": {"en": "in the gap?", "zh": "在缺口里？"},

    "state.ready": {"en": "ready", "zh": "能跑"},

    "state.already_recorded": {"en": "already recorded", "zh": "已经记过"},

    "empty.no_gap": {"en": "nothing to show for this filter: every (build, test) the local table can run already has a record",
                       "zh": "这个筛选下没东西可看：本地表能跑的 (build, test) 都已经有记录了"},

    "page.jobs.run_title": {"en": "run a test over several builds",
                              "zh": "一个 test 跑好几个 build"},

    "page.jobs.run_sub": {"en": "one command, so one test and any builds",
                            "zh": "一条命令，所以是一个 test 加任意几个 build"},

    "btn.run_ticked": {"en": "run the ticked builds", "zh": "跑勾选的构建"},

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
    "jobs.run_hint": {"en": "skips what the ledger already has; <code>--redo</code> runs it again",
                        "zh": "账本里已经有的跳过；要重跑就加 <code>--redo</code>"},

    "jobs.skips_badge": {"en": "skips recorded", "zh": "已记过的跳过"},

    "page.jobs.day_title": {"en": "run a day", "zh": "按天跑"},

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

    "col.claimed": {"en": "claimed", "zh": "领过?"},

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

    "page.worker.state_title": {"en": "its own state file", "zh": "它自己的状态文件"},

    "page.worker.state_sub": {"en": "poller.py's file, displayed and not interpreted",
                                "zh": "poller.py 的那个文件，只摆出来，不做解释"},

    "col.cursor": {"en": "cursor", "zh": "游标"},

    "col.seen": {"en": "seen", "zh": "已领单数"},

    "col.pending": {"en": "pending", "zh": "待处理"},

    "page.worker.start_title": {"en": "start it", "zh": "起 worker"},

    "page.worker.start_sub": {"en": "the exact commands, with the claim filters as select boxes",
                                "zh": "原样的命令，认领条件全用选择框"},

    "filter.mode": {"en": "mode", "zh": "模式"},

    "filter.since": {"en": "since", "zh": "起于"},

    "worker.since_cursor": {"en": "no --since", "zh": "不加 --since"},

    # The badge beside the rail, and the flag's own precedence in its tooltip:
    # `poller.start_cursor()` reads `--since` **before** the cursor in the state file,
    # so the pill is not a suggestion - it is the window this start will use, and the
    # cursor only answers when no `--since` was given.  That ordering is what makes the
    # pill able to reach a job the cursor has already walked past (a stack seeded with
    # build timestamps from days ago), which is the case the value offered comes from.
    "worker.since_badge": {"en": "outranks the cursor", "zh": "盖过状态文件里的游标"},

    "worker.since_hint": {"en": "the window opens at --since, fifteen minutes earlier than the stamp (the feed is not ordered, so it is re-scanned); it outranks the cursor in the state file, and the cursor answers only when no --since is given",
                            "zh": "窗口从 --since 开始，再往前多留十五分钟（事件流不保证顺序，所以要重扫一遍）；它盖过状态文件里的游标 —— 只有在没给 --since 时才轮到游标说话"},

    "btn.start_worker": {"en": "start the worker", "zh": "启动轮转"},

    "worker.start_hint": {"en": "<code>resident</code> drops <code>--once</code> and keeps polling (cancel it on the runs page)",
                            "zh": "<code>resident</code> 会去掉 <code>--once</code>，一直轮询下去（在运行页取消它）"},

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
    "worker.done_here": {"en": "finished in this worker", "zh": "本 worker 跑完的"},
    "worker.cursor_note": {"en": "<b>cursor is not the last claim time.</b> it moves on every poll that has any event in the window, including events already seen, so a healthy idle loop and a stuck one look the same on it. the number that means &ldquo;this loop really claimed something&rdquo; is <code>seen</code>.",
                          "zh": "<b>cursor 不是最后领单时间。</b>只要窗口里有事件它就前进，包括已经见过的，所以「健康的空闲」和「卡死了」在它上面长得一样。真正说明「这条循环领过单」的数是 <code>seen</code>。"},
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
}
