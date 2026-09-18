# SPDX-License-Identifier: LGPL-2.1-or-later
#
r"""Views over the table: what has run, and what is still to run.

Which builds exist (BuildIndex) plus what ran (ledger) feed todo(); ran_tests()
and todo() are pure reads that need no network.

No run lives here any more.  This module used to carry run_job() and
outcome_from(), the old shell over kcilib.run.jobrun.run_node; the interface
layer (kci.Jobs and Job.run) took that over on 2026-09-18, and the shell was
left behind with no caller but a guard, so it was deleted when the object
layer moved out to scripts/kci/ - rather than kept as dead weight in the
implementation.
"""

from kcilib.core import ledger
from kcilib.table.jobspec import DEFAULT_TESTS, jobs_from_build


def ran_tests():
    """Ledger -> {build_id: tests already run}. The one source of "did it run".

    Offline by design: the API records node state, only the ledger records what
    this machine really ran.
    """
    ran = {}
    for build_id in ledger.list_builds():
        ran[build_id] = set(ledger.read_results(build_id))
    return ran


def todo(index, tests=None):
    """(build, test) pairs not run yet. Pure computation.

    Returns (specs, skipped, builds_checked): the pending specs, each carrying its
    BuildRef; [(build_id, test, reason)] for builds missing artifacts; and how many
    builds were inspected, so "0 pending" cannot hide an empty index.
    """
    tests = tuple(tests) if tests else DEFAULT_TESTS
    ran = ran_tests()
    builds = index.all()
    specs, skipped = [], []
    for build in builds:
        build_specs, build_skipped = jobs_from_build(build, tests=tests)
        for test, reason in build_skipped:
            skipped.append((build.build_id, test, reason))
        for spec in build_specs:
            if spec.test in ran.get(build.build_id, set()):
                continue
            specs.append(spec)
    return specs, skipped, len(builds)
