# SPDX-License-Identifier: LGPL-2.1-or-later
"""The five pages.  One function each, one route each, no shared state.

Every function takes the fixture dict and returns an HTML fragment; `shell.document`
wraps it.  A page names no colour and no state word it did not get from `ui`, which
is what keeps five pages one tool.

The order the pages are written in is the order a reader walks them - what upstream
built, what has not run, what this console is running, what it ran, and how it is
trending - and each page's opening panel answers the question in its own blurb.

Two things every page does the same way, because they are the two things the
operator asked for most often:

* **the filter bar is never hidden.**  It is the state of the question, it is what
  the URL would carry, and a reader who cannot see it cannot tell a filtered page
  from an empty one.
* **a number is a link to the rows behind it.**  The chips at the top of /builds
  are counts, not decoration.
"""

from . import ui
from .ui import Col, code, esc
from .words import both, both as tr

# how many artifacts a card is made of, in the order the column shows them
ARTIFACTS = (("kernel", "builds.kernel"), ("kselftest", "builds.kselftest"),
             ("modules", "builds.modules"))


# ═══════════════════════════════════════════════════════════════════════ builds
def builds(d: dict) -> str:
    """What upstream has built, what is here, and which of it has run.

    The table's two hard columns are the ones the old page got wrong: *local* says
    which of the three artifacts are on this disk (a card with nothing behind it is
    a row that looks the same as a whole one until you try), and *api says* answers
    the remote question without pretending a build outside the window does not
    exist.
    """
    f = [
        ui.field(both("filter.api"), ui.select("api", d["apis"], "local")),
        ui.field(both("filter.tree"), ui.multi("tree", ["net-next"], d["trees"], "add a tree")),
        ui.field(both("filter.branch"), ui.select("branch", [""] + d["branches"])),
        ui.field(both("filter.arch"), ui.multi("arch", ["riscv"], d["arches"], "add an arch")),
        ui.field(both("filter.defconfig"),
                 ui.multi("defconfig", [], d["defconfigs"], "any"), "w-lg"),
        ui.field(both("filter.compiler"), ui.multi("compiler", [], d["compilers"], "any")),
    ]
    more = [
        ui.field(both("filter.origin"), ui.select("origin", d["origins"]), "w-sm"),
        ui.field(both("filter.evidence"), ui.select("evidence", d["evidences"]), "w-md"),
        ui.field(both("filter.run"), ui.select("ran", ["any", "pass", "fail", "never"]), "w-sm"),
        ui.field(both("filter.days"), ui.number_input("days", 0), "w-sm"),
        ui.field(both("filter.limit"), ui.number_input("limit", 50), "w-sm"),
        ui.field(both("filter.text"), ui.text_input("text", "", "id, describe, path"), "w-lg"),
    ]
    buttons = (ui.link_btn(both("btn.reset"), "/builds", "sm")
               + ui.btn(both("btn.apply"), "primary sm"))
    # the six conditions every reader touches are always visible; the seven that
    # narrow a window are one click away, because a filter bar nobody can see the
    # end of is a filter bar nobody reads
    toolbar = (
        ui.filters("".join(f) + ui.spread() + buttons,
                   )
        + f'<details class="more"><summary>{both("btn.more")}</summary>'
        + ui.filters("".join(more) + ui.spread() + buttons)
        + '</details>'
    )

    chips = ui.chips([
        (both("builds.cards"), "53", d["counts"][0][2]),
        (both("builds.here"), "54", d["counts"][1][2]),
        (both("builds.bytes"), "53", d["counts"][2][2]),
        (both("builds.acts"), "145", d["counts"][3][2]),
        (both("builds.records"), "60", d["counts"][4][2]),
        (both("builds.gap"), "99", d["counts"][5][2]),
        (both("builds.activities"), "80", d["counts"][6][2]),
    ])

    cols = [
        Col('<input type="checkbox" aria-label="tick all" style="width:auto">', kind="c",
            draw=lambda r: '<input type="checkbox" style="width:auto" aria-label="tick">',
            width="28px"),
        Col(tr("col.build_id"), key="id",
            draw=lambda r: code(r["build_id"], f'/analysis/{r["build_id"]}')),
        Col(tr("col.tree") + " / " + tr("col.branch"), key="tree-branch", draw=_tree_branch),
        Col(tr("col.created"), key="date", kind="n", draw=lambda r: _stamp(r["created"])),
        Col(tr("col.card"), kind="c", draw=_artifact_ticks, width="104px"),
        Col(tr("col.bytes"), kind="n",
            draw=lambda r: f'{r["bytes_mib"]:.1f} MiB' if r["bytes_mib"] else '<span class="dash">&mdash;</span>'),
        Col(tr("col.acts"), kind="n", key="acts", draw=_acts_cell),
        Col(tr("col.api_says"), key="api", draw=_api_cell),
        Col(tr("col.ran"), draw=_ran_cell),
    ]
    body = ui.table(cols, d["builds"])

    table_panel = ui.panel(
        both("page.builds.table"),
        body,
        sub=both("page.builds.table_sub", n=len(d["builds"])),
        tools=(ui.checkbox("all", both("jobs.tick", n=len(d["builds"])))
               + ui.btn(both("builds.pull_selected"), "primary sm")
               + ui.btn(both("builds.record"), "sm")),
        flush=True,
    )

    pulls = ui.panel(
        both("builds.pulls"), ui.table([
            Col(tr("col.when"), key="date", kind="n", draw=lambda r: _stamp(r["when"])),
            Col(tr("col.build_id"), key="id", draw=lambda r: code(r["build_id"][:16] + "…")),
            Col(both("builds.artifacts"), kind="n"),
            Col(tr("col.bytes"), kind="n",
                draw=lambda r: f'{r["bytes_raw"]:,} <span class="muted">({r["mib"]})</span>'),
            Col(both("builds.transferred"), kind="n",
                draw=lambda r: f'{r["transferred"]}' if r["transferred"] else '<span class="dash">0</span>'),
            Col(both("builds.hosts"), draw=lambda r: f'<code>{esc(r["hosts"])}</code>'),
            Col(both("builds.error"), draw=lambda r: (
                f'<span class="pill bad">{esc(r["error"])}</span>' if r["error"]
                else '<span class="dash">&mdash;</span>')),
        ], d["pulls"], empty=both("shell.live_empty")),
        sub=both("builds.pulls_sub"),
        collapsible=True, open_=False, flush=True,
    )

    local = ui.panel(
        both("builds.local_title"),
        ui.panel(both("builds.local_sub"), ui.actions(
            ui.btn(both("builds.make_image"), "primary sm")
            + ui.btn(both("builds.index"), "sm"),
            ui.hint("Build.make() writes the card, the artifacts and the provenance in one act")),
            flush=False),
        sub=both("builds.local_sub"),
        collapsible=True, open_=False,
    )

    return (toolbar
            + ui.cpanel(chips, sub=both("page.builds.chips"))
            + table_panel + pulls + local + ui.foot(d))


