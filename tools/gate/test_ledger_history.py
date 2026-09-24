#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The ledger's history file: what a re-run adds, and what it must not.

    test_ledger_history.py

`Ledger.write` puts **two** files on disk for one run: `<test>.json`, the pair's
current answer, which every run rewrites exactly as it always did, and
`<test>.history.jsonl`, which every run appends to.  The second file is what makes
the re-run button (`btn.run_redo`) worth pressing at all - without it a second run
of one pair destroys the first run's verdict, and the only surviving evidence that
the first ever happened is its console under `var/logs/`, which the page can read
but the ledger cannot.

A file that grows on every write is a file that can be written wrongly, and these
are the ways, each of which this test pins down:

* **the current record is not disturbed.**  `<test>.json` is the newest run and
  nothing here may change what it says - the history is an addition, not a
  replacement, and the day it became one every reader of `Ledger.read` would be
  reading a list where it expects a record;
* **a re-run of the same run is not a second line.**  `deliver` is called by a
  callback that may be retried, and `_same_run` is the idempotence rule - the same
  join the page's own history panel uses (`builds._ledger_run`), so a record that
  arrives twice cannot show up as two runs on either reader;
* **the history is oldest-first.**  The page lists runs newest-first and reverses
  this, and a file whose order depended on how it was written would make that a
  guess;
* **a line that cannot be parsed is an error and not a skip.**  A reader that
  dropped what it could not read would answer "what has this pair done" with a
  shorter list and no way for the answer to say it was shorter - the rule
  `_record_at` already follows for the record itself;
* **the record goes last**, so `deliver`'s `NOT recorded: …` note is true of the
  record it is talking about whenever it is printed.

No network and no disk outside a temporary `KCI_WORK_DIR`.

