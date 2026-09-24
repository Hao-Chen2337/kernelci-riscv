# SPDX-License-Identifier: LGPL-2.1-or-later
"""`/runs`: every background process this console started, and whether it is still going.

One table, grouped by kind, with the two things a row can do beside it: read its log
(`GET /runs/<id>/log`, the whole file as `text/plain`) and cancel it (`POST
/api/runs/<id>/cancel`, an empty-bodied form, drawn only while the row is still
running).  One row is one process whatever it has done - a `worker` that claimed five
jobs is one activity and one row, and a reader who expects five rows concludes the
worker is broken.

**The fold is filter state, not a trick of the renderer.**  Measured on this
deployment, 42 of the 80 activities are `table.py index` - the bookkeeping that runs on
a timer - and they used to be interleaved with the run the operator was watching
(「为什么拉取或者这里就 run 也会显示」).  So the `kind` box holds the kinds the page is
showing, filled with "everything but `FOLDED_KINDS`" when the URL states none, and
`data-rows="all"` is written **only** while the rows on screen really are every
activity.  That attribute is what `_JS`'s `drawTable` reads before it replaces this
table, and the poll it answers fetches `/api/runs` with no filter at all: a folded table
marked "all" would have the 42 bookkeeping rows put back two seconds after the page said
they were folded - a filter that silently undoes itself, one level up from the bug
`04-actions.md` §P8a records.  The default is stated where it can be read (the note
under the bar) and undone in one click, and the link spells every kind out rather than
dropping the key: dropping it lands on the folded page again, which is a "show
everything" that shows the same rows.

**The cells keep the shipped script's vocabulary, not the board's.**  `drawTable`
rebuilds every cell of this table from `_JS` every two seconds, so a row drawn with the
design's own cell classes (`n`, `trunc`, `acts-cell`) would change shape on the first
poll.  `shell.BRIDGE_CSS` is the bridge - it gives the script's names (`id`, `num`,
`wrap`, `act`, `.cell-actions`, `.kind-group`, `td.group-first`) the design's look - and
the same rule decides the group caption: it rides in the first cell of its group's first
row and not in a `<tr>` of its own, because the number of rows on this page is how the
activity count is read, and a caption row would make that number mean something else.
The pill is `ui.end_word`'s for the same reason: `_js()` builds the script's copy of that
mapping out of the same function, so the word cannot change when the poll touches the
cell.

**`kind` is this page's own key and `state` is not.**  No other screen reads a kind, and
the fourteen build axes are questions about an API *node* - there is no `arch` on a
`table.py pull` - so the box, the fold, `rows_of` and every link read `kind` as page
state on the request's check (`check.kind`), while `state` is read as the `Filter` field
it shares with `/builds`.  A page that read neither would draw the folded default, ignore
a `?kind=` the reader typed, and answer a question the URL did not ask - which is the one
thing a filter bar must never do.  `api` is carried and **no longer drawn**: `/runs` reads
no API, but the key decides which stack the *next* page reads, and this page's own links
hand it on - which is the half that was ever load-bearing.  Drawn as well, it was a select
whose two options changed nothing: an activity is this deployment's own process tree, so
`?api=local` and `?api=production` rendered the same fifty-one rows line for line.  A
control that narrows nothing is worse than no control, because a reader who sets it
believes the table narrowed (`_bar`'s `hidden=` is the half that keeps it).

**Both axes are sets, and both boxes are chips.**  `kind` always was one - the fold makes
a set the default - and `state` became one when the `Filter` field grew the multi-valued
spelling `/jobs` asked for.  A select drew a seven-kind default as one `(current: …)`
word, and compared a comma list of states against a single row's state, so the box could
not say what the table was doing and the table answered nothing.  `kind` being page state
and not a `Filter` field is why the chips needed one thing from the engine:
`schema.MULTI_PAGE_STATE` names the page-state keys read as a set (`design/serve.py`).

**Nothing here is computed.**  A state is the record's own word, a kind is the
activity's own field, an age is `Run.age()`'s and an exit code is `run.json`'s.  The two
numbers this page prints are both counts of the rows it was handed - the table's own row
count and each group's - so a caption and the rows under it cannot disagree.
"""


