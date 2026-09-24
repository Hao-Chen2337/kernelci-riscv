# SPDX-License-Identifier: LGPL-2.1-or-later
"""`/analysis`: read down the list - is this getting better or worse.

This page's own question is a **pair**: which two builds the reader ticked, and what
changed between them.  The list's one `±` column is *what changed between neighbours in
this order* - a fork, with the row's own build at the fork point, the pair before it on
the upper arm and the pair after it on the lower - and the bars are *what each build's
own records came back as*.  Those are the two the design draws here; between them they
are one question asked of one window.

**The other two ways of asking it are `/trend`'s page**, and this module still builds
them.  The timeline (*one test over the builds*) and the pass-rate chart (*the same
positions as lines*) were drawn here as well until the operator read the same two
pictures on two pages and had to work out which page their question belonged to
(「分析和趋势的这个重复了」).  `_timeline_panel` and `_chart_panel` are defined below,
`/trend` imports them by name, and **nothing in this module calls them** - which is why
the paragraphs further down about a break in the chart, and about two axes on one
screen, are still in this file: they are facts about code that lives here, and it is
drawn one route over.

Which rows key feeds which panel, in the order the design draws them:

    picks      the builds in this order, with the `±` their neighbours give them
    bars       one region per test: each build's own pass / fail / no-answer in it
    drift      the pairs that were read, for one thing only: keeping a `±` door's
               direction the same as the number in the cell it was clicked from
    tests, sorts, apis, trees/branches/arches/defconfigs/compilers   the bars
    drawn, drawn_from   the footer, which the shell writes

and the two reads only `/trend` is handed - no panel on this route reads either:

    timelines  one row per test: runs, last verdict, regressions, the sparkline
    series     the pass-rate chart and its legend

**Two controls the board deleted are kept, because each one is a capability.**  `limit`
is how wide the window is - the board dropped it and drew a client-side pager instead
(`00-BRIEF.md` §9.6) - and the pass-rate chart is the proof it matters: at this
console's default `limit=25` the chart rests on 5 of `boot`'s 22 runs (§10.11), so the
legend prints **drawn / total** per test and the caption names the window, because a
legend that printed the total alone would be a lie about what the line stands on.  The
proof is `/trend`'s now and the box is on both routes, because the window is the window
either way - here it is how many builds the `±` column walks.  `delta` is how deep the
`±` comparison goes (`check.delta`, the engine's own cap), so it is a number box in the
bar and every `±` cell past it says so.

**A `±` cell says *why* it has no number, and never shows a bare dash** (§9.5).  Four
answers, no fifth:

* a number, when the pair around this row in this order was compared - the three numbers
  are `len()` of what `Drift` answered and nothing here computes a difference;
* "the first row in this order" / "the last row in this order": the row has no neighbour
  on that side, which is a fact about the order and not a missing measurement;
* "beyond the delta cap (n)": the row is past the head this render spent config reads on,
  and n is the number in the box above - printed in the cell, not only in a tooltip;
* "not compared: no kernel config on one side": the pair *was* inside the cap and still
  has no number, so `Drift` refused it.  Which of its three refusals it was is the answer
  of the reader that made the comparison, so the cell names the fact it can be sure of
  and **is itself the door** into the pair's page, where `gui.drift` prints the engine's
  own sentence.

**A break in the pass-rate chart is drawn as a break.**  (This one and the next are
about `_chart_panel` and `_timeline_panel`, which `/trend` draws and this route does
not - they are written down here because the code they describe is here.)  `ui.line_chart` splines the
points of each entry it is given, so one entry per test draws a straight line *across* a
position the ledger has nothing for - the board's own defect, measured on its markup
(§9.2: one continuous polyline per test, and a caption promising breaks).  So this page
hands the chart **one entry per contiguous run of records**, laid out so that every run
of one test keeps that test's colour slot: the colour of an entry is its position in the
list and `ui.legend` names the tests by theirs, so a run that drifted one slot would be
drawn in another test's colour and the legend would name the wrong line.  The entries in
between carry no points at all - `line_chart` draws nothing for them - so the only thing
they hold is a colour slot.

**Two axes on one screen, and the page says so.**  On `/trend`, where both are drawn:
`timelines.marks` is chronological (one mark per build of the newest window, oldest
first) while `series` runs along the page's own order (§10.12); side by side and
unlabelled they read as one axis.  The timeline's sub-line states the date axis, the
chart's caption states the order, and the hint under the chart names the difference in
one sentence.

**The pair, and where it lives.**  The reader ticks two rows; the ticks travel as `pick`
(`Filter.pick`, the key `serve.py` resolves into `older`/`newer` for this route), the
upper tick is the older end - which is the engine's own reading of `picks[0]` - and the
bar above the table says so.  From there the pair is spelled `older`/`newer` in every
link this page writes, which is the pair of keys the shipped shell reads and the pair
`ROUTE_KEYS["/analysis"]` carries.  One seam is worth stating rather than discovering:
**`older`, `newer` and `vs` are not `Filter` fields** - `Filter.from_query` drops them
and `to_query` never writes them - so a page can read them only if the wiring puts them
on the check (which is exactly what `serve.py` does for this route).
`getattr(check, "older", "")` is therefore how this module reads them, `pick` is the
fallback that always arrives, and the wiring is what makes a pair survive a link.

**The detail route** `/analysis/<build_id>?vs=<other>` prints the comparison whole,
because a list of five hundred builds can print five hundred numbers and not five hundred
diffs: what a reader gets on the list is the arithmetic and a door, and the door is where
`accept.py`'s X2 follows them and counts the `CONFIG_` names.  Its neighbours are
recomputed rather than trusted from the URL - the filter and the order ride in the link -
so "previous" and "next" mean *in the order the reader was looking at*, which is the
operator's whole model: 排序决定了它以前一个序和后一个序进行一个比较.

Three things this screen does **not** draw, each for a reason rather than by omission:

* **a per-cell selection of a run** (the old page's `?point=`) - and this one is about
  `_timeline_panel`, so it is `/trend`'s behaviour that it describes.  `ui.spark` draws
  the design's `<i>` squares and no links, and `point` is page state `Filter` has no
  field for, so a cell that linked to it would link to a key no reader here consumes.
  What *is* selectable in a timeline row is the test's own name, which narrows the page
  to that test, and a run's own record is one door away on its build's page - the door
  the picks table already draws for every row;
* **a select-all box above the tick column.**  `/jobs` and `/builds` draw one because their
  ticks are a set; this column is a *pair*, the engine reads the first two ids of it and
  ignores the rest, so a box that ticked twenty-five rows would be a control whose effect
  is silently thrown away;
* **the board's three per-panel bars** (find a test, sort the tests, find a build).  Every
  one of them is a `<select>` with no `name` and an `apply` that is `type="button"`
  (`§9.4`) - they cannot submit anything - and the page's own bar already carries `test`,
  while the tests themselves are the three `lib/tests.py` names, which have no order to
  choose.
"""

import urllib.parse
from functools import partial

from .... import errors
from ....build import ARTIFACTS
from ....i18n import DEFAULT_LANG
from ....kbuild import Kbuilds
from ....tests import DEFAULT_TESTS
from ... import values as values_mod
from ...forms import _names, _token
from ...schema import (
    _LABELS,
    CHART_MODES,
    DAY_CHOICES,
    DEFAULT_DELTA,
    EVIDENCE,
    FILTER_ORDER,
    KBUILD_STATES,
    LIMITS,
    MAX_DAYS,
    MAX_LIMIT,
    MODE_EACH,
    RANS,
    RESULTS,
    SORT_KEYS,
    VERDICTS,
)
from ...sorting import _sort_keys, _sort_spec_of
from ...urls import _carried
from ...values import _short as _cut
from .. import ui, words
from .builds import _origin_boxes

# The form the picks table's tick boxes belong to.  A box in a table cell cannot live
# inside a form drawn above the table, so `form=` names it - the same join `/jobs` uses
# for the same problem - and the bar above the table is that form's own submit.  The
# boxes get **no select-all box**, unlike `/jobs` and `/builds`: this column names a
# *pair*, the engine reads the first two ids of it and ignores the rest, so a box that
# ticked twenty-five rows would be a control whose effect is silently thrown away.
_PAIR_FORM = "pair"

# Which keys each of the page's two bars draws.  The first nine are the board's own
# `/analysis` bar in its own order, plus `limit` and `delta`.  The rest are the kbuild
# axes `Filter.accepts` honours on this page and the board's bar never drew: they are
# folded away in a `details.more` (the board's own second row on `/builds`) rather than
# dropped, because hiding a condition is how a reader who narrowed by `origin=card` on
# `/` loses the condition here without being told.  Every key one bar does not draw, the
# other one carries as a hidden field - a GET bar replaces the whole query string - and
# `_carried` is what decides that list, so a key outside `FILTER_ORDER` (`delta`, `tz`)
# rides the same way and neither bar needs a hand-written special case.
#
# `tz` is named in neither.  The clock is one control in the top bar now
# (`shell.tz_switch`), so a bar that drew a second copy would be two answers to one
# question - and the hidden copy is written first, which is how the select this row used
# to draw ended up doing nothing at all.
_MAIN = ("api", "tree", "branch", "arch", "defconfig", "compiler", "test", "limit",
         "delta")
_FOLD = ("state", "result", "ran", "verdict", "origin", "evidence", "missing", "days")

# How many rows of one config-difference category are printed before the rest folds
# away.  The number is the one this page always printed, and the reason is measured: the pair
# `accept.py` names differs by 616 + 618 + 99 options, and printing all of them inline
# was 265 KB and 67 % of the whole page.  The rest of the rows are still in the document
# (inside a `details`), which is what keeps the whole comparison one click away with the
# script off - and what X2 counts.
_DRIFT_FIRST = 25

# The detail route, as a prefix: a build's own page is `/analysis/<build_id>` and the one
# it is compared with is `?vs=<other>`.  The id is quoted when a link is written, because
# a build id is data and a path segment is not the place to find out whether it needs it.
_DETAIL = "/analysis/"


