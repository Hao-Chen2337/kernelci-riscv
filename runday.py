#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run a day's worth of builds - the rotation, not the queue.

Draft this file is built from (``runday's``)::

    (empty - a day of runs)

`run_latest` answers "the newest build"; the worker answers "whatever the API
offers"; neither answers "everything from Tuesday", which is what a lab that
was switched off over the weekend needs, and what `supervise-run.sh` used to
approximate by looping `./run.sh build index` + `./run.sh run` (that script is
deleted: a loop around two commands is this file now).

Same pipeline, different selector: builds for the day -> make them -> jobs ->
run.  The ledger decides what still has to run, so a day re-run twice runs
nothing twice.

    exit status: 0 all passed, 1 any test failed, 3 infrastructure
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# **An activity's log is read while it runs.**  stdout redirected to a file is
# block-buffered, so `print()`s sat in a 4 KiB buffer: a `table.py pull` of fifty builds
# wrote a 0-byte `run.log` for minutes, and an activity killed mid-flight left an empty log
# behind - the page could not show progress it had been told nothing about.  Line
# buffering is what makes every printed line arrive when it happens.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from lib import build as build_mod
from lib import config, errors, kbuild
from lib import job as job_mod
from lib import re as re_mod


def main(argv=None):
    """The command line: a bad flag is exit 3 with a message, never a silent no-op."""
    try:
        return _main(argv)
    except errors.KciError as exc:
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _day_filters(day: str):
    """The API's own filters for the one calendar day `day`, in UTC.

    The API is askable by revision field - `created__gte` / `created__lt`, both
    ISO-8601 timestamps, the same spelling `Kbuilds` uses for its window - so a
    day is the half-open range [00:00:00, next 00:00:00).  A closed
    `created__lte` of `23:59:59` would drop a build created in the day's last
    second, and a day that silently loses a build is the failure this flag was
    fixed for.

    The date is read here and not handed on: `--day not-a-date` used to be
    accepted in silence, and an API asked for `created__gte=not-a-date` answers
    `0` - a day with no builds and "nothing ran" reported as success.

    UTC, and spelled out as such: the window is the day the API's own clock is
    on, which is the clock `created` is stamped with and the one `_iso_ago()`
    reads for the rolling window next to it.
    """
    try:
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise errors.ConfigError(
            f"--day wants an ISO date (YYYY-MM-DD), got {day!r}") from None
    return {"created__gte": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "created__lt": (start + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")}


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tree", default="riscv")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--day", default="",
                        help="ISO date (YYYY-MM-DD, UTC) to run, instead of --days")
    parser.add_argument("--days", type=int, default=1,
                        help="how many days back to look (default: 1); --day names one day")
    parser.add_argument("--test", action="append", choices=sorted(job_mod.TESTS))
    parser.add_argument("--redo", action="store_true",
                        help="run even what the ledger already has a record for")
    parser.add_argument("--limit", type=int, default=20)
    config.run_flags(parser)
    args = parser.parse_args(argv)
    # A cap below one runs nothing (`[:0]`) or drops the newest builds (`[:-5]`),
    # and both used to end in exit 0 - "nothing ran" reported as success.
    if args.limit < 1:
        raise errors.ConfigError(f"--limit must be at least 1, got {args.limit}")
    run = config.run_from(args)

    api = config.client(args)
    # **One selector, not two.**  `--day` names a calendar day and the day
    # *replaces* the rolling `--days` window; `--days` is what is left for a
    # caller that names no day.  `days=0` is how `getdays` is told to bring no
    # window of its own - which is exactly what lets the day's own
    # `created__gte`/`created__lt` through, per its `extra` rule ("a
    # `created__gte` in it is kept only when `days` asked for no window").  The
    # reading this replaced was no reading at all: `args.day` was parsed and
    # never mentioned again, so `--day 2020-01-01` sent yesterday's window and
    # `--day not-a-date` was accepted in silence.
    day = _day_filters(args.day) if args.day else None
    builds = kbuild.Kbuilds(api).getdays(
        args.tree, 0 if day else args.days, args.branch, extra=day)[:args.limit]
    records = None if args.redo else re_mod.Records.load()
    tests = tuple(args.test or ()) or job_mod.DEFAULT_TESTS

    # A copy nobody registered is a row the builds page can only show as "no card
    # in the local table", and its own drill-down buttons then refuse the build id
    # - so the registration travels with the pull, inside `Job.make()` (see the
    # note below); this loop used to do it by hand after its own `make()`.
    #
    # **No `make()` here, and no `remember()` either.**  Both belong to the job:
    # `Job.make()` pulls exactly the artifacts its test needs and registers the
    # build it pulled (`Builds.remember`), and `Job.run()` wraps it in the guard
    # that turns an unreachable artifact into an infra Outcome instead of an
    # exception - so one build this machine cannot fetch no longer cancels the
    # rest of the day.  Calling `make()` here, outside that guard, is what made
    # `table.py run` end after six seconds with nothing done (see its own note);
    # this loop had the identical line.
    outcomes = []
    for kb in builds:
        made = build_mod.Build(kb)
        for j in job_mod.Jobs.for_build(made, tests=tests):
            if records is not None and records.last(j.test, made.build_id) is not None:
                print(f"skip {made.build_id} {j.test} (already recorded)")
                continue
            outcome = j.run(run, sinks=run.sinks(), source="runday")
            outcomes.append(outcome)
            if not outcome.passed:
                print(f"! {made.build_id} {j.test}: {outcome.detail}", flush=True)

    for outcome in outcomes:
        outcome.print()
    if not outcomes:
        return errors.EXIT_PASS
    # The same classification `table.py run` makes: an infra Outcome is exit 3
    # ("we never got a verdict"), never exit 1 ("a test failed").
    if any(one.exit_code == errors.EXIT_INFRA for one in outcomes):
        return errors.EXIT_INFRA
    return errors.EXIT_TEST_FAIL if any(not o.passed for o in outcomes) else errors.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