from .... import layout
from .... import run as run_mod
from ...forms import _names
from ...schema import FOLDED_KINDS, KIND_ORDER, ROUTE_KEYS, _labels
from ...urls import _carried
from .. import ui, words

# The keys this page reads: `kind` and `state` are its question, `api` is the stack it
# carries and `lang` is the reader's.  Every link written here narrows to this list, so a
# key the check happens to carry - a build window the page never reads - cannot ride on a
# link and become a condition on the page after it.  (`_url`'s own whitelist is by route
# prefix and `/` is a prefix of every route, so it keeps the whole filter; narrowing here
# is what makes this page's links say what this page means.)
CARRY = ROUTE_KEYS["/runs"]

# How much of a command line the argv cell prints.  The number is the shipped script's
# own (`drawTable`'s `argv.slice(0, 60)`) and has to stay that number: that function
# rewrites this cell, and a server that printed more would watch its own row get shorter
# on the first poll.  The whole command is in the cell's `title=`.
ARGV_SHOWN = 60


def runs(view) -> str:
    """The activities screen: the bar, the fold it states, and the table it draws."""
    rows = list(view.rows.get("runs") or ())
    stated = str(getattr(view.check, "kind", "") or "")
    # **A state is one of a set, not one word.**  `state` is the `Filter` field this page
    # shares with `/builds`, and `Filter.from_query` reads a multi-valued axis as every
    # value the query carried (`_named_many`), so `?state=done,failed` arrives here as the
    # comma-joined `"done,failed"` - a string no single row's state ever equals.  Compared
    # with `==` the page answered an empty table to a question that reads as "either",
    # with nothing said: the silent 0 this package refuses everywhere else, and the worse
    # for arriving where a select box used to **refuse the comma outright** - the change
    # that made the field a set turned one loud refusal into one quiet wrong answer.
    # Membership is the fix and the spelling `Filter.accepts` already uses for the same
    # question one page over.
    state = str(getattr(view.check, "state", "") or "")
    states = {one for one in _names(state)}
    folded = not stated and bool(FOLDED_KINDS)
    kinds = stated or (_unfolded(rows) if folded else "")
    wanted = {one for one in _names(kinds)}
    shown = _grouped([one for one in rows
                      if (not wanted or str(one["kind"]) in wanted)
                      and (not states or str(one["state"]) in states)])
    # Only the counts, and over the whole list: `_panel` asks `_groups` for the opening
    # rows of the page it draws, and a caption's number is a fact about the list.
    _, counts = _groups(shown)
    disk = sorted({str(one["kind"]) for one in rows})
    # Every activity is on screen exactly when the filter removed none of them: an empty
    # `kind` means "every kind" (`run_rows`' own rule), and a stated one that covers
    # everything on disk hides nothing either.
    whole = not states and (not wanted or set(disk) <= wanted)
    body = [_bar(view, kinds, state)]
    if folded and kinds:
        body.append(_fold_line(view, ",".join(disk)))
    # This page's own address, filter and all: what each row's 日志 tab leads back to
    # when the reader presses "back to the list" (`ui.log_link`).
    body.append(_panel(view, shown, counts, whole, view.url()))
    return "".join(body)


def _unfolded(rows) -> str:
    """The kinds a plain `/runs` shows: everything the page holds but the bookkeeping.

    `/runs` draws no control for the fourteen build axes and reads no window, because none
    of them filters an activity - there is no `arch` on a `table.py pull` and no `days` on
    a cancel - and a control that changes nothing is the failure this round exists to
    remove.  What is left is `kind`, which is not a `Filter` field, so it arrives as page
    state on the check, beside the `state` the filter does own.
    """
    return ",".join(one for one in sorted({str(one["kind"]) for one in rows})
                    if one not in FOLDED_KINDS)


