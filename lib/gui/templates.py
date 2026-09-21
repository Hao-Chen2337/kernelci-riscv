# SPDX-License-Identifier: LGPL-2.1-or-later
"""The page's own front end: the stylesheet, the poll script, and the one template.

`_PAGE` is the document every page is a `<main>` of - its three load-bearing details
(`<details id="live">` a direct child of `<body>`, `#notice` its sibling, `data-drawn`
the moment the answer was drawn) are explained where they are written.  `_CSS` is the
one stylesheet: no `@import`, no CDN, no web font, no image, because the page has to
open on a machine with no network.  `_JS` is the poll script, and `_js()` puts the
words it writes in front of it as `I18N`, out of `_JS_WORDS` - so the script and the
server print the same sentence in the same language.

**The script re-renders the activity table and the live panel, and the cells it
writes are `_runs_table`'s and `_live_row`'s, written a second time in JavaScript.**
That duplication is deliberate and load-bearing - a table that changes shape when it
refreshes is a table nobody can read while something is running - so the two are kept
in step by hand and neither may be "simplified" into the other.  Nothing here reads a
page's data: this module is strings and the one function that fills them in."""

import json

from .. import errors, layout
from ..i18n import DEFAULT_LANG, t
from .schema import LIVE_KEPT
from .widgets import _end_word, _tally_words

# ---------------------------------------------------------------------------
# Rendering only
# ---------------------------------------------------------------------------

