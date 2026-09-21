# SPDX-License-Identifier: LGPL-2.1-or-later
"""`/jobs`: the pairs with no record, and the ledger's own rows beside them.

The screen is one question asked of two sets.  `re.todo()` answers "which
(build, test) pairs have no record" and `Records` answers "what does the ledger say
about the rest", and the two are only useful **on one page**: shown either alone, a
reader cannot tell a test that failed from a test that never ran - which is the whole
reason an operator opens this screen before starting a run.  So the gap is a panel,
the ledger is a panel under it, and the gap carries its own two numbers (`re.todo()`'s
count, and how many rows this page drew).

**The panel's table is the pairs, and the gap is a column of it.**  The board's panel
says "every pair with no record" and draws nothing else - and on this deployment that
panel is empty for the request the page is opened with: the first pair with no record
sits 51 rows into the order, so at the default cap not one of them is drawn while the
count beside it says 99, and the only empty line the catalogue has for the occasion
("every pair already has a record") would be false.  The old page answered the same
fact the same way - one row per pair, with `col.in_gap` saying which rows the panel's
own subject is - so that is the shape here, and a reader who wants only the gap narrows
it (`?ran=never`), which is what the filter above is for.

**One bar, one test, ticks per build.**  This is the screen the operator's
「test 有些好像有但是不能勾选跑不了」 was reported against, and the shape it describes is
a second `test` control: a table drawn for one test while the bar beside it ran
another, and a row of the other test left with a dash where its box should be.  There
is one `test` here - the filter's, which is also what selects the rows - the bar sends
it as a hidden field (`table.py run` falls back to *all three* tests when a body
carries no `test`), and a row whose test is not the one in force prints a **link to
that test** rather than nothing (the old page's rule, `cells._other_test_tick`: a dash
is true of the code and unreadable to a reader).  The tick is per **build**, because
the command carries one test: two boxes under one build would be one command twice.
That is also why the board's per-row `run <test>` button is not drawn - the old page
replaced fifty-one of them with the one bar over this table, and a second POST shape
for one command is how the two came to disagree.

**What a row that cannot run says.**  `ready` is `not Build.missing(test)`, and this
page names the artifacts themselves: a pair with no record is in `re.todo()`, whose
triples carry that reason in words, and `Gui.todo` is memoised for the request
(`job_rows` and the numbers strip have already walked it), so reading it costs nothing
- while writing `needs` minus `present` here would be a second implementation of the
engine's own answer.  A pair the ledger *already has* is not in `todo()`; its box is
still disabled and says the one word that is true of it, and `needs` lists what the
test waits for.

**Nothing here is computed.**  A verdict is the record's word, a count is
`re.todo()`'s or `Records`', and every command line under a button comes from
`Gui.command()` through `_argv_of` - the only source of an argv this console will
actually run.  `days` and `limit` stay typeable number boxes with a value rail: the
old bar hid them behind the button's own argv, and a reader could not see what was
about to run.

Two things are drawn differently from the board on purpose, and one is not drawn at
all.  Its `apply` is `type="button"`, which cannot submit anything (`09`'s list of the
board's defects), so the button here is a real submit - `filter.noscript` promises a
reader with the script off a way to apply the bar.  The axes the board's `/jobs` bar
drops (`api`, `branch`, `arch`, `defconfig`, `compiler`, `state`, `result`, `origin`,
`evidence`, `missing`) are drawn too, behind `details.more` as the board's own
`/builds` draws them: hiding them, which is what the old page did, is how a reader who
narrowed by `origin=card` on `/` lost the condition here without being told.  And the
board's per-record `log` button is not drawn: it points at `/runs#<build_id>`, whose
anchor names no row (the ids on that page are runs, not builds), and `data._ledger`
hands on no log path for a record - a link that opens the wrong page is worse than the
one click it costs to read the ledger and the activities side by side.

The ledger's `source` column is who wrote the record, and it is a column rather than a
tooltip for one reason: `worker` is the row an operator opens this page to find.
"""

