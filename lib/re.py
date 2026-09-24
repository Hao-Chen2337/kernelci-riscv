# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reading the ledger: what ran, what did not, and what changed.

Draft this file is built from (``lib/re``)::

    (empty - the results and regression readers)

Three questions, all answered from the records on disk and never from a second
bookkeeping file:

* `Records` - what did this machine run, for which build and test
* `todo()` - which (build, test) pairs have not run yet: the local table minus
  the ledger.  This is what the offline line and the GUI's pending column mean.
* `transitions()` - pass -> fail between consecutive runs of one job: a
  regression, and the only thing a trend reports.

Nothing here writes, and nothing here needs the network.

接口形状（C++，只有声明）：include/kci/view.hpp §17 账本读法（§16 的 Filter 在 lib/gui/）。
"""

import json
from dataclasses import dataclass, field

from . import layout
from .build import Builds
from .errors import VERDICT_FAIL, VERDICT_PASS
from .out import Outcome
from .sink import Ledger

# How much of a record's reason the text report shows.
DETAIL_WIDTH = 60


@dataclass
class Records:
    """Every record read, with the groupings its readers ask for."""

    items: list[Outcome] = field(default_factory=list)

    @classmethod
    def load(cls, build_id=None):
        """Read the ledger (one build, or all of it)."""
        return cls(Ledger.read(build_id))

    @staticmethod
    def builds():
        """The build ids the ledger knows, newest first."""
        return Ledger.builds()

    def for_build(self, build_id):
        """Only the records of one build."""
        return Records([one for one in self.items if one.build_id == build_id])

    def for_builds(self, build_ids):
        """Only the records of these builds, as one `Records`.

        `for_build` narrowed to a set: a page that shows a *window* of builds - the
        filtered, ordered, capped list `/analysis` draws - has to be able to ask the
        ledger about exactly that window, or the counts beside it answer a question the
        reader did not ask ("who passed in the last 25" answered over all 60).
        """
        wanted = set(build_ids)
        return Records([one for one in self.items if one.build_id in wanted])

    def for_test(self, test):
        """Only the records of one test."""
        return Records([one for one in self.items if one.test == test])

    def last(self, test, build_id=None):
        """The most recent record of one test (of one build), or None."""
        found = [one for one in self.items
                 if one.test == test and (build_id is None or one.build_id == build_id)]
        return max(found, key=lambda one: one.timestamp or "", default=None)

    def tally(self):
        """`{verdict: n}` over everything read - one spelling of the verdict set."""
        counts: dict[str, int] = {}
        for one in self.items:
            counts[one.verdict] = counts.get(one.verdict, 0) + 1
        return counts

    def series(self, test, build_id=None):
        """One test's history, oldest first - the order a trend reads it in."""
        found = [one for one in self.items
                 if one.test == test and (build_id is None or one.build_id == build_id)]
        return sorted(found, key=lambda one: one.timestamp or "")

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


def todo(builds: Builds, tests, records: "Records | None" = None):
    """The `(build, test, reason)` triples that have no record yet.

    The table minus the ledger, with the reason a pair cannot run rather than
    silently dropping it - a test a build cannot support is worth reporting.
    """
    known = records if records is not None else Records.load()
    triples = []
    for build in builds:
        for test in (tests or ()):
            if known.last(test, build.build_id) is not None:
                continue
            triples.append((build, test, "; ".join(build.missing(test))))
    return triples


def transitions(records: Records, test=None):
    """Every pass -> fail transition, as `(failed, passed)` record pairs.

    Consecutive failures are ONE regression: only the first failure after a pass
    starts a transition, and the detector re-arms only on a fresh pass.  Without
    that rule one bad build reports a new regression every night it stays bad.
    """
    history = (records.series(test) if test
               else sorted(records.items, key=lambda one: one.timestamp or ""))
    found = []
    last_pass = None
    for record in history:
        if record.verdict == VERDICT_PASS:
            last_pass = record
        elif record.verdict == VERDICT_FAIL and last_pass is not None:
            found.append((record, last_pass))
            last_pass = None
    return found


def render(records: Records, stream=None, width=DETAIL_WIDTH):
    """The `results.py` text: one block per build, newest record first."""
    lines = _render_lines(records, width)
    for line in lines:
        print(line, file=stream)
    return lines


def _render_lines(records: Records, width=DETAIL_WIDTH):
    if not len(records):
        # **An empty ledger is not an error, and this line used to be one.**  It
        # called `Ledger.results_dir()`, which `lib/sink.py` never had, so
        # `results.py` on a ledger with no records died with an AttributeError -
        # exit 1 with a traceback, in the one case its own docstring promises
        # ("exit status is 0 even when there is nothing to show").  Nothing had
        # seen it because this checkout's ledger has never been empty; the seam
        # that made it visible is `$KCI_RESULTS_DIR` (lib/layout.py), which the
        # old tree's gate points at an empty directory.  The path comes from
        # `layout.results()`, the same function the writer uses.
        return [f"no result records in {layout.results()}",
                ("  (a fetch or a worker writes them; an empty ledger means "
                 "nothing has run here yet)")]
    lines = []
    for build_id in _builds_of(records):
        found = records.for_build(build_id)
        passing = sum(1 for one in found if one.verdict == VERDICT_PASS)
        lines.append(f"--- {build_id} ({len(found)} record(s), {passing} pass)")
        for one in sorted(found, key=lambda item: item.timestamp or "", reverse=True):
            exit_code = "-" if one.exit_code is None else int(one.exit_code)
            lines.append(f"  {one.test:<24} {one.verdict or '-':<6} "
                         f"exit={exit_code!s:<3} {one.source or '-':<7} "
                         f"{one.timestamp or '-':<21} {_short(one.detail, width)}")
    return lines


def json_report(records: Records):
    """The same thing as data, for `--json` or a page."""
    return json.dumps([one.record() for one in records], indent=1, sort_keys=True)


def _builds_of(records):
    """The build ids present, newest record first."""
    newest: dict[str, str] = {}
    for one in records:
        stamp = one.timestamp or ""
        if stamp > newest.get(one.build_id, ""):
            newest[one.build_id] = stamp
    return [build_id for build_id, _ in
            sorted(newest.items(), key=lambda item: item[1], reverse=True)]


def _short(text, width=DETAIL_WIDTH):
    """One line of reason, cut to a width a terminal can show."""
    if not text:
        return ""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= width else flat[:width - 1] + "…"
