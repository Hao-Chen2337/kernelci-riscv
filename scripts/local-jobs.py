#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The local job table: which builds exist, what to run, what has been run.

    ./run.sh build index [--days N] [--tree T]...   # pull the build index
    ./run.sh jobs  --build <id>                     # list the jobs, run none
    ./run.sh todo  [--build <id>]                   # what is still pending
    ./run.sh summary                                # the ledger at a glance

None of these need upstream configuration merged. It is separate from the worker
because the worker is a standing claimer (polling, cursors, dedup) while this
table only answers what exists and what has run.
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from kcilib import api, sink
from kcilib.core import ledger
from kcilib.source import get_source
from kcilib.table import localrun
from kcilib.table.buildindex import BuildIndex
from kcilib.table.buildref import BuildQuery, builds_from_production_api
from kcilib.table.jobspec import DEFAULT_TESTS, job_definition, jobs_from_build

LOCAL_API = os.environ.get("KCI_API_URL", "http://127.0.0.1:8001")


def _specs_for_build(build, tests):
    """One build's specs, minus the ones the ledger already has."""
    ran = localrun.ran_tests().get(build.build_id, set())
    specs, skipped = jobs_from_build(build, tests=tests)
    return ([spec for spec in specs if spec.test not in ran],
            [(build.build_id, test, reason) for test, reason in skipped], 1)

DAY = 86400


def _iso_days_ago(days):
    return time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.gmtime(time.time() - days * DAY))


def cmd_index(args):
    """Pull the build index from the production API. Read-only, no token needed."""
    query = BuildQuery(
        job=args.job,
        trees=tuple(args.tree or ()),
        result=None if args.any_result else "pass",
        since=args.since or (_iso_days_ago(args.days) if args.days else None),
        limit=args.limit,
    )
    print(f"-> asking {query.api} for {query.job} "
          f"(since {query.since or 'any time'}, "
          f"trees {list(query.trees) or 'any'})")
    refs, dropped = builds_from_production_api(query)
    print(f"   {len(refs)} build(s) usable, {len(dropped)} dropped")
    # Name the drop reasons: "0 builds" is what people chase for hours, and the
    # cause is nearly always one of these.
    reasons = {}
    for _build_id, reason in dropped:
        key = reason.split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
    for key, count in sorted(reasons.items()):
        print(f"     dropped {count}: {key}")
    if not refs:
        # Exiting 0 with no output looks like "no builds exist"; the filter is what
        # found nothing, so say so.
        print("   nothing to add; widen --days/--tree or drop --pass-only")
        return 0
    index = BuildIndex(args.db)
    added, known = index.add_all(refs)
    print(f"   index: +{added} new, {known} already known "
          f"({index.count()} build(s) total in {os.path.relpath(index.path)})")
    newest = refs[0]
    print(f"   newest: {newest.build_id} {newest.tree or '?'} "
          f"{(newest.describe or '')[:40]}")
    return 0


def cmd_jobs(args):
    """List the jobs a build would produce. Runs nothing."""
    index = BuildIndex(args.db)
    build = index.get(args.build) if args.build else None
    if build is None and args.build:
        print(f"build {args.build} is not in the index; run "
              f"'./run.sh build index' first (or check the id)")
        return 1
    if build is None:
        builds = index.newest(1)
        if not builds:
            print("the index is empty; run './run.sh build index' first")
            return 1
        build = builds[0]
    specs, skipped = jobs_from_build(build, tests=args.test)
    print(f"build {build.build_id} ({build.tree or '?'} "
          f"{(build.describe or '')[:40]})")
    for spec in specs:
        print(f"  would run: {spec.test:18s} timeout {spec.timeout_s}s")
    for test, reason in skipped:
        print(f"  skipped  : {test:18s} {reason}")
    return 0


def cmd_todo(args):
    """(build, test) pairs not run yet. Pure subtraction: index minus ledger."""
    index = BuildIndex(args.db)
    ran = localrun.ran_tests()
    tests = tuple(args.test) if args.test else DEFAULT_TESTS
    builds = [index.get(args.build)] if args.build else index.all()
    builds = [b for b in builds if b]
    pending = 0
    for build in builds:
        specs, _skipped = jobs_from_build(build, tests=tests)
        for spec in specs:
            if spec.test in ran.get(build.build_id, set()):
                continue
            pending += 1
            print(f"  {build.build_id}  {spec.test:18s} "
                  f"{build.tree or '?':10s} {(build.describe or '')[:32]}")
    if not pending:
        print(f"nothing pending: {len(builds)} build(s) checked against "
              f"{len(ran)} recorded build(s) in the ledger")
    else:
        print(f"\n{pending} run(s) pending")
    return 0