import urllib.parse
from functools import partial

from ....build import ARTIFACTS
from ....i18n import DEFAULT_LANG
from ...forms import _names
from ...schema import (
    _LABELS,
    DAY_CHOICES,
    EVIDENCE,
    FILTER_ORDER,
    KBUILD_STATES,
    LIMITS,
    MAX_DAYS,
    MAX_LIMIT,
    ORIGINS,
    RANS,
    RESULTS,
    VERDICTS,
)
from .. import ui, words

# The form the gap table's boxes belong to (`cells._job_tick`'s own name).  A box in a
# table cell cannot live inside a form drawn in the panel's head, so the two are joined
# by `form=` and the select-all by `data-all-for=`: that association is what makes the
# bar work with the script off as well as on.
_RUN_FORM = "run-now"

# Which keys each of the page's two bars draws.  The first six are the board's own
# `/jobs` bar in its own order; the rest of the kbuild axes are its folded second row.
# Every key one bar draws the other carries as a hidden field: a GET bar replaces the
# whole query string.
_MAIN = ("tree", "test", "ran", "verdict", "days", "limit")
_FOLD = ("api", "branch", "arch", "defconfig", "compiler", "state", "result",
         "origin", "evidence", "missing")


def jobs(view) -> str:
    """The body of `/jobs`: the two bars, the gap, the ledger, the one-shot lines."""
    todo = _todo(view)
    reasons = {(build.build_id, test): reason for build, test, reason in todo}
    pairs = list(view.rows.get("gap") or ())
    ledger = list(view.rows.get("ledger") or ())[:view.check.limit]
    return "".join((
        _bar(view, _MAIN, _main_fields(view)),
        ui.more(words.both(view.lang, "btn.more"), _bar(view, _FOLD, _fold_fields(view))),
        _gap_panel(view, pairs, _boxed(view, pairs), todo, reasons),
        _ledger_panel(view, ledger),
        _one_shot_panel(view),
    ))


def _todo(view) -> list:
    """`re.todo()` for this request: the pairs with no record, and why they cannot run.

    The page's one reach into the console, and it is free: `Gui.todo` memoises the walk
    for the request (`reads.py`, keyed by the set of tests) because `job_rows` and the
    numbers strip both ask it - so a third ask costs nothing, and the alternative would
    be a second answer to a question `Build.missing()` already owns.
    """
    return view.gui.todo(view.check)


# ------------------------------------------------------------------ the filter
def _bar(view, drawn, fields_html: str) -> str:
    """One of the page's two GET bars: what it draws, and the rest of the question.

    The board gives a page whose axes do not fit one row a `details.more` with its own
    `<form class="filters">` (`/builds` draws one), and a GET bar replaces the whole
    query string - so each bar carries every key it does not draw as a hidden field.
    Without them, `apply` on the folded row would answer a question with no tree in it,
    and nothing on the page would say so.
    """
    carried = dict(view.check.to_query())
    hidden = [(key, carried.get(key, "")) for key in FILTER_ORDER if key not in drawn]
    hidden.append(("lang", "" if view.lang == DEFAULT_LANG else view.lang))
    return ui.filters(fields_html, _bar_buttons(view), action=view.route, auto=True,
                      hidden=hidden)


def _bar_buttons(view) -> str:
    """`start over` and `apply`, the pair every bar ends with.

    The link drops the whole question and keeps the two keys that are not conditions:
    `lang`, and `api` - the identity of the stack the console is pointed at
    (`urls._url`), so a reader on a production view who presses "start over" stays on it
    rather than being moved to the local stack with nothing said.

    The button is written here because `ui.btn` is `type="button"` by contract ("a
    button that posts is `action_form`'s"), and a bar whose only submit is JavaScript is
    a bar that cannot be applied with the script off - which is what the board's own
    `apply` is, and the one thing `filter.noscript` promises the reader.
    """
    lang = view.lang
    return (ui.link_btn(words.both(lang, "btn.reset"),
                        view.url("", carry=("api", "lang")), lang=lang)
            + '<button type="submit" class="btn primary sm">'
            + words.both(lang, "btn.apply") + "</button>")


