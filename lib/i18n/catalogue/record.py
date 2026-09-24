# SPDX-License-Identifier: LGPL-2.1-or-later
"""The record's own words: code-form words, states, buttons, the live panel, refusals.

One part of the catalogue; `lib/i18n/__init__.py` merges the parts in this
order.  The `# ---` banners below are the source's own grouping, kept as they
were written."""

PART: dict[str, dict[str, str]] = {
    # --- the sentences Local.state_text() builds ----------------------------

    "evidence.pulled_text": {"en": "pulled {n} artifacts from {hosts} ({size}) at {at} - {moved} transferred, {whole} already whole",
                               "zh": "从 {hosts} 拉了 {n} 个构件（{size}），时间 {at} - 传输了 {moved} 个，{whole} 个本来就在"},

    "evidence.failed": {"en": "{said}; that attempt failed: {error}",
                          "zh": "{said}；那次拉取失败了：{error}"},

    "evidence.unrecorded_text": {"en": "no pull recorded for these bytes ({where})",
                                   "zh": "这些字节没有拉取记录（{where}）"},

    "evidence.card_in_table": {"en": "a card in the local table", "zh": "本地表里有卡片"},

    "evidence.registered_text": {"en": "registered from the API node {node}, nothing pulled yet",
                                   "zh": "从 API 的 node {node} 登记来的，还没拉过"},

    "evidence.made_here_text": {"en": "made here (published locally): no pull, and no node id to tie it to",
                                  "zh": "本地造的（本地发布的）：没有拉取，也没有 node id 可以对应"},

    "evidence.empty_text": {"en": "nothing on disk and no card", "zh": "磁盘上没有东西，也没有卡片"},

    # --- what each state of the record means -------------------------------


    # --- buttons and links the rendering helpers draw -----------------------

    "btn.apply": {"en": "apply", "zh": "应用"},

    # The filter bar's other end: the link back to the page with nothing asked of
    # it.  `btn.apply` submits the bar and this one empties it, and the two are the
    # pair every bar on every screen carries (the design board draws them at the
    # right of the bar, past the `grow`).
    "btn.reset": {"en": "start over", "zh": "重新开始"},

    "btn.clear": {"en": "clear", "zh": "清除"},

    "btn.refresh": {"en": "refresh", "zh": "刷新"},

    "btn.run": {"en": "run", "zh": "跑"},

    "btn.record_window": {"en": "record this window in the local table", "zh": "把这次窗口登记进本地表"},

    "link.log": {"en": "log", "zh": "日志"},

    # The select-all in a tick column's header.  `{n}` is how many boxes this page
    # drew, because that is exactly what the box ticks: `table.py`'s commands read
    # the ids a form posts, and a control that claimed to tick rows the page did not
    # draw would be promising a command nobody wrote.
    "tick.all": {"en": "tick the {n} on this page", "zh": "勾选本页 {n} 行"},

    "tick.all_title": {"en": "ticks every box this page drew - only those; the filter may have matched more rows than the cap printed, so raise rows to widen it",
                         "zh": "只勾这一页画出来的框；筛选匹配的行可能比上限印出来的多，要更多就把「行数」调大"},

    # `/runs/<id>/log` is the log as a page: two lines of header, then the file.
    # "Open it yourself" (`我要的是类似自己打开那种`) needs the activity to be named in
    # the tab, and an activity with no output yet to say so rather than serve nothing.
    "log.head": {"en": "activity {run} - state {state}, exit {exit_code}",
                   "zh": "活动 {run} — 状态 {state}，退出 {exit_code}"},

    # The one door out of that page.  It opens in a tab of its own, so the browser's
    # own Back button does not lead where the reader came from - the page has to say
    # it.  Where it goes is this page's `?back=` (the filter it was opened from), and
    # it is drawn only when that key is there: a log someone opened by typing its
    # address gets no link, because there is no page to go back to.
    "log.back": {"en": "back to the list", "zh": "回到列表"},

    "log.empty": {"en": "this activity has written nothing to its log yet",
                    "zh": "这个活动还没往日志里写任何东西"},

    # The board's own footer on an inline log row: the box shows what the page has,
    # and the whole file is one link away.  Everything the console prints as a log is
    # a *tail* - the box is a window on a file that keeps growing.
    "log.tail": {"en": "this is the tail; the whole file is at", "zh": "这是尾部，整个文件在"},

    # The refresh control and the age of what this page last read (`gui._refresh`).
    # A unit beside a number and a `title=` - never a sentence: an API answer may be
    # reused for a few seconds, and a page that hid that would be pretending it had
    # just asked (`docs/gui-rework/01-perf.md` §D2, `05-i18n-prose.md` §B.1).
    "refresh.now": {"en": "read now", "zh": "刚刚读到"},

    "refresh.age": {"en": "read {age} ago", "zh": "{age} 前读到"},

    "refresh.title": {"en": "read the files and ask the API again; an answer already read is reused for up to {ttl}",
                        "zh": "重新读文件并再问一次 API；已经读到的答案最多复用 {ttl}"},

    "js.cancel": {"en": "cancel", "zh": "取消"},

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

    "live.noscript": {"en": "JavaScript is off: this list is from when the page was drawn",
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

    "notice.gone": {"en": "{kind} {id} is no longer on disk", "zh": "{kind} {id} 已经不在磁盘上了"},

    "notice.dismiss": {"en": "dismiss", "zh": "知道了"},

    # --- how an activity ended, in the exit code's own words ---------------
    #
    # `Run._settle` (`lib/run.py`) maps exit 1 (a test failed) and exit 3 (infrastructure
    # - LAVA's *incomplete*) onto the one state `failed`, and that is right for the
    # *activity*: the process failed either way.  It is not what happened to the tests,
    # and a pill that printed the state called a run which finished every test it
    # started and failed some of them "failed" - the same word it prints for a command
    # that crashed.  These two words are what `errors.EXIT_TEST_FAIL` / `EXIT_INFRA`
    # mean to a reader; `done` for exit 0 and the state's own word for anything else
    # are the existing `run_state.label.*`.
    "run_end.tests_failed": {"en": "tests failed", "zh": "有测试失败"},

    "run_end.infra": {"en": "incomplete (infra)", "zh": "没跑完（基础设施）"},

    # The tally beside the pill: the ledger's counts for the builds an activity's argv
    # names, one count and its word at a time, joined by the caller.  The word is
    # `verdict.label.*` - one vocabulary for a verdict, not two.
    "run_end.tally_one": {"en": "{n} {word}", "zh": "{n} {word}"},

    # --- one pair's run history (`builds._run_history_panel`) ----------------
    #
    # A (build, test) pair can be run as many times as a reader likes and the ledger's
    # *current* record for it is ONE: `var/results/<build>/<test>.json` is one file that
    # every run rewrites, so that file alone cannot answer "how often".  Two things can:
    # `var/logs/`, one console per run, and - since re-running became a button
    # (`btn.run_redo`) - `var/results/<build>/<test>.history.jsonl`, which `Ledger.write`
    # appends to.  These strings are the whole vocabulary of that difference, and every
    # one of them exists to keep the facts apart: the sub-line names the directory the
    # list really comes from, the rows say *why* a cell is empty instead of leaving a
    # dash that reads as "never recorded", and the four words of `col.kept`'s column
    # separate "this is the record" from "the record moved on" from "there was never
    # one" - three facts a single `—` would flatten into one.
    #
    # `page.history.title` is an `<h2>`, so it names no file, module or call
    # (`words.heading` refuses one that does).  `sub`, `empty` and `record_not_here`
    # carry a `<code>` path and are therefore `t()`-only - the swap has no html mode.
    "page.history.title": {"en": "run history", "zh": "运行历史"},

    "page.history.sub": {"en": "{test} on this build, newest first - every console in {dir}; the ledger keeps the newest record for the pair and writes each earlier one to its history file, so a run whose console is gone is still in the ledger",
                           "zh": "{test} 在这个 build 上的每一次运行，最新的在前 —— {dir} 里的每一份控制台输出；账本对这个配对留的是最新的那条记录，更早的每一条都写进它的历史文件，所以控制台已经不在的运行账本里还有"},

    # The two headers of the two columns that exist only here: which run the surviving
    # record is about, and the console file itself.  "console" and not "log" because
    # this console has a 日志 link everywhere else (`link.log`) and it points at an
    # *activity*'s log (`/runs/<id>/log`); one word for two files is how a reader ends
    # up at the wrong one.
    "page.history.col_record": {"en": "the ledger's record", "zh": "账本记录"},

    "page.history.col_log": {"en": "console", "zh": "控制台"},

    "page.history.kept": {"en": "this run is the one kept", "zh": "这次运行就是留下的那次"},

    "page.history.overwritten": {"en": "a later run overwrote its record", "zh": "后来的运行把它的记录覆盖了"},

    # The third case, and it is a real one rather than a defensive one: a run's console
    # is opened before the run starts and its record is written after it ends (`Job.run`),
    # so a run killed mid-flight leaves exactly this - a console and no record.  "A later
    # run overwrote it" would name a run that never happened, and the panel above every
    # such row would be contradicting itself.
    "page.history.unrecorded": {"en": "the ledger has no record of this run",
                                  "zh": "账本里没有这次运行的记录"},

    # Said under the table and not in a cell: no row is this run, so there is no row to
    # say it in.  It is a different fact from `overwritten` - the ledger remembers a run
    # whose console is not among these - and printing "overwritten" on every row would
    # be this panel inventing one.
    "page.history.record_not_here": {"en": "the ledger's record for this pair names a console that is not in {dir}",
                                       "zh": "账本这个配对的记录指向的控制台不在 {dir} 里"},

    "page.history.empty": {"en": "no console in {dir} for this pair", "zh": "{dir} 里没有这个配对的控制台输出"},

    "page.history.open": {"en": "the console this run printed, archived as {file}",
                            "zh": "这次运行打印的控制台，存档为 {file}"},

    # The `title=` on a verdict pill on `/`.  The pill's own text is untouched - one
    # word, one verdict, as it always was - and this is what says the pill is now a
    # door, so a reader who clicks it is not surprised by a page about one pair.
    "page.history.link_title": {"en": "every run of {test} on this build, with each run's console",
                                  "zh": "这个 build 上 {test} 的每一次运行，以及每次运行的控制台"},

    # --- a request that was refused (409/404, plain text on the wire) -------

    "error.not_an_option": {"en": "{key}={value} is not one of: {options}",
                              "zh": "{key}={value} 不在这些里面：{options}"},

    # The same refusal for an option list too long to name: the worker's `platform`
    # box offers everything `scheduler*.yaml` declares (131 names today), and
    # `_offered` prints the count of what it checked the value against instead of
    # two kilobytes of lab hardware.  `n` is that count and nothing else.
    "error.not_an_option_n": {"en": "{key}={value} is not one of the {n} options",
                                "zh": "{key}={value} 不在这 {n} 个选项里"},

    "error.not_a_name": {"en": "{key}={value} is not a name; use the select boxes",
                           "zh": "{key}={value} 不是名字；请用选择框"},

    # `--since` and not a name: a timestamp is the one argv value this page cannot
    # offer a list of, so it is judged by its shape (`forms._iso_stamp`) and the
    # refusal spells the shape out.  It is a refusal and not a repair because the
    # worker's own reader (`poller.iso_ago`) turns a stamp it cannot parse into
    # "now" - a repaired value would scan the last 15 minutes in silence, which is
    # the window the flag was passed to widen.
    "error.not_a_stamp": {"en": "{key}={value} is not a timestamp; the shape is 2026-09-20T08:20:00Z",
                            "zh": "{key}={value} 不是时间戳；形状是 2026-09-20T08:20:00Z"},

    # A value that becomes part of a command line, refused for *shape* rather than for
    # membership: `_parameter_url` is what stands between a typed address and an argv,
    # and the three things it will not pass are a scheme that is not `file`/`http`/
    # `https`, whitespace (which would end the argument early and start another one),
    # and anything that is neither an absolute URL nor a `/`-rooted path.
    "error.not_a_url": {"en": "{key}={value} is not an address; use http(s)://host/path, file:///path, or /path",
                          "zh": "{key}={value} 不是地址；请用 http(s)://host/path、file:///path 或 /path"},

    "error.two_build_ids": {"en": "two build ids are needed", "zh": "需要两个 build id"},

    "error.unknown_action": {"en": "unknown action {name}; known: {known}",
                               "zh": "不认识的动作 {name}；认识的有：{known}"},

    "error.pull_needs_build": {"en": "pull needs at least one ticked build",
                                 "zh": "拉取至少要勾一个 build"},

    # A POST body this page cannot read is a POST whose fields are all missing, and
    # a missing field silently becomes a default (`_first(form, "tree")`).  Refusing
    # is the only honest answer; the page's own script sends `URLSearchParams` and a
    # plain form sends the same encoding, so this is a hand-made request.
    "error.body_not_a_form": {"en": "a POST body of type {kind} is not a form; send application/x-www-form-urlencoded or multipart/form-data",
                                "zh": "{kind} 类型的 POST body 不是表单；请发 application/x-www-form-urlencoded 或 multipart/form-data"},

    "error.body_no_boundary": {"en": "a multipart/form-data body without a boundary names no fields",
                                 "zh": "multipart/form-data 的 body 没有 boundary，读不出任何字段"},

    # The one refusal `run` makes, and it names what a tick is: `/jobs`' boxes send
    # `<build_id>:<test>` (`jobs._tick_cell`) and `table.py run` takes them as `--pair`,
    # so "build" here would be half of what is being asked for.  `pull` above keeps its
    # own words, because a pull really does tick builds.
    "error.run_needs_build": {"en": "run needs at least one ticked (build, test) pair",
                                "zh": "跑至少要勾一个 (build, test) 对"},

    "error.drift_needs_two": {"en": "drift needs two build ids, one in each select box",
                                "zh": "drift 要两个 build id，两个选择框各一个"},

    # The smart run's own refusal.  It ticks *builds* and not pairs (its phase 3 makes
    # the pairs itself, out of `tests.DEFAULT_TESTS`), so it says "build" the way `pull`
    # above does; a press with nothing ticked cannot even be told which of the three
    # steps it is, which is why this is a refusal and not an empty answer.
    "error.smart_needs_build": {"en": "smart run needs at least one ticked build: the tick says which rows there are to decide about",
                                  "zh": "智能运行至少要勾一个 build：勾选才说明要对哪些行做决定"},

    "error.writer_busy": {"en": "{writer} is writing right now; one writer at a time - the ledger, the download tree and the table have one writer each",
                            "zh": "{writer} 现在正在写；一次只允许一个写者 - 账本、下载目录和本地表各自只有一个写者"},

    "error.no_activity": {"en": "no activity {run_id}", "zh": "没有这条活动 {run_id}"},

    # The `/worker` forget button's id check, and the same alphabet every other value
    # that reaches a command line is held to (`forms.TOKEN`): the id is not a command
    # line here, but it does become a **path segment** of the POST that carries it, so
    # it may not be anything a path can say something with.
    "error.no_node": {"en": "{node_id} is not a node id", "zh": "{node_id} 不是节点 id"},

    # The `/worker` callback box's refusal, and it names the rule rather than saying
    # "invalid": the operator typed a URL that a *token* gets POSTed to, and the two
    # ways it can be wrong (no scheme, no host) are both things the sentence can fix
    # in the reader's head before they retype it.
    "error.callback_url": {"en": "{url} is not a callback URL: it needs http:// or https:// and a host, because a report is POSTed to it",
                            "zh": "{url} 不是回调地址：要有 http:// 或 https:// 和主机名 —— 报告是要 POST 过去的"},

    "error.no_page": {"en": "no page {page}; the pages are {routes} and /local/<build_id>",
                        "zh": "没有这个页面 {page}；页面有 {routes}，以及 /local/<build_id>"},

    "error.no_local_copy": {"en": "no local copy {build_id} (see /local)",
                              "zh": "没有这份本地拷贝 {build_id}（见 /local）"},

    # One archived console, by name: `/logs/<file>` serves `var/logs/<file>` and this is
    # its 404.  A name is the reader's own words back at them (the row they clicked
    # printed it), so it is `repr()`-ed by the caller like `error.no_local_copy`'s id.
    "error.no_such_log": {"en": "no console log {name}", "zh": "没有这份控制台日志 {name}"},

    "error.no_such_action": {"en": "no such action", "zh": "没有这个动作"},

    "error.port_taken": {"en": "cannot listen on {host}:{port} ({why}); another page may already be there - choose another port with --port",
                           "zh": "监听不了 {host}:{port}（{why}）；可能已经有页面在那里了 - 用 --port 换一个端口"},
}
