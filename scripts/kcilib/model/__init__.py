# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The model: nodes -> cards -> jobs -> outcomes, plus the stack.

This is the layer a caller holds (``from kcilib.model import Kbuilds, Jobs``).
It sits ON TOP of the rest of kcilib - core/, run/, table/, api.py, source.py,
sink.py - and nothing below it may import it back (guards/references.py pins
that edge).  A class here only calls those modules and, where the thing it
drives is a script rather than a library, runs that script's own command line
(run.sh for the stack, scripts/dashboard.py for the page, ./run.sh results for
the report) - it re-implements none of it.

It was a separate top-level package (scripts/kci) between 2026-09-18 and
2026-09-19.  That split did not hold: all five entry points imported kcilib as
well, so the "interface" was a second vocabulary rather than a face, and no
program consumed only it.  One package, one vocabulary.
"""

from __future__ import annotations

from .builds import Kbuild, Kbuilds
from .dashboard import Dashboard
from .jobs import (
    DELIVERY_IN_CONTAINER,
    DELIVERY_LOCAL_SERVER,
    RUN_ARGUMENTS,
    RUN_OVERRIDES,
    SOURCE_FETCH,
    SOURCE_TABLE,
    SOURCE_WORKER,
    Job,
    Jobs,
    Outcome,
)
from .nodes import (
    ORIGIN_API,
    ORIGIN_API_LOCAL,
    ORIGIN_HANDMADE,
    ORIGIN_IMPORTED,
    ORIGIN_SELF_BUILD,
    JobPuller,
    KbuildPuller,
    KernelCINode,
    origin_for,
)
from .results import Record, Results
from .stack import Stack

# Sorted the way ruff's RUF022 wants it (constants, classes, functions).
__all__ = [
    "DELIVERY_IN_CONTAINER",
    "DELIVERY_LOCAL_SERVER",
    "ORIGIN_API",
    "ORIGIN_API_LOCAL",
    "ORIGIN_HANDMADE",
    "ORIGIN_IMPORTED",
    "ORIGIN_SELF_BUILD",
    "RUN_ARGUMENTS",
    "RUN_OVERRIDES",
    "SOURCE_FETCH",
    "SOURCE_TABLE",
    "SOURCE_WORKER",
    "Dashboard",
    "Job",
    "JobPuller",
    "Jobs",
    "Kbuild",
    "KbuildPuller",
    "Kbuilds",
    "KernelCINode",
    "Outcome",
    "Record",
    "Results",
    "Stack",
    "origin_for",
]