# ------------------------------------------------------------------- the screen
def analysis(view) -> str:
    """The body of `/analysis`: the two bars, the picker, the table, the comparison.

    **This page is about a pair.**  Which two builds, and what changed between them -
    that is the question its table, its `±` column and its `drift` button answer, and it
    is why the page ends where it does.

    **Everything drawn along the axis of time lives on `/trend` now.**  This page used to
    draw the timeline, the comparisons and the chart as well, and `/trend` drew the same
    three by importing these very builders, so the operator read the same two pictures on
    two pages and had to work out which one their question belonged to
    (「分析和趋势的这个重复了」).  The bars panel (`每个构件的结果`) followed them last,
    and for a sharper reason than tidiness: it is one region per *test* and one line per
    *build of the window*, which is an axis of time and a set of tests - `/trend`'s two
    subjects and neither of this page's (「这个分析的这里的这部分是不是可以移动走」).
    The *functions* are still here - `/trend` imports them by name and deleting them
    would break it - but only `/trend` calls them.

    What is left is the board's own order with one panel the board deleted put back where
    the reader acts on it: the pair and its `drift` button sit directly under the table
    the ticks are in, and only once there are two ticks to run them on (`_pair_panel`
    says why that state is the only one where the panel says anything).
    """
    rows = view.rows
    picks = list(rows.get("picks") or ())
    older, newer = _pair(view)
    return "".join((
        _bar(view, _MAIN, _main_fields(view)),
        ui.more(words.both(view.lang, "btn.more"), _bar(view, _FOLD, _fold_fields(view)),
                # The fold this page's 更多筛选 row is remembered by (`ui._fold`).
                fold="more.analysis"),
        _picker(view, older, newer),
        _picks_panel(view, picks),
        _pair_panel(view, older, newer),
    ))


# ------------------------------------------------------------------ the filter
def _bar(view, drawn, fields_html: str) -> str:
    """One of the page's two GET bars: the controls it draws, and the rest of the question.

    A GET bar replaces the whole query string, so every key it does not draw rides as a
    hidden field - `sort` above all, because the `±` column is decided by the order, and
    `pick`, because the pair the reader ticked is page state that `Filter.to_query()`
    never carries and a bar that dropped it would leave the `drift` button below with
    nothing to run on.

    The keys come from `urls._carried` and not from a walk of `FILTER_ORDER`: the order
    is not the whole of the filter, and this page has two fields outside it - `delta`,
    which the folded row above would otherwise drop while its own box stayed put, and
    `tz`, which is the display clock the top bar owns.
    """
    hidden = _carried(view.route, view.check, drawn)
    hidden += [("pick", one) for one in _picked(view)]
    hidden.append(("lang", "" if view.lang == DEFAULT_LANG else view.lang))
    return ui.filters(fields_html, _bar_buttons(view), action=view.route, auto=True,
                      hidden=hidden)


def _bar_buttons(view) -> str:
    """`start over` and `apply`: the two ends of every bar in this layer.

    `apply` is a real submit button and not the board's `type="button"`: the design's own
    bars draw a button that cannot submit anything (§9.4), and with the script off it is
    the only way to change the question.  `start over` is the page with nothing asked of
    it - it drops the pair as well, because a pair is part of the state a reader is
    looking at and "start over" saying otherwise would leave the `drift` button pointing
    at two builds from the previous question.
    """
    lang = view.lang
    return (ui.link_btn(words.both(lang, "btn.reset"),
                        view.url("", *FILTER_ORDER, older="", newer=""), lang=lang)
            + f'<button class="btn primary sm">{words.both(lang, "btn.apply")}</button>')


# How many values the `delta` box offers before it offers a few instead of all of them.
# The rail `ui.number_input` builds is a *view* of the box and submits nothing of its own
# (`script.py`), so this is about reading the control, not about what may be asked for:
# `0..cap` is the honest rail while it fits, and past that the count is a number a reader
# types or spins to.  The cap itself is always offered, so "compare all of them" is one
# of the stops rather than an arithmetic problem.
_DELTA_STOPS = 32


def _delta_stops(cap: int) -> list[str]:
    """The values the `delta` box suggests: every one when they are few, else the ones
    that mean something - the default, the row counts the `limit` box offers, the cap."""
    if cap <= _DELTA_STOPS:
        return [str(one) for one in range(cap + 1)]
    useful = [DEFAULT_DELTA, *(one for one in LIMITS if DEFAULT_DELTA < one < cap), cap]
    return [str(one) for one in useful]


def _main_fields(view) -> str:
    """The bar the board draws, plus the two controls it deleted.

    Nine controls in the board's own order: the API, the three axes a reader names
    several values of at once, the branch, which test the whole page is about, and then
    `limit` and `delta`.  The last two are the ones this page may not lose - the window
    every panel is drawn in, and the cap every `±` cell is read against.
    """
    lang, check, rows = view.lang, view.check, view.rows
    label = partial(ui.word, lang=lang)
    return "".join((
        _api_field(view),
        ui.field(words.both(lang, "word.tree"),
                 ui.multi("tree", _names(check.tree), rows.get("trees") or (),
                          placeholder="state.any", label="word.tree", lang=lang),
                 width="w-lg"),
        ui.field(words.both(lang, "word.branch"),
                 ui.select("branch", _choices(rows.get("branches") or (), check.branch,
                                              lang=lang), check.branch, labeler=label)),
        ui.field(words.both(lang, "word.arch"),
                 ui.multi("arch", _names(check.arch), rows.get("arches") or (),
                          placeholder="state.any", label="word.arch", lang=lang)),
        ui.field(words.both(lang, "word.defconfig"),
                 ui.multi("defconfig", _names(check.defconfig),
                          rows.get("defconfigs") or (), placeholder="state.any",
                          label="word.defconfig", lang=lang), width="w-lg"),
        ui.field(words.both(lang, "word.compiler"),
                 ui.multi("compiler", _names(check.compiler), rows.get("compilers") or (),
                          placeholder="state.any", label="word.compiler", lang=lang)),
        ui.field(words.both(lang, "word.test"),
                 ui.select("test", _choices(rows.get("tests") or (), check.test, lang=lang),
                           check.test, labeler=label)),
        # A number box with a value rail and not a row of preset buttons: the window is a
        # number a reader asks a question with ("the newest 200 builds"), and a fixed row
        # of buttons cannot say it.
        ui.field(words.both(lang, "filter.rows"),
                 ui.number_input("limit", check.limit, min_=1, max_=MAX_LIMIT, stops=LIMITS),
                 width="w-sm"),
        # The comparison cap.  Its value is printed in every `±` cell it stopped, so the
        # number in this box and the sentence in those cells are one number - and its
        # ceiling is the box beside it, because comparing a row this page did not draw
        # is work nothing on the page accounts for (`DEFAULT_DELTA`).
        ui.field(f'<span {words.attr(lang, "title", "delta.cap_title")}>'
                 f'{words.both(lang, "delta.cap")}</span>',
                 ui.number_input("delta", getattr(check, "delta", 0), min_=0,
                                 max_=check.limit, stops=_delta_stops(check.limit)),
                 width="w-sm"),
    ))


def _fold_fields(view) -> str:
    """The rest of the kbuild axes, behind the fold - the board's own second row.

    Every one of these is a condition `Filter.accepts` reads on this page, so a reader who
    set one on `/` can see it in force here and change it.  `days` lives here rather than
    in the row above because a window in days and a window in rows are two questions and
    this is the one that is rarely the answer.

    `ran` and `verdict` are here because the operator asked for the ledger question on this
    page - 「筛选条件能不能起码加一个（跑没跑过就是这个顺序下的通过率）」 - and they are the
    tree's own words for it rather than a new one: `Filter.ran` is `never`/`ever`/`failing`
    over the records of the `test` in force, which is exactly "has this build run that
    test, and what did it say", and `/jobs` draws the same two boxes.  They earn their
    place on a *comparison* page too: `ran=ever` drops every build with nothing recorded,
    so the order the `±` column and the chart are drawn over holds only the rows that have
    a measurement, and `verdict=fail` is the same list narrowed to the failures.
    """
    lang, check = view.lang, view.check
    label = partial(ui.word, lang=lang)
    return "".join((
        ui.field(words.both(lang, "word.state"),
                 ui.select("state", _choices(KBUILD_STATES[1:], check.state, lang=lang),
                           check.state, labeler=label), width="w-sm"),
        ui.field(words.both(lang, "word.result"),
                 ui.select("result", _choices(RESULTS[1:], check.result, lang=lang),
                           check.result, labeler=label), width="w-sm"),
        ui.field(words.both(lang, "filter.ran"),
                 ui.select("ran", _choices(RANS, check.ran, _LABELS["ran"],
                                           any_key=None, lang=lang),
                           check.ran, labeler=label), width="w-sm"),
        ui.field(words.both(lang, "filter.verdict"),
                 ui.select("verdict", _choices(VERDICTS, check.verdict, _LABELS["verdict"],
                                               lang=lang),
                           check.verdict, labeler=label), width="w-md"),
        # 本地 and 远端 as two ticks, the control `/` and `/jobs` draw (`builds._origin_boxes`):
        # one axis, one spelling.  The 有卡片 and 两个都要 values this select used to offer
        # are the card column and "both ticks" respectively, which is why neither is here.
        ui.field(words.both(lang, "filter.origin"), _origin_boxes(view), width="w-md"),
        ui.field(words.both(lang, "filter.evidence"),
                 ui.select("evidence", _choices(EVIDENCE, check.evidence,
                                                _LABELS["evidence"], any_key=None, lang=lang),
                           check.evidence, labeler=label)),
        ui.field(words.both(lang, "filter.missing"),
                 ui.select("missing", _choices(ARTIFACTS, ",".join(check.missing), lang=lang),
                           ",".join(check.missing), labeler=label)),
        # The clock used to be a box here.  It is the top bar's now (`shell.tz_switch`)
        # and this bar carries the reader's choice as a hidden field: it is the one
        # thing on this row that changes nothing about which rows are shown.
        ui.field(words.both(lang, "filter.days"),
                 ui.number_input("days", check.days, max_=MAX_DAYS, stops=DAY_CHOICES),
                 width="w-sm"),
    ))


