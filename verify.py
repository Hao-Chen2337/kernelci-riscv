#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Every gate this tree has, in one command: what must be true before it is deployed.

    verify [--quick] [--base URL]

The old tree's gate *was* `./run.sh verify`, and it ran that tree: `validate_yaml`,
`compileall` over `scripts/`, `ruff`, and the guard suite that imports `kcilib`.
This is the same idea for the tree that is taking over - one command an operator
runs, whose exit status is the answer - and it is what replaces that gate the day
`scripts/` and `kcilib` are deleted (that is why this file exists).

    ruff                       style, imports, syntax
    i18n --check lib/gui       every string the page prints exists in both languages
                               (run as `python3 -m lib.i18n`, the package's own CLI)
    check_structure.py         the shape: one owner per decision, one exit path
    verify_callback_body.py    the LAVA body, read back by the REAL upstream parser
    test_dom.js                the page's script, run in node against a DOM stub
    test_notice.js             when a finish announces itself, driven the same way:
                               the one check that was never gated, and rotted
    test_config_cache.py       one request parses the workspace once
    test_form_body.py          a POST carries the form's own body
    test_ledger_history.py     a re-run keeps the record it replaced
    test_callback_override.py  where a report goes, and the one setting that moves it
    smoke_pages.py             every page renders, in both languages
    validate_yaml              the PR1 test profile still parses (the deliverable)
    accept.py --base URL       the page over HTTP, if a server is running (--base)

Each check is a command line, run in this repository, and **all of them run**: a
gate that stops at the first failure hides every check behind it, which is the wrong
trade for a command whose whole point is to be trusted.  The exit status is 3 when
any of them failed ("we never got what we came for"), 0 when they all passed.

`CHECKS` below is the list, and there are no others: a check outside that tuple is a
check that rots (see the two that did, in the comments there).

`--quick` leaves out the two slowest (the page renders and the HTTP sweep); that is
for the middle of a change, not for a verdict.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# **An activity's log is read while it runs.**  stdout redirected to a file is
# block-buffered, so `print()`s sat in a 4 KiB buffer: a `table.py pull` of fifty builds
# wrote a 0-byte `run.log` for minutes, and an activity killed mid-flight left an empty log
# behind - the page could not show progress it had been told nothing about.  Line
# buffering is what makes every printed line arrive when it happens.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from lib import errors

ROOT = os.path.dirname(os.path.abspath(__file__))
# The checks' own scripts, inside the tree: they were under `docs/gui-rework/tools/`
# while the rework was happening, and `docs/*` is gitignored - so a fresh clone had
# no gate at all (five checks FAILED, not skipped, because `python3` exists and the
# file does not).  They are published with the tree now; see docs/RUNBOOK.md.
TOOLS = os.path.join(ROOT, "tools", "gate")
PIPELINE = os.path.join(ROOT, "kernelci-pipeline")

# `(name, argv, cwd, needs)` - `needs` is a path that must exist for the check to
# run at all (an upstream clone that `./run.sh setup` creates, or a tool).
CHECKS = (
    ("ruff", ["ruff", "check", "."], ROOT, ""),
    ("i18n", [sys.executable, "-m", "lib.i18n", "--check", "lib/gui"], ROOT, ""),
    ("structure", [sys.executable, os.path.join(TOOLS, "check_structure.py")], ROOT, ""),
    ("callback body", [sys.executable, os.path.join(TOOLS, "verify_callback_body.py")],
     ROOT, os.path.join(ROOT, "kernelci-core")),
    ("dom", ["node", os.path.join(TOOLS, "test_dom.js")], ROOT, ""),
    # **The notice, and it is here because it was not.**  This is the same shape of
    # check as `dom` - the poll script driven in node against a DOM stub - and it
    # asserted `/\/log\?offset=0/` against a notice whose link has been
    # `/runs/<id>/log` since the log box was removed.  Nothing ran it, so nothing
    # noticed: a check outside this tuple is a check that rots (`CHECKS` is the list
    # of everything this tree gates on, and there are no others).
    ("notice", ["node", os.path.join(TOOLS, "test_notice.js")], ROOT, ""),
    ("config cache", [sys.executable, os.path.join(TOOLS, "test_config_cache.py")], ROOT, ""),
    # **The ledger's second file.**  A re-run of one pair used to destroy the record it
    # replaced, which made the re-run button (`btn.run_redo`) a button that erased its own
    # evidence.  `<test>.history.jsonl` is what it leaves instead, and every rule that
    # makes it safe is invisible from the outside: it is not a `.json` `_build_records`
    # would read back as one more record, a re-delivered run is not a second line, and the
    # record is written last so `deliver`'s `NOT recorded:` note is never untrue.  None of
    # that is visible in a render, so it is pinned here.
    ("ledger history", [sys.executable, os.path.join(TOOLS, "test_ledger_history.py")], ROOT, ""),
    ("form body", [sys.executable, os.path.join(TOOLS, "test_form_body.py")], ROOT, ""),
    # **Where a report goes.**  A job node's callback URL arrives inside the definition
    # the pipeline sent, so an operator running this deployment against their own
    # instance could read it on `/worker` and change nothing.  The override is one URL
    # under `var/state/`, and its two boundaries are what this pins: both delivery sites
    # resolve through it (`handle` and the re-post of a report that was refused), and a
    # one-shot `table.py run` still posts only when it is asked to.  Neither is visible
    # in a render.
    ("callback override", [sys.executable, os.path.join(TOOLS, "test_callback_override.py")],
     ROOT, ""),
    ("pages", [sys.executable, os.path.join(TOOLS, "smoke_pages.py"), "--all",
               "--lang", "both"], ROOT, ""),
    ("pipeline yaml", [sys.executable, "tests/validate_yaml.py"], PIPELINE, PIPELINE),
)

# The two that cost a minute or more: the page renders (it reads the API) and the
# HTTP sweep.  `--quick` leaves them out.
SLOW = ("pages",)


def run(name, argv, cwd, needs=""):
    """One check: `(ok, detail)`.  A missing precondition is reported, not skipped silently."""
    if needs and not os.path.exists(needs):
        return None, f"skipped: {needs} is not there (run deploy/setup.sh)"
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              timeout=1800, check=False)
    except FileNotFoundError as error:
        return False, f"cannot run {argv[0]}: {error}"
    except subprocess.TimeoutExpired:
        return False, f"{name} timed out after 30 minutes"
    if done.returncode == 0:
        return True, (done.stdout.strip().splitlines() or [""])[-1][:100]
    tail = (done.stdout + done.stderr).strip().splitlines()
    return False, " | ".join(line.strip() for line in tail[-3:])[:300]


