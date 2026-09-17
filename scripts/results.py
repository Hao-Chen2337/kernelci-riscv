#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""What the local pull lab has recorded, read back from the result ledger.

`./run.sh fetch` and the resident worker both file a record under
`work/results/<build-id>/<test>.json` (kcilib.core.ledger owns the layout).  Until
this script existed nothing ever READ those records: the ledger was write-only,
so "what has this lab actually tested, and how did it end" could only be
answered by walking the directory by hand - which is how a record that never
gets read drifts into a record that is written wrongly.

    ./run.sh results                 # every build, newest record first
    ./run.sh results --build <id>    # one build
    ./run.sh results --json          # the records themselves

Exit status is 0 whenever the ledger could be read, including when it is empty
("nothing recorded yet" is an answer, and a report that exits non-zero for it
would break any loop that calls it).  A record that cannot be parsed is NOT
swallowed: kcilib.core.ledger.read_results raises, and a ledger that quietly loses
rows is worse than no ledger.
"""

import argparse
import json
import os
import sys

# kcilib sits next to this file; resolved through the file's own directory so
# the report runs from any CWD.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from kcilib.core import ledger

# One line per record has to stay readable in a terminal; the detail column is
# where a long infra message would otherwise push the verdict off screen.
DETAIL_WIDTH = 60


def _short(text, width=DETAIL_WIDTH):
    """*text* on one line and no longer than *width*, with an ellipsis."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= width:
        return flat
    return flat[: width - 1] + "\u2026"


def _builds(requested):
    """The build ids to report on: the one asked for, or every recorded one."""
    if requested:
        return [requested]
    return ledger.list_builds()


def render_text(builds):
    """The human report: a header per build, one line per recorded test."""
    if not builds:
        return [
            f"no result records in {ledger.results_dir()}",
            ("  (./run.sh fetch and ./run.sh worker write them; an empty "
             "ledger means nothing has run here yet)"),
        ]
    lines = []
    for build in builds:
        records = ledger.read_results(build)
        if not records:
            lines.append(f"--- {build}: no records")
            continue
        passing = sum(1 for record in records.values()
                      if record.get("verdict") == "pass")
        lines.append(f"--- {build} ({len(records)} record(s), {passing} pass)")
        # Newest record of this build first: the reader is usually asking about
        # the run that just happened.
        for test, record in sorted(
            records.items(),
            key=lambda item: item[1].get("timestamp") or "",
            reverse=True,
        ):
            exit_code = record.get("exit_code")
            # The writer is shown because two of them share this layout now
            # ("fetch" re-runs one production build, "worker" takes dispatched
            # jobs); a row that does not say which one produced it cannot be
            # compared with the API's view of the same run.
            lines.append(
                f"  {test:<24} {record.get('verdict') or '-':<6} "
                f"exit={exit_code if exit_code is not None else '-':<3} "
                f"{record.get('source') or '-':<7} "
                f"{record.get('timestamp') or '-':<21} "
                f"{_short(record.get('detail'))}"
            )
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="results.py",
        description="Read the local result ledger "
                    "(work/results/<build-id>/<test>.json).",
    )
    parser.add_argument("--build", default=None, metavar="ID",
                        help="only this build id (default: every recorded one)")
    parser.add_argument("--json", action="store_true",
                        help="the records themselves, as one JSON object")
    parser.add_argument("--list", action="store_true",
                        help="print the recorded build ids, one per line")
    args = parser.parse_args(argv)

    builds = _builds(args.build)

    if args.list:
        for build in builds:
            print(build)
        return 0

    if args.json:
        payload = {build: ledger.read_results(build) for build in builds}
        json.dump(payload, sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if not os.path.isdir(ledger.results_dir()):
        # Named explicitly: "no records" and "the ledger is somewhere else"
        # look identical otherwise, and the root is overridable
        # (KCI_RESULTS_DIR).
        print(f"ledger root {ledger.results_dir()} does not exist")
        return 0
    for line in render_text(builds):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
