# SPDX-License-Identifier: LGPL-2.1-or-later
"""The design's components: one function per thing a screen is made of.

A page module reads like a list of these - `filters(...)`, `table(...)`,
`pill(...)`, `panel(...)` - and writes no tag of its own except inside a cell
renderer, which is where a cell's own markup belongs.  Every class emitted here is
one `style.py` already styles, or one `shell.BRIDGE_CSS` does for the handful of
names the page's script owns (`shell.py` lists them and says why).  The rules this
file exists to hold:

* **A state is a pill and a pill is a table lookup.**  `STATE["incomplete"]` is
  `warn`, in one place, so the same word is the same colour on all five screens.
  A word nobody has taught this file is `idle`, which is the honest colour for it.
* **A table's header and its cells come from the same `Col` list**, so an alignment
  can never disagree with its column.  A `Col` with no `draw` reads its row by
  `field` (or by `key`); a column that has neither raises while the page is drawn.
  The prototype read cells by the *header's word* - which is translated markup - so
  three of its columns printed an empty cell in every row and nothing said so.
  A cell whose value is `None` prints the design's dash: "nothing there" is an
  answer, and a field that is not in the row at all is a bug.
* **Numbers are right-aligned, ids and command lines are monospace, an argv
  truncates with its whole value in the `title=`.**  The alignment is `kind="n"` on
  the `Col` and nowhere else.
* **A control that cannot be used says why**, in its `title=`, instead of being
  drawn grey with no reason, and a select-all box is drawn `hidden` until the script
  that wires it unhides it.
* **No visible word is written here.**  A label, a heading and a `title=` all come
  from `lib/i18n` through `words.both()` / `words.t()`; a component that took an
  English string would be the second place this console spells its own name.

**Two languages, four modes, and the visible one is the response's.**  Every word here
is `words.both()` (an element's own words) or `words.attr()` (`title`, `aria-label`,
`placeholder`), and the column the server writes is the one this response is drawn in;
the other rides in the attribute for the swap.  Both halves matter: a page whose
*visible* column is always English is a page whose Chinese half no check ever sees
(`accept.py`'s W1/W3 read the served body), so every translation would be unverifiable
dead weight.

`lang` is therefore a parameter of every component that writes a word, and it is
**required and keyword-only**: a default would hide the day one is forgotten, and the
reader who asked for Chinese would meet English with nothing on the page to say so.  A
missed one is a `TypeError` while the page is being written.  `end_word()` is the
exception that proves the point - its cell is the one the shipped script rewrites every
two seconds from an `I18N` built for this response - so it takes the language as its own
third argument.

A parameter that becomes an attribute takes **either a catalogue key or a literal**: a
key is rendered with `words.attr()`, and a literal is escaped as the data it is (a
path, a build id, an argv).  The rule is `word()`'s, applied to attributes, so a page
never has to remember which of the two a component wanted - and a
`checkbox(disabled_reason="jobs.why_disabled")` cannot silently ship an English-only
tooltip.
"""

import html
import json
import urllib.parse

from ... import errors
from ...i18n import CATALOGUE, DEFAULT_LANG, t
from .. import values
from ..schema import DEFAULT_TZ, _labels, state_keys
from . import words
from .words import _KEY_SHAPE, both


# --------------------------------------------------------------- the escapes
def esc(text) -> str:
    """A value from the data, escaped.  Never a translated string - those carry markup."""
    return html.escape("" if text is None else str(text))


DASH = '<span class="dash">&mdash;</span>'


def _attr(lang: str, kind: str, value: str, **fmt) -> str:
    """One attribute, translated when the value names a catalogue key.

    A key becomes the design's own pair (`title="…" data-i18n="title" data-en=…
    data-zh=…`); anything else is data - a path, a build id, an argv - and is escaped
    as the literal it is.  The test is `word()`'s, so the two readers of "is this a key
    or a value" are one rule rather than two.
    """
    if not value:
        return ""
    if value in CATALOGUE:
        return words.attr(lang, kind, value, **fmt)
    # A key-shaped string that names no row is a typo, and an untranslated tooltip is
    # invisible - nobody reads a page twice to find the English one.  Everything else
    # is data (a path, a build id, a sentence), which is what a `title=` usually is.
    if _KEY_SHAPE.match(value):
        raise ValueError(f"{value!r} is shaped like a catalogue key and is not one")
    return f'{kind}="{esc(value)}"'


def word(text, *, lang: str) -> str:
    """A word as markup, whichever of the three shapes the caller had.

    A catalogue key renders in both languages, markup passes through as it stands
    (it is a `words.both()` span or a cell the page built), and anything else is a
    value from the data and is escaped.  This is the one place the three are told
    apart, so a caller may pass `"word.id"`, `both("word.id")` or a build id to the
    same argument - and a page that passes a key where it meant markup gets a
    header it can read instead of the string `word.id` on screen.
    """
    if isinstance(text, str) and text in CATALOGUE:
        return both(lang, text)
    if isinstance(text, str) and "<" in text:
        return text
    return esc(text)


def code(text, href: str = "", title: str = "") -> str:
    """A build id, a path or a command: monospace, and a link when there is one."""
    attr = f' title="{esc(title)}"' if title else ""
    body = f"<code{attr}>{esc(text)}</code>"
    if href:
        return f'<a href="{esc(href)}">{body}</a>'
    return body


def q(text, title: str = "") -> str:
    """The design's muted monospace line: an argv, a query, a path beside a label."""
    attr = f' title="{esc(title)}"' if title else ""
    return f'<span class="q"{attr}>{esc(text)}</span>'


def num(text) -> str:
    """A number that is not a cell of its own.  A whole numeric *column* is `kind="n"`."""
    return f'<span class="num">{esc(text)}</span>'


def duration(seconds) -> str:
    """Seconds as the live panel prints them: `1m06s`, `28s`, `0s`.

    A unit and not a sentence, so it needs no translation and no plural rule - and
    its shape has to be the script's own `liveTime()`, which rewrites this same cell
    every two seconds: the two disagreeing would make a row's elapsed time change
    spelling the moment the poll touched it.
    """
    whole = max(0, round(float(seconds or 0)))
    return f"{whole // 60}m{whole % 60:02d}s" if whole >= 60 else f"{whole}s"


# --------------------------------------------------------------- the states
# The one place a word becomes a colour.  A word not here is `idle`, which is the
# honest colour for a state nobody has taught this file about yet, and `plain` is the
# design's own tone for a code-form value that is neither good nor bad (a kind, a
# count) - passed as `tone_override` where a page wants it.
#
# Every word the *script* can print is in this map too, and in the tone the design
# gives it: the board draws `running` as `info`, `done` as `ok`, `failed` as `bad`,
# `incomplete` as `warn` and `available` as `info`, and `shell.BRIDGE_CSS` colours the
# script's own class vocabulary by this same grouping.  A pill that was one colour when
# the server drew it and another after the poll redrew it would be the panel changing
# shape under the reader - the one thing the two row shapes may not do.
STATE = {
    "pass": "ok", "ok": "ok", "done": "ok", "whole": "ok", "ready": "ok",
    "yes": "ok", "run": "ok", "resident": "ok", "pulled": "ok",
    "fail": "bad", "failed": "bad", "error": "bad", "absent": "bad", "no": "bad",
    "incomplete": "warn", "warn": "warn", "partial": "warn", "not whole": "warn",
    "unrecorded": "warn", "reserved": "warn", "closing": "warn",
    "running": "info", "info": "info", "available": "info", "registered": "info",
    "idle": "idle", "missing": "idle", "card only": "idle", "cancel": "idle",
    "cancelled": "idle", "empty": "idle", "none": "idle", "bytes": "idle",
    "made-here": "idle",
    # The design's own tone words read as themselves, so a value that already *is* a
    # tone (a cell whose word is `bad`, a caller that put a tone's name where a
    # record's value belongs) is not silently drawn as `idle`.
    "bad": "bad", "plain": "plain",
}


def tone(one) -> str:
    """The tone a state word is drawn in, or `idle` for one nobody has taught it."""
    return STATE.get(str(one or "").strip().lower(), "idle")


def end_word(state: str, exit_code: "int | None", lang: str = DEFAULT_LANG) -> str:
    """What an activity's pill *says*: the exit code's word, not the state's.

    `Run._settle` (`lib/run.py`) collapses exit 1 and exit 3 onto the one state
    `failed`, and that is right for the *activity* - the process failed either way.  It
    is not the tests' verdict: `lib/errors.py` defines 0 = pass, 1 = a test failed and
    3 = infrastructure (*incomplete*, no verdict was reached), so a pill that printed
    the state called a run which finished every test it started and failed some of them
    "failed" - the very word it prints for a command that crashed.  The class stays the
    state's (the stylesheet colours one ending one way, and the state filter box offers
    the four states), and only the word is the code's.

    A cancelled activity keeps its own word whatever the code - `Run.cancel` leaves
    `0`/`-15` behind and the reader, not the tests, ended it - and so does any ending
    whose code is outside those three: the pill then says what is on disk, which is
    what the live panel's `exit code not seen` rule already does for a code nobody saw
    (`07-shell.md` §A3).

    `_js()` builds the script's `I18N.end_word` map out of this function
    (`script.py`), so the poll writes this same word into the same cell: this is the one
    owner of the word both writers print, and a second copy would make a pill change its
    word the moment the page refreshed.
    """
    if state == "cancelled":
        return t(lang, "run_state.label.cancelled")
    if exit_code == errors.EXIT_PASS:
        return t(lang, "run_state.label.done")
    if exit_code == errors.EXIT_TEST_FAIL:
        return t(lang, "run_end.tests_failed")
    if exit_code == errors.EXIT_INFRA:
        return t(lang, "run_end.infra")
    return _labels("run_state", lang).get(state, str(state))


