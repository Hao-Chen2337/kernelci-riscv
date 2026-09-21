# SPDX-License-Identifier: LGPL-2.1-or-later
"""The console's presentation layer, rebuilt from the design board.

`design/kernelci-design.html` is the design of record: one self-contained page
that draws all five screens of this console - `/builds`, `/jobs`, `/worker`,
`/runs`, `/analysis` - with the operator's own markup, stylesheet and words.  The
operator asked for that design to *be* the console ("以桌面那份为主重构"), keeping
the behaviour the old pages already implement.  This package is where that
happens, screen by screen.

**It draws; it does not decide.**  Every number here arrives from the readers that
already exist (`lib/gui/reads.py`, `activities.py`, `reports.py`, `lib/re.py`,
`lib/drift.py`), the way `docs/gui-rework/00-BRIEF.md` requires of any page: a
verdict comes from `lib/judge.py`, a tally from `Records`, a gap from `re.todo()`,
a difference from `lib/drift.py`.  A presentation layer that computes is a second
answer to a question the tree already answers once.

**The interaction is not rebuilt.**  The shipped script (`templates._JS`, driven by
`docs/gui-rework/tools/test_dom.js` and `test_notice.js`) owns the two-second poll,
the finish notice, the POST take-over, the value rails and the select-all boxes.
Those suites read the *shipped* script out of `lib.gui` and then look for the
markup it drives, so the markup here keeps the hooks it drives by - `body[data-drawn]`,
`details.live#live`, `#notice` beside it, `#runs[data-rows]`, `form[data-auto]`,
`input[data-stops]`, `input[data-all-for]`, `input[data-multi]`, `[data-status]`.
A restyle that drops one of them is a restyle that silently stops polling.

**The stylesheet is not retyped.**  `style.py` is extracted from the board by
`tools/design_extract.py`, which also carries the `--check` that fails when the
two have drifted apart.  The nine rules left out are the ones that draw the board
itself - the numbered captions and the mock browser window - because those belong
to the design document and not to a console.

The old layer (`templates.py`, `widgets.py`, `fields.py`, `cells.py`, `shell.py`
and `pages/`) stays untouched and serving while this one is built, so the gates
keep meaning something at every step; it is deleted the day the last screen here
passes them.
"""
