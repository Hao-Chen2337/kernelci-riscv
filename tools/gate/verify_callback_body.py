#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The LAVA callback body, replayed through the REAL upstream parser.

    python3 tools/gate/verify_callback_body.py     # exit 1 on any failure

**Why this exists.**  The pipeline's callback endpoint has no parser for any
other shape: a body it cannot read loses the result *without an error*, which is
the worst failure this project can have - the run happened, the ledger says so,
and upstream never learns.  So the body is checked against the real parser
(`kernelci.runtime.lava.Callback`, imported from the `kernelci-core` clone in this
checkout) rather than against our own idea of it.

The old tree had this check (`scripts/tools/verify-lava-body.py`, run by what was
`./run.sh verify`) against **kcilib's** builder.  The new tree builds the same body
(`lib/sink.py: lava_body`) and the old gate is going away with `scripts/`, so the
four cases moved here, asserted the same way:

  1. a boot console that passed, and one that failed        -> pass / incomplete
  2. a kselftest TAP console with a `not ok` and rc=0       -> job Complete, the
     hierarchy node fail, `kselftest.riscv.<case>` = fail/pass/skip; the same
     TAP all-passing keeps the node pass
  3. a console with no TAP at all, tuxrun failing the job    -> incomplete +
     Infrastructure, never green
  4. tuxrun refusing the flags (rc=2)                        -> incomplete + Infrastructure

What the new tree decides differently, and is therefore checked *here*: the
verdict comes from the run's Outcome, not from a return code plus a flag - the
console only supplies the cases the body replays.  Case 2 is the one that proves
the two agree: tuxrun exits 0 with failing selftests, and the body must still be
Complete with a failing case, because "Complete" is what lets the pipeline read
the case list as the result.

The consoles in `fixtures/` are real tuxrun output (`scripts/fixtures/` until that
tree is deleted); the other two cases build their console inline so the exact line
the check turns on is visible next to the check.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
# Import kernelci-core from THIS checkout, never from a hardcoded path: that made
# a fresh clone's results depend on the machine it ran on.
sys.path.insert(0, os.path.join(ROOT, "kernelci-core"))

from lib import errors, judge, sink
from lib.job import Job

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BODY_DIR = "/tmp/lava-body-new"

try:
    from kernelci.runtime.lava import Callback
except ImportError as problem:       # pragma: no cover - a fresh clone without setup
    print(f"X cannot import the real parser from {ROOT}/kernelci-core: {problem}\n"
          "  run deploy/setup.sh (it clones the upstream repositories)", file=sys.stderr)
    sys.exit(1)

CHECKS = 0


def check(condition, message):
    """A check that also holds under `python3 -O`: `assert` is stripped there."""
    global CHECKS
    CHECKS += 1
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def body_for(test, console, returncode, node_id="new-tree-check"):
    """One callback body, built the way a real run builds it: judge, then `lava_body`.

    The console goes through `judge.verdict()` first - that is where the verdict
    comes from now - and the same console is handed to `lava_body()` as the text it
    replays.  A `Job` with no build is enough: the body reads its test, its
    definition's platform and its callback URL, none of which need artifacts.
    """
    os.makedirs(BODY_DIR, exist_ok=True)
    outcome = judge.verdict(returncode, console, test)
    body = sink.lava_body(Job(None, test), outcome, console)
    with open(os.path.join(BODY_DIR, f"{node_id}.json"), "w", encoding="utf-8") as handle:
        json.dump(body, handle, indent=1)
    return outcome, body


def report(tag, body, outcome):
    """The same read-back the old gate printed: what the pipeline itself can see."""
    cb = Callback(body)
    print(f"\n===== {tag} =====")
    print("outcome:", outcome.verdict, f"exit={outcome.exit_code}", outcome.detail[:70])
    print("get_job_status:", cb.get_job_status())
    print("get_meta(api_config_name):", cb.get_meta("api_config_name"))
    print("get_meta(storage_config_name):", cb.get_meta("storage_config_name"))
    print("get_device_id:", cb.get_device_id())
    print("is_infra_error:", cb.is_infra_error())
    return cb


def case_boot(tag, log_name, returncode, expect_status):
    """Case 1: a recorded boot console, replayed end to end."""
    with open(os.path.join(FIXTURES, log_name), encoding="utf-8") as handle:
        console = handle.read()
    outcome, body = body_for("boot", console, returncode, node_id=f"boot-{tag}")
    cb = report(f"boot {tag} (rc={returncode})", body, outcome)
    check(cb.get_job_status() == expect_status,
          f"{tag}: get_job_status() is {cb.get_job_status()!r}, expected {expect_status!r}")
    check(cb.get_log_parser() is not None,
          f"{tag}: the log parser is None -> the pipeline would force incomplete")
    parser = cb.get_log_parser()
    check(len(parser.get_text().splitlines()) > 0,
          f"{tag}: the log parser read no target lines out of a real console")
    if expect_status == "pass":
        check(cb.get_results(), f"{tag}: a passing boot must carry its cases")
    else:
        # **A failed boot carries no case result on purpose**, and that is why its
        # status has to be Incomplete: the reason lives in the `job` case's metadata
        # (`error_msg`), and a body that reported Complete with an empty case list
        # would tell the pipeline "nothing failed".  `is_infra_error()` is False
        # here: a boot that failed is a *job* failure, not infrastructure.
        check(not cb.is_infra_error(),
              f"{tag}: a failed boot is a Job error, not Infrastructure")
    print("ALL good:", cb.get_job_status(), f"({len(parser.get_text().splitlines())} log lines)")