def _api_field(view) -> str:
    """The `api` box: the stacks this deployment knows, and the one **in force**.

    The option has to name the base in force and not the key a URL carries: the key is
    empty for the base this process started on (`Apis.key`), so a box selected on the key
    would leave the browser showing its first option - another API - on a process that
    started on production (`runs.py`'s own finding).  A value nothing here resolves is
    appended rather than dropped, because a select with nothing selected shows its first
    option and the next `apply` would move the reader to a stack they did not choose.
    """
    lang, check = view.lang, view.check
    apis = getattr(view, "apis", None)
    base = str(getattr(check, "api_base", "") or "") or str(getattr(apis, "launch", "") or "")
    here = str(apis.name(base)) if apis is not None else ""
    options = [(str(name), ui.esc(str(addr)))
               for name, addr in view.rows.get("apis") or ()]
    wanted = here or str(getattr(check, "api", "") or "")
    if wanted and wanted not in [name for name, _word in options]:
        options.append((wanted, ui.esc(view.t("state.current_paren", value=base or wanted))))
    return ui.field(words.both(lang, "filter.api"), ui.select("api", options, wanted),
                    width="w-md")


def _choices(values, current: str = "", labels=None, any_key: str = "state.any",
             lang: str = DEFAULT_LANG) -> list:
    """One select box's options: the value, and the word a reader reads for it.

    A value a URL named and this list does not carry is **appended**, never dropped: a
    select with nothing selected shows its first option, so the next `apply` would send a
    different value than the one in the URL - which is how `?missing=kernel` used to
    become "(any)".  `any_key` is the word for "no condition at all", and it is passed
    only for the axes where the empty value *is* that: `state` and `result` carry their
    own empty entry and a second one would offer a value the filter refuses.

    (`ui.select` leaves this rule to its caller on purpose - it cannot know which values
    a page's data can produce - so every page that draws a box over a *vocabulary* needs
    it.  `/jobs` has the same helper; the two belong in `ui.py` the day a third screen
    needs one.)
    """
    labels = labels or {}
    found = [] if any_key is None else [("", any_key)]
    for one in values:
        if one and all(one != got for got, _word in found):
            found.append((one, labels.get(one) or one))
    if current and all(one != current for one, _word in found):
        found.append((current, words.both(lang, "state.current_paren", value=current)))
    return found


# -------------------------------------------------------------------- the pair
def _picked(view) -> list:
    """The ids the reader ticked, in the order the table drew them.

    `Filter.pick` is page state and a tuple, and the order is the order the boxes appear
    in the document - which is the table's order, which is the page's order.  That is what
    makes "the upper tick is the older end" a fact rather than a hope: `serve.py` reads
    `picks[0]` as `older` and `picks[1]` as `newer` for the shipped route, and this page
    reads the same two the same way.
    """
    return [_token(one) for one in (getattr(view.check, "pick", ()) or ())
            if _token(one)][:2]


def _pair(view) -> tuple:
    """Which two builds this page offers to compare: `(older, newer)`, either may be `""`.

    Two channels, in the order the shipped shell reads them: the keys the *wiring* put on
    the check (`older`/`newer`, page state `Filter` has no field for) and then the ticks
    (`pick`, which `Filter` does own and which therefore always arrives).  Reading both is
    what makes a URL written by the shipped page, by this page's own links and by hand all
    mean the same pair - see the module docstring for why the wiring has to be the one
    that closes this seam.
    """
    picked = _picked(view)
    older = _token(getattr(view.check, "older", "")) or (picked[0] if len(picked) == 2
                                                         else "")
    newer = _token(getattr(view.check, "newer", "")) or (picked[1] if len(picked) == 2
                                                         else "")
    return older, newer


def _page_url(view, *drop, **over) -> str:
    """A link to this screen: the question, the order, and the pair in force.

    `older`/`newer` are page state and not `Filter` fields, so `view.url` cannot carry
    them from the check: they are written into every link by hand, or a reader who
    changes the order (or clicks a test's name) loses the two builds the page is about.
    A caller that wants them gone passes an empty value, which removes the key.
    """
    older, newer = _pair(view)
    over.setdefault("older", older)
    over.setdefault("newer", newer)
    return view.url("", *drop, **over)


def _detail_url(view, older: str, newer: str) -> str:
    """The detail route for one pair, carrying the filter and the order it was read in.

    Built through `view.url`, so `?api=`, the window, the test and the order ride along: a
    comparison read out of the context it was made in is a different comparison.  The
    other side is spelled **twice on purpose** - as `vs`, which is this route's own key
    and the one the acceptance gate builds by hand, and as `pick`, which is a `Filter`
    field and therefore reaches a page whose wiring does not put `vs` on the check.  Both
    name the same build, so no URL here says two different things; and `older`/`newer` are
    dropped, because this route names its own pair.
    """
    return view.url(_DETAIL + urllib.parse.quote(older), "older", "newer", "pick",
                    vs=newer, pick=newer) + "#drift"


def _picker(view, older: str, newer: str) -> str:
    """The bar that turns two ticks into a pair: the board's "compare two builds" bar.

    The board draws two text boxes either side of a `compare` whose `type="button"` cannot
    submit anything (§9.4).  Here the two ends are the ticks in the table below - a build
    id is 24 hex characters nobody types - the bar is a real GET form bound to them, and
    `auto` is **off**: a tick is not a decision, and a bar that submitted on the first
    tick would reload the page once per box, which is the same reason the multi-valued
    axes carry `data-multi`.

    A pair already in force is printed beside the button with the door into its whole
    comparison, so a reader who arrived through a link can see which two builds the page
    is about without counting ticks.
    """
    lang = view.lang
    line = ""
    if older and newer:
        line = ('<span class="row tight">'
                + view.t("one.compare_line", older=ui.esc(_short(older)),
                         newer=ui.esc(_short(newer)))
                + ui.link_btn(words.both(lang, "one.all_rows"),
                              _detail_url(view, older, newer), "sm",
                              title="one.compare_title", lang=lang)
                + "</span>")
    return ui.filters(
        ui.field(words.both(lang, "page.analysis.pair"),
                 f'<span class="muted">{words.both(lang, "page.analysis.pair_how")}</span>',
                 width="w-xl") + line,
        f'<button class="btn primary sm">{words.both(lang, "btn.compare")}</button>',
        action=view.route, auto=False,
        # Every key but `pick`: the ticks below are this bar's own answer to the pair, and
        # a hidden `pick` would compete with them for one key - which is the "two controls
        # for one key" failure the old page was written to avoid.
        hidden=[(key, value) for key, value in view.check.to_query() if key != "pick"]
               + [("lang", "" if lang == DEFAULT_LANG else lang)])


# ------------------------------------------------------------------- the picks
def _picks_panel(view, picks) -> str:
    """The list: the builds the filter chose, in this order, with their neighbours' deltas.

    **One list, three jobs** - which builds, in what order, and what changed between the
    neighbours in that order - so the order control lives in this panel's own head: a
    control that decides a column belongs where the column is read.

    The table carries `class="grid picks"`.  `grid` is the design's table and `picks` is
    the name `accept.py`'s X2 reads this list by when it follows a row's door into a
    comparison.
    """
    lang, rows = view.lang, view.rows
    cap = max(0, int(getattr(view.check, "delta", 0) or 0))
    test = view.check.test or DEFAULT_TESTS[0]
    sub = words.both(lang, "page.analysis.picks_note", shown=len(picks),
                     cap=view.check.limit, test=test)
    if picks and not any(row.get("total") is not None for row in picks):
        # Every row's three counts are a dash, and that is the ledger's own answer rather
        # than a missing reader: 24 of the 60 records here hold `results: {}` and they are
        # all `boot`, which is not a TAP test (§10.2).  Said once, above the table, because
        # a column of dashes with no sentence over it reads as a broken page.
        sub += " · " + words.both(lang, "page.analysis.no_tap_note", test=test)
    if len(picks) > 1:
        # What this render had to go and read, said under the cap that asked for it: the
        # reader who dragged `delta` up to the row count is the reader who pays for the
        # downloads, and the sentence that names the price is also the one that says the
        # second look is free (`var/configs/`, `drift._config_text`).  A page with nothing
        # to compare read nothing, so it says nothing.
        fetched = int(rows.get("fetched") or 0)
        sub += " · " + words.both(
            lang, "page.analysis.fetched" if fetched else "page.analysis.fetched_none",
            n=fetched)
    return ui.panel(
        "page.analysis.picks_title",
        ui.table(_picks_cols(view, picks, cap), picks,
                 empty=words.both(lang, "empty.no_builds"), cls="grid picks", lang=lang),
        sub=sub, tools=_order_control(view), flush=True, lang=lang)


def _picks_cols(view, picks, cap: int) -> tuple:
    """The six columns: the tick, the rank, the build, the describe, the verdict, the fork.

    The tick column is this page's own addition to the board's six - it is the pair
    chooser, and a real box in a real form rather than a picture of one.  `#` prints the
    row's **rank** (`picks.rank`, the position in this order): the prototype's fixture set
    that field and its table never drew it, which is a column that exists in the data and
    not on the page.

    The last column is one **fork** and not two `±` columns: a build sits between two
    neighbours, and the board's pair of columns made a reader scan two places to read one
    relationship.  See `_fork_cell` for what the fork draws.
    """
    lang = view.lang
    return (
        ui.Col("", kind="c", width="28px", draw=lambda row: _tick(view, row)),
        ui.Col("col.n", field="rank", kind="n", width="34px"),
        ui.Col("word.build", kind="id", draw=lambda row: _build_cell(view, row)),
        ui.Col("word.describe", kind="trunc", draw=lambda row: _describe_cell(row)),
        ui.Col("col.verdict", kind="c", draw=lambda row: _verdict_cell(row, lang)),
        ui.Col("col.delta", width="186px",
               draw=lambda row: _fork_cell(view, picks, row, cap)),
    )


