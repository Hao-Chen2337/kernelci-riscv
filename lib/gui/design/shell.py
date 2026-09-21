# SPDX-License-Identifier: LGPL-2.1-or-later
"""The whole page: the top bar, the live panel, the body, and the two bridges.

`document()` is the only writer of `<html>` in this package, so the head, the
stylesheet and the scripts are in one place and a screen module returns a fragment.
It emits the design's chrome - the top bar with the brand, the five stations, the
live chip, the two switches a reader owns (language, theme) and the refresh control -
then the live activity panel, then `<main>` with the page, then the footer line and
`#notice`.

**The hooks in here are a contract with code this file may not change.**  The poll
script (`script._JS`) is the shipped one and two node suites drive it:
`docs/gui-rework/tools/test_dom.js` and `test_notice.js` fetch it out of `lib.gui` and
assert what it writes.  The markup below therefore keeps `body[data-drawn]`,
`details.live#live` as a **direct child of `<body>`**, `summary.live-tab`,
`span.live-word`, `b.live-headword`, `span.live-count`, `div.live-body`,
`ul.live-list`, `p.live-empty`, `.spin`, `<div id="notice" role="status"
aria-live="polite">` as a **sibling** of the panel (never inside `.live-body`), and
`<script>{_js(...)}{_JS}</script>` written exactly as `_js()` returns it -
`test_notice.js` parses `var I18N = …;` out of it with a regular expression, so
re-formatting or re-serialising that output breaks a suite.

**The panel is drawn here and re-drawn by the script, so the two row shapes must
agree.**  `live_row()` writes the same cells, in the same order, with the same classes
as the script's own `liveRow()` - a panel that changed shape two seconds after the
page was drawn would be a second, disagreeing answer to "what is running".

The design's own live strip is `ul.acts > li.act` and it is not used here: the script
owns that list, and what it builds is `.live-list > li.live-row`.  `BRIDGE_CSS` is
therefore what styles the script's names - `.live-row`, `.live-id`, `.live-time`,
`.live-what`, `.live-argv`, `.live-act`, `.live-exit`, `.live-line`, `.live-empty`,
`.spin`, `.notice*`, `.kind-group`, `td.group-first` and the rest - with the design's
tokens and the board's own values, so the row a reader sees first and the row the poll
writes back are the same row.  The alternative was editing those markup strings inside
`_JS`, and that is the one thing this file may not do: `_JS` is the string
`test_dom.js` runs and `test_notice.js` parses, `check_hooks.py` reads its selectors
out of it, and the cells it writes are asserted against these builders cell by cell -
so the script's names are bridged here rather than the script rewritten to the
design's.

`BRIDGE_JS` is the other bridge and it closes a real gap: the design writes both
languages into every word (`words.both`) and into three attributes beside it
(`words.attr`: `title`, `aria-label`, `placeholder`), and expects a client-side switch
- but the shipped `_JS` reads none of `[data-i18n]`, knows no `#theme`, and does not
wire a chip box.  So this file carries that script too (a port of the board's, not a
second design): **the four-mode swap**, the theme button, and the `data-add`/`data-drop`
behaviour of a multi-valued axis.  It runs from the last element of `<body>`, which is
before the first paint, so a reader arriving on `?lang=zh` sees Chinese rather than a
flash of English.

The swap lives here rather than in `script._JS` because it is only ever needed by this
file's markup - the swap, the theme button and the chips are this layer's own
`data-i18n` shape and nothing else in the console writes one - and because `_JS` is
frozen by the two suites that drive it.  `_JS` is inlined byte for byte, which is also
what `test_notice.js` parses.

Two deliberate departures from the board's chrome, both named where they happen:
the **language switch is a link** rather than the board's pair of radio buttons (the
console has a `?lang=` and a `kci_lang` cookie, the acceptance gate follows an
`<a hreflang="en">` back out of a Chinese page, and a reader with the script off must
be able to change language at all - `lang_switch()` has the whole argument), and the
**refresh control** with the age of what was read sits in the top bar's tools, because
the board has no such control and a page shown without the age of its data is a page
pretending it just asked (`docs/gui-rework/01-perf.md` §D2).

**A comment inside `BRIDGE_CSS` must not spell a tag an acceptance check looks for.**
`accept.py` reads the raw body with `re` before any parser sees it, so the numbers
strip's wrapper written out in a comment *was* a numbers strip to its S6 check, with
no chip inside it.
"""

import html
import json
import time
from collections.abc import Iterable

from ... import api as api_mod
from ...i18n import LANGS, t
from ..schema import LIVE_KEPT, NAV_KEYS
from ..urls import _url
from . import style, ui, words
from .script import _JS, _js
from .words import both

# route -> the navigation key of its own name.  The order is the board's, which is the
# order a reader walks the tool in: what upstream built, what has not run, what is
# running it, what did run, and how it is trending.
STATIONS = (
    ("/", "nav.builds"),
    ("/jobs", "nav.jobs"),
    ("/worker", "nav.worker"),
    ("/runs", "nav.runs"),
    ("/analysis", "nav.analysis"),
)