def _choices(values, current: str = "", labels=None, any_key: str = "state.any",
             lang: str = DEFAULT_LANG) -> list:
    """One select box's options: the value, and the catalogue key of its word.

    A value is what the console compares and a word is what a reader reads, so the two
    are separate here exactly as `ui.select` documents.  `any_key` is the word for "no
    condition at all", and it is passed only for the axes where the empty value is
    that: `ran`, `origin` and `evidence` each carry their own `any`, and a box offering
    a second, empty one would offer a value `one_of()` refuses - which then answers the
    axis's *default* instead of the reader's choice (`models.Filter.from_query`).

    The value in force is appended when the list does not carry it, which is `_select`'s
    own rule (`lib/gui/widgets.py`): a select with nothing selected *shows its first
    option*, so the next `apply` would send "any" where the URL said `kernel`.
    """
    labels = labels or {}
    found = [] if any_key is None else [("", any_key)]
    for one in values:
        if one and all(one != got for got, _ in found):
            found.append((one, labels.get(one) or one))
    if current and all(one != current for one, _ in found):
        found.append((current, words.both(lang, "state.current_paren", value=current)))
    return found


def _main_fields(view) -> str:
    """The bar the board draws for this screen: the axes a reader changes every visit.

    Six controls: the tree, and the three this screen owns (`test`, which of the pairs
    a row is about, and `ran`/`verdict`, what the ledger says about it), then the window
    and the row cap.  `days` and `limit` are number boxes with a value rail and not a
    row of preset buttons: a fixed row of buttons cannot say "14 days", and `limit` is
    the one control on this page that costs bytes.
    """
    lang, check, rows = view.lang, view.check, view.rows
    label = partial(ui.word, lang=lang)
    return "".join((
        ui.field(words.both(lang, "word.tree"),
                 ui.multi("tree", _names(check.tree), rows.get("trees") or (),
                          placeholder="state.any", label="word.tree", lang=lang),
                 width="w-lg"),
        ui.field(words.both(lang, "word.test"),
                 ui.select("test", _choices(rows.get("tests") or (), check.test, lang=lang),
                           check.test, labeler=label),
                 width="w-md"),
        ui.field(words.both(lang, "filter.ran"),
                 ui.select("ran",
                           _choices(RANS, check.ran, _LABELS["ran"], any_key=None, lang=lang),
                           check.ran, labeler=label),
                 width="w-sm"),
        ui.field(words.both(lang, "filter.verdict"),
                 ui.select("verdict",
                           _choices(VERDICTS, check.verdict, _LABELS["verdict"], lang=lang),
                           check.verdict, labeler=label),
                 width="w-md"),
        ui.field(words.both(lang, "filter.days"),
                 ui.number_input("days", check.days, max_=MAX_DAYS, stops=DAY_CHOICES),
                 width="w-sm"),
        ui.field(words.both(lang, "filter.rows"),
                 ui.number_input("limit", check.limit, min_=1, max_=MAX_LIMIT, stops=LIMITS),
                 width="w-sm"),
    ))


