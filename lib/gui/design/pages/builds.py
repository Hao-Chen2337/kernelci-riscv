# SPDX-License-Identifier: LGPL-2.1-or-later
"""`/`, the builds screen, and `/local/<build_id>`, one copy's drill-down.

The screen is one row per build id over three facts that are never derived from one
another - what the API says, what this disk holds, and what the ledger ran - and the
panels below are those facts in the order a reader checks them: the question that was
asked, the bar that changes it, the seven numbers behind it, the table, the ledger's own
numbers, the pull record, and where a locally made card comes from.

**Both spellings of the route are this module.**  The design board calls the screen
`/builds`; this console has always served it at `/`, and the navigation bar, the
acceptance gate's page list and every link in the operator's history spell that one.  So
`/builds` is an alias that reaches the same `builds()` (`pages/__init__.SCREENS`), and
**every link written here names `/`** (`_ROUTE`).  That is not tidiness: `_url` resolves a
route's query keys by *name* (`ROUTE_KEYS`), `/builds` has no entry there, and a link
written from the alias would therefore drop the reader's whole filter - dropping the cap
out of a chip's link is exactly how a number stops reproducing its own rows.

**A row is `data._builds`' dict and this module adds nothing to it.**  The three cells
that carry a judgement read the engine's own word for it: `checks` is `Build.present()`
per artifact, `here` is `Local.state`, `ran` is `Records.last` per test.  The page decides
none of them (`00-BRIEF.md` §3), and the two numbers it reads for itself - the union
behind the view presets and the total the pager is given - are `len()` of sets the same
readers handed over, measured by id (`_matched`).

**`api` has one slot for three facts, so two of them are read from the answer.**  A row's
`api` is `(state, result, node)` or `None`, and `None` covers an API that did not answer,
a build outside this answer's cap, and a card this machine made - which has no remote
counterpart *by construction* and never had one.  The cell reads the row's own `here` for
the third and this page's `Remote` for the first two (its `note`, and its `total` against
what it carries), in `_api_cell`'s own order; `answer` is the object `data.rows`
already read, so the second ask costs no HTTP (every reader under it is memoised for the
request).

**The numbers strip is the one gate-shaped piece of markup on the page.**  A chip is
`<span class="k">label</span><b class="n">number</b>` inside `<p class="numbers">`, and a
chip that links must link to a page whose table has exactly that many rows (`accept.py`
S6 follows every href and counts them).  That is why every chip's link carries its own
number as `limit` and drops every other key of this page's filter: these numbers count
this disk - the whole local table, the whole download tree, every act, the whole ledger,
every activity - and a link that inherited `?tree=riscv` from the page it was drawn on
would answer a narrower question than the number it printed.  The old strip measured that
failure in a smaller size: `with bytes 9` linking to a page of 8 rows, because
`6a986b26e41d7f97` was pulled, held artifacts and had no card.

**Nothing here writes a path, a query string or a date by hand.**  A link is
`view.url()` (so `?api=` is canonicalised and `?lang=` spelled in one place), a path is
`lib/layout`'s accessor, and a timestamp is the record's own string cut at its `T`.
"""

import os
import urllib.parse
from dataclasses import replace
from functools import partial

from .... import errors, layout
from .... import run as run_mod
from ....build import ARTIFACTS
from ....i18n import DEFAULT_LANG, LANGS, t
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
    RESULTS,
)
from ...values import _human
from .. import ui, words
from ..data import CARD_ARTIFACTS

# The two form ids.  `_PULL_FORM` is the bar's: every row's tick box names it in `form=`
# (a form cannot wrap a table without putting its own button in the middle of it) and the
# header box names it in `data-all-for=`.  `_ONE_FORM` is the id each row's own pull form
# carries - the guide's own name.  Repeating an id is harmless here because nothing looks
# a row's form up *by* id: `_JS` finds a form by its button and the `[data-status]` inside
# it, and each row's form is inside that row.
_PULL_FORM = "pull-now"
_ONE_FORM = "pull-one"

# The page's canonical route.  `/builds` is the design's spelling and an alias of `/`
# (`00-BRIEF.md` §11 item 2), and every link is written against `/` for the reason the
# module docstring gives: a route with no `ROUTE_KEYS` entry silently drops the filter.
_ROUTE = "/"

# The bar, split the way the board splits it: the six axes a reader changes every visit in
# the open row, the rest behind `more filters`.  Every key of `FILTER_ORDER` is in one of
# these two tuples - drawn or carried as a hidden field - because a GET form replaces the
# whole query string: a key in neither place is a condition the next `apply` silently
# drops, which is how "apply" comes to answer a different question than the one on screen.
_MAIN = ("api", "tree", "branch", "arch", "defconfig", "compiler")
_FOLD = ("state", "result", "origin", "evidence", "missing", "days", "limit", "text")

# `data._counts` produces the strip already translated, because it is data and not markup.
# A chip's label is a *word* the reader must be able to swap, so the label is turned back
# into the key that produced it - by value, not by position, so the strip survives a
# reordering in `data.py` - and a label no key owns is printed as the literal it is.
_COUNT_KEYS = ("counts.cards", "counts.here", "counts.bytes", "counts.acts",
               "counts.records", "counts.gap", "counts.activities")
_COUNT_KEY_OF = {t(one, key): key for key in _COUNT_KEYS for one in LANGS}

# `Local.state`'s five words, as the catalogue's own labels for exactly those values.  The
# card column's cells are three ticks, and *which* of the five states this copy is in is
# the fourth fact about it - "a card with nothing behind it" is one of five things, not
# one - so it rides in the cell's `title=` rather than in a column the design does not
# draw.
_HERE_KEYS = {
    "pulled": "evidence.label.pulled",
    "unrecorded": "evidence.label.unrecorded",
    "registered": "evidence.label.registered",
    "made-here": "evidence.label.made_here",
    "empty": "evidence.label.empty",
}


# ------------------------------------------------------------------- the screen
def builds(view) -> str:
    """The body of `/`: the question, the bar, the numbers, the table, the record.

    Two API answers are read and they are two different questions: `quoted` is this page's
    own answer (the one the `api says` column is about, whose `note` and `total` the cell
    needs) and `opened` is the same question with the `origin` axis open, which is what the
    three view presets are sizes *of* - a preset is a view of one set, and the union cannot
    be measured from an answer the card view already narrowed.
    """
    lang, check, rows = view.lang, view.check, view.rows
    held = view.gui.all_locals()
    quoted = view.gui.remote_rows(check, held, lang)
    # The same question with the `origin` axis open, and the check that states it: a preset
    # number is the size of a set, so both halves of that set have to be read with the axis
    # open - reading the API with it open and this disk with it narrowed is how the union
    # comes out equal to the card count.
    opened_check = replace(check, origin="any")
    opened = view.gui.remote_rows(opened_check, held, lang)
    table, records = view.gui._state()
    found = list(rows.get("builds") or ())
    return "".join((
        _asked(view, quoted),
        _bar(view, _MAIN, _main_fields(view)),
        ui.more(words.both(lang, "btn.more"), _bar(view, _FOLD, _fold_fields(view))),
        ui.cpanel(_strip(view, quoted),
                  sub=words.both(lang, "page.builds.chips_title"), lang=lang),
        _builds_panel(view, found, held, quoted, table, opened, opened_check),
        _ledger_panel(view, rows, records),
        _pulls_panel(view),
        _origin_panel(view),
    ))


