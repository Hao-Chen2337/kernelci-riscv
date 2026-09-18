# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The interface layer: nodes -> cards -> jobs -> outcomes, plus the stack.

It sits beside kcilib, not inside it: kcilib is what the implementation is
made of, this is what callers are given ("from kci import Kbuilds, Jobs").  A
class here only calls kcilib.* and, where the thing it drives is a script
rather than a library, runs that script's own command line (run.sh for the
stack, scripts/dashboard.py for the page, ./run.sh results for the report) -
it re-implements none of it, and no kcilib module may import back.
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