def _fold_fields(view) -> str:
    """The rest of the kbuild axes, behind the fold - the board's own second row.

    The board's `/jobs` bar draws six controls and hides nothing; its `more filters` row
    on `/builds` is where the boxes a reader needs rarely live, and these are the same
    axes `/` draws.  A control and not a hidden field is the point: every one of them is
    a condition `Filter.accepts` honours on this page, so a reader who set `origin=card`
    on `/` can see it in force here and change it.

    The word lists come from the rows where the rows carry them (`branches`, `arches`,
    `defconfigs`, `compilers`, `origins`, `evidences` - `data.py`'s own keys) and from
    `schema` for the three it does not (`state`, `result`, `missing`), which is the same
    table the row dict read its two from.
    """
    lang, check, rows = view.lang, view.check, view.rows
    label = partial(ui.word, lang=lang)
    empty = "state.any"
    return "".join((
        ui.field(words.both(lang, "filter.api"),
                 ui.text_input("api", check.api, placeholder=check.api_base or "filter.api",
                               label="filter.api", lang=lang),
                 width="w-md"),
        ui.field(words.both(lang, "word.branch"),
                 ui.select("branch", _choices(rows.get("branches") or (), check.branch,
                                              lang=lang),
                           check.branch, labeler=label),
                 width="w-md"),
        ui.field(words.both(lang, "word.arch"),
                 ui.multi("arch", _names(check.arch), rows.get("arches") or (),
                          placeholder=empty, label="word.arch", lang=lang),
                 width="w-md"),
        ui.field(words.both(lang, "word.defconfig"),
                 ui.multi("defconfig", _names(check.defconfig), rows.get("defconfigs") or (),
                          placeholder=empty, label="word.defconfig", lang=lang),
                 width="w-lg"),
        ui.field(words.both(lang, "word.compiler"),
                 ui.multi("compiler", _names(check.compiler), rows.get("compilers") or (),
                          placeholder=empty, label="word.compiler", lang=lang),
                 width="w-md"),
        ui.field(words.both(lang, "word.state"),
                 ui.select("state", _choices(KBUILD_STATES, check.state, lang=lang),
                           check.state, labeler=label),
                 width="w-sm"),
        ui.field(words.both(lang, "word.result"),
                 ui.select("result", _choices(RESULTS, check.result, lang=lang),
                           check.result, labeler=label),
                 width="w-sm"),
        ui.field(words.both(lang, "filter.origin"),
                 ui.select("origin",
                           _choices(rows.get("origins") or ORIGINS, check.origin,
                                    _LABELS["origin"], any_key=None, lang=lang),
                           check.origin, labeler=label),
                 width="w-sm"),
        ui.field(words.both(lang, "filter.evidence"),
                 ui.select("evidence",
                           _choices(rows.get("evidences") or EVIDENCE, check.evidence,
                                    _LABELS["evidence"], any_key=None, lang=lang),
                           check.evidence, labeler=label),
                 width="w-md"),
        ui.field(words.both(lang, "filter.missing"),
                 ui.select("missing",
                           _choices(ARTIFACTS, ",".join(check.missing), lang=lang),
                           ",".join(check.missing), labeler=label),
                 width="w-md"),
    ))


# -------------------------------------------------------------------- the gap
def _boxed(view, rows) -> dict:
    """Which rows get a tick box, keyed by `(build_id, test)`: the old page's rule.

    The tick is per **build** and not per row, because the bar carries one `test`: a box
    on two rows of one build would be one command twice.  With a test in force the box
    goes on that test's row and the others link to theirs; with no test in force the
    command runs all three tests for every ticked build, so the box goes on the build's
    first row.  A `(build, test)` pair is one row of this table, so the pair is the row's
    identity and a cell can find its own answer back.
    """
    found, seen = {}, set()
    for one in rows:
        first = one["build_id"] not in seen
        seen.add(one["build_id"])
        found[(one["build_id"], one["test"])] = (one["test"] == view.check.test
                                                 if view.check.test else first)
    return found


def _gap_panel(view, pairs, boxed: dict, todo: list, reasons: dict) -> str:
    """The gap: its own two numbers, the command that runs the ticked builds, its table.

    **The table draws every pair this request read, and the gap is a column.**  The
    board's panel says "every pair with no record" and draws nothing else - and on this
    deployment that panel is *empty* for the request the page is opened with: the first
    pair with no record sits 51 rows into the order, so at the default cap not one of
    them is drawn, while the count above the empty table says 99.  The old page answered
    the same fact the same way: one row per pair, and `col.in_gap` says which rows the
    panel's own subject is.  A reader who wants only the gap narrows it (`?ran=never`),
    which is what the filter above is for.
    """
    lang = view.lang
    chips = ui.chips((
        # No link: no screen draws every pair that has no record, and a chip without an
        # `href` is drawn as a `<span>` for exactly that case (`ui.chips`).
        (words.both(lang, "counts.gap"), str(len(todo)), "", ""),
        # This one is a link, and its number is the row count of the table under it -
        # the page it goes to is this one, with the question it was drawn for.
        (words.both(lang, "counts.shown"), str(len(pairs)), "", view.url("")),
    ), lang=lang)
    return ui.panel("label.gap", chips + _gap_table(view, pairs, boxed, reasons),
                    sub=words.both(lang, "jobs.run_sub"),
                    tools=_run_bar(view, boxed), lang=lang)


