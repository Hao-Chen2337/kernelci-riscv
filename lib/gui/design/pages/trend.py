# SPDX-License-Identifier: LGPL-2.1-or-later
"""`/trend`: one test over the builds - is this getting better or worse.

This is `/analysis`'s bottom half given a page of its own, and the reason it earns one
is the **set of tests it draws**.  On `/analysis` the timeline and the chart are two
panels of a page about *one order of builds*, and both draw the catalogue's whole set
(`lib/tests.py:DEFAULT_TESTS`) because a panel inside a page has no room to ask.  A
reader who wants `` `boot` and `kselftest-kvm` only, over this window ''  has a question
that page cannot spell, and the operator asked for exactly that (「可以把三种测试就是
任意组合」).

So this page keeps the two panels and gives them the two things a page owns:

* **a filter bar of their own** - the same `Filter` axes `/analysis` reads and the same
  order control, so the window and the axis are chosen here rather than inherited from a
  page about rows.  It is `/analysis`'s own bar, folded row and all (`_main_fields` minus
  `delta` and the single-valued `test`, plus this page's `tests`), because a page whose
  whole subject is "these builds in this order" is asking `/analysis`'s question and the
  ledger half of it - `state`, `result`, `ran`, `verdict`, `origin`, `evidence`,
  `missing` - narrows the very rows both panels are drawn over;
* **`?tests=`** - which tests to draw, several at once, as chips (`ui.multi`).  Empty
  means the whole catalogue, which is what `/analysis` always draws, so the two pages
  agree until the reader says otherwise.

**Nothing is computed here.**  The panels, the rows and the axis are `/analysis`'s own
readers: `_timeline_panel`/`_chart_panel` are imported from it (they are `(view, …)`
pure functions over `rows["timelines"]`/`rows["series"]`, and `data.rows` builds both
for every route), the order control is `analysis._order_control`, and the filter bar is
`analysis._bar`/`_bar_buttons`/`_api_field`/`_choices`.  A second copy of any of them
would be a second answer to a question this tree answers once.

The one thing this page tells those readers that `/analysis` does not is `test_key`: a
test's name in the timeline is a link **on both pages**, but `/analysis`'s `?test=` is a
single-valued condition (one test's `ran`/`verdict`) while this page's axis is the set
it draws, so clicking a name here means "just this one" and writes `?tests=`.

What this page deliberately does **not** carry: `delta` (no `±` column and no config
comparison - that is `/analysis`'s table), `pick`/`older`/`newer` (no pair to compare),
and the pair's `drift` button.  A key a page draws no control for would be a filter bar
that quietly answers a narrower question than the URL it was handed.

`ran`/`verdict` are the one pair whose meaning shifts here, and they are worth having
anyway.  `Filter.accepts` reads them "over the records of the `test` in force", and this
page carries no single `test` - so the condition is read over the whole ledger and they
mean "has this build a measurement *at all*" (`ran=ever`), "has it none" (`ran=never`),
"did its newest one fail" (`verdict=fail`).

That makes them a **change of window and not only a narrowing of it**, and the reader
should expect it: the pool is filtered *before* `limit` takes the newest N of it, so the
window is a different set rather than a smaller one - the builds with records can be
older than the newest N, and the counts beside each test can go up as easily as down.
Measured on the local stack: 40 rows and `boot: 8` unfiltered, 27 rows and `boot: 26`
under `ran=ever`.  That is the same answer `/` gives for the same two conditions, which
is the point - the boxes are `/jobs`' and `/`'s own words, and there is nothing new to
learn about them here.

The clock is **not** one of this page's controls.  It was for a while - the pairs panel
below prints two stamps per regression and `Filter.tz` says which clock - but the
operator moved it to the top bar, where one control serves every station
(「就是能不能搞成那种就是通用的就是在头顶上」), so this bar carries the choice as a
hidden field instead of drawing a second box.
"""

from functools import partial

from ...forms import _names
from ...schema import CHART_MODES, LIMITS, MAX_LIMIT, MODE_CUMULATIVE, MODE_EACH
from .. import ui, words
from .analysis import (
    _FOLD,
    _api_field,
    _bar,
    _bars_panel,
    _chart_panel,
    _choices,
    _compares_panel,
    _fold_fields,
    _mode_of,
    _order_control,
    _timeline_panel,
)

# Which keys this page's bar draws.  Every *other* key the filter carries rides as a
# hidden field (`urls._carried` writes one for each, not only for the ones named here),
# which is what keeps a GET bar from replacing the whole query string: `sort` is the
# clearest case - it is not drawn here (the order control is a row of links,
# `_order_control`) and it *must* survive, because it is the axis both panels run along.
#
# `mode` is in the list and drawn as a segment (`_mode_field`), which is the one entry
# here that is not a window axis: it selects nothing and narrows nothing, and it is named
# anyway because `urls._carried` reads this tuple as "the keys a control of this bar's own
# speaks for".  A key the bar draws *and* hands over hidden is two values for one key, and
# of two values for one key the first one wins (`forms._first`) - the hidden one, since
# `ui.filters` writes those first - so the reader's click would submit nothing at all.
#
# `days` is in the folded row, not here (`_FOLD` is `/analysis`'s own list), and that is
# deliberate rather than an oversight: it is the one window this page shares with the row
# above, and a control drawn in both would be two boxes for one number - the same shape as
# the clock the top bar took away.  The folded row is a form of its own, so the two would
# not collide on the wire; they would collide in the reader's head.
#
# The clock is that story one step further, and this bar draws no control for it either:
# the top bar has the only one (`shell.tz_switch`) and the key rides hidden off
# `urls._carried`, which is what keeps the table below and the bar above from disagreeing
# about which clock they are in.
_TREND = ("api", "tree", "branch", "arch", "defconfig", "compiler", "limit", "mode")


