# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Sources: who decides what this run should execute.

Only the chooser varies: "table" (local index minus ledger) or "newest" (newest
usable production build).  The events worker is not a source - it is a state
machine, not a jobs() iterator.  The layers share the boundary instead: every
source yields job definitions for the same run_node.

Rationale: docs/docs/code-notes/A-sink-source-dashboard.md.
"""

from kcilib.api import PRODUCTION_API
from kcilib.table.buildindex import BuildIndex
from kcilib.table.buildref import BuildQuery, builds_from_production_api
from kcilib.table.jobspec import DEFAULT_TESTS, jobs_from_build


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
        self.tests = tuple(tests) if tests else DEFAULT_TESTS

    def jobs(self, tests=None):
        """(specs, skipped, builds_checked) - see kcilib.table.localrun.todo."""
        from kcilib.table.localrun import todo
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
        self.tests = tuple(tests) if tests else DEFAULT_TESTS
        self.trees = tuple(trees)

    def build(self):
        """The newest usable BuildRef, or None (and why, on stderr)."""
        query = BuildQuery(job=self.job, api=self.api, trees=self.trees,
                           result="pass")
        # Widen the window: the API pages old-first, so a quiet tree looks empty.
        for days in (self.days, 7, 30, 180):
            query.since = _days_ago(days)
            refs, _dropped = builds_from_production_api(query)
            if refs:
                return refs[0]
        return None

    def jobs(self, tests=None):
        build = self.build()
        if build is None:
            return [], [(self.job, "no usable build",
                         f"no passing {self.job} in the last 180 days")], 0
        specs, skipped = jobs_from_build(build, tests=tests or self.tests)
        return specs, [(build.build_id, test, reason)
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