def _run_bar(view, boxed: dict) -> str:
    """The one command this table's ticks feed: the select-all, and its POST.

    One action bar and not one button per row - the shape the operator asked for.  The
    `test` it runs with is the filter's, sent only when the bar names one: `command()`
    leaves `--test` out for an empty value, and that is what makes a box in the tick
    column mean "the test chosen above, times every ticked build".  The select-all is
    rendered `hidden` until the script wires it (`ui.checkbox`): with the script off a
    box that ticks nothing would be a lie, and the boxes below are tickable by hand.
    """
    check, lang = view.check, view.lang
    boxes = sum(1 for on in boxed.values() if on)
    fields = [("api", check.api)] + ([("test", check.test)] if check.test else [])
    return (ui.checkbox("all", words.both(lang, "tick.all", n=boxes), all_for=_RUN_FORM,
                        lang=lang)
            + ui.action_form("run", words.both(lang, "btn.run_ticked"), fields=fields,
                             argv=view.gui._argv_of_ticked("run", {"test": check.test},
                                                           lang, api=check.api),
                             hint="jobs.run_hint", form_id=_RUN_FORM, lang=lang))


def _gap_table(view, pairs, boxed: dict, reasons: dict) -> str:
    """The board's columns over the pairs this page drew, plus the one that names them.

    `col.in_gap` is the old page's own column and it is what tells a fail from a
    never-ran inside one table: the verdict column says what the ledger has, and this
    one says whether the ledger has anything at all.  `col.artifact` is the board's last
    cell - empty in its header, a per-row `run <test>` button in its body - and it is
    where a row that cannot run says which artifact it is waiting for; the button is not
    drawn (see the module docstring), and the data that takes its place is worth more
    than the button was.

    `empty.no_rows` and not `empty.no_gap`: this table holds both halves, so "every pair
    already has a record" is the one thing an empty one does not mean.
    """
    lang = view.lang
    cols = (
        ui.Col("", draw=lambda row: _tick_cell(view, row, boxed, reasons), kind="c",
               width="28px"),
        ui.Col("word.build_id", draw=lambda row: _build_cell(view, row["build_id"]),
               kind="id"),
        ui.Col("word.tree", draw=lambda row: _tree_cell(row["tree"])),
        ui.Col("word.test", draw=lambda row: ui.code(row["test"])),
        ui.Col("col.needs", draw=lambda row: _muted(row["needs"])),
        ui.Col("col.ready", draw=lambda row: _ready_cell(row, lang), kind="c"),
        ui.Col("label.runs", field="runs", kind="n"),
        ui.Col("label.last", draw=lambda row: _verdict_cell(row["last"], lang), kind="c"),
        ui.Col("col.when", draw=lambda row: _stamp(row["when"]), kind="n"),
        ui.Col("col.in_gap", draw=lambda row: _gap_cell(row, lang), kind="c"),
        ui.Col("col.artifact", draw=lambda row: _waiting_cell(view, row, reasons),
               kind="wrapc"),
    )
    return ui.table(cols, pairs, empty=words.both(lang, "empty.no_rows"), lang=lang)


