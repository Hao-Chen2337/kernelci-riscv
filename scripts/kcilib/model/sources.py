# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Sources: who decides what this run should execute.

Only the chooser varies: "table" (local index minus ledger) or "newest" (the
newest usable production build).  The events worker is not a source - it is a
state machine, not a jobs() iterator.

A source sits in the model because it answers with Jobs: what a source may NOT
do is run anything or import the execution layer, which is what keeps "where a
job comes from" replaceable.

Rationale: docs/code-notes/A-sink-source-dashboard.md.
"""

from kcilib.api import PRODUCTION_API
from kcilib.core import policy
from kcilib.table.build import BuildQuery, builds_from_production_api
from kcilib.table.buildindex import BuildIndex

from .jobs import jobs_for
from .views import todo


class JobSource:
    """A pull source: something that can say what to run right now.

    Subclasses implement jobs() only: they must not run anything or import the
    execution layer, which keeps "where a job comes from" replaceable.
    """

    name = "?"

    def jobs(self, tests=None):
        raise NotImplementedError


class TableSource(JobSource):
    """The local index minus what the ledger already has."""

    name = "table"

    def __init__(self, db=None, tests=None):
        self.index = BuildIndex(db)
        self.tests = tuple(tests) if tests else policy.DEFAULT_TESTS

    def jobs(self, tests=None):
        """(jobs, skipped, builds_checked) - see kcilib.model.views.todo."""
        return todo(self.index, tests=tests or self.tests)


class NewestSource(JobSource):
    """The newest usable production build, and the tests it can support.

    What ./run.sh fetch does, expressed as a source.  Read-only: no token, no
    local stack.
    """

    name = "newest"

    def __init__(self, job="kbuild-gcc-14-riscv", api=PRODUCTION_API,
                 days=3, tests=None, trees=()):
        self.job = job
        self.api = api
        self.days = days
        self.tests = tuple(tests) if tests else policy.DEFAULT_TESTS
        self.trees = tuple(trees)

    def build(self):
        """The newest usable Build, or None (and why, on stderr)."""
        query = BuildQuery(job=self.job, api=self.api, trees=self.trees,
                           result="pass")
        # Widen the window: the API pages old-first, so a quiet tree looks empty.
        for days in (self.days, 7, 30, 180):
            query.since = _days_ago(days)
            builds, _dropped = builds_from_production_api(query)
            if builds:
                return builds[0]
        return None

    def jobs(self, tests=None):
        build = self.build()
        if build is None:
            return [], [(self.job, "no usable build",
                         f"no passing {self.job} in the last 180 days")], 0
        jobs, skipped = jobs_for(build, tests=tests or self.tests)
        return jobs, [(build.build_id, test, reason)
                      for test, reason in skipped], 1


def _days_ago(days):
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.gmtime(time.time() - days * 86400))


SOURCES = {"table": TableSource, "newest": NewestSource}


def get_source(name, **kwargs):
    """Look up a pull source by name (the CLI's --source)."""
    try:
        return SOURCES[name](**kwargs)
    except KeyError:
        raise SystemExit(
            f"unknown source {name!r}; known: {', '.join(sorted(SOURCES))} "
            "(the events source is the worker: ./run.sh worker)") from None
