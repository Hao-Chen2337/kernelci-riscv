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

from ... import errors
from ...i18n import CATALOGUE, DEFAULT_LANG, t
from ..schema import _labels
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


def bars(rows) -> str:
    """A bar per build: pass, fail, then what did not answer.

    The three counts are the build's own and not a running total, so one bar is a
    reading of one build and the list of bars is the trend.  A build with nothing
    recorded gets an empty track and a dash: a bar of width zero would read as
    "everything failed", which is the opposite of what a missing record says.
    """
    out = []
    for row in rows:
        ok, bad, warn = row.get("ok", 0), row.get("bad", 0), row.get("warn", 0)
        total = ok + bad + warn or 1
        segments = "".join(
            f'<i class="{cls}" style="width:{n / total * 100:.2f}%"></i>'
            for cls, n in (("ok", ok), ("bad", bad), ("warn", warn)) if n)
        label = (f"{ok}&thinsp;/&thinsp;{bad}&thinsp;/&thinsp;{warn}"
                 if ok or bad or warn else "&mdash;")
        build = str(row.get("build_id") or "")
        out.append(f'<div class="bar"><span class="bt" title="{esc(build)}">'
                   f"{esc(build[:16])}&hellip;</span>"
                   f'<span class="track">{segments}</span>'
                   f'<span class="bn">{label}</span></div>')
    return f'<div class="bars">{"".join(out)}</div>'


# --------------------------------------------------------------- the charts
# The design's own geometry, in the board's own numbers: a 1180x226 viewBox, the plot
# from x=54 to x=1128 and from y=16 (100%) to y=204 (0%), a dashed line every 25%,
# and the order's two ends named under the axis.  Keeping the board's numbers rather
# than choosing new ones is what makes a chart here look like the chart there.
CHART_W, CHART_H = 1180, 226
CHART_LEFT, CHART_RIGHT, CHART_TOP, CHART_BOTTOM = 54, 1128, 16, 204
CHART_STEPS = (0, 25, 50, 75, 100)
# The five series colours the stylesheet already has.  A sixth test reuses the
# first: the design has five, and the legend beside the chart is what names them.
SERIES = ("--s1", "--s2", "--s3", "--s4", "--s5")


def line_chart(series, slots: int = 0, ends=("", ""), caption: str = "",
               nothing: str = "", *, lang: str) -> str:
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
    """
    rows = _series(series)
    if not rows:
        return f'<p class="empty">{nothing or both(lang, "empty.no_rows")}</p>'
    if not slots or not any(ends):
        axis_slots, axis_ends = _axis(series)
        slots = slots or axis_slots
        ends = ends if any(ends) else axis_ends
    if not slots:                      # no axis given: the rightmost point is the end
        slots = 1 + max((at for _one, points in rows for at, _pct in points), default=0)
    parts = []
    for step in CHART_STEPS:
        y = _y(step)
        parts.append(f'<line class="yline" x1="{CHART_LEFT}" y1="{y:.1f}" '
                     f'x2="{CHART_RIGHT}" y2="{y:.1f}"></line>')
        parts.append(f'<text x="45" y="{y + 3.4:.1f}" text-anchor="end">{step}%</text>')
    parts.append(f'<line class="axis" x1="{CHART_LEFT}" y1="{CHART_BOTTOM}" '
                 f'x2="{CHART_RIGHT}" y2="{CHART_BOTTOM}"></line>')
    span = max(1, int(slots) - 1)
    for at, (name, points) in enumerate(rows):
        colour = SERIES[at % len(SERIES)]
        placed = [(_x(position / span), _y(percent), position, percent)
                  for position, percent in points]
        if not placed:
            continue
        parts.append(f'<polyline fill="none" stroke="var({colour})" stroke-width="1.7" '
                     f'stroke-linejoin="round" stroke-linecap="round" points="'
                     + " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in placed)
                     + '"></polyline>')
        for order, (x, y, position, percent) in enumerate(placed):
            # The point's tooltip is a *word* ("position 3") with two numbers beside
            # it, so it carries both columns like every other word here: an SVG
            # `<title>` is an element, and the swap reaches it the same way it reaches
            # a span.  The board prints this sentence on every marker.
            title = both(lang, "chart.point", test=name, pct=f"{percent:g}",
                         n=position + 1)
            radius = 3 if order == len(placed) - 1 else 2.1
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" '
                         f'fill="var({colour})"><title>{title}</title></circle>')
    for name, x, anchor in ((ends[0], CHART_LEFT, "start"), (ends[1], CHART_RIGHT, "end")):
        if name:
            parts.append(f'<text class="endlbl" x="{x}" y="220" '
                         f'text-anchor="{anchor}">{esc(str(name)[:8])}&hellip;</text>')
    return (f'<svg class="chart" viewBox="0 0 {CHART_W} {CHART_H}" role="img" '
            f'{words.attr(lang, "aria-label", "chart.passrate")}>{"".join(parts)}</svg>'
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


def _x(on_axis: float) -> float:
    """A position on the x axis, as the board's geometry puts it."""
    return CHART_LEFT + (CHART_RIGHT - CHART_LEFT) * max(0.0, min(1.0, on_axis))


