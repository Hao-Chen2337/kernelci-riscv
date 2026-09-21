# SPDX-License-Identifier: LGPL-2.1-or-later
"""The components: one function per thing a page is made of.

A page module reads like a list of these - `table(...)`, `pill(...)`, `filters(...)`
- and names no tag of its own except in a cell renderer, which is where a cell's
own markup belongs.  The three rules this file exists to hold:

* **A state is a pill and a pill is a table lookup.**  `STATE["incomplete"]` is
  `warn`, one place, so the same word is the same colour on all five pages.
* **A table is sticky, zebra-free and numeric where it is numeric.**  `table()`
  takes columns and rows and owns `thead`, the scroll box and `n`/`c` alignment;
  a page that hand-writes a `<tr>` is a page that will drift.
* **Every translated word goes through `words.both()`.**  A literal in a page is
  either a code-form word (`pass`, `boot`, a flag) or a bug.
"""

import html

from . import words
from .words import both

# --------------------------------------------------------------- the escapes
def esc(text) -> str:
    """A value from the data, escaped.  Never a translated string - those carry markup."""
    return html.escape("" if text is None else str(text))


def code(text, href: str = "") -> str:
    """A build id, a path or an argv: monospace, and a link when there is one."""
    body = esc(text)
    if href:
        body = f'<a href="{esc(href)}">{body}</a>'
    return body


def num(text) -> str:
    return f'<span class="num">{esc(text)}</span>'


# --------------------------------------------------------------- the states
# The one place a word becomes a colour.  A word not here is `idle`, which is the
# honest colour for a state nobody has taught the page about yet.
STATE = {
    "pass": "ok", "ok": "ok", "done": "ok", "whole": "ok", "ready": "ok",
    "yes": "ok", "run": "ok",
    "fail": "bad", "failed": "bad", "error": "bad", "absent": "bad", "no": "bad",
    "incomplete": "warn", "warn": "warn", "partial": "warn", "not whole": "warn",
    "running": "info", "available": "info", "info": "info", "pulled": "info",
    "idle": "idle", "missing": "idle", "card only": "idle", "cancel": "idle",
}


def tone(word: str) -> str:
    return STATE.get((word or "").strip().lower(), "idle")


def pill(word, n=None, tone_override: str = "") -> str:
    """One state as a dot and a word.  `n` rides inside the same pill."""
    t = tone_override or tone(str(word))
    body = esc(word)
    if n is not None:
        body += f' <span class="n">{esc(n)}</span>'
    return f'<span class="pill {t}">{body}</span>'


def tick(ok: bool, off: str = "&mdash;") -> str:
    """A check on a field: a glyph, not a sentence.

    The three artifacts of a card are asked about one per column, and a pill with
    the word "kernel" in it three times is three columns of noise - the header
    says which artifact it is.
    """
    if ok:
        return '<span class="tick" title="present">&#10003;</span>'
    if ok is False:
        return '<span class="cross" title="absent">&#10007;</span>'
    return f'<span class="dash">{off}</span>'


def flag(word: str) -> str:
    """A yes/no cell as a small boxed glyph, for a column read at a glance."""
    if word is True:
        return '<span class="flag on" title="yes">&#10003;</span>'
    if word is False:
        return '<span class="flag no" title="no">&#10007;</span>'
    return '<span class="flag" title="unknown">?</span>'


def delta(pair, first: bool = False, last: bool = False) -> str:
    """A config comparison as three signed numbers, or the reason there is none.

    `+a -r ~c` is added / removed / changed.  A row whose pair was not read says
    *why* in words - "the first row in this order" is a fact about the order, not
    a missing measurement, and printing a dash for both would hide that.
    """
    if pair is None:
        if first:
            return f'<span class="muted">{both("analysis.first_row")}</span>'
        if last:
            return f'<span class="muted">{both("analysis.last_row")}</span>'
        return '<span class="dash" title="not read">&mdash;</span>'
    added, removed, changed = pair
    return (f'<span class="delta">'
            f'<span class="plus">+{added}</span>'
            f'<span class="minus">&minus;{removed}</span>'
            f'<span class="same">~{changed}</span></span>')


def spark(marks) -> str:
    """A run of records as squares; `None` is a position with no record."""
    out = []
    for m in marks:
        cls = {"pass": "ok", "fail": "bad", "incomplete": "warn"}.get(m or "", "")
        out.append(f'<i class="{cls}" title="{esc(m or "no record")}"></i>')
    return f'<span class="spark">{"".join(out)}</span>'