def pill(one, n=None, tone_override: str = "", label: str = "", *, lang: str) -> str:
    """One state as a dot and a word.  `n` rides inside the same pill.

    The class is the tone of `one` - the *record's* value (`pass`, `running`,
    `available`) - and never of the word printed inside it, because the record's
    vocabulary is what names a state: an activity's pill is coloured by its state
    whatever its exit code turns out to mean.  `label` is that other word, for the
    case where they legitimately differ (`end_word()`), and `n` is a count that
    belongs to the same fact.
    """
    body = word(label or one, lang=lang)
    if n is not None:
        body += f' <span class="n">{esc(n)}</span>'
    return f'<span class="pill {tone_override or tone(one)}">{body}</span>'


def tick(ok, off: str = "&mdash;", label_html: str = "", *, lang: str) -> str:
    """A check on a field: a glyph, not a sentence.

    The artifacts of a build are asked about one per column, and a pill with the
    word "kernel" in it three times is three columns of noise when the header
    already says which artifact it is.  `label_html` is the design's own shape for
    the same cell - a green word - for the place a glyph would need a legend.
    """
    if label_html:
        return f'<span class="{"tick" if ok else "cross"}">{label_html}</span>'
    if ok:
        return f'<span class="tick" {words.attr(lang, "title", "col.on_disk")}>&#10003;</span>'
    if ok is False:
        return f'<span class="cross" {words.attr(lang, "title", "state.not_here")}>&#10007;</span>'
    return f'<span class="dash">{off}</span>'


def flag(one, *, lang: str) -> str:
    """A yes/no cell as a small boxed glyph, for a column read at a glance."""
    if one is True:
        return f'<span class="flag on" {words.attr(lang, "title", "state.yes")}>&#10003;</span>'
    if one is False:
        return f'<span class="flag no" {words.attr(lang, "title", "state.no")}>&#10007;</span>'
    return f'<span class="flag" {words.attr(lang, "title", "state.unknown")}>?</span>'


def stamp(value, tz: str = DEFAULT_TZ, seconds: bool = False) -> str:
    """A record's stored UTC stamp as the design's two-tone cell, in the reader's clock.

    Split rather than reprinted: the day in the cell's ink, the clock muted beside it, and
    the text on screen made of the value on disk rather than of a second spelling of it
    (`05-i18n-prose`'s rule for a child process's own words).  An empty stamp is the
    design's dash, because a record with no timestamp is not a record at midnight, and a
    stamp nobody can parse is printed as it stands for the same reason.

    **The trailing `Z` is not printed, and that is this cell's whole rule.**  Every stamp
    on this disk is UTC (`lib/kbuild.py`'s `_stamp`) and `tz` is the *reader's* clock: a
    `Z` beside a converted time is a claim about a clock the value is no longer in -
    `09:05Z` in Asia/Shanghai is not 09:05 UTC - so the letter goes and the raw stored
    value takes its place in the `title=`.  **That is what makes dropping it safe**:
    nothing is lost, only the misleading letter, and a reader who needs the UTC the file
    actually holds has it one hover away.  The `title=` is written only when the two
    differ, because a stamp the reader's clock leaves alone needs no second spelling of
    itself in a tooltip.

    **This is one cell and it used to be three.**  `jobs._stamp` printed the `Z` and the
    full clock, `builds._stamp` printed it only on the seconds' spelling, and
    `worker._stamp` printed neither and carried the title - three pages a reader switches
    between in one sitting, disagreeing exactly where it costs something: with the
    console's clock set to anything but UTC, two pages called one stored value two
    different things.  `seconds` is the one difference that was ever real - a build's
    `created` reads to the minute, a pull act's stamp keeps its seconds because that is
    what tells two attempts of one build apart (`jobs` keeps them for the same reason) -
    and it is the *reader's precision*, not the clock's.
    """
    whole = str(value or "")
    if not whole:
        return DASH
    shown = values._in_clock(whole, tz, "%Y-%m-%dT%H:%M:%S")
    day, _sep, rest = shown.partition("T")
    if not rest:
        return f'<span class="nowrap">{esc(day)}</span>'
    clock = rest.rstrip("Z")[:8 if seconds else 5]
    if not clock:
        return f'<span class="nowrap">{esc(day)}</span>'
    title = f' title="{esc(whole)}"' if shown != whole else ""
    return (f'<span class="nowrap"{title}>{esc(day)} '
            f'<span class="muted">{esc(clock)}</span></span>')


def delta(pair, first: bool = False, last: bool = False, *, lang: str) -> str:
    """A config comparison as three signed numbers, or the reason there is none.

    `+a -r ~c` is added / removed / changed.  A row whose pair was not read says
    *why*: "the first row in this order" is a fact about the order and not a missing
    measurement, and a dash for both would hide the difference between them.
    """
    if pair is None:
        if first:
            return f'<span class="muted">{both(lang, "analysis.first_row")}</span>'
        if last:
            return f'<span class="muted">{both(lang, "analysis.last_row")}</span>'
        return f'<span class="dash" {words.attr(lang, "title", "analysis.not_compared")}>&mdash;</span>'
    added, removed, changed = pair
    return ('<span class="delta">'
            f'<span class="plus">+{esc(added)}</span>'
            f'<span class="minus">&minus;{esc(removed)}</span>'
            f'<span class="same">~{esc(changed)}</span></span>')


def spark(marks, *, lang: str) -> str:
    """A run of records as squares; `None` is a position with no record.

    The square's colour is the verdict's tone, and its `title=` is the verdict
    itself - a gap is titled as a gap, because "no record" is a fact about the
    ledger and a blank square with no tooltip reads as a rendering fault.
    """
    out = []
    for one in marks:
        # An empty square says *why* in its own tooltip: a gap is a fact about the
        # ledger, and a blank square with nothing on it reads as a rendering fault.
        attr = (_attr(lang, "title", one) if one
                else words.attr(lang, "title", "analysis.no_record"))
        out.append(f'<i class="{tone(one) if one else ""}" {attr}></i>')
    return f'<span class="spark">{"".join(out)}</span>'


def test_bars(regions) -> str:
    """One region per test, and inside a region one line per build: pass, fail, no answer.

    A region is `{test, ok, bad, warn, bars}`, as `data._test_bars` produces it: its
    heading is the test's own name and **its totals over the window**, its lines are
    what those totals are the sum of.  One list of builds read once per test, so the
    reader compares a build's `boot` with its own `kselftest-kvm` by reading the same
    line of two regions - which is the whole reason the panel draws three of them.

    **Every line's three counts are drawn, in the design's own order**, so the columns
    line up from line to line and region to region and a reader can scan down the `bad`
    column instead of reading three numbers per row.  A count of zero is left in the
    muted tone an `<i>` with no colour class gets; a non-zero one wears its segment's
    colour, so the number and the segment are one fact in two shapes.

    **A row with nothing recorded gets an empty track and a dash.**  A track of width
    zero would read as "everything failed", which is the opposite of what a missing
    record says - so the segments are drawn only for the counts that are there (all
    three zero draws no `<i>` at all, and the track is the sunken plate), and the
    numbers are the design's dash rather than three zeros.  That is also what a region
    whose test ran for none of this window's builds looks like: a heading, a dash, and
    a line per build saying the same thing.
    """
    out = []
    for region in regions:
        counts = _bar_counts(region)
        lines = "".join(_bar_line(one) for one in region.get("bars") or ())
        out.append(f'<div class="region"><div class="rhead">'
                   f'<span class="rt">{esc(region.get("test") or "")}</span>'
                   f'<span class="rn">{_bar_nums(counts)}</span></div>'
                   f'<div class="bars">{lines}</div></div>')
    return f'<div class="regions">{"".join(out)}</div>'


def _bar_counts(row) -> list:
    """A row's three counts as `(segment class, number)`, in the order they are drawn.

    The class is the ledger's own word for the answer (`ok`, `bad`, `warn`) and not a
    colour: `style.py` is where a word becomes a colour, and a second table here would
    be the place the two drifted.  A missing key is zero - a row that never recorded
    anything and a row that recorded three failures are not the same row, and only one
    of them is absent from the tally.
    """
    return [(cls, int(row.get(cls) or 0)) for cls in ("ok", "bad", "warn")]


def _bar_line(row) -> str:
    """One build's line: its id, its three segments, its three numbers."""
    build = str(row.get("build_id") or "")
    counts = _bar_counts(row)
    total = sum(n for _cls, n in counts) or 1
    segments = "".join(f'<i class="{cls}" style="width:{n / total * 100:.2f}%"></i>'
                       for cls, n in counts if n)
    return (f'<div class="bar"><span class="bt" title="{esc(build)}">'
            f"{esc(build[:16])}&hellip;</span>"
            f'<span class="track">{segments}</span>'
            f'<span class="bn">{_bar_nums(counts)}</span></div>')


def _bar_nums(counts) -> str:
    """Three counts as the line's numbers, or the design's dash for none at all.

    `&mdash;` is the answer for a build with no record and for a region whose test has
    none: zero records and zero passes are different facts about the ledger, and only
    one of them is a zero.
    """
    if not any(n for _cls, n in counts):
        return DASH
    return "".join(f'<i class="{cls}">{n}</i>' if n else f"<i>{n}</i>"
                   for cls, n in counts)