def _asked(view, answer) -> str:
    """One line saying which API was asked, and what came back.

    The query is printed as `remote_query()` spells it - the address really read, then the
    wire's own keys - because the address bar's short name (`api=production`) hides which
    stack the numbers below came from (`02-filters.md` §A5).  "The API did not answer" is a
    different sentence and gets its own; it is `t()`-only because the catalogue's text
    carries `&mdash;`, which `both()` refuses (the swap writes text and would print the
    entity as its characters).
    """
    lead = words.both(view.lang, "remote.asked")
    if answer is not None and answer.note:
        return ui.hint(lead + ": " + t(view.lang, "remote.no_answer_line",
                                       note=ui.esc(answer.note)))
    showing = words.both(view.lang, "remote.showing", shown=len(answer), kept=answer.kept)
    cap = words.both(view.lang, "remote.rows_cap", n=answer.limit)
    return ui.hint(lead + ": " + ui.code(view.gui.remote_query(view.check, view.lang))
                   + " &mdash; " + showing + " " + cap)


# ------------------------------------------------------------------ the filter
def _bar(view, drawn, fields_html: str) -> str:
    """One of the page's two GET bars: what it draws, and the rest of the question.

    The board gives a page whose axes do not fit one row a `details.more` with a bar of its
    own (its `/builds` draws one), and a GET bar replaces the whole query string - so each
    bar carries every key it does not draw as a hidden field.  Without them, `apply` on the
    folded row answers a question with no tree in it, and nothing on the page says so.
    """
    carried = dict(view.check.to_query())
    hidden = [(key, carried.get(key, "")) for key in FILTER_ORDER if key not in drawn]
    hidden.append(("lang", "" if view.lang == DEFAULT_LANG else view.lang))
    return ui.filters(fields_html, _bar_buttons(view), action=_ROUTE, auto=True,
                      hidden=hidden)


def _bar_buttons(view) -> str:
    """`start over` and `apply`: the pair every bar ends with.

    The button is a real submit and not the board's `type="button"` (which cannot submit
    anything - one of the defects `00-BRIEF.md` §9 names), because `data-auto` is an
    enhancement and not the only way to change the question.
    """
    lang = view.lang
    return (ui.link_btn(words.both(lang, "btn.reset"), view.url(_ROUTE, *FILTER_ORDER),
                        lang=lang)
            + f'<button class="btn primary sm">{words.both(lang, "btn.apply")}</button>')


def _choices(values, current: str = "", labels=None, any_key: str = "state.any",
             lang: str = DEFAULT_LANG) -> list:
    """One select box's options: the value, and the catalogue key of its word.

    A value is what the console compares and a word is what a reader reads.  `any_key` is
    the word for "no condition at all" and is passed only for the axes where the empty
    value means that: `origin` and `evidence` carry their own `any`, and a box offering a
    second, empty one would offer a value `one_of()` refuses - which then answers the
    axis's *default* instead of the reader's choice.

    The value in force is appended when the list does not carry it: a select with nothing
    selected *shows its first option*, so the next `apply` would send "any" where the URL
    said something else.
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

    The API box is a text input with the base in force as its placeholder rather than the
    board's select: the filter accepts a name *or* a spelled-out `http(s)` address and `ui`
    has no datalist, so the box that can express both - and that says which base is being
    read when it is empty - is the honest one.
    """
    lang, check, rows = view.lang, view.check, view.rows
    label = partial(ui.word, lang=lang)
    return "".join((
        ui.field(words.both(lang, "filter.api"),
                 ui.text_input("api", check.api,
                               placeholder=check.api_base or "filter.api",
                               label="filter.api", lang=lang),
                 width="w-md"),
        ui.field(words.both(lang, "word.tree"),
                 ui.multi("tree", _names(check.tree), rows.get("trees") or (),
                          placeholder="state.any", label="word.tree", lang=lang),
                 width="w-md"),
        ui.field(words.both(lang, "word.branch"),
                 ui.select("branch",
                           _choices(rows.get("branches") or (), check.branch, lang=lang),
                           check.branch, labeler=label),
                 width="w-md"),
        ui.field(words.both(lang, "word.arch"),
                 ui.multi("arch", _names(check.arch), rows.get("arches") or (),
                          placeholder="state.any", label="word.arch", lang=lang),
                 width="w-md"),
        ui.field(words.both(lang, "word.defconfig"),
                 ui.multi("defconfig", _names(check.defconfig),
                          rows.get("defconfigs") or (), placeholder="state.any",
                          label="word.defconfig", lang=lang),
                 width="w-lg"),
        ui.field(words.both(lang, "word.compiler"),
                 ui.multi("compiler", _names(check.compiler),
                          rows.get("compilers") or (), placeholder="state.any",
                          label="word.compiler", lang=lang),
                 width="w-md"),
    ))


def _fold_fields(view) -> str:
    """The rest of the question, behind the fold - the board's own second row.

    `state` and `result` are the API's two words about a node this page reads, `origin` and
    `evidence` are the two axes that decide which side of the union a row is on, `missing`
    names an artifact a card still lacks, and `days`/`limit` are the window and the cap.
    Both numbers stay typeable `<input>`s with a value rail and not a row of preset
    buttons: a fixed row cannot say "14 days", and `limit` is the one control here that
    costs bytes.
    """
    lang, check = view.lang, view.check
    label = partial(ui.word, lang=lang)
    return "".join((
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
                           _choices(ORIGINS, check.origin, _LABELS["origin"],
                                    any_key=None, lang=lang),
                           check.origin, labeler=label),
                 width="w-sm"),
        ui.field(words.both(lang, "filter.evidence"),
                 ui.select("evidence",
                           _choices(EVIDENCE, check.evidence, _LABELS["evidence"],
                                    any_key=None, lang=lang),
                           check.evidence, labeler=label),
                 width="w-md"),
        ui.field(words.both(lang, "filter.missing"),
                 ui.select("missing",
                           _choices(ARTIFACTS, ",".join(check.missing), lang=lang),
                           ",".join(check.missing), labeler=label),
                 width="w-md"),
        ui.field(words.both(lang, "filter.days"),
                 ui.number_input("days", check.days, max_=MAX_DAYS, stops=DAY_CHOICES),
                 width="w-sm"),
        ui.field(words.both(lang, "filter.rows"),
                 ui.number_input("limit", check.limit, min_=1, max_=MAX_LIMIT,
                                 stops=LIMITS),
                 width="w-sm"),
        ui.field(words.both(lang, "filter.text"),
                 ui.text_input("text", check.text, placeholder="id, describe, path",
                               label="filter.text", lang=lang),
                 width="w-lg"),
    ))