def _tree_branch(r: dict) -> str:
    return (f'<span class="tree">{esc(r["tree"])}</span>'
            f'<span class="muted"> / </span><span class="br">{esc(r["branch"])}</span>')


def _stamp(iso: str) -> str:
    """A timestamp: the date in the ink, the time in the soft colour.

    The page sorts by these strings, so they are printed in one shape everywhere -
    `2026-09-20T01:05` - and the reader parses them at a glance instead of at a
    second reading.  A trailing `Z` is kept: it is the one thing that says whether
    the record's clock is UTC.
    """
    if not iso:
        return '<span class="dash">&mdash;</span>'
    day, _, rest = iso.partition("T")
    z = "Z" if rest.endswith("Z") else ""
    return f'<span class="nowrap">{esc(day)}<span class="muted"> {esc(rest.rstrip("Z"))}{z}</span></span>'


def _artifact_ticks(r: dict) -> str:
    out = []
    for key, word in ARTIFACTS:
        present = r["checks"].get(key)
        out.append(f'<span title="{esc(key)}">{ui.tick(present)}</span>')
    return f'<span style="display:inline-flex;gap:7px">{"".join(out)}</span>'


def _acts_cell(r: dict) -> str:
    if not r["acts"]:
        return '<span class="dash">&mdash;</span>'
    title = f'{r["acts_host"]} {r["acts_when"]}' if r["acts_host"] else ""
    return (f'<a href="#acts" title="{esc(title)}">{ui.pill(str(r["acts"]), tone_override="plain")}'
            f'</a>')


