#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""What the pipeline did with this lab's jobs: the newest node of each name.

    report [--name NAME]... [--limit N] [--api-url URL]

The view an operator wants when a job does not come back: for each of this
deployment's three pull-lab job names, the newest job nodes with their state, their
result, their creation time and their **full** node id.

Two things this entry is careful about, both learned from the shell version it
replaces (`./run.sh report`, a `curl` piped into a heredoc):

* **the newest nodes, not the oldest.**  The API hands nodes out oldest first and
  has no sort parameter, so a small page is the *head* of a long history - the
  read has to ask for the tail (`api.nodes(newest=True)`, the client's default:
  when the cap is smaller than the API's `total` it starts at `total - limit`).
* **the whole id.**  A `[:16]` truncation made two nodes of one name print
  identically, which is exactly the case a report exists to tell apart.

It is a read of *this deployment's* API (the local stack by default, `--api-url`
for production), and it never writes: `state=available` nodes waiting in the queue
and `done` nodes that ran are the same kind, so both are shown as they are.

Exit status: 0 with any answer, 3 when the API cannot be reached.
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

# The three pull-lab job names this deployment's stack runs; `--name` may be
# repeated to ask about others (a deployment can run a second lab's names).
DEFAULT_NAMES = ("baseline-riscv-pull-labs", "kselftest-riscv-pull-labs",
                 "kselftest-kvm-pull-labs")


def main(argv=None):
    try:
        return _main(argv)
    except errors.KciError as exc:
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", action="append", default=[],
                        help="job node name (repeatable; default: the three pull-lab jobs)")
    parser.add_argument("--limit", type=int, default=3,
                        help="how many nodes per name to show (default 3)")
    # `--api-url` and nothing else.  This entry reads the API and never builds a
    # `RunConfig`, so the run flags `config.run_flags()` used to hang here
    # (`--device`, `--timeout`, `--parameter`, `--rootfs`, ...) were decoration: the
    # parsed values were dropped on the floor, and a `--parameter bad` was accepted
    # with exit 0 while the same input to `table.py` is `X --parameter wants K=V,
    # got 'bad'` and exit 3.  A flag that reaches nothing is worse than an absent
    # one - the operator is told the command succeeded with a value nothing read -
    # so the flags are gone and argparse refuses them instead (exit 2).
    parser.add_argument("--api-url", default=None)
    args = parser.parse_args(argv)
    if args.limit < 1:
        raise errors.ConfigError(f"--limit must be at least 1, got {args.limit}")

    api = config.client(args)
    for name in args.name or DEFAULT_NAMES:
        # `kind="job"`: regression nodes copy the job's own name/group/path, and
        # without the filter they answer as runs of their own with no result.
        nodes = api.nodes(kind="job", filters={"name": name}, limit=args.limit)
        print(f"--- {name} (newest {args.limit}) ---")
        if not nodes:
            print("  (no nodes)")
            continue
        for node in sorted(nodes, key=lambda one: one.get("created") or "", reverse=True):
            print(f"  {node.get('created') or '?':<28} {(node.get('state') or '?'):<10} "
                  f"{(node.get('result') or '-'):<6} {node.get('id')}")
    return errors.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