# ------------------------------------------------------------- the numbers strip
def _strip(view, answer) -> str:
    """The seven numbers behind this page, each one a link to the rows it counts.

    The order is `data._counts`' own (the board's), the label is swapped back to the key
    that produced it so the strip changes language with the page, and the source sentence
    rides in the `title=` - which is where the old counts line's three absolute paths went.
    A count no single page draws gets no href and is a `<span>`.
    """
    lang = view.lang
    items = []
    for label, value, source in view.rows.get("counts") or ():
        key = _COUNT_KEY_OF.get(label, "")
        number, href = _chip(view, key, value)
        items.append((words.both(lang, key) if key else ui.esc(label), number, source,
                      href))
    return ui.chips(items, lang=lang)


def _chip(view, key: str, value) -> tuple:
    """One chip's number, and the link that shows exactly those rows.

    Every link carries the number as `limit` and drops the rest of this page's filter, for
    the reason the module docstring gives: these numbers are facts about *this disk*, so a
    link that inherited a narrowing condition would print fewer rows than the number it was
    drawn with.

    Two are deliberately not pages of rows of their own.  `pull acts` points at the panel
    below on this page (`#acts`, and the panel carries that id - the board's 21
    `href="#acts"` pointed at an anchor nothing had), and a count with no `href` at all is
    one no page draws.
    """
    number = _countable(value)
    if key == "counts.cards":
        # `origin=card` is the one view `build_rows` lets past the row cap, so the card
        # table prints all of its rows whatever `limit` says: the number and the target
        # agree by construction once the link asks for exactly the cards.
        return number, view.url(_ROUTE, *FILTER_ORDER, origin="card", limit=number)
    if key == "counts.here":
        return number, view.url(_ROUTE, *FILTER_ORDER, origin="local", limit=number)
    if key == "counts.bytes":
        # `origin=any` is not decoration: "an artifact is on disk here" is true of a
        # directory no card names, so a link that inherited `origin=card` from the page it
        # was drawn on prints fewer rows than the number says.
        return number, view.url(_ROUTE, *FILTER_ORDER, origin="any", evidence="bytes",
                                limit=number)
    if key == "counts.acts":
        return number, "#acts"
    if key == "counts.records":
        return number, view.url("/jobs", *FILTER_ORDER, limit=number)
    if key == "counts.gap":
        # **The window, and not `ran=never`.**  The number is `re.todo()`'s - the pairs with
        # no record - and no `/jobs` filter selects exactly those: `job_rows` applies `ran`
        # at the *build* level before it looks at the test, so a build with a `boot` record
        # loses both of its kselftest gaps and `ran=never` answers 93 where `re.todo()`
        # answers 99.  A chip whose link answered a set other than the one its number
        # counted would be this page's own version of the defect S6 exists for, so the link
        # is the window of that size - the shipped page's own link - and the mismatch is
        # reported rather than papered over with a number invented to match.
        return number, view.url("/jobs", *FILTER_ORDER, limit=number)
    if key == "counts.activities":
        # `/runs` folds the bookkeeping kinds by default and this number counts every
        # activity on disk, so naming every kind on disk is what unfolds the table the
        # number was read from (`04-actions.md` §P8a).  With nothing on disk there is no
        # kind to name and no link that could reproduce a zero of its own.
        kinds = _kinds_of(view.rows)
        return number, (view.url("/runs", *FILTER_ORDER, kind=kinds) if kinds else "")
    return number, ""


def _countable(value) -> str:
    """A count as a chip prints it, held to the cap any link to rows of it can carry.

    `00-BRIEF.md` §10 item 10's rule: a chip whose number is larger than `MAX_LIMIT` would
    link to a page that clamps the cap and prints fewer rows than the number says, so the
    printed number *is* the clamped one and the true count stays in the chip's `title=`.  A
    value that is not a number at all is printed as the value it is.
    """
    try:
        return str(max(0, min(int(str(value).strip()), MAX_LIMIT)))
    except ValueError:
        return ui.esc(value)


def _kinds_of(rows) -> str:
    """Every kind of activity on disk, as one `kind=` value: what unfolds `/runs`."""
    return ",".join(sorted({str(one["kind"]) for one in rows.get("runs") or ()}))


# -------------------------------------------------------------------- the table
def _builds_panel(view, found, held: dict, answer, table, opened, opened_check) -> str:
    """The table, its pager, the three view presets, and the one command over its ticks.

    The head carries what the board's head carries: the row count as the sub-line (a
    number, computed - the board printed a literal 7 over its 24-row table and relied on
    its own script to correct it), the three presets as the tools, and the bar that pulls
    every ticked row.  The tick boxes are *outside* that bar's form (`form="pull-now"`),
    which is the only way a table can feed a form drawn in a head, and the select-all box
    sits in the tick column's header, where the board draws it.
    """
    lang = view.lang
    return ui.panel(
        "page.builds.title",
        ui.table(_cols(view, found, held, answer), found,
                 empty=_empty(view, answer, held), lang=lang)
        + _pager(view, found, answer),
        sub=words.both(lang, "page.builds.rows_window", n=len(found)),
        tools=_presets(view, table, opened, opened_check) + _pull_bar(view), flush=True,
        lang=lang)


def _cols(view, found, held: dict, answer) -> tuple:
    """The board's nine columns, in its own order, and the two keys the script reads.

    The tick column's header is `ui.checkbox(all_for=…)`, rendered `hidden` until the
    shipped script unhides it: with the script off a box that ticks nothing would be a
    lie, and the rows' own boxes (which work) are there to be ticked by hand.

    No column carries a `key=`.  The board marks five of its headers `sortable`, but this
    page reads no `sort` - the order is `created`, decided by the engine - and a header
    that looked clickable and answered nothing is the "功能页不太对" this round exists to
    remove.
    """
    lang = view.lang
    return (
        ui.Col(ui.checkbox("all", words.both(lang, "tick.all", n=_boxed(found, held)),
                           all_for=_PULL_FORM, lang=lang), kind="c",
               draw=lambda one: _tick_cell(view, one, held)),
        ui.Col("word.build_id", kind="id",
               draw=lambda one: _build_cell(view, one["build_id"])),
        ui.Col("word.tree_branch", draw=_tree_cell),
        ui.Col("word.created", kind="n", draw=lambda one: _stamp(one["created"])),
        ui.Col("col.card", kind="c", width="104px",
               draw=lambda one: _card_cell(one, lang)),
        ui.Col("col.bytes", kind="n", draw=_bytes_cell),
        ui.Col("col.act", kind="n", draw=lambda one: _acts_cell(one, lang)),
        ui.Col("col.api_says", draw=lambda one: _api_cell(one, answer, lang)),
        ui.Col("filter.ran", draw=lambda one: _ran_cell(one, lang)),
    )


