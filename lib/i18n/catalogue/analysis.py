# SPDX-License-Identifier: LGPL-2.1-or-later
"""`/analysis`: config drift, the regression timeline, its columns and its charts.

One part of the catalogue; `lib/i18n/__init__.py` merges the parts in this
order.  The `# ---` banners below are the source's own grouping, kept as they
were written."""

PART: dict[str, dict[str, str]] = {
    # --- /analysis : config drift, and the regression timeline --------------

    "page.analysis.drift_title": {"en": "config drift", "zh": "config 漂移"},

    # Reworded by step 6.  It said "two builds, chosen in select boxes; Drift does the
    # reading", which is a sentence about the page (`05-i18n-prose.md` §B.1's first
    # forbidden class: how the page works) and was false the moment the chooser stopped
    # being two select boxes.  What it says now is the one number a reader weighing a
    # reload wants: how many configs this render actually read.
    "page.analysis.drift_sub": {"en": "config reads {n}", "zh": "读 config {n}"},

    "btn.run_drift": {"en": "run drift.py", "zh": "跑 drift.py"},

    "analysis.drift_hint": {"en": "one activity; its exit code is the answer (0 no drift, 1 drift)",
                              "zh": "一次活动；退出码就是答案（0 没漂移，1 有漂移）"},

    "analysis.choose_two": {"en": "choose two builds above, or tick exactly two rows on {link}.",
                              "zh": "在上面选两个 build，或者在 {link} 上正好勾两行。"},

    # A typed id the page did not read: refused, because looking it up is a 1 000-node
    # scan inside a GET (116.8-137.9 s measured, `06-analysis.md` §D3).
    "analysis.not_read": {"en": "{build} is not a build this page read; the API cannot be asked for a build by id",
                            "zh": "{build} 不在这一页读到的 build 里；API 没法按 id 查一个 build"},

    "page.analysis.trend_title": {"en": "one line per test", "zh": "每个测试一行"},

    "page.analysis.trend_sub": {"en": "{test} · {n} runs · {order}",
                                  "zh": "{test} · {n} 次 · {order}"},

    "col.timeline": {"en": "timeline", "zh": "时间线"},

    "btn.compare": {"en": "compare", "zh": "对比"},

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

    "sort.k.tree": {"en": "tree", "zh": "源码树"},

    "sort.k.branch": {"en": "branch", "zh": "分支"},

    "sort.k.tree_branch": {"en": "tree-branch", "zh": "总分支"},

    "sort.k.series": {"en": "series", "zh": "系列"},

    "sort.k.verdict": {"en": "verdict", "zh": "判决"},

    "sort.k.id": {"en": "id", "zh": "编号"},

    "sort.dir.asc": {"en": "↑", "zh": "↑"},

    "sort.dir.desc": {"en": "↓", "zh": "↓"},

    "sort.add": {"en": "+{key}", "zh": "+{key}"},

    "sort.drop_title": {"en": "remove this key from the order", "zh": "把这个键从排序里去掉"},

    "sort.flip_title": {"en": "reverse this key's direction", "zh": "把这个键的方向反过来"},

    # The neighbour cell: a comparison that was not made still names its neighbours, and
    # each of those names is the door to the comparison (`/analysis/<id>?vs=<other>`).
    # The regression chart (`_wave_chart`): three lanes over the page's own order.
    "chart.band_title": {"en": "{test} over this order", "zh": "{test} 在这一个排序上"},

    "chart.band_sub": {"en": "{n} slots: {ran} with a record, {gap} with none - the horizontal axis is the order above, not time",
                         "zh": "{n} 个位置：{ran} 个有记录，{gap} 个没有 —— 横轴是上面的顺序，不是时间"},

    "chart.lane_verdict": {"en": "verdict", "zh": "判决"},

    "chart.lane_cases": {"en": "cases", "zh": "用例"},

    "chart.lane_at": {"en": "#", "zh": "序"},

    "chart.gap_title": {"en": "{build} has no {test} record: the local table has the build and the ledger has nothing for this test - open /jobs to fill the gap",
                          "zh": "{build} 没有 {test} 的记录：本地表里有这个 build，账本里这个 test 什么都没有 —— 打开 /jobs 把这个缺口补上"},

    # The line chart (`_trend_lines`, the tree's only SVG).  Its two axes have to be
    # named on the page or the picture lies: `x` is the order above - a reader who
    # assumes time reads a slope that is not there - and `y` is a *running* count of the
    # runs this page is displaying, not the ledger's tally, which is why the word
    # "reached" is doing the work in that sentence.
    "chart.lines_title": {"en": "the same order, as lines", "zh": "同一个顺序，画成折线"},

    "chart.lines_sub": {"en": "y is how many runs of that verdict the order has reached; a position with no record changes no line, and the dashes under the axis are those positions",
                          "zh": "纵轴是走到这个位置为止、那种判决累计有几次；没有记录的位置不改变任何一条线，轴下面那些虚线就是这些位置"},

    "chart.lines_desc": {"en": "One cumulative line per verdict over the {n} positions of the order above; {gap} of them have no {test} record. The same numbers are in the table below.",
                           "zh": "上面的顺序共 {n} 个位置，每种判决一条累加折线；其中 {gap} 个位置没有 {test} 的记录。同样的数字在下面的表里。"},

    "chart.lines_none": {"en": "no {test} record anywhere in this order, so no line can be drawn: the gaps themselves are the answer",
                           "zh": "这一个顺序里没有任何 {test} 的记录，所以一条线也画不出来：缺口本身就是答案"},

    # One key of the line chart's legend: the verdict's word (the same word the pills
    # print) and the count that verdict reached by the end of the order - so identity is
    # never carried by the colour of the stroke alone.
    "chart.key": {"en": "{verdict} {n}", "zh": "{verdict} {n}"},

    "chart.axis_y": {"en": "runs", "zh": "次"},

    # The worker page: what the button would claim, before it is pressed.  A count, so a
    # worker start that finds nothing is readable as "nothing to claim" rather than as a
    # failure - which is the difference the operator could not see.
    "worker.would_claim": {"en": "{n} claimable now", "zh": "现在可领取 {n} 个"},

    # Where the available queue actually is, one click per pair: the default pair on this
    # deployment claims nothing, and "nothing to claim" is not a useful thing to leave a
    # reader holding.
    "worker.pairs_lead": {"en": "the queue has work on these", "zh": "队列里有活的组合"},

    "worker.pair": {"en": "{platform} / {runtime}: {n}", "zh": "{platform} / {runtime}：{n} 个"},

    # Why a platform is shown and not linkable.  Two sentences, because there are two
    # different facts: a name the vendored scheduler config does not declare (`_offered`
    # would refuse it), and a platform this deployment's worker would claim a job for and
    # then boot with the wrong device - the failure that reads as 基础设施 rather than as a
    # wrong setting, so it is said here and not discovered in a console.
    "worker.platform_unknown": {"en": "{platform}: the scheduler config this deployment vendors declares no such platform, so pull_worker.py would refuse --platform {platform}",
                                  "zh": "{platform}：这个部署自带的调度器配置里没有这个平台，pull_worker.py 会拒绝 --platform {platform}"},

    "worker.platform_off": {"en": "{platform}: a worker started from this page cannot run it - the device now follows the job, but the rest of the boot line does not: the cpu parameters and the rootfs are riscv64 only, so a job for {platform} would still end in an infra failure",
                              "zh": "{platform}：从这个页面启动的 worker 跑不了它 —— 设备现在跟着作业走，但启动行的其余部分是 riscv64 专用的（cpu 参数和 rootfs），所以 {platform} 的作业仍然只会以基础设施失败收场"},

    # The runtime has no such sentence: a lab is a claim filter and nothing more, so the
    # only runtime worth not linking is one the vendored config never declared.
    "worker.runtime_unknown": {"en": "{runtime}: the scheduler config this deployment vendors declares no such runtime, so pull_worker.py would refuse --runtime {runtime}",
                                 "zh": "{runtime}：这个部署自带的调度器配置里没有这个 runtime，pull_worker.py 会拒绝 --runtime {runtime}"},

    "delta.before": {"en": "before", "zh": "上一行"},

    "delta.after": {"en": "after", "zh": "下一行"},

    "delta.door_title": {"en": "compare with {build} - open the comparison",
                           "zh": "和 {build} 比较 — 打开这次比较"},

    # `/analysis/<id>`: one build, and one comparison.
    "page.one.title": {"en": "one build", "zh": "一个 build"},

    "page.one.sub": {"en": "{build} - its record, and what it compares with",
                       "zh": "{build} —— 它的记录，以及它和谁比"},

    "one.compare_title": {"en": "the comparison", "zh": "这一对比较"},

    "one.vs_choose": {"en": "name the other build with {link} - the order and the filter above came with you, so the neighbours are the ones this row had",
                        "zh": "用 {link} 指定另一个 build —— 上面的排序和筛选跟着你过来了，所以邻行还是这一行原来的那两行"},

    "one.compare_line": {"en": "{older} &rarr; {newer}", "zh": "{older} &rarr; {newer}"},

    "one.all_rows": {"en": "the whole comparison, every changed option",
                       "zh": "完整比较，每一条变化的选项"},

    "one.back": {"en": "back to the list", "zh": "回到列表"},

    "one.neighbours": {"en": "its neighbours in this order", "zh": "在这个排序里的相邻行"},

    "one.no_neighbours": {"en": "this build is not in the list this page's filter and order produce, so it has no neighbours here",
                            "zh": "这个 build 不在这页筛选和排序产生的那张表里，所以在这里没有相邻行"},

    "filter.sort_refused": {"en": "the order in this URL named {value}, which is not a sort key I know; the keys I know are {options}",
                              "zh": "这个 URL 里的排序写了 {value}，不是我知道的排序键；我知道的是 {options}"},

    "sort.date_asc": {"en": "date ↑", "zh": "日期 ↑"},

    "sort.same_branch": {"en": "same branch first", "zh": "同分支优先"},

    "sort.verdict": {"en": "by verdict", "zh": "按判决"},

    "sort.build": {"en": "by build id", "zh": "按构建号"},

    "delta.cap": {"en": "delta", "zh": "差异"},

    "delta.none_prev": {"en": "— the first row in this order", "zh": "— 这个排序里的第一行"},

    "delta.none_next": {"en": "— the last row in this order", "zh": "— 这个排序里的最后一行"},

    "delta.cannot": {"en": "cannot compare", "zh": "比不了"},

    # The `title=` of a count-less cell, with `{n}` the cap in force: it says *why*
    # there is no `+n −n ~n` (the row is past `?delta=`) and rides beside
    # `delta.door_title`, which says where the click goes.  The visible half of that
    # hint is `col.delta_sub`; this is the per-cell one, and it was dead before it was
    # written into `_delta_cell.marker`.
    "delta.beyond": {"en": "beyond the delta cap ({n})", "zh": "超出差异上限（{n}）"},

    "delta.why_no_config": {"en": "no <code>_config</code> artifact, and the storage fallback answered {code}",
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

    # The column's own label, and the one place the rule is stated: a row with no
    # `+n −n ~n` was **not** compared (it is past the cap, `DEFAULT_DELTA`), and the
    # click that would have produced the number is still there - those cells are doors
    # into `/analysis/<id>?vs=<id>`, which prints the pair's whole diff.  Said here and
    # not in the cells: 47 rows each carrying the same sentence is a wall, not a hint.
    "col.delta_sub": {"en": "vs the row before (↑) and after (↓); no number: not compared, click for the whole diff",
                        "zh": "对着上一行（↑）和下一行（↓）；没有数字：没比较，点开就是完整 diff"},

    "col.n": {"en": "#", "zh": "序"},

    "col.option": {"en": "option", "zh": "选项"},

    "col.cases": {"en": "cases", "zh": "用例"},

    "chart.title": {"en": "the same order, as bars", "zh": "同一个顺序，画成横条"},

    "chart.sub": {"en": "{n} adjacent pairs, {order}", "zh": "{n} 组相邻，{order}"},

    "page.analysis.picks_title": {"en": "the builds in this order", "zh": "这个顺序下的构建"},

    "page.analysis.picks_sub": {"en": "{shown} of {pool} rows, {order}",
                                  "zh": "{shown}/{pool} 行，{order}"},

    "page.analysis.runs_title": {"en": "the runs of {test}", "zh": "{test} 的每一次运行"},

    "page.analysis.runs_sub": {"en": "{n} runs, cap {cap}", "zh": "{n} 次，上限 {cap}"},

    "page.analysis.point_title": {"en": "the run this cell came from", "zh": "这一格是哪次运行"},

    "page.analysis.point_sub": {"en": "click a block in a timeline above", "zh": "点上面时间轴里的一格"},

    "mark.records": {"en": "records", "zh": "记录"},

    "empty.no_builds": {"en": "no build matches this filter", "zh": "这个筛选下没有 build"},

    "word.commit": {"en": "commit", "zh": "commit"},

    "word.log": {"en": "log", "zh": "日志"},

    "word.config": {"en": "config", "zh": "config"},

    # --- the three columns of a config comparison ---------------------------

    "drift.cannot_compare": {"en": "cannot compare: {error}", "zh": "比不了：{error}"},

    "drift.no_drift": {"en": "no drift between <code>{older}</code> and <code>{newer}</code>: the two configs hold the same options.",
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

    "drift.summary": {"en": "<code>{older}</code> &rarr; <code>{newer}</code>: {added} added, {removed} removed, {changed} changed",
                        "zh": "<code>{older}</code> &rarr; <code>{newer}</code>：新增 {added}、删除 {removed}、改动 {changed}"},

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

    "state.already_whole_proven": {"en": "already whole: size proven, nothing transferred",
                                     "zh": "已经完整：大小核对过，没有传输"},

    "state.no_error": {"en": "no error", "zh": "没有错误"},

    "state.no_runs": {"en": "(no runs yet)", "zh": "（还没跑过）"},

    "state.yes": {"en": "yes", "zh": "是"},

    "state.no": {"en": "no", "zh": "否"},

    "label.error_prefix": {"en": "error: {what}", "zh": "错误：{what}"},

    "count.artifacts_act": {"en": "{n} artifacts", "zh": "{n} 个构件"},

    "col.that_pull": {"en": "that pull", "zh": "这次拉取"},

    "col.artifacts": {"en": "artifacts", "zh": "产物"},

    "col.artifact": {"en": "artifact", "zh": "构件"},

    "col.file": {"en": "file", "zh": "文件"},

    "col.bytes": {"en": "bytes", "zh": "字节"},

    "col.transferred": {"en": "transferred", "zh": "续传"},

    "col.hosts": {"en": "hosts", "zh": "主机"},

    "col.error": {"en": "error", "zh": "错误"},

    # --- code-form words: the same string in both columns, on purpose -------
    #
    # These are what the record calls things: an API field, a path, a flag, a
    # vocabulary word a select box offers.  They are in the catalogue so that a
    # page has one place to read every word it prints, and so that `--check` can
    # say "same on purpose" instead of "not translated".  A word that a select
    # box offers as a *value* (`pulled`, `pass`, `resident`) is not here: the
    # value is the vocabulary, and one vocabulary has one spelling.

    "word.build_id": {"en": "build_id", "zh": "构建号"},

    "word.tree": {"en": "tree", "zh": "源码树"},

    "word.branch": {"en": "branch", "zh": "分支"},

    "word.arch": {"en": "arch", "zh": "架构"},

    "word.defconfig": {"en": "defconfig", "zh": "配置"},

    "word.compiler": {"en": "compiler", "zh": "编译器"},

    "created.from_act": {"en": "the pull record's own time: no card names this build",
                           "zh": "拉取记录里的时间：没有卡片给这个 build 命名"},

    "word.created": {"en": "created", "zh": "建于此"},

    "word.node_id": {"en": "node_id", "zh": "节点号"},

    "word.describe": {"en": "describe", "zh": "描述"},

    "word.test": {"en": "test", "zh": "测试"},

    "word.result": {"en": "result", "zh": "结果"},

    "word.url": {"en": "url", "zh": "url"},

    "word.platform": {"en": "platform", "zh": "平台"},

    "word.runtime": {"en": "runtime", "zh": "运行时"},

    "word.build": {"en": "build", "zh": "构件"},

    "word.owner": {"en": "owner", "zh": "owner"},

    "word.state_result": {"en": "state / result", "zh": "state / result"},

    "word.tree_branch": {"en": "tree / branch", "zh": "tree / branch"},

    "word.arch_defconfig_compiler": {"en": "arch / defconfig / compiler",
                                       "zh": "arch / defconfig / compiler"},

    # --- the comparison cells and the two charts ----------------------------
    #
    # A row's `±` is the config difference against its neighbour *in this order*, so
    # the two rows that have no neighbour have to say which end they are on: a
    # dash would read as "not measured", and "the first row" is a fact about the
    # order rather than a missing measurement.  The third case - a pair the page
    # did not spend a config read on - is a dash with its reason in the tooltip.
    "analysis.first_row": {"en": "the first row in this order", "zh": "这个顺序下的第一行"},

    "analysis.last_row": {"en": "the last row in this order", "zh": "这个顺序下的最后一行"},

    "analysis.not_compared": {"en": "not compared", "zh": "没有比较"},

    "analysis.no_record": {"en": "no record", "zh": "没有记录"},

    # The pass-rate chart: one line per test across the positions of the order, one
    # point per build.  The point's own tooltip is the only place the three numbers
    # are printed together, and the `aria-label` is the chart's name for a reader
    # who cannot see it - the design draws both.
    "chart.passrate": {"en": "pass rate across the ordered builds", "zh": "按这个顺序，每个构建的通过率"},

    "chart.point": {"en": "{test} · {pct}% · position {n}", "zh": "{test} · {pct}% · 第 {n} 个"},

    # The arrow is the character and not `&rarr;`: this caption goes through
    # `words.both()`, whose four modes write `textContent`, and an entity would reach
    # the reader as those six characters after the swap (`words._swappable`).
    "chart.cap": {"en": "oldest → newest, the same {n} positions as the table above",
                    "zh": "旧 → 新，和上面那张表同样的 {n} 个位置"},

    # A legend entry's number: how many runs of that test the order holds.  A unit
    # and a number, never `run(s)` - the count is right there and the noun is a unit.
    # The pass-rate chart passes it `drawn / total` rather than the total alone: at this
    # console's default window the chart rests on 5 of `boot`'s 22 runs, and a legend that
    # printed only the 22 would be a lie about what the line stands on
    # (`00-BRIEF.md` §10.11).
    "chart.runs": {"en": "{n} runs", "zh": "{n} 次"},

    # --- `/analysis`, the two `±` columns and the sentences a cell must not omit -------
    #
    # The board draws **two** config-delta columns and says which neighbour each one is
    # against; the tree had one word for both, which is why these two are the design's own
    # pair, verbatim (`proto/words.py`'s names and its two values).
    "col.delta_up": {"en": "config delta vs the row before (up)",
                       "zh": "与上一行的配置差 (上)"},

    "col.delta_down": {"en": "vs the row after (down)", "zh": "与下一行的配置差 (下)"},

    # The timeline's own column: `re.transitions()`'s count, in the board's word.
    "col.regressions": {"en": "regressions", "zh": "回归"},

    # A `±` cell whose pair was inside the cap and still has no number: the engine refused
    # it.  Which of `Drift`'s three refusals it was (no card, what came back is not a
    # kernel config, not among the newest nodes) is only known to the reader that made the
    # comparison, so the cell says the fact it can be sure of and the cell itself is the
    # door into the pair's page, where the engine's own sentence is printed.  A dash here
    # would read as "not measured", and this is a measurement that was attempted.
    "page.analysis.no_config": {"en": "not compared: no kernel config on one side",
                                  "zh": "没有比较：有一边没有 kernel config"},

    # What the picks table is: how many rows this window drew, the cap that decided it, and
    # the test every row's verdict and counts are about.  All three are numbers and value
    # words, so the sentence is the same shape in both columns.  The row cap is spelled
    # `limit` and not `cap`, because the other cap on this page is the *comparison* cap
    # (`delta`), and the two of them said "cap" would read as one number.
    "page.analysis.picks_note": {"en": "{shown} rows, limit {cap}, test {test}",
                                   "zh": "{shown} 行，limit {cap}，test {test}"},

    # One run's TAP counts, in the board's own shape (`9 total / 2 fail / 1 skip`).
    # `fail` and `skip` stay as they are in both columns: they are the record's own
    # vocabulary, and one vocabulary has one spelling (`§12.2`).
    "page.analysis.tap": {"en": "{total} total / {fail} fail / {skip} skip",
                            "zh": "共 {total} 个 / fail {fail} / skip {skip}"},

    # ... and the case the ledger answers with no counts at all: a record whose test died
    # before TAP ran holds `results: {}`, and `0/0` for it would be a claim the ledger does
    # not make (`design/data.py::_picks` states the same rule).  The tooltip is the
    # per-cell version; the panel's sub-line carries the same fact once when every row
    # in the list is a dash, because 25 identical dashes with no sentence over them read
    # as a broken page.
    "page.analysis.no_tap": {"en": "this run reported no TAP counts",
                               "zh": "这次运行没有报 TAP 计数"},

    "page.analysis.no_tap_note": {"en": "no row in this list holds TAP counts: {test} reports none",
                                    "zh": "这个列表里没有一行有 TAP 计数：{test} 不报"},

    # The pair chooser: the board's own bar ("compare two builds"), and the one sentence
    # that says how a pair is chosen here - by ticking rows, not by typing ids.  It is also
    # what the disabled `drift` button says in its `title=`, so the instruction and the
    # refusal are one sentence.
    "page.analysis.pair": {"en": "compare two builds", "zh": "对比两个构建"},

    "page.analysis.pair_how": {
        "en": "tick two rows in the table below, then press compare: the upper tick is the older end",
        "zh": "在下面的表里勾两行，然后按对比：靠上那一行是旧的一端"},

    # The pass-rate chart.  Its three sentences are the board's own sub-line, a caption
    # that states the axis **and the window**, and the one hint that names the two axes of
    # this screen - the timeline is by date, this chart is by the order above, and side by
    # side and unlabelled they read as one axis (`§10.12`).
    "page.analysis.chart": {"en": "pass rate in this order", "zh": "这个顺序下的通过率"},

    "page.analysis.chart_sub": {
        "en": "one line per test; a break is a position the ledger has nothing for",
        "zh": "每个测试一条线；断开的地方是账本里没有记录的位置"},

    "page.analysis.chart_cap": {
        "en": "the same {n} positions as the table above, in this order; the window is the newest {cap} builds, so each legend entry says how many of that test's runs are inside it",
        "zh": "和上面那张表同样的 {n} 个位置，同一个排序；窗口是最新 {cap} 个构建，所以图例里每个数字说的是这个测试有几次运行落在窗口里"},

    "page.analysis.chart_none": {
        "en": "no run in this window has a record, so no line can be drawn: the gaps are the answer",
        "zh": "这个窗口里没有任何一次运行有记录，画不出线：缺口本身就是答案"},

    "page.analysis.axes_note": {
        "en": "these positions are by date; the chart below runs along the order above, so the two are not the same axis",
        "zh": "这里的格子按日期；下面的曲线按上面的排序，两者不是同一个轴"},

    # The timeline panel's sub-line: the board's own sentence about its axis, which is the
    # half of "two axes" this panel states (`page.analysis.trend_title` is its title).
    "page.analysis.timeline_sub": {
        "en": "newest on the right; a gap is a position the ledger has nothing for",
        "zh": "右边最新；空格是账本里没有记录的位置"},

    # The bars panel: the board's own title and sub-line, and the one clause the sub-line
    # was missing.  Without it "one bar per build" can be read as a running total, which is
    # the opposite of what the panel draws - the numbers are that build's own records for
    # the test in force.
    "page.analysis.bars": {"en": "how each build came back", "zh": "每个构件的结果"},

    "page.analysis.bars_sub": {
        "en": "one bar per build: pass, fail, then what did not answer - that build's own records for {test}, never a running total",
        "zh": "每个构件一条：通过、失败、然后是没有答复的 —— 那是这个构件自己在 {test} 上的记录，不是累计"},

    # --- the detail route `/analysis/<build_id>?vs=<other>` ----------------------------
    #
    # The single-build page's own two sentences: the box that names the other side, and the
    # state of not having named one.  Both are the design's "type both ids" bar, said for
    # the one id this route still needs.
    "one.vs": {"en": "the other build", "zh": "另一个 build"},

    "one.vs_none": {"en": "no other build named yet: type its id above and press compare",
                      "zh": "还没指定另一个 build：在上面填它的号，然后按对比"},

    # A build the window did not read has no row on this page, so it has no counts here
    # either - and which window was read is the fact that makes that readable rather than
    # broken.
    "one.not_in_window": {
        "en": "{build} is not among the {n} builds this window read, so its own counts are not on this page",
        "zh": "{build} 不在这一个窗口读到的 {n} 个 build 里，所以这一页没有它自己的计数"},
}
