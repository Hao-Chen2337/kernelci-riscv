# SPDX-License-Identifier: LGPL-2.1-or-later
"""The prototype's words, in both languages, keyed like `lib/i18n/catalogue/`.

The real console looks every sentence up in `lib/i18n`; this file is the same
shape with only the sentences the prototype uses, so moving a page into the tree
is a copy of the keys and not a rewrite of the page.

A string may carry `{placeholders}` - `str.format`'s, exactly as in
`lib/i18n/__init__.py`, so a value is interpolated the same way on both sides.
`WORDS` is the code-form vocabulary that is deliberately identical in both
columns (`build_id`, `boot`, `pass`), which keeps "same on purpose" readable.
"""

LANGS = ("en", "zh")
DEFAULT_LANG = "en"

STRINGS = {
    # -- shell ------------------------------------------------------------
    "nav.builds":     {"en": "builds", "zh": "构建"},
    "nav.jobs":       {"en": "jobs", "zh": "测试"},
    "nav.runs":       {"en": "runs", "zh": "运行"},
    "nav.worker":     {"en": "worker", "zh": "轮转"},
    "nav.analysis":   {"en": "analysis", "zh": "分析"},
    "shell.brand":    {"en": "kernelci-riscv", "zh": "kernelci-riscv"},
    "shell.theme":    {"en": "theme", "zh": "配色"},
    "shell.theme_light": {"en": "light", "zh": "浅色"},
    "shell.theme_dark":  {"en": "dark", "zh": "深色"},
    "shell.lang":     {"en": "language", "zh": "语言"},
    "shell.running":  {"en": "{n} running", "zh": "{n} 个在跑"},
    "shell.live":     {"en": "activity", "zh": "活动"},
    "shell.live_sub": {"en": "every process this console has started, newest first",
                       "zh": "这个控制台起过的每个进程，新的在前"},
    "shell.live_empty": {"en": "nothing has run today", "zh": "今天什么都没跑"},
    "shell.log":      {"en": "log", "zh": "日志"},
    "shell.cancel":   {"en": "cancel", "zh": "取消"},
    "shell.exit":     {"en": "exit {n}", "zh": "退出码 {n}"},
    "shell.exit_none": {"en": "exit code not seen", "zh": "没看到退出码"},
    "shell.read_from": {"en": "read from", "zh": "读自"},
    "shell.drawn":    {"en": "drawn", "zh": "绘制于"},
    "shell.prototype": {"en": "frontend prototype - the numbers are a fixture, no command runs",
                        "zh": "前端原型 —— 数字是样例，不会真的运行任何命令"},

    # -- the filter bar ---------------------------------------------------
    "filter.api":       {"en": "api", "zh": "接口"},
    "filter.tree":      {"en": "tree", "zh": "源码树"},
    "filter.branch":    {"en": "branch", "zh": "分支"},
    "filter.arch":      {"en": "arch", "zh": "架构"},
    "filter.defconfig": {"en": "defconfig", "zh": "配置"},
    "filter.compiler":  {"en": "compiler", "zh": "编译器"},
    "filter.run":       {"en": "run", "zh": "跑过"},
    "filter.verdict":   {"en": "verdict", "zh": "判决"},
    "filter.evidence":  {"en": "evidence", "zh": "本地证据"},
    "filter.origin":    {"en": "origin", "zh": "来源"},
    "filter.missing":   {"en": "not pulled", "zh": "没拉的"},
    "filter.has":       {"en": "has", "zh": "有"},
    "filter.days":      {"en": "days", "zh": "天数"},
    "filter.limit":     {"en": "limit", "zh": "上限"},
    "filter.text":      {"en": "text", "zh": "文字"},
    "filter.test":      {"en": "test", "zh": "测试"},
    "filter.state":     {"en": "state", "zh": "状态"},
    "filter.result":    {"en": "result", "zh": "结果"},
    "filter.kind":      {"en": "kind", "zh": "种类"},
    "filter.platform":  {"en": "platform", "zh": "平台"},
    "filter.runtime":   {"en": "runtime", "zh": "运行时"},
    "filter.job":       {"en": "job", "zh": "作业"},
    "filter.since":     {"en": "since", "zh": "起于"},
    "filter.mode":      {"en": "mode", "zh": "模式"},
    "filter.sort":      {"en": "sort", "zh": "排序"},
    "filter.delta":     {"en": "compare", "zh": "比较"},
    "filter.pick":      {"en": "pick", "zh": "挑选"},
    "filter.older":     {"en": "older end", "zh": "旧的一端"},
    "filter.newer":     {"en": "newer end", "zh": "新的一端"},
    "filter.point":     {"en": "around", "zh": "围绕"},
    "btn.apply":        {"en": "apply", "zh": "应用"},
    "btn.reset":        {"en": "start over", "zh": "重新开始"},
    "btn.more":         {"en": "more filters", "zh": "更多筛选"},
    "btn.fresh":        {"en": "ask the API again", "zh": "重新问接口"},

    # -- shared column words ---------------------------------------------
    "col.build_id":  {"en": "build_id", "zh": "构建号"},
    "col.tree":      {"en": "tree", "zh": "源码树"},
    "col.branch":    {"en": "branch", "zh": "分支"},
    "col.created":   {"en": "created", "zh": "建于此"},
    "col.card":      {"en": "card", "zh": "卡片"},
    "col.bytes":     {"en": "bytes", "zh": "字节"},
    "col.acts":      {"en": "acts", "zh": "动作"},
    "col.api_says":  {"en": "api says", "zh": "接口说"},
    "col.ran":       {"en": "ran", "zh": "跑过"},
    "col.test":      {"en": "test", "zh": "测试"},
    "col.needs":     {"en": "needs", "zh": "需要"},
    "col.ready":     {"en": "ready?", "zh": "能跑?"},
    "col.runs":      {"en": "runs", "zh": "跑了几次"},
    "col.last":      {"en": "last", "zh": "最近"},
    "col.when":      {"en": "when", "zh": "何时"},
    "col.gap":       {"en": "in the gap?", "zh": "在缺口里?"},
    "col.verdict":   {"en": "verdict", "zh": "判决"},
    "col.exit":      {"en": "exit", "zh": "退出码"},
    "col.source":    {"en": "source", "zh": "谁跑的"},
    "col.detail":    {"en": "detail", "zh": "细节"},
    "col.id":        {"en": "id", "zh": "编号"},
    "col.kind":      {"en": "kind", "zh": "种类"},
    "col.state":     {"en": "state", "zh": "状态"},
    "col.age":       {"en": "age", "zh": "多久了"},
    "col.what":      {"en": "what", "zh": "跑了什么"},
    "col.argv":      {"en": "argv", "zh": "命令行"},
    "col.node":      {"en": "node_id", "zh": "节点号"},
    "col.name":      {"en": "name", "zh": "名字"},
    "col.result":    {"en": "result", "zh": "结果"},
    "col.platform":  {"en": "platform", "zh": "平台"},
    "col.runtime":   {"en": "runtime", "zh": "运行时"},
    "col.claimed":   {"en": "claimed", "zh": "领过?"},
    "col.definition": {"en": "definition", "zh": "定义"},
    "col.file":      {"en": "file", "zh": "文件"},
    "col.cursor":    {"en": "cursor", "zh": "游标"},
    "col.seen":      {"en": "seen", "zh": "已领单数"},
    "col.pending":   {"en": "pending", "zh": "待处理"},
    "col.took":      {"en": "took", "zh": "耗时"},
    "col.log":       {"en": "log", "zh": "日志"},
    "col.timeline":  {"en": "timeline", "zh": "时间线"},
    "col.regressions": {"en": "regressions", "zh": "回归"},
    "col.rank":      {"en": "#", "zh": "序"},
    "col.build":     {"en": "build", "zh": "构件"},
    "col.delta_up":  {"en": "config delta vs the row before (up)", "zh": "与上一行的配置差 (上)"},
    "col.delta_down": {"en": "vs the row after (down)", "zh": "与下一行的配置差 (下)"},

    # -- words the record itself uses: identical in both columns ----------
    "word.pass":    {"en": "pass", "zh": "pass"},
    "word.fail":    {"en": "fail", "zh": "fail"},
    "word.skip":    {"en": "skip", "zh": "skip"},
    "word.done":    {"en": "done", "zh": "done"},
    "word.running": {"en": "running", "zh": "running"},
    "word.ready":   {"en": "ready", "zh": "ready"},
    "word.missing": {"en": "missing", "zh": "missing"},
    "word.available": {"en": "available", "zh": "available"},
    "word.incomplete": {"en": "incomplete", "zh": "incomplete"},
    "word.local":   {"en": "local", "zh": "local"},
    "word.remote":  {"en": "remote", "zh": "remote"},

    # -- page: builds -----------------------------------------------------
    "page.builds.blurb": {"en": "what upstream has built, what is on this disk, and which of it has run",
                          "zh": "上游建了什么、这块盘上有什么、哪些跑过了"},
    "page.builds.table": {"en": "builds", "zh": "构建"},
    "page.builds.table_sub": {"en": "{n} rows in this window", "zh": "这个窗口里 {n} 行"},
    "page.builds.chips": {"en": "the numbers behind this page", "zh": "这一页背后的数"},
    "builds.cards":  {"en": "cards", "zh": "已登记"},
    "builds.here":   {"en": "here", "zh": "本机"},
    "builds.bytes":  {"en": "with bytes", "zh": "有文件"},
    "builds.acts":   {"en": "pull acts", "zh": "拉取动作"},
    "builds.records": {"en": "records", "zh": "账本记录"},
    "builds.gap":    {"en": "in the gap", "zh": "在缺口里"},
    "builds.activities": {"en": "activities", "zh": "后台活动"},
    "builds.kernel": {"en": "kernel", "zh": "内核"},
    "builds.kselftest": {"en": "kselftest", "zh": "kselftest"},
    "builds.modules": {"en": "modules", "zh": "模块"},
    "builds.card_only": {"en": "card only", "zh": "只有卡片"},
    "builds.whole":  {"en": "whole", "zh": "完整"},
    "builds.partial": {"en": "not whole", "zh": "不完整"},
    "builds.no_remote": {"en": "not in this answer (cap {n})", "zh": "不在这次答案里（上限 {n}）"},
    "builds.no_remote_note": {
        "en": "the column used to read &ldquo;no remote counterpart&rdquo; for a build that is simply outside the window the query returned",
        "zh": "这一列以前对「只是不在这次查询窗口里」的构件也写「没有远端对应物」"},
    "builds.pull_selected": {"en": "pull the selected", "zh": "拉取勾选的"},
    "builds.record": {"en": "record this window in the local table", "zh": "把这次窗口登记进本地表"},
    "builds.index":  {"en": "index the cards", "zh": "登记卡片"},
    "builds.pulls":  {"en": "what has been pulled", "zh": "拉过什么"},
    "builds.pulls_sub": {"en": "the acts Build.make() recorded, newest first",
                         "zh": "Build.make() 记下的动作，新的在前"},
    "builds.artifacts": {"en": "artifacts", "zh": "产物"},
    "builds.transferred": {"en": "transferred", "zh": "续传"},
    "builds.hosts":  {"en": "hosts", "zh": "主机"},
    "builds.error":  {"en": "error", "zh": "错误"},
    "builds.local_title": {"en": "a local origin", "zh": "本地自己产的"},
    "builds.local_sub": {"en": "how a card with no remote counterpart is made",
                         "zh": "没有远端对应物的卡片是怎么来的"},
    "builds.make_image": {"en": "make a card from a local artifact", "zh": "从本地产物造一张卡片"},
    "builds.run_detail": {"en": "run", "zh": "跑"},
    "builds.pull":   {"en": "pull", "zh": "拉取"},

    # -- page: jobs -------------------------------------------------------
    "page.jobs.blurb": {"en": "which (build x test) pairs have not run, which have, and what came back",
                        "zh": "哪些（构建 × 测试）组合还没跑、哪些跑过了、结果是什么"},
    "page.jobs.queue": {"en": "still to run", "zh": "还没跑的"},
    "page.jobs.queue_sub": {"en": "every pair with no record, newest build first",
                            "zh": "所有没有记录的组合，新的构建在前"},
    "page.jobs.ledger": {"en": "the ledger", "zh": "账本"},
    "page.jobs.ledger_sub": {"en": "{n} records, newest first", "zh": "{n} 条记录，新的在前"},
    "jobs.recorded": {"en": "already recorded", "zh": "已记录"},
    "jobs.run_now":  {"en": "run the ticked builds", "zh": "跑勾选的构建"},
    "jobs.run_day":  {"en": "run a day", "zh": "按天跑"},
    "jobs.run_newest": {"en": "run the newest build once", "zh": "最新的构建跑一次"},
    "jobs.ledger_full": {"en": "the ledger, in full", "zh": "完整账本"},
    "jobs.worker_rows": {"en": "these are the rows a worker writes",
                         "zh": "worker 跑出来的就是这几行"},
    "jobs.tick":     {"en": "tick the {n} on this page", "zh": "勾上这页的 {n} 个"},
    "jobs.none":     {"en": "nothing is in the gap - every pair on this page has a record",
                      "zh": "缺口是空的 —— 这一页每个组合都有记录"},

    # -- page: worker -----------------------------------------------------
    "page.worker.blurb": {"en": "what the poll loop is doing, what it has claimed, what came back",
                          "zh": "轮转在干什么、领到单了吗、跑出什么了"},
    "page.worker.status": {"en": "the poller, as far as this disk knows", "zh": "就这块盘知道的，轮转现在什么样"},
    "worker.state_file": {"en": "its own state file", "zh": "它自己的状态文件"},
    "worker.state_sub": {"en": "poller.py&rsquo;s file, displayed and not interpreted",
                         "zh": "poller.py 的文件，只显示不解释"},
    "worker.cursor_note": {
        "en": "<b>cursor is not the last claim time.</b> it moves on every poll that has any event in the window, including events already seen, so a healthy idle loop and a stuck one look the same on it. the number that means &ldquo;this loop really claimed something&rdquo; is <code>seen</code>.",
        "zh": "<b>cursor 不是最后领单时间。</b>只要窗口里有事件它就前进，包括已经见过的，所以「健康的空闲」和「卡死了」在它上面长得一样。真正说明「这条循环领过单」的数是 <code>seen</code>。"},
    "worker.queue": {"en": "the queue on the API", "zh": "接口上的队列"},
    "worker.queue_sub": {"en": "job nodes this runtime can see, newest first",
                         "zh": "这个运行时能看到的作业节点，新的在前"},
    "worker.done_here": {"en": "finished in this worker", "zh": "本 worker 跑完的"},
    "worker.done_here_sub": {"en": "the ledger's rows with source=worker - this panel did not exist before",
                             "zh": "账本里 source=worker 的行 —— 这一块以前不存在"},
    "worker.start": {"en": "start the worker", "zh": "启动轮转"},
    "worker.stop":  {"en": "stop", "zh": "停止"},
    "worker.once":  {"en": "once", "zh": "跑一次"},
    "worker.resident": {"en": "resident", "zh": "常驻"},
    "worker.where_results": {"en": "results land in <a href=\"/jobs\">jobs</a> (the worker rows) and in the panel below",
                             "zh": "跑完的结果在 <a href=\"/jobs\">测试</a>（worker 那几行）和下面那一块"},
    "worker.pid": {"en": "process", "zh": "进程"},
    "worker.since": {"en": "started", "zh": "起于"},
    "worker.uptime": {"en": "uptime", "zh": "已经跑了"},
    "worker.claimed": {"en": "claimed", "zh": "领过"},
    "worker.not_claimed": {"en": "not claimed", "zh": "没领过"},

    # -- page: runs -------------------------------------------------------
    "page.runs.blurb": {"en": "every background process this console started, and whether it is still going",
                        "zh": "这个控制台起过的每个后台进程，还在不在跑"},
    "page.runs.table": {"en": "activities", "zh": "后台活动"},
    "page.runs.table_sub": {"en": "{n} rows in this window", "zh": "这个窗口里 {n} 行"},
    "runs.note": {
        "en": "<b>a worker that claims five jobs still has one row here.</b> this table is what the console started, not what those processes did - the results are in <a href=\"/jobs\">jobs</a>.",
        "zh": "<b>一个领了五单的 worker 在这张表上仍然只有一行。</b>这张表是控制台起过什么，不是那些进程干了什么 —— 结果在<a href=\"/jobs\">测试</a>里。"},
    "runs.group": {"en": "{kind} ({n})", "zh": "{kind}（{n} 个）"},

    # -- page: analysis ---------------------------------------------------
    "page.analysis.blurb": {"en": "read down the list: is this getting better or worse",
                            "zh": "一路看下去，是在变好还是变坏"},
    "page.analysis.picks": {"en": "the builds in this order", "zh": "这个顺序下的构建"},
    "page.analysis.picks_sub": {"en": "the order is the question: a row's neighbour is decided by it",
                                "zh": "顺序本身就是问题：一行的邻居由它决定"},
    "page.analysis.bars": {"en": "how each build came back", "zh": "每个构件的结果"},
    "page.analysis.bars_sub": {"en": "one bar per build: pass, fail, then what did not answer",
                               "zh": "每个构件一条：通过、失败、然后是没有答复的"},
    "page.analysis.timeline": {"en": "one line per test", "zh": "每个测试一行"},
    "page.analysis.timeline_sub": {"en": "newest on the right; a gap is a position the ledger has nothing for",
                                   "zh": "右边最新；空格是账本里没有记录的位置"},
    "page.analysis.drift": {"en": "drift", "zh": "偏移"},
    "page.analysis.drift_sub": {"en": "how much two neighbouring configs differ, in ±",
                                "zh": "相邻两份配置差多少，用 ± 表示"},
    "analysis.first_row": {"en": "the first row in this order", "zh": "这个顺序下的第一行"},
    "analysis.last_row": {"en": "the last row in this order", "zh": "这个顺序下的最后一行"},
    "analysis.not_comparable": {"en": "not comparable", "zh": "不可比"},
    "analysis.no_delta": {"en": "no number: only the first {n} rows spend a config read",
                          "zh": "没有数字：只有前 {n} 行会去读配置"},
    "analysis.compare": {"en": "compare", "zh": "对比"},
    "analysis.left": {"en": "left", "zh": "左"},
    "analysis.right": {"en": "right", "zh": "右"},
}


