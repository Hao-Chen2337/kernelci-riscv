# SPDX-License-Identifier: LGPL-2.1-or-later
"""The `Run` side: what is running, what the queue holds, and what a reader may do about it.

`run_rows` is the activity table's rows, `busy` is the one-writer lock's answer (the
ledger, the download tree and the table have one writer each), `worker_state` and
`job_rows`/`job_node_rows` are the jobs queue as `/worker` asks it - the queue is read
once and the platform/runtime boxes are built out of the same answer the table shows -
and `pull_acts` is the download tree's own activities, which is where the panel's
`pull` rows come from.

All of them read `lib/run.py` and `lib/job.py` per request, for the same reason
`reads` does: the page starts the processes that write what it is showing."""

import json
from collections.abc import Iterable
from typing import Any

from .. import errors, layout
from .. import run as run_mod
from ..kjob import Kjobs
from ..tests import TESTS
from .forms import _tests_of
from .models import Filter
from .schema import KINDS, LIVE_KEPT, WRITE_KINDS
from .server import _request_scratch

# The `Run` kind a `pull_worker.py` activity carries - `schema.KINDS`'s own spelling
# of it, which is also what `actions.start()` writes into `run.json` and what `/runs`
# groups the rows under.  Named once here rather than spelled in the loop below: two
# spellings of a kind is how one of them stops matching the rows it is looking for.
WORKER_KIND = KINDS["worker"]

# The activity kinds whose argv can name **builds** - the ones whose row may carry a
# ledger tally (`_add_tallies`).  `table.py run --build …` is the one on this
# deployment (17 of 77 activities); `runday.py --days` and `table.py index --days`
# name a window and a tree instead, and a `fetch` names none, so their rows ask the
# ledger nothing.  The list is by kind and not by flag because the flag is the
# activity's own business: `_builds_of` still has to find a `--build` in the argv, and
# a kind whose command never grows one simply never pays for the read.
TALLY_KINDS = ("run", "runday", "table")


def _api_of(argv: Iterable[str]) -> str:
    """The API base an activity's own argv names: its `--api-url` value, or `""`.

    `_builds_of`'s shape for the other flag a page has to read back.  The argv *is*
    the command that ran (`lib/run.py`'s header), so this is the one place that can
    say which queue an activity was really claiming from - and the one fact the worker
    page cannot get from its own `?api=` key, because the key is what the *page* reads
    and the argv is what the *worker* read.  The two disagreeing is not a bug in
    either: it is a page that shows one queue beside a worker that took work out of
    another, with nothing on screen saying so.

    Read the way the entry point writes it (`gui.actions`, `*api`), not guessed: only
    a `--api-url` followed by a value counts, and an activity whose command carries no
    such flag (`table.py pull`) answers `""` - "no base named", never the launch base.
    """
    parts = [str(one) for one in argv]
    for at, one in enumerate(parts[:-1]):
        if one == "--api-url" and not parts[at + 1].startswith("-"):
            return parts[at + 1].rstrip("/")
    return ""


def _builds_of(argv: Iterable[str]) -> set[str]:
    """The build ids an activity's own argv names: every `--build <id>` pair in it.

    Read off the argv and not off the run's id, its `what`, or a page's memory of what
    was ticked: the argv *is* the command that ran (`lib/run.py`'s header), so a row
    that shows a tally shows the ledger of exactly the builds that command was given -
    including one an operator typed by hand.  `--build` is what `table.py pull` and
    `table.py run` take (`lib/gui/actions.py` builds both), repeated once per build.
    """
    found: set[str] = set()
    parts = [str(one) for one in argv]
    for at, one in enumerate(parts[:-1]):
        if one == "--build" and not parts[at + 1].startswith("-"):
            found.add(parts[at + 1])
    return found


