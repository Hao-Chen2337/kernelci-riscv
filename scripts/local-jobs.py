#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""本地任务表:把"有哪些构建可跑 / 我要跑什么 / 跑过什么"变成一张能看的表。

    ./run.sh build index [--days N] [--tree T]...   # 从生产 API 搬构建索引
    ./run.sh jobs  --build <id>                     # 只列出会生成哪些 job,不跑
    ./run.sh todo  [--build <id>]                   # 还没跑的清单
    ./run.sh summary                                # 台账

这四件事都**不依赖上游配置合没合**:index 只读生产 API,其余全在本地算。
所以 1599 还没合的时候,这张表就已经能用了 —— 而它正是"接单模式"的对照组。

为什么单独一个入口,而不是塞进 worker:worker 是**常驻的接单者**,它的问题域是
"轮询、游标、去重、重投";这张表的问题域是"我知道有哪些构建、我跑过哪些"。
两者的共同部分(执行一个 job)已经在 kcilib 里了,这里只做表的事。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from kcilib import sink
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
    """从生产 API 搬构建索引。只读,不需要 token。"""
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
    # Say WHY the drops happened: "0 builds" is the answer people chase for hours,
    # and the reason is nearly always one of these four lines.
    reasons = {}
    for _build_id, reason in dropped:
        key = reason.split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
    for key, count in sorted(reasons.items()):
        print(f"     dropped {count}: {key}")
    if not refs:
        # Printing nothing and exiting 0 would look like "no builds exist"; the
        # filter is what found nothing, so name it.
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
    """列出某个构建会生成哪些 job。不跑任何东西。"""
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
    """还没跑过的 (构建, 测试)。纯减法:索引 − 账本。"""
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
    """台账:索引 + 账本 + 本地 API,一次打全。只读,不需要 token。"""
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
    stats = _api_stats(args.api_url)
    if stats is None:
        print("local API: not reachable (start it with ./run.sh stack); "
              "the rest of this report does not need it")
        return 0
    print(f"local API ({args.api_url}):")
    for kind, counts in stats.items():
        total = sum(counts.values())
        detail = ", ".join(
            f"{name} {count}" for name, count in
            sorted(counts.items(), key=lambda item: -item[1])[:4])
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


def _api_stats(api_url):
    """节点统计,按 kind 分组。API 不可达时返回 None(而不是抛)。"""
    stats = {}
    for kind in ("checkout", "kbuild", "job"):
        try:
            with urllib.request.urlopen(
                    f"{api_url.rstrip('/')}/latest/nodes?kind={kind}&limit=1000",
                    timeout=15) as resp:
                items = json.loads(resp.read()).get("items", [])
        except (urllib.error.URLError, ValueError, OSError):
            return None
        counts = {}
        for node in items:
            name = node.get("name") or "?"
            counts[name] = counts.get(name, 0) + 1
        stats[kind] = counts
    return stats


def cmd_run(args):
    """跑起来 —— 来源决定跑什么,执行层永远是同一个 run_node。

    --source table  : 索引 − 账本(默认;本地表驱动)
    --source newest : 生产上最新的可用构建(./run.sh fetch 的能力,现在只是
                      一个来源,不再是另一条执行路径)

    --build 只在 source=table 时有意义:newest 本来就只有那一个构建。

    结果去哪不在这里判断:出口由 **job 定义** 决定(kcilib/sink.py),账本无条件、
    回传只在定义里带了 callback.url 时才有 —— 原来这里看的是 --callback-url 这个
    argparse 值。
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
    # 定义先全部建好,出口从**定义**算(kcilib/sink.py):"--callback-url 给没给"
    # 是 argparse 的事,"结果去哪"是 job 定义的事。一趟里所有 job 的出口相同,
    # 因为唯一的输入是同一个 --callback-url。
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
        # 结果去哪由出口说了算。账本出口的"送达"就是执行层刚写好的那条记录
        # (kcilib/run/jobrun.py:491 record_result),取回来打印;回传出口要的是
        # run_node 的报告三元组,run_job 现在把它放在 outcome["report"] 里
        # (kcilib/table/localrun.py)—— 没有 callback 段时为 None,出口自己不会要。
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