# The design's own favicon: a data-URI, because this page has to open with no network.
FAVICON = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' "
           "viewBox='0 0 16 16'><rect width='16' height='16' rx='3' fill='%232f5bd0'/>"
           "<text x='8' y='12' font-size='9' font-family='monospace' fill='white' "
           "text-anchor='middle'>k</text></svg>")


def station(route: str) -> str:
    """Which station a route belongs to: its own path, or the one it hangs off.

    `/local/<id>` is the builds page's own detail route and `/analysis/<id>` hangs
    off `/analysis`, so the navigation marks the station a reader is *in* rather than
    none at all, and both carry that station's conditions.
    """
    for name, _key in STATIONS:
        if route == name or (name != "/" and route.startswith(name + "/")):
            return name
    return "/"


def nav(view) -> str:
    """The five stations, the current one marked, each carrying what it reads.

    The current station is a link to itself rather than a `<b>`: the design colours
    `nav a[aria-current="page"]`, and a reader who clicks the page they are on gets
    the page again - which is what a navigation bar means everywhere else.
    """
    here = station(view.route)
    carry = NAV_KEYS.get(here, ())
    parts = []
    for route, key in STATIONS:
        current = ' aria-current="page"' if route == here else ""
        href = html.escape(view.url(route, carry=carry))
        parts.append(f'<a href="{href}"{current}>{both(view.lang, key)}</a>')
    return (f'<nav class="nav" {words.attr(view.lang, "aria-label", "shell.pages")}>'
            f'{"".join(parts)}</nav>')


def lang_switch(view, keep: Iterable[tuple[str, str]] = ()) -> str:
    """The language switch: one link per language, each spelling its own `?lang=`.

    A link and not the board's pair of radio buttons, and that is the one place the
    design's markup is deliberately not used.  The design switches language in the
    page (its own script moves every `data-i18n` element); this console has a
    `?lang=` and a `kci_lang` cookie, the acceptance gate follows an
    `<a hreflang="en">` back out of a Chinese page (N3), and a reader with the script
    off must still be able to change language.  Both are satisfied by a real URL, and
    the swap in `BRIDGE_JS` is then only what shows the *response's* language.

    Every href spells the language out, the default included, and it is written with
    `_url` rather than `view.url()` for one reason: `View.url()` speaks for the
    language this response is drawn in, and this is the single link whose whole job is
    to ask for the other one.
    """
    parts = []
    for one in LANGS:
        href = html.escape(_url(view.route, view.check, keep=keep, lang=one,
                                 spell_lang=True))
        current = ' aria-current="true"' if one == view.lang else ""
        text = html.escape(t(one, f"lang.{one}"))
        parts.append(f'<a href="{href}" hreflang="{one}" lang="{one}"{current}>{text}</a>')
    return (f'<span class="seg" role="group" '
            f'{words.attr(view.lang, "aria-label", "shell.lang")}>{"".join(parts)}</span>')


def theme_button(view) -> str:
    """The reader's own choice of ground, in the design's third state (`auto`).

    `auto` is the OS's choice and is what the stylesheet does with no `data-theme` at
    all; `BRIDGE_JS` moves it to the reader's stored choice before the first paint and
    cycles it on a click.
    """
    return (f'<button type="button" class="btn sm" id="theme" '
            f'{words.attr(view.lang, "title", "shell.theme_title")}>&#9680; '
            f'<span id="theme-word">{html.escape(t(view.lang, "theme.auto"))}</span></button>')


def live_chip(running: int, lang: str) -> str:
    """The top bar's one live fact: how many activities are running, and a way there.

    The same two elements the panel's tab carries (`.spin`, `.live-word`), so the poll
    keeps both in step with one rule and one number - and the number comes from the
    same rows the panel was drawn from, so a chip and a panel cannot disagree at
    render time.
    """
    word = t(lang, "live.tab_running", n=running) if running else t(lang, "live.tab_idle")
    spin = ('<span class="spin" aria-hidden="true"'
            + ("" if running else " hidden") + "></span>")
    return (f'<a class="live-chip{" idle" if not running else ""}" href="#live">'
            f'{spin}<span class="live-word">{html.escape(word)}</span></a>')


def refresh(view) -> str:
    """The one control that re-reads the page, and the age of what it last read.

    A link and not a button: every page here is a GET whose URL *is* its state, so
    "ask again" is this URL with `fresh=1` in it.  The age beside it is not
    decoration - an answer served from the cache and shown without its age is a page
    pretending it just asked (`docs/gui-rework/01-perf.md` §D2), so the number is
    printed and the `title=` names the TTL it was given.
    """
    age = api_mod.read_age()
    when = (both(view.lang, "refresh.now") if age is None or age < 1
            else both(view.lang, "refresh.age", age=_ago(age)))
    return (f'<a class="btn sm" href="{html.escape(view.url("", fresh="1"))}" '
            f'{words.attr(view.lang, "title", "refresh.title", ttl=_ago(api_mod.request_ttl()))}>'
            f'{both(view.lang, "btn.refresh")}</a>'
            f'<span class="pill idle">{when}</span>')