def _boxed(found, held: dict) -> int:
    """How many boxes this table drew - the number the select-all's own label prints.

    `tick.all`'s contract is exact: the box ticks the boxes the page drew, and no more.  A
    row whose copy has no card is *not* tickable (`_tick_cell` says why in the cell), so the
    count is of the rows that got a box and not of the rows on screen - on this deployment
    the union view draws one card-less row, and a label reading "tick the 50" over 49 boxes
    would be the same overstatement the board's own literal `tick the 7` was.
    """
    return sum(1 for one in found
               if (held.get(str(one["build_id"])) is not None
                   and held[str(one["build_id"])].card is not None))


def _pager(view, found, answer) -> str:
    """The rows past the cap, reachable - and nothing when everything fits.

    `?offset=` was a key three readers understood and no link ever wrote, so row 51 of this
    table could only be seen by widening `limit`.  `ui.pager` is that link, and its page
    size is `limit` itself - which is what keeps a chip's `?limit=N` landing on a table of
    exactly N rows (`accept.py` S6 counts them).

    `total` is the size of the set this table is about, measured by id (`_matched`): the
    number of rows `build_rows` merges *before* the cap, which is the only total a pager can
    be given that does not hide rows behind a page it never draws.  The card view is the
    one view `build_rows` does not cap, so its page size is `MAX_LIMIT` and a card table
    smaller than that draws no pager at all - the honest shape, because a pager over an
    uncapped table would offer a page 2 that draws the same rows again.
    """
    check = view.check
    size = MAX_LIMIT if check.origin == "card" else max(1, check.limit)
    total = len(found) if check.origin == "card" else _matched(view, answer)
    return ui.pager(view, total, size, check.offset)


def _matched(view, answer, check=None) -> int:
    """How many rows one question's table is about: the API's ids union this disk's.

    `BuildsMixin.build_rows` merges exactly these two sets and caps the result, so this is
    the number the cap hides rows from.  It is measured **by id** and not by adding two
    sizes: the sets overlap by every build the API answered and this machine holds, so a
    sum would print a union larger than the page could ever show.

    `check` is the question both halves are read with, and it defaults to this page's own -
    which is what the *pager* wants (it pages the table drawn above it).  A view preset
    passes the check with its axis open instead, because a preset's number is a size and
    both halves of that set have to be measured the same way.
    """
    named = {str(one.build_id) for one in answer}
    kept = {str(one.build_id)
            for one in view.gui.filtered_locals(view.check if check is None else check)}
    return len(named | kept)


def _presets(view, table, opened, opened_check) -> str:
    """The three sets this list can be, as one pressable number each.

    `origin` decides *which* builds the rows are about, and as a select among fifteen
    controls the place that holds the reader's cards had no name on the page.  Pressing a
    number keeps every other condition, so switching the view never changes the filter.

    The three numbers are the sets themselves, and the middle one is the union **measured
    by id**: the cards are the local table's own size, the window is what this question's
    answer carries, and the union is the two of them counted by id (`_matched`) - which is
    why it is read from the answer with the `origin` axis open.  A union measured from an
    answer the card view had already narrowed is not a union, it is the same number twice:
    the old page printed `cards 53` beside `both 53` while 54 builds were on the page.

    The window's number is the size of the API's *answer*, and pressing it draws that answer
    **and the carded copies it did not carry**: `reads.filtered_locals` hands `accepts` the
    local card where its parameter is named `kbuild`, so `origin=remote` is true of anything
    carded on this disk and the third view is wider than its label.  That is the engine's
    own reading of the axis, measured on this deployment (53 rows drawn, 3 of them carrying
    an API answer) and identical on the shipped page; this page does not restate the axis,
    and it prints the number the label promises rather than a count that would make the
    label wrong instead.
    """
    lang = view.lang
    parts = []
    for value, key, number in (("card", "view.cards", len(table)),
                               ("any", "view.union", _matched(view, opened, opened_check)),
                               ("remote", "view.window", len(opened))):
        current = ' aria-current="true"' if view.check.origin == value else ""
        href = view.url(_ROUTE, origin=value)
        parts.append(f'<a href="{ui.esc(href)}"{current}>'
                     f'{words.both(lang, key, n=number)}</a>')
    return f'<span class="seg">{"".join(parts)}</span>'


def _pull_bar(view) -> str:
    """The one command this table's ticks feed: every ticked row, in one POST.

    No visible argv line: the ids do not exist until a box is ticked, and the bar's own
    sentence (`pull.pull_hint`, in the form's `title=`) is what it owes the reader - the
    command is `<each ticked build>` with every other condition known, which
    `_argv_of_ticked` is the reader for and the guide asks only of the one-shot bars.
    """
    return ui.action_form("pull", words.both(view.lang, "btn.pull_selected"),
                          fields=[("api", view.check.api)], form_id=_PULL_FORM,
                          hint="pull.pull_hint", lang=view.lang)


def _empty(view, answer, held: dict) -> str:
    """Why the table is empty - it can be empty for three different reasons.

    "The API did not answer", "this machine holds nothing", and "your filter hid what it
    holds" are three facts, and one table can be empty for any of them.  The filter case
    carries its number and the link that empties the filter: how much it hid is what makes
    it visible that a filter is in force.  These sentences carry `<b>` and `&mdash;`, so
    they are rendered in this response's language - the swap writes text and would print
    the tags.
    """
    lang = view.lang
    if answer is not None and answer.note and not len(answer):
        return t(lang, "empty.remote_no_answer", note=ui.esc(answer.note))
    if held:
        link = view.link(_ROUTE, words.both(lang, "link.clear_filter"), *FILTER_ORDER)
        return t(lang, "empty.filter_hides", n=len(held), link=link)
    return t(lang, "empty.nothing_local", downloads=ui.esc(layout.downloads()))


# ------------------------------------------------------------------- the cells
def _tick_cell(view, one, held: dict) -> str:
    """This row's box, or the reason this row cannot be ticked at all.

    `table.py pull --build` reads the local table, so a row without a card is not tickable
    and says why: the box that used to be drawn there fed a command that refuses with
    `no build '…' in builds.json`.  Whether the copy has a card is a fact this page already
    holds (`all_locals()`, the same dict `data.rows` read) and not a second question asked
    of the disk.

    The row's own `pull` is a form of its own, so pulling one card does not mean ticking a
    box, finding the bar above and pressing a button that is also holding somebody else's
    ticks.  Its command line is the form's `title=` rather than a printed line: fifty of
    those under a column of ticks is a wall, and the bar above already prints the shape.
    """
    lang = view.lang
    build_id = str(one["build_id"])
    copy = held.get(build_id)
    if copy is None or copy.card is None:
        return (f'<span class="none" {words.attr(lang, "title", "pull.no_card_title")}>'
                f'{words.both(lang, "pull.not_tickable")}</span>')
    return (ui.checkbox("selected", "", value=build_id, form=_PULL_FORM, lang=lang)
            + ui.action_form("pull", words.both(lang, "pull.one"),
                             fields=[("selected", build_id), ("api", view.check.api)],
                             hint=t(lang, "pull.one_title", build=build_id),
                             form_id=_ONE_FORM, kind="sm", lang=lang))