def _y(percent: float) -> float:
    """A percentage on the y axis, as the board's geometry puts it."""
    return CHART_BOTTOM - (CHART_BOTTOM - CHART_TOP) * max(0.0, min(100.0, percent)) / 100


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
    """

    __slots__ = ("draw", "field", "key", "kind", "title", "width", "word")

    def __init__(self, one, draw=None, kind="", key="", title="", width="", field=""):
        self.word, self.kind, self.draw = one, kind, draw
        self.key, self.title, self.width = key, title, width
        self.field = field


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


def table(cols, rows, empty: str = "", table_id: str = "", rows_of: str = "",
          kinds=(), cls: str = "grid", *, lang: str) -> str:
    """A table, or the one line that says why it is empty.

    `table_id`, `rows_of` and `kinds` are the three things the poll script reads on
    the one table it re-draws (`/runs`): the id it looks for, `data-rows="all"` where
    the rows on screen are every activity, and `data-kinds` naming the order the
    group captions came in - without it a refresh would drop the captions and
    re-shape the table two seconds after it was drawn.
    """
    rows = list(rows)
    if not rows:
        return f'<p class="empty">{empty or both(lang, "empty.no_rows")}</p>'
    head, body = [], []
    for one in cols:
        col = _column(one)
        classes = " ".join(part for part in (col.kind, "sortable" if col.key else "") if part)
        attrs = f' class="{classes}"' if classes else ""
        attrs += " " + _attr(lang, "title", col.title) if col.title else ""
        attrs += f' style="width:{esc(col.width)}"' if col.width else ""
        head.append(f"<th{attrs}>{word(col.word, lang=lang)}</th>")
    for row in rows:
        cells = []
        for one in cols:
            col = _column(one)
            cell = _reader(col)(row)
            cells.append(f'<td class="{col.kind}">{cell}</td>' if col.kind
                         else f"<td>{cell}</td>")
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
    """
    bits = [f"<h2>{words.heading(lang, title)}</h2>"]
    if sub:
        bits.append(f'<span class="sub">{sub}</span>')
    if tools:
        bits.append(f'<span class="tools">{tools}</span>')
    body_cls = "body flush" if flush else "body"
    if collapsible:
        return (f'<details class="panel"{" open" if open_ else ""}>'
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
          *, lang: str) -> str:
    """A multi-valued axis: the chosen values are chips, the box adds one.

    Four axes (`tree`, `arch`, `defconfig`, `compiler`) accept several values at once,
    and a row of tick boxes for 48 trees is a wall.  The chips are the chosen set, the
    free box takes a value no candidate list carries, and the menu offers the rest.

    Two things the board's markup does not have and a console's filter needs: every
    chip carries a **hidden input** under the axis's name, without which the chips
    would be a picture of a filter that submits nothing; and the free box carries the
    same name, so a value typed with the script off still reaches the page.  The box
    and the free input carry `data-multi`, which is what tells the shipped bar to
    leave this control alone until `apply` is pressed - one chip is not a decision.
    """
    tags = "".join(
        f'<span class="tag" data-v="{esc(one)}">{esc(one)}'
        f'<input type="hidden" name="{esc(name)}" value="{esc(one)}">'
        f'<button type="button" data-drop="{esc(one)}" '
        f'{words.attr(lang, "aria-label", "filter.remove", value=one)}>&times;</button></span>'
        for one in chosen)
    menu = "".join(
        f'<button type="button" data-add="{esc(one)}">{esc(one)}</button>'
        for one in options if one not in chosen)
    return (f'<div class="multi" data-name="{esc(name)}" data-multi="1"><div class="box">'
            f"{tags}"
            f'<input type="text" name="{esc(name)}" '
            f'{_attr(lang, "placeholder", placeholder)} '
            f'{_attr(lang, "aria-label", label)} data-multi="1" autocomplete="off"></div>'
            f'<div class="menu" hidden>{menu}</div></div>')