def _tick(view, row) -> str:
    """This row's box, bound to the picker bar above the table.

    `checked` is read back off the URL, so the page a reader reloads shows the pair it is
    about, and the name is the engine's own word for what it means (`pick`) - which is
    what makes ticking two rows and pressing `compare` work with the script off.
    """
    return ui.checkbox("pick", "", value=str(row["build_id"]), form=_PAIR_FORM,
                       checked=str(row["build_id"]) in _picked(view), lang=view.lang)


def _build_cell(view, row) -> str:
    """The build: its id as the door into its own page, and the pair that places it.

    The tree and the branch go on a second line because the order being read is often
    `tree-branch`, and then the pair is the row's address while the id is the detail.  The
    whole id rides in the `title=`: the cell prints sixteen characters of twenty-four, and
    a reader who needs the rest should not have to open a page to copy it.
    """
    build = str(row["build_id"])
    return (ui.code(_short(build), href=view.url(_DETAIL + urllib.parse.quote(build)),
                     title=build)
            + '<br><span class="muted" style="font-size:11px">'
            + f'{ui.esc(row["tree"])} / {ui.esc(row["branch"])}</span>')


def _describe_cell(row) -> str:
    """The kernel a build is, as the record spells it - a dash when nobody said."""
    describe = str(row.get("describe") or "")
    return ui.code(describe) if describe else ui.DASH


def _verdict_cell(row, lang: str) -> str:
    """The verdict for the test in force, and **that run's own** `total / fail / skip`.

    The pill is the record's word, so a build with no record for this test is neither a
    pass nor a failure: it says `no record`, which is what the ledger answered.  The three
    numbers are the TAP counts of the record that spoke, and a record which died before
    TAP ran holds none - printing `0/0` for it would be a claim the ledger does not make
    (`data._picks` states the same rule), so the cell shows the design's dash and its
    tooltip says why.
    """
    verdict = str(row.get("verdict") or "")
    if not verdict:
        return f'<span class="dash">{words.both(lang, "analysis.no_record")}</span>'
    if row.get("total") is None:
        counts = (f'<span class="dash" {words.attr(lang, "title", "page.analysis.no_tap")}>'
                  f'&mdash;</span>')
    else:
        counts = ('<span class="q">'
                  + words.both(lang, "page.analysis.tap", total=row["total"],
                               fail=row["failed"], skip=row["skipped"])
                  + "</span>")
    return ui.pill(verdict, lang=lang) + "<br>" + counts


def _fork_cell(view, picks, row, cap: int) -> str:
    """This row's two config comparisons, drawn as one **fork**.

    A build does not have two config deltas; it has two *neighbours*, and the delta is a
    fact about the pair.  The board drew that as two columns - `±` for the row above and
    `±` for the row below - which put the two halves of one relationship in two places and
    left the reader to work out, from the column order alone, which neighbour each number
    was against.  The fork draws the relationship instead: the row's own build is the
    **fork point**, the pair before it leaves on the upper arm and the pair after it on
    the lower one, so the shape says what the two columns only implied.

    The two arms are the *same* bodies the two columns drew (`_edge_body`), each with the
    direction now written into it - a `↑` on the upper arm and a `↓` on the lower - because
    a direction that used to be carried by the column's position has to be carried by the
    cell once there is one column.  Trimmed to `min(cap, rows)` rows the fork is a closed
    tree; at the two ends one arm has no pair to name, and the body says which fact that is
    ("the first row in this order") rather than the arm being drawn empty.
    """
    lang = view.lang
    arms = []
    for side, key, arrow, hint in (("up", "delta_up", "↑", "col.delta_up"),
                                   ("down", "delta_down", "↓", "col.delta_down")):
        # The arrow is not decoration: with one column there is nothing else on the page
        # saying which neighbour the numbers beside it are against.
        arms.append(f'<span class="arm {side}" '
                    f'{words.attr(lang, "title", hint)}>'
                    f'<span class="trunk"></span>'
                    f'<span class="arrow">{arrow}</span>'
                    f'<span class="body">{_edge_body(view, picks, row, key, cap)}</span>'
                    f"</span>")
    return f'<span class="fork">{"".join(arms)}</span>'


def _edge_body(view, picks, row, key: str, cap: int) -> str:
    """One arm of the fork: the pair's three numbers, or **why** there is no number.

    Four answers and no fifth (§9.5, and the module docstring states them): a number; "the
    first row in this order"; "the last row in this order"; "beyond the delta cap (n)",
    which is the cap in the box above printed in the cell itself; and the engine's refusal,
    which is what a pair inside the cap with no number can only be.  Which refusal it was
    is the *door's* answer and not this cell's guess, so the cell says the fact it can be
    sure of and the door opens the engine's own sentence.

    **Every cell that names a pair is a door, number or not.**  The two count-less answers
    that name a neighbour - the cap and the refusal - have always been links, and the three
    numbers were not, which left the page's most useful cells looking like the only inert
    ones on it: a reader who wanted the diff for the pair they were looking at had to guess
    that the *absent* number was the clickable thing.  The number is a link into the same
    route (`_detail_url`), marked by `a.delta-link`'s dotted underline rather than by the
    accent colour, so the cell still reads as three numbers first.

    The direction of that door is the direction of the number beside it: `Drift.series`
    directs every pair **oldest build first** whatever order the list is in, so a door
    built from the list's own order would show `+5` in the cell and `−5` on the page it
    opened whenever the sort ran the other way - which `date-asc`, `verdict` and
    `tree-branch` all do.  `_directed` reads the direction off the engine's own rows.

    What comes back is one **arm's** body and not a cell: `_fork_cell` puts the two arms
    together, and every sentence above about "the cell" is about the contents this
    returns.  `key` is still the arm's own name (`delta_up` / `delta_down`) because that
    is the direction - which neighbour the pair is against - and nothing else changes.
    """
    lang = view.lang
    pair = row.get(key)
    at = int(row.get("rank", 0)) - 1
    here = str(row["build_id"])
    first, last = at == 0, at == len(picks) - 1
    if pair is not None:
        # A number is a door too, and it is the door a reader most often wants: the cells
        # that *have* a number are the pairs this page actually read.  Until this link
        # existed the only cells that opened anything were the ones with **no** number, so
        # the comparisons a reader is most likely to want were the ones that looked inert.
        # Same door as the count-less branch below - `_directed` for the direction the
        # engine read the pair in, `_detail_url` for the route - and the tooltip names the
        # other end, which is what tells a number from the two identical-looking `±` cells
        # beside it.  The index is checked like the branch below does: `rank` is the data's
        # field and not this page's index, and a row that arrived without one must not
        # raise out of a cell whose whole job is to answer "what is here".
        other_at = at - 1 if key == "delta_up" else at + 1
        if 0 <= other_at < len(picks):
            there = str(picks[other_at]["build_id"])
            return (f'<a class="delta-link" '
                    f'{words.attr(lang, "title", "delta.door_title", build=_short(there))} '
                    f'href="{ui.esc(_detail_url(view, *_directed(view, here, there)))}">'
                    f'{ui.delta(pair, lang=lang)}</a>')
        return ui.delta(pair, lang=lang)
    if first:
        return ui.delta(None, first=True, lang=lang)
    if last:
        return ui.delta(None, last=True, lang=lang)
    other_at = at - 1 if key == "delta_up" else at + 1
    if not 0 <= other_at < len(picks):
        # Unreachable for rows whose `rank` is their position in this list (the ends are
        # answered above), and kept because `rank` is the *data's* field and not this
        # page's index: a row that arrived with a rank of 0 would otherwise raise a
        # `KeyError` on a page whose whole job is to answer "why is there no number here".
        return (f'<span class="muted" {words.attr(lang, "title", "analysis.not_compared")}>'
                f'{words.both(lang, "analysis.not_compared")}</span>')
    # Row `at` reads `edges[at - 1]` for its up cell and `edges[at]` for its down cell, and
    # `_config_edges` built one edge per adjacent pair of the first `min(cap, rows)` rows -
    # so the edge on this side exists exactly when the index below is inside that head.
    head = min(cap, len(picks))
    attempted = other_at <= (head - 1 if key == "delta_up" else head - 2)
    there = str(picks[other_at]["build_id"])
    body = (words.both(lang, "page.analysis.no_config") if attempted
            else words.both(lang, "delta.beyond", n=cap))
    return ('<a class="muted" '
            f'{words.attr(lang, "title", "delta.door_title", build=_short(there))} '
            f'href="{ui.esc(_detail_url(view, *_directed(view, here, there)))}">'
            f"{body}</a>")


def _directed(view, first: str, second: str) -> tuple:
    """Two ids as the engine compared them: the older one first.

    `rows["drift"]` is the engine's own list of the pairs this render read, and each row
    of it carries `left`/`right` already directed oldest-first (`data._drift`, from the
    same `Drift.series` answer the `±` numbers came out of).  A pair that is not in it -
    one past the cap, or one the engine refused - keeps the order it was given in, which
    is the order the reader was looking at.
    """
    if first == second:
        return first, second
    for one in view.rows.get("drift") or ():
        if {str(one["left"]), str(one["right"])} == {first, second}:
            return str(one["left"]), str(one["right"])
    return first, second