def _ago(seconds: float) -> str:
    """A number of seconds as a reader says it: `5s`, `3m`, `2h`."""
    whole = max(0, int(seconds or 0))
    if whole < 60:
        return f"{whole}s"
    if whole < 3600:
        return f"{whole // 60}m"
    return f"{whole // 3600}h"


def topbar(view, running: int, keep: Iterable[tuple[str, str]] = ()) -> str:
    """The one bar: who this is, which station, and the switches the reader owns."""
    return ('<header class="topbar">'
            '<span class="brand"><span class="mark">kci</span>'
            f'<span class="name">{both(view.lang, "shell.brand")}</span></span>'
            f"{nav(view)}"
            f'<span class="tools">{live_chip(running, view.lang)}'
            f"{refresh(view)}{lang_switch(view, keep)}{theme_button(view)}</span>"
            "</header>")


def activity(one: dict) -> dict:
    """One activity row, in either of the two shapes this tree hands the panel.

    `design/data.py`'s `activities` are the prototype's rows - `run_id`, `exit`,
    `argv` as the one copyable string, `age` as the elapsed time - and the engine's
    `Gui.run_rows()` rows, which the old shell's panel reads, are `id`, `exit_code`,
    `argv` as a list, `seconds`.  The panel is drawn from whichever shape the page was
    handed, so the two spellings are read **once, here**, and the row below never has
    to ask: a row that read `argv` as a list when it is a string would print
    `p u l l _ w o r k e r . p y`, one letter per column.

    `seconds` is the duration the script's `liveTime()` prints and `age` is the
    data layer's coarser "how long ago it started"; the cell prefers the first and
    falls back to the second, so the panel is drawn from what the row carries.
    """
    argv = one.get("argv") or ()
    return {
        "id": one.get("id") or one.get("run_id") or "",
        "state": str(one.get("state") or ""),
        "what": str(one.get("what") or ""),
        "argv": argv if isinstance(argv, str) else " ".join(str(part) for part in argv),
        "exit": one.get("exit_code", one.get("exit")),
        "seconds": one.get("seconds"),
        "age": str(one.get("age") or ""),
        "started": one.get("started") or 0,
    }


def live_row(one: dict, lang: str) -> str:
    """One activity: state, elapsed, what it is, its command line, and its two acts.

    The cells, their order and their classes are the script's own (`liveRow()` in
    `_JS`), because that function rewrites this list every two seconds and a row that
    changed shape when it refreshed is a row nobody can read while something runs.

    The pill is the *state's* colour with the *exit code's* word (`ui.end_word`): a run
    that finished every test it started and failed some of them says `incomplete
    (infra)`, not `failed` - the word a crashed command gets - while it stays the
    colour of the state on disk, which is also the class the script writes for it.
    """
    one = activity(one)
    state = one["state"]
    ended = state != "running"
    code = one["exit"]
    exit_word = (t(lang, "live.exit", code=ui.esc(code)) if code is not None
                 else t(lang, "live.exit_unknown"))
    argv = one["argv"]
    home = html.escape(str(one["id"]))
    elapsed = ui.duration(one["seconds"]) if one["seconds"] is not None else one["age"]
    acts = (f'<a href="/runs/{home}/log" target="_blank" rel="noopener">'
            f'{html.escape(t(lang, "link.log"))}</a>')
    if not ended:
        acts += (f'<form method="post" action="/api/runs/{home}/cancel">'
                 f'<button class="btn">{html.escape(t(lang, "js.cancel"))}</button></form>')
    return ('<li class="live-row ' + ("ended" if ended else "running") + '"'
            f' data-id="{home}" data-started="{float(one.get("started") or 0):.3f}"'
            f' data-state="{html.escape(state)}">'
            '<div class="live-line">'
            + ("" if ended else '<span class="spin" aria-hidden="true"></span>')
            + ui.pill(state, label=ui.end_word(state, code, lang), lang=lang)
            + f'<code class="live-id">{home}</code>'
            + f'<span class="live-time num">{html.escape(elapsed)}</span></div>'
            + f'<div class="live-what">{html.escape(one["what"][:80])}</div>'
            + f'<code class="live-argv" title="{html.escape(argv)}">{html.escape(argv)}</code>'
            + '<div class="live-act">'
            + (f'<span class="live-exit">{exit_word}</span>' if ended else "")
            + acts + "</div></li>")