# --------------------------------------------------------------- the charts
# The design's own geometry, in the board's own numbers: a 1180-wide viewBox, the plot
# from x=54 to x=1128 and from y=16 (100%) to y=204 (0%), a dashed line every 25%, and
# the order's two ends named under the axis.  Keeping the board's numbers rather than
# choosing new ones is what makes a chart here look like the chart there.
#
# **The height is the one number the board never had to fix, and the operator asked for
# it twice** (「趋势图重画得更大更好看」).  The board drew one test; this chart draws up to
# five, and dividing its own 188 of plot by five leaves 32.8 per band - two numbers 33
# apart and a slope with nowhere to go.  So the plot is a **sum of bands**, with the
# board's own 188 as its floor rather than its ceiling:
#
#     plot = max(CHART_BOTTOM - CHART_TOP,
#                bands * CHART_BAND + (bands - 1) * CHART_LANE_GAP)
#
# One test is therefore drawn exactly where the board drew it (1180x226, unchanged), and
# every further test makes the picture **taller instead of thinner**: three tests come
# out 1180x382 and five 1180x622, each band a full 104 of plot.  `.chart` is
# `width: 100%`, so the height a reader gets is this number over 1180 times the panel's
# width - the chart grows with its own content and never with the room it is given.
CHART_W = 1180
# The plot's own left and right.  `CHART_LEFT` is now the **narrowest** the name column
# may be rather than where the plot always starts: a band's name is drawn in that column
# and the plot begins where the column ends (`_gutter`).
CHART_LEFT, CHART_RIGHT = 54, 1128
# 100% and 0% of the board's own one-band plot.
CHART_TOP, CHART_BOTTOM = 16, 204
CHART_BAND = 104                  # one band of a chart that has several
CHART_LANE_GAP = 16               # between two plates: more than 2 * the plate's margin
CHART_PLATE_PAD = 6               # above a band's 100% and below its 0%
CHART_FOOT = 22                   # under the axis: the two ends' names (the board's own)
CHART_GUTTER_MAX = 190            # the name column's ceiling, for a very long name
CHART_CHAR = 6.0                  # one character of `.chart text` at 10px mono
CHART_STEPS = (0, 25, 50, 75, 100)   # the board's own grid, which one band can carry
CHART_TICKS = (0, 50, 100)           # and the three lines a band of many can
CHART_LABELS = (0, 100)              # the two of them a reader is given a number for
# The five series colours the stylesheet already has.  A sixth test reuses the
# first: the design has five, and the legend beside the chart is what names them.
SERIES = ("--s1", "--s2", "--s3", "--s4", "--s5")


def line_chart(series, slots: int = 0, ends=("", ""), caption: str = "",
               nothing: str = "", *, point: str = "chart.point", lang: str) -> str:
    """One line per test across the positions of the order, as the board draws it.

    `series` is the page's `series` rows - one per test, each with `test`, `points`
    (the `{at, pct}` pairs the line is drawn through), and the axis every row shares
    as `slots` and `ends` - and it is handed straight through from the data layer.
    A page that built its own list may pass `(test, [(at, pct)])` instead, and with
    neither `slots` nor `ends` given the axis is read off the first row: an axis is
    one thing, so nothing here asks for it twice.

    The x axis is **the order**, never time, and a position a test has no record for
    is left out of its line rather than drawn at zero or carried forward: a gap is
    not a failure, and it is the same gap the timeline prints as an empty square.
    That is why the caller passes points and not a fixed-length series.

    This is the one component here that is not a table, and the reason is the
    operator's question - "is this getting better or worse" is answered by five lines
    over 24 builds at a glance where 120 cells are not.  Every number it draws is in
    the table above it as well: the chart is a second reading of one answer, never a
    second answer.

    **One band per test, and that is what makes a line readable.**  The first cut drew
    every test through the board's one 0..100% axis, and the operator reported what
    that has to produce: 「这些线条虽然有颜色但还是会重合」 - five tests at 100% are one
    line drawn five times, and the only colour a reader sees is the last one drawn.  A
    colour is a name for a line, not a position, so no palette could have fixed it.  A
    band per test gives every line its own 0..100% of the *same* pixel height, so the
    levels and the slopes stay comparable from one test to the next while two lines
    physically cannot meet.  (An offset per line would move the numbers a reader is
    reading - 100% would stop meaning the top; one chart per test would lose the one
    thing the panel is for, the tests *against each other*.)

    **A band is drawn as what it is now: a plate.**  It was invisible until this
    component was redrawn - a line over white, with the test's name printed *inside*
    the plot at x=58, which is over the gridlines and over the line itself (this
    docstring used to admit it: "a line crosses a letter rather than a letter crossing
    a line").  Each band is now a `--raised` card running the full width of the
    picture, its name in a column of its own to the left of the plot, and the grid,
    the fill and the line drawn on top of the card.  Three things came out of that one
    change and they are why it is worth the markup:

    * **the name is never over the plot.**  It has a column, and the column is exactly
      as wide as the longest name this chart was handed and no wider (`_gutter`), so
      the plot loses the least it can.  The full name is still in the band's `<title>`:
      the column has a ceiling, and a test whose name is past it is cut with a `…`
      rather than allowed to run over its own line;
    * **the numbers a band carries are its two ends.**  They used to hang on a fixed
      x=45, the middle of a 54-wide margin the board chose before it knew any name, and
      how many there were depended on how many tests were asked for: a chart of one
      printed all five of the board's steps (`0% 25% 50% 75% 100%`) while a chart of
      several printed two, so one picture and another disagreed about what its own
      grid meant.  Every band is now given the same two - its 0% and its 100%, at the
      right edge of the name column, against the plot they label.  The steps between
      them are the grid with nothing written on it, and the number a reader wants off
      this axis is which of their tests sits high in its band, which is a line and not
      a label; the exact percentage is on the marker's own tooltip (`chart.point`);
    * **a line has weight.**  The run's own points are closed down to its band's 0% as
      a filled `--sN` area at 14%, with the 2-wide stroke and the markers over it.  The
      fill is what makes a curve legible from across the room; the stroke alone, at
      1.7 over a 1180-unit viewBox, is a hairline on any window wider than the board's.

    The name in the column carries its band's colour, which is the one thing the legend
    above cannot say: *this* card is `kselftest-kvm`.  It is an inline `style` and not a
    presentation attribute because `.chart text` is a rule and a rule beats an
    attribute - the reason `fill="var(--s1)"` on a `<polyline>` works and on a `<text>`
    would silently come out grey.
    """
    rows = _series(series)
    if not rows:
        return chart_none(nothing or both(lang, "empty.no_rows"))
    if not slots or not any(ends):
        axis_slots, axis_ends = _axis(series)
        slots = slots or axis_slots
        ends = ends if any(ends) else axis_ends
    if not slots:                      # no axis given: the rightmost point is the end
        slots = 1 + max((at for _one, points in rows for at, _pct in points), default=0)
    # Which bands exist, and what to call each one.  The band is the **colour slot**
    # (`at % len(SERIES)`) and not the position in this list: `_chart_series` splits a
    # test's line wherever the ledger has a gap, so one test arrives here as several
    # entries - all of them in that test's slot, and all of them belong in its band.  A
    # test with no record anywhere in the window has no entry at all and gets no band.
    bands, named = {}, {}
    for at, (name, points) in enumerate(rows):
        slot = at % len(SERIES)
        if points and slot not in bands:
            bands[slot] = len(bands)
            named[slot] = str(name)
    if not bands:                      # every point list empty: nothing to scale to
        bands = {0: 0}
    count = len(bands)
    # This chart's own geometry, before a single number is placed on it: the plot is
    # the sum of its bands (`CHART_BAND`), the board's own 188 of plot is the floor
    # under it, and the name column is as wide as this chart's names.
    plot = max(CHART_BOTTOM - CHART_TOP,
               count * CHART_BAND + (count - 1) * CHART_LANE_GAP)
    tall = (plot - CHART_LANE_GAP * (count - 1)) / count
    base = CHART_TOP + plot                                    # the axis
    left = _gutter(named.values())
    lanes = sorted(bands.items(), key=lambda one: one[1])
    top_of = {slot: CHART_TOP + lane * (tall + CHART_LANE_GAP) for slot, lane in lanes}
    parts = []
    # The plates first, so that every grid line, area, line, marker and number below is
    # drawn on top of the band it belongs to.
    for slot, _lane in lanes:
        top = top_of[slot]
        parts.append(f'<rect class="band" x="0" y="{top - CHART_PLATE_PAD:.1f}" '
                     f'width="{CHART_W}" '
                     f'height="{tall + 2 * CHART_PLATE_PAD:.1f}" rx="5"></rect>')
    # One test in the order keeps the board's own five-step grid; more than one gets the
    # three lines a band can carry unambiguously (its own 0%, middle and 100%).  The
    # **numbers** are `CHART_LABELS` and not the steps: a band's two ends are what a
    # reader reads off this axis, the lines between them are the grid, and the exact
    # percentage of a point is on that point's own tooltip.
    steps = CHART_STEPS if count == 1 else CHART_TICKS
    for slot, _lane in lanes:
        top, bottom = top_of[slot], top_of[slot] + tall
        for step in steps:
            y = _lane_y(step, top, bottom)
            parts.append(f'<line class="yline" x1="{left:.1f}" y1="{y:.1f}" '
                         f'x2="{CHART_RIGHT}" y2="{y:.1f}"></line>')
            if step in CHART_LABELS:
                parts.append(f'<text x="{left - 10:.1f}" y="{y + 3.4:.1f}" '
                             f'text-anchor="end">{step}%</text>')
    parts.append(f'<line class="axis" x1="{left:.1f}" y1="{base:.1f}" '
                 f'x2="{CHART_RIGHT}" y2="{base:.1f}"></line>')
    span = max(1, int(slots) - 1)
    for at, (name, points) in enumerate(rows):
        # An entry with no points is one of the placeholders `_chart_series` inserts to
        # keep every run of one test in that test's colour: it draws nothing, and it has
        # no band of its own either (`bands` is built from the entries that do).
        if not points:
            continue
        slot = at % len(SERIES)
        colour = SERIES[slot]
        top = top_of[slot]
        placed = [(_x(position / span, left), _lane_y(percent, top, top + tall),
                   position, percent) for position, percent in points]
        # The area first, the line over it, the markers over that: the area is the run's
        # own points closed against its band's 0%, which is a polygon of the same x's
        # with the band's floor as its two ends - a run of one point has no area to fill
        # and gets none.
        if len(placed) > 1:
            parts.append(f'<polygon class="area" fill="var({colour})" points="'
                         + " ".join([f"{x:.1f},{y:.1f}" for x, y, _p, _c in placed]
                                    + [f"{placed[-1][0]:.1f},{top + tall:.1f}",
                                       f"{placed[0][0]:.1f},{top + tall:.1f}"])
                         + '"></polygon>')
        parts.append(f'<polyline fill="none" stroke="var({colour})" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round" points="'
                     + " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in placed)
                     + '"></polyline>')
        for order, (x, y, position, percent) in enumerate(placed):
            # The point's tooltip is a *word* ("position 3") with two numbers beside
            # it, so it carries both columns like every other word here: an SVG
            # `<title>` is an element, and the swap reaches it the same way it reaches
            # a span.  The board prints this sentence on every marker.
            title = both(lang, point, test=name, pct=f"{percent:g}",
                         n=position + 1)
            radius = 3.6 if order == len(placed) - 1 else 2.2
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" '
                         f'fill="var({colour})"><title>{title}</title></circle>')
    # The bands' names last, so a line crosses a letter rather than a letter crossing a
    # line.  Each carries the full test name in its tooltip - and here the tooltip is
    # what makes the `…` honest, because the column has a ceiling and a name past it is
    # cut to fit.
    for slot, _lane in lanes:
        name = named.get(slot, "")
        if name:
            parts.append(f'<text class="bandlbl" x="10" '
                         f'y="{top_of[slot] + tall / 2 + 3.4:.1f}" '
                         f'style="fill:var({SERIES[slot]})">{esc(_fit(name, left))}'
                         f'<title>{esc(name)}</title></text>')
    for name, x, anchor in ((ends[0], left, "start"), (ends[1], CHART_RIGHT, "end")):
        if name:
            parts.append(f'<text class="endlbl" x="{x:.1f}" y="{base + 16:.1f}" '
                         f'text-anchor="{anchor}">{esc(str(name)[:8])}&hellip;</text>')
    return (f'<svg class="chart" viewBox="0 0 {CHART_W} {base + CHART_FOOT:.0f}" '
            f'role="img" {words.attr(lang, "aria-label", "chart.passrate")}>'
            f'{"".join(parts)}</svg>'
            + (f'<div class="chartcap">{caption}</div>' if caption else ""))