def _order_control(view) -> str:
    """The order, as the keys in force plus one link that adds each key (§5's own control).

    The operator asked for two things here and they are one control: **several keys at
    once** (`?sort=tree-branch,date`) and **the order visible enough to change one of
    them**.  So the keys in force are chips numbered by position - each with an arrow that
    reverses it - and every key not in force is a `+key` link that appends it at its
    default direction.  It is a row of *links* and not a form: the order is a `Filter`
    field, so every link on this page already carries it, and a control whose state is the
    URL survives a reload, a bookmark and a script turned off.

    The `×` is drawn only when more than one key is in force, and that is not a style
    choice: an empty `sort` *means* the page's default order (`date ↓`), so dropping the
    last key would look like "no order at all" and be `date ↓` again - a control that
    appears to do nothing, which is the defect class this round exists to remove.  One key
    keeps its arrow instead.
    """
    lang = view.lang
    keys = _sort_keys(view.check.sort)
    in_force = {name for name, _direction in keys}
    chips = []
    for at, (name, direction) in enumerate(keys):
        flipped = [(other, ("desc" if direction == "asc" else "asc") if other == name
                    else other_dir) for other, other_dir in keys]
        parts = [ui.link_btn(words.both(lang, "sort.dir." + direction),
                             _page_url(view, sort=_sort_spec_of(flipped)), "sm",
                             title="sort.flip_title", lang=lang)]
        if len(keys) > 1:
            rest = _sort_spec_of([one for one in keys if one[0] != name])
            parts.append(ui.link_btn("&times;", _page_url(view, sort=rest), "sm",
                                     title="sort.drop_title", lang=lang))
        chips.append(f'<span class="chip"><span class="k">{at + 1}. '
                     + words.both(lang, "sort.k." + name.replace("-", "_"))
                     + "</span>" + "".join(parts) + "</span>")
    adds = "".join(
        # `+` and the key's own two-column span, rather than the catalogue's `sort.add`
        # row: its placeholder is called `{key}`, and `words.both`'s second parameter is
        # called `key` too, so filling it through that call is a `TypeError` and not a
        # string (`lib.i18n.t` spells `lang`/`key` as positional-only for exactly this
        # reason).  The join is a glyph and two spans, so both columns still swap.
        ui.link_btn("+" + words.both(lang, "sort.k." + name.replace("-", "_")),
                    _page_url(view, sort=_sort_spec_of([*keys, (name, SORT_KEYS[name][0])])),
                    "sm", lang=lang)
        for name in SORT_KEYS if name not in in_force)
    return (f'<span class="row tight"><span class="muted">'
            f'{words.both(lang, "filter.sort")}</span>'
            f'{"".join(chips)}{adds}</span>')


# ------------------------------------------------------------------- the panels
def _timeline_panel(view, timelines, test_key: str = "test") -> str:
    """One row per test: how many runs, the last verdict, the regressions, and the run of them.

    The sparkline's gaps are **positions the ledger has nothing for**, drawn as empty
    squares whose tooltip says so (`ui.spark`): the marks are one per build of the window
    this page drew, in this page's order, so a test that stopped running is a run of empty
    squares instead of a line that pretends.  That axis, and the three counts beside it,
    are the same window and the same order the chart below runs along - the sub-line says
    so (`page.analysis.axes_note`), because a reader who has just read a sparkline carries
    its axis down to the next panel whether or not the two agree.

    The test's name is a link to this page with that test chosen - the one thing a reader
    looking at a row wants next - and it also keeps this panel's cells selectable, which
    is what `accept.py`'s X3 reads for.

    `test_key` is *which* of the two test keys the link writes: this page's `?test=` is a
    single-valued condition (`Filter.test` narrows `ran`/`verdict`), while `/trend`'s
    `?tests=` is the set it draws, and clicking a name there means "just this one" -
    `view.link("", …, tests="boot")` is that whole sentence.  The default is this page's
    key, so every caller that passes nothing is unchanged.
    """
    lang = view.lang
    cols = (
        ui.Col("word.test", draw=lambda row: _test_cell(view, row, test_key)),
        ui.Col("label.runs", field="runs", kind="n", width="64px"),
        ui.Col("label.last", kind="c", draw=lambda row: _last_cell(row, lang)),
        ui.Col("col.regressions", kind="n", width="96px",
               draw=lambda row: _regressions_cell(row)),
        ui.Col("col.timeline", draw=lambda row: ui.spark(row["marks"], lang=lang)),
    )
    return ui.panel("page.analysis.trend_title",
                    ui.table(cols, timelines, empty=words.both(lang, "empty.no_rows"),
                             lang=lang),
                    sub=words.both(lang, "page.analysis.timeline_sub") + " · "
                        + words.both(lang, "page.analysis.axes_note"),
                    flush=True, lang=lang)


def _test_cell(view, row, test_key: str = "test") -> str:
    """The test's name, as the link that narrows the page to that test.

    The key is the caller's (`_timeline_panel` says which page writes which), and it is
    built as a dict rather than keyword-by-name because it is a *variable* key: `?test=`
    on `/analysis`, `?tests=` on `/trend`, and `view.link`'s keyword is the key.
    """
    name = str(row["test"])
    return view.link("", ui.code(name), **{test_key: name})


def _last_cell(row, lang) -> str:
    """The newest verdict for this test, or the word for a test that has not run.

    `last` is `None` when the ledger holds no record for the test at all, and an empty
    pill would say nothing: the honest word for it is `state.no_runs`.
    """
    last = str(row.get("last") or "")
    if not last:
        return f'<span class="muted">{words.both(lang, "state.no_runs")}</span>'
    return ui.pill(last, lang=lang)


def _regressions_cell(row) -> str:
    """How many transitions landed on a worse verdict: the number coloured, or a plain zero.

    The count is `re.transitions()`'s own - this page counts nothing - and zero is muted
    because zero regressions is not news, while any other number is the one thing on this
    row a reader is looking for.
    """
    n = int(row.get("regressions") or 0)
    return f'<span class="cross">{n}</span>' if n else '<span class="muted">0</span>'


def _when(view, stamp: str) -> str:
    """A stamp as a cell: the page's clock, with the stored value one hover away.

    The `title=` is only added when the two differ - a page printing UTC has nothing to
    add - and the raw value is the whole one, minutes and seconds included, because the
    cell is what a reader copies from.
    """
    whole = str(stamp or "")
    if not whole:
        return ui.DASH
    shown = values_mod._in_clock(whole, view.check.tz)
    attr = f' title="{ui.esc(whole)}"' if shown != whole else ""
    return f'<span class="nowrap muted"{attr}>{ui.esc(shown)}</span>'


def _compares_panel(view, timelines) -> str:
    """What was compared, read record by record: one row per build, and the step into it.

    **One row per record and not per pair.**  The list this replaced had a row per
    *comparison*, the older side in one column and the newer side in the next, so the
    operator's own window - 68 records, 65 comparisons (「这个窗口里比较了 65 组相邻记录」)
    - was 65 rows in which 62 of the 68 records appeared **twice**: once as the newer side
    of its own step and once as the older side of the next one, while the thing a reader
    scans for (which build is this row about, and when) was not the subject of the row at
    all (「这里应该给是一 build 为主吧」).  A record is what the ledger stores -
    `var/results/<build>/<test>.json` is one file per (build, test) pair - and a
    comparison is what can be said *about* two records, so the subject of a row is the
    record and `判定` is one of its attributes.

    **The pair is the row above.**  `_record_rows` keeps `data._timelines`' own order for
    each test's comparisons - oldest first, the order `re.transitions()` reads them in,
    which is **not** the page's `sort`: a reader who reverses the window reverses the
    timeline's cells and this list keeps its chronology, the same way it always has - so
    the record a row was compared against is the row directly above it, and the two
    columns this replaced said exactly that, twice.  A test's oldest record in the window
    has nothing above it and `判定` prints `窗口起点`: it is in the list because it is one
    of the window's records, and it is not a comparison because the window made none with
    it.

    **The 判定 column is derived and not stored.**  `regression` is `re.transitions()`'s
    own answer (a comparison is a regression when it is the transition the detector
    returned, which is why a run of consecutive failures is one `回归` and three
    `仍是失败` rows and not four); everything else follows from the two verdicts.  Two
    readings of one fact would be a second vocabulary for the ledger's words, so
    `_change_cell` reads the verdicts the row already carries.

    **The sub-line counts comparisons and not rows**, and it says both: `{m}` is how many
    records the window holds, `{n}` how many adjacent pairs they make - one fewer per
    test, which is the number the panel used to be made of - and `{r}` how many of those
    pairs were regressions, which is the integer the timeline's 回归 column is.  A reader
    who has just read the timeline above needs all three to check it.

    The build id is a door into that build's own page, and the stamp is printed in
    `Filter.tz`'s clock with the stored UTC in the `title=` - the rule `/worker` prints
    its records by, so the two pages do not disagree about which clock a stamp is in.

    The fold is the diff sections' own and for their reason: this list is longer than the
    four-row one it replaced by an order of magnitude, and the counts stay in the
    sub-line, so a folded row is never a hidden one.
    """
    lang = view.lang
    rows = [one for timeline in timelines for one in _record_rows(timeline)]
    pairs = sum(len(one.get("comparisons") or ()) for one in timelines)
    found = sum(int(one.get("regressions") or 0) for one in timelines)
    sub = words.both(lang, "page.analysis.compares_sub", m=len(rows), n=pairs, r=found)
    if not rows:
        return ui.panel("page.analysis.compares_title",
                        ui.empty(words.both(lang, "page.analysis.compares_none")),
                        sub=sub, lang=lang)
    cols = (ui.Col("word.test", field="test"),
            ui.Col("page.analysis.cmp_col",
                   draw=lambda row: _change_cell(row, lang)),
            ui.Col("word.build_id",
                   draw=lambda row: _record_cell(view, row, lang)))
    table = ui.table(cols, rows[:_DRIFT_FIRST], cls="grid", lang=lang)
    rest = rows[_DRIFT_FIRST:]
    if rest:
        table += ui.more(words.both(lang, "drift.all_rows", n=len(rows)),
                         ui.table(cols, rest, cls="grid", lang=lang), fold="more.pairs")
    return ui.panel("page.analysis.compares_title", table, sub=sub, flush=True, lang=lang)


