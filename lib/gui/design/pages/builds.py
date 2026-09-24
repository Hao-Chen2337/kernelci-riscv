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

**A verdict is one run's answer, so the pill that shows it is also the door to the
rest.**  A pair can be run as many times as a reader likes and the ledger keeps one
record for it (`var/results/<build>/<test>.json` is rewritten by each run), while every
run keeps its own console in `var/logs/`.  `_ran_cell`'s pill therefore links to
`/local/<build_id>?test=<test>`, and that page draws `_run_history_panel`: every console
of the pair, newest first, with the one surviving record joined onto the run it is about.
That panel is the only reader of run history in this tree, because `var/logs/` is the
only complete list of runs there is.

**Nothing here writes a path, a query string or a date by hand.**  A link is
`view.url()` (so `?api=` is canonicalised and `?lang=` spelled in one place), a path is
`lib/layout`'s accessor, and a timestamp is the record's own string cut at its `T`.
"""

import glob
import os
import urllib.parse
from dataclasses import replace
from functools import partial

from .... import errors, layout
from .... import run as run_mod
from ....build import ARTIFACTS
from ....i18n import DEFAULT_LANG, LANGS, t
from ....sink import Ledger
from ...forms import _names, _tests_of
from ...schema import (
    _LABELS,
    DAY_CHOICES,
    EVIDENCE,
    FILTER_ORDER,
    KBUILD_STATES,
    LIMITS,
    MAX_DAYS,
    MAX_LIMIT,
    RESULTS,
)
from ...urls import _carried
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

# The two sides a row can come from, as the reader's own words for them, in the order the
# bar draws them.  The *value* is what `forms._origins` reads back out of the query and what
# `accepts` ORs together, and it is the axis's own spelling (`schema.ORIGINS`) rather than a
# label - a checkbox's `value=` is data, and `/`'s 来源 boxes are the only control on this
# page whose value the reader never sees.
_ORIGIN_SIDES = (("local", "origin.label.local"), ("remote", "origin.label.remote"))

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

# `models.COPY_ORIGINS`' three values as the catalogue's own words for exactly those
# values - the 出处 column's cells.  A value not in this map is a copy no act
# describes, which the cell draws as the dash: "nothing recorded" is a fact about the
# record, not a place the bytes came from, and it is not in this map for that reason.
# (It is `COPY_ORIGINS` and not `ORIGINS` - that other name is the *filter* axis,
# `any`/`local`/`remote`/`both`/`card`, and the two must not be read as one.)
_SOURCE_KEYS = {
    "made-here": "source.made_here",
    "local-api": "source.local_api",
    "official": "source.official",
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
    table, _ = view.gui._state()
    found = list(rows.get("builds") or ())
    return "".join((
        _asked(view, quoted),
        _bar(view, _MAIN, _main_fields(view)),
        ui.more(words.both(lang, "btn.more"), _bar(view, _FOLD, _fold_fields(view)),
                # The fold this page's 更多筛选 row is remembered by (`ui._fold`).
                fold="more.builds"),
        ui.cpanel(_strip(view, quoted),
                  sub=words.both(lang, "page.builds.chips_title"), lang=lang),
        _builds_panel(view, found, held, quoted, table, opened, opened_check),
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

    The keys are `urls._carried`'s and not a walk of `FILTER_ORDER`, because the order is
    not the whole of the filter: the top bar's clock (`shell.tz_switch`) is a `Filter`
    field outside it, and a rule that only walked the order reset the reader's clock on
    every apply.
    """
    hidden = _carried(_ROUTE, view.check, drawn)
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


def _titled(lang: str, key: str, title: str) -> str:
    """A field's label, with the paragraph that defines the field in its `title=`.

    Some of this page's boxes offer words that mean nothing on their own - the two axes
    behind the fold are the ones the operator asked about (「解释一下」) - and a `title=` is
    where a fact about a control lives (`analysis._delta_cap` does the same).  The
    alternative the board uses for its prose is a sentence on the page, which is the
    「垃圾文字注释」 this page has none of.
    """
    return (f'<span {words.attr(lang, "title", title)}>'
            f'{words.both(lang, key)}</span>')


