# SPDX-License-Identifier: LGPL-2.1-or-later
"""The five screens, and the one place a route becomes a page.

    PAGES["/runs"](view) -> the body of that screen

Each screen is its own module because each screen is its own argument: `/builds` is
"what is there", `/jobs` is "what has no record yet", `/worker` is "what the poll
loop is doing", `/runs` is "what this console started", `/analysis` is "is this
getting better or worse".  A file per question is what keeps a page module readable
and what lets one screen be rewritten without the other four being opened.

The table is built by importing what exists rather than by a literal dict, because
the screens are being ported one at a time and the console has to keep rendering
while that happens: a route whose module is **not written yet** is simply absent, and
a page that is missing is a 404 rather than an import error that takes down the four
that are finished.

"Not written yet" is judged by the file, not by catching `ImportError`.  Swallowing
the import error was the first spelling of this and it was wrong in the way that
costs the most: a screen that *is* written but is broken - a wrong relative import,
a syntax error, a module-level `TypeError` - disappeared from this table exactly like
a screen nobody had started, so `check_hooks.py --route /jobs` printed the shell's
8/8 and said nothing, and the registry itself was the thing hiding it.  A file that
exists is imported and its errors are its own.

`/builds` is the design board's name for the screen the console serves at `/`; both
keys point at the same function (see `00-BRIEF.md` §11), because the gate and every
existing link spell the first and the board spells the second.
"""

import importlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# route -> the module under this package that draws it, and the function's name.
# The route is the URL; the pair is (module name, function name).
SCREENS = (
    ("/", "builds", "builds"),
    ("/builds", "builds", "builds"),
    ("/jobs", "jobs", "jobs"),
    ("/worker", "worker", "worker"),
    ("/runs", "runs", "runs"),
    ("/analysis", "analysis", "analysis"),
)


def _load() -> dict:
    """Every screen whose module is written, keyed by route.

    A module that is not there is not an error (see the docstring above); a module
    that is there and does not import is, and it is reported as itself rather than as
    a missing page.
    """
    found = {}
    for route, module_name, function_name in SCREENS:
        if not os.path.exists(os.path.join(HERE, f"{module_name}.py")):
            continue
        module = importlib.import_module(f"{__name__}.{module_name}")
        drawer = getattr(module, function_name, None)
        if drawer is None:
            raise ImportError(f"{module_name}.py is written but defines no {function_name}()")
        found[route] = drawer
    return found


PAGES = _load()