def live(view) -> str:
    """What is running now, and what just ended - the shell's own panel.

    **Drawn by the server, not built by the script**, which is the point: a panel that
    exists only after a successful `fetch` shows nothing exactly when a reader wants
    it.  The script's job is to update this list, never to create it.

    `open` follows the facts: something running means the panel is already out, so the
    reader sees it without a click, and a quiet page does not spend a screenful on an
    empty list.  Nothing is computed - a row is an activity on disk, and "recently
    ended" is the first `LIVE_KEPT` rows of the same list that are not running.
    """
    rows = list(view.rows.get("activities") or ())
    running = [one for one in rows if one.get("state") == "running"]
    ended = [one for one in rows if one.get("state") != "running"][:LIVE_KEPT]
    body = "".join(live_row(one, view.lang) for one in (*running, *ended))
    head = t(view.lang, "live.head_running" if running else "live.head_recent")
    word = (t(view.lang, "live.tab_running", n=len(running)) if running
            else t(view.lang, "live.tab_idle"))
    spin = ('<span class="spin" aria-hidden="true"'
            + ("" if running else " hidden") + "></span>")
    return ('<details class="live" id="live"' + (" open" if running else "") + ">"
            f'<summary class="live-tab">{spin}'
            f'<span class="live-word">{html.escape(word)}</span></summary>'
            '<div class="live-body"><div class="live-head">'
            + spin
            + f'<b class="live-headword">{html.escape(head)}</b>'
            + f'<span class="live-count">{len(running)}</span>'
            # Rendered `hidden` and unhidden by the script only where the browser
            # really has the Notification API: a button that does nothing because the
            # origin is not a secure context is a worse lie than no button, and it
            # never prompts on its own - the click is the gesture.
            + '<button class="btn sm live-notify" type="button" data-notify="1" hidden>'
            + f'{html.escape(t(view.lang, "live.notify_off"))}</button></div>'
            + f'<ul class="live-list">{body}</ul>'
            + f'<p class="live-empty"{" hidden" if body else ""}>'
            + f'{html.escape(t(view.lang, "live.none"))}</p>'
            + '<noscript><p class="q">' + html.escape(t(view.lang, "live.noscript"))
            + "</p></noscript>"
            + "</div></details>")


def document(view, body: str, keep: Iterable[tuple[str, str]] = (),
             banners: str = "") -> str:
    """The whole file: head, top bar, panel, the page, the footer, the scripts.

    `keep` is the page state that is not a filter field (the worker's mode, the runs
    page's kind and state): the language switch has to carry it - `serve.py`'s
    `PAGE_STATE` is what collects it, one route at a time - or switching language
    would answer a question the reader did not ask.

    `banners` is what this *request* ran into - an API that did not answer, a writer
    that blocks a write - and it goes above the body, which is where the old shell put
    it too.  It is an argument rather than something read out of `view.rows`: a banner
    is about the request and not about the page's data.

    The digest that rides to the script is the local state this answer was drawn from
    (`lib.gui.server._state_digest`), and it is what makes the poll re-read the page
    when something writes.  It is imported lazily: this module is the design layer's
    entry point and pulling an HTTP server module into it at import time would make
    every screen pay for a server it does not use.
    """
    from ..server import _state_digest
    rows = list(view.rows.get("activities") or ())
    running = len([one for one in rows if one.get("state") == "running"])
    title = t(view.lang, dict(STATIONS)[station(view.route)])
    # The machine-first front door the old layer offered, kept as a link in the foot:
    # a path and not a word, so it reads the same in both languages.
    summary = '<a href="/summary.json">summary.json</a>'
    return f"""<!doctype html>
<html lang="{html.escape(view.lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kernelci-riscv &mdash; {html.escape(title)}</title>
<link rel="icon" href="{FAVICON}">
<style>{style.CSS}{BRIDGE_CSS}</style>
</head>
<body data-drawn="{time.time():.3f}">
{topbar(view, running, keep)}
{live(view)}
<main class="wrap">
{banners}{body}
{ui.foot(view.rows, extra=summary, lang=view.lang)}
</main>
<div id="notice" role="status" aria-live="polite"></div>
<script>{_js(view.lang, _state_digest())}{_JS}</script>
<script>{_bridge()}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# The bridge stylesheet: the names this page's script owns.
#
# The design board draws its live strip, its activity table and its chips with its
# own markup, and on this console three of those are drawn by `_JS` and by the
# acceptance gate instead - so the class names in them are not the design's and
# `style.py` (extracted from the board, and re-checked against it by
# `tools/design_extract.py --check`) cannot carry their rules.  Every rule below is
# therefore one of three things, and nothing else:
#
#   1. the script's own vocabulary, given the design's look - `.live-row` and its
#      cells, `.live-body`, `.live-head`, `.live-empty`, `.spin`, `table.grid`'s
#      `td.num` / `td.wrap` / `td.act` / `.cell-actions` / `.tally`, `tr.kind-group`,
#      `.kind-group`, `td.group-first`, `.notice`, `#notice`, `.status`, and the two
#      elements the value rail adds (`.rail`, `.railout`);
#   2. the two names the acceptance gate reads in the numbers strip - the strip's own
#      wrapper and the chip's number - which are the design's `.chips` row and its
#      `.chip .v` value under the names the gate looks for;
#   3. the handful of `hidden` attributes that need saying out loud, because an author
#      rule that gives an element a `display` beats the `hidden` attribute whatever
#      its specificity - `.f.cb` is `display: flex`, so a select-all box rendered
#      `hidden` would otherwise be visible before the script wired it, and a box that
#      ticks nothing is a lie.
#
# `_JS` as shipped draws the panel and the runs table, and every name it writes is
# either a name the design already styles or one of the bridges below - no rule here
# touches a class the board owns.
BRIDGE_CSS = """
/* 1. The live panel.  The board draws this strip in the flow at the top of a screen
   (`.live`, `style.py`), and the panel here is the same box: one body, one head row,
   one list of activities.  It is a direct child of <body> (the contract `_JS` and
   `test_notice.js` share), so it gets the wrap's own measure back by hand. */