def checkbox(name: str, label_html: str, checked: bool = False, value: str = "",
             form: str = "", all_for: str = "", disabled_reason: str = "",
             title: str = "", *, lang: str) -> str:
    """A tick box, a row's tick, or the select-all of a form.

    `all_for` names the form this box ticks *every* box of; it is rendered `hidden`
    with its label, and the script is what unhides it: with JavaScript off a box that
    ticks nothing would be a lie, and the server-side `?tick=` key is the no-JS path.
    `form` is how a box that lives outside its form - one row of a table feeding the
    bar above it - still posts with it.

    `disabled_reason` is the whole of what a disabled box does: it says why, in the
    title, because a grey box with no reason is a box the reader will click twice.
    """
    attrs = f' type="checkbox" name="{esc(name)}"'
    attrs += f' value="{esc(value)}"' if value else ""
    attrs += f' form="{esc(form)}"' if form else ""
    attrs += " checked" if checked else ""
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


def more(summary_html: str, body_html: str, open_: bool = False) -> str:
    """The second, folded row of a filter bar: the boxes a reader needs rarely."""
    return (f'<details class="more"{" open" if open_ else ""}>'
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
                kind: str = "primary sm", *, lang: str) -> str:
    """One write action, as the form the page's script takes over.

    The POST goes to `/api/actions/<name>` and the shipped script keeps the reader on
    the page (`_JS`'s delegated submit listener), so the answer is written into
    `status()`, which is per form and has to be inside this form - two bars sharing
    one line would each claim the other's refusal.  `fields` are the conditions the
    command will run with, as hidden values; `inner` is a control the row itself
    draws (a tick box) and never a second copy of a condition, which would submit
    both values and leave the server to pick one.  `inner` must not contain a
    `<button>`: the script disables the first button of the form while it posts.

    `blocked` is the reason this action must not be pressable, and the reason is what
    the disabled button says in its `title=` - it keeps its label and explains
    itself rather than vanishing.
    """
    hidden = "".join(f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'
                     for name, value in fields)
    attrs = f' id="{esc(form_id)}"' if form_id else ""
    attrs += " " + _attr(lang, "title", hint) if hint else ""
    button = (f'<button class="btn {esc(kind)}" disabled '
              f'{_attr(lang, "title", blocked)}>'
              f"{label_html}</button>" if blocked
              else f'<button class="btn {esc(kind)}">{label_html}</button>')
    line = (f'<p class="q" style="margin-top:7px;word-break:break-all" '
            f'title="{esc(argv)}">{esc(argv)}</p>' if argv else "")
    return (f'<form method="post" action="/api/actions/{esc(action)}"{attrs}>'
            f"{hidden}{inner}{button}{status()}{line}</form>")


def pager(view, total: int, limit: int, offset: int, window: int = 2) -> str:
    """The design's pager over this console's page state, or nothing when it fits.

    `?offset=` is a key three readers understand and no link ever wrote, so the only way
    to see row 51 was to widen `limit`.  This is that link: **the page size is `limit`**,
    which is what makes a chip's `?limit=N` still land on a table with exactly N rows
    (`accept.py`'s S6 counts them), and every page is an `<a>` to `view.url(offset=…)` -
    so a page survives a reload, a bookmark and a script turned off, and the pager never
    spells a query string of its own.

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
            nav.append(f'<a class="btn sm" href="{esc(view.url(offset=str((one - 1) * limit)))}">'
                       f"{one}</a>")
        last = one
    ends = []
    for label, target in (("&lsaquo;", page - 1), ("&rsaquo;", page + 1)):
        if 1 <= target <= pages:
            ends.append(f'<a class="btn sm" href="'
                        f'{esc(view.url(offset=str((target - 1) * limit)))}">{label}</a>')
        else:
            # A link cannot be `disabled`, which is how the board draws the end of the
            # range: the same button in the muted ink, and nothing to click.
            ends.append(f'<span class="btn sm muted">{label}</span>')
    state = list(view.check.to_query() if view.check is not None else ())
    carried = "".join(
        f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'
        for name, value in (*state, ("offset", str(max(0, offset)))))
    jump = (f'<form class="pjumpwrap" method="get" action="{esc(view.route)}" '
            f'data-pager="1" hidden>{carried}'
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