def _build_cell(view, build_id) -> str:
    """A build id, linked to the page that shows that build alone.

    `/local/<build_id>` is this console's detail route for one build (`00-BRIEF.md` §5
    keeps it reachable) and it is the page that reads the same API key, so the link carries
    `api=` and nothing else: the detail page reads no window and no tree, and a link that
    carried them would look like a condition it honours.
    """
    href = view.url("/local/" + urllib.parse.quote(str(build_id)))
    return ui.code(build_id, href=href)


def _tree_cell(one) -> str:
    """The source tree and the branch, or the dash: a copy nobody named has neither."""
    tree, branch = str(one.get("tree") or ""), str(one.get("branch") or "")
    if not tree and not branch:
        return ui.DASH
    return (f'<span class="tree">{ui.esc(tree)}</span>'
            f' <span class="muted">/</span> '
            f'<span class="br">{ui.esc(branch)}</span>')


def _stamp(value, seconds: bool = False) -> str:
    """A record's timestamp as the board prints it: the day, then the clock, quiet.

    The two halves are the *value's* own characters and the `T` between them is the only
    thing dropped, which keeps a table of stamps readable without a date library and
    without a second spelling of a timestamp this tree already stores as text.  The
    precision is the board's own and differs by table: a build's `created` is printed to
    the minute (`2026-09-20 01:05`, the same sixteen characters the old cell cut), while a
    pull act's stamp keeps its seconds and its `Z` (`09:20:48Z`) because that is what
    tells two attempts of one build apart.
    """
    text = str(value or "")
    if not text:
        return ui.DASH
    day, _, clock = text.partition("T")
    if not clock:
        return f'<span class="nowrap">{ui.esc(day)}</span>'
    return (f'<span class="nowrap">{ui.esc(day)} '
            f'<span class="muted">{ui.esc(clock if seconds else clock[:5])}</span></span>')


def _card_cell(one, lang: str) -> str:
    """The three artifacts of a card, each ticked from `Build.present()` or explained.

    **This column exists because a card with nothing behind it used to look like a whole
    build.**  The tick is an `os.path.isfile` per artifact (`data._builds.checks`), never
    the card's own URLs: a card that declares three artifacts and holds none is the row
    this column is here to expose, and reading the card would tick all three for a copy
    with no bytes at all.  A missing artifact keeps its name in the `title=` and says what
    missing means; the group's own `title=` is `Local.state`, the engine's word for what
    this machine knows about the copy - three ticks cannot tell a copy nobody pulled from
    one that was pulled and left unrecorded.
    """
    present = words.attr(lang, "title", "page.builds.present")
    absent = words.attr(lang, "title", "state.not_here")
    checks = dict(one.get("checks") or {})
    parts = []
    for name in CARD_ARTIFACTS:
        glyph = (f'<span class="tick" {present}>&#10003;</span>' if checks.get(name)
                 else f'<span class="cross" {absent}>&#10007;</span>')
        parts.append(f'<span title="{ui.esc(name)}">{glyph}</span>')
    here = str(one.get("here") or "")
    return (f'<span class="cell-actions" '
            f'{words.attr(lang, "title", _HERE_KEYS.get(here, "") or "state.unknown")}>'
            f'{"".join(parts)}</span>')


def _bytes_cell(one) -> str:
    """What is on disk here, as a size - `Local.size()` and never what a record claims.

    A copy with nothing on disk has zero bytes and prints the dash: the dash and the zero
    are the same fact.  `MiB` is the column's unit and not a word either language has an
    opinion about.
    """
    size = one.get("bytes_mib")
    return ui.DASH if size is None else f'{ui.esc(size)} MiB'


def _acts_cell(one, lang: str) -> str:
    """The pull record, short: how many acts, and the link into the panel that holds them.

    Where the acts came from and when they happened are the link's `title=`: the panel
    below prints both for every act, and a cell that repeated them would be a second copy
    of one answer.  No acts is a dash and not a zero - nothing was recorded, which is a
    different statement.
    """
    count = int(one.get("acts") or 0)
    if not count:
        return ui.DASH
    said = " ".join(str(one.get(name) or "") for name in ("acts_host", "acts_when")).strip()
    title = f' title="{ui.esc(said)}"' if said else ""
    return (f'<a href="#acts"{title}>'
            f'{ui.pill(count, tone_override="plain", lang=lang)}</a>')


def _api_cell(one, answer, lang: str) -> str:
    """`api says`: the API's own answer for this row, or which silence this is.

    An answer that arrived is the node's `state`, its `result` and the short node id -
    three values, none of them translated (`pass`, `done` and a hex id are the API's
    vocabulary).

    **When the row carries no remote fact, three different facts look alike**, and this
    cell tells them apart in `_api_cell`'s own order:

    * the API did not answer - this page has an answer object and it carries a `note`, so
      nothing is known about the remote side of *any* row;
    * there is no remote counterpart **by construction** - this machine made the card
      (`Local.state` is `made-here`), so no query ever had it to return, and naming a cap
      here would name a window that hid what was never asked for;
    * the build is outside this answer's cap - the API's own total is larger than what the
      answer carries, so the window is printed with its number and the sentence that
      explains it is the tooltip.

    Everything else is the fourth case: the API answered and this id was not in the answer,
    which is a fact about *that answer* and not about the API.
    """
    said = one.get("api")
    if said is not None:
        state, result, node = said
        head = ui.pill(state, lang=lang)
        if result:
            head += f' <span class="muted" style="font-size:11px">{ui.esc(result)}</span>'
        if node:
            head += f'<br><span class="id">{ui.esc(node)}</span>'
        return head
    if answer is not None and answer.note:
        return words.both(lang, "state.no_answer_remote")
    if str(one.get("here") or "") == "made-here":
        # The words are the same ones the fallback below prints, and the `title=` is what
        # says *why*: a card this machine made has no remote counterpart by construction,
        # while a copy the API's answer simply did not carry has none by observation.  Two
        # facts, one sentence - the difference is the tooltip, because a reader who made
        # the card needs to know that no query was ever going to return it.
        return (f'<span {words.attr(lang, "title", "state.made_here")}>'
                f'{words.both(lang, "state.no_remote_counterpart")}</span>')
    if answer is not None and answer.total is not None and answer.total > len(answer):
        why = words.attr(lang, "title", "state.outside_window_title",
                         total=answer.total, limit=answer.limit)
        return (f'<span {why}>'
                f'{words.both(lang, "state.outside_window", limit=answer.limit)}</span>')
    return words.both(lang, "state.no_remote_counterpart")


