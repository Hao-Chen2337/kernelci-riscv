# SPDX-License-Identifier: LGPL-2.1-or-later
#
r"""Views and execution: table rows become a real run, and runs are looked up again.

Which builds exist (BuildIndex) plus what ran (ledger) feed todo(), which feeds
run_job(); ran_tests() and todo() are pure reads that need no network.
run_job() is a thin shell over run_node, which already owns every step.
No callback URL means ledger only - the local "make your own job" mode.
"""

import os

from kcilib.core import config, ledger
from kcilib.run.jobrun import SOURCE_TABLE, run_node
from kcilib.table.jobspec import DEFAULT_TESTS, jobs_from_build


def ran_tests():
    """Ledger -> {build_id: tests already run}. The one source of "did it run".

    Offline by design: the API records node state, only the ledger records what
    this machine really ran.
    """
    ran = {}
    for build_id in ledger.list_builds():
        ran[build_id] = set(ledger.read_results(build_id))
    return ran


def todo(index, tests=None):
    """(build, test) pairs not run yet. Pure computation.

    Returns (specs, skipped, builds_checked): the pending specs, each carrying its
    BuildRef; [(build_id, test, reason)] for builds missing artifacts; and how many
    builds were inspected, so "0 pending" cannot hide an empty index.
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
    """run_node's (url, token, body) -> RunOutcome with its verdict and record path.

    The verdict is derived from the body, never re-parsed from the console: the
    ledger and the upstream callback must carry the same conclusion.
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
    """Run one job definition -> RunOutcome. All execution is run_node's.

    Without a callback section run_node still runs, archives and records, and
    nobody is notified. The (callback_url, token, body) triple is the only source
    of a callback and travels intact in outcome["report"], else None.
    """
    run_config = run_config or config.RunConfig()
    # source="table": tells the ledger which writer filed the row; jobrun used to
    # hardcode "worker", so every table run was misfiled.
    callback_url, token, body = run_node(definition, run_config, node_id,
                                         source=SOURCE_TABLE)
    outcome = outcome_from(body)
    outcome["callback_url"] = callback_url
    outcome["record"] = _record_path(definition)
    outcome["report"] = (callback_url, token, body) if callback_url else None
    return outcome


def _record_path(definition):
    """The ledger file this run actually landed in, or None.

    The path is recomputed from the definition's artifact URLs, so it is a
    prediction, not a receipt; os.path.exists turns it into a fact.
    """
    from kcilib.run.artifacts import build_id_from_artifacts
    from kcilib.table.jobspec import test_of
    build_id = build_id_from_artifacts(definition.get("artifacts") or {})
    test = test_of(definition)
    if not build_id or not test:
        return None
    path = ledger.result_path(build_id, test)
    return path if os.path.exists(path) else None
