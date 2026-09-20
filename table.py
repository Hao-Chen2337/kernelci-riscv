#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The local build table, offline: what this machine has, and what it still owes.

    table index     ask the API which builds exist and add them to the table
    table jobs      one build's tests, with the reason for each that cannot run
    table todo      the table minus the ledger: what has not run yet
    table summary   counts by tree and verdict
    table run       run the todo, here, with no API and no stack

This is the line that proves the other two: it executes the same `Job.run()`
with no queue, no container and no callback, so a green run here is evidence
about the worker's path rather than about a second implementation of it.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# **An activity's log is read while it runs.**  stdout redirected to a file is
# block-buffered, so `print()`s sat in a 4 KiB buffer: a `table.py pull` of fifty builds
# wrote a 0-byte `run.log` for minutes, and an activity killed mid-flight left an empty log
# behind - the page could not show progress it had been told nothing about.  Line
# buffering is what makes every printed line arrive when it happens.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from lib import build as build_mod
from lib import config, errors
from lib import job as job_mod
from lib import re as re_mod

COMMANDS = ("index", "jobs", "todo", "summary", "pull", "run")


def _looks_like_network(exc: Exception) -> bool:
    """Is this failure about the way there, rather than about the build?

    The distinction the breaker needs: a build with no `modules` URL fails every time
    (`deadbeef1234`) and the next build deserves its own attempt, while a proxy that cannot
    connect fails *all* of them and the loop should stop.  The evidence is in the message
    because that is where the transport puts it (`ArtifactError` wraps the requests
    exception), and a message this does not recognise counts as "about the build" - the
    safe direction, since stopping on an unknown error would hide real work.
    """
    text = str(exc).lower()
    return any(word in text for word in ("proxy", "timed out", "timeout", "connection",
                                         "unreachable", "temporary failure", "ssl"))