def bars(rows) -> str:
    """A bar per build: pass, fail, then what did not answer.

    The three counts are the run's own, not a running total, so a bar is a reading
    of one build and the list of bars is the trend.  The mockup note asked for
    both readings and this is the one that fits a bar; the timeline panel below
    carries the other.
    """
    out = []
    for r in rows:
        ok, bad, warn = r["ok"], r["bad"], r["warn"]
        total = ok + bad + warn or 1
        seg = "".join(
            f'<i class="{cls}" style="width:{n / total * 100:.2f}%"></i>'
            for cls, n in (("ok", ok), ("bad", bad), ("warn", warn)) if n
        )
        label = f'{ok}&thinsp;/&thinsp;{bad}&thinsp;/&thinsp;{warn}' if ok or bad or warn else "&mdash;"
        out.append(
            f'<div class="bar"><span class="bt" title="{esc(r["build_id"])}">'
            f'{esc(r["build_id"][:16])}&hellip;</span>'
            f'<span class="track">{seg}</span>'
            f'<span class="bn">{label}</span></div>'
        )
    return f'<div class="bars">{"".join(out)}</div>'


# --------------------------------------------------------------- the table
class Col:
    """One column: its word, how it aligns, and how a cell is drawn.

    `key` is what the header sorts by - the page hands it straight to the URL, so
    a column with no `key` is a column the order does not know about.
    """

    __slots__ = ("word", "kind", "draw", "key", "title", "width")

    def __init__(self, word, draw=None, kind="", key="", title="", width=""):
        self.word, self.kind, self.draw = word, kind, draw
        self.key, self.title, self.width = key, title, width


def table(cols, rows, empty: str = "") -> str:
    """A table, or the one line that says why it is empty.

    `cols` are `Col`s; a cell is `col.draw(row)` if it has one, else
    `row[col.word]` escaped.  `cols` may also carry a `(word, key)` tuple, which
    is the common case and is turned into a `Col` here.
    """
    if not rows:
        return f'<p class="empty">{empty or both("shell.live_empty")}</p>'
    head, body = [], []
    for c in cols:
        if not isinstance(c, Col):
            c = Col(c[0], key=c[1] if len(c) > 1 else "")
        cls = f' class="{c.kind} sortable"' if c.key else (f' class="{c.kind}"' if c.kind else "")
        title = f' title="{esc(c.title)}"' if c.title else ""
        style = f' style="width:{c.width}"' if c.width else ""
        head.append(f'<th{cls}{title}{style}>{c.word}</th>')
    for row in rows:
        tds = []
        for c in cols:
            if not isinstance(c, Col):
                c = Col(c[0], key=c[1] if len(c) > 1 else "")
            cell = c.draw(row) if c.draw else esc(row.get(c.word, ""))
            cls = f' class="{c.kind}"' if c.kind else ""
            tds.append(f'<td{cls}>{cell}</td>')
        body.append(f'<tr>{"".join(tds)}</tr>')
    return (
        '<div class="tscroll"><table class="grid">'
        f'<thead><tr>{"".join(head)}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody>'
        '</table></div>'
    )


# --------------------------------------------------------------- containers
def panel(title: str, body: str, sub: str = "", tools: str = "",
          open_: bool = True, flush: bool = False, collapsible: bool = False) -> str:
    """The one container.  `flush` drops the padding for a table that fills it."""
    head_bits = [f'<h2>{title}</h2>']
    if sub:
        head_bits.append(f'<span class="sub">{sub}</span>')
    if tools:
        head_bits.append(f'<span class="tools">{tools}</span>')
    head = f'<div class="head">{"".join(head_bits)}</div>'
    cls = "panel"
    if collapsible:
        return (f'<details class="{cls}"{" open" if open_ else ""}>'
                f'<summary class="head">{"".join(head_bits)}</summary>'
                f'<div class="body{" flush" if flush else ""}">{body}</div></details>')
    return (f'<section class="{cls}">{head}'
            f'<div class="body{" flush" if flush else ""}">{body}</div></section>')


def note(text: str, warn: bool = False) -> str:
    """A caveat: the sentence that stops a reader misreading the panel under it."""
    cls = "note warn" if warn else "note"
    return f'<p class="{cls}"><span>&#9432;</span><span>{text}</span></p>'


def hint(text: str) -> str:
    return f'<p class="hint">{text}</p>'


def empty(text: str) -> str:
    return f'<p class="empty">{text}</p>'


def kv(pairs) -> str:
    """The worker's own file: a label and a value, no interpretation."""
    rows = "".join(
        f'<div><dt>{k}</dt><dd>{v}</dd></div>' for k, v in pairs
    )
    return f'<dl class="kv">{rows}</dl>'


# --------------------------------------------------------------- controls
def field(label_html: str, control: str, width: str = "w-md", cls: str = "") -> str:
    """One filter: its label above, its control below, one width per kind."""
    return (f'<label class="f {width} {cls}"><span class="lbl">{label_html}</span>'
            f'{control}</label>')


def text_input(name: str, value: str = "", placeholder: str = "") -> str:
    return (f'<input type="text" name="{esc(name)}" value="{esc(value)}"'
            f' placeholder="{esc(placeholder)}" spellcheck="false" autocomplete="off">')


def number_input(name: str, value, min_: int = 0, max_: int = 0) -> str:
    lim = f' min="{min_}"' if min_ else ""
    lim += f' max="{max_}"' if max_ else ""
    return f'<input type="number" name="{esc(name)}" value="{esc(value)}"{lim} inputmode="numeric">'