def trend(view) -> str:
    """The body of `/trend`: the bar, the order, the timeline, the comparisons, the two pictures.

    The order is `/analysis`'s own - timeline above chart - because the two pictures are
    one answer read twice, and the sub-line under the timeline says so
    (`page.analysis.axes_note`).  Both panels are `/analysis`'s builders, unchanged but
    for the key a test's name links with.

    The bars panel (`每个构件的结果`) is the fourth reader and the last one here: it came
    off `/analysis` because it is one region per *test* and one line per *build of the
    window* - this page's two subjects and neither of that page's (「这个分析的这里的
    这部分是不是可以移动走」, and `analysis.analysis`'s docstring says the same from the
    other end).  It is drawn last because it is the most detailed reading of the window:
    the timeline gives a cell per build, the chart a point, and this one the record's own
    numbers.  The panel's own picker went with the move - see `analysis._bars_panel`.
    """
    rows = view.rows
    return "".join((
        _bar(view, _TREND, _trend_fields(view)),
        # `/analysis`'s own folded row, drawn by `/analysis`'s own builder: every box in
        # it is a condition both panels are narrowed by (the docstring says why), so this
        # page draws the row rather than a second, thinner one of its own.  The name the
        # row is remembered by is its own (`ui._fold`), so opening it here does not open
        # the row on `/analysis`.
        ui.more(words.both(view.lang, "btn.more"), _bar(view, _FOLD, _fold_fields(view)),
                fold="more.trend"),
        _order_control(view),
        _timeline_panel(view, rows.get("timelines") or (), test_key="tests"),
        _compares_panel(view, rows.get("timelines") or ()),
        _chart_panel(view, rows.get("series") or ()),
        _bars_panel(view, rows.get("bars") or ()),
    ))


def _trend_fields(view) -> str:
    """The bar: the axes a window is chosen with, and the set of tests to draw.

    `/analysis`'s `_main_fields` minus what this page has no use for (`delta`, and the
    single-valued `test` box) plus the one control it adds: **`tests` as a multi box**,
    which is the whole point of the page.  `_names` turns the comma-joined value the
    filter carries into the chips' list, exactly as the four axes above it do.

    `limit` is here for `/analysis`'s reason and not for symmetry: it is one of the two
    numbers every panel on this page is drawn in - the window in rows - and a page whose
    whole subject is "these builds in this order" may not leave the reader unable to say
    which builds those are.  The other one, `days`, is in the folded row below with the
    rest of the conditions that are rarely the answer (`_TREND` says why).
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
        # The one control this page exists for: which tests to draw a line per.  The
        # candidates are `lib/tests.py:TESTS` - the same tuple the filter accepts
        # (`forms._tests_many`), so the box cannot offer a name the page would refuse.
        ui.field(words.both(lang, "word.test"),
                 ui.multi("tests", _names(check.tests), rows.get("tests") or (),
                          placeholder="state.any", label="word.test", lang=lang),
                 width="w-lg"),
        _mode_field(view),
        ui.field(words.both(lang, "filter.rows"),
                 ui.number_input("limit", check.limit, min_=1, max_=MAX_LIMIT,
                                 stops=LIMITS),
                 width="w-sm"),
    ))


def _mode_field(view) -> str:
    """Which of the chart's two questions is being asked, as a segment.

    `schema.CHART_MODES` holds the two answers and their order, `models.Filter.mode` the
    value in force, and `data._points` the arithmetic - so this control decides nothing;
    what it owes the reader is the sentence, because the two curves are the same picture
    of the same window and the difference between them is invisible in the markup:

    * **the accumulated rate** (the default, `MODE_CUMULATIVE`) is the share of
      everything that ran *up to* a position that passed, so a stretch with no record
      carries the last value and the line stays flat across it;
    * **each build's own** (`MODE_EACH`) is that one build's own number, so a position
      with no record is a break - which is what a reader who wants to see `10 0 0` beside
      `8 2 0` is looking for (「切换一种模式就是改成能显示具体每一项的通过数值那种」).

    The label keys are spelled out here rather than built from the value, and for two
    reasons: `MODE_CUMULATIVE` is the empty string (`schema` says why), so
    `"chart.mode." + value` would ask the catalogue for `chart.mode.` on the default
    entry; and the worker's segment *does* build its key from the value
    (`worker._mode_field`), so a shared prefix would be one name for two vocabularies.

    The hint under it is the one the worker's own `mode` segment carries
    (`worker.mode_note.once` / `.resident`): a segment has no room to say what it does,
    and the two `title=` attributes a reader would hover are not a sentence they can
    read on a phone.
    """
    lang = view.lang
    labels = {MODE_CUMULATIVE: "chart.mode.cumulative", MODE_EACH: "chart.mode.each"}
    return ui.field(words.both(lang, "filter.mode"),
                    ui.seg("mode", [(one, words.both(lang, labels[one]))
                                    for one in CHART_MODES], _mode_of(view))
                    + ui.hint(words.both(lang, "page.trend.mode_note")), width="w-xl")
