#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kernel config drift between two builds of one job.

    drift [--job NAME] [--older ID] [--newer ID] [--older-config PATH] [--newer-config PATH]

Exit status is the answer: 0 no drift, 1 drift.  Without `--older/--newer` the
two newest passing builds of the job are used, which is the comparison that
matters after a toolchain bump.
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

from lib import config, drift, errors

JOB = "kbuild-gcc-14-riscv"


def main(argv=None):
    try:
        return _main(argv)
    except errors.KciError as exc:
        # The house convention every other entry point here keeps: a bad flag, a
        # dead API or a build that cannot be resolved is exit 3 with one line, not
        # a traceback with exit 1.  `./run.sh drift` runs with the stack down by
        # default (`KCI_API_URL` unset means 127.0.0.1:8001), and the old tool it
        # replaces answered that case with a message - a traceback here would be a
        # regression in how the command fails, not just in what it prints.
        print(f"X {exc}", file=sys.stderr)
        # The error's OWN code, not a fixed 3: this tree's vocabulary gives each
        # failure its exit status (`errors.py`), and hardcoding one here is how an
        # entry point starts disagreeing with it.  Found by
        # `docs/gui-rework/tools/check_structure.py`, which checks all of them.
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job", default=JOB)
    parser.add_argument("--older", default="")
    parser.add_argument("--newer", default="")
    parser.add_argument("--older-config", default="")
    parser.add_argument("--newer-config", default="")
    parser.add_argument("--max-lines", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--api-url", default=None)
    args = parser.parse_args(argv)

    # **Half a pair of files is not "no files".**  This was `if both ... else`,
    # so one `--*-config` fell through to the API path and the answer was about
    # the network, never about the flag that was left out: `--older-config F`
    # alone said "need two builds to compare; this job has 0 finished and
    # passing" (or a connection error), while the operator had asked for a local
    # comparison.  Two files or none; the middle case names the flag it wants.
    if args.older_config and args.newer_config:
        report = drift.Drift.from_files(args.older_config, args.newer_config)
    elif args.older_config or args.newer_config:
        given = "--older-config" if args.older_config else "--newer-config"
        missing = "--newer-config" if args.older_config else "--older-config"
        raise errors.ConfigError(
            f"{given} without {missing}: a local comparison needs two files - give "
            "both config paths, or neither to compare two builds")
    else:
        report = drift.Drift.between(config.client(args), args.job,
                                     args.older or None, args.newer or None)

    if args.json:
        print(report.json())
    else:
        report.print(max_lines=args.max_lines)
    # `drifted()` is a METHOD (`lib/drift.py` compares the three lists), and this
    # line read it as an attribute: a bound method is always truthy, so `drift.py`
    # exited 1 even when the two configs held exactly the same options.  The one
    # thing this entry point promises is that exit status ("0 no drift, 1 drift"),
    # and the old `./run.sh drift` tool answers 0 for the same pair of builds;
    # nothing parses the JSON shape, so nothing else could notice.
    return errors.EXIT_TEST_FAIL if report.drifted() else errors.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
