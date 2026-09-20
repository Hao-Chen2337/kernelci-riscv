#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The resident pull-lab worker: take jobs from the events API, run them, report back.

Draft this file is built from (``pull_worker``)::

    int main(){
        poller()
    }

That is still the whole entry point, because everything else lives in
`lib/poller.py`: the cursor, the seen set, the unposted reports, the flock, the
claim check and the batch rules.  A job is executed by `job.Job.run()`, which
is the same executor the one-shot line and the offline table use.

The result is posted as a LAVA-compatible callback body - the only shape the
pipeline's callback endpoint ingests.
"""

import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# **An activity's log is read while it runs.**  stdout redirected to a file is
# block-buffered, so `print()`s sat in a 4 KiB buffer: a `table.py pull` of fifty builds
# wrote a 0-byte `run.log` for minutes, and an activity killed mid-flight left an empty log
# behind - the page could not show progress it had been told nothing about.  Line
# buffering is what makes every printed line arrive when it happens.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from lib import config, errors, poller


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
    run, poll, args = config.parse_poll(argv)
    # The claim filters come from the poll config; what tuxrun runs in comes from
    # the run config, built here from the same command line.
    run = replace(run or config.RunConfig(), container_runtime=poll.container_runtime)
    # `args`, not `poll.api_url`: `client()` reads `--api-url` off a parsed command
    # line and refuses a URL string (its guard is load-bearing - see lib/config.py).
    api = config.client(args)
    worker = poller.Poller(api, run=run, runtime=poll.runtime, platform=poll.platform,
                           state_file=poll.state_file, period=poll.period,
                           max_retries=poll.max_retries, since=poll.since)
    if poll.once:
        return worker.once()
    worker.loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