body > .live { width: calc(100% - 32px); max-width: 1648px; margin: 12px auto 0;
               overflow: hidden; }
body > .live > summary { color: var(--ink-mid); }
.live-body { background: var(--surface); }
.live-head { display: flex; align-items: center; gap: 9px;
             padding: 8px 12px; border-bottom: 1px solid var(--line-soft);
             font-size: 12.5px; }
.live-head .live-count { margin-left: auto; color: var(--ink-soft);
                         font-variant-numeric: tabular-nums; }
.live-list { display: flex; flex-direction: column; }
.live-row { padding: 7px 12px; border-top: 1px solid var(--line-soft); }
.live-row:first-child { border-top: 0; }
.live-row.ended { color: var(--ink-soft); }
.live-line { display: flex; align-items: center; gap: 10px; }
.live-id { font-family: var(--mono); font-size: 11.5px; color: var(--ink-mid); }
.live-time { margin-left: auto; font-family: var(--mono); font-size: 11.5px;
             color: var(--ink-soft); }
.live-what { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis;
             white-space: nowrap; }
.live-argv { display: block; max-width: 100%; font-family: var(--mono);
             font-size: 11px; color: var(--ink-soft); white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; }
.live-act { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.live-act .btn, .live-act form { margin: 0; }
.live-act .btn { padding: 2px 7px; font-size: 11.5px; }
/* The log link is written bare by the script (`<a href="/runs/<id>/log">`), so it is
   given the design's small button look here rather than a class it does not carry. */
.live-act > a { display: inline-flex; align-items: center; padding: 2px 7px;
                font-size: 11.5px; color: var(--ink-mid); background: var(--surface);
                border: 1px solid var(--line); border-radius: var(--r-sm); }
.live-act > a:hover { border-color: var(--accent); color: var(--accent);
                      text-decoration: none; }
.live-exit { font-family: var(--mono); font-size: 11.5px; color: var(--ink-soft); }
.live-empty { padding: 18px 12px; text-align: center; color: var(--ink-soft);
              font-size: 12.5px; }
/* The `<noscript>` line: the design's muted `.q`, not the board's deleted `.note`
   (its screens draw no caveat component any more). */
.live-body noscript p { margin: 10px 12px; }

/* The ring the script toggles is the board's `.pulse`: one fact ("something is
   running"), so one look.  `[hidden]` is spelled out because the `hidden` attribute
   loses to any author rule that gives the element a `display`. */
.spin { width: 6px; height: 6px; border-radius: 50%; background: var(--info);
        flex: 0 0 auto; animation: pulse 1.6s ease-in-out infinite; }
.spin[hidden], .live-empty[hidden], .live-notify[hidden] { display: none; }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }

/* The header chip wears the same two elements as the panel's tab; when nothing runs
   it is the quiet pill and the script hides the dot. */
.live-chip { color: var(--info); background: var(--info-soft); border-color: var(--info); }
.live-chip.idle { color: var(--idle); background: var(--idle-soft);
                  border-color: var(--line); box-shadow: none; }
.live-chip.idle .spin { display: none; }

/* **The pill in the script's own vocabulary.**  `_JS` writes `<span class="{state}
   pill">` - the *value's* word for the class, which is the old layer's pill
   vocabulary (`PILL_WORDS` in `schema.py`: every verdict, every run state, every
   evidence state and every job state) - while the design colours `.pill.ok`,
   `.warn`, `.bad`, `.info`, `.idle`.  Without the rules below, every pill the poll
   redrew would lose its colour while the server-drawn pill beside it kept one: the
   same row, two looks, changing on the first tick.  The grouping is `ui.STATE`'s,
   available, so the two vocabularies are one colour per word. */
.pill.pass, .pill.done, .pill.pulled { color: var(--ok); background: var(--ok-soft);
        border-color: var(--ok); }