def _grouped(rows) -> list:
    """The rows by kind in `KIND_ORDER`, each group in the page's own newest-first order.

    A kind this tree has not heard of sorts last rather than disappearing: a `stack` or a
    `verify` activity is a fact about the deployment, not something to hide.  `sorted` is
    stable, so within a kind the newest-first order the data layer produced survives.
    """
    rank = {kind: at for at, kind in enumerate(KIND_ORDER)}
    return sorted(rows, key=lambda one: rank.get(str(one["kind"]), len(rank)))


def _groups(rows) -> tuple:
    """Which row opens each kind's group, and how many rows each group draws.

    The caption is drawn inside the opening row's first cell, so the number of `<tr>`s on
    this page keeps meaning the number of activities - the count a caption row would
    silently change.

    The two answers are asked of different rows, and the caller says which: `opens` is
    read off the page being drawn (the page's first row of a kind is the one that carries
    the caption, or a page that starts mid-group would draw its rows under the previous
    page's heading), while `counts` is read off the whole list (a caption says how many
    of that kind there are, not how many of them happen to be on this page).
    """
    opens, counts = {}, {}
    for one in rows:
        kind = str(one["kind"])
        opens.setdefault(kind, str(one["id"]))
        counts[kind] = counts.get(kind, 0) + 1
    return opens, counts


def _bar(view, kinds, state) -> str:
    """The filter bar: the two axes this page reads, the stack it carries, and apply.

    **Both axes are sets, so both are chips.**  `kind` because this page's own default
    is already seven of the eight kinds, and a select drew that as one `(current: a,b,…)`
    entry: the table was filtered and the box did not say so.  `state` because `runs()`
    compares a row's state by membership now - the select that used to draw it sent one
    value, so a comma list was accepted and then matched nothing (`runs()` says why the
    empty table was the bug and not the filter).

    A value neither menu offers renders as a chip anyway: `ui.multi` draws the chosen
    set, not the offered one, which is the property `_kind_options` used to hand-roll by
    appending a `(current: …)` option so the browser could not fall back to the first
    one.  With chips there is no fallback to prevent.

    **`api` used to be a third field here and is gone.**  It was a select with two
    options that changed nothing: `/runs`'s rows are the activity tree (`var/runs/` and
    the worker's own state), which is this deployment's and not the remote API's, so
    `?api=local` and `?api=production` rendered the same fifty-one rows line for line -
    a control that answers a question the page does not ask is worse than no control,
    because a reader who sets it believes the table narrowed.  The *key* still rides
    (`_carried` below), which is what it is for: the rest of the console is on one API
    and this page must not be the one that changes it.
    """
    lang = view.lang
    return ui.filters(
        ui.field(words.both(lang, "word.kind"),
                 ui.multi("kind", _names(kinds), _offered(view, "kinds"),
                          placeholder="state.any", label="word.kind", lang=lang))
        + ui.field(words.both(lang, "word.state"),
                   ui.multi("state", _names(state), _offered(view, "run_states"),
                            labels=_labels("run_state", lang),
                            placeholder="state.any", label="word.state", lang=lang)),
        _buttons(view), action=view.route, auto=True,
        # Everything this route reads that this bar draws no control for.  The clock is
        # the one that showed: `tz` is a `Filter` field outside `FILTER_ORDER` and the
        # top bar's switch is the one control (`shell.tz_switch`), so without this an
        # `apply` here answered in the default clock while the bar above still said
        # otherwise.  `text`, and anything the reader set by hand, ride the same way.
        hidden=_carried(view.route, view.check, ("kind", "state")))