def case_kselftest():
    """Case 2: tuxrun exits 0 with a failing selftest - Complete, hierarchy fail."""
    tap = ("2026-09-08T00:00:00 lava-dispatcher, installed at version: 2026.05\n"
           "start: 0 validate\n"
           "ok 1 selftests: riscv: vector\n"
           "ok 2 selftests: riscv: hwprobe # SKIP\n"
           "not ok 3 selftests: riscv: mm\n")
    outcome, body = body_for("kselftest-riscv", tap, 0, node_id="kselftest-tap")
    cb = report("kselftest TAP: rc=0 + not ok -> Complete, hierarchy fail", body, outcome)
    summary = judge.tap_summary(tap, "kselftest-riscv")
    check(summary.failed == 1, f"the judge read {summary.failed} failures out of one not-ok row")
    check(outcome.verdict == errors.VERDICT_FAIL,
          f"a failing selftest with rc=0 must be a test failure, got {outcome.verdict!r}")
    check(cb.get_job_status() == "pass",
          "a Completed job stays Complete: the failing case carries the verdict, "
          f"not the job status (got {cb.get_job_status()!r})")
    results = cb.get_results()
    print("get_results:", results)
    check(results.get("kselftest.riscv", {}).get("mm") == "fail", results)
    check(results.get("kselftest.riscv", {}).get("vector") == "pass", results)
    check(results.get("kselftest.riscv", {}).get("hwprobe") == "skip", results)

    node = {"id": "test", "name": "kselftest-riscv-pull-labs",
            "result": "pass", "data": {}, "artifacts": {}}
    hierarchy = cb.get_hierarchy(results, node)
    print("get_hierarchy job result:", hierarchy["node"]["result"],
          "| children:", [child["node"]["name"] for child in hierarchy["child_nodes"]])
    check(hierarchy["node"]["result"] == "fail",
          f"a failing TAP row must flip the job node to fail, got {hierarchy['node']['result']!r}")

    passing = ("2026-09-08T00:00:00 lava-dispatcher, installed at version: 2026.05\n"
               "ok 1 selftests: riscv: vector\n"
               "ok 2 selftests: riscv: hwprobe\n")
    _outcome_pass, body_pass = body_for("kselftest-riscv", passing, 0, node_id="kselftest-pass")
    cb_pass = Callback(body_pass)
    check(judge.tap_summary(passing, "kselftest-riscv").failed == 0, "the all-pass TAP read a failure")
    hierarchy_pass = cb_pass.get_hierarchy(cb_pass.get_results(), node)
    check(hierarchy_pass["node"]["result"] == "pass",
          f"an all-passing TAP must keep the node pass, got {hierarchy_pass['node']['result']!r}")
    print("all-pass TAP keeps the node pass: OK")


def case_no_tap():
    """Case 3: tuxrun failed before any test ran - never green."""
    console = ("2026-09-08T00:00:00 Resource not available: Connection refused\n"
               "2026-09-08T00:00:00 JobError: Your job cannot terminate cleanly.\n"
               "2026-09-08T00:00:00 {'definition': 'lava', 'case': 'job', "
               "'result': 'fail'}\n")
    check(judge.infra_reason(2, console, "kselftest-kvm") is not None,
          "a JobError must be read as 'no verdict', not as a test failure")
    outcome, body = body_for("kselftest-kvm", console, 2, node_id="no-tap")
    cb = report("no TAP + JobError -> incomplete/Infrastructure", body, outcome)
    summary = judge.tap_summary(console, "kselftest-kvm")
    check(summary.failed == 1, f"a console with no TAP must not read as passed: {summary}")
    check(cb.get_job_status() == "incomplete", cb.get_job_status())
    check(cb.is_infra_error(), "a JobError must map to Infrastructure")


def case_infra():
    """Case 4: tuxrun refusing the flags - incomplete + Infrastructure."""
    console = ("usage: tuxrun [options]\ntuxrun: error: argument --tests: "
               "invalid choice: 'kselftest-riscv'\n")
    outcome, body = body_for("kselftest-riscv", console, 2, node_id="infra")
    cb = report("tuxrun refuses the job (rc=2) -> incomplete/Infrastructure", body, outcome)
    check(cb.get_job_status() == "incomplete", cb.get_job_status())
    check(cb.is_infra_error() is True, "an infra verdict must set error_type=Infrastructure")


def main():
    case_boot("pass", "tuxrun-pass.log", 0, "pass")
    case_boot("fail", "tuxrun-fail.log", 1, "incomplete")
    case_kselftest()
    case_no_tap()
    case_infra()
    print(f"\nALL CALLBACK CHECKS PASSED ({CHECKS} checks; bodies in {BODY_DIR}/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
