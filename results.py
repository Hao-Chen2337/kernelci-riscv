#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""What this machine ran: the ledger, read back.

    results [--build ID] [--test NAME] [--json] [--list]

Needs no API, no container and no stack, so it still answers "what did this
machine run" with everything stopped - which is the point of a durable record.
Exit status is 0 even when there is nothing to show; an empty ledger is an
answer, not a failure.
"""

import argparse
import json
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

from lib import errors, layout
from lib import re as re_mod


def main(argv=None):
    """The command line: a bad flag or a corrupt record is exit 3 with a message, never a traceback.

    `Ledger.read()` raises on a record it cannot parse, on purpose ("a ledger that
    quietly loses rows is worse than none") - and this is where that becomes an exit
    status instead of a traceback with exit 1.  Every entry point in this tree keeps
    the same shape, and `docs/gui-rework/tools/check_structure.py` checks it.
    """
    try:
        return _main(argv)
    except errors.KciError as exc:
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", default="")
    parser.add_argument("--test", default="")
    parser.add_argument("--list", action="store_true", help="the build ids the ledger has")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        builds = re_mod.Records.builds()
        if args.json:
            print(json.dumps(builds, indent=1))
        else:
            for build_id in builds:
                print(build_id)
        return errors.EXIT_PASS

    records = re_mod.Records.load(args.build or None)
    if args.test:
        records = records.for_test(args.test)
    if args.json:
        print(re_mod.json_report(records))
        return errors.EXIT_PASS
    lines = _nothing_matched(args) if not len(records) else None
    if lines:
        for line in lines:
            print(line)
    else:
        re_mod.render(records)
    return errors.EXIT_PASS


def _nothing_matched(args):
    """The sentence for an empty answer out of a ledger that is not empty.

    `lib/re.render()` answers `no result records in <dir>` for an empty `Records`
    however it came to be empty, and the two ways are not the same fact: a ledger
    with nothing in it at all, and a filter that matched none of the records the
    ledger holds.  `results.py --build deadbeef1234` over 23 builds and 61 records
    printed the empty-ledger paragraph - "an empty ledger means nothing has run
    here yet" - to a reader who was looking for a typo in a build id, which is the
    one thing that answer says cannot be it.  A filter that matched nothing is now
    answered with the filter's own name and the size of the ledger, so the reader
    knows the records are there and the *argument* is what to look at.

    Only this case reads the ledger a second time, and only when a filter was
    given at all: the ordinary path (records found) does no extra work, and a
    ledger that really is empty still gets `re.render()`'s own words verbatim.
    """
    named = [f"{flag} {value}" for flag, value in (("build", args.build),
                                                   ("test", args.test)) if value]
    if not named:
        return None
    known = re_mod.Records.load()
    if not known:
        return None
    # The build count comes out of the records themselves rather than a second
    # listing: `Ledger.write()` builds the path out of the record's own
    # `build_id`, so the field and the directory that holds it cannot disagree.
    return [f"no records for {' and '.join(named)} in {layout.results()}",
            (f"  (the ledger is not empty: {len(known)} record(s) over "
             f"{len({one.build_id for one in known})} build(s); "
             "this filter matched none of them)")]


if __name__ == "__main__":
    sys.exit(main())
