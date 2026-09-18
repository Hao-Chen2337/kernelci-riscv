# SPDX-License-Identifier: LGPL-2.1-or-later
#
r"""Views over the table: what has run, and what is still to run.

Which builds exist (BuildIndex) and what ran (ledger) feed todo(); both are pure
reads that need no network - the ledger answers "did this machine run it", the
API answers "what does upstream think", and only the ledger answers it offline.

It lives in the model, not in table/, because it answers with Jobs: a view that
names the vocabulary has to sit above the index, not beside it.
"""

from kcilib.core import ledger, policy

from .jobs import jobs_for


def ran_tests():
    """Ledger -> {build_id: tests already run}. The one source of "did it run"."""
    ran = {}
    for build_id in ledger.list_builds():
        ran[build_id] = set(ledger.read_results(build_id))
    return ran


def todo(index, tests=None):
    """(jobs, skipped, builds_checked): what is pending, on which builds.

    *skipped* is [(build_id, test, reason)] for tests a build cannot support - a
    reason, never a silent drop - and *builds_checked* is how many builds were
    inspected, so "0 pending" cannot hide an empty index.
    """
    tests = tuple(tests) if tests else policy.DEFAULT_TESTS
    ran = ran_tests()
    builds = index.all()
    pending, skipped = [], []
    for build in builds:
        jobs, build_skipped = jobs_for(build, tests=tests)
        for test, reason in build_skipped:
            skipped.append((build.build_id, test, reason))
        for job in jobs:
            if job.test in ran.get(build.build_id, set()):
                continue
            pending.append(job)
    return pending, skipped, len(builds)