def _api_cell(r: dict) -> str:
    if r["api"] is None:
        return (f'<span class="pill idle bare">{both("builds.no_remote", n=50)}</span>')
    state, result, node = r["api"]
    return (f'{ui.pill(result, tone_override=ui.tone(result))}'
            f'<span class="muted" style="font-size:11px"> {esc(state)}</span><br>'
            f'<span class="id">{code(node)}</span>')


def _ran_cell(r: dict) -> str:
    ran = [(t, v) for t, v in r["ran"] if v]
    if not ran:
        return '<span class="dash">never run</span>'
    out = []
    for test, verdict in r["ran"]:
        if not verdict:
            out.append(f'<span class="dash" title="{esc(test)}">&mdash;</span>')
        else:
            out.append(ui.pill(f'{test} {verdict}', tone_override=ui.tone(verdict)))
    return f'<span style="display:inline-flex;gap:4px;flex-wrap:wrap">{"".join(out)}</span>'


# ═════════════════════════════════════════════════════════════════════════ jobs
def jobs(d: dict) -> str:
    """Which (build x test) pairs have no record, and what the ledger says for the rest.

    The two halves are one page on purpose: the queue is what is *not* known and
    the ledger is what is, and a reader who has to change pages to compare them
    cannot tell a pair that failed from a pair that never ran.
    """
    toolbar = ui.filters(
        ui.field(both("filter.tree"), ui.multi("tree", ["net-next", "mainline"], d["trees"],
                                               "add a tree"), "w-lg")
        + ui.field(both("filter.test"), ui.select("test", ["any"] + d["tests"]))
        + ui.field(both("filter.run"), ui.select("ran", ["any", "pass", "fail", "never"]), "w-sm")
        + ui.field(both("filter.verdict"), ui.select("verdict", ["any", "pass", "fail", "incomplete"]))
        + ui.field(both("filter.days"), ui.number_input("days", 0), "w-sm")
        + ui.field(both("filter.limit"), ui.number_input("limit", 60), "w-sm")
        + ui.spread()
        + ui.link_btn(both("btn.reset"), "/jobs", "sm")
        + ui.btn(both("btn.apply"), "primary sm"),
    )

    gap_rows = [r for r in d["gap"] if r["gap"]]
    queue = ui.panel(
        both("page.jobs.queue"),
        ui.table([
            Col('<input type="checkbox" aria-label="tick all" style="width:auto">', kind="c",
                draw=lambda r: ('<input type="checkbox" style="width:auto" aria-label="tick">'
                                if r["ready"] else
                                '<input type="checkbox" style="width:auto" disabled '
                                'title="an artifact this test needs is not on disk">'),
                width="28px"),
            Col(tr("col.build_id"), key="id", draw=lambda r: code(r["build_id"], f'/analysis/{r["build_id"]}')),
            Col(tr("col.tree"), key="tree", draw=lambda r: f'<span class="tree">{esc(r["tree"])}</span>'),
            Col(tr("col.test"), key="test", draw=lambda r: f'<code>{esc(r["test"])}</code>'),
            Col(tr("col.needs"), draw=lambda r: f'<span class="muted">{esc(r["needs"])}</span>'),
            Col(tr("col.ready"), kind="c",
                draw=lambda r: ui.pill("ready") if r["ready"] else ui.pill("missing")),
            Col(tr("col.runs"), kind="n", key="runs", draw=lambda r: esc(r["runs"])),
            Col(tr("col.last"), kind="c",
                draw=lambda r: ui.pill(r["last"]) if r["last"] else '<span class="dash">&mdash;</span>'),
            Col(tr("col.when"), kind="n", draw=lambda r: _stamp(r["when"])),
            Col("", kind="", width="120px",
                draw=lambda r: (ui.btn(f'run {esc(r["test"])}', "primary sm") if r["ready"]
                                else '<span class="dash">needs an artifact</span>')),
        ], gap_rows, empty=tr("jobs.none")),
        sub=both("page.jobs.queue_sub"),
        tools=(ui.checkbox("all", both("jobs.tick", n=len(gap_rows)))
               + ui.btn(both("jobs.run_now"), "primary sm")),
        flush=True,
    )

    ledger = ui.panel(
        both("page.jobs.ledger"),
        ui.table([
            Col(tr("col.build_id"), key="id", draw=lambda r: code(r["build_id"][:16] + "…", f'/analysis/{r["build_id"]}')),
            Col(tr("col.test"), key="test", draw=lambda r: f'<code>{esc(r["test"])}</code>'),
            Col(tr("col.verdict"), kind="c", key="verdict",
                draw=lambda r: ui.pill(r["verdict"])),
            Col(tr("col.exit"), kind="n", draw=lambda r: esc(r["exit"])),
            Col(tr("col.source"), kind="c", draw=_source_cell),
            Col(tr("col.when"), key="date", kind="n", draw=lambda r: _stamp(r["when"])),
            Col(tr("col.detail"), kind="wrapc", draw=lambda r: esc(r["detail"])),
            Col("", kind="acts-cell", width="110px",
                draw=lambda r: ui.link_btn(both("col.log"), f'/runs#{r["build_id"]}', "sm")),
        ], d["ledger"]),
        sub=both("page.jobs.ledger_sub", n=len(d["ledger"])),
        tools=(ui.btn(both("jobs.ledger_full"), "sm")),
        flush=True,
    )

    runner = ui.panel(
        both("jobs.run_day"),
        ui.actions(
            ui.btn(both("jobs.run_day"), "primary sm")
            + ui.btn(both("jobs.run_newest"), "sm"),
            ui.hint("one command per test, so a day of builds is one activity per test "
                    "and the ledger gets a row per pair that answered")),
        collapsible=True, open_=False,
    )

    return (toolbar + queue
            + ui.panel("", ui.note(tr("jobs.worker_rows") + " &mdash; "
                                   + 'the <code>source</code> column is who wrote it, '
                                     'and a worker writes <code>worker</code>.'), flush=True)
            + ledger + runner + ui.foot(d))


