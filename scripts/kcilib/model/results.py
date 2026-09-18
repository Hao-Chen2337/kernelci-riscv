# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The local result ledger, read through the module that owns its layout.

work/results/<build-id>/<test>.json is kcilib.core.ledger's record; the human
report over it is scripts/results.py's (`./run.sh results`).  This class reads
both the way their owners do - the ledger module for the records, the report
script for the text - so no record layout and no line format is spelled twice.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from kcilib import repo_root
from kcilib.core import ledger as _ledger


class Record:
    """One ledger record, read-only: the fields kcilib.core.ledger promises.

    ``Results.rows()`` hands these out rather than the raw JSON document,
    because that document's key set is the ledger's contract
    (``ledger.RESULT_FIELDS``): a field read through a typed property cannot
    silently depend on a key the writer may drop, and a value stored with the
    wrong JSON type reads as None - the same answer as "not recorded".  The
    whole document stays available through as_dict() for a caller that needs
    every key the writer filed.
    """

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values: dict[str, object] = dict(values)

    # ---- the identity of the run -----------------------------------------

    @property
    def build_id(self) -> str | None:
        """The build this run belongs to (the record's own directory)."""
        return self._text("build_id")

    @property
    def test(self) -> str | None:
        """The test name; the record's file name wins over a missing field."""
        return self._text("test")

    @property
    def job(self) -> str | None:
        """The job definition's name, as the run layer knew it."""
        return self._text("job")

    @property
    def source(self) -> str | None:
        """Who filed the record: "fetch", "worker" or "table"."""
        return self._text("source")

    # ---- what happened ---------------------------------------------------

    @property
    def verdict(self) -> str | None:
        """pass / fail / error, as kcilib.run.judge named it."""
        return self._text("verdict")

    @property
    def exit_code(self) -> int | None:
        """tuxrun's exit status; None when the run never produced one."""
        value = self._values.get("exit_code")
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    @property
    def detail(self) -> object:
        """The failure detail the writer kept (a message, or nothing)."""
        return self._values.get("detail")

    @property
    def timestamp(self) -> str | None:
        """When the record was written, as the ledger's own "Z" format."""
        return self._text("timestamp")

    @property
    def log(self) -> str | None:
        """The archived console log's path, when one was kept."""
        return self._text("log")

    @property
    def artifacts_dir(self) -> str | None:
        """The per-job workspace the run used."""
        return self._text("artifacts_dir")

    @property
    def build_created(self) -> str | None:
        """When the build itself was created, as its node reported."""
        return self._text("build_created")

    @property
    def revision(self) -> object:
        """The kernel revision document the record carries."""
        return self._values.get("revision")

    @property
    def results(self) -> object:
        """The per-test results the callback body carried."""
        return self._values.get("results")

    # ---- reads -----------------------------------------------------------

    def is_pass(self) -> bool:
        """True for the one verdict that means the test itself passed."""
        return self.verdict == "pass"

    def as_dict(self) -> dict[str, object]:
        """The record exactly as the ledger stored it (a copy)."""
        return dict(self._values)

    def _text(self, name: str) -> str | None:
        """*name*'s value when it is a string, else None."""
        value = self._values.get(name)
        return value if isinstance(value, str) else None


class Results:
    """What this machine has recorded: the local result ledger, read only.

    Its records, their order and their file names are kcilib.core.ledger's; the
    text() report is scripts/results.py's.  Both work with the stack down and
    without the API, which is the point of the ledger.
    """

    def __init__(self, results_dir: Path | None = None) -> None:
        """*results_dir* moves the ledger root for this object only.

        None (the default) is the deployment's own root: work/results, or
        $KCI_RESULTS_DIR.
        """
        self.root: Path = Path(repo_root())
        self.results_dir: Path | None = (
            Path(results_dir) if results_dir is not None else None
        )

    # ---- the records -----------------------------------------------------

    def builds(self) -> list[str]:
        """Every build id the ledger holds a record for, newest first."""
        with self._at(self.results_dir):
            return _ledger.list_builds()

    def rows(self, build_id: str) -> list[Record]:
        """One build's records, one Record each, ordered by test name.

        A build nothing was recorded for is an empty list; an unreadable record
        raises, exactly as kcilib.core.ledger.read_results does - a ledger that
        quietly loses rows is worse than no ledger.
        """
        with self._at(self.results_dir):
            records = _ledger.read_results(build_id)
        return [
            # The file name is authoritative when a body omits its own test.
            Record(dict(record, test=record.get("test") or test))
            for test, record in sorted(records.items())
        ]

    def latest(self, n: int = 3) -> list[Record]:
        """The *n* newest records across every build, newest first.

        "Newest" is the record's own timestamp - the field
        kcilib.core.ledger.list_builds orders builds by - so the word cannot
        mean two things in one call chain.
        """
        records = [record for build in self.builds()
                   for record in self.rows(build)]
        records.sort(key=lambda record: record.timestamp or "", reverse=True)
        return records[:n]

    # ---- the report ------------------------------------------------------

    def _argv(self, *args: str) -> list[str]:
        """`./run.sh` with *args*: the report is a command, not a re-render."""
        return [str(self.root / "run.sh"), *args]

    def text(self) -> str:
        """`./run.sh results`' output, verbatim - this layer renders nothing.

        scripts/results.py owns that report.  Running it is what keeps a
        caller's view and the operator's identical, down to the "no result
        records in ..." wording; a ledger that cannot be read raises here
        rather than coming back as an empty-looking report.
        """
        env = dict(os.environ)
        if self.results_dir is not None:
            env[_ledger.RESULTS_DIR_ENV] = str(self.results_dir)
        done = subprocess.run(self._argv("results"), cwd=str(self.root),
                              env=env, check=False, capture_output=True,
                              text=True)
        if done.returncode != 0:
            raise RuntimeError(
                f"./run.sh results exited {done.returncode}: "
                f"{done.stderr.strip() or done.stdout.strip()}")
        return done.stdout

    @contextmanager
    def _at(self, directory: Path | None) -> Iterator[None]:
        """Read the ledger at *directory* by moving the root it reads.

        kcilib.core.ledger resolves $KCI_RESULTS_DIR on every call, so this
        sets that one variable instead of walking the tree here: the layout
        stays that module's, and a caller asking for another directory is
        asking the ledger, not a second reader.
        """
        if directory is None:
            yield
            return
        previous = os.environ.get(_ledger.RESULTS_DIR_ENV)
        os.environ[_ledger.RESULTS_DIR_ENV] = str(directory)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(_ledger.RESULTS_DIR_ENV, None)
            else:
                os.environ[_ledger.RESULTS_DIR_ENV] = previous