def main(argv=None):
    """The command line: a bad flag is exit 3 with a message, never a traceback.

    The same shape every entry point of this tree keeps, and
    `tools/gate/check_structure.py` checks it - including for this file,
    which it failed the first time it ran (the check was written, then pointed at
    its own author).
    """
    try:
        return _main(argv)
    except errors.KciError as exc:
        print(f"X {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true",
                        help="leave out the slow checks (page renders)")
    parser.add_argument("--base", default="",
                        help="also sweep a running page over HTTP (accept.py --base URL)")
    args = parser.parse_args(argv)

    checks = [one for one in CHECKS if not (args.quick and one[0] in SLOW)]
    if args.base:
        checks.append(("accept", [sys.executable, os.path.join(TOOLS, "accept.py"),
                                  "--base", args.base], ROOT, ""))

    failed, skipped, passed = [], [], 0
    for name, command, cwd, needs in checks:
        ok, detail = run(name, command, cwd, needs)
        if ok is None:
            skipped.append(name)
            print(f"  --  {name:<14} {detail}")
        elif ok:
            passed += 1
            print(f"  ok  {name:<14} {detail}")
        else:
            failed.append(name)
            print(f"  X   {name:<14} {detail}")

    print(f"\n{passed} passed"
          + (f", {len(failed)} FAILED ({', '.join(failed)})" if failed else "")
          + (f", {len(skipped)} skipped ({', '.join(skipped)})" if skipped else ""))
    return errors.EXIT_INFRA if failed else errors.EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
