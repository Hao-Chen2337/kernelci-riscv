# SPDX-License-Identifier: LGPL-2.1-or-later
"""The GUI: three things kept apart - what the API has, what we hold, and the record.

The old page merged the first two into one table of `build_id`s, which quietly
claimed that a local copy and a remote build with the same id are the same thing.
They are two equal *values*; sameness has to be established.  So this page shows
three separate facts and never derives one from another:

* **remote** - the answer to one API query (`Kbuilds.getdays`), always a window
  (or `days=0`, which asks for the whole history), so the page prints the query
  it asked *and* how much of the answer it is showing;
* **local** - a card registered in the table (`Builds`) and bytes on disk
  (`Build.present()`), which are two facts even about the same directory;
* **the correspondence** - `var/downloads/<build-id>/provenance.json`, written by
  `Build.make()` when the bytes are pulled: which URL every artifact came from,
  how many bytes were proven, and when.  No record means "not recorded", never a
  guess from a matching id.

Every button runs the command an operator would type (`Gui.command()`), as a `Run`
(see `lib/run.py`); one writer at a time; and the page computes nothing - a verdict
comes from `judge`, a tally from `Records`, a gap from `todo()`, a regression from
`transitions()`, a difference from `Drift`.

The module this was, split by what each part knows:

    schema.py     the vocabulary every page is drawn from: the routes, the actions,
                  the filter vocabulary and the tables two pages must agree about
    forms.py      one query string or form body, as the values a page may use
    models.py     `Filter`, the answer one API query gives (`Remote`), one card in
                  the table and the bytes under it (`Local`)
    values.py     one value as a page prints it (an age, a size, an id, a state), and
                  the candidates an axis offers to be asked with (`_vocabulary`)
    urls.py       every link: one function, one spelling of a URL
    sorting.py    the order a table is drawn in
    pairs.py      two builds, and the name a comparison spells them by
    reads.py      what a page reads, per request - the rows the five screens are built
                  from (`build_rows`, `_known_builds`) and the comparisons between
                  adjacent rows (`_config_edges`)
    activities.py the running commands: what is busy, what each one did, the pulls
    reports.py    the three JSON answers (`/summary.json`, drift, trend)
    actions.py    the command line a button runs, the `Run` it starts, and why a
                  one-shot button cannot be offered at all (`_one_tree`)
    server.py     the socket loop, the handler, and one request's own state
    app.py        `Gui` itself: the fields, and the mixins it is assembled from
    design/       the presentation layer, and the only one: `serve.py` is `Gui.render`,
                  `data.py` reshapes the readers into one dict per request, `ui.py`,
                  `words.py` and `style.py` are the components, the vocabulary and the
                  stylesheet, `shell.py` is the one writer of `<html>`, `script.py` is
                  the shipped poll script and the words it writes, `view.py` is what a
                  screen is handed, and `pages/*.py` is one module per screen

The layer that stood beside it - `templates.py`, `widgets.py`, `fields.py`, `cells.py`,
`shell.py`, `pages/`, and the two view modules only that layer read (`tables.py`,
`driftview.py`, `trendview.py`) - is gone, and what this layer borrowed from it was
**moved, not copied**: the poll script into `design/script.py`, the pill's word into
`design/ui.py`, the axis vocabulary into `values.py`, the row readers into
`design/data.py`, and the four reads that were reached through `Gui` itself into
`reads.py` and `actions.py`.

`from lib import gui` re-exports the surface the entry point and the tools read -
`Gui`, `PORT`, `ROWS`, `REFRESH` and the module-level names they reach for - so a
caller written against the single module keeps working.  Inside the package a module
imports the one it needs (`from .models import Filter`) and never this file, which is
what keeps the graph acyclic: the names a module only ever spells inside a *string*
annotation are imported under `TYPE_CHECKING`, because nothing evaluates those and
`models` and the pages that read it would otherwise import each other in a circle.

接口形状（C++，只有声明）：include/kci/view.hpp §16 Filter、§17 账本、§18 Drift、§19 GUI。
"""

from ..i18n import t
from .app import Gui
from .design.script import _JS, _js
from .schema import HOST, PORT, REFRESH, ROWS
from .server import _form_body

# What the root entry point, the tools under `docs/gui-rework/tools/` and anything
# else that was written against `lib/gui.py` read off this module - the whole of the
# surface this package promises to keep, whatever moves underneath it.
__all__ = ["HOST", "PORT", "REFRESH", "ROWS", "_JS", "Gui", "_form_body", "_js", "t"]