def _buttons(view) -> str:
    """The bar's two ends: the page with nothing asked of it, and the button that applies.

    `apply` is a real submit button and not the board's `type="button"`: the design's own
    bars draw a button that cannot submit anything, and with the script off - the state
    `data-auto` exists to make bearable - it is the only way to change the question.
    """
    clear = ui.link_btn(words.both(view.lang, "btn.reset"),
                        view.url("", carry=CARRY, kind="", state=""), "sm", lang=view.lang)
    return (clear + '<button type="submit" class="btn primary sm">'
            + words.both(view.lang, "btn.apply") + "</button>")


def _offered(view, key) -> list:
    """The values a box's menu offers: what this console can start, not what is on disk.

    The list is the board's own - `rows["kinds"]` is the eight kinds a button can start,
    `rows["run_states"]` the four an activity can be in - and not the values that happen
    to be present: a kind nobody has run yet is still one a button can start.

    A value the menu does not carry is **not dropped**: `ui.multi` draws the chosen set
    whatever the menu holds, so a URL naming something this console has never heard of
    still shows the reader the value it asked about.  A state with no catalogue word for
    it loses its translation and not its chip, which is `_labels`' own rule.
    """
    return [str(one) for one in view.rows.get(key) or ()]


def _fold_line(view, every) -> str:
    """The one line that says a default is hiding rows, and undoes it in one click.

    `runs.folded_note` carries `<code>`, which is why it is rendered in this response's
    language (`view.t`) instead of as a span the script could swap: the swap writes text,
    and a sentence with markup in it would arrive as those characters.
    """
    link = view.link("", words.both(view.lang, "runs.show_all"), carry=CARRY, kind=every)
    return ui.hint(view.t("runs.folded_note", link=link))


def _panel(view, shown, counts, whole, back: str = "") -> str:
    """The table in a panel of its own: how many rows, then one page of activities.

    The spacer is the board's own: a `flush` body has no padding, and the table needs the
    gap above it that the design draws.  `back` rides down to the log links in the last
    column, which are the only cells on this page that leave it.

    The page is `Filter.offset`'s - this page's own list, so the bare key and no
    `schema.LIST_OFFSETS` name - and `counts` is asked of the **whole** list while `opens`
    is asked of the page: a caption says how many of that kind there are, and the row
    that carries it has to be a row this page actually draws.

    `data-rows="all"` is the shipped script's licence to rewrite this table every two
    seconds (`drawTable`, `liveTableAll`), and it is true only while the table **is**
    every activity - unfiltered, first page, nothing paged out.  Past that the attribute
    is left off and the poll stops rewriting the table: rows the reader paged to are not
    rows a two-second timer gets to replace.  What still arrives live is the panel above
    and the finish notice; a change to the digest reloads the page, which lands the
    reader back on the page they asked for.
    """
    lang = view.lang
    limit = max(1, view.check.limit)
    total = len(shown)
    # An offset past the end (a URL typed by hand, a list that shrank under the reader)
    # lands on the last page rather than on an empty table under a sub-line counting rows.
    offset, page = ui.page_slice(shown, view.check.offset, limit)
    opens, _ = _groups(page)
    whole = whole and offset == 0 and total <= limit
    body = ('<div style="height:10px"></div>'
            + ui.table(_cols(opens, counts, lang, back), page,
                       empty=words.both(lang, "empty.no_activity"), table_id="runs",
                       rows_of="all" if whole else "", kinds=KIND_ORDER, lang=lang)
            + ui.pager(view, total, limit, offset))
    return ui.panel("counts.activities", body, flush=True, lang=lang,
                    sub=words.both(lang, "filter.cap_rows", n=total))