def _record_rows(timeline) -> list[dict]:
    """One test's comparisons read as one row per record: the step into each, oldest first.

    `comparisons` is `data._timelines`' own list for this test - adjacent pair after
    adjacent pair, oldest first, `regression` already marked (`data._pair_key` says how
    the mark is matched) - and a row here is that pair's *newer* side, carrying both
    verdicts and the mark, because those three fields are the whole of what
    `_change_cell` reads.

    The oldest record of the window is the one record in `comparisons` that is never a
    `newer` side: it is the first pair's `older`.  It gets a row of its own - a reader
    looking at a window of records is looking at that one too, and a list that started at
    the second-oldest would be missing a build - marked `first`, which is what
    `_change_cell` prints `窗口起点` for.  Marked, and not inferred from an empty
    `older_verdict`: a record that ran and came back with no verdict at all
    (`incomplete`, `error`) has an empty one as well, and that step is `其他` and not the
    start of the window.

    A test with fewer than two records in the window made no comparison and gets no rows:
    this is the *comparison* panel, and `compares_none` is its sentence for a window
    where no test has a pair.
    """
    comparisons = list(timeline.get("comparisons") or ())
    if not comparisons:
        return []
    test = str(timeline.get("test") or "")
    oldest = comparisons[0]
    rows = [{"test": test, "first": True,
             "build": oldest.get("older"), "at": oldest.get("older_at"),
             "verdict": oldest.get("older_verdict")}]
    rows += [{"test": test,
              "build": one.get("newer"), "at": one.get("newer_at"),
              "verdict": one.get("newer_verdict"),
              # The older end of the step, under a name that says what it is *to this
              # row* rather than which end of the pair it was: the row's own verdict is
              # `verdict` and this is the one it is being read against.
              "from_verdict": one.get("older_verdict"),
              "regression": one.get("regression")}
             for one in comparisons]
    return rows


def _change_cell(row, lang: str) -> str:
    """What the step into this record was, in one word: the regression, or the thing that was not.

    Six sentences and no seventh, and every one of them is readable off the row's own
    verdict, the one it is read against (`from_verdict`) and `regression`
    (`_compares_panel` says why nothing else is stored) - bar the first, which is read off
    the row's own `first` flag and is not a step at all:

    * **`窗口起点`** - the oldest record of the window, with nothing above it to be
      compared against (`_record_rows` marks it and says why the mark is a flag rather
      than an empty `from_verdict`).  It is a record that is in the list because the
      list is the window's records; the comparison it did not take part in is why there
      are one fewer pairs than rows.
    * **`回归`** - the transition `re.transitions()` returned.  A `pass -> fail` step is
      always one of these (the detector re-arms on a fresh pass, so the first failure
      after a pass is the transition itself), and it is marked from the flag rather than
      from the verdicts so a change to the detector's rule cannot leave this column
      disagreeing with the count.
    * **`仍在失败`** - a failure after a failure.  The run is compared and is *not* a new
      regression, which is the rule that stops one bad build reporting a new regression
      every night it stays bad; these are the rows a four-row panel hid.
    * **`恢复`** - a failure followed by a pass: the test came back, and the detector is
      armed again.
    * **`仍通过`** and **`其他`** - nothing moved, and everything else (`incomplete` and
      `error` are answers too, and a step into or out of one is not any of the four
      above).  `其他` is deliberately vague: it is the honest word for "the verdicts are
      not pass and fail in one of the four arrangements".
    """
    if row.get("first"):
        key = "page.analysis.cmp_first"
    elif row.get("regression"):
        key = "page.analysis.cmp_regression"
    elif (row.get("from_verdict") == errors.VERDICT_FAIL
          and row.get("verdict") == errors.VERDICT_FAIL):
        key = "page.analysis.cmp_failing"
    elif (row.get("from_verdict") == errors.VERDICT_FAIL
          and row.get("verdict") == errors.VERDICT_PASS):
        key = "page.analysis.cmp_recovered"
    elif (row.get("from_verdict") == errors.VERDICT_PASS
          and row.get("verdict") == errors.VERDICT_PASS):
        key = "page.analysis.cmp_holding"
    else:
        key = "page.analysis.cmp_other"
    tone = key == "page.analysis.cmp_regression"
    # `words.both` hands back an element, not a string - the `data-en`/`data-zh` span the
    # language swap reads - so it goes in **raw**.  It was `ui.esc`'d here, which is the
    # one thing that turns it into the wrong thing: every cell of this column printed the
    # span's own markup as its text (`<span data-i18n="text" data-en="still passing" …>`)
    # and the column the panel exists for was the one column a reader could not read.
    # `words.both`'s docstring is the rule - a page writes its return value into the page,
    # and `_last_cell`/`_timeline_panel` beside this one already do.
    word = words.both(lang, key)
    return f'<span class="bad">{word}</span>' if tone else word


def _record_cell(view, row, lang: str) -> str:
    """A row's own record: the build id as a door, how it came back, and when it was recorded.

    **`_record_cell` and not `_build_cell`**: that name is the picks table's own build
    column, three hundred lines above, and a second `_build_cell` at module level does not
    collide loudly - the later definition simply wins and every caller of the earlier one
    gets a `TypeError` about a missing argument (`/analysis` 500'd on exactly that while
    this panel was being written).

    The verdict is the record's own word as the console's own pill (`ui.pill`), read
    off the row and never re-derived: the 判定 column says what the *step into* this
    record was, and this says what the record itself was, which is the pair of facts a
    reader needs to agree or disagree with it.

    One cell for the one side a row has.  It used to be drawn twice per comparison - as
    the older side of one row and the newer side of the next, off three key names the
    caller passed in - and the keys are literals now because there is one of each.
    """
    build = str(row.get("build") or "")
    if not build:
        return ui.DASH
    verdict = str(row.get("verdict") or "")
    return (ui.code(_cut(build), href=view.url(_DETAIL + urllib.parse.quote(build)),
                    title=build)
            + " " + (ui.pill(verdict, lang=lang) if verdict else ui.DASH)
            + " " + _when(view, row.get("at")))


def _chart_panel(view, series) -> str:
    """The pass rate in this order: one line per test, with its legend and its two modes.

    The legend and the caption carry the facts that make the picture honest:

    * **how many runs are drawn out of how many the ledger has.**  The window is the
      newest `limit` builds of the order, and at this console's default that is 5 of
      `boot`'s 22 runs (§10.11): a legend printing the total alone would be a lie about
      what the line rests on, so every entry prints `drawn / total`;
    * **which axis this is.**  The caption says the positions are the table's, in this
      order - and that is the timeline panel's axis too, cells and counts alike
      (`page.analysis.axes_note` says so under that panel), so the two pictures of one
      window can be read against each other;
    * **which of the two questions the `y` axis answers.**  `schema.CHART_MODES` holds
      them and `data._points` does the arithmetic; what this panel owes the reader is the
      sentence, and it is a different sentence for each mode because the two curves mean
      different things: on the accumulated reading a flat stretch is a *carried* value
      (nothing ran there, so the rate stood still) while on the per-build reading it is a
      run that came back where the last one did.  A panel that printed one sentence over
      both would be describing the wrong picture half the time.

    The mode is read off the check and never off this function's arguments: it is page
    state (`PAGE_STATE["/trend"]`), so `data.rows` has already refused anything the box
    does not offer and this reads the same answer the points were built from.

    A test with no record anywhere in the window has no entry to draw, and when *no* test
    has one the panel says so instead of printing axes over nothing.  That sentence is
    `ui.chart_none` and not `ui.empty`: an empty chart is a **plate of a band's own
    height** with the sentence on it, so the panel keeps the shape of a picture at
    `/trend?ran=never` - the window a new stack shows first - instead of collapsing into
    one line of grey where a chart was promised.
    """
    lang = view.lang
    each = _mode_of(view) == MODE_EACH
    rows = [one for one in series if isinstance(one, dict)]
    slots = max([int(one.get("slots") or 0) for one in rows] or [0])
    ends = next((tuple(one.get("ends") or ("", "")) for one in rows if one.get("ends")),
                ("", ""))
    cap = int(getattr(view.check, "limit", 0) or 0)
    entries = _chart_series(rows)
    sub = words.both(lang, "page.analysis.chart_sub_each" if each
                     else "page.analysis.chart_sub")
    if not any(points for _name, points in entries):
        return ui.panel("page.analysis.chart",
                        ui.chart_none(words.both(lang, "page.analysis.chart_none")),
                        sub=sub, lang=lang)
    # `kept` and not `len(points)`: on the accumulated reading a position inside the run
    # draws a point it has no record for, so the drawn count can exceed the ledger's
    # (`data._series` says which number is which).  The legend is a statement about the
    # evidence, so it counts the records.
    legend = ui.legend([{"test": str(one.get("test") or ""),
                         "runs": f'{one.get("kept") or 0} / {one.get("runs") or 0}'}
                        for one in rows], lang=lang)
    chart = ui.line_chart(entries, slots=slots, ends=ends,
                          caption=words.both(lang, "page.analysis.chart_cap", n=slots,
                                             cap=cap),
                          # The marker's own sentence says which reading the number is
                          # (`chart.point` / `chart.point.each`): "80%" on the accumulated
                          # curve is a rate over everything up to that position and on the
                          # per-build one it is that build's own run, and the two are the
                          # same three characters on screen.
                          point="chart.point.each" if each else "chart.point",
                          lang=lang)
    return ui.panel("page.analysis.chart", legend + chart, sub=sub, lang=lang)


def _mode_of(view) -> str:
    """Which of `schema.CHART_MODES` this request asked for, refused to the default.

    `data.rows` has already made this decision for the points (`rows["mode"]`), so this
    reads **that** and not the check: a panel and the curve it draws may not answer two
    different questions, and reading the same answer twice from one place is how that
    stays true.  The check is the fallback for a caller that handed no rows - a test, or
    a page that draws the panel without the data layer.
    """
    rows = getattr(view, "rows", None) or {}
    mode = str(rows.get("mode") or getattr(view.check, "mode", "") or "")
    return mode if mode in CHART_MODES else CHART_MODES[0]