# The keys whose value is markup and not a sentence: they carry a `<b>`, a `<code>`
# or a link, exactly as `lib/i18n`'s values do.  A key here is written with
# `innerHTML` on the client and a key not here with `textContent`, which is what
# keeps a build id that happens to contain `<` from becoming a tag.
HTML_KEYS = frozenset({
    "builds.no_remote_note", "worker.cursor_note", "runs.note", "worker.where_results",
})


def t(lang: str, key: str, **kw) -> str:
    """One string, in `lang`, with `{placeholders}` filled.

    An unknown key comes back as the key and a bad placeholder comes back as the
    string it was: a prototype page that dies is harder to review than a page with
    `{n}` in it, which is the same trade `lib/i18n/__init__.py` makes.
    """
    row = STRINGS.get(key)
    if row is None:
        return key
    text = row.get(lang) or row[DEFAULT_LANG]
    if not kw:
        return text
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):
        return text


def both(key: str, **kw) -> str:
    """`en` and `zh` as one HTML fragment, so a language switch is client-side.

    The real console re-renders the page in the other language and holds the
    choice in a cookie.  A prototype has no backend round-trip to spend, so every
    translated string is written out twice and the switch only moves an
    attribute - which also makes reviewing both columns one page instead of two.
    """
    row = STRINGS.get(key)
    if row is None:
        return key
    en = _fill(row.get("en", key), kw)
    zh = _fill(row.get("zh", en), kw)
    how = "html" if key in HTML_KEYS else "text"
    return (f'<span data-i18n="{how}" data-en="{_attr(en)}" data-zh="{_attr(zh)}">'
            f'{zh if DEFAULT_LANG == "zh" else en}</span>')


def _fill(text: str, kw: dict) -> str:
    if not kw:
        return text
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):
        return text


def _attr(text: str) -> str:
    return (text.replace("&", "&amp;").replace('"', "&quot;")
                .replace("<", "&lt;").replace(">", "&gt;"))
