#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The browser-side contract of the new presentation layer: every hook the shipped script drives.

    python3 tools/check_hooks.py                 # the shell around a stub body
    python3 tools/check_hooks.py --route /runs   # a real screen, when the pages exist
    python3 tools/check_hooks.py --body FILE     # a body under review, read from a file

`lib/gui/design/script.py`'s `_JS` is the console's interaction - the two-second poll,
the finish notice, the POST take-over, the value rails, the select-all boxes - and
it finds the page by *selector*.  A restyle that drops one of those selectors does
not fail anything: it silently stops polling, or stops announcing a finished run,
or draws a button whose answer never appears.  The two node suites do not catch it,
because both of them build their own DOM stub and drive the script against that
rather than against a page this tree rendered.

So this renders a page through the real pipeline (the real readers, the design's
shell, the real data) and then asks, for every selector the shipped script queries,
whether the document it would receive contains it - and says what stops working when
the answer is no.  That last part is the point: "missing #notice" is a puzzle, "a
finished run stops announcing itself" is a bug report.

Exit status is 0 when every hook is present, 1 when one is missing (each named with
its symptom), and 2 when the page could not be rendered at all.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import api as api_mod
from lib.gui import app
from lib.gui.design import data as design_data
from lib.gui.design import script as design_script
from lib.gui.design import shell as design_shell
from lib.gui.design.view import View
from lib.gui.models import Filter

# The selectors the shipped script queries, and what a page loses without one.  A
# selector the script builds at run time (`#runs tbody`, `input[name=selected]`) is
# listed by the part of it that has to exist in the markup.
SHELL_HOOKS = {
    "#live": "the activity panel cannot be found: nothing polls, nothing redraws",
    ".live-list": "the panel cannot replace its rows, so a running run never moves",
    ".live-word": "the tab stops saying how many are running",
    ".live-count": "the panel's own count stops tracking the list",
    ".live-headword": "the panel's heading stops saying what it is showing",
    ".live-empty": "'nothing has run' can be neither shown nor taken away",
    ".live .spin, .live-chip .spin": "no spinner while a poll is in flight",
    "#notice": "a finished run stops announcing itself",
}

# The other half belongs to a page body, and these are **capabilities, not
# obligations**: `/runs` has no tick column and no bulk action, so demanding
# `input[data-all-for]` there would report a screen for not having a control it never
# had - a phantom failure, which is how a checker gets ignored.  Each of these is
# therefore required only when the page's own markup says the control it belongs to is
# there: the marker in the second column is what makes it an obligation, and the third
# is the control it is about, for the sentence the tool prints.
IMPLIED = (
    ("[data-status]", ('method="post"', '/api/actions/'), "POST action form"),
    ("input[data-stops]", ('type="number"',), "number box"),
)

PAGE_HOOKS = {
    "form[data-auto]": "the filter bar stops applying itself when a control changes",
}

# Route-level obligations: a hook only the screen that draws the control can carry.
# `input[data-all-for]` is here and not implied by "has a tick box", because the two
# are not the same statement: `/analysis` ticks a *pair* (the engine reads the first
# two ids, so a select-all would tick twenty-five rows and silently discard
# twenty-three), which is exactly why that screen draws no select-all - and a checker
# that demanded one would be reporting a page for a control it deliberately does not
# have.  The screens with a bulk action are `/` (pull every ticked row) and `/jobs`
# (run every ticked build), and for those the box is an obligation.
ROUTE_HOOKS = {
    "/runs": {"#runs": "the runs table cannot be refreshed in place (the whole page reloads instead)"},
    "/": {"input[data-all-for]": "the header box cannot tick the page"},
    "/jobs": {"input[data-all-for]": "the header box cannot tick the page"},
    "/builds": {"input[data-all-for]": "the header box cannot tick the page"},
}

# The symptom of each capability hook, said once (the obligation's own wording names
# the control, so the two can be read together).
HOOK_SYMPTOM = {
    "[data-status]": "a pressed button's answer (started, refused) is never shown",
    "input[data-all-for]": "the header box cannot tick the page",
    "input[data-stops]": "the number boxes lose their value rail",
}

STUB = ('<section class="panel"><div class="head"><h2>stub</h2></div>'
        '<div class="body">tools/check_hooks.py</div></section>')


def queried(script: str) -> list:
    """Every literal selector the script hands to querySelector/getElementById, sorted."""
    found = set()
    for match in re.finditer(r"querySelector(?:All)?\(\s*[\"'`]([^\"'`]+)[\"'`]", script):
        found.add(match.group(1))
    for match in re.finditer(r"getElementById\(\s*[\"'`]([^\"'`]+)[\"'`]", script):
        found.add("#" + match.group(1))
    return sorted(found)