def _ran_cell(one, lang: str) -> str:
    """The ledger's verdicts for this build, one pill per test, or the dash.

    The page computes no verdict: `ran` is `Records.last(test, build_id)` per test, and a
    pair with no record is a dash rather than a pill - which is exactly what the gap
    counts.  A row with no card still gets its verdicts, because the ledger is keyed by
    build id and does not care what the table says.
    """
    parts = [ui.pill(verdict, label=f"{test} {verdict}", lang=lang)
             for test, verdict in one.get("ran") or () if verdict]
    return f'<span class="cell-actions">{"".join(parts)}</span>' if parts else ui.DASH


# --------------------------------------------------------------- the two panels
def _ledger_panel(view, rows, records) -> str:
    """The ledger's own four numbers, with the code that produced each in its title.

    `Records.tally()` and `re.todo()` are the engine's answers and this page counts
    nothing; the regressions come from `rows["timelines"]`, the key `data.py` already built
    from `re.transitions()`, so this number and the one on `/analysis` are one reading.
    None of the four is a link: no page draws "the verdicts" or "the regressions" as rows,
    and a chip that linked somewhere with a different row count would be the one number
    here a reader could not check.
    """
    lang = view.lang
    ledger = list(rows.get("ledger") or ())
    tally = ", ".join(f"{verdict}: {many}"
                      for verdict, many in sorted(records.tally().items())) or "-"
    gap = len(view.gui.todo(view.check))
    regressions = ", ".join(f'{one["test"]}: {one["regressions"]}'
                            for one in rows.get("timelines") or ()) or "-"
    items = (
        (words.both(lang, "label.records_in_ledger"), str(len(ledger)), layout.results(),
         ""),
        (words.both(lang, "label.verdicts"), tally, "Records.tally()", ""),
        (words.both(lang, "counts.gap"), str(gap),
         t(lang, "label.gap") + " - re.todo()", ""),
        (words.both(lang, "label.regressions"), regressions, "re.transitions()", ""),
    )
    return ui.panel("page.builds.ledger_title", ui.chips(items, lang=lang), lang=lang)


def _pulls_panel(view) -> str:
    """What has been pulled: one row per act, newest first.

    Uncapped, and that is a decision with a measurement behind it: this table is where a
    build that is on disk with **no card** is visible at all.  Such a copy is not in the
    local table, so the card view - the page's default - draws no build row for it, and
    `accept.py`'s S7, which exists for exactly that copy, finds it here by its own id.
    Capping this table would hide it again, which is the bug and not the fix.

    A row's id is the link into that build's own page, and the short form is what a
    seven-column table can hold - the whole id is the link's `title=`.
    """
    lang = view.lang
    pulls = list(view.rows.get("pulls") or ())
    cols = (
        ui.Col("col.when", kind="n",
               draw=lambda one: _stamp(one["when"], seconds=True)),
        ui.Col("word.build_id", kind="id", draw=lambda one: _pull_id(view, one)),
        ui.Col("col.artifacts", kind="n", draw=lambda one: ui.esc(one["artifacts"])),
        ui.Col("col.bytes", kind="n", draw=_pull_bytes),
        ui.Col("col.transferred", kind="n", draw=lambda one: ui.esc(one["transferred"])),
        ui.Col("col.hosts", draw=lambda one: ui.code(one["hosts"]) if one["hosts"]
               else ui.DASH),
        ui.Col("col.error", kind="wrapc", draw=lambda one: _error_cell(one, lang)),
    )
    empty = t(lang, "empty.nothing_pulled",
              provenance=ui.esc(os.path.basename(layout.provenance("x"))),
              downloads=ui.esc(layout.downloads()))
    # The id the strip's `pull acts` chip points at.  `ui.panel` writes no id of its own,
    # and a chip whose `href="#acts"` names nothing is the board's own defect (21 of its
    # links did exactly that): the wrapper is what makes the chip a link to something a
    # reader can reach.
    return ('<div id="acts">'
            + ui.panel("page.builds.acts_title",
                       ui.table(cols, pulls, empty=empty, lang=lang),
                       sub=words.both(lang, "page.builds.acts_sub"),
                       collapsible=True, open_=False, flush=True, lang=lang)
            + "</div>")


def _pull_id(view, one) -> str:
    """A pull act's build id, short, linked to that build's own page."""
    build_id = str(one["build_id"])
    href = view.url("/local/" + urllib.parse.quote(build_id))
    return ui.code(f"{build_id[:16]}&hellip;", href=href, title=build_id)


def _pull_bytes(one) -> str:
    """An act's own byte count and its human spelling, side by side as the board draws it."""
    return (f'{ui.esc(one["bytes_raw"])} '
            f'<span class="muted">({ui.esc(one["mib"])})</span>')


def _error_cell(one, lang: str) -> str:
    """What went wrong in that attempt, as the design's `bad` pill, or the dash."""
    if not one.get("error"):
        return ui.DASH
    return ui.pill(str(one["error"]), tone_override="bad", lang=lang)


def _origin_panel(view) -> str:
    """Where a build with no remote counterpart comes from, and the two commands for it.

    A card this machine made is the one row the API can never answer for, and the way such
    a card comes to exist is a local artifact published as a build - which is why both
    commands are about the disk and not about the query, and why they are folded away.
    `index` is drawn **once** on this page: the board draws that command twice (once in the
    table's head, once here), and two forms for one command are two answer lines for one
    press.

    Both carry the argv they will run, and both are refused where the filter names several
    trees: `--tree` is single-valued in the entry point either button starts, so the button
    says which case this is rather than starting a command that would refuse it.
    """
    lang, check = view.lang, view.check
    tree = check.tree or "riscv"
    index_fields = [("api", check.api), ("tree", check.tree), ("days", str(check.days)),
                    ("limit", str(check.limit))]
    index_argv = {"tree": check.tree, "days": str(check.days), "limit": str(check.limit)}
    image = layout.serve("Image")
    state = (t(lang, "local.image_state", path=ui.code(image)) if os.path.isfile(image)
             else t(lang, "local.image_state_missing", path=ui.code(image)))
    return ui.panel(
        "page.builds.image_title",
        ui.action_form("provision", words.both(lang, "page.builds.card_from_local"),
                       fields=[("api", check.api), ("tree", tree)],
                       argv=view.gui._argv_of("provision", {"tree": tree}, lang,
                                              api=check.api),
                       blocked=view.gui._one_tree(check, lang), lang=lang)
        + ui.hint(state)
        + ui.action_form("index", words.both(lang, "page.builds.index_cards"),
                         fields=index_fields,
                         argv=view.gui._argv_of("index", index_argv, lang, api=check.api),
                         blocked=view.gui._one_tree(check, lang), lang=lang),
        sub=words.both(lang, "page.builds.image_sub"),
        collapsible=True, open_=False, lang=lang)