.pill.fail, .pill.failed, .pill.error { color: var(--bad); background: var(--bad-soft);
        border-color: var(--bad); }
.pill.incomplete, .pill.unrecorded, .pill.reserved, .pill.closing {
        color: var(--warn); background: var(--warn-soft); border-color: var(--warn); }
.pill.running, .pill.available, .pill.registered { color: var(--info);
        background: var(--info-soft); border-color: var(--info); }
.pill.cancelled, .pill.idle, .pill.empty, .pill.bytes, .pill.made-here {
        color: var(--idle); background: var(--idle-soft); border-color: var(--line); }
/* `_pill`'s answer to an empty value: a dash, no fill. */
.pill.none { color: var(--ink-soft); background: none; border-color: var(--line); }

/* 2. The activity table.  `drawTable` re-renders `/runs` every 2 s with the old
   layer's cell classes (`id`, `num`, `wrap`, `act`, `cell-actions`) because it also
   re-renders the old layer's table, so those names are given the design's own look
   (`id`, `n`, `trunc`, `acts-cell`).  `td.act` must not inherit the board's `.act`
   grid - it is a table cell that happens to share a word with the live strip's row. */
table.grid td.num, table.grid th.num { text-align: right;
        font-variant-numeric: tabular-nums; font-family: var(--mono); font-size: 11.5px; }
table.grid td.wrap { white-space: normal; min-width: 160px; max-width: 340px; }
table.grid td.act { display: table-cell; white-space: nowrap; }
table.grid td.act > a, table.grid td.act > form { margin-right: 6px; }
table.grid .cell-actions { display: inline-flex; align-items: center; gap: 6px; }
table.grid .tally { margin-left: 6px; color: var(--ink-soft); font-size: 11.5px;
                    font-variant-numeric: tabular-nums; }
.kind-group { display: block; font-size: 11px; font-weight: 600; letter-spacing: .05em;
              text-transform: uppercase; color: var(--ink-soft); }
td.group-first { border-top: 2px solid var(--line); }
/* **The script draws a caption row the server does not.**  `drawTable` writes
   `<tr class="kind-group">` *and* the `<span class="kind-group">` in the first cell of
   the group's first row, which is the shape `runs.py` writes; the server writes only
   the span.  The row is the same words as the span directly under it, so it is hidden:
   the reader sees one caption per group, exactly as drawn, and the row count keeps
   meaning "one row per activity".  Deleting the block from `drawTable` is the honest
   fix and it is not available: `_JS` is what the two node suites drive. */
table.grid tr.kind-group { display: none; }

/* 3. The numbers strip.  The gate reads two names in it - the strip's wrapper and the
   chip's number - and the board styles its own two (`.chips`, `.chip .v`).  Same row,
   same type, under the names the gate knows.

   **A comment in this file must not spell a tag the gate's regular expressions look
   for.**  `accept.py` reads the raw body with `re` before any parser sees it, so the
   strip's wrapper written out in a comment here *is* a numbers strip to that check -
   it matched this block and found no chip inside it.  Names, not tags. */
.numbers { display: flex; flex-wrap: wrap; gap: 8px; }
.chip .n { font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums;
           letter-spacing: -.02em; }

/* 4. The controls the design has no markup for: the language switch (a `seg` of
   links, where the board has a `seg` of radio buttons), the value rail the script
   inserts beside a number box, and the status line a POST answers into. */
.seg a { padding: 4px 9px; font-size: 11.5px; color: var(--ink-mid);
         border-left: 1px solid var(--line); background: var(--surface); }
.seg a:first-child { border-left: 0; }
.seg a:hover { text-decoration: none; }
.seg a[aria-current="true"] { background: var(--accent-soft); color: var(--accent);
                              font-weight: 500; }
.f > .rail { width: 100%; height: 16px; margin-top: 2px; padding: 0;
             accent-color: var(--accent); background: transparent; }
.f > .railout { font-size: 11px; color: var(--ink-soft);
                font-variant-numeric: tabular-nums; }
.f > .railout[data-off="1"] { color: var(--warn); }
@media (max-width: 700px) { .f > .rail, .f > .railout { display: none; } }
.status { font-size: 12px; color: var(--ink-soft); }
.status:empty { display: none; }
.status.bad { color: var(--bad); }

/* 5. The finish notice: what ended while the page was open, announced once.  It is
   fixed in a corner of its own and empty means absent, so a quiet page carries no box
   and no gap.  It is NOT inside `.live-body`: that element is the panel's body, and a
   message about a finish must be readable with the panel closed. */
#notice { position: fixed; right: 16px; bottom: 16px; z-index: 31;
          display: flex; flex-direction: column; gap: 8px; width: min(380px, 92vw); }
#notice:empty { display: none; }
.notice { display: flex; align-items: center; gap: 8px; margin: 0;
          padding: 8px 12px; font-size: 12.5px; line-height: 1.4;
          color: var(--ok); background: var(--ok-soft); border: 1px solid var(--ok);
          border-radius: var(--r); box-shadow: var(--shadow-pop); }
