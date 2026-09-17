# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Shared library for the RISC-V pull-lab scripts (import with scripts/ on
sys.path, e.g. ``from kcilib.run import judge``).

core/ is plumbing both run paths share, run/ is the run path, table/ the local
job table, api.py the one KernelCI API client, sink.py where a result goes.
Rationale: docs/docs/code-notes/W2c-kcilib.md (layout: docs/ARCHITECTURE.md).
"""

import os


def repo_root():
    """The repository root - walked up to, not counted in dirname() calls.

    Modules sit at different depths, and a fixed dirname() count pointed one
    level short (at scripts/) after a package move: every artifact went to
    scripts/work/ and the ledger read back empty, with nothing raised."""
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
    # No run.sh (a checkout without one, or a harness that copied only kcilib/):
    # fall back to the old answer so callers get a root, not an exception.
    return os.path.dirname(os.path.dirname(here))
