# SPDX-License-Identifier: LGPL-2.1-or-later
"""`python3 -m lib.i18n …` -- this file is the door, `check.py` is the command.

A package's `__main__.py`, not its `__init__.py`, is what `-m` runs, so the lines
below are the whole of the entry: import the real main, hand it argv, exit with
what it returns.
"""

import sys

from .check import _main

if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