def stripped(markup: str) -> str:
    """The document without its stylesheet and its script.

    The script is a *string in the page*, and it is full of the very selectors and
    attributes this tool looks for: `drawTable()` mentions `name="selected"`, the
    bridge mentions `[data-status]`.  Scanning the whole document therefore reported
    obligations the markup had nothing to do with - a phantom failure of exactly the
    kind that teaches a reader to ignore a checker.  The script is checked by
    `test_dom.js`/`test_notice.js`, which run it; this tool is for the markup.
    """
    for tag in ("script", "style"):
        markup = re.sub(rf"<{tag}\b.*?</{tag}>", "", markup, flags=re.DOTALL | re.IGNORECASE)
    return markup


def present(markup: str, selector: str) -> bool:
    """Whether a simple selector appears in rendered markup.

    Deliberately not a CSS engine: the script's selectors are ids, classes,
    attributes and one descendant step, and a stub DOM that answered "maybe" for the
    rest would be a third place for this contract to be wrong.  A selector this
    cannot judge is reported as unjudged rather than as present.
    """
    tail = re.split(r"[\s>+~]+", selector.strip())[-1]
    # The attribute test comes first: `form[data-auto]` and `input[data-stops]` are
    # tag plus attribute, and it is the attribute the script asks for.  Forgetting to
    # strip the brackets here reported every one of those hooks missing on a page that
    # had them all - five phantom failures, which is how a checker gets ignored.
    attr = re.search(r"\[([A-Za-z0-9_-]+)(?:([\^$*]?=)\"?([^\]\"]*)\"?)?\]", tail)
    if attr:
        name, _, value = attr.groups()
        if value:
            return re.search(rf'\s{re.escape(name)}="{re.escape(value)}', markup) is not None
        return re.search(rf"\s{re.escape(name)}(=|\s|>)", markup) is not None
    if tail.startswith("#") and re.fullmatch(r"#[A-Za-z0-9_-]+", tail):
        return re.search(rf'id="{re.escape(tail[1:])}"', markup) is not None
    if tail.startswith(".") and re.fullmatch(r"\.[A-Za-z0-9_-]+", tail):
        return re.search(rf'class="[^"]*\b{re.escape(tail[1:])}\b', markup) is not None
    return False


def body_for(route: str, view: View) -> tuple:
    """The page's own markup, from the pages package when it exists.

    Until the screens are ported there is nothing to draw, and a checker that
    refused to run until then would be a checker nobody runs during the port - so
    a missing page module is answered with a stub body and said out loud.
    """
    try:
        from lib.gui.design import pages
    except ImportError:
        return STUB, False
    drawer = pages.PAGES.get(route)
    if drawer is None:
        return STUB, False
    return drawer(view), True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--route", default="/", help="the screen to render")
    parser.add_argument("--body", default="", metavar="FILE",
                        help="check this body instead of rendering a screen")
    parser.add_argument("--lang", default="en", choices=("en", "zh"))
    parser.add_argument("--api-url", default="", help="the API the page should be pointed at")
    parser.add_argument("--rows", type=int, default=25)
    args = parser.parse_args(argv)

    base = args.api_url or api_mod.LOCAL
    gui = app.Gui(rows=args.rows, api=api_mod.Api(base, timeout=20))
    check = Filter(limit=args.rows, origin="any")
    try:
        rows = design_data.rows(gui, check, args.lang)
        view = View(rows, check, args.lang, args.route, gui, gui.apis)
        if args.body:
            with open(args.body, encoding="utf-8") as handle:
                body, real = handle.read(), True
        else:
            body, real = body_for(args.route, view)
        markup = design_shell.document(view, body)
    except Exception as exc:                                     # noqa: BLE001 - reported, not raised
        print(f"X {args.route} could not be rendered: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"{args.route} [{args.lang}]  {len(markup):,} bytes  "
          f"({'a real screen' if real else 'the shell around a stub body'})")
    markup = stripped(markup)
    wanted = dict(SHELL_HOOKS)
    if real:
        wanted.update(PAGE_HOOKS)
        wanted.update(ROUTE_HOOKS.get(args.route, {}))
        implied = {sel: (symptom, control) for sel, markers, control in IMPLIED
                   if any(marker in stripped(body) for marker in markers)
                   for symptom in (f"{control} is drawn, so {HOOK_SYMPTOM[sel]}",)}
        wanted.update(implied)
    missing = []
    for selector, symptom in sorted(wanted.items()):
        if not present(markup, selector.split(",")[0]):
            missing.append((selector, symptom))
    # The script also queries things only a page body can carry (`#runs tbody`,
    # `input[name=selected]`).  They are listed rather than judged: a stub body has
    # none of them, and calling that a failure would train the reader to ignore this
    # tool exactly when the ported screens are what it is for.
    body_level = [one for one in queried(design_script._JS)
                  if one not in wanted and not present(markup, one.split(",")[0])]
    for selector, symptom in missing:
        print(f"  MISSING {selector:24s} {symptom}")
    if real:
        for selector, _markers, control in IMPLIED:
            if selector not in wanted:
                print(f"  n/a     {selector:24s} this screen has no {control}")
    print(f"  {len(wanted) - len(missing)}/{len(wanted)} hooks present"
          + (f"; page-level, not judged here: {body_level}" if body_level else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
