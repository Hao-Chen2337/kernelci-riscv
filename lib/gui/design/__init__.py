# SPDX-License-Identifier: LGPL-2.1-or-later
"""The console's presentation layer, rebuilt from the design board.

`design/kernelci-design.html` is the design of record: one self-contained page
that draws all five screens of this console - `/builds`, `/jobs`, `/worker`,
`/runs`, `/analysis` - with the operator's own markup, stylesheet and words.  The
operator asked for that design to *be* the console ("以桌面那份为主重构"), keeping
the behaviour the old pages already implement.  This package is where that
happened, screen by screen.

**It is the only presentation layer.**  `serve.py`'s `DesignRenderMixin` is mixed
into `Gui` by `app.py`, so `Gui.render` is this dispatch and there is no second one,
and every screen is a module under `pages/`.  The layer it replaced is gone - what
this package still borrowed from it (the poll script, the pill's word, the axis
vocabulary, the row readers) was moved rather than copied into `script.py`, `ui.py`,
`values.py` and `data.py`.

**It draws; it does not decide.**  Every number here arrives from the readers that
already exist (`lib/gui/reads.py`, `activities.py`, `reports.py`, `lib/re.py`,
`lib/drift.py`), the way `docs/gui-rework/00-BRIEF.md` requires of any page: a
verdict comes from `lib/judge.py`, a tally from `Records`, a gap from `re.todo()`,
a difference from `lib/drift.py`.  A presentation layer that computes is a second
answer to a question the tree already answers once.

**The interaction is not rebuilt.**  The shipped script (`script._JS`, driven by
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
"""