def _cols(opens, counts, lang, back: str = "") -> tuple:
    """The eight columns, in the vocabulary the script that re-draws them writes.

    The headers are the board's own words for these cells (`word.id` is 编号 and `word.kind`
    is 种类, which is the line the board drew between a value and a label); the cell classes
    are `drawTable`'s, because a cell with the design's own class would lose its look the
    first time the poll replaced it.
    """
    return (
        ui.Col("word.id", kind="id", draw=lambda one: _id_cell(one, opens, counts, lang)),
        ui.Col("word.kind", draw=lambda one: ui.esc(one["kind"])),
        ui.Col("word.state", draw=lambda one: _state_cell(one, lang)),
        ui.Col("col.age", kind="num", draw=lambda one: ui.esc(one["age"])),
        ui.Col("col.exit", kind="num", draw=lambda one: _exit_cell(one, lang)),
        ui.Col("col.what_run", kind="wrap", draw=lambda one: ui.esc(one["what"])),
        ui.Col("word.argv", kind="wrap", draw=lambda one: _argv_cell(one)),
        ui.Col("", kind="act", width="130px", draw=lambda one: _acts_cell(one, lang, back)),
    )


def _id_cell(one, opens, counts, lang) -> str:
    """The id cell: the group's caption when it opens, then the id and where it lives.

    The caption is the group's kind and the number of rows drawn under it, and the id's
    `title=` is the activity's own directory - the two files a reader has to open by hand
    when the page cannot answer.
    """
    kind = str(one["kind"])
    caption = ""
    if opens.get(kind) == str(one["id"]):
        caption = (f'<span class="kind-group">'
                   f'{words.both(lang, "runs.group", kind=ui.esc(kind), n=counts[kind])}</span>')
    home = layout.runs(str(one["id"]))
    return (caption
            + f'<code {words.attr(lang, "title", "runs.dir_title", dir=home)}>'
            f'{ui.esc(one["id"])}</code>')


def _state_cell(one, lang) -> str:
    """The state as a pill, worded by the exit code and coloured by the state.

    The two are different answers and both are wanted: `Run._settle` writes one state for
    exit 1 and exit 3 alike, and "tests failed" is not the word for a command that
    crashed.  `ui.end_word` owns that mapping because `_js()` builds the script's copy of
    it from the same function - the pill cannot change its word when the poll rewrites it.
    """
    state = str(one["state"])
    return ui.pill(state, label=ui.end_word(state, one["exit"], lang), lang=lang)


def _exit_cell(one, lang) -> str:
    """The exit code, or the dash the script writes for a code nobody has seen.

    A `drift` activity's code is its *answer* (0 no drift, 1 drift) and not a verdict on
    the command, so that row's cell carries the sentence in its `title=` - the same
    `title=` `drawTable` writes on the same cell.
    """
    code = "-" if one["exit"] is None else ui.esc(one["exit"])
    if str(one["kind"]) == "drift":
        return f'<span {words.attr(lang, "title", "analysis.drift_hint")}>{code}</span>'
    return code


def _argv_cell(one) -> str:
    """The command line: monospace, cut where the script cuts it, whole in the `title=`."""
    argv = str(one["argv"])
    return ui.code(argv[:ARGV_SHOWN], title=argv)


def _acts_cell(one, lang, back: str = "") -> str:
    """What a row can do: read its log, and cancel it while it is still running.

    The log is the route itself - `/runs/<id>/log` answers the whole file - in a tab of its
    own, so a click, a middle-click and a copied address all give the same thing; there is
    no inline box because this page holds no log text to put in one.  That tab carries this
    page as its `?back=`, because a tab of its own has no Back button into the table it was
    opened from (`ui.log_link`).  Cancel is an empty-bodied POST: the id is in the path, the
    answer is JSON, and `_JS` is what keeps the reader on the page where the row is about to
    end.  A finished row has no cancel, because `Run.cancel` on a settled process is a
    button that cannot do what it says.
    """
    home = ui.esc(one["id"])
    acts = [ui.log_link(one["id"], words.both(lang, "link.log"), back)]
    if str(one["state"]) == run_mod.RUNNING:
        acts.append(f'<form method="post" action="/api/runs/{home}/cancel">'
                    f'<button class="btn">{words.both(lang, "js.cancel")}</button></form>')
    return f'<span class="cell-actions">{"".join(acts)}</span>'


PAGES = {"/runs": runs}