def main(argv=None):
    try:
        return _main(argv)
    except errors.KciError as exc:
        # An infrastructure failure is exit 3, not a traceback and not 1: the
        # exit status says whether a *test* failed, and "the artifact never
        # arrived" is not a test result.
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--build", action="append", default=[],
                        help="one build id; repeat for several")
    parser.add_argument("--test", action="append", choices=sorted(job_mod.TESTS))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--tree", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--redo", action="store_true",
                        help="run even what the ledger already has a record for")
    config.run_flags(parser)
    args = parser.parse_args(argv)
    run = config.run_from(args)

    table = build_mod.Builds.load()
    tests = tuple(args.test or ()) or job_mod.DEFAULT_TESTS
    command = args.command

    if command == "index":
        table.fetch(config.client(args) if not args.no_api else None,
                    tree=args.tree or None, days=args.days, limit=args.limit)
        table.save()
        table.print()
        return errors.EXIT_PASS

    if command == "summary":
        table.print()
        re_mod.render(re_mod.Records.load(), width=60)
        return errors.EXIT_PASS

    if command == "todo":
        for build, test, reason in re_mod.todo(table, tests):
            print(f"{build.build_id}  {test:<16} {reason or 'ready'}")
        return errors.EXIT_PASS

    if command == "pull":
        # Materialize the bytes for the builds the caller names (`--build`, repeated):
        # this is what a page's "pull the selected builds" button runs.
        #
        # **One unfetchable build does not cancel the others.**  `build.make()` raises
        # `ArtifactError` for a build whose URL 404s, whose host is down, or which simply
        # has no URL for an artifact (`deadbeef1234` has no `modules` and no `kselftest`
        # at all) - and the loop used to let that escape, so the rest of the list was never
        # pulled and `table.save()` never ran.  On this workspace that is not hypothetical:
        # three of the 52 cards cannot be fetched, so a blanket pull could never exit 0
        # while still doing 49 builds' worth of correct work
        # (`docs/gui-rework/round2/01-cards.md` §3.5 measured it).  Each build is now its
        # own attempt: the failures are printed as failures, the successes are saved, and
        # the exit code is 3 - this program's "we never got what we came for" - so a
        # button's activity says `failed` only when something really failed.
        wanted = args.build or [b.build_id for b in table]
        failed: list[str] = []
        # **A dead network is not fifty dead builds.**  Each `make()` retries a timeout
        # three times, so a pull of fifty builds against an unreachable artifact host is
        # fifty three-attempt hangs - ten minutes of an activity reporting nothing while
        # the page's own API calls queue behind it (measured: the operator's own 51-build
        # pull ran for minutes against `files.kernelci.org: ProxyError: handshake timed
        # out`).  After two builds in a row fail for a reason that is *about the network*
        # rather than about the build, this stops and says so; whatever was pulled is
        # already saved (`Build.make` writes each artifact as it lands).
        network_failures = 0
        for build_id in wanted:
            build = table.get(build_id)      # a Build already: the table holds cards
            try:
                build.make()
            except (errors.KciError, OSError) as exc:
                failed.append(build_id)
                print(f"! {build_id}: {exc}", flush=True)
                if isinstance(exc, errors.InfraError) or _looks_like_network(exc):
                    network_failures += 1
                    if network_failures >= 2:
                        left = len(wanted) - len(failed)
                        print(f"stopping: {left} build(s) left, and the last two failures "
                              "were the network, not the builds", flush=True)
                        break
                else:
                    network_failures = 0
                continue
            network_failures = 0
            print(f"pulled {build.build_id}")
            build.print()
        table.save()
        if failed:
            count = len(failed)
            print(f"{count} build{'s' if count != 1 else ''} could not be pulled: "
                  + ", ".join(failed), flush=True)
            return errors.EXIT_INFRA
        return errors.EXIT_PASS

    if command == "jobs":
        build = table.get(args.build[0]) if args.build else table.newest()
        job_mod.Jobs.for_build(build, tests=tests).print()
        return errors.EXIT_PASS

    # run: the same executor as the worker, with no queue and no callback
    #
    # The ledger decides what still has to run, exactly as `runday` does it and
    # for the same reason: without this, `table.py run` re-ran every (build, test)
    # pair it was given whether or not the ledger already held a verdict, so a
    # button that says "run the tests this build has not run" ran all of them -
    # and the operator's own note ("这条命令连账本里已经有的也会跑；页面自己不加任何
    # 跳过") was reading the page's refusal to skip as a feature.  `--redo` is the
    # way back to the old behaviour, and it is the *only* difference between this
    # loop and the one in `runday.py`.
    #
    # **One unfetchable build does not cancel the other forty-nine.**  This loop
    # used to call `build.make()` itself, before the skip and outside any guard,
    # so the artifact error of ONE build escaped to `main()` - and because the
    # operator's own 50-build selection starts with `6aa3689720239ade90209d50`
    # (a card whose kernel URL names the local stack's artifact server, up only
    # while he runs it), every run of it ended after **6.2 seconds** with four
    # lines about one dead host and no work at all: 0 of 50 builds attempted, no
    # `running:` line, no outcome, exit 3.  `pull` above has guarded each build
    # since this round began; `run` never got the same treatment, and it did not
    # need the pre-fetch at all: `Job.make()` (lib/job.py) already makes exactly
    # the artifacts a test needs, and `Job.run()` already wraps that in the guard
    # that turns "the artifact never arrived" into an infra Outcome with a ledger
    # record - which is also why the next run skips that pair instead of dying on
    # it again.  All the pre-fetch added was a second, unguarded copy of the same
    # download, run for builds whose every test the ledger was about to skip.
    #
    # The exit status is classified, not guessed: an infra Outcome (`incomplete`,
    # exit 3) is not "a test failed" - `lib/errors.py` reserves 1 for a console
    # that showed a selftest fail, and reporting an unreachable artifact as one
    # would invent a regression.
    #
    # One guard travels with the skip: a run where everything was skipped has no
    # outcomes, and `any(...)` over nothing is False, so without the early return
    # the exit status would say PASS - a day with nothing to do reported as a day
    # that passed its tests.
    source = "table"
    records = None if args.redo else re_mod.Records.load()
    outcomes = []
    skipped = 0
    # `table.get()` hands back a Build already (`pull` above says the same):
    # wrapping it in Build() again makes its `kbuild` a Build, and the first
    # artifact lookup then dies on `Build` having no `artifacts`.
    wanted = [table.get(one) for one in args.build] if args.build else list(table)
    for build in wanted:
        for one in job_mod.Jobs.for_build(build, tests=tests):
            if records is not None and records.last(one.test, build.build_id) is not None:
                print(f"skip {build.build_id} {one.test} (already recorded)")
                skipped += 1
                continue
            # `append`, not `+=`: `Job.run()` answers with one `Outcome`, and only
            # the collection's `Jobs.run()` answers with a list.  Iterating the
            # jobs to skip them means calling the singular one, so the loop has to
            # collect them itself - which is the whole cost of having a per-test
            # skip at all.
            outcome = one.run(run, sinks=run.sinks(), source=source)
            outcomes.append(outcome)
            if not outcome.passed:
                # Said when it happens, not only in the summary at the end: an
                # activity's log is read while it runs, and a fifty-build run
                # that reports its first failure an hour later is the same
                # problem `pull`'s per-build line already fixes.
                print(f"! {build.build_id} {one.test}: {outcome.detail}", flush=True)
    for outcome in outcomes:
        outcome.print()
    if skipped and not outcomes:
        print(f"nothing to run: the ledger already has all {skipped} pair(s)")
    if not outcomes:
        return errors.EXIT_PASS
    if any(one.exit_code == errors.EXIT_INFRA for one in outcomes):
        return errors.EXIT_INFRA
    return errors.EXIT_TEST_FAIL if any(not o.passed for o in outcomes) else errors.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
