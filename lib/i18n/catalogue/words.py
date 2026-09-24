# SPDX-License-Identifier: LGPL-2.1-or-later
"""The axes strip, the "the API did not answer" branches, and the value -> label maps.

One part of the catalogue; `lib/i18n/__init__.py` merges the parts in this
order.  The `# ---` banners below are the source's own grouping, kept as they
were written."""

PART: dict[str, dict[str, str]] = {
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

    "filter.axis_applied": {"en": "applied to the rows this page read", "zh": "在本页读到的行里筛"},

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

    # The `×` on a chip of a multi-valued axis.  The board names the value in the
    # accessible label (`remove net-next`) because a chip box holds several chips and
    # "remove" alone does not say which one a screen reader is on.
    "filter.remove": {"en": "remove {value}", "zh": "移除 {value}"},

    # The two words the multi-valued axes added (`schema.MULTI_FIELDS`).  Both are
    # labels on a control and not sentences about the page: the first names the free box
    # beside the tick boxes, which is where a value the candidate list does not carry
    # is still typeable, and the second is the `blocked` reason on a one-shot button
    # (`_one_tree`) - the class of string `worker.platform_off` already is.
    "filter.type_one": {"en": "or type one", "zh": "或自己填一个"},

    "filter.one_tree": {"en": "a one-shot command takes one tree; this filter names {trees}",
                          "zh": "一次性的命令只指一棵树；这个筛选指了 {trees}"},

    "filter.own": {"en": "this page's own filter: ", "zh": "本页自己的筛选："},

    "filter.none": {"en": "(none)", "zh": "（无）"},

    "filter.noscript": {"en": "JavaScript is off: change a value, then press apply.",
                          "zh": "JavaScript 没开：改一个值，然后按「应用」。"},

    # The window's own label.  `label.last` is the *column* "last" (the newest
    # verdict); a number box whose name is `days` reads better spelled out, and the
    # English stays the one word it always was.
    "filter.last": {"en": "last", "zh": "最近"},

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

    # The same token where the ticks are pairs: `/jobs`' run bar ticks rows of a
    # (build, test) table, and its command is `--pair <build_id>:<test>` per box
    # (`Gui._argv_of_ticked`'s `tick_word`).  A bar that said "build" over that line
    # would name the wrong thing - one tick is one pair, not every test of one build.
    "action.ticked_pair": {"en": "<each ticked (build, test) pair>",
                             "zh": "<每个勾选的 (build, test) 对>"},

    # One activity's `what` column, read off its argv (`_what_of`): a flag repeated
    # more than twice collapses to this, so "run twenty builds" is a line and not a
    # page.  Code-form on purpose in both columns - it is a flag and a count.
    "run.n_of": {"en": "{flag} ×{n}", "zh": "{flag} ×{n}"},

    # The two sentences `?test=` gets instead of silence: a value this page cannot
    # run is *reported* (`Filter.clamps`), and `kbuild` - the one value an operator
    # is most likely to try - is named for what it is.
    # Both are printed inside `_shell`'s `capped` span, which **escapes** what it is
    # given (the `api_refused` note next to them is an address a reader typed): no
    # markup here, or the reader sees `&lt;code&gt;`.
    "filter.test_refused": {"en": "test={value} is not a test this page can run; it can run: {options}",
                              "zh": "test={value} 不是本页能跑的 test；能跑的有：{options}"},

    "filter.test_is_job": {"en": "{value} is a build job (kind=kbuild), not a test; the builds it made are what index/pull/run read",
                             "zh": "{value} 是 build 的 job（kind=kbuild），不是 test；它产出的 build 才是 index/pull/run 读的东西"},

    # The activity table's bookkeeping is folded by default, as *page filter state*
    # (`04` §P8a), and this is the one line that says so and undoes it in one click.
    "runs.folded_note": {"en": "the <code>table</code> activities are folded away — {link}",
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

    "col.name": {"en": "name", "zh": "名字"},

    "col.remote": {"en": "remote", "zh": "远端"},

    "col.verdict": {"en": "verdict", "zh": "判决"},

    "col.source": {"en": "source", "zh": "谁跑的"},

    "col.detail": {"en": "detail", "zh": "细节"},

    "state.current_paren": {"en": "{value} (current)", "zh": "{value}（当前）"},

    # A three-valued cell: yes, no, and "nobody said".  The third one needs a word
    # because an empty cell reads as "the page failed to fill this in" - which is
    # what a `flag` with nothing to show must not look like.
    "state.unknown": {"en": "unknown", "zh": "不知道"},

    # A language's name is written in that language, in both columns, on purpose:
    # the switcher is the one thing a reader must be able to use *before* choosing.
    "lang.en": {"en": "English", "zh": "English"},

    "lang.zh": {"en": "中文", "zh": "中文"},

    # --- the branches that say "the API did not answer" --------------------
    #
    # Four places distinguish "nothing arrived" from "the answer was empty";
    # each one gets its own key rather than a shared tail.
    "remote.no_answer_line": {"en": "the API did not answer this query: {note} &mdash; there are no rows, and nothing is known about this window either way",
                                "zh": "API 没有应答这次查询：{note} &mdash; 一行都没有，这个窗口的情况也无从得知"},

    "worker.no_answer": {"en": "the API did not answer this query: {note}",
                           "zh": "API 没有应答这次查询：{note}"},

    "state.no_answer_remote": {"en": "the API did not answer this query: nothing is known about the remote side",
                                 "zh": "API 没有应答这次查询：远端那一侧的情况无从得知"},

    "remote_detail.no_answer": {"en": "<b>the API did not answer this query</b> ({note}), so nothing is known about this copy's remote side &mdash; neither that it is there nor that it is not.",
                                  "zh": "<b>API 没有应答这次查询</b>（{note}），所以这份拷贝的远端一侧无从得知 &mdash; 既不知道它在，也不知道它不在。"},

    # --- value -> label, one map per word list -----------------------------
    #
    # A select box shows a label and submits a *value*; the value is what
    # `Filter.accepts()`, `Records` and `Run` compare, so it is never translated
    # (`PILL_WORDS` colours it).  These keys are the label only.
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
    "evidence.label.bytes": {"en": "bytes on disk", "zh": "磁盘上有字节"},

    "evidence.label.empty": {"en": "empty", "zh": "空"},

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

    "mode.label.once": {"en": "once", "zh": "跑一次"},

    "mode.label.resident": {"en": "resident", "zh": "常驻"},

    # The trend chart's two questions, in `schema.CHART_MODES`' order.  They are **not**
    # under `mode.label.*` beside the worker's pair above, and the prefix is the point:
    # that pair is how a *worker run* is launched (one job per request, or a resident
    # process) and this one is what a *curve* counts, so one prefix over both would be
    # one name for two vocabularies - and the day a control built its key from the value
    # (`f"mode.label.{value}"`, which is how the worker's segment is written) it would
    # offer a reader `跑一次` as a way to read a chart.
    "chart.mode.cumulative": {"en": "totals", "zh": "累计"},

    "chart.mode.each": {"en": "per build", "zh": "逐项"},

    "verdict.label.pass": {"en": "pass", "zh": "通过"},

    "verdict.label.fail": {"en": "fail", "zh": "失败"},

    "verdict.label.incomplete": {"en": "incomplete", "zh": "没答复"},

    "verdict.label.error": {"en": "error", "zh": "错误"},

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