_CSS = """
/* The one stylesheet.  No @import, no CDN, no web font, no image: the page has
   to open on a machine with no network.  Fonts come from the system stack.
   Chrome / Firefox / Safari of 2026; `position: sticky` is used, `:has()` is not.
   Comments here are English like the rest of the tree; the numbers are measured,
   not eyeballed - see the contrast note under the tokens. */

/* ---------------------------------------------------------------------------
   1. Tokens: every colour is named here and nowhere else.  The dark theme swaps
   tokens only, never a selector: a selector missed in one theme is one unreadable
   element with no second way to notice it.

   Measured contrast (ink on background), light: ok 7.95  bad 7.48  warn 6.62
   err 7.39  info 7.22  idle 8.09  body 15.31  muted 6.00 - all above AA 4.5:1,
   which the 11.5px pill needs.  Dark: ok 9.82  bad 9.27  warn 9.59  err 9.21
   info 8.83  idle 8.12  body 14.90.  Changing a colour means recomputing these.
   A manual theme switch would be a second thing to persist; not this round.
   --------------------------------------------------------------------------- */
:root {
  color-scheme: light dark;

  /* Body text in a sans stack, anything a machine reads in a mono one.  The CJK
     fallbacks are spelled out: some systems pick a very ugly CJK mono first. */
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue",
          "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;

  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px;
  --r: 6px;             /* the one corner radius; pills use 999px, nothing else */
  --max: 1500px;        /* reading width: eleven columns fit without folding */
  --head-h: 96px;       /* the sticky header's height; thead sticks below it.
                           Change this whenever .site-head changes height, or the
                           header row slides under the navigation. */

  --bg: #f5f6f8; --fg: #1b1f24; --muted: #5a6472; --line: #d7dce2;
  --card: #ffffff; --card-2: #f1f3f6; --hl: #eaf1fd;
  --link: #0b4a8f; --focus: #1a5fb4;

  --ok-ink: #0f5132;   --ok-bg: #dbf2e4;   --ok-bd: #93d3ae;
  --bad-ink: #842029;  --bad-bg: #fbdede;  --bad-bd: #f0a9a9;
  --warn-ink: #7a4b00; --warn-bg: #fdf1d8; --warn-bd: #e6c583;
  --err-ink: #6d2a86;  --err-bg: #f3e3fa;  --err-bd: #d4aee4;
  --info-ink: #0b4a8f; --info-bg: #ddeafc; --info-bd: #a9c9ef;
  --idle-ink: #41474d; --idle-bg: #eceef1; --idle-bd: #c9ced4;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131619; --fg: #e6e9ec; --muted: #9aa4af; --line: #2b3138;
    --card: #1a1e22; --card-2: #22272c; --hl: #1d2b3f;
    --link: #7cb0f0; --focus: #7cb0f0;

    --ok-ink: #8ff0b4;   --ok-bg: #13351f;   --ok-bd: #2f6b45;
    --bad-ink: #ffb4b4;  --bad-bg: #3a1a1a;  --bad-bd: #7a3a3a;
    --warn-ink: #ffd28a; --warn-bg: #3a2c10; --warn-bd: #7a5c22;
    --err-ink: #e2b6f5;  --err-bg: #2f1a3a;  --err-bd: #6b3f80;
    --info-ink: #a8cdf7; --info-bg: #122a45; --info-bd: #2f5a86;
    --idle-ink: #c3c8ce; --idle-bg: #2a2e33; --idle-bd: #474d54;
  }
}

/* ---------------------------------------------------------------------------
   2. The ground: body text in sans, ids and paths and commands in mono
   --------------------------------------------------------------------------- */
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 14px/1.5 var(--sans); }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

code, .mono { font-family: var(--mono); }
code { padding: 0 4px; font-size: .92em; background: var(--card-2);
       border: 1px solid var(--line); border-radius: 4px; white-space: nowrap; }
.id, td.id code { font-size: 12.5px; white-space: nowrap; }
.argv { display: inline-block; padding: 2px 6px; }

:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }

/* ---------------------------------------------------------------------------
   3. Header / meta line / main / sections
   --------------------------------------------------------------------------- */
.site-head { position: sticky; top: 0; z-index: 20;
             background: var(--card); border-bottom: 1px solid var(--line); }
.site-head .in { display: flex; flex-wrap: wrap; align-items: baseline;
                 gap: var(--s1) var(--s4); max-width: var(--max);
                 margin: 0 auto; padding: var(--s2) var(--s4); }
.site-head h1 { margin: 0; font-size: 16px; font-weight: 650; letter-spacing: -.01em; }
.site-head h1 .sub { font-size: 13px; font-weight: 400; color: var(--muted); }

nav.pages { display: flex; flex-wrap: wrap; gap: 2px; }
nav.pages a, nav.pages b { padding: 3px 9px; font-size: 13px; border-radius: var(--r); }
nav.pages b { background: var(--hl); font-weight: 650; }
nav.pages a:hover { background: var(--card-2); text-decoration: none; }

/* The language slot is empty until the bilingual round wires it up: the space is
   reserved here so that round changes nothing about this layout. */
.lang { display: flex; gap: 6px; margin: 0 0 0 auto; font-size: 12.5px; }
.lang a[aria-current="true"] { font-weight: 700; text-decoration: underline; }

.meta { max-width: var(--max); margin: 0 auto; padding: var(--s2) var(--s4) 0;
        color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap;
        align-items: baseline; gap: var(--s1) var(--s3); }
main { max-width: var(--max); margin: 0 auto; padding: var(--s2) var(--s4) var(--s6); }

/* ---------------------------------------------------------------------------
   3b. The numbers: one chip per number, and the chip is the link.

   The counts line was three sentences with three absolute paths in them; this is
   the same information as seven pressable numbers.  `.k` is the noun, `.n` is the
   number: two elements and not one string, because no plural rule in this
   catalogue could agree `row`/`rows` with an arbitrary count, and the number has
   to line up under the number (that is what `tabular-nums` is for).
   --------------------------------------------------------------------------- */
.numbers { display: flex; flex-wrap: wrap; align-items: baseline;
           gap: var(--s1) var(--s3); margin: 0; }
.numbers .chip { display: inline-flex; align-items: baseline; gap: 5px;
                 padding: 1px 8px; border: 1px solid var(--line);
                 border-radius: 999px; background: var(--card); color: var(--fg); }
.numbers .chip .k { color: var(--muted); font-size: 11.5px; }
.numbers .chip .n { font-variant-numeric: tabular-nums; }
a.chip:hover { background: var(--hl); text-decoration: none; border-color: var(--focus); }

/* A badge: one short fact, its explanation in the tooltip.  This is the shape the
   page uses where it used to print a sentence (docs/gui-rework/05-i18n-prose.md
   §B.2), and `{n} without a card` under the pull bar is the first one. */
.badge { display: inline-block; padding: 0 7px; font-size: 11.5px; line-height: 1.6;
         border: 1px dashed var(--idle-bd); border-radius: 999px;
         background: var(--idle-bg); color: var(--idle-ink);
         font-variant-numeric: tabular-nums; }

h2 { margin: var(--s5) 0 var(--s2); font-size: 15px; font-weight: 650; }
h2 span { margin-left: var(--s2); font-size: 12.5px; font-weight: 400;
          color: var(--muted); }

.card { margin: 0 0 var(--s4); padding: var(--s3) var(--s4);
        background: var(--card); border: 1px solid var(--line);
        border-radius: var(--r); }

footer.site { max-width: var(--max); margin: var(--s5) auto 0;
              padding: var(--s3) var(--s4); font-size: 12px; color: var(--muted);
              border-top: 1px solid var(--line); }

/* ---------------------------------------------------------------------------
   4. The filter bar: one row, label above control, wrapping on a narrow screen.
      It is the page's only GET form.
   --------------------------------------------------------------------------- */
.toolbar { display: flex; flex-wrap: wrap; align-items: flex-end;
           gap: var(--s2) var(--s3); margin: 0 0 var(--s3);
           padding: var(--s2) var(--s3); background: var(--card);
           border: 1px solid var(--line); border-radius: var(--r); }

.field { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.field > label { font-size: 11px; color: var(--muted); letter-spacing: .02em; }
.field input, .field select { height: 30px; padding: 0 6px; font: inherit;
           font-size: 13px; color: var(--fg); background: var(--card);
           border: 1px solid var(--line); border-radius: 4px; }
.field.w-name input, .field.w-name select { min-width: 15ch; }
.field.w-num input { width: 8ch; text-align: right;
                     font-variant-numeric: tabular-nums; }
.field input::placeholder { color: var(--muted); opacity: .7; }
/* The multi-valued axes: one tick box per candidate, and a free box beside them
   (`fields._check_group`).  The candidate list scrolls instead of growing the bar -
   `tree` alone is fifty names - so the bar keeps its own height whatever a checkout's
   config declares, and the whole list is still there for a wheel or a Tab key.
   `display: block` deliberately overrides `.field`'s column: a `<fieldset>`'s own
   layout is special-cased in several engines, and the two rows inside it (the boxes,
   then the free box) need no flex of their own. */
.field.w-checks { display: block; border: 1px solid var(--line); border-radius: 4px;
                  padding: 4px 6px; }
.field.w-checks > legend { font-size: 11px; color: var(--muted); padding: 0 3px;
                           letter-spacing: .02em; }
.field.w-checks .checks { display: flex; flex-wrap: wrap; gap: 2px 8px;
                          max-height: 5.4em; overflow-y: auto; }
.field.w-checks .check { display: flex; align-items: center; gap: 3px; font-size: 12px;
                         white-space: nowrap; }
.field.w-checks .check input { height: 13px; width: 13px; padding: 0; min-width: 0; }
.field.w-checks .field.w-name { flex-direction: row; align-items: center; gap: 4px;
                                margin-top: 3px; }
.field.w-checks .field.w-name input { height: 24px; font-size: 12px; min-width: 12ch; }

.toolbar .spacer { flex: 1 1 auto; }
.quick { display: flex; align-items: center; gap: 4px; font-size: 12px; }
.quick .lead { color: var(--muted); }
.quick a { padding: 2px 8px; color: var(--muted);
           border: 1px solid var(--line); border-radius: 999px; }
.quick a:hover { background: var(--card-2); text-decoration: none; }
.quick a[aria-current="true"] { color: var(--fg); background: var(--hl);
                                border-color: var(--focus); }
/* A control this page must not offer (the worker's platforms a claim filter can name
   but the worker here cannot boot): the same slot, no link, no button, and the reason
   is the visible text (and its `title=` when it wraps). Dashed and dimmed so it reads
   as inert without becoming invisible - the value is still information. */
.off { padding: 2px 8px; color: var(--muted); opacity: .75;
       border: 1px dashed var(--line); border-radius: 4px;
       cursor: not-allowed; }
.quick span.off { border-radius: 999px; }

button, .btn { height: 30px; padding: 0 12px; font: inherit; font-size: 13px;
       cursor: pointer; color: var(--fg); background: var(--card-2);
       border: 1px solid var(--line); border-radius: 4px; }
button:hover, .btn:hover { border-color: var(--muted); text-decoration: none; }
button.primary { color: #fff; background: var(--focus); border-color: var(--focus); }
button[disabled] { opacity: .5; cursor: not-allowed; }
td .btn, td button { height: 24px; padding: 0 8px; font-size: 12px; }

/* A write action: the conditions it sends are visible as a command line and as a
   name/value list, so the button and the command cannot disagree. */
.actionbar { display: flex; flex-wrap: wrap; align-items: center;
             gap: var(--s2) var(--s3); margin: 0 0 var(--s3);
             padding: var(--s2) var(--s3); background: var(--card);
             border: 1px solid var(--line); border-radius: var(--r); }
.actionbar .field { flex: 1 1 auto; }
.actionbar details { flex: 1 1 100%; }

/* What the button's own POST answered.  One per form (`[data-status]`), written by
   the delegated submit listener in `_JS` - so two action bars on one page never
   share a line, and an empty one takes no room. */
.status { font-size: 12px; color: var(--muted); }
.status:empty { display: none; }
.status.bad { color: var(--bad-ink); }

/* ---------------------------------------------------------------------------
   5. What is in force: the axes strip, one `key: value` per axis a page reads -
      **including the ones at their default**, which is the whole point (`_axes`).
      The `×` is a rebuilt URL, not a handler; the number beside a value is how
      many rows that axis matched, and `dim` means it matched nearly all of them.
   --------------------------------------------------------------------------- */
.axes { display: flex; flex-wrap: wrap; align-items: baseline;
        gap: 0 var(--s3); margin: 0 0 var(--s2); font-size: 12px; }
.axes .ax { display: inline-flex; align-items: baseline; gap: 5px; padding: 1px 4px;
            border-bottom: 2px solid transparent; }
.axes .ax.set { border-bottom-color: var(--line); }   /* this axis is doing work */
.axes .k { color: var(--muted); }
.axes .v { font-variant-numeric: tabular-nums; }
.axes .v.any { color: var(--muted); }                 /* a default reads grey */
.axes .n { font-size: 11px; color: var(--ok-ink); font-variant-numeric: tabular-nums; }
.axes .n.dim { color: var(--muted); }                 /* matched almost everything */
.axes .x { padding: 0 3px; color: var(--muted); text-decoration: none;
           border-radius: 999px; }
.axes .x:hover { color: var(--bad-ink); background: var(--bad-bg); }

/* The cap's own cost, beside the cap.  Four numbers instead of the 45-word
   sentence that used to sit under four tables: `175 KB / 50 rows`, the API's own
   total, what no cap can show, and what this page's own filter dropped. */
.ofnum, .gap { display: inline-flex; flex-direction: column; line-height: 1.15;
               padding-bottom: 4px; }
.ofnum b, .gap b { font-size: 13px; font-variant-numeric: tabular-nums; }
.ofnum .sub, .gap .sub { font-size: 10.5px; color: var(--muted); }
.gap b { color: var(--warn-ink); }

/* `_rail`: a duplicate *view* of a control that is already a real box.  The box
   carries `name`, the rail does not, so the rail can never submit a second value
   and a page with this script off is exactly the page it was before the rail
   existed - there is no class to gate on, because the script creates the element. */
.field input.has-rail { border-top-right-radius: 0; border-bottom-right-radius: 0; }
.rail { width: 9ch; height: 30px; padding: 0; accent-color: var(--focus);
        background: transparent; border: 1px solid var(--line); border-left: 0;
        border-radius: 0 4px 4px 0; }
.railout { min-width: 4ch; padding-left: 4px; font-size: 12px;
           font-variant-numeric: tabular-nums; }
.railout[data-off="1"] { color: var(--warn-ink); }   /* typed, not a suggestion */
@media (max-width: 700px) { .rail, .railout { display: none; } }   /* box remains */

.chip { display: inline-flex; align-items: center; gap: 4px;
        padding: 1px 3px 1px 8px; font-size: 12px; background: var(--card);
        border: 1px solid var(--line); border-radius: 999px; }
.chip code { padding: 0; background: none; border: 0; }
.chip a { padding: 0 5px; color: var(--muted); border-radius: 999px; }
.chip a:hover { color: var(--bad-ink); background: var(--bad-bg);
                text-decoration: none; }

/* The activity table's group captions (`_runs_table(group=True)`, and the same
   markup in the script's re-render): the kind and its count, drawn as a block inside
   the first cell of each group's first row.  Not a `<tr>` of its own, so the number of
   rows on this page still means the number of activities. */
.kind-group { display: block; font-size: 11.5px; font-weight: 600; color: var(--muted);
              letter-spacing: .02em; }
td.group-first { border-top: 2px solid var(--line); }

/* ---------------------------------------------------------------------------
   6. Banners / query lines / empty states
   --------------------------------------------------------------------------- */
p.query, p.note { margin: 0 0 var(--s3); padding: var(--s1) var(--s3);
        font-size: 12.5px; color: var(--muted); background: var(--card-2);
        border-left: 3px solid var(--line); border-radius: 0 4px 4px 0; }
p.query code { padding: 0; background: none; border: 0; }

.banner { margin: 0 0 var(--s2); padding: var(--s2) var(--s3); font-size: 13px;
          border: 1px solid var(--line); border-radius: var(--r); }
.banner.bad { color: var(--bad-ink); background: var(--bad-bg);
              border-color: var(--bad-bd); }
.banner.busy { color: var(--info-ink); background: var(--info-bg);
               border-color: var(--info-bd); }
.bad { color: var(--bad-ink); }
.busy { color: var(--info-ink); }

.empty { margin: 0 0 var(--s3); padding: var(--s3) var(--s4); font-size: 13px;
         color: var(--muted); background: var(--card);
         border: 1px dashed var(--line); border-radius: var(--r); }
.empty b { color: var(--fg); }

details { margin: var(--s1) 0 0; }
summary { cursor: pointer; font-size: 12px; color: var(--muted); }
details table { margin-top: var(--s2); font-size: 12px; }

/* A clamped number is said out loud and is not an error: a hand-edited URL is a
   normal way of asking.  The class name is part of the page's contract. */
.capped { color: var(--warn-ink); }

/* ---------------------------------------------------------------------------
   7. Tables.  No scroll wrapper on purpose: `overflow-x` would make the wrapper
      the scroll container and the sticky `thead` would stop sticking to the
      page.  Wide columns wrap (`td.wrap`), they do not scroll sideways.
   --------------------------------------------------------------------------- */
table { width: 100%; border-collapse: separate; border-spacing: 0;
        font-size: 13px; background: var(--card);
        border: 1px solid var(--line); border-radius: var(--r); }

thead th { position: sticky; top: var(--head-h); z-index: 10;
        padding: var(--s2); font-size: 11.5px; font-weight: 600;
        color: var(--muted); text-align: left; white-space: nowrap;
        background: var(--card); border-bottom: 1px solid var(--line); }

tbody td { padding: 3px var(--s2); border-bottom: 1px solid var(--line);
        vertical-align: top; white-space: nowrap; max-width: 34ch;
        overflow: hidden; text-overflow: ellipsis; }
tbody tr:nth-child(even) td { background: var(--card-2); }
tbody tr:hover td { background: var(--hl); }   /* after the zebra rule, so it wins */
tbody tr:target td { box-shadow: inset 3px 0 0 var(--focus); }
tbody tr:last-child td { border-bottom: 0; }

td.wrap, th.wrap { min-width: 22ch; max-width: 52ch; white-space: normal;
        overflow: visible; text-overflow: clip; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.act { white-space: nowrap; }
.cell-actions { display: flex; align-items: center; gap: var(--s1); }

/* Column shape, by table name and position: one place decides it, so a caller
   does not have to put a class on every cell.  `td.wrap`/`td.num` are for the
   odd cell that differs from its column. */
table.jobs td:nth-child(1), table.queue td:nth-child(1),
table.pulls td:nth-child(2), table.ledger td:nth-child(1),
table.runs td:nth-child(1) { font-family: var(--mono); }
table.jobs td:nth-child(5), table.queue td:nth-child(2), table.remote-detail td:nth-child(6),
table.card-fields td:nth-child(2), table.pulls td:nth-child(7), table.bytes td:nth-child(2) {
    white-space: normal; overflow: visible; text-overflow: clip; max-width: 52ch; }

/* The merged builds table, and the trap this block exists for: the three tables it
   replaces are gone, so *their* `nth-child` rules would point at the wrong columns -
   `table.local td:nth-child(6)` was that table's correspondence cell and is this
   one's bytes cell, and `table.remote td:nth-child(1)` is the tick box here, not an
   id.  A column is a shape by position, and the positions changed.  Walked against
   the nine cells `_builds` draws:

     1 tick (a box: no shape)        2 build_id (mono, nowrap - a `code` that wraps
     loses the alignment the short ids are read by)   3 tree / branch (wraps)
     4 created (nowrap)              5 card (wraps: `act: node …` is a fragment)
     6 bytes (nowrap: `.artifacts` keeps the artifact set on one line)
     7 act (wraps: hosts, a time and a `failed` pill)
     8 api says (wraps)              9 ran (pills, nowrap)

   The old class names stay on the table as *aliases* (`cls="builds remote local"`,
   because the row probe of the operator's own acceptance script counts this table by
   its class) and an alias carries no shape - which is why `remote`, `local` and
   `pull` are absent from the two rules above: an alias that carried shape would
   fight this block, which is exactly the trap the plan recorded. */
table.builds td:nth-child(2) { font-family: var(--mono); }
table.builds td:nth-child(3), table.builds td:nth-child(5), table.builds td:nth-child(7),
table.builds td:nth-child(8) {
    white-space: normal; overflow: visible; text-overflow: clip; max-width: 52ch; }
table.builds td:nth-child(6), table.builds td:nth-child(9) { white-space: nowrap; }
table.timeline-rows td:nth-child(5) { min-width: 24ch; }
/* A URL is one long word: inside a wrapping cell it has to be allowed to break,
   or `code`'s own `nowrap` would push the table wider than the screen. */
td.wrap code { white-space: normal; overflow-wrap: anywhere; }

/* ---------------------------------------------------------------------------
   8. States and verdicts: pills.  The second class is the word the code already
      uses (pass / running / pulled …), so JavaScript keeps no second vocabulary
      and both themes colour it from the tokens.
   --------------------------------------------------------------------------- */
.pill { display: inline-block; padding: 0 7px; font-size: 11.5px; line-height: 1.6;
        white-space: nowrap; font-variant-numeric: tabular-nums;
        border: 1px solid var(--idle-bd); border-radius: 999px;
        background: var(--idle-bg); color: var(--idle-ink); }

/* verdict pass / run done / evidence pulled / job available */
.pill.pass, .pill.done, .pill.pulled, .pill.available {
        border-color: var(--ok-bd); background: var(--ok-bg); color: var(--ok-ink); }
/* verdict fail / run failed */
.pill.fail, .pill.failed {
        border-color: var(--bad-bd); background: var(--bad-bg); color: var(--bad-ink); }
/* verdict incomplete / evidence unrecorded / job reserved, closing */
.pill.incomplete, .pill.unrecorded, .pill.reserved, .pill.closing {
        border-color: var(--warn-bd); background: var(--warn-bg); color: var(--warn-ink); }
/* verdict error: it must not look like fail, or the two are not told apart */
.pill.error {
        border-color: var(--err-bd); background: var(--err-bg); color: var(--err-ink); }
/* run running / evidence registered */
.pill.running, .pill.registered {
        border-color: var(--info-bd); background: var(--info-bg); color: var(--info-ink); }
/* run cancelled / evidence made-here, empty, bytes / a value with no word of its own.
   `bytes` is the one evidence value that is not a `Local.state`: it is a filter over
   the download tree (`?evidence=bytes`), and it is coloured as a plain fact rather
   than as a verdict - having bytes is neither good nor bad news. */
.pill.cancelled, .pill.made-here, .pill.empty, .pill.none, .pill.idle, .pill.bytes {
        border-color: var(--idle-bd); background: var(--idle-bg); color: var(--idle-ink); }
.pill.empty { border-style: dashed; }
.pill.none { color: var(--muted); background: none; }

/* The ledger's tally beside a pill (`_end_cell`): the counts the pill cannot carry,
   in the muted ink and at the pill's own size, so the cell reads as one fact - how
   this activity ended - with the numbers that say whether it did any work. */
.tally { color: var(--muted); font-size: 11.5px; margin-left: var(--s2);
         font-variant-numeric: tabular-nums; white-space: nowrap; }

/* The artifacts a copy holds, and the ones it does not: one line, no commas. */
.artifacts { display: inline-flex; gap: var(--s2); white-space: nowrap; }
.artifacts .no { color: var(--muted); opacity: .7; }

/* The regression timeline: one block per run, a pass -> fail point ringed.
   Each block is a link now (`_timeline`), because a `<span>` with a `title` is inert
   with JavaScript on *and* off - `这个不能选` was literal.  The link is stripped of its
   underline and takes the surrounding colour, so the strip of squares still reads as
   one chart and not as a row of links; the hover/focus outline is what says it can be
   clicked, and the selected one is marked by `aria-current`. */
.timeline { display: inline-flex; align-items: center; gap: 3px; }
.timeline .point { font-size: 12px; line-height: 1; }
.timeline a.point { text-decoration: none; color: inherit; cursor: pointer; }
.timeline a.point:hover, .timeline a.point:focus { outline: 1px solid var(--focus); }
.timeline a.point[aria-current] { background: var(--hl); border-radius: 2px; }
.timeline .point.regressed { outline: 2px solid currentColor; outline-offset: 1px;
        border-radius: 2px; }

/* The regression chart (`_wave_chart`): one column per position of the page's order,
   three lanes under it.  The verdict colours are the `.pill` ones, so a pass is the
   same green in the chart and in the table - two verdict palettes would be two
   verdicts.  A gap is dashed and empty, the convention `table.bars .bar.gap` already
   uses for a comparison that was not made.  Widths are classes, never inline styles;
   `min-width` keeps 50 slots readable and the wrapper scrolls on a narrow screen
   rather than wrapping, because a wrapped strip stops being an axis. */
.wave-wrap { overflow-x: auto; }
table.wave { border-collapse: collapse; width: 100%; min-width: 640px;
        table-layout: fixed; }
table.wave th { font-size: 11px; font-weight: 600; text-align: right; color: var(--muted);
        padding: 0 6px 0 0; width: 6ch; }
table.wave td { padding: 0; border: 0; text-align: center; font-size: 12px;
        border-bottom: 0; }
table.wave td.num { color: var(--muted); white-space: nowrap; }
table.wave .point { display: block; line-height: 1.35; text-decoration: none;
        color: inherit; }
table.wave .point.pass       { background: var(--ok-bg);   color: var(--ok-ink); }
table.wave .point.fail       { background: var(--bad-bg);  color: var(--bad-ink); }
table.wave .point.incomplete { background: var(--warn-bg); color: var(--warn-ink); }
table.wave .point.error      { background: var(--err-bg);  color: var(--err-ink); }
table.wave .point.gap, table.wave td.empty { border: 1px dashed var(--line);
        background: none; color: var(--muted); }
table.wave .point[aria-current] { outline: 2px solid var(--focus); outline-offset: -2px; }
table.wave .point:hover, table.wave .point:focus { outline: 2px solid var(--focus);
        outline-offset: -2px; }

/* The regression line chart (`_trend_lines`): **the tree's first SVG**, and the
   reason for it is in that function - a segment joining two points at different
   heights has no table-cell spelling, and every other picture here is a table.
   Four things this block is careful about:

   * the colours are the verdict tokens and nothing new (`--ok/bad/warn/err`), because
     these are the verdict colours of every pill on the page and a second verdict
     palette would be a second verdict;
   * **colour is not the only carrier.**  The four status inks do not separate as a
     categorical palette.  Rendered against this page's own surface, the check that
     measures it (`validate_palette.js "#0f5132,#842029,#7a4b00,#6d2a86"`, light mode)
     FAILS them: fail against pass is ΔE 4.7 under deuteranopia, fail against
     incomplete is 11.1 with full colour vision.  So every series also has its own
     **dash pattern** - solid, dotted, dashed, and a heavier solid - its own marker
     radius, and a name in the key row;
   * strokes and dash patterns live here and never in a `style=`, the rule
     `_bar_chart`'s width classes keep; the geometry that must be per-point (`cx`,
     `cy`, `r`) is an attribute because a coordinate is not a style;
   * `min-width` keeps the axis text at a readable size and the wrapper scrolls rather
     than folding the axis - the trade `.wave-wrap` already makes.  The box is scaled
     uniformly (`height: auto`), so a marker stays a circle, and
     `vector-effect: non-scaling-stroke` keeps a 2px line 2px at every width. */
.lines-wrap { overflow-x: auto; }
svg.trend-lines { display: block; width: 100%; min-width: 640px; max-width: 1000px;
        height: auto; font-family: var(--sans); }
svg.trend-lines text { fill: var(--muted); font-size: 10px; }
svg.trend-lines text.axis-name { font-weight: 600; }
svg.trend-lines .axis { stroke: var(--line); stroke-width: 1; }
svg.trend-lines .grid { stroke: var(--line); stroke-width: 1; opacity: .55; }
/* The gap rug: the same dashed mark a gap cell carries in `table.wave`, one mark per
   position the ledger has nothing for - so a flat line and a missing run are not the
   same picture.  Drawn as one `<path>` of short horizontal strokes, not one per gap. */
svg.trend-lines .rug { stroke: var(--line); stroke-width: 5; stroke-dasharray: 2 4; }
svg.trend-lines .line { fill: none; stroke-width: 2; stroke-linejoin: round;
        stroke-linecap: round; vector-effect: non-scaling-stroke; }
svg.trend-lines .marker { stroke: var(--card); stroke-width: 1; }
/* The hit target: unpainted and larger than the marker, so a 2.6-unit dot is still a
   click. `pointer-events: all` because an unpainted shape is not otherwise a target. */
svg.trend-lines .hit { fill: none; stroke: none; pointer-events: all; }
svg.trend-lines a { cursor: pointer; }
svg.trend-lines a:hover .marker, svg.trend-lines a:focus .marker,
svg.trend-lines a[aria-current] .marker { stroke: var(--focus); stroke-width: 2.5; }
svg.trend-lines .line.pass        { stroke: var(--ok-ink); }
svg.trend-lines .marker.pass      { fill: var(--ok-ink); }
svg.trend-lines .line.incomplete  { stroke: var(--warn-ink); stroke-dasharray: 1 3; }
svg.trend-lines .marker.incomplete { fill: var(--warn-ink); }
svg.trend-lines .line.fail        { stroke: var(--bad-ink); stroke-dasharray: 6 3; }
svg.trend-lines .marker.fail      { fill: var(--bad-ink); }
/* The emphasised series: heavier than the other three, and its markers are larger -
   told apart from `pass` (solid too) by weight before it is told apart by colour. */
svg.trend-lines .line.error       { stroke: var(--err-ink); stroke-width: 3.5; }
svg.trend-lines .marker.error     { fill: var(--err-ink); }
/* The key row: name, count, and a swatch that carries the series' own stroke.  In the
   muted ink like every other label - the colour is on the swatch, never on the text. */
.lines-key { display: flex; flex-wrap: wrap; align-items: baseline;
        gap: var(--s1) var(--s4); margin: 0 0 var(--s2); font-size: 12px;
        color: var(--muted); }
.lines-key .k { display: inline-flex; align-items: center; gap: 6px;
        font-variant-numeric: tabular-nums; }
.lines-key .sw { width: 22px; border-top-width: 2px; border-top-style: solid; }
.lines-key .pass .sw { border-color: var(--ok-ink); }
.lines-key .incomplete .sw { border-color: var(--warn-ink); border-top-style: dotted; }
.lines-key .fail .sw { border-color: var(--bad-ink); border-top-style: dashed; }
.lines-key .error .sw { border-color: var(--err-ink); border-top-width: 3.5px; }
/* A delta that opens the comparison it names: the number is the door, so it has to
   look pressable without becoming a second colour in a cell full of numbers. */
a.delta-door { text-decoration: none; color: inherit; cursor: pointer; }
a.delta-door:hover, a.delta-door:focus { outline: 1px solid var(--focus); }
a.delta-door.none { color: var(--muted); }

/* ---------------------------------------------------------------------------
   8b. `/analysis`: one list, its sort, its +/-, and its chart.
      The list is a table whose rows are links (`table.picks`), so the two things the
      old select boxes could not do - two lines per row, and a `title` on the full id -
      are possible; and the delta column is a column of *values*, so it wraps instead
      of being clipped by the 34ch rule on `tbody td`.
   --------------------------------------------------------------------------- */
table.picks td, table.delta-list td, table.drift td { white-space: normal;
        overflow: visible; text-overflow: clip; max-width: 60ch; }
table.picks td.num, table.picks td.act, table.picks td.delta { white-space: nowrap; }
table.picks tr.nocfg td { color: var(--muted); }
/* A group break in `sort=same-branch`, drawn as a rule rather than as a caption row:
   the row already names its own tree/branch, so the break is the only thing missing. */
table.picks tr.group td { border-top: 2px solid var(--line); }

/* The delta: `+added` is a green figure and `-removed` a red one, because that is what
   the two mean to a reader comparing two configs; `~changed` is neither.  A refusal is
   muted with a dotted underline - it is a fact about the pair, not an error of ours -
   and the two regression arrows say "more failing" / "fewer" rather than "plus/minus",
   because for failures the sign and the verdict point opposite ways. */
.delta, .delta-list .delta { font-variant-numeric: tabular-nums; }
.delta .plus { color: var(--ok-ink); }
.delta .minus { color: var(--bad-ink); }
.delta .tilde, .delta .zero { color: var(--muted); }
.delta .none, .delta .bad { color: var(--muted); }
.delta .bad { border-bottom: 1px dotted var(--warn-bd); }
.delta-up { color: var(--bad-ink); }
.delta-down { color: var(--ok-ink); }

/* The chart of the list above: one row per comparison, in the same order, so the eye
   can walk down both.  The width is a class (`w0`..`w20`, a 5% step) and never an
   inline style: the quantum is decided once here, the exact number is printed in the
   last cell, and a third colour would be a third class. */
table.bars { width: 100%; font-size: 12px; }
table.bars th { text-align: left; font-weight: 400; font-family: var(--mono);
        white-space: nowrap; }
table.bars td { border-bottom: 0; padding: 2px var(--s2); }
table.bars .bar { display: inline-block; height: 10px; vertical-align: middle;
        background: var(--info-bg); border: 1px solid var(--info-bd); border-radius: 2px; }
table.bars .bar.gap { background: none; border-style: dashed; }
.w0 { width: 0 }     .w1 { width: 5% }    .w2 { width: 10% }   .w3 { width: 15% }
.w4 { width: 20% }   .w5 { width: 25% }   .w6 { width: 30% }   .w7 { width: 35% }
.w8 { width: 40% }   .w9 { width: 45% }   .w10 { width: 50% }  .w11 { width: 55% }
.w12 { width: 60% }  .w13 { width: 65% }  .w14 { width: 70% }  .w15 { width: 75% }
.w16 { width: 80% }  .w17 { width: 85% }  .w18 { width: 90% }  .w19 { width: 95% }
.w20 { width: 100% }

/* The two-line label of a row, the three marks beside it, and the run's own row. */
.marks { display: inline-flex; gap: var(--s2); font-size: 11.5px; color: var(--muted);
        white-space: nowrap; }
.marks .yes { color: var(--ok-ink); }
.marks .no { color: var(--muted); opacity: .8; }
table.runs-list td.wrap, table.record-fields td { white-space: normal;
        overflow: visible; text-overflow: clip; max-width: 60ch; }
table.runs-list tr.selected td { background: var(--hl); }
table.record-fields th { width: 10ch; font-weight: 600; color: var(--muted);
        vertical-align: top; white-space: nowrap; }

/* ---------------------------------------------------------------------------
   9. Narrow screens: fields go to one column, the header grows, and --head-h
      grows with it (the sticky thead depends on that number).
   --------------------------------------------------------------------------- */
@media (max-width: 900px) {
  :root { --head-h: 120px; }
  .field { flex: 1 1 44%; }
  .field.w-num { flex: 0 0 auto; }
  .field.w-name input { width: 100%; min-width: 0; }
  .site-head .in { gap: 2px var(--s3); }
  .meta { font-size: 11.5px; }
}

@media (max-width: 600px) {
  :root { --head-h: 168px; }
  .field { flex: 1 1 100%; }
  body { font-size: 13.5px; }
  table { font-size: 12.5px; }
  .actionbar { gap: var(--s1) var(--s2); }
}

/* ---------------------------------------------------------------------------
   10. The live panel: what is running now, and what just ended (`_live_panel`).
       A `<details>`, because opening and closing it has to work with JavaScript
       off and because a `<summary>` is a disclosure a keyboard and a screen
       reader already know.  Two fixed boxes: the summary is the tab that stays
       put, `.live-body` is the part that slides out from the right.

       Nothing between `.live-body` and `<body>` may carry a `transform` or a
       `filter`: that would make `position: fixed` mean "fixed to that ancestor",
       and the tab would slide away with the panel it is supposed to be the
       handle of (`_PAGE` says the same thing on the markup side).

       The tab wears the `running` pill's own two tokens (section 8): "there is a
       live activity" is one fact, so it is one colour, and the spinner beside it
       is the same fact again - which is why neither is a new palette entry.
   --------------------------------------------------------------------------- */
.live > summary { position: fixed; z-index: 30; top: var(--head-h); right: 0;
        display: flex; align-items: center; gap: 6px; list-style: none;
        padding: var(--s1) var(--s3); font-size: 12px;
        color: var(--info-ink); background: var(--info-bg);
        border: 1px solid var(--info-bd); border-right: 0;
        border-radius: var(--r) 0 0 var(--r); cursor: pointer; }
.live > summary::-webkit-details-marker { display: none; }
.live > summary:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
.live[open] > summary { border-bottom: 0; }

.live-body { position: fixed; z-index: 29; top: var(--head-h); right: 0; bottom: 0;
        width: min(380px, 92vw); display: flex; flex-direction: column;
        background: var(--card); border-left: 1px solid var(--line);
        box-shadow: -8px 0 24px rgba(0, 0, 0, .08); overflow: hidden; }
.live[open] > .live-body { animation: live-in .18s ease-out both; }
@keyframes live-in { from { transform: translateX(100%); } to { transform: none; } }

.live-head { display: flex; align-items: center; gap: var(--s2);
        padding: var(--s2) var(--s3); font-size: 13px;
        border-bottom: 1px solid var(--line); }
.live-head .live-count { margin-left: auto; color: var(--muted);
        font-variant-numeric: tabular-nums; }
.live-list { flex: 1 1 auto; overflow: auto; margin: 0; padding: 0; list-style: none; }
.live-row { padding: var(--s2) var(--s3); border-bottom: 1px solid var(--line); }
.live-row.ended { color: var(--muted); }
.live-line { display: flex; align-items: center; gap: var(--s2); }
.live-id { font-size: 12px; }
.live-time { margin-left: auto; color: var(--muted);
        font-variant-numeric: tabular-nums; font-size: 12px; }
.live-what { margin: 2px 0; font-size: 12.5px; }
.live-argv { display: block; max-width: 100%; font-size: 12px; white-space: nowrap;
        overflow: hidden; text-overflow: ellipsis; }
.live-act { display: flex; align-items: center; gap: var(--s2); margin-top: var(--s1); }
.live-act .btn { height: 22px; padding: 0 6px; font-size: 12px; }
.live-exit { font-size: 12px; }
.live-body .note { margin: var(--s2) var(--s3); }

/* The panel is an overlay, so on a wide screen the page makes room for it rather
   than sitting under it.  Below 1100px it covers content on purpose: the tab
   closes it, and a 380px column beside a twelve-column table helps nobody. */
@media (min-width: 1100px) {
  .live[open] ~ main, .live[open] ~ footer.site {
        padding-right: calc(min(380px, 92vw) + var(--s4)); }
}

/* The header's live chip: the same fact as the panel's tab, one line, always
   visible.  Tokens are the `running` pill's, so the chip and the panel agree
   without a second palette entry. */
.live-chip { display: inline-flex; align-items: center; gap: 6px; padding: 1px 8px;
        font-size: 12px; color: var(--info-ink); background: var(--info-bg);
        border: 1px solid var(--info-bd); border-radius: 999px; }
.live-chip:hover { text-decoration: none; border-color: var(--focus); }
.live-chip.idle { color: var(--muted); background: none; border-color: var(--line); }
.live-chip .live-word { font-variant-numeric: tabular-nums; }
/* Below 900px the header is already two rows deep (section 9 raises `--head-h`
   there), and a chip that pushed it to three would slide the sticky `thead` under
   the header.  The fact is not lost: the panel's own tab is fixed to the same
   corner and prints the same count, and the panel is where the chip points. */
@media (max-width: 900px) { .live-chip { display: none; } }

/* The spinner: a ring in the `running` pill's own two tokens, so "spinning" and
   "running" are one fact rather than two.  It is decoration - the pill and the
   counter carry the meaning - hence `aria-hidden` on the three places it is
   drawn.  Stopping it costs the reader nothing: the number beside it is still
   moving, and with JavaScript off the panel says that the number is a snapshot. */
.spin { display: inline-block; width: 12px; height: 12px; flex: 0 0 auto;
        border: 2px solid var(--info-bd); border-top-color: var(--info-ink);
        border-radius: 999px; animation: spin 1s linear infinite; }
.spin[hidden] { display: none; }
/* The desktop-notice button is rendered `hidden` and unhidden by the script only
   where the browser really has the API.  Spelled out for the same reason
   `.spin[hidden]` is: the `hidden` attribute loses to any author rule that gives the
   element a `display`, whatever its specificity. */
.live-notify[hidden] { display: none; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ---------------------------------------------------------------------------
   11. The finish notice: what ended while this page was open, announced once
       (`notice` in `_JS`).  NOT inside `.live-body`: that element is transformed
       while it slides in, and a transform makes `position: fixed` mean "fixed to
       the transformed box", so a toast in there would fly in with the panel.
       Empty means absent, so a quiet page carries no box and no gap.
   --------------------------------------------------------------------------- */
#notice { position: fixed; z-index: 31; right: var(--s4); bottom: var(--s4);
        display: flex; flex-direction: column; gap: var(--s2);
        width: min(380px, 92vw); }
#notice:empty { display: none; }
/* The panel and the notice want the same corner.  A sibling combinator and not
   `:has()` (which this stylesheet does not use): `#notice` is a sibling of `.live`
   precisely so the two can be told about each other with no JavaScript at all. */
.live[open] ~ #notice { right: calc(min(380px, 92vw) + var(--s4)); }
.notice { display: flex; align-items: center; gap: var(--s2); margin: 0;
        padding: var(--s2) var(--s3); font-size: 12.5px; line-height: 1.4;
        color: var(--ok-ink); background: var(--ok-bg);
        border: 1px solid var(--ok-bd); border-radius: var(--r);
        box-shadow: 0 4px 16px rgba(0, 0, 0, .10); }
/* Three colours, three truths: an exit code the run really reported (ok/bad by
   its value), a code that was never seen, and an activity that is no longer on
   disk.  The last two are `warn`, never `failed` - `Run._settle` maps a code it
   never learned to `failed`, and a notice may not repeat a claim nobody can
   check (`07-shell.md` §A3). */
.notice.failed { color: var(--bad-ink); background: var(--bad-bg);
        border-color: var(--bad-bd); }
.notice.unknown, .notice.cancelled { color: var(--warn-ink); background: var(--warn-bg);
        border-color: var(--warn-bd); }
.notice .btn { margin-left: auto; height: 22px; padding: 0 6px; font-size: 12px; }
.notice a { margin-left: var(--s1); }

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
  /* The spinner is the one thing that has to keep reading as "in progress": the
     global rule above would leave a plain ring that says nothing at all, so
     reduced motion gets a ring with one quadrant picked out instead of a
     frozen circle.  It says "in progress" without moving. */
  .spin { animation: none !important; border-top-color: var(--info-bd);
          border-left-color: var(--info-ink); }
}
"""