class ActivitiesMixin:
    def job_rows(self, check: "Filter | None" = None) -> list[dict[str, Any]]:
        """One row per (build, test): the local table minus the ledger, vizualised."""
        check = check or Filter(limit=self.rows, origin="any")
        table, records = self._state()
        held = self.all_locals()
        tests = _tests_of(check)
        gap = {(build.build_id, test) for build, test, _ in self.todo(check)}
        rows = []
        for build in table:
            local = held.get(build.build_id) or self.local_of(build.build_id, build.kbuild)
            if not check.accepts(build.kbuild, records, local):
                continue
            # One reason per (build, test), looked up rather than recomputed: the
            # column is `build.missing(test)`, which stats every artifact the test
            # needs, and the same pair is reachable from more than one row of this
            # page (`_tests_of` returns all three when no test is chosen).
            reasons = {test: "; ".join(build.missing(test)) for test in tests}
            for test in tests:
                if not check.accepts(build.kbuild, records, local, test=test):
                    continue
                record = records.last(test, build.build_id)
                rows.append({"build_id": build.build_id, "test": test,
                             "tree": build.kbuild.tree if build.kbuild else "",
                             "describe": build.describe(),
                             "needs": ", ".join(TESTS.get(test, {}).get("needs", ())),
                             "reason": reasons[test],
                             "runs": len(records.for_build(build.build_id).for_test(test)),
                             "verdict": record.verdict if record else "",
                             "when": record.timestamp if record else "",
                             "source": record.source if record else "",
                             "gap": (build.build_id, test) in gap})
        return rows[check.offset:check.offset + check.limit]

    def job_node_rows(self, check: "Filter | None" = None, state: str = "",
                      limit: int = 0) -> tuple[list[dict[str, Any]], str]:
        """The API's queue as `(rows, why there are none)`.

        The reason is returned rather than kept on `Gui`: this server is threaded,
        and an instance attribute would put one request's failure on another
        request's page.  An empty string means the API answered.

        `limit` is how wide *this caller* wants the read to be, and the read is as
        wide as the widest caller of one page needs: `Filter.limit` (50 by default)
        is a table's print cap, and reading the queue at that width and then reading
        it *again* at `QUEUE_ROWS` is what made `/worker` pay four calls and 680,254
        bytes for one answer (`docs/gui-rework/01-perf.md` §F4).  The rows come back
        in the API's own order and only the row filters `check.job`/`check.text` are
        applied, so a caller that wants the first `check.limit` of them slices this
        answer rather than asking for it twice.
        """
        check = check or Filter(limit=self.rows, origin="any")
        try:
            found = Kjobs(self._client(self.api_base(check))).getjob(
                state=state or None, limit=max(limit, check.limit))
        except errors.KciError as exc:
            return [], str(exc)
        seen = set(self.worker_state().get("seen") or [])
        rows = []
        for job in found:
            if check.job and job.name != check.job:
                continue
            if check.text and check.text.lower() not in \
                    f"{job.name} {job.node_id} {job.state} {job.result}".lower():
                continue
            rows.append({"node_id": job.node_id, "name": job.name, "state": job.state,
                         "result": job.result, "platform": job.platform, "runtime": job.runtime,
                         "created": job.created, "definition": bool(job.definition_url),
                         "claimed": job.node_id in seen})
        return rows[:limit or check.limit], ""

    def worker_bases(self, kept: int = LIVE_KEPT) -> list[str]:
        """The API bases the worker activities **on this screen** are claiming from.

        The worker page's other half.  Its queue table is drawn from this request's
        `?api=` key and says so in its query line; the live panel beside it lists the
        activities with their own argv, and a worker among them names the base it
        really read.  A page can therefore show `asked the API: https://api.kernelci.org
        … rows 0` above a worker that ran `--api-url http://127.0.0.1:8001` - and the
        operator reads that as "the worker never claimed anything", when the truth is
        that the two halves are about two different queues.  This is that fact as
        data: the bases, so the page can name them and link to each one.

        **The same rows the live panel shows** - running first, then the first `kept`
        that have ended - because a note explaining two halves of one screen has to be
        about the rows the reader can see.  Walking every worker activity ever run
        would put yesterday's failed run on today's page for ever, and the note would
        be about nothing on screen (`05-i18n-prose.md` §B.1's restatement test); the
        ended ones are `LIVE_KEPT` and not this list's own decision, so the panel and
        the note widen together the day that number changes.

        Empty strings are dropped, not returned: `_api_of` answers `""` for an argv
        with no `--api-url` (an activity started before the page carried the key, or
        by hand), and "no base named" is not a base the page could link to.
        """
        rows = self.run_rows()
        running = [one for one in rows if one["state"] == run_mod.RUNNING]
        ended = [one for one in rows if one["state"] != run_mod.RUNNING][:kept]
        found: list[str] = []
        for one in (*running, *ended):
            if one["kind"] != WORKER_KIND:
                continue
            base = _api_of(one["argv"])
            if base and base not in found:
                found.append(base)
        return found

    def worker_state(self) -> dict[str, Any]:
        """The worker's own state file, read as the document `poller.py` wrote it.

        Displayed, never interpreted: the cursor/seen/pending rules belong to
        `poller.py`, and this page only shows what that file says.
        """
        try:
            with open(layout.worker_state(), encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, ValueError):
            return {}
        return stored if isinstance(stored, dict) else {}

    def runs(self) -> list[Any]:
        """Every activity on disk, read once per request.

        `Run.load_all()` walks `var/runs` and parses every `run.json`, and one
        `/analysis` render asked for it **104 times** - 104 opens over ~50 activity
        directories for a page that shows none of them, because `_shell` wants the
        count, `busy()` wants the writers and `/runs` wants both
        (`docs/gui-rework/01-perf.md` §F2.3, BASELINE.md).  Cheap in absolute terms
        and still wrong: it is one fact read over and over inside one render, and it
        grows with every activity ever run, which nothing prunes.

        Cached like `_state()` and `all_locals()`, and in the request's scratch
        rather than on `Gui`, for the reason the `_LOCAL` comment gives: the next
        request has to see what the last writer wrote.
        """
        held = _request_scratch()
        if "runs" not in held:
            held["runs"] = run_mod.Run.load_all()
        return held["runs"]

    def run_rows(self, kind: str = "", state: str = "") -> list[dict[str, Any]]:
        """Every activity on disk - the workflow monitor's table.

        `kind` is a **comma list** as well as one name.  The page's own default is a
        *set* of kinds ("everything but the bookkeeping", `FOLDED_KINDS`) and a set
        that the URL can carry is a set the URL can be reloaded with, the poll's guard
        can compare, and the filter box can show - which is why the fold is filter
        state and not a trick of the renderer (`_runs`, `04-actions.md` §P8a).

        `tally` is the ledger's `{verdict: n}` over the builds this activity's own
        **argv** names (`_builds_of`), and it is here rather than on the page because
        the refreshed row needs it too: the 2 s poll writes its answer back into
        `#runs` with the same cells `_runs_table` drew (`templates._JS`), so a cell
        the server can fill and the script cannot is a cell that empties itself two
        seconds after the page was drawn.  It is read from `self._state()` - the one
        `Records.load()` of this request, memoed in the request's scratch like every
        other read here - and only when a row actually names a build: a `table.py
        index` argv names a window, not a build, so the 50 bookkeeping rows on this
        deployment cost one `--build` scan each and no ledger read at all.
        """
        wanted = {one for one in str(kind or "").split(",") if one}
        found = [{"id": one.id, "kind": one.kind, "state": one.state, "what": one.what,
                  "age": one.age(), "seconds": round(one.seconds(), 1), "log": one.log,
                  "exit_code": one.exit_code, "argv": list(one.argv),
                  "tally": {},
                  # `started` and `ended` are epoch floats the activity writes about
                  # itself (`lib/run.py:82-83`; `ended` is 0.0 while it runs), and they
                  # are what make the finish notice truthful.  Without them the only
                  # signal a page has is "the id I saw running is not running now",
                  # which cannot tell a finish that happened *while the reader watched*
                  # from one that happened before the page was drawn - so a reload
                  # re-announced an old finish for ever, which is the lie the notice
                  # exists to avoid.  With them the shell stamps the moment it drew the
                  # page (`data-drawn`) and `ended > drawn` is a fact about the run
                  # rather than an inference about the poll (`07-shell.md` §C1).
                  #
                  # `started` is also half the notice's key: the id is a
                  # second-resolution stamp plus the kind, and two activities of one
                  # kind started in the same second shared it until `Run._free_id`
                  # (`lib/run.py:89`) suffixed the collision.
                  "started": one.started, "ended": one.ended}
                 for one in self.runs()
                 if (not wanted or one.kind in wanted) and (not state or one.state == state)]
        self._add_tallies(found)
        return found

    def _add_tallies(self, rows: list[dict[str, Any]]) -> None:
        """Fill each row's `tally` from the ledger, for the rows whose argv names builds.

        One pass over the ledger for every row that wants a number, and no read at all
        when none does.  A row counts the records of **its own** builds: two `table.py
        run` activities over the same ticked builds show the same tally, which is the
        truth - they asked the same question of the same ledger.

        The verdicts are `Records.tally()`'s own words (`lib/judge.py` writes them),
        and only the counts cross into the page: the word for a verdict is the
        catalogue's (`run_end.tally_one`, `verdict.label.*`).
        """
        wants = [_builds_of(one["argv"]) if one["kind"] in TALLY_KINDS else set()
                 for one in rows]
        if not any(wants):
            return
        per_build: dict[str, dict[str, int]] = {}
        for record in self._state()[1]:
            slot = per_build.setdefault(record.build_id, {})
            slot[record.verdict] = slot.get(record.verdict, 0) + 1
        for row, build_ids in zip(rows, wants):
            counts: dict[str, int] = {}
            for build_id in build_ids:
                for verdict, n in per_build.get(build_id, {}).items():
                    counts[verdict] = counts.get(verdict, 0) + n
            row["tally"] = counts

    def busy(self, rows: "list[dict[str, Any]] | None" = None) -> list[str]:
        """The writers running right now - one at a time, and the page says which.

        `rows` is an answer `run_rows()` already gave, and it is what lets the shell
        read the activities once: it needs them three times in one render - the live
        panel, this banner, and the counts - and the answer to "what is running" is
        the same list every time.  Left out, it reads them itself, because the writer
        gate in `start()` asks this question on its own.

        "Something is running" and "writes are refused" are **two different facts**
        and this method is only the second: a running `results` or `trend` shuts no
        gate, so a page that showed it here would refuse work nobody is holding
        (`07-shell.md` §A4).  The live panel is where the first fact lives.
        """
        found = self.run_rows() if rows is None else rows
        return [one["id"] for one in found
                if one["state"] == run_mod.RUNNING and one["kind"] in WRITE_KINDS]

    def pull_acts(self) -> list[dict[str, Any]]:
        """Every pull act recorded on this machine, newest first - what was pulled, and when."""
        found = []
        for local in self.all_locals().values():
            for act in local.acts:
                found.append({"build_id": local.build_id, "at": str(act.get("at") or ""),
                              "error": str(act.get("error") or ""),
                              "entries": list(act.get("entries") or []),
                              "node_id": str(local.pull.get("node_id") or ""),
                              "entries_count": len(act.get("entries") or []),
                              "bytes": sum(int(one.get("bytes") or 0)
                                           for one in (act.get("entries") or [])
                                           if isinstance(one, dict))})
        found.sort(key=lambda one: (one["at"], one["build_id"]), reverse=True)
        return found



