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
thing a filter bar must never do.  `api` is carried and drawn for the same reason it was
carried before: `/runs` reads no API, but the key decides which stack the *next* page
reads, and this page's own links hand it on.

**Nothing here is computed.**  A state is the record's own word, a kind is the
activity's own field, an age is `Run.age()`'s and an exit code is `run.json`'s.  The two
numbers this page prints are both counts of the rows it was handed - the table's own row
count and each group's - so a caption and the rows under it cannot disagree.
"""

from functools import partial

from .... import layout
from .... import run as run_mod
from ....i18n import CATALOGUE
from ...schema import FOLDED_KINDS, KIND_ORDER, ROUTE_KEYS
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
    state = str(getattr(view.check, "state", "") or "")
    folded = not stated and bool(FOLDED_KINDS)
    kinds = stated or (_unfolded(rows) if folded else "")
    wanted = {one for one in kinds.split(",") if one}
    shown = _grouped([one for one in rows
                      if (not wanted or str(one["kind"]) in wanted)
                      and (not state or str(one["state"]) == state)])
    opens, counts = _groups(shown)
    disk = sorted({str(one["kind"]) for one in rows})
    # Every activity is on screen exactly when the filter removed none of them: an empty
    # `kind` means "every kind" (`run_rows`' own rule), and a stated one that covers
    # everything on disk hides nothing either.
    whole = not state and (not wanted or set(disk) <= wanted)
    body = [_bar(view, kinds, state)]
    if folded and kinds:
        body.append(_fold_line(view, ",".join(disk)))
    body.append(_panel(shown, opens, counts, whole, view.lang))
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
    """
    opens, counts = {}, {}
    for one in rows:
        kind = str(one["kind"])
        opens.setdefault(kind, str(one["id"]))
        counts[kind] = counts.get(kind, 0) + 1
    return opens, counts


def _bar(view, kinds, state) -> str:
    """The filter bar: the two axes this page reads, the stack it carries, and apply."""
    lang = view.lang
    label = partial(ui.word, lang=lang)
    return ui.filters(
        ui.field(words.both(lang, "word.kind"),
                 ui.select("kind", _kind_options(view, kinds), kinds, labeler=label))
        + ui.field(words.both(lang, "word.state"),
                   ui.select("state", _state_options(view, state), state, labeler=label))
        + ui.field(words.both(lang, "filter.api"),
                   ui.select("api", _api_options(view), _api_in_force(view), labeler=label)),
        _buttons(view), action=view.route, auto=True)


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


def _kind_options(view, kinds) -> list:
    """The `kind` box: the kinds a button can start, plus the value the URL actually asked for.

    The list is `rows["kinds"]` - the eight kinds this console's own buttons start, which
    is the list the board draws - and not the kinds that happen to be on disk: a kind
    nobody has run yet is still one a button can start.  A URL naming a kind no option
    carries is **appended** rather than dropped: with nothing selected the browser falls
    back to the first option, so the next apply would send a different value than the one
    in the URL - how `?missing=kernel` used to become "(any)".  A kind is a value, so it
    stays the same word in both languages and only the two bracketed options are words.
    """
    offered = [str(one) for one in view.rows.get("kinds") or ()]
    options = [("", "state.any_paren")]
    options += [(one, one) for one in offered]
    if kinds and kinds not in offered:
        options.append((kinds, words.both(view.lang, "state.current_paren", value=kinds)))
    return options


def _state_options(view, state) -> list:
    """The `state` box: the four states an activity can be in, and the URL's own value.

    The values are code vocabulary and stay as they are in both languages - which is what
    the catalogue's four `run_state.label.*` entries spell - and a value the box cannot
    offer is appended, never dropped, for `_kind_options`' reason.
    """
    offered = [str(one) for one in view.rows.get("run_states") or ()]
    options = [("", "state.any_paren")]
    options += [(one, _state_label(one)) for one in offered]
    if state and state not in offered:
        options.append((state, words.both(view.lang, "state.current_paren", value=state)))
    return options


