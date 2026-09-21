#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The page: what this deployment has, and buttons that run the real commands.

    gui [--port 8079] [--rows 25] [--refresh S]

Read-only apart from the buttons, and every button is a command of this tree
(the root entry points, `deploy/*.sh`) - the page may not become a second
interface with its own behaviour.  One action
at a time: the ledger and the table have one writer each and a page that lets
two runs race is a page that corrupts them.

The page holds no copy of the table or the ledger: `Gui` reads them once per
request (`lib/gui/`, `_state`), because the buttons here start the very
commands that write them.  A page that read them at startup kept saying "six
records" after the seventh was on disk - the operator's "I ran it and nothing
changed" - and only a restart made it true again.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config, errors, gui

# A page waits 10s for the API, not 60: a slow upstream must cost one page, and the
# old dashboard used the same 10s/1-retry patience for the same reason.
GUI_TIMEOUT = 10


def main(argv=None):
    """The command line: a bad flag or a corrupt record is exit 3 with a message, never a traceback.

    `Ledger.read()` raises on a record it cannot parse, on purpose ("a ledger that
    quietly loses rows is worse than none") - and this is where that becomes an exit
    status instead of a traceback with exit 1.  Every entry point in this tree keeps
    the same shape, and `docs/gui-rework/tools/check_structure.py` checks it.
    """
    try:
        return _main(argv)
    except errors.KciError as exc:
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=gui.PORT)
    parser.add_argument("--rows", type=int, default=gui.ROWS)
    parser.add_argument("--refresh", type=int, default=gui.REFRESH)
    parser.add_argument("--api-url", default=None)
    args = parser.parse_args(argv)

    # One console and one class: `Gui` draws the design's screens (`design/serve.py` is
    # its `render`), so there is nothing here for a flag to choose between.  The readers,
    # the actions, the poll and the gates are the engine's either way.
    gui.Gui(port=args.port, rows=args.rows, refresh=args.refresh,
            api=config.client(args, timeout=GUI_TIMEOUT)).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