def _chart_series(series) -> list:
    """The `series` rows as the list `ui.line_chart` draws one polyline for each entry of.

    **One entry per contiguous run of records**, because that is the only way the break
    the caption promises gets drawn: `line_chart` splines the points of one entry, so a
    test whose records skip three positions comes out of a single entry as a line *across*
    the gap - the board's own fault, measured on its markup (§9.2: one continuous polyline
    per test, under a caption promising breaks).

    The colour of an entry is its **position in this list** (`ui.SERIES`) and the legend
    names the tests by *their* position in its own list, so every run of one test has to
    land on that test's slot or the legend would name the wrong line.  Each run therefore
    goes at the first index congruent to the test's own, and the entries in between are
    empty: a row with no points draws no polyline and no marker, so a placeholder costs a
    little markup and nothing a reader can see.  (One entry per test is a line across every
    gap; one entry per run with no slots reserved is each run in the next test's colour.)
    """
    out = []
    for at, one in enumerate(series):
        for run in _contiguous(one.get("points") or ()):
            while len(out) % len(ui.SERIES) != at % len(ui.SERIES):
                out.append((str(one.get("test") or ""), ()))
            out.append((str(one.get("test") or ""),
                        [(point.get("at", 0), point.get("pct", 0)) for point in run]))
    return out


def _contiguous(points) -> list:
    """One test's points split into runs of adjacent positions of the order.

    Adjacent means `at` differs by one: the positions are the order's, so two records with
    a build between them are two runs and not one line.  A single point is a run of one -
    which draws a marker and no line, and that is exactly what one record at a position is.
    """
    runs, run = [], []
    for point in points:
        at = int(point.get("at", 0))
        if run and at != int(run[-1].get("at", 0)) + 1:
            runs.append(run)
            run = []
        run.append(point)
    if run:
        runs.append(run)
    return runs


def _bars_panel(view, regions) -> str:
    """How each build came back: which tests to draw, then one region per test.

    One reading of one window, per test: a heading naming the test and its totals over
    the window's builds, and under it **one line per build** - that build's own pass /
    fail / no-answer for that test, the numbers beside the line.  Three regions stacked
    is what makes the panel's question askable at all: a reader who wants to know
    whether the same build that failed `boot` also failed `kselftest-riscv` reads that
    build's line in each region, and the single test the page's own `test` box names
    could never answer it.

    **Which tests get a region is the page's own `tests` box**, and this panel draws no
    picker of its own.  It had one while it lived on `/analysis`, where the box above it
    asked the *other* question - `test`, the single test `Filter.accepts` reads
    `ran`/`verdict` over and the picks table names in its verdict column - and the
    panel's axis therefore had nowhere else to be said.  The two controls even needed
    two names for themselves (`page.analysis.bars_pick` was not `word.test`) for the
    reason one word over two controls is how a reader comes to read them as one control.
    On `/trend` the box above asks exactly this question: `tests`, the set of tests the
    page draws a line per, which is also what the timeline and the chart are drawn over.
    A second box at the foot of that page would be one key with two controls - and the
    forms would not even be peers, since a GET bar replaces the whole query string and
    the panel's own would have had to spell out `mode` and `sort` by hand to hand the
    reader back the picture they were reading.

    With nothing in the window there are no lines to draw under any heading, and the
    regions are replaced by the design's own empty line: three headings over nothing
    would be a picture of a question with no answer in it.
    """
    lang = view.lang
    drawn = sum(len(one.get("bars") or ()) for one in regions)
    body = ui.test_bars(regions) if drawn else ui.empty(words.both(lang, "empty.no_rows"))
    return ui.panel("page.analysis.bars", body,
                    sub=words.both(lang, "page.analysis.bars_sub"), lang=lang)


def _pair_panel(view, older: str, newer: str) -> str:
    """The pair in force, the door into its whole comparison, and the `drift` button.

    Three things about one pair and each is a different question: *which* two builds (the
    line), *what their configs differ by in full* (the door - a list of five hundred builds
    can print five hundred numbers and not five hundred diffs), and *what an operator could
    run* (the action bar, whose command line comes from `Gui.command()` and nowhere else).
    The fields are the engine's own names for this action (`api`, `older`, `newer`), and
    the answer to the POST is written into the `[data-status]` line inside the form - which
    is also the hook `tools/check_hooks.py` reads on this screen.

    **A panel with no pair is not drawn at all**, and that is the whole of the fix for the
    row the operator pasted (「在上面那个表里勾两行，然后按对比…／跑 drift.py 这个是不是
    没有必要」).  Without two ticks this panel used to print the picker bar's instruction a
    second time - this copy pointing *up* at the table the bar had pointed down at - over a
    disabled `drift` button whose `title=` **was that same sentence**, because an action
    with nothing to compare has no other reason to give.  So the state the reader met was
    one sentence twice and a button that could do neither half of what it said: nothing in
    it was a second answer, and the page above it already teaches the gesture.  What is
    *not* redundant is the pair: with two rows ticked this is the one place the two ids,
    the door into their whole diff and the command line to reproduce it all stand together
    - which is why it is drawn here and not only on the detail route the door opens.  (The
    board draws no such panel at all; this is the old page's `drift` action put back where
    the ticks are, and it now costs a reader who has ticked nothing exactly nothing.)
    """
    lang, check = view.lang, view.check
    if not (older and newer):
        return ""
    return ui.panel("one.compare_title", (
        '<p class="row tight">'
        + view.t("one.compare_line", older=ui.esc(_short(older)),
                 newer=ui.esc(_short(newer)))
        + ui.link_btn(words.both(lang, "one.all_rows"), _detail_url(view, older, newer),
                      "sm", title="one.compare_title", lang=lang)
        + "</p>"
        + ui.action_form(
            "drift", words.both(lang, "btn.run_drift"),
            fields=[("api", check.api), ("older", older), ("newer", newer)],
            # The command line is the engine's own (`Gui.command()`, through `_argv_of`):
            # two ids are always here, so this never prints a refusal about a chooser the
            # page does not draw.
            argv=view.gui._argv_of("drift", {"older": older, "newer": newer}, lang,
                                   api=check.api),
            hint="analysis.drift_hint", lang=lang)),
        lang=lang)


# ------------------------------------------------------------------ the detail
def detail(view) -> str:
    """`/analysis/<build_id>?vs=<other>`: one build, its neighbours, and the whole diff.

    The route every number on the list is a door into.  Three panels and no more, because
    a reader who clicked a `±` asked one question: the build's own counts, the neighbours it
    had *in the order they were looking at* (each a door into that comparison), and the
    pair's config difference printed whole - which is what makes `accept.py`'s X2 count the
    `CONFIG_` names here rather than on the list.

    The comparison is the one read this page makes that the list does not: `gui.drift`,
    through the engine's own `Drift`, handed the builds this console has already read as
    its catalogue.  That argument is not an optimisation - without it `Drift` looks a build
    id up by **scanning** the API (`kbuild.SCAN`, 116.8-137.9 s measured on production) and
    a GET may not start that.  An id neither the cards nor this window's answer knew is
    refused by name for the same reason, never looked up.
    """
    rows = view.rows
    picks = list(rows.get("picks") or ())
    here = _route_id(view.route)
    other = _other_side(view, here)
    return "".join((
        _one_panel(view, picks, here),
        _doors_panel(view, picks, here),
        _compare_panel(view, here, other),
    ))


def _one_panel(view, picks, here: str) -> str:
    """The build's own row: what it is, which run spoke, and that run's three counts.

    The counts are the same numbers the list's verdict cell printed for this row, from the
    same record through the same reader, so a reader who followed a door cannot find the
    two pages disagreeing about what a build did.  A build the window did not read has no
    row here, and the page says **which** window it looked in rather than showing an empty
    table.
    """
    lang = view.lang
    row = next((one for one in picks if str(one["build_id"]) == here), None)
    test = view.check.test or DEFAULT_TESTS[0]
    sub = words.both(lang, "page.one.sub", build=ui.esc(_short(here)))
    pairs = [("word.build_id", ui.code(here, title=here))]
    if row is not None:
        pairs += [("word.tree_branch", ui.esc(f'{row["tree"]} / {row["branch"]}')),
                  ("word.describe", _describe_cell(row)),
                  ("word.test", ui.code(test)),
                  ("col.verdict", _verdict_cell(row, lang))]
    body = ui.kv([(words.both(lang, key), value) for key, value in pairs])
    if row is None:
        body += ui.hint(words.both(lang, "one.not_in_window", build=ui.esc(_short(here)),
                                   n=view.check.limit))
    return ui.panel("page.one.title", body, sub=sub,
                    tools=ui.link_btn(words.both(lang, "one.back"),
                                      view.url("/analysis"), "sm", lang=lang), lang=lang)


def _doors_panel(view, picks, here: str) -> str:
    """The neighbours this build had in the order the reader was looking at.

    Recomputed rather than trusted from the URL: this build's position is read out of the
    order the link carried, which is what makes "previous" and "next" mean what the row
    meant.  Each door is the whole comparison of that pair (`/analysis/<other>?vs=<this>`),
    and the order control sits in the panel's head because changing the order changes which
    builds are neighbours at all.
    """
    lang = view.lang
    at = next((one for one, row in enumerate(picks) if str(row["build_id"]) == here), None)
    doors = []
    if at is not None:
        for other_at, key in ((at - 1, "delta.before"), (at + 1, "delta.after")):
            if not 0 <= other_at < len(picks):
                continue
            there = str(picks[other_at]["build_id"])
            doors.append((key, there))
    body = (('<span class="row tight">' + "".join(
        ui.link_btn(words.both(lang, key) + " " + ui.code(_short(there)),
                    _detail_url(view, *_directed(view, here, there)), "sm",
                    # The title is rendered here and not passed as a key: `delta.door_title`
                    # carries the other build's id as `{build}`, and `ui.link_btn` has no
                    # `fmt`, so a key would reach the reader as those six characters.
                    title=view.t("delta.door_title", build=_short(there)), lang=lang)
        for key, there in doors) + "</span>") if doors
        else ui.hint(words.both(lang, "one.no_neighbours")))
    return ui.panel("one.neighbours", body, tools=_order_control(view), lang=lang)