def _tick_cell(view, row, boxed: dict, reasons: dict) -> str:
    """This row's box, its refusal, or the link that would give it a box at all.

    A row whose test is not the test in force cannot be run by *this* bar: its box would
    send that build with the wrong `test`, which is the operator's
    「test 有些好像有但是不能勾选跑不了」.  A dash said nothing about why and nothing about
    what to do; the link is the same page with that row's test chosen, and its tooltip is
    the sentence that explains the rule.  A row that cannot run keeps its box and it is
    `disabled` with the reason - the artifact it is waiting for - in its `title=`.
    """
    lang = view.lang
    if not boxed.get((row["build_id"], row["test"])):
        return view.link("", words.both(lang, "jobs.tick_other", test=row["test"]),
                         test=row["test"], cls="none",
                         title=view.t("jobs.tick_other_title", test=row["test"]))
    return ui.checkbox("selected", "", value=row["build_id"], form=_RUN_FORM,
                       disabled_reason="" if row["ready"] else _waiting(row, reasons),
                       lang=lang)


def _waiting(row, reasons: dict) -> str:
    """What a disabled box says: the artifacts this pair is waiting for.

    `ready` is `not Build.missing(test)`, and the names are that same answer read out of
    `re.todo()`, whose triples carry it.  A pair the ledger already has is not in
    `todo()`, so this page does not guess at a reason it was not handed: the box says
    `filter.missing`, which is the whole of what is known about such a row.
    """
    return reasons.get((row["build_id"], row["test"])) or "filter.missing"


def _ready_cell(row, lang: str) -> str:
    """`ready?`: whether every artifact this test needs is on disk, and its toned word."""
    if row["ready"]:
        return ui.pill("ready", label="state.ready", lang=lang)
    return ui.pill("missing", label="filter.missing", lang=lang)


def _waiting_cell(view, row, reasons: dict) -> str:
    """The artifact a row is waiting for, or the design's dash when it waits for none.

    Printed **verbatim**, which is `tables._records_table`'s rule for a record's own
    words: `Build.missing(test)` answers with the artifact and what is wrong with it
    (`kernel: not downloaded yet (<path>)`), that sentence is the engine's, and a page
    that trimmed it to the first word would be rewriting a fact nobody here can
    re-observe.  The column is bounded (`wrapc`) because that sentence is long.
    """
    if row["ready"]:
        return ui.DASH
    return f'<span class="dash">{ui.esc(_waiting(row, reasons))}</span>'


def _gap_cell(row, lang: str) -> str:
    """Whether this pair is the panel's own subject: in the gap, or already recorded."""
    return words.both(lang, "state.yes" if row["gap"] else "state.already_recorded")


def _verdict_cell(one, lang: str) -> str:
    """A record's own word, toned by `ui.STATE`; no record is the design's dash."""
    return ui.pill(one, lang=lang) if one else ui.DASH


# ----------------------------------------------------------------- the ledger
def _ledger_panel(view, rows) -> str:
    """What the ledger holds, newest first, whoever wrote each record.

    Capped by this page's `limit` like every other table here, with `the ledger, in
    full` in its own head: `results.py` is read-only and needs no API, so the whole
    ledger is one press away rather than one `limit` away.
    """
    check, lang = view.check, view.lang
    tools = ui.action_form("results", words.both(lang, "btn.ledger_full"),
                           fields=[("test", check.test)],
                           argv=view.gui._argv_of("results", {"test": check.test}, lang),
                           hint="jobs.results_hint", lang=lang)
    return ui.panel("page.jobs.ledger_title", _ledger_table(view, rows), tools=tools,
                    flush=True, lang=lang)


def _ledger_table(view, rows) -> str:
    """The board's seven columns: the id, the test, the verdict, the exit, who wrote the
    record, when it was written, and the record's own words.

    No tree column, because the board draws none here: a record is keyed by build id,
    the tree is a fact of the build, and the id's own page carries it.  The board's
    eighth cell is not drawn either (see the module docstring).
    """
    lang = view.lang
    cols = (
        ui.Col("word.build_id",
               draw=lambda row: _build_cell(view, row["build_id"], short=True), kind="id"),
        ui.Col("word.test", draw=lambda row: ui.code(row["test"])),
        ui.Col("col.verdict", draw=lambda row: _verdict_cell(row["verdict"], lang), kind="c"),
        ui.Col("col.exit", field="exit", kind="n"),
        ui.Col("col.source", draw=lambda row: _source_cell(row["source"], lang), kind="c"),
        ui.Col("col.when", draw=lambda row: _stamp(row["when"]), kind="n"),
        ui.Col("col.detail", field="detail", kind="wrapc"),
    )
    return ui.table(cols, rows, empty=words.both(lang, "empty.no_ledger_record"), lang=lang)