def legend(items, *, lang: str) -> str:
    """The chart's key: the colour, the name, the count.

    `items` is the same `series` rows the chart was drawn from, or `(test, runs)`
    pairs - one legend beside one chart, so the two read the same list and the
    colours line up by position.
    """
    out = []
    for at, one in enumerate(items):
        if isinstance(one, dict):
            name, runs = one.get("test", ""), one.get("runs", 0)
        else:
            name, runs = one[0], one[1]
        out.append(f'<span class="lg"><i style="background:var({SERIES[at % len(SERIES)]})">'
                   f"</i><code>{esc(name)}</code>"
                   f'<span class="muted">{both(lang, "chart.runs", n=runs)}</span></span>')
    return f'<div class="legend">{"".join(out)}</div>'


def _series(series) -> list:
    """`series` as `[(test, [(at, percent), ...]), ...]`, from either spelling.

    The data layer's rows carry `test` and `points` (each point `{at, pct}`, with
    the build and the verdict beside them for a tooltip this component does not
    print); a page that built its own list passes `(test, [(at, pct)])`.  One
    reader, so the chart cannot be drawn from one shape and its legend from the
    other.
    """
    rows = []
    for one in series or ():
        if isinstance(one, dict):
            name, points = one.get("test", ""), one.get("points") or ()
        else:
            name, points = one[0], one[1]
        placed = [(point.get("at", 0), point.get("pct", 0)) if isinstance(point, dict)
                  else (point[0], point[1]) for point in points]
        rows.append((name, placed))
    return rows


def _axis(series) -> tuple:
    """The axis the series rows share: `slots`, and the two builds under its ends."""
    for one in series or ():
        if isinstance(one, dict):
            return int(one.get("slots") or 0), tuple(one.get("ends") or ("", ""))
    return 0, ("", "")


def _x(on_axis: float, left: float) -> float:
    """A position on the x axis, in this chart's own geometry.

    `left` is the plot's own left edge, which this chart's names decide (`_gutter`):
    the axis and every line on it have to start where the plot starts, or a band's 0%
    would begin underneath its own name.
    """
    return left + (CHART_RIGHT - left) * max(0.0, min(1.0, on_axis))


def _gutter(names) -> float:
    """How wide the name column has to be, for the names this chart was handed.

    **Sized to the longest name and no wider**, because every unit here is a unit the
    plot does not get: at this console's own catalogue the longest name is
    `kselftest-riscv` (15 characters), which wants 112 of a 1180-wide picture - 94% of
    the board's plot kept - and a chart of `boot` alone keeps the board's own 54.

    The width is read off `CHART_CHAR` rather than measured, and deliberately: the
    column is text in the design's own mono face at the stylesheet's own 10px
    (`.chart text`), so 6 units a character is the arithmetic that face and that size
    give.  A metric that disagreed with the stylesheet could only be right until
    somebody changed `font-size`.
    """
    longest = max((len(name) for name in names), default=0)
    return max(CHART_LEFT, min(CHART_GUTTER_MAX, longest * CHART_CHAR + 22))


def _fit(name: str, left: float) -> str:
    """A band's name, cut to the column it is drawn in - the full one is in its title.

    Only a name past `CHART_GUTTER_MAX` is ever cut, which the catalogue's three
    (`boot`, `kselftest-riscv`, `kselftest-kvm`) are not: the column grows to fit them.
    A cut name is a name a reader cannot act on, so the band's `<title>` carries all of
    it, the same way the axis' two ends carry theirs.

    The cut is the **character** and not `&hellip;` (`chart.cap`'s note on the arrow),
    because the caller escapes what this returns: an entity would reach the reader as
    those six letters.
    """
    room = int((left - 12) / CHART_CHAR)
    return name if len(name) <= room else name[:max(1, room - 1)] + "…"


def chart_none(text: str) -> str:
    """A chart with nothing to draw: a plate with a sentence on it, no axes.

    `ui.empty` is one line of centred grey - the right shape inside a table's body and
    the wrong one where a picture was promised.  A chart whose window has no records at
    all is the *common* case at `/trend?ran=never` and the first thing a new stack
    shows, and the panel used to change height for it the moment the data moved: the
    chart became a sentence, and a reader who had scrolled to the chart found the page
    a band shorter than it was.  This is the same plate a band is drawn on, dashed and
    tall enough for a band, so an empty chart is still the **shape** of a chart.
    """
    return f'<p class="chart-none">{text}</p>'


def _lane_y(percent: float, top: float, bottom: float) -> float:
    """A percentage, as the height it gets **inside one band** of the chart.

    The board's own `_y` mapped 0..100% onto the whole plot, which is what put every
    test on the same line; with a band per test the same percentage is a different
    height in each of them.  One test is one band from `CHART_TOP` to `CHART_BOTTOM`,
    so a chart of one test is drawn exactly where it was.
    """
    return bottom - (bottom - top) * max(0.0, min(100.0, percent)) / 100


# --------------------------------------------------------------- the table
class Col:
    """One column: its word, how it aligns, and how a cell is drawn.

    `key` is what the header sorts by - the page hands it straight to the URL, so a
    column with no `key` is a column the order does not know about.  `field` is which
    member of a row a cell without a `draw` reads; it defaults to `key`, and a column
    with neither raises in `table()` rather than printing a blank.

    `kind` is the class the cell carries.  The design's own words are `n` (right
    aligned, tabular), `c` (centred), `id` (monospace), `trunc` (one line with an
    ellipsis), `wrapc` (wrapping, bounded) and `acts-cell` (a row's buttons).  The
    runs table is the one exception, and it is the script's rather than this file's:
    its cells are re-drawn every two seconds by `drawTable`, so they keep the
    script's own names (`id`, `num`, `wrap`, `act`) and `shell.BRIDGE_CSS` is what
    makes the two vocabularies look alike.

    `span` names a field whose equal neighbours this column draws **once**, as one
    cell with `rowspan=` over the rows it covers - the spreadsheet merge the operator
    asked for over `/jobs` ("第一列的横线少一点"), where three tests of one build repeat
    its id three times.  The rows must already be *contiguous* by that field: `table()`
    merges neighbours and neither sorts nor groups, so a value that returns later is a
    second run with a cell of its own.  It is named apart from `field` because the two
    are different questions - a cell reads the row to draw itself, this one reads the
    row to decide whether the cell above it is the same cell - and a column that draws
    a link, a pill or an escaped value reads the raw field all the same.
    """

    __slots__ = ("draw", "field", "key", "kind", "span", "title", "width", "word")

    def __init__(self, one, draw=None, kind="", key="", title="", width="", field="",
                 span=""):
        self.word, self.kind, self.draw = one, kind, draw
        self.key, self.title, self.width = key, title, width
        self.field, self.span = field, span


