#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pin the kernel this deployment serves, and record which build it is.

    provision [--tree TREE] [--branch BRANCH]

The newest production build of the tree that **finished and passed** is chosen
(the window widens 3 -> 7 -> 30 -> 180 days), its kernel is fetched through the
same `make()` every other fetch uses, and `var/serve/Image` is published as a
symlink to it - the local stack's seed hands that image to the jobs it creates.

What this deployment serves is then a *record*, not a convention:
`var/state/served.json` names the build, its revision (commit, describe, tree,
branch), the artifact URLs (kernel, modules, kselftest, config) and the guest
rootfs.  Retention reads it so it never deletes the served build; the stack's
seed reads it so the nodes it creates name the same kbuild the kernel came from
(`modprobe` matches /lib/modules by kernel release, so a kernel and a module tree
from two different builds make every KVM test skip).

The kernel and the modules are never mixed: both are read off the one card the
API answered with.

A kernel this machine built or hand-placed is a different act - publish it with
`run_latest.py --provision-only`, which takes the image already at
`var/serve/Image` and records it the same way.

Exit status: 0 published, 3 no build to publish or the API/network could not
answer.
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

from lib import api, build, config, errors


def main(argv=None):
    try:
        return _main(argv)
    except errors.KciError as exc:
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tree", default="riscv",
                        help="which tree's builds to choose from (default: riscv)")
    parser.add_argument("--branch", default=None)
    # `--api-url` and nothing else.  Provisioning has no job to run: it reads the
    # API, fetches a kernel and publishes a symlink, and never builds a `RunConfig`
    # - so the run flags `config.run_flags()` used to hang here (`--device`,
    # `--timeout`, `--parameter`, `--rootfs`, ...) were decoration, and a bad value
    # among them (`--parameter bad`) was accepted with exit 0 while `table.py` says
    # `X --parameter wants K=V, got 'bad'` and exits 3.  They are gone; argparse
    # refuses them now (exit 2).  A flag that reaches nothing is worse than an
    # absent one.
    parser.add_argument("--api-url", default=None)
    # This line reads PRODUCTION unless told otherwise, exactly as `run_latest.py`
    # does: provisioning is the "serve the newest production build here" act, while
    # the worker and the table are about this deployment's own API.  Leaving it to
    # `config.client()` meant 127.0.0.1:8001 - the local stack, i.e. the thing this
    # command is preparing - which failed with "connection refused" the moment
    # `./run.sh provision` stopped calling an entry that defaulted to production.
    parser.set_defaults(api_url=os.environ.get("KCI_API_URL") or api.PRODUCTION)
    args = parser.parse_args(argv)

    card = build.provision(config.client(args), args.tree, args.branch)
    print(f"published {card.build_id}: {(card.revision or {}).get('describe', '?')} "
          f"({(card.revision or {}).get('commit', '')[:12]})")
    print(f"  serving  var/serve/Image -> {card.build_id}")
    print(f"  recorded var/state/served.json ({card.artifact('modules') or 'no modules URL'})")
    return errors.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