def _source_cell(one, lang: str) -> str:
    """Who wrote the record: `worker` is the row an operator looks for."""
    return ui.pill(one, tone_override="info", lang=lang) if one else ui.DASH


# --------------------------------------------------------------- the one-shots
def _one_shot_panel(view) -> str:
    """The two commands that are not "run the ticked builds", behind one fold.

    Both take one tree, so both are refused where the filter names several
    (`Gui._one_tree`): the button keeps its label and says why in its `title=`, which is
    how the reader finds out what to untick.  Folded, as the board draws it - these are
    the commands a reader starts once the table above has told him what to run.
    """
    check, lang = view.check, view.lang
    day_fields = [("api", check.api), ("tree", check.tree), ("branch", check.branch),
                  ("days", str(check.days)), ("limit", str(check.limit))]
    fetch_fields = [("api", check.api), ("tree", check.tree), ("branch", check.branch),
                    ("test", check.test)]
    day_argv = {"tree": check.tree, "branch": check.branch, "days": str(check.days),
                "limit": str(check.limit)}
    fetch_argv = {"tree": check.tree, "branch": check.branch, "test": check.test}
    return ui.panel(
        "page.jobs.day_title",
        ui.action_form("runday", words.both(lang, "btn.run_day"), fields=day_fields,
                       argv=view.gui._argv_of("runday", day_argv, lang, api=check.api),
                       hint="jobs.runday_hint", blocked=view.gui._one_tree(check, lang),
                       lang=lang)
        + ui.action_form("fetch", words.both(lang, "btn.run_newest"), fields=fetch_fields,
                         argv=view.gui._argv_of("fetch", fetch_argv, lang, api=check.api),
                         blocked=view.gui._one_tree(check, lang), lang=lang),
        collapsible=True, open_=False, lang=lang)


# ------------------------------------------------------------------- the cells
def _build_cell(view, build_id: str, short: bool = False) -> str:
    """A build id, linked to the page that shows that build alone.

    `/analysis/<build_id>` and not `/local/<build_id>`: the first is the board's own
    link and the route this layer's single-build page answers at (`page.one.*`), while
    the second is the old layer's per-copy page.  `view.url` is what carries this page's
    question onto it, so the test and the cap the reader is looking at are the ones the
    build's own page opens with.
    """
    href = view.url("/analysis/" + urllib.parse.quote(build_id))
    # The ellipsis as its own character and not as `&hellip;`: `ui.code` escapes the
    # text it is handed, so an entity here would reach the reader as those six letters.
    shown = f"{build_id[:16]}\u2026" if short else build_id
    return ui.code(shown, href=href, title=build_id if short else "")


def _tree_cell(value: str) -> str:
    """The source tree, or the design's dash: a build with no card has no tree to name."""
    return f'<span class="tree">{ui.esc(value)}</span>' if value else ui.DASH


def _muted(value: str) -> str:
    """A value in the quiet ink - the board's own treatment of `needs`."""
    return f'<span class="muted">{ui.esc(value)}</span>' if value else ui.DASH


def _stamp(value) -> str:
    """A record's timestamp as the board prints it: the day, then the clock, quiet."""
    if not value:
        return ui.DASH
    day, _, clock = str(value).partition("T")
    if not clock:
        return f'<span class="nowrap">{ui.esc(day)}</span>'
    return (f'<span class="nowrap">{ui.esc(day)} '
            f'<span class="muted">{ui.esc(clock)}</span></span>')