def _state_label(value) -> str:
    """A state's catalogue key, or the value itself when the catalogue has no word for it.

    `_labels`' own rule (`lib/gui/schema.py`): a state this console grows loses its
    translation and not its box.  The fallback matters because `ui.word` prints what it is
    given, so the *key* of a state nobody has written a word for would reach the reader as
    `run_state.label.paused`.
    """
    key = f"run_state.label.{value}"
    return key if key in CATALOGUE else value


def _api_options(view):
    """The `api` box: the stacks this deployment knows, and the one this page carries.

    An activity is not a build and this page reads no API, but the key decides which stack
    the reader's *next* page reads, and dropping it silently is what the old layer's `/runs`
    was fixed for: walking `/remote` -> `/runs` -> `/remote` used to land back on the
    startup base with nothing said.  So the key is drawn and posted rather than hidden, and
    the option is the name while the label is the address, which is the shape
    `Apis.entries()` answers in.
    """
    found = [(str(name), str(base)) for name, base in view.rows.get("apis") or ()]
    here = _api_in_force(view)
    if here and here not in [name for name, _base in found]:
        found.append((here, words.both(view.lang, "state.current_paren", value=here)))
    return found


def _api_in_force(view) -> str:
    """Which stack this page carries, as the name a URL spells (`local`, `production`).

    The option has to name the base **in force** and not the key a URL carries: the key is
    empty for the base this process started on (`Apis.key`), so a box selected on the key
    would leave the browser showing its first option - a different stack, on a process
    that started on production.  A value nothing here resolves falls back to the launch
    base, which is what the engine reads in that case too.
    """
    apis = getattr(view, "apis", None)
    check = view.check
    base = str(getattr(check, "api_base", "") or "") or str(getattr(apis, "launch", "") or "")
    named = str(apis.name(base)) if apis is not None else ""
    return named or str(getattr(check, "api", "") or "")


def _fold_line(view, every) -> str:
    """The one line that says a default is hiding rows, and undoes it in one click.

    `runs.folded_note` carries `<code>`, which is why it is rendered in this response's
    language (`view.t`) instead of as a span the script could swap: the swap writes text,
    and a sentence with markup in it would arrive as those characters.
    """
    link = view.link("", words.both(view.lang, "runs.show_all"), carry=CARRY, kind=every)
    return ui.hint(view.t("runs.folded_note", link=link))


def _panel(shown, opens, counts, whole, lang) -> str:
    """The table in a panel of its own: how many rows, then one row per activity.

    The spacer is the board's own: a `flush` body has no padding, and the table needs the
    gap above it that the design draws.
    """
    body = ('<div style="height:10px"></div>'
            + ui.table(_cols(opens, counts, lang), shown,
                       empty=words.both(lang, "empty.no_activity"), table_id="runs",
                       rows_of="all" if whole else "", kinds=KIND_ORDER, lang=lang))
    return ui.panel("counts.activities", body, flush=True, lang=lang,
                    sub=words.both(lang, "filter.cap_rows", n=len(shown)))


def _cols(opens, counts, lang) -> tuple:
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
        ui.Col("", kind="act", width="130px", draw=lambda one: _acts_cell(one, lang)),
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


def _acts_cell(one, lang) -> str:
    """What a row can do: read its log, and cancel it while it is still running.

    The log is the route itself - `/runs/<id>/log` answers the whole file as `text/plain` -
    in a tab of its own, so a click, a middle-click and a copied address all give the same
    thing; there is no inline box because this page holds no log text to put in one.  Cancel
    is an empty-bodied POST: the id is in the path, the answer is JSON, and `_JS` is what
    keeps the reader on the page where the row is about to end.  A finished row has no
    cancel, because `Run.cancel` on a settled process is a button that cannot do what it
    says.
    """
    home = ui.esc(one["id"])
    acts = [(f'<a href="/runs/{home}/log" target="_blank" rel="noopener">'
             f'{words.both(lang, "link.log")}</a>')]
    if str(one["state"]) == run_mod.RUNNING:
        acts.append(f'<form method="post" action="/api/runs/{home}/cancel">'
                    f'<button class="btn">{words.both(lang, "js.cancel")}</button></form>')
    return f'<span class="cell-actions">{"".join(acts)}</span>'


PAGES = {"/runs": runs}