def cmd_summary(args):
    """The whole table at a glance: index, ledger and local API. Read-only."""
    index = BuildIndex(args.db)
    ran = localrun.ran_tests()
    print(f"build index: {index.count()} build(s) in "
          f"{os.path.relpath(index.path)}")
    if index.count():
        builds = index.all()
        newest, oldest = builds[0], builds[-1]
        print(f"  newest: {newest.build_id} {newest.tree or '?'} "
              f"{(newest.describe or '')[:36]} ({newest.created or '?'})")
        print(f"  oldest: {oldest.build_id} {oldest.tree or '?'} "
              f"({oldest.created or '?'})")
        trees = {}
        for build in builds:
            key = build.tree or "?"
            trees[key] = trees.get(key, 0) + 1
        top = sorted(trees.items(), key=lambda item: -item[1])
        print("  trees: " + ", ".join(f"{name} {count}" for name, count in top[:6]))

    records = 0
    verdicts = {}
    for build_id, tests in ran.items():
        records_for_build = ledger.read_results(build_id)
        for test in tests:
            records += 1
            key = (records_for_build.get(test) or {}).get("verdict") or "-"
            verdicts[key] = verdicts.get(key, 0) + 1
    print(f"ledger: {records} run(s) over {len(ran)} build(s)")
    if records:
        print("  verdicts: " + ", ".join(
            f"{name} {count}" for name, count in sorted(verdicts.items())))
        for (build_id, test), record in _last_runs(ran, 3):
            print(f"  last: {build_id} {test:16s} "
                  f"{record.get('verdict') or '-':5s} "
                  f"{record.get('timestamp') or '?'} "
                  f"{(record.get('detail') or '')[:44]}")

    specs, skipped, checked = localrun.todo(index, tests=args.test)
    print(f"pending: {len(specs)} run(s) over {checked} indexed build(s)"
          + (f"; {len(skipped)} skipped for missing artifacts" if skipped else ""))

    if args.no_api:
        return 0
    stats = api.node_counts(args.api_url)
    if stats is None:
        print("local API: not reachable (start it with ./run.sh stack); "
              "the rest of this report does not need it")
        return 0
    print(f"local API ({args.api_url}):")
    for kind, counts in stats.items():
        total = sum(count for _name, count in counts)
        detail = ", ".join(f"{name} {count}" for name, count in counts[:4])
        print(f"  {kind:9s} {total:4d}  {detail}")
    return 0


def _last_runs(ran, count):
    """The newest *count* (build, test) pairs by their record timestamp."""
    rows = []
    for build_id, tests in ran.items():
        records = ledger.read_results(build_id)
        for test in tests:
            rows.append(((build_id, test), records.get(test) or {}))
    rows.sort(key=lambda row: row[1].get("timestamp") or "", reverse=True)
    return rows[:count]


