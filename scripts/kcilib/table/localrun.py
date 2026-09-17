# SPDX-License-Identifier: LGPL-2.1-or-later
#
r"""视图与执行:表里的东西怎么变成一次真的运行,以及怎么回头查。

这一层把三样东西接起来:

    BuildIndex(有哪些构建)  账本(跑过什么)  API(上游眼里什么状态)
                       \        |        /
                        \       v       /
                     todo()  ──>  run_job()

*ran_tests()/todo()* 是纯读:不联网也能回答"我还差多少没跑"。
*run_job()* 是**薄壳** —— 它只做两件事:包住 kcilib.run.jobrun.run_node(那里已经有
下载、烤盘、执行、判决、归档、记账的全部逻辑),再把返回值整理成 RunOutcome。
它**不重复实现任何一步**,因为那些步骤已经被 19 项 guard 钉住了。

没有 callback URL 的定义跑完只落账本 —— 这正是"本地自己造 job"的形态:不碰
任何 API,不依赖上游配置合没合。
"""

import os

from kcilib.core import config, ledger
from kcilib.run.jobrun import SOURCE_TABLE, run_node
from kcilib.table.jobspec import DEFAULT_TESTS, jobs_from_build


def ran_tests():
    """账本 -> {build_id: {已跑过的 test}}。"跑没跑"的唯一来源。

    不看 API:上游记的是"节点状态",账本记的是"这台机器真的跑过"。两者都要,
    但只有账本能离线回答"我跑过没有"。
    """
    ran = {}
    for build_id in ledger.list_builds():
        ran[build_id] = set(ledger.read_results(build_id))
    return ran


def todo(index, tests=None):
    """(构建, 测试) 里还没跑过的那些。纯计算。

    返回 (specs, skipped,builds_checked):
      specs          —— 待跑清单(每个都带着它的 BuildRef)
      skipped        —— [(build_id, test, 原因)],缺构件的构建在这里被剔掉
      builds_checked —— 看了几个构建(便于说清"0 待跑"是真的没有还是筛空了)
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


def outcome_from(body):
    """run_node 的 (url, token, body) -> RunOutcome(含判决与账本路径)。

    判决从 body 反推(callback.verdict_from_body),不重新解析控制台:账本和
    上游收到的必须是同一个结论。
    """
    from kcilib.run.callback import verdict_from_body
    verdict, exit_code, detail = verdict_from_body(body)
    return {
        "verdict": verdict,
        "exit_code": exit_code,
        "detail": detail,
        "status": body.get("status"),
    }


def run_job(definition, run_config=None, node_id=None):
    """跑一个 job 定义 -> RunOutcome。执行层全部复用 run_node。

    定义里没有 callback 段时,run_node 仍然会跑、会归档、会记账,只是没有人
    回传 —— 这正是我们要的"只写账本"模式。

    **报告三元组必须原样带出来**:run_node 交回 (callback_url, token, body),那
    是回传**唯一**的可能来源。这里曾经把它丢掉(只留 url),于是
    `./run.sh run --callback-url URL` 从来没有真的 POST 过 —— 帮助文本和
    jobspec 的说明都在描述一个不存在的回传。出口层(kcilib/sink.py)需要一个可以
    送的东西,所以它现在放在 outcome["report"] 里;没有 callback 段时为 None。
    """
    run_config = run_config or config.RunConfig()
    # source="table": this run came from the local job table, not from the events
    # API, and the ledger's source field says which writer filed the row.  It used
    # to be hardcoded "worker" inside jobrun, so every table run was misfiled.
    callback_url, token, body = run_node(definition, run_config, node_id,
                                         source=SOURCE_TABLE)
    outcome = outcome_from(body)
    outcome["callback_url"] = callback_url
    outcome["record"] = _record_path(definition)
    outcome["report"] = (callback_url, token, body) if callback_url else None
    return outcome


def _record_path(definition):
    """这次运行**实际**落在哪个账本文件,没有就说没有。

    路径是按定义里的构件 URL 重算出来的(和执行层写账本用的是同一套
    result_path),所以它是**预测**,不是回执:账本写失败时(jobrun 里那条
    "could not record this run" 只是警告,不影响回传)预测值仍然成立,而我们
    会把一个不存在的文件报给用户。这里用 os.path.exists 把它变成事实。
    """
    from kcilib.run.artifacts import build_id_from_artifacts
    from kcilib.table.jobspec import test_of
    build_id = build_id_from_artifacts(definition.get("artifacts") or {})
    test = test_of(definition)
    if not build_id or not test:
        return None
    path = ledger.result_path(build_id, test)
    return path if os.path.exists(path) else None
