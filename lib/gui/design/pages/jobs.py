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

**One bar, and every row of the table is a tick box.**  This is the screen the
operator's 「test 有些好像有但是不能勾选跑不了」 was reported against, and the shape it
described was a second `test` control: a table drawn for one test while the bar beside
it ran another, and a row of the other test left with a link where its box should be.
That link only moved the filter above and re-drew the page - two loads to start one
row - so the row itself is what ticks now, and the command is built out of the rows.

**A tick is one (build, test) pair, which is why the engine took a new flag.**  The old
bar carried one `test` and ticked builds, because `table.py run --build A --test boot`
is a *cross product*: two tests times two builds is four runs.  A box under the second
test of a build therefore could not be honoured - the page drew a link instead, and
the operator's complaint was exactly that row.  `--pair <build_id>:<test>` names the
pairs themselves (`table.py`'s `_jobs`), one run each, which is what a row already is:
the box sends its own row's `<build_id>:<test>`, the bar sends no `test` at all, and
any mixture of ticked rows runs as the mixture that was ticked.  The printed argv says
`action.ticked_pair` where the ids go (`_argv_of_ticked`); the executor and the skip
behind it are unchanged - which pairs actually run is still the ledger's answer.

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

**能跑 means one thing on this page, and 能跑? is where it is asked.**  The operator's
「能跑 vs 没下载资源」 named two states that read the same, and the page had two
reasons for it: the 能跑? column answered its question with `filter.missing` - the
*filter's* word for the axis, which reads 缺什么, a question about a resource rather
than a verdict about the row, drawn in the same neutral tone - and the 在缺口里 column
answered *its* question with `state.ready`, so one row could print 跑不了 (this pair's
files are not all here) beside 能跑 (this pair has no record) in two adjacent cells.
So the pair is now `state.ready` against `state.cannot_run` (跑不了, toned `warn`, the
colour the 构件 column gives a named artifact that has not arrived), the gap's own two
answers are `state.not_run` (还没跑) and `state.already_recorded`, and the reason a row
cannot run stays where it already was: which artifact, and which of its two ways of
being missing, is `col.artifact`'s answer (`_waiting_cell`).

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
narrowed by `origin=card` on `/` lost the condition here without being told.  Nine of
the axes are offered as **sets** rather than one value each (`ui.multi`): `tree`/`arch`/
`defconfig`/`compiler` as they always were, and `state`/`result`/`verdict`/`evidence`/
`missing` because the operator asked for 「一个指标多个值筛选」 and each of those is a
small closed vocabulary where "any of these" is a question a reader really has - with
one refusal kept: an empty set already means "no condition", so a chip list never offers
the `any` its own emptiness says.  `branch`, `test` and `ran` stay single-valued
(`Filter.from_query` and `schema.MULTI_FIELDS` say why each one is not a set), and
`origin` is a set of the **two sides** a row can come from - drawn as two ticks by
`builds._origin_boxes`, the same control `/` and `/analysis` draw, so one axis has one
spelling rather than a three-value select here and two ticks there.  And the
board's per-record `log` button is not drawn: it points at `/runs#<build_id>`, whose
anchor names no row (the ids on that page are runs, not builds), and `data._ledger`
hands on no log path for a record - a link that opens the wrong page is worse than the
one click it costs to read the ledger and the activities side by side.

**The table's own columns are the doors to the rest of the page's answers.**  Three
of them stop being a printed value and become a way in, which is what an operator
asked for after reading them: 跑了几次 is a **link** to the page that draws every run
of that (build, test) pair (`builds._run_history_panel`, reached by `?test=`, so the
panel that already existed is the one that opens and no second renderer is written),
在缺口里？ says which of the two things the column means, and 构件 says **which** artifact
a row is waiting for and **in which of two ways** it is missing - the card names no
URL for it (nothing will ever fetch it) or it is named and not here yet (a pull fixes
it) - while an artifact whose bytes are on disk is waiting for nothing whatever the
card says (`Build._why`).  All three read the engine (`Build.lacking`,
`re.todo()`), so the page and `table.py run` cannot disagree about what a row needs.

The ledger's `source` column is who wrote the record, and it is a column rather than a
tooltip for one reason: `worker` is the row an operator opens this page to find.
"""

import urllib.parse
from functools import partial

from ....build import ARTIFACTS
from ....i18n import DEFAULT_LANG, t
from ...forms import _names
from ...schema import (
    _LABELS,
    DAY_CHOICES,
    EVIDENCE,
    KBUILD_STATES,
    LIMITS,
    MAX_DAYS,
    MAX_LIMIT,
    RANS,
    RESULTS,
    VERDICTS,
    _labels,
)
from ...urls import _carried
from .. import ui, words
from .builds import _origin_boxes

# The form the gap table's boxes belong to (`_tick_cell`'s own name).  A box in a
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
        ui.more(words.both(view.lang, "btn.more"), _bar(view, _FOLD, _fold_fields(view)),
                # The fold this page's 更多筛选 row is remembered by: `/jobs` has one,
                # and the row a reader opened comes back open (`ui._fold`).
                fold="more.jobs"),
        _gap_panel(view, pairs, todo, reasons),
        _ledger_panel(view, ledger),
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

    The keys are `urls._carried`'s and not a walk of `FILTER_ORDER`, because the order is
    not the whole of the filter: the top bar's clock (`shell.tz_switch`) is a `Filter`
    field outside it, and a rule that only walked the order reset the reader's clock on
    every apply.
    """
    hidden = _carried(view.route, view.check, drawn)
    hidden.append(("lang", "" if view.lang == DEFAULT_LANG else view.lang))
    return ui.filters(fields_html, _bar_buttons(view), action=view.route, auto=True,
                      hidden=hidden)


def _bar_buttons(view) -> str:
    """`start over` and `apply`, the pair every bar ends with.

    The link drops the whole question and keeps the three keys that are not *conditions*:
    `api` - the identity of the stack the console is pointed at (`urls._url`), so a reader
    on a production view who presses "start over" stays on it rather than being moved to
    the local stack with nothing said; `lang`; and `tz`, which is the reader's clock.  The
    clock is the one this link used to lose, and it was the odd one out on the site -
    `/`, `/analysis`, `/trend`, `/runs` and `/worker` all kept it, so "start over" on
    `/jobs` was the single control in the console that could move a reader's clock without
    their asking.  It changes nothing about *which* rows are shown, which is why it is
    carried and not cleared with the question.

    The button is written here because `ui.btn` is `type="button"` by contract ("a
    button that posts is `action_form`'s"), and a bar whose only submit is JavaScript is
    a bar that cannot be applied with the script off - which is what the board's own
    `apply` is, and the one thing `filter.noscript` promises the reader.
    """
    lang = view.lang
    return (ui.link_btn(words.both(lang, "btn.reset"),
                        view.url("", carry=("api", "lang", "tz")), lang=lang)
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

    The value in force is appended when the list does not carry it: a select with
    nothing selected *shows its first option*, so the next `apply` would send "any"
    where the URL said `kernel`.
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
        # 最近 as a **set** of verdicts (`?verdict=fail,incomplete`), which is the
        # operator's 「一个指标多个值」 asked of this column: "which pairs are failing,
        # one way or another" is one question, and "fail or incomplete" is not the
        # same as the "any" a select box had to fall back on.
        ui.field(words.both(lang, "filter.verdict"),
                 ui.multi("verdict", _names(check.verdict), VERDICTS[1:],
                          labels=_labels("verdict", lang),
                          placeholder="state.any", label="filter.verdict", lang=lang),
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
        # The two kbuild axes as sets, like the four above them: `?state=done,running`
        # is "still building or finished", and it is sent to the API as `state__in`
        # (`schema.MULTI_FIELDS` measures why a comma in a plain key answers 0).  The
        # word for `done`/`running` is `job_state`'s, which is the table the job nodes
        # of the same vocabulary already draw from - one word for one state.
        ui.field(words.both(lang, "word.state"),
                 ui.multi("state", _names(check.state), KBUILD_STATES[1:],
                          labels=_labels("job_state", lang),
                          placeholder=empty, label="word.state", lang=lang),
                 width="w-sm"),
        ui.field(words.both(lang, "word.result"),
                 ui.multi("result", _names(check.result), RESULTS[1:],
                          placeholder=empty, label="word.result", lang=lang),
                 width="w-sm"),
        # The same two ticks `/` draws, from the same function: 有卡片 and 两个都要 were
        # values *this* select offered and `/`'s no longer does, so the same axis had two
        # spellings one click apart.  `builds._origin_boxes` says why neither value is
        # needed (卡片 is a column of its own two panels up, and two ticks *are* 两个都要).
        ui.field(words.both(lang, "filter.origin"), _origin_boxes(view), width="w-md"),
        # 证据 and 缺失 as sets too, and neither is sent to the API (`API_FILTERS` has
        # no key for them): a row is in when *any* named value holds of it, answered by
        # `Filter.accepts` on the rows this page has.  `EVIDENCE`'s own `any` is left
        # out of the offered chips - an empty set already means it, and a chip that
        # says "no condition" beside three real conditions is a trap.
        ui.field(words.both(lang, "filter.evidence"),
                 ui.multi("evidence", _names(check.evidence),
                          [one for one in (rows.get("evidences") or EVIDENCE) if one != "any"],
                          labels=_labels("evidence", lang),
                          placeholder=empty, label="filter.evidence", lang=lang),
                 width="w-md"),
        ui.field(words.both(lang, "filter.missing"),
                 ui.multi("missing", _names(check.missing), ARTIFACTS,
                          placeholder=empty, label="filter.missing", lang=lang),
                 width="w-md"),
    ))


# -------------------------------------------------------------------- the gap
def _gap_panel(view, pairs, todo: list, reasons: dict) -> str:
    """The gap: its own two numbers, the commands this table starts, and its table.

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
    return ui.panel("label.gap", chips + _gap_table(view, pairs, reasons),
                    sub=words.both(lang, "jobs.run_sub"),
                    tools=_run_bar(view, pairs), lang=lang)


def _run_bar(view, pairs) -> str:
    """Every command this table starts: the ticks' POST, then the two whole-window runs.

    One action bar and not one button per row - the shape the operator asked for.  Its
    only field is the API: a tick now carries its own test (`_tick_cell` puts
    `<build_id>:<test>` in the box), so there is no `test` left for the bar to name, and
    its absence is what lets one command run rows of different tests - the mixture that
    was ticked, which is the whole of `--pair` (`table.py`'s `_jobs`).  The select-all
    counts every row drawn, because every row has a box; it is rendered `hidden` until
    the script wires it (`ui.checkbox`), since with the script off a box that ticks
    nothing would be a lie, and the boxes below are tickable by hand.

    **按天跑 and 跑最新构建 live here too, and not in a panel of their own.**  They used
    to be one more `ui.panel` under this table with its own fold, its own form and its
    own copy of `tree`/`branch`/`days` - so a reader who had just read the table above
    it set the same four values a second time, and the fold was the only place the day
    run's window was ever visible.  Both commands are *selectors over this table's own
    question*: they read the filter drawn above the table (tree, branch, days, limit)
    and they run what the ledger does not have, which is the column 在缺口里 already
    answers per row.  So they are two buttons on the table's own bar, their argv is
    built from this page's filter (`_argv_of`, the only source of an argv this console
    runs), and the list of what they would run is the table they sit on - narrowed with
    `?days=` and 在缺口里, rather than a second renderer of the same pairs.  Both keep
    the `_one_tree` refusal: `runday.py` and `run_latest.py` take one tree each.
    """
    check, lang = view.check, view.lang
    day_fields = [("api", check.api), ("tree", check.tree), ("branch", check.branch),
                  ("days", str(check.days)), ("limit", str(check.limit))]
    day_argv = {"tree": check.tree, "branch": check.branch, "days": str(check.days),
                "limit": str(check.limit)}
    fetch_fields = [("api", check.api), ("tree", check.tree), ("branch", check.branch),
                    ("test", check.test)]
    fetch_argv = {"tree": check.tree, "branch": check.branch, "test": check.test}
    return (ui.checkbox("all", words.both(lang, "tick.all", n=len(pairs)),
                        all_for=_RUN_FORM, lang=lang)
            + ui.action_form("run", words.both(lang, "btn.run_ticked"),
                             fields=[("api", check.api)],
                             argv=view.gui._argv_of_ticked("run", {}, lang, api=check.api,
                                                           tick_word="action.ticked_pair"),
                             hint="jobs.run_hint", form_id=_RUN_FORM, lang=lang,
                             # **重跑, beside 跑.**  The operator's 「我必须点进某个 boot
                             # 里面按那个重跑好像才行」: `--redo` existed and reached
                             # `table.py run` (`actions.command`), but the only button on
                             # any page that sent it was the one on a single build's page
                             # (`builds._correspondence_commands`), so the ledger could
                             # only be overridden one pair at a time, through a record the
                             # reader had to go and find.  This is the same action, the
                             # same ticks and the same fields, one `redo=1` apart - on the
                             # button, not in a hidden field, so the 跑 beside it does not
                             # send it and the two printed lines differ by `--redo` and by
                             # nothing else.
                             also=(("run", words.both(lang, "btn.run_redo"),
                                    view.gui._argv_of_ticked("run", {"redo": "1"}, lang,
                                                             api=check.api,
                                                             tick_word="action.ticked_pair"),
                                    "", (("redo", "1"),)),))
            + ui.action_form("runday", words.both(lang, "btn.run_day"), fields=day_fields,
                             argv=view.gui._argv_of("runday", day_argv, lang, api=check.api),
                             hint="jobs.runday_hint", blocked=view.gui._one_tree(check, lang),
                             lang=lang)
            + ui.action_form("fetch", words.both(lang, "btn.run_newest"),
                             fields=fetch_fields,
                             argv=view.gui._argv_of("fetch", fetch_argv, lang, api=check.api),
                             blocked=view.gui._one_tree(check, lang), lang=lang))


def _gap_table(view, pairs, reasons: dict) -> str:
    """The board's columns over the pairs this page drew, plus the one that names them.

    `col.in_gap` is the old page's own column and it is what tells a fail from a
    never-ran inside one table: the verdict column says what the ledger has, and this
    one says whether the ledger has anything at all.  `col.ready` is the pair's verdict
    about *this machine* - 能跑 or 跑不了 - and it carries the header `title=` that
    defines its two words, because the column is two characters wide and the vocabulary
    is the operator's rather than the reader's (`_ready_cell`).  `col.artifact` is the
    board's last cell - empty in its header, a per-row `run <test>` button in its body -
    and it is where a row that cannot run says which artifact it is waiting for; the
    button is not drawn (see the module docstring), and the data that takes its place is
    worth more than the button was.

    `empty.no_rows` and not `empty.no_gap`: this table holds both halves, so "every pair
    already has a record" is the one thing an empty one does not mean.

    **The build id is one cell for the three rows it names** (`Col(span=…)`): the rows
    come from `Gui.job_rows` in build-major order, so a build's rows are contiguous and
    the column can be drawn once per run of equal ids instead of three times.  Nothing
    moves between the rows - each one keeps its own test, needs, readiness and box, and
    the tick column above all of them, since a tick is a pair and not a build.  A run
    the cap cuts in half is still one run here: the rows that were drawn span the rows
    that were drawn, which is what a reader looking at this page can see.
    """
    lang = view.lang
    cols = (
        ui.Col("", draw=lambda row: _tick_cell(view, row, reasons), kind="c",
               width="28px"),
        ui.Col("word.build_id", draw=lambda row: _build_cell(view, row["build_id"]),
               kind="id", span="build_id"),
        ui.Col("word.tree", draw=lambda row: _tree_cell(row["tree"])),
        ui.Col("word.test", draw=lambda row: ui.code(row["test"])),
        ui.Col("col.needs", draw=lambda row: _muted(row["needs"])),
        # The header's own `title=` defines the column's two answers: 能跑 and 跑不了 are
        # the operator's pair of words and the page's only place where they are explained
        # (`col.ready_title` says where the missing pieces are named, which is the 构件
        # column below - the one this page was opened for).
        ui.Col("col.ready", draw=lambda row: _ready_cell(row, lang), kind="c",
               title="col.ready_title"),
        ui.Col("label.runs", draw=lambda row: _runs_cell(view, row), kind="n"),
        ui.Col("label.last", draw=lambda row: _verdict_cell(row["last"], lang), kind="c"),
        ui.Col("col.when", draw=lambda row: ui.stamp(row["when"], view.check.tz, seconds=True), kind="n"),
        ui.Col("col.in_gap", draw=lambda row: _gap_cell(row, lang), kind="c"),
        ui.Col("col.artifact", draw=lambda row: _waiting_cell(view, row, reasons),
               kind="wrapc"),
    )
    return ui.table(cols, pairs, empty=words.both(lang, "empty.no_rows"), lang=lang)


def _tick_cell(view, row, reasons: dict) -> str:
    """This row's box, or its refusal in words.

    Every row has one, whatever test is in force, and its value is the row's own
    identity - `<build_id>:<test>` - because that is what `table.py run --pair` takes:
    the box *is* the pair it sits under, so ticked rows of different tests run as the
    mixture that was ticked (`_run_bar`).  A row that cannot run keeps its box and it is
    `disabled` with the reason - the artifact it is waiting for - in its `title=`.
    """
    lang = view.lang
    return ui.checkbox("selected", "", value=f"{row['build_id']}:{row['test']}",
                       form=_RUN_FORM,
                       disabled_reason="" if row["ready"] else _waiting(row, reasons, lang),
                       lang=lang)


def _waiting(row, reasons: dict, lang: str) -> str:
    """What a disabled box says: the artifacts this pair is waiting for.

    `ready` is `not Build.missing(test)`, and the names are that same answer read out of
    `re.todo()`, whose triples carry it (`jobs()` builds `reasons` from the triples'
    third element, which is `"; ".join(build.missing(test))` - a sentence, already
    words).  A pair the ledger already has is not in `todo()`, so this page does not
    guess at a reason it was not handed: it says `filter.missing` - the page's own word
    for an artifact that is not on this disk - in the reader's language.

    **The fallback is rendered here, and it used to be the key.**  Both callers take a
    string to *draw* (`ui.checkbox(disabled_reason=…)` for the row's box,
    `ui.esc(…)` in a `<span class="dash">` for the 构件 cell), and the fallback was the
    catalogue key `filter.missing` itself - so the box got a translation, because
    `ui._attr` looks a key up when it recognises one, while the 构件 cell printed the
    key: `filter.missing` on screen, the class of bug `ui._attr`'s key-shape guard
    raises on.  One function cannot answer both a word and a key, and this one's real
    values were always words (the sentences above), so the fallback became a word too
    and the `lang` came with it.  A key that reaches a screen is a bug whether or not
    today's rows reach the branch that prints it.

    What the box's `title=` loses by this is the swap pair `ui._attr` writes for a key
    (`data-en`/`data-zh`): it is now one language, like the sentence every other row's
    box already carries there.  Nothing is lost on screen - the page is drawn in the
    language that was asked for, `t()` renders in it, and the shell's language switch
    is a link that reloads, not a swap in place.
    """
    return reasons.get((row["build_id"], row["test"])) or t(lang, "filter.missing")


def _ready_cell(row, lang: str) -> str:
    """`能跑?`: whether every artifact this test needs is on disk, in two stated words.

    **能跑 against 跑不了 - the operator's 「能跑 vs 没下载资源」.**  The cell answered
    this question before with `state.ready` against `filter.missing`, and the second of
    those is the *filter's* word for the axis: it reads 缺什么, a question about a
    resource rather than a verdict about the row, and `ui.STATE` tones `missing` `idle`
    - the same neutral grey a fact about nothing is drawn in - so a pair whose files are
    all here and a pair waiting for bytes were two cells a reader had to read a second
    time to tell apart.  The negative is `state.cannot_run` (跑不了) in the `warn` tone,
    which is the colour the 构件 column gives a named artifact that has not arrived yet
    (`col.artifact.no_bytes`) - the state this one usually means, and the one a pull
    fixes.

    **The reason is not repeated here.**  *Which* artifact is missing and *which of the
    two ways* it is missing is `col.artifact`'s answer (`_waiting_cell`), which is the
    column beside this one; what the test wanted in the first place is `needs`, two
    columns to the left.  This cell is the verdict only, and the header's `title=`
    (`col.ready_title`) is where its two words are defined.

    The word is also the non-colour half of the signal: 跑不了 cannot be misread for
    能跑 with the script off or by a reader who does not tell the two tones apart, and
    the two words are the operator's own (the module docstring says why).
    """
    if row["ready"]:
        return ui.pill("ready", label="state.ready", lang=lang)
    return ui.pill("cannot run", label="state.cannot_run", tone_override="warn", lang=lang)


def _runs_cell(view, row) -> str:
    """How many runs the ledger holds for this pair - and the door to those runs.

    The count is the link, because the count is the question: a reader looking at `3`
    wants to know which of the three the ledger kept and what the others said, and the
    page that answers it already exists (`builds._run_history_panel`, reached by
    `?test=`), so this is a link and not a second renderer.  The route is the *old*
    layer's per-copy page (`/local/<build_id>`) rather than `/analysis/<build_id>`:
    the panel lives there, and `test` is one of the few keys that route reads
    (`ROUTE_KEYS`), which is what carries the pair across.

    Zero is not a link: the panel would open on "no run of this pair", which is what
    this row's 最近 and 何时 already say, and a link that can only answer nothing is
    worse than the number that says nothing.
    """
    if not row["runs"]:
        return ui.num(row["runs"])
    return view.link("/local/" + urllib.parse.quote(row["build_id"]),
                     ui.num(row["runs"]), test=row["test"])


def _waiting_cell(view, row, reasons: dict) -> str:
    """Which artifact a row is waiting for, **and which of the two ways it is missing**.

    The board's last cell is a per-row `run <test>` button, which this page does not
    draw (see the module docstring): what a reader needs from a row that cannot run is
    the artifact that stops it, and an artifact can be absent in two states that need
    two different responses - the card names no URL for it (nothing will ever fetch it:
    no run of this pair can ever start from the API's answer) or it is named and not
    here yet (a pull fixes it).  The operator asked for exactly this
    (「区分一下没有下载和没有网址」), and `Build.lacking` is the engine's answer, made
    once so the page and `table.py run` cannot come to disagree about which pairs run.

    A card with **no URL whose bytes are on disk** is not waiting for anything: `_why`
    asks the file first, so such an artifact is in neither group - which is the answer
    to 「没有网址理论也可以硬塞入资源？」, and the reason a file put there by hand makes
    a pair runnable (`Build.make`).  The hint says so where the reader meets the state.

    A build this machine has no card for has no `Build` to ask (`build_of` answers
    `None`): the reason `re.todo()` gave is then the whole of what is known, and that
    is the sentence this cell printed before the two states existed.
    """
    if row["ready"]:
        return ui.DASH
    lang = view.lang
    build = view.gui.build_of(row["build_id"])
    lacking = build.lacking(row["test"]) if build is not None else None
    if not lacking or any(why not in (build.NO_URL, build.NO_BYTES) for _, why in lacking):
        # `Build.lacking` answers a prose reason with an empty name when the test
        # itself is unknown here (`needs()` refused it); that, and no card at all,
        # both fall back to `_waiting`'s sentence - which is the same string the row's
        # box carries, and now a word in the reader's language rather than a key
        # (`_waiting` says why: this is the caller that printed the key).
        return f'<span class="dash">{ui.esc(_waiting(row, reasons, lang))}</span>'
    # One pill per *run* of equal why, so the artifacts keep the order the test asks
    # for them in (`kernel, modules, kselftest`) instead of being sorted by state.
    drawn, sentence = [], "; ".join(build.missing(row["test"]))
    for name, why in lacking:
        if not drawn or drawn[-1][0] != why:
            drawn.append((why, []))
        drawn[-1][1].append(name)
    words_of = {build.NO_URL: "col.artifact.no_url", build.NO_BYTES: "col.artifact.no_bytes"}
    tones = {build.NO_URL: "bad", build.NO_BYTES: "warn"}
    title = sentence
    if any(why == build.NO_URL for _, why in lacking):
        title = f"{sentence} - {view.t('col.artifact.no_url_hint')}"
    cells = " ".join(ui.pill(tones[why], label=words_of[why], lang=lang)
                     + " ".join(ui.code(name) for name in names)
                     for why, names in drawn)
    return f'<span title="{ui.esc(title)}">{cells}</span>'


def _gap_cell(row, lang: str) -> str:
    """Whether this pair is the panel's own subject: still to run, or already recorded.

    The two words are the column header's two answers (`col.in_gap`): `state.not_run`
    (还没跑) and `state.already_recorded`.  The first one used to be `state.ready`, which
    was the improvement on the bare `state.yes` it once printed - the header asked "in
    the gap?" and the reader got "是" beside "已经记过", so neither cell answered its own
    heading - but 能跑 is the word the 能跑? column beside this one answers a different
    question with, and a row could therefore print 跑不了 and 能跑 in two adjacent cells
    (the operator's 「能跑 vs 没下载资源」; the catalogue says the rest).  A record's own
    two states are now spelled in words about the *record*, which is what this column is
    about.  What is computed is unchanged - `row["gap"]` is `re.todo()`'s answer for the
    pair.
    """
    return words.both(lang, "state.not_run" if row["gap"] else "state.already_recorded")


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
        ui.Col("col.when", draw=lambda row: ui.stamp(row["when"], view.check.tz, seconds=True), kind="n"),
        ui.Col("col.detail", field="detail", kind="wrapc"),
    )
    return ui.table(cols, rows, empty=words.both(lang, "empty.no_ledger_record"), lang=lang)


def _source_cell(one, lang: str) -> str:
    """Who wrote the record: `worker` is the row an operator looks for."""
    return ui.pill(one, tone_override="info", lang=lang) if one else ui.DASH


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