def _source_cell(r: dict) -> str:
    """Who wrote the record - which is the column that answers "did my worker run?"."""
    tone = {"worker": "info", "runday": "plain", "table": "plain", "index": "plain"}.get(r["source"], "plain")
    return ui.pill(r["source"], tone_override=tone)


# ═══════════════════════════════════════════════════════════════════════ worker
def worker(d: dict) -> str:
    """What the poll loop is doing, what it claimed, and what came back.

    The panel the old page did not have is the last one: the ledger's rows with
    `source=worker`.  It costs no new storage - the records are already there -
    and without it the answer to "did it do anything" is a cursor that moves
    whether or not anything was claimed.
    """
    w = d["worker"]
    state = ui.pill("running") if w["running"] else ui.pill("idle")

    status = (
        f'<div class="row" style="gap:14px;align-items:baseline">'
        f'{state}'
        f'<span class="q">{both("worker.pid")} <b>{w["pid"]}</b></span>'
        f'<span class="q">{both("worker.since")} <b>{esc(w["started"])}</b></span>'
        f'<span class="q">{both("worker.uptime")} <b>{esc(w["uptime"])}</b></span>'
        f'<span class="grow"></span>'
        f'{ui.btn(both("worker.stop"), "sm danger")}'
        f'{ui.btn(both("worker.start"), "primary sm")}'
        f'</div>'
        f'<p class="q" style="margin-top:7px;word-break:break-all">{esc(w["argv"])}</p>'
        f'<p class="hint" style="margin-top:7px">{tr("worker.where_results")}</p>'
    )

    toolbar = ui.filters(
        ui.field(both("filter.platform"), ui.select("platform", ["qemu-riscv64", "qemu-arm64"]))
        + ui.field(both("filter.runtime"), ui.select("runtime", ["pull-labs-riscv", "pull-labs-arm64"]))
        + ui.field(both("filter.state"), ui.select("state", ["any", "available", "done", "running"]))
        + ui.field(both("filter.job"), ui.text_input("job", "", "node id or name"), "w-lg")
        + ui.field(both("filter.since"), ui.text_input("since", "2026-09-20T08:20:25Z"), "w-lg")
        + ui.field(both("filter.limit"), ui.number_input("limit", 50), "w-sm")
        + ui.field(both("filter.mode"), ui.seg("mode", [("once", tr("worker.once")),
                                                        ("resident", tr("worker.resident"))],
                                               "resident"), "w-md")
        + ui.spread() + ui.link_btn(both("btn.reset"), "/worker", "sm")
        + ui.btn(both("btn.apply"), "primary sm"))

    state_file = ui.panel(
        both("worker.state_file"),
        ui.kv([
            (f'<code>{esc(w["state_file"])}</code>', ""),
            (tr("col.cursor"), esc(w["cursor"])),
            (tr("col.seen"), f'<b>{w["seen"]}</b>'),
            (tr("col.pending"), esc(w["pending"])),
        ]) + '<div style="height:10px"></div>' + ui.note(tr("worker.cursor_note"), warn=True),
        sub=both("worker.state_sub"),
    )

    queue = ui.panel(
        both("worker.queue"),
        ui.table([
            Col(tr("col.node"), key="id", draw=lambda r: code(r["node_id"], f'/worker?job={r["node_id"]}')),
            Col(tr("col.name"), key="test", draw=lambda r: f'<code>{esc(r["name"])}</code>'),
            Col(tr("col.state"), kind="c", key="state", draw=lambda r: ui.pill(r["state"])),
            Col(tr("col.result"), kind="c", key="verdict",
                draw=lambda r: ui.pill(r["result"]) if r["result"] else '<span class="dash">&mdash;</span>'),
            Col(tr("col.platform"), draw=lambda r: f'<code>{esc(r["platform"])}</code>'),
            Col(tr("col.runtime"), draw=lambda r: f'<code>{esc(r["runtime"])}</code>'),
            Col(tr("col.created"), key="date", kind="n", draw=lambda r: _stamp(r["created"])),
            Col(tr("col.claimed"), kind="c",
                draw=lambda r: f'<span class="tick">{tr("worker.claimed")}</span>' if r["claimed"]
                else f'<span class="muted">{tr("worker.not_claimed")}</span>'),
            Col(tr("col.definition"), kind="acts-cell", width="80px",
                draw=lambda r: ui.link_btn("json", f'/worker?job={r["node_id"]}', "sm")),
        ], d["queue"]),
        sub=both("worker.queue_sub"),
        flush=True,
    )

    mine = [r for r in d["ledger"] if r["source"] == "worker"][:8]
    done = ui.panel(
        both("worker.done_here"),
        ui.table([
            Col(tr("col.when"), key="date", kind="n", draw=lambda r: _stamp(r["when"])),
            Col(tr("col.build"), key="id", draw=lambda r: code(r["build_id"][:16] + "…", f'/analysis/{r["build_id"]}')),
            Col(tr("col.test"), draw=lambda r: f'<code>{esc(r["test"])}</code>'),
            Col(tr("col.verdict"), kind="c", draw=lambda r: ui.pill(r["verdict"])),
            Col(tr("col.took"), kind="n", draw=lambda r: esc(r["took"]) if r.get("took") else '<span class="dash">&mdash;</span>'),
            Col(tr("col.log"), kind="acts-cell", width="70px",
                draw=lambda r: ui.link_btn(both("col.log"), f'/runs#{r["build_id"]}', "sm")),
            Col(tr("col.detail"), kind="wrapc", draw=lambda r: esc(r["detail"])),
        ], mine),
        sub=both("worker.done_here_sub"),
        flush=True,
    )

    return toolbar + ui.panel("", status, flush=False) + state_file + queue + done + ui.foot(d)