# The two polls: `/api/state` every 2s (the activities *and* the digest of the local
# files a page was drawn from), and the log of the one activity being watched (1s).
#
# The 2s poll does three things and they stop in different places.
#
#  * **The live panel** (`drawLive`) is updated on every page, because it is in the
#    shell: what is running now is the one fact a reader needs wherever they are.
#  * **The trigger** (`location.reload()` on a digest change) runs on every page too,
#    because it is the operator's 触发式: an activity that finished wrote something,
#    so the page re-reads itself rather than waiting for a manual refresh.  It is why
#    a finish the reader was watching can both be announced *and* leave the page up
#    to date - see the `notice`/`carry` pair below, which is what keeps the message
#    from being wiped by the reload the message is about.
#  * **The history table** is rewritten only where there is an activity table *and*
#    that table is showing every activity (`data-rows="all"`, `_table`):
#    `/api/state` answers the unfiltered question, so writing its answer into a
#    filtered `tbody` would replace the reader's rows with rows they did not ask for
#    - `/pull` drew one row and showed fifty two seconds later (`07-shell.md` §A2).
#
# The table re-render writes the same cells with the same classes as `_runs_table`:
# a table that changes shape when it refreshes is a table nobody can read while
# something is running.  `esc()` is what keeps a run's own text from becoming
# markup.  The `change` listener is progressive enhancement - with JavaScript off
# the form's apply button still submits, and the toolbar says so in a `<noscript>`
# note.
#
# The words this script writes (`I18N.log`, `I18N.cancel`, `I18N.sending`, …) are the
# catalogue's, injected as a small object by `_js()`: `_runs_table` and `_live_row`
# read the same ones server-side, so neither the table nor the panel can come back
# in another language than the one it was drawn in.
_JS = """
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
// A filter bar submits itself when a control *commits*, and a keyboard reader browses
// with the arrow keys first.  On a `<select>` and on a number box every arrow press is a
// `change`, so browsing submitted the form, reloaded the page and put the reader back at
// the top of it - the operator's 「有时候按某些键下面的会突然跳到头顶」.  So one-step keys
// set `browsing` for a moment and the submit waits for a committed gesture (Enter,
// Escape, Tab or a click); a mouse click still submits at once, because that is already
// a decision.
//
// The fourth control shape in a bar is the `<input list="…">` box `_name_field` draws
// (the `api` / `tree` / `branch` fields), and it was the one the whitelist missed:
// **Firefox opens a datalist on the down arrow**, so an arrow key changes the value and
// fires a `change` - the same browse-then-submit as a select, with `browsing` never set.
// `hasAttribute('list')` is the whole test: the box is the browser's own widget
// whatever the list is called.
//
// The **fifth** control shape is the tick-box group a multi-valued axis is asked with
// (`_check_group`: `tree`, `arch`, `defconfig`, `compiler`), and it is the one shape
// whose `change` is not a decision.  The gesture there is "tick these three, then
// apply": submitting on the first tick would reload the page once per box and pay the
// API's read once per reload.  So those boxes carry `data-multi` and the listener
// below leaves them alone; `apply` is beside them, and with the script off it is the
// only way out of the bar either way, which is what every other control here promises.
var browsing = 0;
document.querySelectorAll('form[data-auto]').forEach(function (f) {
  f.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === 'Escape') { browsing = 0; return; }
    var one = (e.key || '').indexOf('Arrow') === 0 ||
              e.key === 'PageUp' || e.key === 'PageDown' ||
              e.key === 'Home' || e.key === 'End';
    if (one && (e.target.tagName === 'SELECT' || e.target.type === 'range' ||
                e.target.type === 'number' || e.target.hasAttribute('list'))) {
      browsing = Date.now();
    }
  });
  f.addEventListener('change', function (e) {
    if (browsing && Date.now() - browsing < 1200) { return; }
    if (e.target.getAttribute && e.target.getAttribute('data-multi')) { return; }
    if (e.target.type !== 'submit' && e.target.type !== 'button') {
      keepPlace(barTarget(f));
      f.submit();
    }
  });
  // Every other way this bar leaves the page is a *native* submission, and it fires a
  // `submit` event that `f.submit()` above does not.  Both paths remember the place,
  // because both land on a page the reader did not ask to start at the top: the Apply
  // button and Enter in a box are the two gestures a filter bar offers, and until this
  // listener only the digest reload stored anything (`restorePlace` returned to the
  // top of every filtered page - the operator's 「跳到头顶」).
  f.addEventListener('submit', function () { keepPlace(barTarget(f)); });
  f.addEventListener('mouseup', function () { browsing = 0; });
  f.addEventListener('blur', function () { browsing = 0; }, true);
});
// Where the reader is in the page, kept for the load about to happen.  Two callers and
// one shape: the digest reload keeps the URL it is reloading, and a filter bar keeps the
// **destination** - the URL the browser is about to put in the address bar, which is
// what `restorePlace` matches on.  Its test is the whole URL on purpose: a position is
// only a position in the row set it was read in, and a path-only match would restore a
// scroll from one filtered table into another.  No storage, no place, no crash.
function keepPlace(url) {
  if (!url) { return; }
  try {
    sessionStorage.setItem('kci.place', JSON.stringify(
      {url: url, top: window.scrollY || 0, at: Date.now()}));
  } catch (err) {}
}
// The URL a filter bar is about to navigate to: a GET form's fields *are* the query,
// in the form's own order, which is what the browser will serialise too.  `URLSearchParams`
// for the same reason the action bars use it (`_form_body` reads what this encoding
// says), and the whole thing is guarded because a place that cannot be computed must
// still let the navigation happen.
function barTarget(f) {
  try {
    var url = new URL(f.getAttribute('action') || '', location.href);
    url.search = new URLSearchParams(new FormData(f)).toString();
    return url.href;
  } catch (err) { return ''; }
}
// An action button is an ordinary `<form method="post" action="/api/actions/<name>">`,
// so a browser's own behaviour would be to navigate to the JSON answer
// (`{started, kind, argv}`) - the reader asked for a build to be
// registered and got a page of JSON.  That answer is the contract and does not
// change; this listener is what keeps the reader where they were.
//
// Delegated on `document` on purpose: `drawLive` replaces the panel's rows every 2
// seconds, and a listener bound per form would be thrown away with them.  Two POST
// shapes are taken over: `/api/actions/**`, whose answer is the JSON contract, and
// `/api/runs/<id>/cancel`, whose answer is JSON too - a reader who cancelled an
// activity should stay on the page that shows it ending rather than be navigated to
// `{"cancelled": …}`.  The filter bar's GET (which submits itself from the `change`
// listener above, and must navigate) is not touched.
function barStatus(form, text, bad) {
  var spot = form.querySelector('[data-status]');
  if (!spot) { return; }
  spot.textContent = text;
  spot.className = bad ? 'status bad' : 'status';
}
document.addEventListener('submit', function (e) {
  var form = e.target;
  if (!form || !form.matches
      || !form.matches('form[method="post"][action^="/api/actions/"], '
                       + 'form[method="post"][action$="/cancel"]')) {
    return;
  }
  e.preventDefault();
  var button = form.querySelector('button');
  if (button) { button.disabled = true; }
  barStatus(form, I18N.sending, false);
  // `URLSearchParams`, not `new FormData(form)`: this posts what the server reads.
  // `FormData` serialises to `multipart/form-data`, and the reader took the body with
  // `parse_qs`, so no field arrived at all - every action ran on its defaults and the
  // ones needing a ticked row were refused with "needs at least one ticked build"
  // however many were ticked.  The server now reads both encodings (`_form_body`), so
  // a page already open in a browser keeps working; this is the spelling it should
  // have had.  Repeated names survive: `new URLSearchParams(formData)` keeps all 17
  // `selected` values, which is what `_ticks()` reads.
  var body = new URLSearchParams(new FormData(form));
  fetch(form.getAttribute('action'), { method: 'POST', body: body })
    .then(function (answer) {
      return answer.text().then(function (text) {
        return { ok: answer.ok, status: answer.status, text: text };
      });
    })
    .then(function (answer) {
      if (button) { button.disabled = false; }
      if (!answer.ok) {
        barStatus(form, I18N.rejected.replace('{reason}', answer.text.trim()), true);
        return;
      }
      var started = null;
      try { started = JSON.parse(answer.text); } catch (err) { started = null; }
      var id = (started && started.started) || '?';
      barStatus(form, I18N.started.replace('{id}', id)
        .replace('{argv}', ((started && started.argv) || []).join(' ')), false);
      livePoll();
      // **The panel is what opens the new activity.**  This used to fill the page's
      // log box with `<id>`'s tail; there is no box any more, and the re-point is the
      // `livePoll()` above - the activity that just started is the panel's first row,
      // and its 日志 link is a real link to the whole log in a tab of its own.  Nothing
      // is opened here on the reader's behalf: a script-opened tab is a pop-up, and a
      // start the reader has just confirmed does not need one.
    })
    .catch(function (err) {
      if (button) { button.disabled = false; }
      barStatus(form, I18N.unreachable.replace('{error}', err), true);
    });
});
// Is the reader typing into something on this page?  A reload that throws away a
// half-typed filter is worse than a table that is two seconds stale, so the trigger
// below waits for the next tick instead of firing under their hands.
function typing() {
  var one = document.activeElement;
  return !!one && (one.tagName === 'INPUT' || one.tagName === 'SELECT' ||
                   one.tagName === 'TEXTAREA');
}
// Is the reader busy inside something this poll would rewrite?  `#live` is the panel
// and `#runs` the activity table, and both are replaced wholesale (`drawLive`,
// `drawTable`) - the replacement drops the row under the cursor and can move the page
// under it, which is one more way the viewport jumps while nothing was clicked.
// `typing()` is the other half and is older: a reload that throws away a half-typed
// filter is worse than a page two seconds stale.  The finish notice is outside both
// regions on purpose - it is a card in its own corner, and dismissing it is not a
// reason to freeze the table beside it.
function busyHere() {
  if (typing()) { return true; }
  var one = document.activeElement;
  return !!(one && one.closest && one.closest('#live, #runs'));
}
// --- the live panel and the finish notice ---------------------------------
//
// One poll feeds three readers: the panel (what is running, on every page), the
// notice (what just ended, once each), and the history table (only where that table
// is the whole activity list - `data-rows="all"`).
var liveSeen = {}, liveNoticed = {}, liveTableAll = false;
var baseTitle = document.title;
// `data-drawn` is the moment the server drew this answer, and it is half of the
// notice's rule: a run carrying `ended > pageDrawn` ended *while this page was
// open*, whatever the poll happened to see.  Read defensively, because a page
// without it (an older answer, a test harness with a smaller DOM) must degrade to
// the other half of the rule rather than throw at load.
var pageDrawn = parseFloat((document.body && document.body.getAttribute
  ? document.body.getAttribute('data-drawn') : '') || '0');

// An id is a second-resolution stamp plus the kind, so two activities of one kind
// started in the same second shared it until `Run._free_id` suffixed the collision
// (`07-shell.md` §A3).  The key the memory and the notice are kept under is
// therefore `id@started`: keyed on the id alone, a reused id would swallow a finish
// and mis-attribute the one before it.
function liveKey(r) { return r.id + '@' + (r.started || 0); }

function liveTime(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  var m = Math.floor(sec / 60);
  return m ? (m + 'm' + (sec % 60 < 10 ? '0' : '') + (sec % 60) + 's') : (sec + 's');
}

// What an activity's pill *says*, which is not the same thing as its colour.
// `I18N.end_word` is the server's `_end_word` answered for the three codes
// `lib/errors.py` defines (0 pass / 1 a test failed / 3 infrastructure), built
// server-side and injected - the script holds no copy of those numbers, and the
// class it prints is still `r.state`'s, because that is what the stylesheet colours
// and what the state filter box offers.  A state the map has no code for is printed
// as itself, which is what the panel did before: "the pill says what is on disk".
function endWord(r) {
  if (r.state === 'cancelled') { return r.state; }
  // `+r.exit_code` and not `String`: a code that arrived as a string ("3") and one
  // that arrived as a number (3) are the same code, and only one of them is a key in
  // the map.
  var code = (r.exit_code === null || r.exit_code === undefined) ? ''
             : String(Number(r.exit_code));
  return (I18N.end_word || {})[code] || r.state;
}

// The ledger's counts for the builds a row's argv named, as words: `50 pass / 9 fail`.
// `I18N.tally` is `(verdict value, its word)` in the order the server prints them
// (`_tally_words`), and only the counts that happened are printed - the same rule
// `_tally_word` follows, because these two write one cell.
function tallyWord(t) {
  if (!t) { return ''; }
  var order = I18N.tally || [], parts = [], i, n;
  for (i = 0; i < order.length; i++) {
    n = t[order[i][0]];
    if (n) {
      parts.push((I18N.tally_one || '{n} {word}')
        .replace('{n}', n).replace('{word}', order[i][1]));
    }
  }
  return parts.join(' / ');
}
function tallyChip(r) {
  var said = tallyWord(r.tally);
  return said ? '<span class="tally">' + esc(said) + '</span>' : '';
}

// The same cells, the same classes and the same words as `_live_row`: the panel is
// rewritten every 2 s, and a row that changed shape or language when it refreshed
// would be a second, disagreeing answer to one question.
function liveRow(r) {
  var ended = r.state !== 'running';
  var code = (r.exit_code === null || r.exit_code === undefined) ? null : r.exit_code;
  var exitText = code === null ? esc(I18N.exit_unknown)
                               : esc(I18N.exit.replace('{code}', code));
  var argv = (r.argv || []).join(' ');
  var id = esc(r.id);
  return '<li class="live-row ' + (ended ? 'ended' : 'running') + '"' +
    ' data-id="' + id + '" data-started="' + esc(r.started || 0) + '"' +
    ' data-state="' + esc(r.state) + '">' +
    '<div class="live-line">' + (ended ? '' : '<span class="spin" aria-hidden="true"></span>') +
    '<span class="' + esc(r.state) + ' pill">' + esc(endWord(r)) + '</span>' +
    '<code class="live-id">' + id + '</code>' +
    '<span class="live-time num">' + esc(liveTime(r.seconds)) + '</span></div>' +
    // `_live_row` prints What as `[:80]`, so this does too: the two answers to "what
    // is running" must differ in their values only, never in their shape.
    '<div class="live-what">' + esc(String(r.what || '').slice(0, 80)) + '</div>' +
    '<code class="live-argv" title="' + esc(argv) + '">' + esc(argv) + '</code>' +
    '<div class="live-act">' + (ended ? '<span class="live-exit">' + exitText + '</span>' : '') +
    // The whole log, in a tab of its own: `/runs/<id>/log` answers `text/plain`
    // (`lib/gui/server.py`, `log_body`), and nothing takes the click over any more -
    // `target`/`rel` are the pairing that opens a new tab without handing it a handle
    // back into this page.  `_live_row` (the server's own copy of this row) writes the
    // same link, because the panel is drawn by the server and only *updated* here.
    '<a href="/runs/' + encodeURIComponent(r.id) + '/log"' +
    ' target="_blank" rel="noopener">' + esc(I18N.log) + '</a>' +
    (ended ? '' : '<form method="post" action="/api/runs/' +
      encodeURIComponent(r.id) + '/cancel"><button class="btn">' +
      esc(I18N.cancel) + '</button></form>') +
    '</div></li>';
}

// One finish, said once.  Three different truths and three different words:
//
//   * an exit code the run really reported - `notice_done` / `notice_failed`;
//   * no code at all - `notice_nocode`.  `Run._settle` maps a code it never learned
//     to `failed`, so a notice that repeated the run's state would claim a failure
//     nobody can check (`07-shell.md` §A3).  The pill says what is on disk; the
//     sentence says what was seen;
//   * an id that is simply gone - `notice_gone`.  Deleted by `prune`, not finished.
//
// Nothing is remembered between tabs, and nothing is remembered between *loads*
// except the carry below: a tab the operator opens after coming back was not
// watching, so it must not announce (that is the rule that makes a reload safe).
function notice(r, gone, quiet) {
  var box = document.getElementById('notice');
  if (!box) { return; }
  var code = (r.exit_code === null || r.exit_code === undefined) ? null : r.exit_code;
  // A cancellation is neither a success nor a failure, and it is the one finish the
  // reader caused themselves: `-15` under "failed" would be the page blaming the
  // reader for pressing its own button.
  var cancelled = (r.state === 'cancelled');
  var line = gone ? I18N.notice_gone.replace('{kind}', r.kind).replace('{id}', r.id)
    : cancelled ? I18N.notice_cancelled.replace('{kind}', r.kind)
    : code === null ? I18N.notice_nocode.replace('{kind}', r.kind)
    : (code === 0 ? I18N.notice_done : I18N.notice_failed)
        .replace('{kind}', r.kind).replace('{code}', code);
  var cls = (gone || code === null) ? 'unknown' : (code === 0 ? '' : 'failed');
  if (cancelled) { cls = 'cancelled'; }
  var el = document.createElement('p');
  // The colour is decided by the *exit code*, never by the run's own `state`: a state
  // class would fight this one on the rows where `_settle` guessed "failed" for a
  // code it never saw, and the pill inside prints the code's own word over the state's
  // class (`endWord` - "incomplete (infra)" beside "exit 3", not "failed").
  el.className = ('notice ' + cls).replace(/ +$/, '');
  el.setAttribute('data-key', liveKey(r));
  el.innerHTML = '<span class="' + esc(r.state) + ' pill">' + esc(endWord(r)) + '</span> ' +
    esc(line) + ' <a href="/runs/' + encodeURIComponent(r.id) + '/log"' +
    ' target="_blank" rel="noopener">' +
    esc(I18N.log) + '</a><button class="btn" type="button" data-dismiss="1">' +
    esc(I18N.dismiss) + '</button>';
  box.appendChild(el);
  // At most five on screen: a burst of finishes must not turn the corner into a wall
  // that hides the page it is reporting on.
  while (box.children.length > 5) { box.removeChild(box.firstChild); }
  // `quiet` is the carried card drawn on the page that lands after the reload: the
  // title and the desktop notification already happened, on the page that saw the
  // finish, and firing them a second time would be the same finish announced twice.
  if (!quiet) {
    document.title = '\u2713 ' + line + ' \u2014 ' + baseTitle;
    // The third channel, and the only one that works with the window unfocused.  Used
    // only when the reader has already granted it (`data-notify` asks); nothing here
    // ever prompts, and a page without permission is the page it was.
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      try { new Notification('kernelci-riscv: ' + line); } catch (err) { /* silence */ }
    }
  }
}

// **The notice has to survive the reload it is about.**  A finish changes the local
// digest, and the trigger in `livePoll` reloads the page on that change - so a message
// shown and then reloaded away would be a message nobody ever reads.  What is carried
// across *that* reload is therefore the **fact** (the activity, and whether it
// vanished), not a rendered string: the page that lands rebuilds the card with the
// same markup, so the carried notice has its log link and its dismiss button like any
// other, and it is written only by a page that just detected a finish, read and
// deleted by the page that lands, and ignored when older than 30 s.
//
// This is not the "already announced" set `07-shell.md` §B3 rejects: that would
// *suppress* a notice, while this only *retains* one, in the one tab that saw it, for
// the one reload the poll itself caused.  A tab the operator opens later carries
// nothing, so a finish from before the load is still never announced - and a manual
// reload after that reads nothing, because the entry was deleted when it was read.
var CARRY = 'kci-notice';
function carried() {
  var kept = [];
  try {
    var raw = window.sessionStorage.getItem(CARRY);
    window.sessionStorage.removeItem(CARRY);   // read once: a reload of a reload
    var seen = JSON.parse(raw || '[]');        // must not repeat it either
    for (var i = 0; i < seen.length; i++) {
      if (Date.now() - (seen[i].at || 0) < 30000) { kept.push(seen[i]); }
    }
  } catch (err) { kept = []; }                 // no storage: no carry, no crash
  return kept;
}
function carry(said) {
  try {
    window.sessionStorage.setItem(CARRY, JSON.stringify(said.map(function (one) {
      var r = one[0];
      return { at: Date.now(), gone: !!one[1],
               r: { id: r.id, kind: r.kind, state: r.state, exit_code: r.exit_code } };
    })));
  } catch (err) { /* a page that cannot store still shows the notice */ }
}
function drawCarried() {
  var kept = carried(), i;
  if (!document.getElementById('notice')) { return; }
  for (i = 0; i < kept.length; i++) { notice(kept[i].r, kept[i].gone, true); }
}

// The panel, rewritten in place.  The server drew it, so everything the script does
// here is an update: the rows, the tab's word and count, the header's ring and chip.
// No live region anywhere near it - it is rewritten every 2 s, and a screen reader
// pointed at it would never stop talking (`#notice` is the live region).
function drawLive(live, ended) {
  var panel = document.getElementById('live');
  if (!panel) { return; }
  var list = panel.querySelector('.live-list');
  if (list) {
    list.innerHTML = live.map(liveRow).join('') +
      ended.slice(0, LIVE_KEPT).map(liveRow).join('');
  }
  var word = live.length ? I18N.tab_running.replace('{n}', live.length) : I18N.tab_idle;
  document.querySelectorAll('.live-word').forEach(function (one) {
    one.textContent = word;
  });
  var count = panel.querySelector('.live-count');
  if (count) { count.textContent = live.length; }
  var headword = panel.querySelector('.live-headword');
  if (headword) {
    headword.textContent = live.length ? I18N.head_running : I18N.head_recent;
  }
  // The ring is the same fact as the number, so it follows the number: no live row,
  // no ring.  The panel's tab and the header's chip carry the same two elements, so
  // one rule keeps both in step.
  document.querySelectorAll('.live .spin, .live-chip .spin').forEach(function (one) {
    one.hidden = !live.length;
  });
  var empty = panel.querySelector('.live-empty');
  if (empty) { empty.hidden = !!(live.length + ended.length); }
}

// The count in the window title, which is the only channel that reaches a reader
// whose attention is elsewhere.  Restored on focus, so it cannot become permanent
// clutter that hides the page's own name.
function drawTitle(n) {
  document.title = (n ? '\u25cc ' + I18N.tab_running.replace('{n}', n) + ' \u2014 '
                      : '') + baseTitle;
}

function livePoll() {
  // One request, three answers: the activities, the local digest, and (through the
  // two fields `run_rows` now carries) when each of them started and ended.
  fetch('/api/state').then(function (r) { return r.json(); }).then(function (answer) {
    var runs = answer.runs || [];
    var now = {}, live = [], ended = [], i, r, was, key, key2, said = [];
    for (i = 0; i < runs.length; i++) {
      r = runs[i];
      key = liveKey(r);
      now[key] = r;
      if (r.state === 'running') {
        live.push(r);
        liveSeen[key] = r;
        continue;
      }
      ended.push(r);
      if (liveNoticed[key]) { continue; }
      was = liveSeen[key];
      // Two independent truths, and the notice needs one of them:
      //
      //   1. this page SAW it running and now it is not - a transition inside this
      //      page's own lifetime, which needs no new field on the server at all;
      //   2. the run says it ended *after this page was drawn* - `ended` is the run
      //      writing a fact about itself, and `pageDrawn` is the server writing one
      //      about the page, so it cannot be true of anything that ended earlier.
      //      This is the half that survives a throttled hidden tab, where the poll
      //      may run once a minute and truth 1 can miss a short activity entirely.
      if ((was && was.state === 'running') || (r.ended && r.ended > pageDrawn)) {
        said.push([r, false]);
        notice(r, false);
        liveNoticed[key] = 1;
      }
    }
    // An id that was running and is simply gone was deleted (`prune`), not finished:
    // it is announced as "no longer on disk" and never as done or failed.
    for (key2 in liveSeen) {
      if (!now[key2] && !liveNoticed[key2]) {
        said.push([liveSeen[key2], true]);
        notice(liveSeen[key2], true);
        liveNoticed[key2] = 1;
      }
    }
    liveSeen = {};
    for (i = 0; i < live.length; i++) { liveSeen[liveKey(live[i])] = live[i]; }
    // **Not under the reader's hands.**  `busyHere()` is the guard the digest reload
    // already had (`typing()`), extended to the two regions this poll rewrites: the
    // panel and the activity table are replaced wholesale, which moves whatever the
    // reader was reading the moment their cursor is in them - and a `cancel` button
    // under the cursor is a control they are about to press.  The cost is stated the
    // way it really is: `drawLive`/`drawTable` are skipped on **every** tick the cursor
    // stays inside those regions, not for one tick - and each tick is what makes the
    // numbers in them advance (`live-time`'s "2m" is `Run.seconds()` re-read on every
    // `/api/state` answer and written into the row here), so a reader who parks the
    // cursor on the panel reads a frozen elapsed time and frozen tally chips until they
    // move it away.  That is the trade, and it is the right way round: a control that
    // moves under the cursor is worse than a number a minute behind.  Nothing is lost
    // when something *does* write: the reload below is guarded by `typing()` alone, so
    // a write still changes the digest, still reloads the page, and the numbers come
    // back counted.
    if (!busyHere()) { drawLive(live, ended); }
    drawTitle(live.length);
    // The trigger: something wrote while this page was open - an activity that
    // settled its run.json, a record under var/results, a pull's provenance - so the
    // page re-reads itself with the question it was asked, which is the operator's
    // 触发式.  A half-typed filter waits for the next tick (`typing()`): throwing away
    // what the reader is writing is worse than a page two seconds stale.
    if (answer.digest && DIGEST && answer.digest !== DIGEST && !typing()) {
      carry(said);
      // **A reload is not a new visit.**  The trigger fires because *something wrote*,
      // and the reader was usually reading a row halfway down the page: reloading from
      // the top loses their place, which is the same complaint as a keystroke jumping
      // the viewport.  The position rides in `sessionStorage` beside the finish notice
      // (`carry`), with the same shelf life and the same "no storage, no crash" rule.
      keepPlace(location.href);
      location.reload();
      return;
    }
    if (liveTableAll && !busyHere()) { drawTable(runs); }
  }).catch(function () {});
}

// The history table, and only where it is the whole activity list (`data-rows="all"`,
// which `_table` emits exactly while the rows on screen are every activity).  A page
// whose table was drawn from a filter keeps its own rows: `/api/state` answers the
// unfiltered question, and writing that into a folded `tbody` would put the 37
// `table` rows back two seconds after the page said they were folded - the
// "silently undone filter" the operator met as "为什么拉取或者这里就 run 也会显示".
function drawTable(runs) {
  var body = document.querySelector('#runs tbody');
  var table = document.querySelector('#runs[data-rows="all"]');
  if (!body || !table) { return; }
  // The group captions are part of the table, so the refresh draws them too: the
  // order came from the server in `data-kinds` when it drew the rows, and a
  // re-render that dropped them would be a different table two seconds later.
  var order = (table.getAttribute('data-kinds') || '').split(',').filter(Boolean);
  var kinds = [], i;
  for (i = 0; i < runs.length; i++) {
    if (kinds.indexOf(runs[i].kind) < 0) { kinds.push(runs[i].kind); }
  }
  kinds.sort(function (a, b) {
    var ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib);
  });
  var html = '';
  for (i = 0; i < kinds.length; i++) {
    var group = runs.filter(function (r) { return r.kind === kinds[i]; });
    if (order.length) {
      html += '<tr class="kind-group"><td class="group">' +
        esc(group.length ? kinds[i] + ' (' + group.length + ')' : kinds[i]) + '</td></tr>';
    }
    html += group.map(function (r, at) {
      var code = (r.exit_code === null ? '-' : r.exit_code);
      var argv = (r.argv || []).join(' ');
      var exitCell = (r.kind === 'drift'
        ? '<span title="' + esc(I18N.drift_hint) + '">' + esc(code) + '</span>' : esc(code));
      // The caption sits in the first cell of its group's first row, exactly as
      // `_runs_table` draws it - not a row of its own, so the number of `<tr>`s on
      // this page keeps meaning "activities" (S6 counts them).
      var caption = (order.length && at === 0
        ? '<span class="kind-group">' + esc(r.kind + ' (' + group.length + ')') + '</span>'
        : '');
      return '<tr><td class="id' + (caption ? ' group-first' : '') + '">' + caption +
        '<code title="' + esc(I18N.dir_title.replace('{dir}', I18N.runs + r.id)) + '">' +
        esc(r.id) + '</code></td><td>' + esc(r.kind) +
        '</td><td><span class="' + esc(r.state) + ' pill">' + esc(endWord(r)) +
        '</span>' + tallyChip(r) + '</td>' +
        '<td class="num">' + esc(r.age) + '</td><td class="num">' + exitCell + '</td>' +
        '<td class="wrap">' + esc(r.what) + '</td>' +
        '<td class="wrap"><code title="' + esc(argv) + '">' + esc(argv.slice(0, 60)) +
        '</code></td><td class="act"><span class="cell-actions">' +
        // The same link `_runs_table` writes: the whole log, served as a page of its
        // own (`text/plain`, `lib/gui/server.py`), opened in a new tab.
        '<a href="/runs/' + esc(r.id) + '/log" target="_blank" rel="noopener">' +
        esc(I18N.log) + '</a>' +
        '<form method="post" action="/api/runs/' + esc(r.id) + '/cancel">' +
        '<button class="btn">' + esc(I18N.cancel) + '</button></form></span></td></tr>';
    }).join('');
  }
  body.innerHTML = html;
}

// Dismiss a notice, and ask for the desktop permission only when the reader presses
// the button that offers it - `Notification.requestPermission()` on load is an
// unprompted permission prompt, which every browser discourages and Safari refuses
// without a user gesture.
document.addEventListener('click', function (e) {
  var one = e.target;
  if (!one || !one.closest) { return; }
  var card = one.closest('[data-dismiss]');
  if (card) {
    var box = card.closest('.notice');
    if (box && box.parentNode) { box.parentNode.removeChild(box); }
    return;
  }
  var ask = one.closest('[data-notify]');
  if (!ask || typeof Notification === 'undefined') { return; }
  if (Notification.permission === 'granted') {
    ask.textContent = I18N.notify_on;
    return;
  }
  Notification.requestPermission().then(function (state) {
    ask.textContent = (state === 'granted') ? I18N.notify_on : I18N.notify_off;
  });
});
document.addEventListener('visibilitychange', function () {
  if (!document.hidden) { drawTitle(Object.keys(liveSeen).length); }
});
window.addEventListener('focus', function () {
  drawTitle(Object.keys(liveSeen).length);
});
liveTableAll = !!document.querySelector('#runs[data-rows="all"]');
// The desktop-notice button is server-rendered `hidden` and unhidden here only where
// the browser really has the API: `window.Notification` is absent outside a secure
// context (a LAN address, unlike 127.0.0.1), and a button that does nothing is a
// worse lie than no button.
(function () {
  var ask = document.querySelector('[data-notify]');
  if (!ask || typeof Notification === 'undefined') { return; }
  ask.hidden = false;
  ask.textContent = (Notification.permission === 'granted') ? I18N.notify_on
                                                           : I18N.notify_off;
})();
drawCarried();
// A rail is a duplicate *view* of a box that is already a real control: the box
// carries `name`, the rail does not, so the rail can never submit a value of its own
// and a page with this script off is exactly the page it was before the rail existed.
//
// `data-stops` is the suggestion set in the order the server offered it, and the
// rail's min/max are *indices* into it: what the reader slides through is the
// suggestions, and what the form sends is always the value in the box.  Typing a
// value the set does not name is the point ("滑条式可以给你选…但你可以自己填"): the
// readout prints it, the rail stays where it was, and the field is never refused.
var RAIL_MAX = 24;      // more stops than this and the dropdown beats the rail
function railStops(box) {
  try { return JSON.parse(box.getAttribute('data-stops') || '[]'); }
  catch (err) { return []; }
}
function railFor(box, stops) {
  var rail = document.createElement('input');
  rail.type = 'range';
  rail.className = 'rail';
  rail.min = 0;
  rail.max = Math.max(0, stops.length - 1);
  rail.step = 1;
  rail.tabIndex = -1;
  rail.setAttribute('aria-hidden', 'true');   // the box is the control, not this
  var read = document.createElement('output');
  read.className = 'railout';
  read.setAttribute('for', box.id);
  function show() {
    var at = stops.indexOf(box.value);
    if (at >= 0) { rail.value = at; }
    read.textContent = (box.value === '' ? '\\u2014' : box.value);
    read.dataset.off = (at < 0 ? '1' : '0');  // typed, and not one of the hints
  }
  rail.addEventListener('input', function () {         // sliding: read, do not send
    box.value = stops[Number(rail.value)];
    show();
  });
  // No synthetic `change` here, and that is a correction to the plan's `_rail`
  // (`02-filters.md` §B3): a native `change` on a range input **bubbles**, so the
  // bar's own listener (`form[data-auto]`) already picks the release up and submits
  // the box's value once.  Re-dispatching a change on the box as well made it submit
  // twice - the Node fake-DOM test in this round counts exactly two `form.submit()`
  // calls with that line and one without (`nodes()`-style counting in
  // `docs/gui-rework/09-step34-verification.md`).  Two submits of one form is two
  // page loads on an API where a load costs seconds.
  box.addEventListener('input', show);                 // typing moves the readout
  box.addEventListener('change', show);
  box.insertAdjacentElement('afterend', rail);
  rail.insertAdjacentElement('afterend', read);
  box.classList.add('has-rail');
  show();
}
// The other half of the reload: put the reader back where they were, once, if the
// stored place is this URL and it is fresh.  `scrollTo` is called nowhere else in this
// script on purpose - a page that moves the viewport on its own is the bug, and the one
// place it is wanted is undoing a reload the page itself asked for.
function restorePlace() {
  var raw = null;
  try { raw = sessionStorage.getItem('kci.place'); sessionStorage.removeItem('kci.place'); }
  catch (err) { return; }
  if (!raw) { return; }
  var place = null;
  try { place = JSON.parse(raw); } catch (err) { return; }
  if (!place || place.url !== location.href || Date.now() - place.at > 30000) { return; }
  if (place.top) { window.scrollTo(0, place.top); }
}
restorePlace();
window.addEventListener('load', restorePlace);

function buildRails(root) {
  (root || document).querySelectorAll('input[data-stops]:not(.has-rail)')
    .forEach(function (box) {
      var stops = railStops(box);
      if (stops.length < 2 || stops.length > RAIL_MAX) { return; }
      railFor(box, stops);
    });
}
buildRails();
window.addEventListener('load', function () { buildRails(); });
setInterval(livePoll, 2000);
window.addEventListener('load', function () { livePoll(); });

// One box that ticks every box a form will post.  The operator asked for it in so
// many words (「无论是跑测试还是 pull 等等能不能加一个全选功能」), and the whole of it is
// this listener: the boxes live outside their form (`form="pull-now"`, `form="run-now"`,
// which is how a row a page did not draw can still feed the bar it belongs to), so the
// header box names the form it is the select-all *of*, and nothing here submits
// anything - the bar's own button still posts the ticks, which is what keeps every
// command coming from `Gui.command()`.  The control itself is rendered `hidden` and
// unhidden here, the same progressive-enhancement rule the notify button follows.
function buildSelectAll(root) {
  (root || document).querySelectorAll('input[data-all-for]').forEach(function (all) {
    if (all.dataset.allReady) { return; }
    all.dataset.allReady = '1';
    all.hidden = false;
    var label = all.closest('label');
    if (label) { label.hidden = false; }
    all.addEventListener('change', function () {
      var want = all.checked;
      document.querySelectorAll('input[name="selected"][form="' +
        all.getAttribute('data-all-for') + '"]').forEach(function (box) {
        box.checked = want;
      });
    });
  });
}
buildSelectAll();
window.addEventListener('load', function () { buildSelectAll(); });
window.addEventListener('DOMContentLoaded', function () { buildSelectAll(); });
"""


