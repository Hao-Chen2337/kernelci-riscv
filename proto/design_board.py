# SPDX-License-Identifier: LGPL-2.1-or-later
"""The whole design on one scroll: five pages, stacked, each with its own caption.

    python3 -m proto.design_board [--out FILE]

This is the thing to look at.  It writes one self-contained HTML file - the
stylesheet and the script inlined - that opens from the desktop with no server, no
network and nothing to install, and every screen of the console is on it in order.
The five pages it draws are the same functions `proto/serve.py` serves, so a change
made while looking at the board is a change to the pages and not to a drawing of
them.

Nothing here is wired: a button is a button, a filter does not filter, and the
numbers are the fixture.  That is the point of a board - it is cheap to change and
it cannot break anything.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proto import data, pages, shell, theme, ui
from proto.words import both

HERE = os.path.dirname(os.path.abspath(__file__))

# The order the screens are shown in, with the sentence that says what question
# each one answers.  The caption is the *design* note: what a reader is meant to
# be able to do on the screen and why it is laid out this way.
SHEETS = [
    ("/builds", "builds", "01",
     "upstream's builds, this disk's copies, and which of them has run"),
    ("/jobs", "jobs", "02",
     "which (build x test) pairs have no record, and what the ledger says for the rest"),
    ("/worker", "worker", "03",
     "what the poll loop is doing, what it claimed, and what came back"),
    ("/runs", "runs", "04",
     "every background process this console started, and whether it is still going"),
    ("/analysis", "analysis", "05",
     "read down the list: is this getting better or worse"),
]

# What to look at on each sheet.  Written as a reviewer's note and not as a
# feature list: one sentence per decision worth arguing with.
NOTES = {
    "/builds": [
        "the filter bar never collapses; the seven conditions behind <b>more filters</b> do",
        "the <b>card</b> column is three artifacts, not one word - a card with nothing behind it used to look like a whole build",
        "the <b>api says</b> column says <i>not in this answer (cap 50)</i> instead of <i>no remote counterpart</i>",
        "the numbers under the bar are links, not decoration",
    ],
    "/jobs": [
        "the queue is what is <i>not</i> known and the ledger is what is - one page, so a fail and a never-ran are told apart",
        "a row that cannot run says which artifact it is waiting for, and its tick box is disabled",
        "the <b>source</b> column is who wrote the record - <code>worker</code> is the row an operator looks for",
    ],
    "/worker": [
        "the last panel is new: the ledger's <code>source=worker</code> rows, so the answer to \"did it do anything\" is not a cursor",
        "<code>cursor</code> carries a warning that it is not the last claim time; <code>seen</code> is the number that means a claim",
        "the start button has the sentence that says where the results will appear",
    ],
    "/runs": [
        "one row per process, with the note that a worker which claimed five jobs is still one row",
        "state is a pill, the argument is monospace and truncates, the log is one click",
    ],
    "/analysis": [
        "three panels answer three different questions: this build's own counts (bars), one test over time (timeline), and the config between neighbours (±)",
        "a ± cell that was not read says <i>why</i> - <i>the first row in this order</i> - instead of a dash",
        "the timeline's gaps are positions the ledger has nothing for, drawn as empty squares",
    ],
}


def sheet_caption(route: str, slug: str, number: str, blurb: str) -> str:
    notes = "".join(f"<li>{n}</li>" for n in NOTES.get(route, ()))
    return (
        f'<div class="sheet" id="{slug}">'
        f'<div class="sheet-head">'
        f'<span class="sheet-no">{number}</span>'
        f'<h2>{both("nav." + slug)}</h2>'
        f'<span class="sheet-route">/{slug}</span>'
        f'<span class="sheet-blurb">{blurb}</span>'
        f'</div>'
        f'<ul class="sheet-notes">{notes}</ul>'
        f'</div>'
    )


def board(d: dict) -> str:
    """The board: a cover, then the five screens one under the other."""
    cover = (
        '<header class="board-cover">'
        '<h1>kernelci-riscv &mdash; frontend</h1>'
        '<p class="lede">five screens, drawn from the rows the real console prints. '
        'nothing here runs a command, reads a record or asks the API: it is a design '
        'to be argued with, and changing it changes only a drawing.</p>'
        '<ul class="cover-notes">'
        '<li><b>the point</b> &mdash; the back end is not written for these screens yet, '
        'and this is the cheap way to decide what the screens should be first</li>'
        '<li><b>the theme</b> &mdash; a light and a dark palette, switched from the top bar; '
        'every colour is a named token, so both themes are one stylesheet</li>'
        '<li><b>the language</b> &mdash; EN / 中文 in the top bar, every sentence written twice</li>'
        '<li><b>to argue</b> &mdash; the note under each sheet title lists the decisions worth '
        'disagreeing with</li>'
        '</ul>'
        '</header>'
    )
    screens = "".join(
        sheet_caption(route, slug, number, blurb)
        + '<div class="frame">'
        + shell.live_strip(d)
        + pages.PAGES[route](d)
        + '</div>'
        for route, slug, number, blurb in SHEETS
    )
    return cover + screens


BOARD_CSS = """
/* -- the board around the screens: a cover, a caption, and a frame ------------- */
body { background: var(--ground); }
.board-cover { max-width: 860px; margin: 28px auto 34px; padding: 0 4px; }
.board-cover h1 { font-size: 27px; font-weight: 600; letter-spacing: -.025em; margin-bottom: 10px; }
.board-cover .lede { font-size: 14px; line-height: 1.65; color: var(--ink-mid); max-width: 66ch; }
.cover-notes { margin: 18px 0 0; display: grid; gap: 7px; }
.cover-notes li {
  position: relative; padding-left: 17px; font-size: 12.5px; line-height: 1.6; color: var(--ink-mid);
}
.cover-notes li::before {
  content: ""; position: absolute; left: 3px; top: 9px; width: 5px; height: 5px;
  border-radius: 50%; background: var(--accent);
}
.cover-notes b { color: var(--ink); }

