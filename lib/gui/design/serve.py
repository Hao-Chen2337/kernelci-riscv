# SPDX-License-Identifier: LGPL-2.1-or-later
"""Serving the design's screens: the one place a path becomes a page.

    gui.py --design                 # the console, drawn by lib/gui/design/pages/*

`DesignGui` is `Gui` with `render` replaced and **nothing else**.  The readers, the
actions, the ledger, the activity poll, the language negotiation, the JSON endpoints
and every gate are the same code the old pages use - which is the whole reason the
two layers can be served side by side from one engine, and the reason this class is
twenty lines of dispatch instead of a second console.

What the glue owns, and why each is here rather than in a page:

* **Route to page.**  The five stations are the design's own five screens, and
  `/builds` is the board's name for the screen the console serves at `/`: both keys
  resolve to the same drawer and links are written for `/`, because a route no key
  list knows (`ROUTE_KEYS` has no `/builds`) would drop the reader's whole question
  from every link the page writes.  A detail route (`/local/<id>`, `/analysis/<id>`)
  is the station's module drawing one row.
* **Page state.**  `kind` (`/runs`) and `mode`/`platform`/`runtime`/`since`
  (`/worker`) are keys a route reads that are *not* filter conditions - the old
  layer's own `/runs` docstring says so - so they are not `Filter` fields and
  `to_query()` leaves them out.  The pages ask for them on the check, which is what
  the old shell did by handing them to `_runs`/`_worker` as arguments; this is that
  hand-off, in the one place that builds the check.
* **The shells' own links.**  `keep` is what the top bar, the language switch and the
  refresh link carry, so a reader who switches language or reloads stays on the
  question they asked instead of landing on its default.

A page that is not written yet is a 404 with the same sentence the old layer uses -
the port is finished screen by screen, and the screens that are done have to be
reachable while the others still are not.
"""

from ... import errors
from ...i18n import DEFAULT_LANG, t
from ..app import Gui
from ..models import Filter
from ..schema import PAGES as STATION_NAMES
from . import data, pages, shell
from .view import View

# The paths that are a station in the old layer and an alias here: the board spells
# the builds screen `/builds` and every existing link and gate spells it `/`.
ALIASES = {"": "/", "/index.html": "/", "/builds": "/"}

# A station's drill-down: the path prefix, the module under `pages/`, and the drawer
# in it.  The station itself is the module's own name (`pages/builds.py::builds`).
DETAILS = {"/local/": ("builds", "local"), "/analysis/": ("analysis", "detail")}

# Page state: the keys a route reads that are **not** conditions, and therefore not
# `Filter` fields.  `state` is absent because it *is* one (a condition on two other
# screens), so `from_query` already carries it.  Per route, because that is the only
# true statement: `kind` means nothing to `/analysis` and `older` means nothing to
# `/runs`, and a state key attached where no page reads it is a URL that says the
# reader asked for something nobody looked at.
PAGE_STATE = {
    "/runs": ("kind",),
    "/worker": ("mode", "platform", "runtime", "since"),
    "/analysis": ("older", "newer", "vs"),
    "/analysis/": ("older", "newer", "vs"),
}


def _state_names(route: str) -> tuple:
    """The page-state keys a route reads: its own, or a detail route's station's.

    Resolved by longest prefix the way `_url` resolves a route's query keys, and for
    the same reason: `/analysis/<id>` *is* `/analysis` with a row named in the path,
    and a comparison that lost `older`/`newer` on the way to its own detail page is a
    different comparison.
    """
    if route in PAGE_STATE:
        return PAGE_STATE[route]
    for name, keys in PAGE_STATE.items():
        if name.endswith("/") and route.startswith(name):
            return keys
    return ()


def _page_state(check: Filter, query, names: tuple) -> None:
    """Hand the route's own keys to the check, the way the old shell handed them over.

    Read straight off the query and attached, because that is where the screens look
    for them (`getattr(view.check, "kind", "")`, `_named(view.check, "since")`);
    `Filter` has no `__slots__`, and a value the URL did not carry is left **absent**
    rather than set to `""`, so a page can tell "asked for nothing" from "asked for
    the empty string".
    """
    for name in names:
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


class DesignGui(Gui):
    """The console drawn by the design's screens; the engine underneath is `Gui`."""

    def render(self, page: str = "/", query=None, lang: str = DEFAULT_LANG) -> str:
        """One screen as HTML: the path chooses it, the query string is its state."""
        query = query or {}
        route, drawer = _drawer(page)
        if drawer is None:
            raise errors.ConfigError(t(lang, "error.no_page", page=repr(page),
                                       routes=", ".join(name for name, _ in STATION_NAMES)))
        check = Filter.from_query(query, lang, self.apis)
        names = _state_names(route)
        _page_state(check, query, names)
        rows = data.rows(self, check, lang)
        view = View(rows, check, lang, route, self, self.apis)
        keep = [(name, getattr(check, name, "")) for name in names
                if getattr(check, name, "")]
        return shell.document(view, drawer(view), keep=keep)
