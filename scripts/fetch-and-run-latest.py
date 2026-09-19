#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Fetch the newest production riscv kbuild and run it locally with tuxrun.

This file is the entry point and nothing else - the command line, the flow, the
console and the exit status live in kcilib/model/fetch.py, and the run itself is
one Job.run(), the same executor the worker and the local table use.  Same rule
as scripts/riscv_pull_worker.py.

exit status: 0 pass, 1 test failure, 3 infrastructure error
"""

import os
import sys

# scripts/ is resolved through THIS file's own directory: the entry runs from
# any CWD.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kcilib.model.fetch import main

if __name__ == "__main__":
    sys.exit(main())