/* Three colours, three truths: an exit code the run really reported (by its value),
   a code nobody saw, and an id that is no longer on disk.  The last two are `warn`,
   never `failed` - `Run._settle` maps a code it never learned to `failed`, and a
   notice may not repeat a claim nobody can check. */
.notice.failed { color: var(--bad); background: var(--bad-soft); border-color: var(--bad); }
.notice.unknown, .notice.cancelled { color: var(--warn); background: var(--warn-soft);
                                     border-color: var(--warn); }
.notice .btn { margin-left: auto; padding: 2px 7px; font-size: 11.5px; }
.notice a { margin-left: 4px; }

/* 6. The `hidden` attributes that need saying out loud: an author rule beats the
   attribute, and a control the script has not wired yet must not be visible. */
.f.cb[hidden], input[type="checkbox"][hidden] { display: none; }
"""


# The words this script writes itself, in both columns: the three theme names and the
# `×`'s accessible label.  They are injected as JSON, exactly as `_js()` injects
# `I18N`, so the script holds no copy of a translation and a word added to the
# catalogue reaches it without touching JavaScript.
_BRIDGE_KEYS = (("", "theme.auto"), ("light", "theme.light"), ("dark", "theme.dark"))


def _bridge() -> str:
    """`BRIDGE_JS` with the words it writes in front of it."""
    # `</` is broken up for the same reason `_js()` breaks it up: no translation can
    # be allowed to close the element it lives in.
    blob = json.dumps({"themes": {name: [t(one, key) for one in ("en", "zh")]
                                  for name, key in _BRIDGE_KEYS},
                       "remove": [t(one, "filter.remove") for one in ("en", "zh")]},
                      ensure_ascii=False).replace("</", "<\\/")
    return f"var BRIDGE = {blob};\n" + BRIDGE_JS


BRIDGE_JS = """
// The three behaviours the design's own page carries and this console's shipped
// script does not.  `_JS` is about live activity - the poll, the notice, the action
// bars, the rails - and it reads none of `[data-i18n]`, `#theme` or `.multi`; the
// board's own script reads all three.  This is that script's three parts, ported -
// and the first of them is four modes, not one, because the board writes
// `data-i18n="text"` 352 times and `aria-label`/`title`/`placeholder` 79 times.
//
// It runs from the last element of <body>: every element it touches is already parsed,
// and nothing has been painted yet, so a reader who asked for Chinese does not see a
// flash of English first.
(function () {
  "use strict";
  var root = document.documentElement;
  // The attribute, not the reflected `root.lang` property: what the server wrote is
  // one place to look, and it is the same thing a stub can answer.
  function lang() { return root.getAttribute("lang") === "zh" ? "zh" : "en"; }
  function pair(one) { return lang() === "zh" ? one[1] : one[0]; }

  // --- 1. the language, in the four modes the markup uses ------------------
  // Every visible word is in the markup twice (`words.both`), and so is every
  // attribute a reader reads (`words.attr`): an element carries `data-i18n` naming
  // *which* of the four it is, and the pair to move into it.  There is no `html`
  // mode: the design deleted it, and `words.both` refuses a value that would need
  // one, so a swap here is always `textContent` or `setAttribute` and never markup.
  var ATTRS = ["title", "placeholder", "aria-label"];
  document.querySelectorAll("[data-i18n]").forEach(function (el) {
    var text = el.getAttribute(lang() === "zh" ? "data-zh" : "data-en");
    if (text === null) { return; }
    var kind = el.getAttribute("data-i18n");
    if (ATTRS.indexOf(kind) >= 0) { el.setAttribute(kind, text); }
    else { el.textContent = text; }
  });

  // --- 2. the theme -------------------------------------------------------
  // auto -> light -> dark, remembered.  `auto` is the reader who has chosen nothing,
  // which is the stylesheet's own state: no `data-theme` at all, so the OS decides.
  // The choice is applied here rather than by the server because it is the reader's
  // and not the request's - and here, rather than in the stylesheet, because only a
  // script can read what they stored.
  var THEMES = ["", "light", "dark"];
  var word = document.getElementById("theme-word");
  function themeWord() {
    if (!word) { return; }
    var name = root.getAttribute("data-theme") || "";
    word.textContent = pair(BRIDGE.themes[name] || BRIDGE.themes[""]);
  }
  function setTheme(name) {
    if (name) { root.setAttribute("data-theme", name); }
    else { root.removeAttribute("data-theme"); }
    themeWord();
    try { localStorage.setItem("kci-theme", name); } catch (err) { /* private window */ }
  }
  var stored = "";
  try { stored = localStorage.getItem("kci-theme") || ""; } catch (err) { /* ditto */ }
  if (THEMES.indexOf(stored) < 0) { stored = ""; }
  setTheme(stored);
  var button = document.getElementById("theme");
  if (button) {
    button.addEventListener("click", function () {
      setTheme(THEMES[(THEMES.indexOf(stored) + 1) % THEMES.length]);
      stored = root.getAttribute("data-theme") || "";
    });
  }

  // --- 3. the pager's jump box --------------------------------------------
  // A reader has a page number in mind; the URL carries `offset`, and a plain GET cannot
  // multiply.  So the form is rendered `hidden` and this unhides it - with the script
  // off, a control that cannot work would be a lie - and the conversion happens on
  // submit, into the `offset` field the form already carries.
  document.querySelectorAll("form[data-pager]").forEach(function (form) {
    var box = form.querySelector("input.pjump");
    var field = form.querySelector('input[name="offset"]');
    if (!box || !field) { return; }
    form.hidden = false;
    form.addEventListener("submit", function () {
      var limit = Number(box.getAttribute("data-limit")) || 1;
      var last = Number(box.getAttribute("data-pages")) || 1;
      var page = Math.min(last, Math.max(1, Number(box.value) || 1));
      field.value = String((page - 1) * limit);
    });
  });

  // --- 4. the chip box ----------------------------------------------------
  // A multi-valued axis (`tree`, `arch`, `defconfig`, `compiler`) is a box of chips
  // plus a menu of the values it may also name.  The chips are the *filter*: each one
  // carries a hidden input under the axis's name, so what the reader sees and what the
  // form submits are the same set.  A chip added here is added the same way the server
  // draws one, which is why the hidden input is created and not only the visible tag -
  // a chip that submitted nothing would be a filter that looks applied and is not.
  function boxInput(box) { return box.querySelector('.box input[type="text"]'); }
  function renderMenu(box) {
    var menu = box.querySelector(".menu");
    if (!menu) { return; }
    var chosen = {};
    box.querySelectorAll(".tag").forEach(function (tag) {
      chosen[tag.getAttribute("data-v")] = 1;
    });
    var input = boxInput(box);
    var query = (input && input.value ? input.value : "").trim().toLowerCase();
    var shown = 0;
    menu.querySelectorAll("button[data-add]").forEach(function (item) {
      var value = item.getAttribute("data-add");
      var hit = !chosen[value] && (!query || value.toLowerCase().indexOf(query) >= 0);
      item.hidden = !hit;
      if (hit) { shown += 1; }
    });
    menu.hidden = !shown;
  }
  function addChip(box, value) {
    var tags = box.querySelectorAll(".tag"), i;
    for (i = 0; i < tags.length; i += 1) {
      if (tags[i].getAttribute("data-v") === value) { return; }
    }
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.setAttribute("data-v", value);
    tag.appendChild(document.createTextNode(value));
    var hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = box.getAttribute("data-name") || "";
    hidden.value = value;
    tag.appendChild(hidden);
    var drop = document.createElement("button");
    drop.type = "button";
    drop.setAttribute("data-drop", value);
    drop.setAttribute("aria-label", pair(BRIDGE.remove).replace("{value}", value));
    drop.innerHTML = "&times;";
    tag.appendChild(drop);
    var input = boxInput(box);
    box.querySelector(".box").insertBefore(tag, input);
    if (input) { input.value = ""; }   // the value is a chip now, not a typed name
    renderMenu(box);
  }
  function dropChip(box, value) {
    box.querySelectorAll(".tag").forEach(function (tag) {
      if (tag.getAttribute("data-v") === value) { tag.remove(); }
    });
    renderMenu(box);
  }
  function wireBox(box) {
    var input = boxInput(box);
    if (!input) { return; }
    input.addEventListener("focus", function () { renderMenu(box); });
    input.addEventListener("input", function () { renderMenu(box); });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        // Enter takes the first offer, the way a combobox does.  The default action
        // of Enter in a text box is to submit the bar, and adding a chip is not a
        // decision to submit - `apply` is.
        ev.preventDefault();
        var first = box.querySelector(".menu button[data-add]:not([hidden])");
        if (first) { addChip(box, first.getAttribute("data-add")); }
      } else if (ev.key === "Escape") {
        box.querySelector(".menu").hidden = true;
        input.blur();
      }
    });
    box.addEventListener("click", function (ev) {
      var add = ev.target.closest("[data-add]");
      if (add) { addChip(box, add.getAttribute("data-add")); return; }
      var drop = ev.target.closest("[data-drop]");
      if (drop) { dropChip(box, drop.closest(".tag").getAttribute("data-v")); }
    });
  }
  document.querySelectorAll(".multi").forEach(wireBox);
  // One open menu at a time: a click anywhere else closes what is open, which is what
  // makes the box usable with the mouse without a second click to dismiss it.
  document.addEventListener("click", function (ev) {
    document.querySelectorAll(".multi").forEach(function (box) {
      if (box.contains(ev.target)) { return; }
      var menu = box.querySelector(".menu");
      if (menu) { menu.hidden = true; }
    });
  });
})();
"""