# ═════════════════════════════════════════════════════════════════════════ runs
def runs(d: dict) -> str:
    """Every background process this console started, and whether it is still going.

    The note above the table is the one sentence the old page left out: a worker
    that has claimed five jobs still has one row here, and a reader who expects
    five rows concludes the worker is broken.
    """
    toolbar = ui.filters(
        ui.field(both("filter.kind"), ui.select("kind", ["any"] + d["kinds"]), "w-md")
        + ui.field(both("filter.state"), ui.select("state", ["any", "running", "done", "failed"]))
        + ui.field(both("filter.api"), ui.select("api", d["apis"], "local"))
        + ui.field(both("filter.text"), ui.text_input("text", "", "id, argument, path"), "w-xl")
        + ui.spread() + ui.link_btn(both("btn.reset"), "/runs", "sm")
        + ui.btn(both("btn.apply"), "primary sm"))

    body = ui.table([
        Col(tr("col.id"), key="id", draw=lambda r: f'<span id="{esc(r["id"])}">{code(r["id"])}</span>'),
        Col(tr("col.kind"), key="kind", draw=lambda r: f'<code>{esc(r["kind"])}</code>'),
        Col(tr("col.state"), kind="c", key="state", draw=lambda r: ui.pill(r["state"])),
        Col(tr("col.age"), kind="n", draw=lambda r: esc(r["age"])),
        Col(tr("col.exit"), kind="n",
            draw=lambda r: esc(r["exit"]) if r["exit"] is not None
            else f'<span class="muted">{tr("shell.exit_none")}</span>'),
        Col(tr("col.what"), kind="trunc", draw=lambda r: esc(r["what"])),
        Col(tr("col.argv"), kind="trunc",
            draw=lambda r: f'<span class="q" title="{esc(r["argv"])}">{esc(r["argv"])}</span>'),
        Col("", kind="acts-cell", width="130px",
            draw=lambda r: (ui.link_btn(both("col.log"), f'/runs/{r["id"]}/log', "sm")
                            + (ui.btn(both("shell.cancel"), "sm danger")
                               if r["state"] == "running" else ""))),
    ], d["runs"])

    table_panel = ui.panel(
        both("page.runs.table"),
        ui.note(tr("runs.note")) + '<div style="height:10px"></div>' + body,
        sub=both("page.runs.table_sub", n=len(d["runs"])),
        tools=(ui.btn(both("btn.fresh"), "sm")),
        flush=True,
    )
    return toolbar + table_panel + ui.foot(d)


