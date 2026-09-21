# SPDX-License-Identifier: LGPL-2.1-or-later
"""The shell and the top of the site: navigation, the counts strip, `/`, `/remote`.

One part of the catalogue; `lib/i18n/__init__.py` merges the parts in this
order.  The `# ---` banners below are the source's own grouping, kept as they
were written."""

PART: dict[str, dict[str, str]] = {
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

    # The builds table's head, as the board's own sub-line: how many rows this window
    # holds.  The board printed a literal `7 rows in this window` over a 24-row table
    # (its script corrected the English at run time, so the served markup was wrong in
    # both languages - `00-BRIEF.md` §9 item 4), so the number is a placeholder the page
    # fills from the rows it drew.
    "page.builds.rows_window": {"en": "{n} rows in this window", "zh": "这个窗口里 {n} 行"},

    # The card column's three cells: `present` is the board's own word for a tick whose
    # artifact `Build.present()` found on disk, and its absence is the existing
    # `state.not_here`.  A tick with no word for "here" beside it reads as decoration.
    "page.builds.present": {"en": "present", "zh": "在"},

    # The two commands in the local-origin panel, in the board's own words.  They are new
    # keys rather than the old layer's `btn.publish_image`/`btn.record_window` because the
    # board's wording is what the operator chose for the new skin (`00-BRIEF.md` §12
    # item 2) - and the panel says *what the command is for* (`page.builds.image_sub`)
    # rather than naming the path it happens to read.
    "page.builds.card_from_local": {"en": "make a card from a local artifact",
                                      "zh": "从本地产物造一张卡片"},

    "page.builds.index_cards": {"en": "index the cards", "zh": "登记卡片"},

    "counts.cards": {"en": "cards", "zh": "已登记"},

    "counts.here": {"en": "here", "zh": "本机"},

    "counts.bytes": {"en": "with bytes", "zh": "有文件"},

    "counts.acts": {"en": "pull acts", "zh": "拉取动作"},

    "counts.records": {"en": "records", "zh": "账本记录"},

    "counts.gap": {"en": "in the gap", "zh": "在缺口里"},

    "counts.activities": {"en": "activities", "zh": "后台活动"},

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
                             "zh": "产物就在本机磁盘上（Build.present()）"},

    "counts.title_acts": {"en": "every act Build.make() recorded, in {provenance}",
                            "zh": "Build.make() 记下的每一条 act，在 {provenance} 里"},

    "header.api_down": {"en": "the API did not answer: {note}", "zh": "API 没有应答：{note}"},

    "header.busy": {"en": "writing right now: {writers} &mdash; another writer is refused until it ends",
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

    "col.here": {"en": "here", "zh": "本机"},

    "empty.remote_no_answer": {"en": "<b>the API did not answer this query</b> ({note}), so this table is empty because nothing arrived &mdash; not because the API has no such build",
                                 "zh": "<b>API 没有应答这次查询</b>（{note}），所以这张表是空的，因为什么都没回来 &mdash; 不是 API 没有这个 build"},

    "empty.remote_empty": {"en": "<b>the API answered, and the answer is empty</b> for this query ({query}) &mdash; an empty answer, not a missing one",
                             "zh": "<b>API 答了，答案是空的</b>，这次查询是（{query}） &mdash; 空答案，不是没有"},

    # --- the chrome the design board added ---------------------------------
    #
    # The board's top bar names the program, offers the two switches a reader owns
    # (language, theme) and ends every screen with the line that says what was read.
    # `shell.brand` is deliberately the same in both columns: it is what the program
    # is called, not a word either language has an opinion about, and translating a
    # product name is how a page ends up with two of them.
    "shell.brand": {"en": "kernelci-riscv", "zh": "kernelci-riscv"},

    "shell.pages": {"en": "pages", "zh": "页面"},

    "shell.lang": {"en": "language", "zh": "语言"},

    "shell.theme_title": {"en": "light / dark", "zh": "浅色 / 深色"},

    # The three states the theme button cycles through.  `auto` is the reader who has
    # chosen nothing, which is what the stylesheet does with no `data-theme` at all;
    # it is a state and not a missing value, so it has a word.
    "theme.auto": {"en": "auto", "zh": "自动"},

    "theme.light": {"en": "light", "zh": "浅色"},

    "theme.dark": {"en": "dark", "zh": "深色"},

    # The last line of every screen: which files it was drawn from, and when.  A
    # page shown without its age is a page pretending it just read something.
    "shell.read_from": {"en": "read from", "zh": "读自"},

    "shell.drawn": {"en": "drawn", "zh": "绘制于"},

    # The chip panel's own sub-line on `/`, whose `<h2>` is empty in the design.
    "page.builds.chips_title": {"en": "the numbers behind this page", "zh": "这一页背后的数"},

    # The pager's jump box.  The board's own box takes a page number and its script
    # converts it; a form cannot, so this console's takes the row to start at and the
    # title says so - with the page size, because the box steps by it.
    "pager.jump": {"en": "type a row number and press enter; a page is {limit} rows",
                     "zh": "输入行号后回车；每页 {limit} 行"},
}