def cmd_run(args):
    """Run: the source decides what runs; the executor is always the same run_node.

    --source table is the index minus the ledger (default), newest is the newest
    usable production build, and --build only makes sense with source=table. Where
    results go comes from the job definition (kcilib/sink.py), not from argparse:
    the ledger always, plus a callback only when callback.url is set.
    """
    tests = tuple(args.test) if args.test else None
    if args.build and args.source != "table":
        print(f"--build only makes sense with --source table "
              f"(got --source {args.source})")
        return 1
    if args.build:
        index = BuildIndex(args.db)
        build = index.get(args.build)
        if build is None:
            print(f"build {args.build} is not in the index")
            return 1
        planned, skipped, checked = _specs_for_build(build, tests or DEFAULT_TESTS)
    else:
        source = get_source(args.source, db=args.db, tests=tests,
                            job=args.job) if args.source == "table" \
            else get_source(args.source, job=args.job, tests=tests)
        planned, skipped, checked = source.jobs()
        print(f"   source: {args.source} ({checked} build(s) checked)")
    if skipped:
        print(f"   {len(skipped)} skipped (missing artifacts)")
    if args.limit:
        planned = planned[:args.limit]
    if not planned:
        print("nothing to run")
        return 0
    print(f"-> running {len(planned)} job(s), one at a time")
    # Build the definitions first: the sink comes from the definition, not from
    # argparse. Every job in a trip shares one sink (the same --callback-url).
    definitions = [(spec, job_definition(spec, callback_url=args.callback_url))
                   for spec in planned]
    sinks = sink.sinks_for(definitions[0][1])
    if not sink.has_callback(sinks):
        print("   no --callback-url: results go to the local ledger only")
    results = []
    for spec, definition in definitions:
        print(f"\n=== {spec.build_id} / {spec.test} "
              f"({spec.build.tree or '?'} {(spec.build.describe or '')[:36]})")
        try:
            outcome = localrun.run_job(definition, node_id=spec.build.build_id)
        except Exception as error:  # noqa: BLE001 - one job must not stop the batch
            print(f"  run failed before a verdict: {error}")
            results.append((spec, {"verdict": "error", "detail": str(error)}))
            continue
        results.append((spec, outcome))
        print(f"  verdict: {outcome['verdict']} "
              f"(exit {outcome['exit_code']}) {outcome['detail'][:60]}")
        # The sink decides delivery: for the ledger sink it is the record the executor
        # just wrote (kcilib.run.jobrun.record_result), for the callback sink the report
        # triple run_job puts in outcome["report"] (None without a callback section).
        delivered = sink.deliver(sinks, definition, outcome=outcome,
                                 report=outcome.get("report"))
        record = delivered.get(sink.LEDGER)
        if record:
            print(f"  record: {os.path.relpath(record)}")
    failed = [spec for spec, out in results if out.get("verdict") != "pass"]
    print(f"\n{len(results)} run(s): {len(results) - len(failed)} pass, "
          f"{len(failed)} not pass")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="local-jobs.py",
        description="The local job table: which builds exist, what to run, "
                    "what has been run.")
    parser.add_argument("--db", default=None,
                        help="build index path (default work/builds.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="pull the build index from the "
                                           "production API")
    p_index.add_argument("--job", default="kbuild-gcc-14-riscv")
    p_index.add_argument("--days", type=int, default=7,
                         help="only builds newer than N days (0 = any)")
    p_index.add_argument("--since", default=None, help="ISO8601 (overrides --days)")
    p_index.add_argument("--tree", action="append",
                         help="only this tree; repeatable")
    p_index.add_argument("--any-result", action="store_true",
                         help="include failed builds (default: passing only)")
    p_index.add_argument("--limit", type=int, default=200)
    p_index.set_defaults(func=cmd_index)

    p_jobs = sub.add_parser("jobs", help="list the jobs a build would produce")
    p_jobs.add_argument("--build", default=None)
    p_jobs.add_argument("--test", action="append", help="repeatable")
    p_jobs.set_defaults(func=cmd_jobs)

    p_todo = sub.add_parser("todo", help="what has not been run yet")
    p_todo.add_argument("--build", default=None)
    p_todo.add_argument("--test", action="append", help="repeatable")
    p_todo.set_defaults(func=cmd_todo)

    p_sum = sub.add_parser("summary", help="the local job table, at a glance")
    p_sum.add_argument("--test", action="append", help="repeatable")
    p_sum.add_argument("--api-url", default=LOCAL_API)
    p_sum.add_argument("--no-api", action="store_true",
                       help="skip the local-API section (works with no stack)")
    p_sum.set_defaults(func=cmd_summary)

    p_run = sub.add_parser("run", help="run the pending jobs, one at a time")
    p_run.add_argument("--build", default=None)
    p_run.add_argument("--test", action="append", help="repeatable")
    p_run.add_argument("--limit", type=int, default=0,
                       help="stop after N jobs (0 = all pending)")
    p_run.add_argument("--callback-url", default=None,
                       help="post results here as well (default: ledger only)")
    p_run.add_argument("--source", default="table", choices=("table", "newest"),
                       help="where the jobs come from: table = the local index "
                            "minus the ledger; newest = the newest usable "
                            "production build (what ./run.sh fetch does)")
    p_run.add_argument("--job", default="kbuild-gcc-14-riscv",
                       help="with --source newest: which build config")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