# The catalogue key of every word this script writes -> the name it reads it by.
# Two spellings on purpose: the catalogue's keys are dotted and shared with the page
# (`js.cancel` is looked up server-side by `_runs_table` too), while the script wants
# `I18N.cancel` in the middle of a line of JavaScript.  A missing entry here is a
# word the script reads as `undefined`, so the list is one object and not two.
_JS_WORDS = {"link.log": "log", "js.cancel": "cancel",
             "runs.dir_title": "dir_title",
             "analysis.drift_hint": "drift_hint",
             "action.sending": "sending", "action.started": "started",
             "action.rejected": "rejected", "action.unreachable": "unreachable",
             # The live panel and the finish notice.  `tab_*`, `head_*` and `exit*`
             # are read server-side too (`_live_panel`, `_live_chip`), so the panel the
             # poll rewrites cannot come back in another language than the one it was
             # drawn in - the same rule the table's three words follow.
             "live.tab_running": "tab_running", "live.tab_idle": "tab_idle",
             "live.head_running": "head_running", "live.head_recent": "head_recent",
             "live.exit": "exit", "live.exit_unknown": "exit_unknown",
             "live.notify_on": "notify_on", "live.notify_off": "notify_off",
             "notice.done": "notice_done", "notice.failed": "notice_failed",
             "notice.nocode": "notice_nocode", "notice.gone": "notice_gone",
             "notice.cancelled": "notice_cancelled",
             "notice.dismiss": "dismiss"}