Exit status is the verdict, like `python3 lib/i18n.py --check lib/gui.py`.
"""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from lib import layout
from lib.errors import LedgerError
from lib.sink import HISTORY_SUFFIX, Ledger, Outcome

BUILD = "6aade015d96a8203de6dff37"
TEST = "kselftest-riscv"
OTHER = "boot"


def record(at: str, verdict: str = "pass", test: str = TEST, log: str = "") -> Outcome:
    """One run of one pair, as `judge` would hand it over: a stamp, a verdict, a console."""
    return Outcome(build_id=BUILD, test=test, verdict=verdict, timestamp=at, log=log)


def lines(path: str) -> list[dict]:
    """The history file as parsed objects, in file order."""
    with open(path, encoding="utf-8") as handle:
        return [json.loads(one) for one in handle if one.strip()]


def main() -> int:
    home = tempfile.mkdtemp(prefix="kci-ledger-history-")
    os.environ["KCI_WORK_DIR"] = home
    failed, checks = 0, 0

    def check(name, ok, evidence=""):
        nonlocal failed, checks
        checks += 1
        if not ok:
            failed += 1
        print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({evidence})" if evidence else ""))

    try:
        current = layout.results(BUILD, TEST)
        history = layout.results_history(BUILD, TEST)

        # 1. the file is a sidecar of the record and not a second record: `_build_records`
        #    walks a build's directory for `*.json`, so a history named `.json` would be
        #    read back as one more record of the pair.
        check("the history is not a `.json` `_build_records` would pick up",
              history.endswith(HISTORY_SUFFIX) and not history.endswith(".json"),
              os.path.basename(history))
        check("the record keeps its old path", current.endswith(f"{TEST}.json"),
              os.path.basename(current))

        # 2. three runs of one pair: three history lines, and the record is the newest.
        for at, verdict in (("2026-09-01T10:00:00Z", "pass"),
                            ("2026-09-01T11:00:00Z", "fail"),
                            ("2026-09-01T12:00:00Z", "pass")):
            Ledger.write(record(at, verdict))
        wrote = lines(history)
        check("every run is a line, oldest first",
              [one["timestamp"] for one in wrote] ==
              ["2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z", "2026-09-01T12:00:00Z"],
              str([one["timestamp"] for one in wrote]))
        check("the record is still the newest run and reads as one record",
              [one.verdict for one in Ledger.read(BUILD) if one.test == TEST] == ["pass"],
              str([one.verdict for one in Ledger.read(BUILD) if one.test == TEST]))
        check("and the history reads as all three, oldest first",
              [one.verdict for one in Ledger.history(BUILD, TEST)] ==
              ["pass", "fail", "pass"],
              str([one.verdict for one in Ledger.history(BUILD, TEST)]))

        # 3. the same run delivered twice is one run.  `deliver` is called from a callback
        #    that may be retried, and two lines for one run would put a phantom second run
        #    in every count the page draws off this file.
        Ledger.write(record("2026-09-01T12:00:00Z", "pass"))
        check("a re-delivered run adds no line", len(lines(history)) == 3,
              f"{len(lines(history))} lines")

        # 4. and the join is the **console's basename** where both sides have one, which is
        #    the join the page's own run-history panel makes (`builds._ledger_run`): the
        #    same console re-recorded at a later stamp is one run, not two.  A stamp-only
        #    rule would list one console twice.
        console = "/var/logs/6aade015.kselftest-riscv.20260901.log"
        Ledger.write(record("2026-09-01T11:30:00Z", "fail", log=console))
        before = len(lines(history))
        Ledger.write(record("2026-09-01T11:45:00Z", "fail", log=console))
        check("the same console at a later stamp is still one run",
              len(lines(history)) == before, f"{before} then {len(lines(history))} lines")

        # 5. a second test of the same build has its own file, and `boot`'s runs do not
        #    land in `kselftest-riscv`'s.  Measured as "one more line in boot's file and
        #    none in this one", so the case does not depend on what the cases above left.
        kselftest_lines = len(lines(history))
        Ledger.write(record("2026-09-01T13:00:00Z", "fail", test=OTHER))
        check("another test writes its own history",
              len(lines(layout.results_history(BUILD, OTHER))) == 1 and
              len(lines(history)) == kselftest_lines,
              os.path.basename(layout.results_history(BUILD, OTHER)))
        check("and the two histories do not share a file",
              layout.results_history(BUILD, TEST) != layout.results_history(BUILD, OTHER))

        # 6. a line this reader cannot parse raises, naming the file and the line.  The
        #    alternative - skipping it - answers "what has this pair done" with a shorter
        #    list and nothing on screen to say so.  The line number is read off the file
        #    rather than assumed: it is the count of everything above plus the bad one.
        with open(history, encoding="utf-8") as handle:
            wanted = len(handle.readlines()) + 1
        with open(history, "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        try:
            Ledger.history(BUILD, TEST)
        except LedgerError as error:
            said = str(error)
            bad = os.path.basename(history) in said and f"line {wanted}" in said
        else:
            said, bad = "no error", False
        check("an unreadable line raises, naming the file and the line", bad, said)
        with open(history, encoding="utf-8") as handle:
            kept = handle.readlines()
        with open(history, "w", encoding="utf-8") as handle:
            handle.writelines(kept[:-1])

        # 7. a pair that never ran has no file and answers `[]` rather than raising:
        #    "no history" is a fact about a pair, not a failure to read one.
        check("a pair with no history answers an empty list",
              Ledger.history(BUILD, "never-run") == [],
              str(Ledger.history(BUILD, "never-run")))

        # 8. **the history is written first, and this is why**: `deliver`'s note is a
        #    statement about the *record* ("recorded in <path>" / "NOT recorded: <why>"),
        #    so a run whose history could not be written must leave no record behind -
        #    otherwise the note would be true of the file it names and false of the
        #    ledger, which is the one thing a reader cannot check from the console.  The
        #    failure is made by putting a directory where the history file goes: the
        #    record's own path stays writable, so only the order can save it.
        blocked = layout.results_history(BUILD, "blocked")
        os.makedirs(blocked, exist_ok=True)

        class Job:
            """What `deliver` reads off a job: the two names it fills an empty record with."""

            build_id, test = BUILD, "blocked"

        said = Ledger().deliver(Job(), record("2026-09-01T14:00:00Z", "pass",
                                              test="blocked"))
        check("a run whose history could not be written says NOT recorded",
              said.startswith("NOT recorded:"), said)
        check("and it left no record behind either",
              not os.path.exists(layout.results(BUILD, "blocked")),
              layout.results(BUILD, "blocked"))
    finally:
        shutil.rmtree(home, ignore_errors=True)
        os.environ.pop("KCI_WORK_DIR", None)

    print(f"\n{checks - failed}/{checks} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