def _compare_panel(view, here: str, other: str) -> str:
    """The pair: the other side named, the engine's answer, and the agent that re-reads it.

    Three states, each saying what it is: **no other build named** (the chooser is the form
    in this panel - one box, which is the design's "type both ids" bar in the one spelling
    this route needs), **the pair's difference** (through `gui.drift`, whose summary is the
    engine's own three numbers), and **a refusal** (the engine's sentence, printed as data
    because it is the engine's own words and not a catalogue string).

    The whole diff is three panels - added, removed, changed - with the first
    `_DRIFT_FIRST` options of each inline and the rest folded into a `details`.  The option
    names are what the reader came for (`显示太少了`), and a category with no rows is
    simply absent: the summary line above carries the zero, so a head over an empty list
    would be the defect the old block was fixed for.
    """
    lang = view.lang
    body = [_vs_bar(view, here, other)]
    sections = ""
    if not (here and other):
        body.append(ui.hint(words.both(lang, "one.vs_none")))
    else:
        report = _drift(view, here, other)
        if report.get("error"):
            body.append(ui.hint(f'<span class="muted">{words.both(lang, "delta.cannot")}'
                                f"</span> {ui.esc(str(report['error']))}"))
        else:
            body.append(_summary_line(view, report))
            sections = _diff_sections(view, report)
            body.append(_raw_configs(view, report))
    body.append(ui.action_form(
        "drift", words.both(lang, "btn.run_drift"),
        fields=[("api", view.check.api), ("older", here), ("newer", other)],
        # Same rule as the list page's bar: a pair of one (or none) prints no command line,
        # because the engine's refusal for that case names two select boxes this page does
        # not draw.
        argv=(view.gui._argv_of("drift", {"older": here, "newer": other}, lang,
                                api=view.check.api) if (here and other) else ""),
        hint="analysis.drift_hint",
        blocked="" if (here and other) else "one.vs_none", lang=lang))
    return ui.panel("one.compare_title", "".join(body), lang=lang) + sections


def _vs_bar(view, here: str, other: str) -> str:
    """The form that names the other side: one box, and the question beside it as hidden fields.

    The box is named **`pick`** and not `vs`, and that is the one place where a page has to
    choose between the spelling a route documents and the spelling that works: `pick` is a
    `Filter` field, so the id arrives with no help from the wiring, while `vs` is page state
    the wiring has to put on the check (the module docstring's seam).  The box's own words
    still say "the other build", and the links this page writes spell both keys, so the two
    spellings never disagree about anything a reader can see.

    The route is this page, so the form carries every key the page reads as a hidden field -
    `sort` above all, because the neighbours this page offers are the neighbours *of that
    order*.  `auto` is on: this bar has one control, and committing it is what the reader
    typed the id to do.
    """
    lang = view.lang
    hidden = _carried(view.route, view.check)
    hidden.append(("lang", "" if lang == DEFAULT_LANG else lang))
    return ui.filters(
        ui.field(words.both(lang, "one.vs"),
                 ui.text_input("pick", other, placeholder="one.vs", label="one.vs",
                               lang=lang), width="w-xl"),
        f'<button class="btn primary sm">{words.both(lang, "btn.compare")}</button>',
        action=view.route, auto=True, hidden=hidden)


def _summary_line(view, report) -> str:
    """What the pair is and what the engine said about it: refs, kind, `+a −r ~c`.

    The two sides are named the way a reader names a build (`tree/branch · describe`, from
    the catalogue `gui.drift` was handed) rather than as two 24-character ids, and the kind
    is printed because the engine compares two *trees* happily: 616 new options across two
    trees is a real number that must not be read as one kernel moving.
    """
    lang = view.lang
    refs = " &rarr; ".join(f'<code>{ui.esc(str(report.get(key) or ""))}</code>'
                           for key in ("older_ref", "newer_ref"))
    kind = ""
    if report.get("same") is True:
        kind = words.both(lang, "drift.same_branch")
    elif report.get("same") is False:
        kind = words.both(lang, "drift.cross_tree")
    summary = report.get("summary") or {}
    badge = words.both(lang, "drift.badge", added=summary.get("added", 0),
                       removed=summary.get("removed", 0), changed=summary.get("changed", 0))
    if not report.get("drifted"):
        # The engine answered "nothing moved", which is an answer and not an empty diff:
        # it is printed with both refs, because `+0 −0 ~0` beside two ids is the fact that
        # these two builds hold the same options.
        nothing = view.t("drift.no_drift", older=ui.esc(str(report.get("older") or "")),
                         newer=ui.esc(str(report.get("newer") or "")))
        return (f'<p class="row tight">{refs}{kind}</p><p>{nothing}</p>')
    return f'<p class="row tight">{refs}{kind}<span class="delta">{badge}</span></p>'


def _raw_configs(view, report) -> str:
    """The two `.config` files themselves, as links - "open it and read it", cheapest form.

    The URL is already on the `Kbuild` the page read, so this costs nothing and it is the
    whole file rather than this page's reading of it: a diff this page folds at twenty-five
    rows a category is not the whole answer, and the file is.
    """
    out = []
    for key in ("older_url", "newer_url"):
        url = str(report.get(key) or "")
        if url:
            out.append(f'<p class="q">{words.both(view.lang, "word.config")} '
                       f'{ui.code(url, href=url, title=url)}</p>')
    return "".join(out)


def _diff_sections(view, report) -> str:
    """The config difference printed whole: one panel per category, value by value.

    A row is `option | older | newer` and the missing side is the design's dash and never an
    empty cell - "this option has no value here" is the whole content of that cell
    (`lib/drift.diff` returns `(key, value)` for an addition or a removal and
    `(key, older, newer)` for a change).  The count is in the panel's own sub-line and the
    options are `<code>`, which is what `accept.py`'s X2 counts on this route.
    """
    lang = view.lang
    out = []
    for order, word in enumerate(("drift.added", "drift.removed", "drift.changed")):
        entries = list(report.get(("added", "removed", "changed")[order]) or ())
        if not entries:
            continue
        cols = (ui.Col("col.option", kind="trunc",
                       draw=lambda row: f'<code>{ui.esc(row["option"])}</code>'),
                ui.Col("filter.older", draw=lambda row: _side(row, "older")),
                ui.Col("filter.newer", draw=lambda row: _side(row, "newer")))
        rows = [_diff_row(order, entry) for entry in entries[:_DRIFT_FIRST]]
        table = ui.table(cols, rows, cls="grid", lang=lang)
        rest = entries[_DRIFT_FIRST:]
        if rest:
            # One fold per category, named by the category's own catalogue key: the
            # reader who unfolded 新增 gets 新增 unfolded and 改动 where they left it.
            table += ui.more(words.both(lang, "drift.all_rows", n=len(entries)),
                             ui.table(cols, [_diff_row(order, entry) for entry in rest],
                                      cls="grid", lang=lang),
                             fold="more." + word)
        out.append(ui.panel(word, table,
                            sub=words.both(lang, "filter.cap_rows", n=len(entries)),
                            flush=True, lang=lang))
    return "".join(out)


def _diff_row(order: int, entry) -> dict:
    """One option of a diff as the three cells of its row, whichever shape it came in."""
    older = newer = ""
    if order == 0:                      # added: the newer build has it, the older has not
        newer = str(entry[1])
    elif order == 1:                    # removed: the older one had it
        older = str(entry[1])
    else:                              # changed: both sides
        older, newer = str(entry[1]), str(entry[2])
    return {"option": str(entry[0]), "older": older, "newer": newer}


def _side(row, key: str) -> str:
    """One side of a diff row: the value, or the dash for the side that has none."""
    value = str(row[key])
    return ui.esc(value) if value else ui.DASH


def _drift(view, older: str, newer: str) -> dict:
    """The config difference of one pair, through the engine's own reader.

    `Gui.drift` is the whole of it: it tokenises the two ids, hands `Drift` the builds this
    request has already read as a catalogue, and answers the three lists plus the two refs
    and the raw artifact URLs.  The catalogue is what keeps a GET from looking a build id up
    by scanning the API, so it is built from the same two readers `data.rows` used - both
    memoised for the request, so this costs no second HTTP read - and an id this page did
    not read is refused before the engine is asked at all.
    """
    check = view.check
    known, builds = view.gui._known_builds(check.api, check.limit)
    unread = [one for one in (older, newer) if one and one not in set(known)]
    if unread:
        return {"error": view.t("analysis.not_read", build=unread[0]), "older": older,
                "newer": newer}
    catalogue = Kbuilds(view.gui._client(view.gui.api_base(check)), items=builds)
    return view.gui.drift(older, newer, view.lang, check.api, catalogue=catalogue)


# -------------------------------------------------------------------- the ids
def _route_id(route: str) -> str:
    """The build id the route names, or `""` when it names none.

    The id is the path segment after `/analysis/`, percent-decoded and then held to the
    alphabet every other id in this console is held to (`forms._token`): an id reaches a
    command line and a URL, and a value that is not one is not a thing to print on a page
    either.  A query string on the route is cut, because a route is a path here and the
    questions live in the check.
    """
    path = str(route or "").split("?", 1)[0]
    if not path.startswith(_DETAIL):
        return ""
    return _token(urllib.parse.unquote(path[len(_DETAIL):]))


def _other_side(view, here: str) -> str:
    """The build this one is compared with, from whichever channel carried it.

    `?vs=` is this route's own spelling and the one `accept.py` builds by hand, and it
    arrives only if the wiring put it on the check.  `pick` is the fallback that always
    arrives, and both keys are written by this page's own doors - so the page reads both
    and takes the first that names a build other than this one.
    """
    for one in (getattr(view.check, "vs", ""), *_picked(view),
                (view.rows or {}).get("vs", "")):
        found = _token(one)
        if found and found != here:
            return found
    return ""


def _short(build: str) -> str:
    """A build id as these tables print it: sixteen characters and an ellipsis.

    `values._short` is the tree's one cut and its default is twelve; this page asks for
    sixteen because the list is read by kernel revision and twelve characters of a build id
    do not tell two of one tree apart.  The whole id is always in the `title=` beside it,
    so nothing is lost to the cut.
    """
    whole = str(build or "")
    cut = _cut(whole, 16)
    return cut + "\u2026" if len(whole) > len(cut) else cut


PAGES = {"/analysis": analysis, _DETAIL: detail}