def _js(lang: str = DEFAULT_LANG, digest: str = "") -> str:
    """The poll script, with the words it writes in front of it as `I18N`.

    A JSON object rather than string literals, because the words have to be escaped
    for the element they sit in: `ensure_ascii=False` keeps the Chinese readable in a
    page that is UTF-8 anyway, and every `</` is broken up so that no run's own text
    (or a translation) can ever close the `<script>` it lives in.

    Most of them are also read server-side (`_runs_table` for the log link and the
    cancel button, `_live_row` for the panel's cells), so neither the table nor the
    panel can come back in another language when the poll rewrites it.  The rest are
    this script's own: the action bar's status line
    (`action.sending` / `action.started` / `action.rejected` / `action.unreachable`)
    and the finish notice (`notice.*`).  Everything goes through `textContent` or an
    `esc()`-ed interpolation, so unlike a page's HTML none of it carries markup - the
    ellipses and colons here are the characters themselves, and that is also what
    makes a translation unable to inject any.

    `digest` is the local state this page was drawn from (`_state_digest`), and it
    travels in the script because that is the only place the poll can compare it:
    `livePoll` re-reads the page when the server reports a different one.
    """
    words = {short: t(lang, key) for key, short in _JS_WORDS.items()}
    # `runs` is the activity directory itself, not a catalogue string: the refreshed
    # row prints the same `title=` on its id cell that `_runs_table` prints
    # (`runs.dir_title` is `{dir}/run.json + run.log`), and a path is not a word to
    # translate.  Without it a refreshed row would lose a tooltip the drawn row has,
    # which is the "the table changes shape when it refreshes" rule this file keeps.
    words["runs"] = layout.runs("")
    # Three entries that are not single words either, for the same reason `runs` is not
    # a catalogue string: they are what the script needs to write the state cell the
    # server drew (`_end_cell`), and a second copy of it in JavaScript would be the
    # drift the whole of `_JS_WORDS` exists to prevent.
    #
    #   * `end_word` - `_end_word`'s answer for the three exit codes `lib/errors.py`
    #     defines, keyed by the code as a string (a JSON object's keys are strings).
    #     The numbers themselves do not travel: the map is built where the constants
    #     live, so a `3` in this script is impossible.
    #   * `tally` / `tally_one` - the verdict vocabulary in print order and the format
    #     of one count (`_tally_words`, `run_end.tally_one`).
    words["end_word"] = {str(code): _end_word(state, code, lang)
                         for code, state in ((errors.EXIT_PASS, "done"),
                                             (errors.EXIT_TEST_FAIL, "failed"),
                                             (errors.EXIT_INFRA, "failed"))}
    words["tally"] = _tally_words(lang)
    words["tally_one"] = t(lang, "run_end.tally_one")
    blob = json.dumps(words, ensure_ascii=False).replace("</", "<\\/")
    # `LIVE_KEPT` rides with the words: the cap the panel was rendered with and the
    # slice `livePoll` writes back are the same number, and two spellings of it would
    # drift the day one of them changed.
    return (f"var I18N = {blob};\n"
            f"var LIVE_KEPT = {LIVE_KEPT};\n"
            f"var DIGEST = {json.dumps(digest)};\n" + _JS)