# ------------------------------------------------------------ /local/<build_id>
def local(view) -> str:
    """One copy's page: the card, the bytes, the record, the remote row, the ledger.

    `data.rows` is one request's answer to one question about *many* builds and this page
    is about one of them, so it reads what the dict cannot carry whole - the `Local` the
    readers already walked (`all_locals()`, memoised for the request) for the card, the
    files and the recorded acts - and takes the rest from the rows it was handed: the
    ledger's rows for this id are in `rows["ledger"]` (the whole ledger) and the activities
    whose command names it are in `rows["runs"]`.

    A build id this machine holds nothing for is a 404 and not an empty page: the route
    names one copy, and six empty panels for an id that is not here would be an answer to a
    question nobody asked.
    """
    build_id = _copied(view)
    held = view.gui.all_locals()
    copy = held.get(build_id)
    if copy is None:
        raise errors.ConfigError(t(view.lang, "error.no_local_copy",
                                   build_id=repr(build_id)))
    answer = view.gui.remote_rows(view.check, held, view.lang)
    remote = next((one for one in answer if str(one.build_id) == build_id), None)
    return "".join((
        _card_panel(view, copy),
        _bytes_panel(view, copy),
        _record_panel(view, copy),
        _remote_panel(view, copy, remote, answer),
        _ledger_rows_panel(view, build_id),
        _activity_panel(view, build_id),
        _commands_panel(view, build_id),
    ))


def _copied(view) -> str:
    """The build id this route names: `/local/<build_id>`, unquoted.

    An empty answer is a route that named no copy at all - `/local` is a 302 onto `/` in
    the engine's own table - and the caller turns it into the same 404 as an id that is not
    on disk: both are "this page has nothing to show".
    """
    route = str(view.route or "")
    head = "/local/"
    if not route.startswith(head):
        return ""
    return urllib.parse.unquote(route[len(head):])


def _card_panel(view, copy) -> str:
    """What the local table registered for this id, and which node it came from.

    A copy with no card is still a copy somebody knows something about - the old `/` printed
    "no card in the local table" beside 30 MiB of bytes while the record it was reading held
    the node id it wanted - so the node row says *which* of the two facts spoke: the card's
    node, or that the table has none.
    """
    lang = view.lang
    card = copy.card
    pairs = [
        (words.both(lang, "word.build_id"), ui.code(copy.build_id)),
        (words.both(lang, "word.describe"),
         ui.esc(card.describe()) if card is not None else ui.DASH),
        (words.both(lang, "word.node_id"), _node_cell(copy, lang)),
        (words.both(lang, "word.tree_branch"),
         ui.esc(f"{card.tree} / {card.branch}") if card is not None else ui.DASH),
        (words.both(lang, "word.arch_defconfig_compiler"),
         ui.esc(" / ".join(one for one in (card.arch, card.defconfig, card.compiler)
                           if one)) if card is not None else ui.DASH),
        (words.both(lang, "word.created"),
         ui.esc(card.created) if card is not None and card.created else ui.DASH),
        (words.both(lang, "label.artifact_urls"), _artifact_urls(card)),
        (words.both(lang, "col.here"), _state_cell(copy, lang)),
    ]
    return ui.panel("page.correspondence.card_title", ui.kv(pairs),
                    sub=words.both(lang, "page.correspondence.card_sub"), lang=lang)


def _node_cell(copy, lang: str) -> str:
    """The node this copy is known by, or the one place it is not known at all."""
    if copy.card is None:
        return words.both(lang, "state.not_in_table")
    if copy.node_id:
        return ui.code(copy.node_id)
    return words.both(lang, "state.no_node_id")


def _artifact_urls(card) -> str:
    """The artifact URLs as the API spells them, one per line - or the dash."""
    if card is None or not card.artifacts:
        return ui.DASH
    return "<br>".join(ui.code(f"{name}: {url}")
                       for name, url in sorted(card.artifacts.items()))


def _state_cell(copy, lang: str) -> str:
    """`Local.state` and its own sentence: what this machine knows about the copy.

    The word is the engine's (`pulled`, `unrecorded`, `registered`, `made-here`, `empty`)
    and the sentence is `Local.state_text()`'s - the reader that owns "pulled three
    artifacts from … at …", and knows that a byte count and a record are two facts.
    """
    word = _HERE_KEYS.get(str(copy.state or ""), "")
    return (ui.pill(str(copy.state or ""), label=word or "", lang=lang)
            + " " + ui.hint(ui.esc(copy.state_text(lang))))


def _bytes_panel(view, copy) -> str:
    """What is on disk, artifact by artifact: the file and its size, read from the disk.

    `Build.present()` and `os.path.getsize`, never the record: one build's newest act named
    a single artifact while three were whole on disk, and a page that printed the record as
    the bytes told the reader the copy was smaller than it was.
    """
    lang = view.lang
    cols = (ui.Col("col.artifact", draw=lambda one: ui.esc(one["artifact"])),
            ui.Col("col.file", kind="wrapc", draw=lambda one: ui.code(one["path"])),
            ui.Col("col.bytes", kind="n", draw=lambda one: one["size"]))
    found = []
    for name, path in sorted(copy.present.items()):
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        found.append({"artifact": name, "path": path,
                      "size": f"{size} ({_human(size)})" if size else ui.DASH})
    return ui.panel("page.correspondence.bytes_title",
                    ui.table(cols, found,
                             empty=t(lang, "empty.no_bytes", path=ui.code(copy.path)),
                             lang=lang),
                    sub=words.both(lang, "page.correspondence.bytes_sub"),
                    flush=True, lang=lang)


def _record_panel(view, copy) -> str:
    """The pull record: every act `Build.make()` wrote, newest first, with its entries.

    One table per act rather than one table for all of them: an act's entries are what was
    attempted *together*, and a flat table would put two attempts' artifacts in one
    alphabetical list.  The act's own line is built from the engine's words
    (`count.artifacts_act`, `label.error_prefix`) and not from a sentence this page
    composed.
    """
    lang = view.lang
    acts = list(copy.acts or ())
    cols = (ui.Col("col.artifact", draw=lambda one: ui.esc(one["artifact"])),
            ui.Col("word.url", kind="wrapc", draw=lambda one: ui.code(one["url"])),
            ui.Col("col.bytes", kind="n",
                   draw=lambda one: f'{one["bytes"]} ({_human(int(one["bytes"] or 0))})'),
            ui.Col("col.that_pull", draw=lambda one: words.both(
                lang, "col.transferred" if one["transferred"]
                else "state.already_whole_proven")))
    parts = []
    for act in acts:
        entries = [one for one in act.get("entries") or () if isinstance(one, dict)]
        said = t(lang, "count.artifacts_act", n=len(entries)) + ", " + (
            t(lang, "label.error_prefix", what=ui.esc(str(act["error"])))
            if act.get("error") else t(lang, "state.no_error"))
        parts.append(ui.hint(f'<b>{ui.esc(str(act.get("at") or "?"))}</b> &mdash; {said}'))
        parts.append(ui.table(cols, entries, lang=lang))
    if not parts:
        return ui.panel("page.correspondence.record_title",
                        ui.empty(words.both(lang, "empty.no_pull_record")), lang=lang)
    return ui.panel("page.correspondence.record_title", "".join(parts),
                    sub=words.both(lang, "count.acts_in_record", n=len(acts)),
                    collapsible=True, lang=lang)