# ═════════════════════════════════════════════════════════════════════ analysis
def analysis(d: dict) -> str:
    """Is this getting better or worse: the order, the comparison, and the run of records.

    Three panels answer it three ways and they are not the same question - the bar
    list is one build's own counts, the timeline is one test over time, and the
    delta columns are the config between two neighbours.  Keeping them apart is
    what makes "the line went up" mean something specific.
    """
    toolbar = ui.filters(
        ui.field(both("filter.test"), ui.select("test", d["tests"], "boot"))
        + ui.field(both("filter.sort"), ui.select("sort", d["sorts"], "date"), "w-lg")
        + ui.field(both("filter.limit"), ui.number_input("limit", 50), "w-sm")
        + ui.field(both("filter.delta"), ui.number_input("delta", 3, 0, 12), "w-sm")
        + ui.field(both("filter.point"), ui.text_input("point", "", "a build id"), "w-lg")
        + ui.spread() + ui.link_btn(both("btn.reset"), "/analysis", "sm")
        + ui.btn(both("btn.apply"), "primary sm"))

    picks = ui.panel(
        both("page.analysis.picks"),
        ui.table([
            Col(tr("col.rank"), kind="n", key="rank", width="34px"),
            Col("", kind="acts-cell", width="96px",
                draw=lambda r: (ui.link_btn(both("analysis.left"), "#", "sm")
                                + ui.link_btn(both("analysis.right"), "#", "sm"))),
            Col(tr("col.build"), key="id", draw=_build_cell),
            Col("describe", key="series", kind="trunc",
                draw=lambda r: f'<code>{esc(r["describe"])}</code>'),
            Col(tr("col.verdict"), kind="c", key="verdict", draw=_verdict_counts),
            Col(tr("col.delta_up"), draw=lambda r: ui.delta(
                r["delta_up"], first=r["rank"] == 1), width="120px"),
            Col(tr("col.delta_down"), draw=lambda r: ui.delta(
                r["delta_down"], last=r["rank"] == len(d["picks"])), width="120px"),
        ], d["picks"]),
        sub=both("page.analysis.picks_sub"),
        tools=(ui.hint(tr("analysis.no_delta", n=3))),
        flush=True,
    )

    bars = ui.panel(
        both("page.analysis.bars"),
        ui.bars(d["bars"])
        + '<div style="height:10px"></div>'
        + ui.hint('<span class="pill ok">pass</span> '
                  '<span class="pill bad">fail</span> '
                  '<span class="pill warn">incomplete</span> '
                  '&mdash; the three numbers are <code>this build&rsquo;s own</code>, '
                  'not a running total'),
        sub=both("page.analysis.bars_sub"),
    )

    timeline = ui.panel(
        both("page.analysis.timeline"),
        ui.table([
            Col(tr("col.test"), key="test", draw=lambda r: f'<code>{esc(r["test"])}</code>'),
            Col(tr("col.runs"), kind="n", key="runs", width="64px"),
            Col(tr("col.last"), kind="c", draw=lambda r: ui.pill(r["last"])),
            Col(tr("col.regressions"), kind="n", key="verdict", width="96px",
                draw=lambda r: (f'<span class="cross">{r["regressions"]}</span>' if r["regressions"]
                                else '<span class="muted">0</span>')),
            Col(tr("col.timeline"), draw=lambda r: ui.spark(r["marks"])),
        ], d["timelines"]),
        sub=both("page.analysis.timeline_sub"),
        flush=True,
    )

    drift = ui.panel(
        both("page.analysis.drift"),
        ui.table([
            Col(both("analysis.left"), kind="", draw=lambda r: f'<span class="id">{code(r["left"][:16] + "…")}</span>'),
            Col("", kind="c", width="40px", draw=lambda r: '<span class="muted">&rarr;</span>'),
            Col(both("analysis.right"), kind="", draw=lambda r: f'<span class="id">{code(r["right"][:16] + "…")}</span>'),
            Col("&plusmn;", draw=lambda r: ui.delta((r["added"], r["removed"], r["changed"]))),
            Col("", kind="acts-cell", width="90px",
                draw=lambda r: ui.link_btn(both("analysis.compare"), "#", "sm")),
        ], d["drift"]),
        sub=both("page.analysis.drift_sub"),
        collapsible=True, open_=False, flush=True,
    )

    pair = ui.panel(
        both("analysis.compare"),
        f'<div class="split">'
        f'<div><p class="hint" style="margin-bottom:6px">{esc(d["drift"][0]["left"])}</p>'
        f'<textarea rows="12" readonly spellcheck="false"># the left config, as read from '
        f'var/configs/\nCONFIG_RISCV=y\nCONFIG_64BIT=y\nCONFIG_SMP=y\nCONFIG_KVM=y\n'
        f'CONFIG_KASAN=y\n</textarea></div>'
        f'<div><p class="hint" style="margin-bottom:6px">{esc(d["drift"][0]["right"])}</p>'
        f'<textarea rows="12" readonly spellcheck="false">CONFIG_RISCV=y\nCONFIG_64BIT=y\n'
        f'CONFIG_SMP=y\nCONFIG_KVM=n\nCONFIG_KASAN=n\nCONFIG_KCSAN=y\n</textarea></div>'
        f'</div>'
        f'<p class="hint" style="margin-top:8px">'
        f'<span class="delta"><span class="plus">+3</span>'
        f'<span class="minus">&minus;1</span><span class="same">~2</span></span> '
        f'&mdash; added, removed, changed; the pair is cached in <code>var/configs/</code> '
        f'after the first read, so the first comparison of a page is the only slow one</p>',
        sub=both("page.analysis.drift_sub"),
        collapsible=True, open_=False,
    )

    return toolbar + picks + timeline + bars + drift + pair + ui.foot(d)


def _verdict_counts(r: dict) -> str:
    if r["verdict"] is None:
        return '<span class="dash">not recorded</span>'
    total, failed, skipped = r["total"], r["failed"], r["skipped"]
    return (f'{ui.pill(r["verdict"])}'
            f'<br><span class="q">{total} total'
            f'<span class="muted"> / </span>{failed} fail'
            f'<span class="muted"> / </span>{skipped} skip</span>')


def _build_cell(r: dict) -> str:
    """A build in the analysis list: the id, and the pair that places it.

    The tree and branch go on a second line because the order being read is often
    `tree-branch`, and then the pair is the row's address and the id is the detail.
    """
    return (f'{code(r["build_id"][:16] + "…", "/analysis/" + r["build_id"])}<br>'
            f'<span class="muted" style="font-size:11px">'
            f'{esc(r["tree"])} / {esc(r["branch"])}</span>')


PAGES = {
    "/builds": builds,
    "/jobs": jobs,
    "/runs": runs,
    "/worker": worker,
    "/analysis": analysis,
}