# The page: identity, the one live fact, the panel, the numbers, the body.
#
# Three things about this markup are load-bearing and are easy to undo by accident:
#
#  * **`<details id="live">` is a direct child of `<body>`.**  Its `.live-body` is
#    `position: fixed`, and a `transform`/`filter` on any ancestor re-anchors a fixed
#    element to that ancestor: the panel would slide with the page and the tab would
#    slide away with the panel it is the handle of.  Nothing may be inserted between
#    it and `<body>`, and no wrapper may gain a transform.
#  * **`#notice` is a sibling of the panel**, not a child of `.live-body` - for the
#    same reason (`.live-body` animates with `transform`), and because a closed
#    `<details>` renders nothing but its summary, so a notice inside it would be
#    invisible exactly when nothing is running.  `role="status"` +
#    `aria-live="polite"` is the whole screen-reader story; the panel itself is *not*
#    a live region, because it is rewritten every 2s.
#  * **`data-drawn` is on `<body>`** and is the moment this answer was drawn.  The
#    notice compares a run's own `ended` against it, so a page reloaded an hour later
#    cannot re-announce an hour-old finish (`_live_panel`, `run_rows`).
_PAGE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kernelci-riscv {title}</title>
<style>{css}</style></head><body data-drawn="{drawn}">
<header class="site-head"><div class="in">
<h1>kernelci-riscv &mdash; <span class="sub">{title}</span></h1>
<nav class="pages">{nav}</nav>
{live_chip}
<p class="lang">{langs}</p>
</div></header>
{live}
<p class="meta">{meta}</p>
<main>
{banners}
{body}
</main>
<footer class="site"><a href="/summary.json">summary.json</a>
   &mdash; {tagline}</footer>
<div id="notice" role="status" aria-live="polite"></div>
<script>{js}</script>
</body></html>
"""