.sheet { max-width: 1680px; margin: 40px auto 0; padding: 0 16px; }
.sheet-head { display: flex; align-items: baseline; gap: 11px; flex-wrap: wrap;
  padding-bottom: 9px; border-bottom: 2px solid var(--ink); }
.sheet-no { font-family: var(--mono); font-size: 13px; color: var(--accent); font-weight: 500; }
.sheet-head h2 { font-size: 19px; font-weight: 600; letter-spacing: -.02em; }
.sheet-route { font-family: var(--mono); font-size: 12px; color: var(--ink-soft);
  background: var(--sunken); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 1px 7px; }
.sheet-blurb { flex: 1 1 320px; font-size: 12.5px; color: var(--ink-soft); text-align: right; }
.sheet-notes { display: grid; gap: 5px; margin: 11px 0 13px; }
.sheet-notes li { position: relative; padding-left: 16px; font-size: 12px; line-height: 1.6; color: var(--ink-mid); }
.sheet-notes li::before {
  content: ""; position: absolute; left: 2px; top: 8px; width: 5px; height: 5px;
  border-radius: 1px; background: var(--accent); opacity: .55;
}
.sheet-notes code { font-size: 11px; }
.frame { background: var(--ground); border: 1px solid var(--line); border-radius: var(--r);
  padding: 12px; box-shadow: var(--shadow); }
.frame .live { margin-bottom: 12px; }
.frame .topbar { position: static; border: 1px solid var(--line); border-radius: var(--r);
  margin-bottom: 12px; }
.frame table.grid thead th { top: 0; }
@media print { .sheet { page-break-inside: avoid; } }
"""


def document(d: dict) -> str:
    """One file: the board, plus the app's own stylesheet and script, inlined."""
    with open(os.path.join(HERE, "static", "app.css"), encoding="utf-8") as fh:
        app_css = theme.css_vars() + "\n" + fh.read()
    with open(os.path.join(HERE, "static", "app.js"), encoding="utf-8") as fh:
        app_js = fh.read()
    top = (
        '<header class="topbar">'
        '<span class="brand"><span class="mark">kci</span>'
        f'<span class="name">{both("shell.brand")}</span>'
        '<span class="sep">&rsaquo;</span>'
        '<span class="where">frontend design board &mdash; five screens</span></span>'
        '<nav class="nav">'
        + "".join(f'<a href="#{slug}">{both("nav." + slug)}</a>'
                  for _r, slug, _n, _b in SHEETS)
        + '</nav>'
        '<span class="tools">'
        '<span class="seg" role="group" aria-label="language">'
        '<label><input type="radio" name="lang" value="en" checked><span>EN</span></label>'
        '<label><input type="radio" name="lang" value="zh"><span>中文</span></label>'
        '</span>'
        '<button type="button" class="btn sm" id="theme" title="light / dark">'
        '&#9680; <span id="theme-word">auto</span></button>'
        '</span>'
        '</header>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kernelci-riscv - frontend design board</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='3' fill='%232f5bd0'/></svg>">
<style>
{app_css}
{BOARD_CSS}
</style>
</head>
<body>
{top}
{board(d)}
<script>
{app_js}
</script>
</body>
</html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(HERE, "site", "design-board.html"))
    args = parser.parse_args(argv)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    text = document(data.data())
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out}  ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