def select(name: str, options, value: str = "", labeler=None) -> str:
    """A select box.  `options` is a list of strings, or of `(value, word)` pairs."""
    out = []
    for o in options:
        if isinstance(o, (tuple, list)):
            val, word = o[0], (labeler(o[1]) if labeler else o[1])
        else:
            val, word = o, (labeler(o) if labeler else o)
        sel = ' selected' if str(val) == str(value) else ""
        out.append(f'<option value="{esc(val)}"{sel}>{word}</option>')
    return f'<select name="{esc(name)}">{"".join(out)}</select>'


def multi(name: str, chosen, options, placeholder: str = "") -> str:
    """A multi-value axis: the chosen values are chips, the box adds one.

    Four axes (`tree`, `arch`, `defconfig`, `compiler`) accept several values at
    once, and a row of tick boxes for 48 trees is a wall.  A chip box says what is
    chosen in the width of one field and keeps the other 44 values behind it.
    """
    tags = "".join(
        f'<span class="tag">{esc(v)}<button type="button" data-drop="{esc(v)}" '
        f'aria-label="remove {esc(v)}">&times;</button></span>'
        for v in chosen
    )
    menu = "".join(
        f'<button type="button" data-add="{esc(o)}"'
        f'{" aria-selected=true" if o in chosen else ""}>{esc(o)}</button>'
        for o in options if o not in chosen
    )
    return (f'<div class="multi" data-name="{esc(name)}">'
            f'<div class="box">{tags}'
            f'<input type="text" placeholder="{esc(placeholder)}" '
            f'aria-label="{esc(name)}" autocomplete="off"></div>'
            f'<div class="menu" hidden>{menu}</div></div>')


def checkbox(name: str, label_html: str, checked: bool = False) -> str:
    return (f'<label class="f cb"><input type="checkbox" name="{esc(name)}"'
            f'{" checked" if checked else ""}><span class="lbl">{label_html}</span></label>')


def seg(name: str, options, value: str = "") -> str:
    """An either/or: the worker's mode, a page's own toggle."""
    out = []
    for val, word in options:
        ck = " checked" if str(val) == str(value) else ""
        out.append(f'<label><input type="radio" name="{esc(name)}" value="{esc(val)}"{ck}>'
                   f'<span>{word}</span></label>')
    return f'<span class="seg">{"".join(out)}</span>'


def btn(word_html: str, kind: str = "", title: str = "", name: str = "") -> str:
    """A button.  It does nothing in the prototype and says so, loudly and once."""
    cls = f'btn {kind}'.strip()
    attrs = f' class="{cls}"'
    if title:
        attrs += f' title="{esc(title)}"'
    if name:
        attrs += f' name="{esc(name)}"'
    return f'<button type="button"{attrs}>{word_html}</button>'


def link_btn(word_html: str, href: str, kind: str = "sm") -> str:
    return f'<a class="btn {kind}" href="{esc(href)}">{word_html}</a>'


def filters(fields_html, buttons_html: str = "") -> str:
    """The filter bar: every field, then the buttons that submit them."""
    tail = f'<span class="grow"></span>{buttons_html}' if buttons_html else ""
    return f'<form class="filters" method="get">{fields_html}{tail}</form>'


def spread() -> str:
    """The gap that pushes the buttons of a bar to its right edge."""
    return '<span class="grow"></span>'


def cpanel(chips_html: str, title: str = "", sub: str = "") -> str:
    """The row of numbers behind a page, in a panel of its own.

    Chips outside a container read as decoration; inside one they read as the
    page's own arithmetic, which is what they are - each one is the count of the
    rows a link goes to.
    """
    return panel(title, chips_html, sub=sub)


def chips(items) -> str:
    """The numbers behind a page: a word, a number, and the file it came from."""
    out = []
    for label_html, value, title in items:
        out.append(
            f'<a class="chip" href="#" title="{esc(title)}">'
            f'<span class="k">{label_html}</span>'
            f'<span class="v">{esc(value)}</span></a>'
        )
    return f'<div class="chips">{"".join(out)}</div>'


def actions(buttons_html: str, blurb_html: str = "") -> str:
    """A row of buttons with the sentence that says what running them costs."""
    if not blurb_html:
        return f'<div class="row tight">{buttons_html}</div>'
    return (f'<div class="row"><span class="row tight">{buttons_html}</span>'
            f'<span class="hint" style="margin:0">{blurb_html}</span></div>')


def foot(d: dict, extra: str = "") -> str:
    """What the page read and when - the line that makes a stale page obvious."""
    src = ", ".join(f'<code>{esc(p)}</code>' for p in d["drawn_from"])
    return (f'<p class="foot"><span>{both("shell.read_from")} {src}</span>'
            f'<span>{both("shell.drawn")} <code>{esc(d["drawn"])}</code></span>'
            f'<span class="grow"></span>{extra}</p>')
