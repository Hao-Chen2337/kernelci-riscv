#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Retention for the fetched builds: keep the newest, plus the one served.

    prune [--keep N] [--dry-run] [--downloads DIR]

Every build under `var/downloads/` is one `fetch` or one worker job's bytes, and
a daily loop of them is gigabytes a year, so the directory is bounded.  What is
kept, and why each row was kept, is printed before anything is deleted - and
`--dry-run` prints exactly the same table and deletes nothing, because the
decision (`lib/retention.py: plan()`) is one pass that both faces share.

The build `var/serve/Image` serves is never removed whatever its age: it is the
kernel the local stack seeds its jobs from, and the record that names it
(`var/state/served.json`) is written by the same command that publishes it.

Exit status: 0 whether or not anything was removed (an empty directory is not a
failure), 3 when the flags or the workspace are impossible.
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

from lib import errors, layout, retention


def main(argv=None):
    try:
        return _main(argv)
    except errors.KciError as exc:
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=int, default=retention.DEFAULT_KEEP,
                        help=f"newest builds to keep (default {retention.DEFAULT_KEEP})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the decision, delete nothing")
    parser.add_argument("--downloads", default="",
                        help=f"the directory to prune (default {layout.downloads()})")
    args = parser.parse_args(argv)

    # A cap below one deletes the build the stack serves and the one just fetched;
    # the old tree's `./run.sh prune` refused it with the same sentence.
    if args.keep < 1:
        raise errors.ConfigError(
            "--keep must be at least 1 - the newest build is the one the local "
            "stack serves")
    retention.prune(args.downloads or layout.downloads(), keep=args.keep, dry=args.dry_run)
    return errors.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
