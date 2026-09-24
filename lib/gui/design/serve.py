# SPDX-License-Identifier: LGPL-2.1-or-later
"""Serving the design's screens: the one place a path becomes a page.

    gui.py                          # the console, drawn by lib/gui/design/pages/*

`DesignRenderMixin` is `Gui`'s `render` and **nothing else**, mixed into `Gui` by
`app.py`.  The readers, the actions, the ledger, the activity poll, the language
negotiation, the JSON endpoints and every gate are the engine's, untouched - which is
why this is twenty lines of dispatch instead of a console of its own, and why one class
can be the whole console: `from lib import gui; gui.Gui(...)` draws these screens.

What the glue owns, and why each is here rather than in a page:

* **Route to page.**  The five stations are the design's own five screens, and
  `/builds` is the board's name for the screen the console serves at `/`: both keys
  resolve to the same drawer and links are written for `/`, because a route no key
  list knows (`ROUTE_KEYS` has no `/builds`) would drop the reader's whole question
  from every link the page writes.  A detail route (`/local/<id>`, `/analysis/<id>`)
  is the station's module drawing one row.
* **Page state.**  `kind` (`/runs`) and `mode`/`platform`/`runtime`/`since`
  (`/worker`) are keys a route reads that are *not* filter conditions, so they are not
  `Filter` fields and `to_query()` leaves them out.  `schema.PAGE_STATE` is the table
  that names them per route, and this hands them to the check, which is what the retired
  shell did by handing them to its drawers as arguments; this is that hand-off, in the
  one place that builds the check.
* **The shells' own links.**  `keep` is what the top bar, the language switch and the
  refresh link carry, so a reader who switches language or reloads stays on the
  question they asked instead of landing on its default.  `ui.pager` keeps the same set
  on a page link (`ui._kept_state`), for the same reason: turning a page is not
  answering a different question.

A path no drawer answers is a 404: the five stations are all the screens there are, and
`error.no_page` names them, so a hand-edited URL that names nothing gets a sentence
instead of a blank page.
"""

from ... import errors
from ...i18n import DEFAULT_LANG, t
from ..forms import _names
from ..models import Filter
from ..schema import MULTI_PAGE_STATE, state_keys
from ..schema import PAGES as STATION_NAMES
from . import data, pages, shell
from .view import View

# The paths that are the board's names for a station: the board spells the builds
# screen `/builds` and every existing link and gate spells it `/`.
ALIASES = {"": "/", "/index.html": "/", "/builds": "/"}

# A station's drill-down: the path prefix, the module under `pages/`, and the drawer
# in it.  The station itself is the module's own name (`pages/builds.py::builds`).
DETAILS = {"/local/": ("builds", "local"), "/analysis/": ("analysis", "detail")}

def _page_state(check: Filter, query, names: tuple) -> None:
    """Hand the route's own keys to the check, the way the old shell handed them over.

    Read straight off the query and attached, because that is where the screens look
    for them (`getattr(view.check, "kind", "")`, `_named(view.check, "since")`);
    `Filter` has no `__slots__`, and a value the URL did not carry is left **absent**
    rather than set to `""`, so a page can tell "asked for nothing" from "asked for
    the empty string".

    One value per key is the rule, and the keys in `schema.MULTI_PAGE_STATE` are the
    named exception: those are read as the whole set the query carried, joined.
    """
    for name in names:
        if name in MULTI_PAGE_STATE:
            # A key a reader answers with several values (`schema.MULTI_PAGE_STATE`):
            # every value under it, joined into the one comma spelling the page parses
            # (`_names` reads both a repeated key and a comma-joined value, so a link
            # and a chip group are the same answer).  Without this the chips would
            # submit seven `kind=` values and `[:1]` below would keep only the first -
            # a control that shows seven ticks and applies one.
            parts = [one for value in (query.get(name) or [])
                     for one in _names(str(value))]
            joined = ",".join(dict.fromkeys(parts))
            if joined:
                setattr(check, name, joined)
            continue
        value = (query.get(name) or [""])[0]
        if value:
            setattr(check, name, value)


def _drawer(path: str):
    """The route and the function that draws `path`, or `None` when nothing does."""
    page = ALIASES.get(path, path)
    for prefix, (module_name, drawer_name) in DETAILS.items():
        if page.startswith(prefix):
            module = getattr(pages, module_name, None)
            return (page, getattr(module, drawer_name, None)) if module else (page, None)
    return page, pages.PAGES.get(page)


class DesignRenderMixin:
    """The route dispatch: `Gui.render` is this method and there is no second one.

    A mixin and not a subclass, because `Gui` is the one name the entry point, the
    tools and every gate build (`app.py` mixes this in where the retired `ShellMixin`
    was).  Two classes that both answered `render` would be two consoles - one of them
    reachable only by a flag - and the whole point of this round is that there is one
    screen per route, drawn from one set of readers.
    """

    def render(self, page: str = "/", query=None, lang: str = DEFAULT_LANG) -> str:
        """One screen as HTML: the path chooses it, the query string is its state."""
        query = query or {}
        route, drawer = _drawer(page)
        if drawer is None:
            raise errors.ConfigError(t(lang, "error.no_page", page=repr(page),
                                       routes=", ".join(name for name, _ in STATION_NAMES)))
        check = Filter.from_query(query, lang, self.apis)
        names = state_keys(route)
        _page_state(check, query, names)
        rows = data.rows(self, check, lang)
        view = View(rows, check, lang, route, self, self.apis)
        keep = [(name, getattr(check, name, "")) for name in names
                if getattr(check, name, "")]
        return shell.document(view, drawer(view), keep=keep)