def _remote_panel(view, copy, remote, answer) -> str:
    """This copy's remote counterpart, or which of the three silences this is.

    The sub-line names the question that was asked, because "not in the answer" means
    nothing until the answer is named - and it is rendered in this response's language
    rather than as a swappable span: the question is a value that can carry an `&` (an
    `?api=` a reader typed), and the swap writes text, so a sentence assembled around a URL
    has to be one language.  That language is this answer's.
    """
    lang = view.lang
    query = view.gui.remote_query(view.check, lang)
    sub = t(lang, "page.correspondence.remote_sub", query=ui.esc(query))
    if remote is None:
        if answer is not None and answer.note:
            return ui.panel("page.correspondence.remote_title",
                            ui.hint(t(lang, "remote_detail.no_answer",
                                      note=ui.esc(answer.note))), sub=sub, lang=lang)
        why = t(lang, "remote_detail.none", query=ui.esc(query))
        return ui.panel(
            "page.correspondence.remote_title",
            ui.hint(f'<span title="{ui.esc(why)}">'
                    f'{words.both(lang, "state.no_remote_counterpart")}</span>'),
            sub=sub, lang=lang)
    warning = ""
    if copy.node_id and remote.node_id and str(copy.node_id) != str(remote.node_id):
        warning = ui.hint(words.both(lang, "remote_detail.node_mismatch",
                                     record=ui.esc(copy.node_id),
                                     api=ui.esc(remote.node_id)))
    pairs = [
        (words.both(lang, "word.build_id"), ui.code(remote.build_id)),
        (words.both(lang, "word.node_id"),
         ui.code(remote.node_id) if remote.node_id else ui.DASH),
        (words.both(lang, "word.tree_branch"), ui.esc(f"{remote.tree} / {remote.branch}")),
        (words.both(lang, "word.created"), ui.esc(str(remote.created or "")[:16])),
        (words.both(lang, "word.state_result"),
         ui.pill(remote.state or "?", lang=lang) + " "
         + ui.pill(remote.result or "?", tone_override="idle", lang=lang)),
        (words.both(lang, "col.artifact_urls"), _artifact_urls(remote)),
    ]
    return ui.panel("page.correspondence.remote_title", warning + ui.kv(pairs), sub=sub,
                    lang=lang)


def _ledger_rows_panel(view, build_id: str) -> str:
    """Every record the ledger holds for this build, newest first, as it was stored.

    `detail` is a child process's own free text, printed verbatim: a ledger written before
    a phrasing changed keeps the old words for ever, and a page that rewrote them would be
    claiming something about a run nobody can re-observe.
    """
    lang = view.lang
    rows = [one for one in view.rows.get("ledger") or ()
            if str(one["build_id"]) == build_id]
    cols = (ui.Col("word.test", draw=lambda one: ui.code(one["test"])),
            ui.Col("col.verdict", kind="c",
                   draw=lambda one: ui.pill(one["verdict"], lang=lang)
                   if one["verdict"] else ui.DASH),
            ui.Col("col.exit", kind="n", field="exit"),
            ui.Col("col.source", kind="c",
                   draw=lambda one: ui.pill(one["source"], tone_override="info", lang=lang)
                   if one["source"] else ui.DASH),
            ui.Col("col.when", kind="n", draw=lambda one: _stamp(one["when"])),
            ui.Col("col.detail", kind="wrapc", field="detail"))
    return ui.panel("page.correspondence.ledger_title",
                    ui.table(cols, rows,
                             empty=words.both(lang, "empty.no_ledger_record"), lang=lang),
                    collapsible=True, flush=True, lang=lang)


def _activity_panel(view, build_id: str) -> str:
    """The activities whose command names this build - a text match, and said so.

    The match is the id's first twelve characters in an argv, which is the old page's own
    rule: an activity *is* a command line, the id is in it because a command was given it,
    and nothing ties a run to a build but that.  The sub-line says so, so a reader who sees
    a run that merely mentioned the id is not misled.  Log and cancel are the two things a
    row can do, as on `/runs`: the log is the file itself (`text/plain`, in a tab of its
    own), and cancel is an empty-bodied POST that only a running activity gets.
    """
    lang = view.lang
    search = build_id[:12]
    rows = [one for one in view.rows.get("runs") or () if search in str(one["argv"])]
    cols = (ui.Col("word.id", kind="id", draw=lambda one: ui.esc(one["id"])),
            ui.Col("word.kind", draw=lambda one: ui.esc(one["kind"])),
            ui.Col("word.state", draw=lambda one: ui.pill(
                one["state"], label=ui.end_word(one["state"], one["exit"], lang),
                lang=lang)),
            ui.Col("col.age", kind="n", field="age"),
            ui.Col("col.exit", kind="n", field="exit"),
            ui.Col("col.what_run", kind="wrapc", field="what"),
            ui.Col("", kind="acts-cell", draw=lambda one: _log_acts(one, lang)))
    return ui.panel("page.correspondence.activities_title",
                    ui.table(cols, rows,
                             empty=words.both(lang, "empty.no_activity_match"), lang=lang),
                    sub=words.both(lang, "page.correspondence.activities_sub"),
                    collapsible=True, flush=True, lang=lang)


def _log_acts(one, lang: str) -> str:
    """Read this activity's log, and cancel it while it is still running."""
    ident = ui.esc(one["id"])
    log = f"/runs/{ident}/log"
    acts = [(f'<a href="{log}" target="_blank" rel="noopener">'
             f'{words.both(lang, "link.log")}</a>')]
    if str(one["state"]) == run_mod.RUNNING:
        acts.append(f'<form method="post" action="/api/runs/{ident}/cancel">'
                    f'<button class="btn sm">{words.both(lang, "js.cancel")}</button>'
                    f"</form>")
    return f'<span class="cell-actions">{"".join(acts)}</span>'


def _commands_panel(view, build_id: str) -> str:
    """The two commands a reader starts from one copy's page.

    `pull` re-checks the sizes and appends an act to the record above; `run` runs the tests
    this copy has no record for - which is the ledger panel's missing half.  Both are
    handed the one id this route names, and the argv under each button is the command it
    will run, from `command()` through `_argv_of`, so the printed line and the process
    cannot disagree.
    """
    lang, check = view.lang, view.check
    fields = [("selected", build_id), ("api", check.api)]
    return ui.panel(
        "page.correspondence.commands_title",
        ui.action_form("pull", words.both(lang, "btn.pull_recheck"), fields=fields,
                       argv=view.gui._argv_of("pull", {"selected": build_id}, lang,
                                              api=check.api),
                       hint="correspondence.pull_hint", lang=lang)
        + ui.action_form("run", words.both(lang, "btn.run_pending"), fields=fields,
                         argv=view.gui._argv_of("run", {"selected": build_id}, lang,
                                                api=check.api),
                         lang=lang),
        lang=lang)
