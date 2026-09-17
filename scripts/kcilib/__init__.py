# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Shared library for the RISC-V pull-lab scripts (import with scripts/ on
sys.path, e.g. ``from kcilib.run import judge``).

Three lines live in it (see docs/ARCHITECTURE.md):

    core/    cli config state ports params ledger        - plumbing both run paths share
    run/     poll jobrun runner judge bake artifacts callback delivery - the run path
    table/   buildref jobspec buildindex localrun        - the local job table
    api.py   the one KernelCI API client
    sink.py  where a result goes (ledger always, callback when the job says so)
"""

import os


def repo_root():
    """The repository root - walked up to, not counted in dirname() calls.

    Modules sit at different depths (api.py, core/x.py, run/y.py, table/z.py), and
    a fixed number of dirname() calls is a silent trap: after the last move,
    ledger/buildindex/config/bake each pointed one level short, at scripts/, so
    every artifact was written to scripts/work/ and the ledger read back empty.
    Nothing raised - the paths were just wrong.  Walking up to the directory that
    holds run.sh and scripts/ cannot drift that way.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = here
    for _ in range(6):
        if (os.path.isfile(os.path.join(candidate, "run.sh"))
                and os.path.isdir(os.path.join(candidate, "scripts"))):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    # Nothing matched (a checkout without run.sh, or a harness that copied only
    # kcilib/): fall back to the old answer so callers get a root, not an
    # exception.
    return os.path.dirname(os.path.dirname(here))