def _column(one) -> Col:
    """A `Col`, or the `(word, key)` pair the prototype's pages passed."""
    if isinstance(one, Col):
        return one
    return Col(one[0], key=one[1] if len(one) > 1 else "")


def _reader(col: Col):
    """How one `Col` reads a row: its own `draw`, or the field it names."""
    if col.draw is not None:
        return col.draw
    field = col.field or col.key
    if not field:
        raise ValueError(
            f"column {col.word!r} has no draw() and names no field to read: a column "
            "that read its own header would print an empty cell in every row")
    def read(row):
        if field not in row:
            raise KeyError(f"column {field!r} is not a member of this row")
        value = row[field]
        return DASH if value is None else esc(value)
    return read


def _runs(cols, rows) -> dict:
    """Where a spanned column merges: `(column index, row index) -> rows covered`.

    One entry per run of equal values, keyed by the row the run starts at, and nothing
    at all for a row inside a run - that row emits no cell for this column, because the
    run's cell is `rowspan`-ing over it (`table()` reads this back).  A run of one is
    recorded too and drawn as an ordinary cell: `rowspan="1"` is the same table with
    more markup in it.
    """
    found = {}
    for index, col in enumerate(cols):
        if not col.span:
            continue
        start = 0
        for at in range(1, len(rows) + 1):
            if at < len(rows) and _spanned(rows[at], col) == _spanned(rows[start], col):
                continue
            found[(index, start)] = at - start
            start = at
    return found


def _spanned(row, col: Col):
    """The value a spanned column merges by, read the way `_reader` reads a cell.

    A field the row does not carry is a mistake in the column, not an empty run: it is
    the same `KeyError` a `field=`-only column raises, because a merge over a value
    nobody has would silently join every row.
    """
    if col.span not in row:
        raise KeyError(f"column {col.span!r} is not a member of this row")
    return row[col.span]