def _origin_boxes(view) -> str:
    """来源: the two sides a row can come from, ticked one at a time or both.

    **本地 and 远端, and neither of the two values the select used to offer.**  有卡片 is a
    fact the 表里的卡片 column prints row by row - the operator's own argument for
    dropping it (「那个有卡片这个后面不是有区分了吗」) - 两个都要 is what ticking both of these
    says, and 不限 is what ticking neither says.  One select offering all three invited
    the reader to keep three spellings of one question apart.

    **Two ticks are one value and it is the sides it names.**  `forms._origins` reads the
    comma list `local,remote`, which `accepts` ORs, so the two boxes round-trip exactly:
    the URL a press writes draws both boxes ticked again.  The boxes carry `data-multi`
    (`ui.checkbox`), without which the shipped bar would submit on the first tick and the
    reader could never ask for both.

    **`card` is honoured and drawn by nothing here.**  `?origin=card` is what the strip's
    已登记 chip and the 卡片 preset write, and it is narrower than 本地 (a card in the
    table, not a card *or* bytes) - so when it is in force the boxes cannot say it and the
    note does.  A page that drew neither box ticked and said nothing would be applying a
    condition it does not show.
    """
    lang, check = view.lang, view.check
    chosen = set(_names(check.origin))
    if "both" in chosen:
        # A round-1 spelling of two ticks: drawn as the two ticks it means, so a link
        # written before this round shows a reader the state it really asks for.
        chosen = {value for value, _key in _ORIGIN_SIDES}
    boxes = "".join(
        ui.checkbox("origin", words.both(lang, key), checked=value in chosen,
                    value=value, multi=True, lang=lang)
        for value, key in _ORIGIN_SIDES)
    if "card" in chosen:
        boxes += (f'<span class="muted" style="font-size:11px">'
                  f'{words.both(lang, "origin.card_only")}</span>')
    return boxes


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
        ui.field(_titled(lang, "filter.origin", "filter.origin_title"),
                 _origin_boxes(view), width="w-md"),
        ui.field(_titled(lang, "filter.evidence", "filter.evidence_title"),
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
        # `limit=number` is what keeps this chip honest now that `/runs` pages: the link
        # asks for a table of the number the chip counted, so the page it lands on draws
        # every one of them and S6 can still count them back.  The number is already held
        # to the cap any link can carry (`_countable`).
        kinds = _kinds_of(view.rows)
        return number, (view.url("/runs", *FILTER_ORDER, kind=kinds, limit=number)
                        if kinds else "")
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
# The two marks this page draws for an artifact, as the glyphs the cells write.  One
# spelling for the table and for the legend above it (`_card_legend`), so the ✓ the
# reader is told about is the ✓ in the row: `_card_cell` and `_resource_cell` both write
# these two entities, and the classes are the board's own (`style.py`: `.tick` is `--ok`,
# `.cross` is `--bad`).
_TICK = "&#10003;"
_CROSS = "&#10007;"


def _builds_panel(view, found, held: dict, answer, table, opened, opened_check) -> str:
    """The table, its pager, the three view presets, and the one command over its ticks.

    The head carries what the board's head carries: the row count as the sub-line (a
    number, computed - the board printed a literal 7 over its 24-row table and relied on
    its own script to correct it), the three presets as the tools, and the bar that pulls
    every ticked row.  The tick boxes are *outside* that bar's form (`form="pull-now"`),
    which is the only way a table can feed a form drawn in a head, and the select-all box
    sits in the tick column's header, where the board draws it.

    `_card_legend` goes **inside** the body, above the table, and not in the head with
    the count: it explains one column, it is read once and then skipped, and the head is
    where the reader looks for what the *list* is - a sentence about 卡片's marks there
    would be in the way of the presets on every visit to answer one question once.
    """
    lang = view.lang
    return ui.panel(
        "page.builds.title",
        _card_legend(lang)
        + ui.table(_cols(view, found, held, answer), found,
                   empty=_empty(view, answer, held), lang=lang)
        + _pager(view, found, answer),
        sub=words.both(lang, "page.builds.rows_window", n=len(found)),
        tools=_presets(view, table, opened, opened_check) + _pull_bar(view), flush=True,
        lang=lang)


def _card_legend(lang: str) -> str:
    """The line over the table that says what the 卡片 column's three marks are.

    **The tooltip was not enough, and the operator said so.**  `col.card_title` answers
    「卡片这里为什么要显示三个钩或者×」 in the header's `title=`, and each mark answers
    for itself in its own (`card.tick_here`/`card.tick_absent`) - all of it invisible to
    a reader who does not hover, and the question is one a reader has *while reading the
    table*, not one they think to ask of a two-character heading.  So the same answer is
    drawn on the page: which three artifacts the marks are, in which order, and what a
    tick and a cross mean.

    **The marks are shown and not described.**  The glyphs are the cells' own (`_TICK` /
    `_CROSS` in `.tick`/`.cross`, the colours of the column below), so a reader who has
    never seen this console still has the pair in front of them - colour, glyph and word
    together, which is the house rule for a colour signal (`_resource_cell` states it).
    The sentence itself is `col.card_legend`.

    `t()` and not `both()`: the value carries those two spans, and `words.both` refuses
    markup - the swap writes text, so a tagged value would arrive at a Chinese reader as
    its own characters.  `builds._remote_panel` and `analysis` make the same call for
    the same reason.  The consequence is the catalogue's own and it is honest: this line
    is drawn in the response's language rather than swapping in place.
    """
    return (f'<p class="cardkey">'
            f'{t(lang, "col.card_legend", yes=_TICK, no=_CROSS)}</p>')


def _cols(view, found, held: dict, answer) -> tuple:
    """The board's nine columns, three facts about this machine, and the two keys the script reads.

    The tick column's header is `ui.checkbox(all_for=…)`, rendered `hidden` until the
    shipped script unhides it: with the script off a box that ticks nothing would be a
    lie, and the rows' own boxes (which work) are there to be ticked by hand.

    The three inserted columns (出处, 表里的卡片, 资源) are the design's own order
    extended, not a second table: the board's nine kept their places and the three sit
    with the ticks and the size, which are the columns that ask *what does this machine
    hold* - one fact each, and each header's `title=` says which "local" it is about.

    No column carries a `key=`.  The board marks five of its headers `sortable`, but this
    page reads no `sort` - the order is `created`, decided by the engine - and a header
    that looked clickable and answered nothing is the "功能页不太对" this round exists to
    remove.
    """
    lang = view.lang
    return (
        ui.Col(ui.checkbox("all", words.both(lang, "tick.all", n=len(found)),
                           all_for=_PULL_FORM, lang=lang), kind="c",
               draw=lambda one: _tick_cell(view, one, held)),
        ui.Col("word.build_id", kind="id",
               draw=lambda one: _build_cell(view, one["build_id"])),
        ui.Col("word.tree_branch", draw=_tree_cell),
        ui.Col("word.created", kind="n",
               draw=lambda one: ui.stamp(one["created"], view.check.tz)),
        ui.Col("col.card", kind="c", width="104px",
               title="col.card_title",
               draw=lambda one: _card_cell(one, lang)),
        # The three per-build facts, in the plan's order: where the bytes came from,
        # whether the local table holds a card, and what is on disk.  They sit between
        # the ticks and the size because they are the same kind of statement - what
        # this machine holds - and each header's `title=` is where its "local" is
        # spelled out: 本地 is this disk and this ledger, 本地 API is the service on
        # :8001, and the two words must not be read as one.
        ui.Col("col.provenance", draw=lambda one: _source_cell(one, lang),
               title="col.provenance_title"),
        ui.Col("col.in_table", kind="c", width="104px",
               draw=lambda one: _in_table_cell(one, lang), title="col.in_table_title"),
        ui.Col("col.resource", draw=lambda one: _resource_cell(one, lang),
               title="col.resource_title"),
        ui.Col("col.bytes", kind="n", draw=_bytes_cell),
        ui.Col("col.act", kind="n", draw=lambda one: _acts_cell(one, lang)),
        ui.Col("col.api_says", draw=lambda one: _api_cell(one, answer, lang)),
        ui.Col("filter.ran", draw=lambda one: _ran_cell(view, one)),
    )


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
    """The four commands over this table's ticks, in one form.

    *pull the selected* is what the page always had.  *index this window* and *index,
    then pull the selected* are the answer to the table that reads 勾不了: on a view of
    another API the ticked rows are exactly the ones this machine has no card for, and
    `table.py pull` reads the local table - so the pull cannot work until the window the
    rows were drawn from has been registered.  The registering used to be a button in a
    panel folded shut at the bottom of the page, under a title about local cards, which
    is not where a reader who cannot tick anything goes looking.  *smart run* is the
    same four questions asked of the rows in the order the rows need them answered
    (`actions.ActionsMixin._smart`): it is for the reader who does not want to work out
    which of the other three presses this selection is ready for.

    **One form, five buttons.**  A tick box names exactly one form (`form="…"`), and
    the four tick-driven commands here have to read the same boxes - so they are buttons
    of one form, each carrying its own `formaction`, which `ui.action_form`'s `also`
    draws and the shipped script reads off the button that was pressed.  The fields are
    the union of what the five need: `pull` reads only `selected` and ignores the
    window's conditions, `index` reads those and ignores the ticks.  The fifth is the
    fourth's own command in its other mode (`redo` on the button itself), which is why
    the two are one action apart and not two actions.

    No visible argv line, for the reason the pull bar never had one: four of the five
    commands take `<each ticked build>`, which does not exist until a box is ticked -
    and one line under five buttons would be read as the command for whichever the
    reader is about to press.  Each button's own `title=` carries what is known of it.
    """
    lang, check = view.lang, view.check
    fields = [("api", check.api), ("tree", check.tree),
              ("days", str(check.days)), ("limit", str(check.limit))]
    # `table.py index` and `table.py index-pull` each declare one `--tree`, so a filter
    # naming several trees cannot be handed to either - the same refusal, and the same
    # sentence, the panel's own index button carried.
    blocked = view.gui._one_tree(check, lang)
    return ui.action_form(
        "pull", words.both(lang, "btn.pull_selected"), fields=fields, form_id=_PULL_FORM,
        hint="pull.pull_hint", lang=lang,
        also=(("index", words.both(lang, "page.builds.index_cards"),
               view.gui._argv_of("index", {"tree": check.tree, "days": str(check.days),
                                           "limit": str(check.limit)},
                                 lang, api=check.api),
               blocked),
              ("index_pull", words.both(lang, "btn.index_pull"),
               view.gui._argv_of_ticked("index_pull", {"tree": check.tree,
                                                       "days": str(check.days),
                                                       "limit": str(check.limit)},
                                        lang, api=check.api),
               blocked),
              # 智能运行: the same ticks, the same fields, and a decision the other three
              # leave to the reader - which of the three commands these rows need first
              # (`actions.ActionsMixin._smart` reads the rows and answers per row).  Its
              # `title=` is the hint and not an argv: the command does not exist until a
              # box is ticked, for the reason the other two tick-driven buttons print
              # none either - and because *which* command it is depends on what those
              # ticks hold.  It carries no `blocked` of its own, and the two above carry
              # the bar's: `_one_tree` is about the register half, which is `index` and
              # `index-pull` only.  What a multi-tree filter does to *this* button is
              # `command()`'s own `_named(form, "tree")`, which every one of its three
              # commands reads before it dispatches - so a press on a two-tree filter is
              # refused in the same words the `pull` button beside it is refused in, and
              # no phase of this press is an exception to that.
              ("smart", words.both(lang, "btn.smart_run"), "smart.hint", ""),
              # **重跑, and it is the smart press with the ledger ignored.**  The
              # operator's 「难道就不能默认增加重跑？」: `--redo` was reachable only from
              # a single build's own page, one pair at a time, through a record the
              # reader had to go and find first.  Here it is the row's own tick and the
              # same press - `redo=1` on the button (`ui.action_form`'s `also`), which
              # `_smart` hands to the phase-3 command, so the pair runs whether or not
              # the ledger has it.  It is not a *second* way to run: the phases above it
              # are unchanged, and a row that still needs its card or its bytes gets
              # them first (`smart.rerun_hint` says so - this button has no argv to
              # print, because which command it is depends on what the ticks hold).
              ("smart", words.both(lang, "btn.run_redo"), "smart.rerun_hint", "",
               (("redo", "1"),))))


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
    """This row's box - every row has one - and the row's own pull where there is a card.

    **Every row is tickable, and the box does not depend on what this machine holds.**
    It used to be drawn only where the local table already had a card, because
    `table.py pull --build` reads that table and refuses the rest with `no build '…' in
    builds.json` - so on a view of another API, where almost nothing is carded yet, the
    whole table read 勾不了 and the page looked broken.  But *which rows the reader
    means* and *which rows can be fetched right now* are two different questions, and
    the box was answering the second one.  A tick is a selection: it says which rows
    the bar's command is about, and the two index buttons beside that command are
    exactly what turns a selection of uncarded rows into a pull that works.

    What is still gated is the row's *own* `pull`, which is a form of its own with no
    registering half to reach for - pressing it on a row with no card can only refuse,
    so it is not drawn, and the marker beside the box says why.  That marker is a
    statement about the row's card and not about the tick above it.

    The row's own `pull` is a form of its own, so pulling one card does not mean ticking a
    box, finding the bar above and pressing a button that is also holding somebody else's
    ticks.  Its command line is the form's `title=` rather than a printed line: fifty of
    those under a column of ticks is a wall, and the bar above already prints the shape.
    """
    lang = view.lang
    build_id = str(one["build_id"])
    box = ui.checkbox("selected", "", value=build_id, form=_PULL_FORM, lang=lang)
    copy = held.get(build_id)
    if copy is None or copy.card is None:
        return (box
                + f'<span class="none" {words.attr(lang, "title", "pull.no_card_title")}>'
                + f'{words.both(lang, "pull.no_card")}</span>')
    return (box
            + ui.action_form("pull", words.both(lang, "pull.one"),
                             fields=[("selected", build_id), ("api", view.check.api)],
                             hint=t(lang, "pull.one_title", build=build_id),
                             form_id=_ONE_FORM, kind="sm", lang=lang))


def _build_cell(view, build_id) -> str:
    """A build id, linked to the page that shows that build alone.

    `/local/<build_id>` is this console's detail route for one build (`00-BRIEF.md` §5
    keeps it reachable) and it is the page that reads the same API key, so the link carries
    `api=` and nothing else: the detail page reads no window and no tree, and a link that
    carried them would look like a condition it honours.  (`limit` is the one filter key
    it does read - the page size its four lists page at - and `ROUTE_KEYS["/local/"]`
    says so.)
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




def _card_cell(one, lang: str) -> str:
    """The three artifacts of a card, each ticked from `Build.present()` or explained.

    **This column exists because a card with nothing behind it used to look like a whole
    build.**  The tick is an `os.path.isfile` per artifact (`data._builds.checks`), never
    the card's own URLs: a card that declares three artifacts and holds none is the row
    this column is here to expose, and reading the card would tick all three for a copy
    with no bytes at all.  The group's own `title=` is `Local.state`, the engine's word
    for what this machine knows about the copy - three ticks cannot tell a copy nobody
    pulled from one that was pulled and left unrecorded.

    **Three marks are three artifacts, and each mark now says which.**  The reader asked
    what the three are (「卡片这里为什么要显示三个钩或者×」), and the answer was in the
    markup and unreadable: each glyph carried `page.builds.present` (在 / 不在) and the
    artifact's *name* was on a span wrapped around it - so the name was shadowed by the
    inner title and hovering a ✓ said only "在".  One title per mark, naming the artifact
    and its state in one sentence (`card.tick_here`/`card.tick_absent`), is the whole
    fact the tooltip has room for; `col.card_title` says what the column as a whole is,
    and **`_card_legend` draws the same answer on the page above the table**, because the
    operator asked this question a second time and a fact that lives only under a hover
    is a fact a reader who does not hover never sees.  The name stays a code word from
    `CARD_ARTIFACTS` - it is a filename, not a word this catalogue translates.
    """
    checks = dict(one.get("checks") or {})
    parts = []
    for name in CARD_ARTIFACTS:
        here = bool(checks.get(name))
        glyph, cls = (_TICK, "tick") if here else (_CROSS, "cross")
        title = "card.tick_here" if here else "card.tick_absent"
        parts.append(f'<span class="{cls}" '
                     f'{words.attr(lang, "title", title, name=name)}>{glyph}</span>')
    here = str(one.get("here") or "")
    return (f'<span class="cell-actions" '
            f'{words.attr(lang, "title", _HERE_KEYS.get(here, "") or "state.unknown")}>'
            f'{"".join(parts)}</span>')


def _source_cell(one, lang: str) -> str:
    """出处: where this copy's bytes came from - the act's own URLs, in three words.

    `Local.origin` is the reading and this is the word for it; the column's `title=`
    defines the three.  A copy no act describes is the dash, which is not a fourth
    origin: nothing was recorded, and the words for "we do not know" would be this
    page's own invention (`data._builds.source` says the same).

    Two of the three words name a *machine*, and the one this column must not be
    confused about is the local API: 本地 here is this disk, and the API on :8001 is
    a service this console talks to - which is why the tooltip is a paragraph and not
    the two-character label the other columns get away with.
    """
    value = str(one.get("source") or "")
    key = _SOURCE_KEYS.get(value)
    return ui.DASH if key is None else words.both(lang, key)


def _in_table_cell(one, lang: str) -> str:
    """卡片: is there a card for this build in the local table? (有 / 没有)

    The fact is `Builds.load()`'s own (`build_row.in_table`), which is what the card
    view and the chips above the table count - this column does not read the API, and
    the header's tooltip says so: 本地 is `var/state/builds.json` on this disk.
    """
    return words.both(lang, "state.has" if one.get("in_table") else "state.has_not")


def _resource_cell(one, lang: str) -> str:
    """资源: every artifact of this build, ticked or crossed, in the two design colours.

    `Local.present` is one `os.path.isfile` per artifact, and the names are
    `lib/build/model.py`'s own - the same vocabulary the ticks beside this column are
    drawn from, plus `config`, which the ticks leave out because no test needs it (a
    copy holding only its `.config` is a copy with something in it, and a tick column
    that asks about three artifacts cannot say that).

    **The operator's 「资源列红绿」: the absences are drawn, not only the presences.**
    The cell printed the artifacts that *are* on disk and the one word 没有 when none
    was, so the reader who wants the whole picture - can these tests run, which is the
    question this page is read for - had to hold that list against the three ticks in
    the column beside it and diff the two: three-of-four and four-of-four read as two
    lists of names.  Every artifact is a mark now, ✓ in `--ok` or ✗ in `--bad` - the two
    glyphs, in the two colours, that `_card_cell` already draws for these files.

    **Colour is never the only signal, and that is why the name is inside the mark.**
    This console is read with the script off and by readers who do not tell red from
    green, so each mark carries three things at once: the glyph (✓/✗, which is a shape
    and not a hue), the colour, and the artifact's own `title=`
    (`card.tick_here`/`card.tick_absent`, the words the 卡片 column already uses for
    this exact fact) - and the name is drawn *inside* the mark rather than beside it, so
    a reader who sees neither the colour nor an obvious glyph still reads `kernel` or
    `config` and knows which file the row is about.  The group's `title=` stays the
    paths of the files that are here, escaped: a path is the one thing a reader cannot
    guess from a name.

    A row with nothing on disk is therefore four crossed names and not one word: those
    four absences *are* the detail this column is opened for, and a directory nobody
    pulled is four files that are not here rather than a fact about a directory.
    """
    present = set(one.get("present") or ())
    marks = []
    for name in ARTIFACTS:
        here = name in present
        glyph, cls = (_TICK, "tick") if here else (_CROSS, "cross")
        title = "card.tick_here" if here else "card.tick_absent"
        marks.append(f'<span class="{cls}" '
                     f'{words.attr(lang, "title", title, name=name)}>'
                     f'{glyph} {ui.esc(name)}</span>')
    paths = ui.esc(str(one.get("present_paths") or ""))
    return f'<span class="cell-actions" title="{paths}">{" ".join(marks)}</span>'


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


def _ran_cell(view, one) -> str:
    """The ledger's verdicts for this build, one linked pill per test, or the dash.

    The page computes no verdict: `ran` is `Records.last(test, build_id)` per test, and a
    pair with no record is a dash rather than a pill - which is exactly what the gap
    counts.  A row with no card still gets its verdicts, because the ledger is keyed by
    build id and does not care what the table says.

    **The pill is also the door to that pair's runs.**  What a reader does with a `fail`
    is ask how often and since when, and the answer is the pair's consoles - which the
    ledger cannot give (it keeps one record per pair, rewritten by each run) and
    `/local/<build_id>?test=<test>` can (`_run_history_panel`).  The pill's own word is
    untouched: the link is drawn around it and the `title=` says what it opens, so a
    cell that printed one verdict before still prints one verdict.
    """
    lang = view.lang
    build_id = str(one["build_id"])
    parts = []
    for test, verdict in one.get("ran") or ():
        if not verdict:
            continue
        href = view.url("/local/" + urllib.parse.quote(build_id), test=test)
        why = words.attr(lang, "title", "page.history.link_title", test=test)
        parts.append(f'<a href="{ui.esc(href)}" {why}>'
                     f'{ui.pill(verdict, label=f"{test} {verdict}", lang=lang)}</a>')
    return f'<span class="cell-actions">{"".join(parts)}</span>' if parts else ui.DASH


# --------------------------------------------------------------- the panels
# `_ledger_panel` stood here, printing the records' verdict tally and the per-test
# regression counts.  **The operator cut it** (「这个可以删除了就是」), and the case for
# keeping it had already been spent: the panel had been trimmed once before, for printing
# the ledger's size and the gap count - numbers the strip above it already carries as
# *links*, which a reader can click and check.  What was left was two chips that were
# neither clickable nor checkable, and the regressions chip in particular was the third
# printing of one reading: `re.transitions()` counts them, `_timelines` carries the pairs,
# and `_regressions_panel` on `/analysis` and `/trend` lists them one by one with a door
# into each build.  A bare integer that no page draws rows for is the one kind of number
# this console does not print.
#
# `records` is still read by `builds()` for the table below (`_state()` returns the pair),
# which is why the call site now unpacks it as `_` rather than dropping the read.
def _pulls_panel(view) -> str:
    """What has been pulled: one row per act, newest first.

    This table is where a build that is on disk with **no card** is visible at all: such
    a copy is not in the local table, so the card view - the page's default - draws no
    build row for it, and `accept.py`'s S7, which exists for exactly that copy, finds it
    here by its own id.

    It was uncapped on that argument, and the argument was right about what must not
    happen (a copy the reader cannot reach) and wrong about the remedy: with 352 acts
    recorded on this machine the one-row-per-act list was eight screens of scrolling,
    and the copy that needed finding was *harder* to find, not easier.  So it pages -
    `?pulls=50` and on - which keeps every act reachable, in order, and puts the newest
    fifty where a reader looks first.  S7 walks the pages now (`accept._pulls_page_with`),
    so the copy this panel exists to show is still the copy the gate reads.

    A row's id is the link into that build's own page, and the short form is what a
    seven-column table can hold - the whole id is the link's `title=`.
    """
    lang = view.lang
    pulls = list(view.rows.get("pulls") or ())
    cols = (
        ui.Col("col.when", kind="n",
               draw=lambda one: ui.stamp(one["when"], view.check.tz, seconds=True)),
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
            + ui.list_panel(view, "page.builds.acts_title", cols, pulls,
                            empty=empty, lang=lang,
                            sub=words.both(lang, "page.builds.acts_sub"),
                            offset=view.check.list_offset("pulls"),
                            limit=view.check.limit, key="pulls",
                            collapsible=True, open_=False)
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
    """Where a build with no remote counterpart comes from, and the boxes that make one.

    A card this machine made is the one row the API can never answer for, and the way such
    a card comes to exist is a local artifact published as a build - which is why the
    command is about the disk and not about the query, and why it is folded away.

    **The boxes are the command's own facts, and they are the only copy of them.**  The
    operator asked to make such a card himself (「你可以加一些参数…然后让他能自己造」), and
    the facts only the reader knows are exactly what `run_latest.py --provision-only`
    takes as `--parameter k=v` (`actions.command`'s provision branch says why each one is
    a parameter and not a flag).  So they are visible inputs inside the form and not hidden
    values beside it: a hidden `tree` and a visible one would submit the name twice.

    **The tree box starts from this page's own question.**  A reader who is looking at one
    tree and presses this is publishing *that* tree, so the box is prefilled with it - but
    only when the filter names exactly one, because `--tree` is single-valued and a
    comma-joined value is a value the command refuses.

    **No argv line is printed.**  Five of the six values do not exist until the reader
    types them, and a line that showed `--parameter commit=` would be a command line that
    is not the one the press runs; `_pull_bar` is the precedent (what is knowable goes in
    the button's `title=`), and `page.builds.image_command` is that title.

    **`index` used to be drawn here as well**, and it is drawn **once** on this page: it is
    in the table's own bar now (`_pull_bar`), because registering this window is what makes
    the rows above tickable and belongs where the ticks are, not under a title about local
    cards at the bottom.  The board draws that command twice (once in the table's head,
    once here) and two forms for one command are two answer lines for one press.
    """
    lang, check = view.lang, view.check
    named = _names(check.tree)
    tree = named[0] if len(named) == 1 else "riscv"
    image = layout.serve("Image")
    state = (t(lang, "local.image_state", path=ui.code(image)) if os.path.isfile(image)
             else t(lang, "local.image_state_missing", path=ui.code(image)))

    def box(name: str, key: str, width: str, value: str = "") -> str:
        """One fact: the box's `name=` is the `--parameter` key, the label is a word."""
        return ui.field(words.both(lang, key),
                        ui.text_input(name, value, placeholder=key, label=key, lang=lang),
                        width=width)

    fields = (box("tree", "word.tree", "w-md", tree)
              + box("branch", "word.branch", "w-md")
              + box("commit", "word.commit", "w-md")
              + box("describe", "word.describe", "w-lg")
              + box("defconfig", "word.defconfig", "w-md")
              + box("kernel_url", "word.kernel_url", "w-xl"))
    return ui.panel(
        "page.builds.image_title",
        ui.hint(words.both(lang, "page.builds.image_how"))
        + ui.action_form("provision", words.both(lang, "page.builds.card_from_local"),
                         fields=[("api", check.api)],
                         inner=f'<div class="filters" style="border-bottom:0">{fields}</div>',
                         hint="page.builds.image_command", lang=lang)
        + ui.hint(state),
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

    **`?test=` adds one panel and changes nothing else.**  A reader who pressed a verdict
    pill on `/` (`_ran_cell`) asked about one *pair*, not about the copy, so the answer -
    every run of that pair, `_run_history_panel` - goes first, where the click was aiming.
    Without the key the page is panel for panel the page it was: the route names one copy
    and nothing here answers a question about its tests unasked.

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
    panels = [
        _card_panel(view, copy),
        _bytes_panel(view, copy),
        _record_panel(view, copy),
        _remote_panel(view, copy, remote, answer),
        _ledger_rows_panel(view, build_id),
        _activity_panel(view, build_id),
        _commands_panel(view, build_id),
    ]
    test = str(getattr(view.check, "test", "") or "")
    if test:
        panels.insert(0, _run_history_panel(view, build_id, test))
    return "".join(panels)


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
    return ui.list_panel(view, "page.correspondence.bytes_title", cols, found,
                         empty=t(lang, "empty.no_bytes", path=ui.code(copy.path)),
                         lang=lang,
                         sub=words.both(lang, "page.correspondence.bytes_sub"),
                         offset=view.check.list_offset("bytes"),
                         limit=view.check.limit, key="bytes")


def _record_panel(view, copy) -> str:
    """The pull record: every act `Build.make()` wrote, newest first, with its entries.

    One table per act rather than one table for all of them: an act's entries are what was
    attempted *together*, and a flat table would put two attempts' artifacts in one
    alphabetical list.  The act's own line is built from the engine's words
    (`count.artifacts_act`, `label.error_prefix`) and not from a sentence this page
    composed.

    That one-table-per-act shape is why this panel does not go through `ui.list_panel`:
    the thing being paged is acts, not rows, so the page is cut out of `acts` here and
    the pager is handed the act count.  A record grows with every pull and was the
    longest thing on this page, which is what put it on `record` (`schema.LIST_OFFSETS`)
    - a key of its own, so paging the record does not page the bytes at the same time.
    """
    lang = view.lang
    acts = list(copy.acts or ())
    if not acts:
        return ui.panel("page.correspondence.record_title",
                        ui.empty(words.both(lang, "empty.no_pull_record")), lang=lang)
    limit = max(1, view.check.limit)
    offset, acts_here = ui.page_slice(acts, view.check.list_offset("record"), limit)
    cols = (ui.Col("col.artifact", draw=lambda one: ui.esc(one["artifact"])),
            ui.Col("word.url", kind="wrapc", draw=lambda one: ui.code(one["url"])),
            ui.Col("col.bytes", kind="n",
                   draw=lambda one: f'{one["bytes"]} ({_human(int(one["bytes"] or 0))})'),
            ui.Col("col.that_pull", draw=lambda one: words.both(
                lang, "col.transferred" if one["transferred"]
                else "state.already_whole_proven")))
    parts = []
    for act in acts_here:
        entries = [one for one in act.get("entries") or () if isinstance(one, dict)]
        said = t(lang, "count.artifacts_act", n=len(entries)) + ", " + (
            t(lang, "label.error_prefix", what=ui.esc(str(act["error"])))
            if act.get("error") else t(lang, "state.no_error"))
        parts.append(ui.hint(f'<b>{ui.esc(str(act.get("at") or "?"))}</b> &mdash; {said}'))
        parts.append(ui.table(cols, entries, lang=lang))
    return ui.panel("page.correspondence.record_title",
                    "".join(parts)
                    + ui.pager(view, len(acts), limit, offset, key="record"),
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
            ui.Col("col.when", kind="n",
                  draw=lambda one: ui.stamp(one["when"], view.check.tz)),
            ui.Col("col.detail", kind="wrapc", field="detail"))
    return ui.list_panel(view, "page.correspondence.ledger_title", cols, rows,
                         empty=words.both(lang, "empty.no_ledger_record"), lang=lang,
                         offset=view.check.list_offset("ledger"),
                         limit=view.check.limit, key="ledger",
                         collapsible=True, open_=True)


def _activity_panel(view, build_id: str) -> str:
    """The activities whose command names this build - a text match, and said so.

    The match is the id's first twelve characters in an argv, which is the old page's own
    rule: an activity *is* a command line, the id is in it because a command was given it,
    and nothing ties a run to a build but that.  The sub-line says so, so a reader who sees
    a run that merely mentioned the id is not misled.  Log and cancel are the two things a
    row can do, as on `/runs`: the log is the file itself, in a tab of its own and with
    this page as its `?back=` (`ui.log_link`), and cancel is an empty-bodied POST that only
    a running activity gets.
    """
    lang = view.lang
    back = view.url()
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
            ui.Col("", kind="acts-cell", draw=lambda one: _log_acts(one, lang, back)))
    return ui.list_panel(view, "page.correspondence.activities_title", cols, rows,
                         empty=words.both(lang, "empty.no_activity_match"), lang=lang,
                         sub=words.both(lang, "page.correspondence.activities_sub"),
                         offset=view.check.list_offset("activities"),
                         limit=view.check.limit, key="activities",
                         collapsible=True, open_=True)


def _log_acts(one, lang: str, back: str = "") -> str:
    """Read this activity's log, and cancel it while it is still running.

    `back` is this page, so the log's own tab can lead here again - the tab has no
    Back button into a page it did not come from (`ui.log_link`).
    """
    ident = ui.esc(one["id"])
    acts = [ui.log_link(one["id"], words.both(lang, "link.log"), back)]
    if str(one["state"]) == run_mod.RUNNING:
        acts.append(f'<form method="post" action="/api/runs/{ident}/cancel">'
                    f'<button class="btn sm">{words.both(lang, "js.cancel")}</button>'
                    f"</form>")
    return f'<span class="cell-actions">{"".join(acts)}</span>'


def _commands_panel(view, build_id: str) -> str:
    """The three commands a reader starts from one copy's page.

    `pull` re-checks the sizes and appends an act to the record above; `run` runs the tests
    this copy has no record for - which is the ledger panel's missing half; `re-run` runs
    them again whatever the ledger says, which is the button the `--redo` flag in
    `table.py`'s own parser had been waiting for (`actions._switch` sends it).  All three
    are handed the one id this route names, and the argv under each button is the command
    it will run, from `command()` through `_argv_of`, so the printed line and the process
    cannot disagree.

    **The pairs are this page's test, or all three.**  `?test=<test>` is what a verdict
    pill on `/` links here with (`_ran_cell`), and the history panel above a page that
    carries it is about that one pair - so a run button that ran all three would be
    answering a wider question than the page it stands on.  With no `?test=` the page is
    about the copy and all three are what "run" means here; `forms._tests_of` is that
    rule already spelled once, and it is the same one `/jobs` draws rows by.

    `pull` ticks the build and the two run buttons tick their **pairs**, because that is
    what each command takes: `table.py run` reads `--pair <build_id>:<test>`
    (`actions.command`), so this page names the tests itself rather than sending a bare
    id the child would refuse.  Naming them is not a second opinion about which tests to
    run - whether each pair actually runs is still the ledger's answer inside that
    command, which is what the pending button's label says it does and what the re-run
    button's `--redo` is the way past - so the two labels have to say which of them
    ignores the ledger, and `correspondence.redo_hint` beside the second is where they do.
    """
    lang, check = view.lang, view.check
    fields = [("selected", build_id), ("api", check.api)]
    pairs = [f"{build_id}:{test}" for test in _tests_of(check)]
    return ui.panel(
        "page.correspondence.commands_title",
        ui.action_form("pull", words.both(lang, "btn.pull_recheck"), fields=fields,
                       argv=view.gui._argv_of("pull", {"selected": build_id}, lang,
                                              api=check.api),
                       hint="correspondence.pull_hint", lang=lang)
        + ui.action_form("run", words.both(lang, "btn.run_pending"),
                         fields=[("selected", one) for one in pairs]
                         + [("api", check.api)],
                         argv=view.gui._argv_of("run", {"selected": pairs}, lang,
                                                api=check.api),
                         lang=lang)
        # The same action and the same pairs, one field more: `redo` is the tick
        # `actions._switch` reads, and it is the only difference between this form and
        # the one above it - which is why the two printed lines differ by `--redo` and
        # by nothing else.
        + ui.action_form("run", words.both(lang, "btn.run_redo"),
                         fields=[("selected", one) for one in pairs]
                         + [("api", check.api), ("redo", "1")],
                         argv=view.gui._argv_of("run", {"selected": pairs, "redo": "1"},
                                                lang, api=check.api),
                         hint="correspondence.redo_hint", lang=lang),
        lang=lang)


# --------------------------------------------------- one pair's run history
def _run_rows(build_id: str, test: str) -> list:
    """Every console `var/logs/` holds for one pair, newest first.

    **This is the whole of the run history**, and it is read off the file names
    because there is nowhere else to read it: `lib/job.py` writes
    `<build>.<test>.<stamp>.log` per run, while `var/results/<build>/<test>.json` is
    one file per pair that every run rewrites.  So the ledger's count for a pair is
    one whatever happened, and a pair run thirteen times is thirteen lines here.

    The stamp is the run's UTC start (`kbuild._stamp()`), so ordering by it is
    ordering by when the run began, and it sorts as text - the one spelling this tree
    writes deliberately compares as a string.

    Both halves of the name are escaped before the wildcard is added: a build id or a
    test name carrying one of the pattern's own characters can then only ever match
    itself, and a pattern that leaked into the next field would list one pair's runs
    under another pair's heading.
    """
    pattern = layout.logs(f"{glob.escape(build_id)}.{glob.escape(test)}.*.log")
    found = [{"file": os.path.basename(one), "path": one} for one in glob.glob(pattern)]
    for one in found:
        one["stamp"] = _run_stamp(one["file"])
    return sorted(found, key=lambda one: one["stamp"], reverse=True)


def _run_stamp(name: str) -> str:
    """The run's start, read out of its console's own file name.

    The name is `<build>.<test>.<stamp>.log`, and the stamp - the field before
    `.log` - is it.  `rsplit` and not a split: a build id and a test name may each
    carry dots of their own, and the stamp never does, so the last field is the right
    one whatever the other two look like.
    """
    return name[: -len(".log")].rsplit(".", 1)[-1]


def _record_for(view, build_id: str, test: str):
    """The ledger's surviving record for one pair, or `None`.

    `view.gui._state()` is the one `Records` this request has already read (`data.rows`
    calls it too, and it is memoised for the request), so this join costs no second walk
    of `var/results/`.  `rows["ledger"]` cannot answer it: that dict carries the six
    fields the ledger panel draws and not the record's `log`, which is the join key.
    """
    _, records = view.gui._state()
    return records.last(test, build_id)


def _ledger_run(record, runs: list) -> str:
    """Which of these runs the surviving record is about, by the console it names.

    The record names the console it kept (`Outcome.log`, an absolute path under
    `var/logs/`) and that file was written by exactly one run, so the file name is the
    join and the record's own `log` field is what decides it.

    A record that names no console at all is matched on its `timestamp` instead, and
    not left to read as "never recorded": `Job._keep_console` answers `""` when a run
    printed nothing, and that stamp is the same `started` string the file name was
    built from (`Job.run`), so the row is still findable.  A record that matches
    neither is named in the panel's own line rather than hidden (`_run_history_panel`).
    """
    if record is None:
        return ""
    named = os.path.basename(str(record.log or ""))
    for one in runs:
        if named and one["file"] == named:
            return one["file"]
    stamp = str(record.timestamp or "")
    for one in runs:
        if stamp and one["stamp"] == stamp:
            return one["file"]
    return ""


def _runs_records(records: list, runs: list) -> dict:
    """The ledger's records of one pair, keyed by the console of the run each one is about.

    `_ledger_run` is the one join between a record and a run, and this is it applied to
    every record the pair has rather than to the surviving one alone - the history's
    whole purpose, and the reason it is written in the same shape (`sink._same_run`).

    Oldest first, so the **newest** record of a run wins when two of them name it: the
    write is idempotent, so that is a file written by an older version of this tree or
    edited by hand, and the later line is the one that was there when the reader looked.

    A record that joins to no console is left out, and it is left out on purpose: the
    rows of this table are the runs `var/logs/` holds, so a record with no console is a
    fact about the ledger rather than a row here - the caller counts those and says so
    underneath (`_run_history_panel`).
    """
    found: dict[str, object] = {}
    for one in records:
        name = _ledger_run(one, runs)
        if name:
            found[name] = one
    return found


def _run_row(one: dict, record, ledger: bool, kept: bool = False) -> dict:
    """One run as a table row: the file's own facts, plus its own record's where there is one.

    `record` is the record this run left - out of the pair's history, or the surviving
    `<test>.json` for the run that one is about - and `None` for a run that left none.
    That is the whole join, and it is done here rather than in a cell so that "which
    fields are empty and why" is decided once.  The three fields the record can add are
    the three a file name cannot say: what the run came back with, what it exited with,
    and who ran it.

    `kept` is not `record is not None`: it says this run's record is the *surviving*
    one, which is the whole of the difference between the two sentences for a run that
    has a record - every other page reads the surviving record and nothing else
    (`Ledger.read`).

    `ledger` is not `record is not None` either: it says whether the pair has a record
    at all - the surviving one, or one the history keeps - which is what the fourth
    cell's sentence needs.  An empty cell means one of two different things: the ledger
    holds a later run's record instead of this run's, or there is no record of this pair
    to hold, and `_kept_cell` may not guess which.
    """
    return {"file": one["file"], "stamp": one["stamp"],
            "kept": kept and record is not None, "recorded": record is not None,
            "ledger": ledger,
            "verdict": record.verdict if record is not None else "",
            "exit": record.exit_code if record is not None else None,
            "source": record.source if record is not None else ""}


def _run_history_panel(view, build_id: str, test: str) -> str:
    """Every run of one (build, test) pair, newest first, each with its own record.

    **The panel exists because the number on `/` was the wrong unit.**  A pair can be
    run many times and the ledger keeps one *current* record for it, so nothing a
    `Ledger.read` returns can say how often - the consoles in `var/logs/` can, and this
    is them.

    **Every row now carries its own run's record**, because the ledger keeps them
    (`Ledger.history`): the pair's history is joined to the rows by the same rule the
    surviving record is (`_runs_records`), so a run a later one replaced is a row with
    its own verdict, exit code and source instead of three dashes.  The surviving record
    still wins for the row it is about, so the newest row reads exactly as it did.

    A row that joins to no record says which of the two silences it is: the pair's
    ledger holds other runs and not this one, or it holds none at all.  And a pair with
    **no** record anywhere is a third fact, not a second: a run whose console exists
    while its record does not is the run this tree went out of its way to make
    diagnosable (`Job.run` - `_InFlight` opens the log before tuxrun starts, so a run
    killed mid-flight leaves a console and no record), and a single interrupted run of a
    pair would otherwise have this panel say a later run overwrote a record that was
    never written.

    Two lines underneath are about records rather than runs, and they are lines and not
    rows because a record with no console has no console to link and no start stamp to
    print: `page.history.record_not_here` for the surviving record's own console, and
    `page.history.records_no_console` for the history's.  The second is the one the
    history makes possible - `var/logs/` is pruned and `var/results/` is not, so a pair
    can have more runs in the ledger than it has consoles left - and a reader looking at
    five rows and a history of nine has to be told which four are missing rather than
    left to count.

    The sub-line names the directory and the two facts it is the whole point of: the
    rows are the log files, and the ledger's record of a pair is one *current* one plus
    its history.
    """
    lang = view.lang
    runs = _run_rows(build_id, test)
    records = Ledger.history(build_id, test)
    record = _record_for(view, build_id, test)
    kept = _ledger_run(record, runs)
    shown = _runs_records(records, runs)
    if kept and record is not None:
        # The surviving record is what every other page reads, so it is what this row
        # shows even in the one case where the history's newest line disagrees with it.
        shown[kept] = record
    rows = [_run_row(one, shown.get(one["file"]), kept=one["file"] == kept,
                     ledger=record is not None or bool(records)) for one in runs]
    cols = (
        ui.Col("col.when", kind="n",
               draw=lambda one: ui.stamp(one["stamp"], view.check.tz, seconds=True)),
        ui.Col("col.verdict", kind="c",
               draw=lambda one: (ui.pill(one["verdict"], lang=lang)
                                 if one["verdict"] else ui.DASH)),
        ui.Col("col.exit", kind="n", field="exit"),
        ui.Col("col.source", kind="c",
               draw=lambda one: (ui.pill(one["source"], tone_override="info", lang=lang)
                                 if one["source"] else ui.DASH)),
        ui.Col("page.history.col_record", kind="wrapc",
               draw=lambda one: _kept_cell(one, lang)),
        ui.Col("page.history.col_log", kind="wrapc",
               draw=lambda one: _console_cell(one, lang)),
    )
    body = ui.table(cols, rows, lang=lang,
                    empty=t(lang, "page.history.empty", dir=ui.code(layout.logs())))
    if runs and record is not None and not kept:
        body += ui.hint(t(lang, "page.history.record_not_here",
                          dir=ui.code(layout.logs())))
    # A history record whose console is not among the rows: joined by the same rule the
    # rows are (`_runs_records`), so what is left over here is exactly the records that
    # name a console `var/logs/` no longer has.
    orphaned = len([one for one in records if not _ledger_run(one, runs)])
    if orphaned:
        body += ui.hint(t(lang, "page.history.records_no_console", n=orphaned,
                          dir=ui.code(layout.logs())))
    return ui.panel("page.history.title", body, flush=True, lang=lang,
                    sub=t(lang, "page.history.sub", test=test,
                          dir=ui.code(layout.logs())))


def _kept_cell(one, lang: str) -> str:
    """Which of the four things happened to this run's record.

    One of four sentences and no fifth: this run's record is the surviving one, its
    record is in the history and a later run's is the surviving one, a later run
    overwrote its record and nothing kept it, or the pair has no record at all.

    The second sentence is new with the history, and it is not the third under another
    name: a run the history still holds is a run whose verdict the three cells above
    still print (`_run_row`), while the third is a run whose record is nowhere - the
    ledger written before this tree kept histories, or one whose history file was
    removed - and only the second of those is something a reader can go and read.

    The fourth is not folded into the third because the third names a run that did
    something, and when the pair was never recorded there is no such run to name.  A
    dash here would be a question the reader cannot answer from this panel.
    """
    if one["kept"]:
        key = "page.history.kept"
    elif one["recorded"]:
        key = "page.history.in_history"
    else:
        key = "page.history.overwritten" if one["ledger"] else "page.history.unrecorded"
    return words.both(lang, key)


def _console_cell(one, lang: str) -> str:
    """This run's console: the archived file's own name, linked to the text it is.

    The link's text is the file name and not a word like "log": the name is where the
    run's own identity is written down (`<build>.<test>.<stamp>.log`), and a reader
    comparing two consoles wants to know which file they are reading.  It opens in a
    tab of its own, like every other log link on this console (`ui.log_link`), so the
    history stays where it was.
    """
    name = str(one["file"])
    href = "/logs/" + urllib.parse.quote(name, safe="")
    why = words.attr(lang, "title", "page.history.open", file=name)
    return (f'<a href="{ui.esc(href)}" target="_blank" rel="noopener" {why}>'
            f'{ui.code(name)}</a>')
