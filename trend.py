#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The regression trend: what these jobs did, oldest first, and where they turned red.

    trend [--job NAME]... [--api-url URL]

This reads the **production API's history**, not this machine's ledger: every
finished (`state=done`) node of a pull-lab job, in the order they happened, with
its commit, its result and its node id - then one line saying how many passed, how
many failed and how many regressions the run contains.

A regression is a pass -> fail **transition**, not a failure: consecutive failures
are one regression, and the detector re-arms only on a fresh pass, so a build that
stays bad for a week is reported once.  That rule is `lib/re.py: transitions()` -
the same function the `/analysis` page draws its wave from - so the command line
and the page cannot disagree about what a regression is.

`kind=job` is not decoration either: regression nodes copy the job's own
name/group/path, so without the filter they come back as runs of their own, with
commit `?`, counted in the pass/fail line and tracked again as if they were
history (`scripts/tools/regression_tracker.py` learned that the hard way).

Exit status: 0 whatever the trend says (a red trend is a *result*), 3 when the
API or the flags are impossible.
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

from lib import config, errors
from lib import re as re_mod
from lib.kjob import Kjobs
from lib.out import Outcome

# The three pull-lab job names this deployment's stack runs.  The kvm entry is the
# shared `kselftest-kvm-pull-labs` definition, not a riscv-specific one.
DEFAULT_JOBS = ("baseline-riscv-pull-labs", "kselftest-riscv-pull-labs",
                "kselftest-kvm-pull-labs")

# A node's `result` as the ledger's verdict vocabulary.  Only pass/fail can start
# or end a regression; anything else (skipped, incomplete, a result this tree has
# not heard of) is a run that produced no verdict, which is what VERDICT_INFRA is.
VERDICTS = {"pass": errors.VERDICT_PASS, "fail": errors.VERDICT_FAIL}


def commit_of(job):
    """The commit the job ran, out of the raw node: `data.kernel_revision.commit`."""
    revision = (job.node.get("data") or {}).get("kernel_revision") or {}
    return (revision.get("commit") or "?")[:12] if isinstance(revision, dict) else "?"


def as_records(jobs):
    """One job's finished nodes as ledger-shaped records, oldest first.

    `re.transitions()` is written for records (`verdict`, `timestamp`), so the
    history is handed to it in that shape instead of growing a second copy of the
    transition rule for API nodes.  The node id rides along as `build_id`, because
    a transition is printed with the run it happened on.
    """
    return re_mod.Records([
        Outcome(build_id=job.node_id, test=job.name,
                verdict=VERDICTS.get(job.result, errors.VERDICT_INFRA),
                timestamp=job.created, detail=job.result)
        for job in jobs])


def main(argv=None):
    try:
        return _main(argv)
    except errors.KciError as exc:
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job", action="append", default=[],
                        help="job node names to read (default: the three pull-lab jobs)")
    # `--api-url` and nothing else.  This entry reads the API's history and never
    # builds a `RunConfig`, so the run flags `config.run_flags()` used to hang here
    # (`--device`, `--timeout`, `--parameter`, `--rootfs`, ...) were decoration: the
    # parsed values were dropped on the floor, and a `--parameter bad` was accepted
    # with exit 0 while the same input to `table.py` is `X --parameter wants K=V,
    # got 'bad'` and exit 3.  A flag that reaches nothing is worse than an absent
    # one - the operator is told the command succeeded with a value nothing read -
    # so the flags are gone and argparse refuses them instead (exit 2).
    parser.add_argument("--api-url", default=None)
    args = parser.parse_args(argv)

    api = config.client(args)
    for name in args.job or DEFAULT_JOBS:
        runs = Kjobs(api).done(name)
        print(f"== {name} ==")
        if not runs:
            print("  (no finished runs)")
            continue
        for job in runs:
            print(f"  {job.created}  {commit_of(job):<12}  {job.result or '?':<10}  {job.node_id}")
        records = as_records(runs)
        passing = sum(1 for one in records if one.verdict == errors.VERDICT_PASS)
        failing = sum(1 for one in records if one.verdict == errors.VERDICT_FAIL)
        print(f"  -> {passing} pass / {failing} fail, "
              f"{len(re_mod.transitions(records))} regression(s)")
    return errors.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