def table(cols, rows, empty: str = "", table_id: str = "", rows_of: str = "",
          kinds=(), cls: str = "grid", *, lang: str) -> str:
    """A table, or the one line that says why it is empty.

    `table_id`, `rows_of` and `kinds` are the three things the poll script reads on
    the one table it re-draws (`/runs`): the id it looks for, `data-rows="all"` where
    the rows on screen are every activity, and `data-kinds` naming the order the
    group captions came in - without it a refresh would drop the captions and
    re-shape the table two seconds after it was drawn.

    A column with `span` is drawn once per run of equal neighbours (`_runs`), which
    leaves the rows under it one `<td>` shorter than the rest.  That is the whole
    difference: a reader sees the same table with fewer lines in that column, and the
    rows behind it are untouched - `/jobs`' build id over its three tests is the case.
    """
    rows = list(rows)
    if not rows:
        return f'<p class="empty">{empty or both(lang, "empty.no_rows")}</p>'
    cols = [_column(one) for one in cols]
    runs = _runs(cols, rows)
    head, body = [], []
    for col in cols:
        classes = " ".join(part for part in (col.kind, "sortable" if col.key else "") if part)
        attrs = f' class="{classes}"' if classes else ""
        attrs += " " + _attr(lang, "title", col.title) if col.title else ""
        attrs += f' style="width:{esc(col.width)}"' if col.width else ""
        head.append(f"<th{attrs}>{word(col.word, lang=lang)}</th>")
    for at, row in enumerate(rows):
        cells = []
        for index, col in enumerate(cols):
            # A row this column's own cell already covers contributes nothing here.
            covered = runs.get((index, at), 0)
            if col.span and not covered:
                continue
            cell = _reader(col)(row)
            rowspan = f' rowspan="{covered}"' if covered > 1 else ""
            cells.append(f'<td class="{col.kind}"{rowspan}>{cell}</td>' if col.kind
                         else f"<td{rowspan}>{cell}</td>")
        body.append(f'<tr>{"".join(cells)}</tr>')
    attrs = f' class="{esc(cls)}"' if cls else ""
    attrs += f' id="{esc(table_id)}"' if table_id else ""
    attrs += f' data-rows="{esc(rows_of)}"' if rows_of else ""
    attrs += f' data-kinds="{esc(",".join(kinds))}"' if kinds else ""
    return (f'<div class="tscroll"><table{attrs}>'
            f'<thead><tr>{"".join(head)}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


# --------------------------------------------------------------- containers
def panel(title: str, body: str, sub: str = "", tools: str = "",
          open_: bool = True, flush: bool = False, collapsible: bool = False, *,
          lang: str) -> str:
    """The one container.  `flush` drops the padding for a table that fills it.

    `title` is a catalogue key or markup and goes through `words.heading()`, which
    refuses a heading that names a module, a file or a call: that is the acceptance
    gate's own rule, applied where the heading is written rather than at the gate.
    An empty title is the design's own case - the board draws panels whose `<h2>` is
    empty and whose `sub` carries the fact.

    A `collapsible` panel is remembered under its own `title` (`_fold`): the reader
    who folded the ledger away gets it folded away on the next copy's page too, which
    is what the title being the panel's identity - one catalogue key, no call site
    naming it twice - buys.
    """
    bits = [f"<h2>{words.heading(lang, title)}</h2>"]
    if sub:
        bits.append(f'<span class="sub">{sub}</span>')
    if tools:
        bits.append(f'<span class="tools">{tools}</span>')
    body_cls = "body flush" if flush else "body"
    if collapsible:
        return (f'<details class="panel"{_fold(title)}{" open" if open_ else ""}>'
                f'<summary class="head">{"".join(bits)}</summary>'
                f'<div class="{body_cls}">{body}</div></details>')
    return (f'<section class="panel"><div class="head">{"".join(bits)}</div>'
            f'<div class="{body_cls}">{body}</div></section>')


def hint(text: str) -> str:
    """The muted line a caveat goes in: the design's `.q`.

    The board has no caveat component any more - `.note`, `.hint` and `.split` are
    classes of components its screens stopped drawing - so a page that has to say
    something out loud says it in this line, and one that has to say it about a
    particular control puts it in that control's `title=`.  The name is the
    prototype's, kept so a page moving across does not have to rename a call.
    """
    return f'<p class="q">{text}</p>'


def empty(text: str) -> str:
    return f'<p class="empty">{text}</p>'


def kv(pairs) -> str:
    """The worker's own file: a label and a value, no interpretation.

    A pair is `(label_html, value_html)`: the label is a word from the catalogue and
    the value is the file's own text, which is neither translated nor judged.
    """
    return ('<dl class="kv">'
            + "".join(f"<div><dt>{key}</dt><dd>{value}</dd></div>" for key, value in pairs)
            + "</dl>")


# --------------------------------------------------------------- controls
def field(label_html: str, control: str, width: str = "w-md", cls: str = "",
          tag: str = "") -> str:
    """One filter: its label above, its control below, one width per kind.

    The design wraps a field in a `<label>`, which is what makes clicking the word
    focus the box.  A control that is itself a group of labels (`seg`, `multi`) would
    then be a label inside a label - invalid markup, and read twice by a screen
    reader - so the element defaults to the one that keeps the document valid and
    only a caller with a reason overrides it.
    """
    element = tag or ("div" if "<label" in control else "label")
    classes = " ".join(part for part in ("f", width, cls) if part)
    return (f'<{element} class="{classes}"><span class="lbl">{label_html}</span>'
            f"{control}</{element}>")


def text_input(name: str, value: str = "", placeholder: str = "", label: str = "",
               *, lang: str) -> str:
    """A free-text box.  `label` is its accessible name, for a bar where the visible
    label is the field's own word and the box needs its own.

    Both the placeholder and the accessible name are words, so both take a catalogue
    key as gladly as a literal (`_attr`): the board carries `data-i18n` on each of
    them, and a placeholder that cannot be swapped is English to a Chinese reader.
    """
    return (f'<input type="text" name="{esc(name)}" value="{esc(value)}"'
            f' {_attr(lang, "placeholder", placeholder)}'
            f' {_attr(lang, "aria-label", label)}'
            f' spellcheck="false" autocomplete="off">')


def number_input(name: str, value, min_: int = 0, max_: int = 0, box_id: str = "",
                 stops=()) -> str:
    """A number box, and the suggestion set a value rail is built from.

    `stops` rides to the script in `data-stops`: the rail it draws is a duplicate
    *view* of this box and carries no name of its own, so it can never submit a value
    the box did not already hold.  Past 24 stops the script leaves the rail out on
    purpose - a dropdown beats a slider at that length.
    """
    limits = f' min="{int(min_)}"' if min_ else ""
    limits += f' max="{int(max_)}"' if max_ else ""
    ident = f' id="{esc(box_id)}"' if box_id else ""
    rail = ""
    if stops:
        packed = json.dumps([str(one) for one in stops], separators=(",", ":"))
        rail = f' data-stops="{esc(packed)}"'
    return (f'<input type="number" name="{esc(name)}"{ident} value="{esc(value)}"'
            f'{limits}{rail} inputmode="numeric">')


def select(name: str, options, value: str = "", labeler=None) -> str:
    """A select box.  `options` is a list of strings, or of `(value, word)` pairs.

    A value is what this console compares and a label is what a reader reads, so the
    two are separate here: `labeler` is how a value's word is produced (`both(...)`),
    and the value itself is never translated.
    """
    out = []
    for one in options:
        val, text = one[0], one[1] if isinstance(one, (tuple, list)) else one
        if labeler is not None:
            text = labeler(text)
        chosen = " selected" if str(val) == str(value) else ""
        out.append(f'<option value="{esc(val)}"{chosen}>{text}</option>')
    return f'<select name="{esc(name)}">{"".join(out)}</select>'


def multi(name: str, chosen, options, placeholder: str = "", label: str = "",
          labels=None, *, lang: str) -> str:
    """A multi-valued axis: the chosen values are chips, the box adds one.

    Several axes (`tree`, `arch`, the kbuild states and results, the two ways a
    ledger can answer) accept more than one value at once, and a row of tick boxes
    for 48 trees is a wall.  The chips are the chosen set, the free box takes a value
    no candidate list carries, and the menu offers the rest.

    `labels` is `value -> word` for the axes whose values are a vocabulary a reader
    reads in words (`_labels("evidence", lang)`), the same mapping `select`'s
    `labeler` carries: what the reader sees is translated and what the chip
    *submits* is the value, which is why the two are separate here as everywhere
    else in this file.  An axis whose values are their own words (`kernel`, `pass`)
    passes none, and then the value is what is shown.

    Two things the board's markup does not have and a console's filter needs: every
    chip carries a **hidden input** under the axis's name, without which the chips
    would be a picture of a filter that submits nothing; and the free box carries the
    same name, so a value typed with the script off still reaches the page.  The box
    and the free input carry `data-multi`, which is what tells the shipped bar to
    leave this control alone until `apply` is pressed - one chip is not a decision.
    """
    labels = labels or {}
    tags = "".join(
        f'<span class="tag" data-v="{esc(one)}">{labels.get(one) or esc(one)}'
        f'<input type="hidden" name="{esc(name)}" value="{esc(one)}">'
        f'<button type="button" data-drop="{esc(one)}" '
        f'{words.attr(lang, "aria-label", "filter.remove", value=one)}>&times;</button></span>'
        for one in chosen)
    # The menu button's own text is the label, and the shipped script reads it back
    # when it turns a click into a chip (`shell.py`'s `addChip`): a chip added here
    # and one added by hand have to read the same, or picking a second value would
    # re-spell the first one's word.
    menu = "".join(
        f'<button type="button" data-add="{esc(one)}">{labels.get(one) or esc(one)}</button>'
        for one in options if one not in chosen)
    return (f'<div class="multi" data-name="{esc(name)}" data-multi="1"><div class="box">'
            f"{tags}"
            f'<input type="text" name="{esc(name)}" '
            f'{_attr(lang, "placeholder", placeholder)} '
            f'{_attr(lang, "aria-label", label)} data-multi="1" autocomplete="off"></div>'
            f'<div class="menu" hidden>{menu}</div></div>')


def checkbox(name: str, label_html: str, checked: bool = False, value: str = "",
             form: str = "", all_for: str = "", disabled_reason: str = "",
             title: str = "", multi: bool = False, *, lang: str) -> str:
    """A tick box, a row's tick, or the select-all of a form.

    `all_for` names the form this box ticks *every* box of; it is rendered `hidden`
    with its label, and the script is what unhides it: with JavaScript off a box that
    ticks nothing would be a lie, and the server-side `?tick=` key is the no-JS path.
    `form` is how a box that lives outside its form - one row of a table feeding the
    bar above it - still posts with it.

    `disabled_reason` is the whole of what a disabled box does: it says why, in the
    title, because a grey box with no reason is a box the reader will click twice.

    `multi` marks a box that is one value of an axis a reader answers with **several
    boxes** (`/`'s 来源 is two: 本地 and 远端, `builds._origin_boxes`).  The shipped
    bar auto-submits on change and skips any element carrying `data-multi`
    (`script.py`'s listener, `ui.multi`'s reason for the same attribute): without it,
    ticking the first box would answer the question before the second one was ticked,
    and a reader could not ask for both.
    """
    attrs = f' type="checkbox" name="{esc(name)}"'
    attrs += f' value="{esc(value)}"' if value else ""
    attrs += f' form="{esc(form)}"' if form else ""
    attrs += " checked" if checked else ""
    attrs += ' data-multi="1"' if multi else ""
    if all_for:
        attrs += f' data-all-for="{esc(all_for)}" hidden'
        attrs += " " + _attr(lang, "title", title or "tick.all_title")
        return (f'<label class="f cb" hidden><input{attrs}>'
                f'<span class="lbl">{label_html}</span></label>')
    if disabled_reason:
        attrs += f' disabled {_attr(lang, "title", disabled_reason)}'
    elif title:
        attrs += " " + _attr(lang, "title", title)
    return f'<label class="f cb"><input{attrs}><span class="lbl">{label_html}</span></label>'


def seg(name: str, options, value: str = "") -> str:
    """An either/or: the worker's mode, a page's own toggle."""
    out = []
    for val, label_html in options:
        chosen = " checked" if str(val) == str(value) else ""
        out.append(f'<label><input type="radio" name="{esc(name)}" value="{esc(val)}"{chosen}>'
                   f"<span>{label_html}</span></label>")
    return f'<span class="seg">{"".join(out)}</span>'


def btn(label_html: str, kind: str = "", title: str = "", name: str = "",
        disabled_reason: str = "", attrs: str = "", *, lang: str) -> str:
    """A button.  A button that posts is `action_form`'s; this one acts on nothing
    by itself, which is why it is `type="button"` and never a bare `<button>`."""
    classes = " ".join(part for part in ("btn", kind) if part)
    extra = ""
    if title or disabled_reason:
        extra += " " + _attr(lang, "title", title or disabled_reason)
    extra += f' name="{esc(name)}"' if name else ""
    extra += " disabled" if disabled_reason else ""
    return f'<button type="button" class="{classes}"{extra}{attrs}>{label_html}</button>'


def link_btn(label_html: str, href: str, kind: str = "sm", title: str = "",
             *, lang: str) -> str:
    attr = " " + _attr(lang, "title", title) if title else ""
    return f'<a class="btn {esc(kind)}" href="{esc(href)}"{attr}>{label_html}</a>'


def log_link(ident: str, label_html: str, back: str = "") -> str:
    """The one 日志 link, in every place a page draws one.

    Three server-side writers draw it (`shell.live_row`, `runs._acts_cell`,
    `builds._log_acts`) and the script draws three more, so the shape is decided
    once - and the shape now has a second half.  The log opens in a tab of its own,
    which is what makes "点进日志之后回不去" possible: Back leads to whatever was open
    before the tab, not to the table the click was made in.  `back` is that table
    (the page's own URL, `View.url()`), and the log page draws it as a link.

    `back` empty writes the bare href, which is what a caller with no page to return
    to gets: the log page then has no link, rather than one that lies.
    """
    # `safe=""` on both halves: an id is one path segment (a `/` in it would be read as
    # a second one) and `back` is one value (an `&` in it would end the parameter).
    href = "/runs/" + urllib.parse.quote(str(ident), safe="") + "/log"
    if back:
        href += "?back=" + urllib.parse.quote(back, safe="")
    return (f'<a href="{esc(href)}" target="_blank" rel="noopener">'
            f'{label_html}</a>')


def status() -> str:
    """Where a form's POST answer is written (`[data-status]`, by the script).

    The class is `status` and nothing else on purpose: the script writes
    `className = 'status bad'` over whatever it finds, so a second class here would
    be wiped the first time the form answered.
    """
    return '<span class="status" data-status></span>'


def filters(fields_html, buttons_html: str = "", action: str = "", auto: bool = True,
            hidden=()) -> str:
    """The filter bar: every field, then the buttons that submit them.

    `hidden` carries the keys this page reads but draws no control for.  A GET form
    replaces the whole query string, so a key left out of the form is a key the next
    request silently answers without - which is the one way a filter bar can move the
    reader to a different question than the one they were looking at.

    `auto` is the design's own behaviour (`data-auto`): a control that commits
    submits the bar, so `apply` is the keyboard and no-JavaScript path rather than
    the only path.
    """
    carried = "".join(f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'
                      for name, value in hidden if value)
    attrs = f' action="{esc(action)}"' if action else ""
    attrs += ' data-auto="1"' if auto else ""
    tail = f'<span class="grow"></span>{buttons_html}' if buttons_html else ""
    return (f'<form class="filters" method="get"{attrs}>'
            f"{carried}{fields_html}{tail}</form>")


def _fold(name: str) -> str:
    """The identity a fold remembers itself by, for the script's fold memory.

    A `<details>` with no name is drawn the way the server's own facts say it on every
    load, which is the right answer for a fold whose open state *is* a fact - the
    activity panel is out while something is running.  A name is the reader's own
    choice outliving that fact: `_JS`'s `buildFolds` keeps it in `localStorage` and
    puts it back on the next load, on whichever page the fold is drawn.

    A fold is remembered **by name and not by page**, so a name has to be the same
    wherever it is the same fold and different wherever it is not.  That is why a
    panel is named by its own `title` (one catalogue key per panel, and the panel is
    the same panel on whatever route draws it) and a row of filter boxes by the page
    it belongs to.  The name goes into an attribute, so it is a slug and not a
    sentence: nothing that needs escaping, nothing that moves between languages.
    """
    return f' data-fold="{esc(name)}"' if name else ""


def more(summary_html: str, body_html: str, open_: bool = False, fold: str = "") -> str:
    """The second, folded row of a filter bar: the boxes a reader needs rarely.

    `fold` is the name this row is remembered by (`_fold`); a bar that passes none is
    drawn folded on every load, which is what 更多筛选 wants for the reader who has
    never opened it.
    """
    return (f'<details class="more"{_fold(fold)}{" open" if open_ else ""}>'
            f"<summary>{summary_html}</summary>{body_html}</details>")


def spread() -> str:
    """The gap that pushes a bar's buttons to its right edge."""
    return '<span class="grow"></span>'


def cpanel(chips_html: str, title: str = "", sub: str = "", *, lang: str) -> str:
    """The row of numbers behind a page, in a panel of its own.

    Chips outside a container read as decoration; inside one they read as the page's
    own arithmetic, which is what they are - each one is the count of the rows a link
    goes to, and `accept.py`'s S6 follows the link and counts them.
    """
    return panel(title, chips_html, sub=sub, lang=lang)


def chips(items, *, lang: str) -> str:
    """The numbers behind a page: a word, a number, and where the number came from.

    An item is `(label_html, value, title, href)`.  A chip without an `href` counts
    something no single page shows and is drawn as a `<span>`, which is the honest
    shape for it.

    The wrapper is `<p class="numbers">` and the number is `<b class="n">`: those two
    names are the acceptance gate's (it reads a chip as a label and a number, and
    follows the linked ones), and `BRIDGE_CSS` is where that shape is given the
    design's `.chips` layout and `.v` type.
    """
    out = []
    for label_html, value, title, href in items:
        attr = " " + _attr(lang, "title", title) if title else ""
        body = f'<span class="k">{label_html}</span><b class="n">{esc(value)}</b>'
        if href:
            out.append(f'<a class="chip" href="{esc(href)}"{attr}>{body}</a>')
        else:
            out.append(f'<span class="chip"{attr}>{body}</span>')
    return f'<p class="numbers">{"".join(out)}</p>'


def actions(buttons_html: str, argv: str = "", blurb: str = "") -> str:
    """A row of buttons, the command line they would run, and what running it costs.

    The command line is the point of every button in this console - each one runs
    something an operator could have typed - so it is printed under them in full,
    with the whole value in the `title=` for a line too long for the panel.  A bare
    row of buttons is a button whose effect the reader has to guess at.
    """
    out = [f'<div class="row"><span class="row tight">{buttons_html}</span></div>']
    if argv:
        out.append(f'<p class="q" style="margin-top:7px;word-break:break-all" '
                   f'title="{esc(argv)}">{esc(argv)}</p>')
    if blurb:
        out.append(f'<p class="q" style="margin-top:7px">{blurb}</p>')
    return "".join(out)


def action_form(action: str, label_html: str, fields=(), inner: str = "", argv: str = "",
                hint: str = "", blocked: str = "", form_id: str = "",
                kind: str = "primary sm", also=(), *, lang: str) -> str:
    """One write action, as the form the page's script takes over.

    The POST goes to `/api/actions/<name>` and the shipped script keeps the reader on
    the page (`_JS`'s delegated submit listener), so the answer is written into
    `status()`, which is per form and has to be inside this form - two bars sharing
    one line would each claim the other's refusal.  `fields` are the conditions the
    command will run with, as hidden values; `inner` is a control the row itself
    draws - a tick box, or a box the reader types into (`/`'s provision panel, whose
    six values exist only once they are typed).  An `inner` control is the form's own
    value for the name it carries and never a *second* copy of a hidden one: two
    controls with one name would submit both values and leave the server to pick one,
    so a caller that draws a condition as `inner` leaves it out of `fields`.  `inner`
    must not contain a `<button>`: the script disables the pressed button of the form
    while it posts.

    `blocked` is the reason this action must not be pressable, and the reason is what
    the disabled button says in its `title=` - it keeps its label and explains
    itself rather than vanishing.

    `also` is this same form's other buttons, `(action, label, hint, blocked)` each,
    drawn after this one - for the commands that take **the same fields and the same
    ticks**.  The builds bar is what it was added for: *pull the selected*, *index
    this window* and *index, then pull the selected* are one press apart, and the box
    a reader ticks has to reach two of them.  One form is the only way to say that,
    because a tick box names exactly one form (`form="…"`): two forms would mean two
    sets of boxes and a bar where half the ticks are invisible to half the buttons.
    Each extra button carries its own `formaction`, which the shipped script reads
    off the button that was pressed (`e.submitter`).  They carry their own `hint` and
    their own `blocked`, because both are facts about *that* command - on that bar the
    two index buttons refuse a filter naming several trees and the pull beside them
    does not.

    **An `also` entry may carry a fifth element: the `(name, value)` pairs that button
    alone sends.**  That is how two buttons over one set of ticks run one command in two
    modes - the re-run buttons (「难道就不能默认增加重跑？」) are the same action over the
    same ticks as the run beside them, one `redo=1` apart.  It cannot be a hidden field:
    a hidden field belongs to the **form**, so the button next to it would send `redo=1`
    too, and "run" and "re-run" would be decided by a field neither of them owns.  The
    browser submits a submitter's own name and value with the form, and `_JS`'s POST
    says `FormData(form, e.submitter)` for the same reason: without that argument the
    value reached the server over the no-script path and vanished over the scripted one,
    which is one press running two different commands.

    **An extra button's `hint` is also where its command line goes.**  `argv` draws
    one line for the whole form, which is right for a form with one button; under
    three, a line naming one of them is read as the command for whichever the reader
    is about to press.  So the tick-driven buttons print nothing (`_pull_bar` says
    why) and the ones whose command is known carry it as their own `title=`, which is
    what the per-row pull already does.
    """
    hidden = "".join(f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'
                     for name, value in fields)
    attrs = f' id="{esc(form_id)}"' if form_id else ""
    attrs += " " + _attr(lang, "title", hint) if hint else ""

    def button(name: str, label: str, note: str = "", why: str = "",
               first: bool = False, sends=()) -> str:
        """One button of this form: the form's own action, or its own `formaction`.

        `sends` are the fields this button carries and its siblings do not (see
        `also` above).  They are drawn as `name`/`value` **on the button**, which is
        the only element a browser reads them off: they belong to the press, and a
        button that is not the one pressed contributes nothing.
        """
        said = [f'formaction="/api/actions/{esc(name)}"'] if not first else []
        said += [f'name="{esc(key)}" value="{esc(value)}"' for key, value in sends]
        if why:
            said.append("disabled")
        title = _attr(lang, "title", why or note)
        if title:
            said.append(title)
        return (f'<button class="btn {esc(kind)}"'
                + (f' {" ".join(said)}' if said else "")
                + f">{label}</button>")

    extra = []
    for entry in also:
        one, label, note, why = entry[:4]
        # The fifth element is optional, so it is read by position rather than by a
        # star-target: an `also` with four elements and one with five are both ordinary,
        # and a bare `*sends` would make the fifth element's own shape the thing a
        # caller has to get right.
        extra.append(button(one, label, note, why,
                            sends=entry[4] if len(entry) > 4 else ()))
    buttons = button(action, label_html, why=blocked, first=True) + "".join(extra)
    line = (f'<p class="q" style="margin-top:7px;word-break:break-all" '
            f'title="{esc(argv)}">{esc(argv)}</p>' if argv else "")
    return (f'<form method="post" action="/api/actions/{esc(action)}"{attrs}>'
            f"{hidden}{inner}{buttons}{status()}{line}</form>")


def _kept_state(view) -> tuple:
    """The page state this request holds, as the pairs a link has to carry to keep it.

    `kind` on `/runs` (the kinds the reader unfolded, `runs._unfolded`) and
    `mode`/`platform`/`runtime`/`since` on `/worker` (the arguments the start button is
    about to run) are read off the query by the route's own wiring and live on the check
    (`schema.PAGE_STATE`, `design/serve.py`) - but they are not `Filter` fields, so
    `to_query()` leaves them out and nothing puts them in a URL unless a caller asks for
    them by name (`urls._url`'s `keep`).

    That is right for most links, which are *about* one condition.  A pager is not: its
    whole job is to move a reader to another page **of the page they are on**, and a page
    link that dropped the reader's unfolded kinds - or the window the queue is about to
    be asked for - would answer a question they did not ask.  So the pager keeps the
    route's own page state, read from the one table that names it rather than spelled at
    each call site, where the next list would forget it.

    A value the request did not state is left out: `_page_state` sets an absent key to
    nothing rather than to `""`, and a pair with an empty value would be a key the URL
    spells as asked-for-and-empty.  `keep`'s own reader drops those anyway.
    """
    check = view.check
    if check is None:
        return ()
    kept = []
    for name in state_keys(view.route):
        value = getattr(check, name, "")
        if value:
            kept.append((name, str(value)))
    return tuple(kept)


def pager(view, total: int, limit: int, offset: int, window: int = 2,
          key: str = "offset") -> str:
    """The design's pager over this console's page state, or nothing when it fits.

    `?offset=` is a key three readers understand and no link ever wrote, so the only way
    to see row 51 was to widen `limit`.  This is that link: **the page size is `limit`**,
    which is what makes a chip's `?limit=N` still land on a table with exactly N rows
    (`accept.py`'s S6 counts them), and every page is an `<a>` to `view.url(offset=…)` -
    so a page survives a reload, a bookmark and a script turned off, and the pager never
    spells a query string of its own.

    `key` is the query key the offset is written under.  It is `offset` for the page's
    **own** list (the builds table, `/runs`), and one of `schema.LIST_OFFSETS` for the
    second and later lists a page draws together - `/local/<build_id>` prints four, and
    one shared `offset` would turn all four pages at once.  The key is always spelled,
    never filtered: `_url` keeps an override the caller wrote by hand (`urls._url`'s
    `given`), which is what lets a named list page on a route whose whitelist has never
    heard of the name.

    Every link and the jump form keep the route's own page state as well as its filter
    (`_kept_state`): a page link is a move to another page *of this page*, and the kinds
    a reader unfolded on `/runs` - or the window `/worker`'s start button is about to
    ask for - are part of the page they are on.

    The class family is the board's: `.pager`, `.pages`, `.btn.on` for the page the
    reader is on, `.pjumpwrap`/`.pjump`/`.ptotal` for the jump box.  The readout is the
    board's own shape (`1–20 / 240`).

    Two things differ from the board, and both are forced by the URL being the state.
    The page list is a **window** around the current page plus the first and last, where
    the board's twenty-row table prints a button per page - a 5000-row table would print
    a hundred.  And the jump box takes a *page number* only because `BRIDGE_JS` turns it
    into an offset on submit: a plain GET cannot do that arithmetic, so the box is
    rendered `hidden` and unhidden by the script, and `accept.py`'s no-JavaScript reader
    sees the page links alone.
    """
    offset, limit = max(0, int(offset)), max(1, int(limit))
    total = max(0, int(total))
    pages = max(1, (total + limit - 1) // limit)
    if pages == 1:
        return ""                              # everything fits: no pager at all
    kept = tuple(one for one in _kept_state(view) if one[0] != key)
    page = min(pages, offset // limit + 1)
    steps = sorted({1, pages} | {one for one in range(page - window, page + window + 1)
                                 if 1 <= one <= pages})
    nav, last = [], 0
    for one in steps:
        if one > last + 1:
            nav.append('<span class="muted">&hellip;</span>')
        if one == page:
            nav.append(f'<span class="btn sm on">{one}</span>')
        else:
            # `{key: …}` and not `offset=…`: spelling the key as a keyword argument is
            # the one way to hand `view.url` a name that is not a Python identifier of
            # its own (`urls._url`'s `**over`), and the key this list pages by is data.
            at = esc(view.url(keep=kept, **{key: str((one - 1) * limit)}))
            nav.append(f'<a class="btn sm" href="{at}">{one}</a>')
        last = one
    ends = []
    for label, target in (("&lsaquo;", page - 1), ("&rsaquo;", page + 1)):
        if 1 <= target <= pages:
            at = esc(view.url(keep=kept, **{key: str((target - 1) * limit)}))
            ends.append(f'<a class="btn sm" href="{at}">{label}</a>')
        else:
            # A link cannot be `disabled`, which is how the board draws the end of the
            # range: the same button in the muted ink, and nothing to click.
            ends.append(f'<span class="btn sm muted">{label}</span>')
    state = list(view.check.to_query() if view.check is not None else ())
    carried = "".join(
        f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'
        for name, value in (*state, *kept, (key, str(max(0, offset)))))
    # `data-offset-name` is how `BRIDGE_JS` finds that hidden field: the box carries a
    # *page number* and the script has to write an offset into the field this pager
    # spells, which is `offset` on one list and `pulls`/`record`/… on the next.
    jump = (f'<form class="pjumpwrap" method="get" action="{esc(view.route)}" '
            f'data-pager="1" data-offset-name="{esc(key)}" hidden>{carried}'
            f'<input class="pjump" type="number" min="1" max="{pages}" value="{page}" '
            f'data-limit="{limit}" data-pages="{pages}" '
            f'{words.attr(view.lang, "title", "pager.jump", limit=limit)}>'
            f'<span class="ptotal">/ {pages}</span></form>')
    return ('<div class="pager">'
            f'<span class="muted">{offset + 1 if total else 0}&ndash;'
            f'{min(offset + limit, total)} / {total}</span>'
            f'<span class="grow"></span>'
            f'<span class="pages">{"".join(ends[:1] + nav + ends[1:])}</span>'
            f"{jump}</div>")


def page_slice(rows, offset: int, limit: int) -> tuple:
    """One page of a list: the rows it holds, and the offset that is really theirs.

    A URL can say any offset - typed into the jump box's place, left over from a list
    that has since shrunk, or carried by a bookmark of a page that no longer exists -
    and `rows[900:950]` of a sixty-row list is an empty table under a sub-line that
    counts sixty: a page that says it has rows and draws none.  So the offset is clamped
    to the last page boundary, and it is the **clamped** offset the pager is handed as
    well, so the page the reader sees and the page the pager names are the same page.

    Returns `(offset, page)`.  The caller slices nothing itself: this is the one place
    that decides where a page begins, and `list_panel`, `_record_panel` and `/runs` all
    read it from here.
    """
    limit = max(1, int(limit))
    total = len(rows)
    offset = min(max(0, int(offset)), (max(0, total - 1) // limit) * limit)
    return offset, rows[offset:offset + limit]


def list_panel(view, title: str, cols, rows, empty: str = "", *, lang: str,
               sub: str = "", offset: int = 0, limit: int = 50, key: str = "offset",
               collapsible: bool = False, open_: bool = True, flush: bool = True,
               tools: str = "") -> str:
    """A panel that is one paginated list: the whole of `panel` + `table` + `pager`.

    Every list a page draws was spelling this composition out by hand - the title key,
    the table, the `empty` sentence, then a pager bolted on - and each of them decided
    on its own whether the sub-line's count was the page or the whole list.  This is
    that one answer: `rows` is the **whole** list, `total` is its length, the sub-line's
    `{n}` is that same total (the reader is told how many rows there are, and the pager
    beside it says which of them are on screen), and only that page is drawn
    (`page_slice`, which is also where an offset past the end is brought back).

    `key` is the offset key this list pages by (`pager`): `offset` for a page's own
    list, a `schema.LIST_OFFSETS` name for the second and later ones, and `""` for a
    list that must not paginate at all - then no pager is drawn and `rows[:limit]` is
    what the reader gets, which is the shape a panel with a fixed small list wants to
    keep saying out loud.

    Unlike `panel`, `flush` defaults to `True`: this is a table panel, and the design's
    table fills its box edge to edge.
    """
    all_rows = list(rows)
    offset, page = page_slice(all_rows, offset, limit)
    body = table(cols, page, empty=empty, lang=lang)
    if key:
        body += pager(view, len(all_rows), limit, offset, key=key)
    return panel(title, body, sub=sub, tools=tools, open_=open_, flush=flush,
                 collapsible=collapsible, lang=lang)


def log_row(text: str, span: int = 0, link: str = "", tag: str = "tr", *,
            lang: str) -> str:
    """The design's inline log: a `.logrow` holding a `.logbox`.

    The board builds this row from its own script on a click of a `/runs/...` link and
    fills it with a tail; here the server draws it, for the pages that already hold the
    text - a config comparison, a build's own log - so the row is there with the script
    off and the text can be selected, searched, copied and linked.

    The board draws it in either holder, and so does this: a `tr` under the row it
    belongs to (`span` is that row's column count, for the `colspan`) or an `li` under
    an item of a list.  It is *not* the live panel's list: the shipped script rewrites
    that list every two seconds, so a log row put there would be gone before it was
    read - the live panel's rows keep the real `/runs/<id>/log` link.

    `link` is the whole file, printed as a `<code>` path in the row's `.logfoot`: the
    box shows what the page has and the footer is where the rest of it is - the board's
    own words (`log.tail`) and the board's own two elements.
    """
    foot = ""
    if link:
        foot = (f'<div class="logfoot">{both(lang, "log.tail")} '
                f'<a href="{esc(link)}"><code>{esc(link)}</code></a></div>')
    box = f'<div class="logbox"><pre>{esc(text)}</pre>{foot}</div>'
    if tag == "li":
        return f'<li class="logrow">{box}</li>'
    return (f'<tr class="logrow"><td colspan="{max(1, int(span))}">{box}</td></tr>')


def foot(d: dict, extra: str = "", *, lang: str) -> str:
    """What the page read and when - the line that makes a stale page obvious.

    `d` is the page's rows, so this is the one component that reads the data dict
    rather than a value: the two facts it prints (`drawn_from`, `drawn`) are the
    page's own and neither is a thing a caller would hold separately.
    """
    source = ", ".join(f"<code>{esc(one)}</code>" for one in (d.get("drawn_from") or ()))
    return ('<p class="foot">'
            f'<span>{both(lang, "shell.read_from")} {source}</span>'
            f'<span>{both(lang, "shell.drawn")} <code>{esc(d.get("drawn"))}</code></span>'
            f'<span class="grow"></span>{extra}</p>')
