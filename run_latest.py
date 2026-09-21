#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Re-run the newest production riscv build here, once.

Draft this file is built from (``run_latest``)::

    kb = kbuild(API = ORG)
    kbuild.new (tree = main next riscv )
    b = build (kb)
    j = job(b)
    outcome = j.runjob

The whole one-shot line, in five lines: ask the API for the newest usable
build, make it local, pick the tests, run them, exit with the verdict.

    exit status: 0 pass, 1 test failure, 3 infrastructure error

No artifact server, no seam swapping, no second ledger write: the artifacts are
made local and tuxrun is pointed at them (the one thing to prove first is that
`file://` URLs work for the kernel and the kselftest tarball too - today only
the baked rootfs uses one, and the rest go through a local HTTP server whose
port must be probed, owned and proven).
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

from lib import api as api_mod
from lib import build as build_mod
from lib import config, errors, kbuild
from lib import job as job_mod

TREE = "riscv"
BRANCH = None

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tree", default=TREE)
    parser.add_argument("--branch", default=BRANCH)
    parser.add_argument("--test", action="append", choices=sorted(job_mod.TESTS))
    parser.add_argument("--kvm", action="store_true", help="the curated kselftest-kvm subset")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--provision-only", action="store_true",
                        help="publish this deployment's own kernel and record it, run nothing")
    config.run_flags(parser)
    # This line reads PRODUCTION unless told otherwise: it is the "re-run the
    # newest production build here" command, while the worker and the table are
    # about this deployment.
    parser.set_defaults(api_url=os.environ.get("KCI_API_URL") or api_mod.PRODUCTION)
    args = parser.parse_args(argv)

    try:
        # `run_from` belongs inside the `try` with everything else that can refuse
        # this command line: `--parameter bad` is a `ConfigError`, and raised from
        # out here it escaped as a traceback and exit 1 - which this project reads
        # as "the tests failed".  The refusal is infrastructure (3), like `table.py`.
        run = config.run_from(args)
        return _run(args, run)
    except errors.KciError as exc:
        # An infrastructure failure is exit 3, not a traceback: the exit status
        # IS the verdict, and "we never got one" has to be distinguishable from
        # "the tests failed".
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _run(args, run):
    if args.provision_only:
        return build_mod.publish_local(run)

    api = config.client(args)
    newest = kbuild.Kbuilds(api).getnew(args.tree, args.branch)
    print(f"build: {newest.build_id}  {newest.describe()}")

    made = build_mod.Build(newest).make()
    # `fetch` pulled bytes and a pull record; the card is this line's job, because
    # `make()` never touches the table - without it the build this command just
    # pulled renders on the builds page as "no card in the local table".
    build_mod.Builds.load().remember(made)
    tests = tuple(args.test or ()) or (("kselftest-kvm",) if args.kvm else job_mod.DEFAULT_TESTS)
    outcomes = job_mod.Jobs.for_build(made, tests=tests).run(
        run, sinks=run.sinks(), source="fetch")

    for outcome in outcomes:
        outcome.print()
    return outcomes[-1].exit_code if outcomes else errors.EXIT_INFRA


if __name__ == "__main__":
    sys.exit(main())
