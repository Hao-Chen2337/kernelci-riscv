# SPDX-License-Identifier: LGPL-2.1-or-later
"""What a run came back with.

Draft this file is built from (``lib/out``)::

    class out

An Outcome is the only thing a run produces and the only thing a sink, a
viewer or a caller ever sees.  It is plain data with one method that turns it
into the record on disk, whose key set is a contract three readers already
depend on (`work/results/<build-id>/<test>.json`).

接口形状（C++，只有声明）：include/kci/local.hpp §10 Outcome。
"""

import json
from dataclasses import asdict, dataclass, field

from . import errors

# The record's key set, in the order it is written.  `results.py`, the GUI and
# the local table read these names; a missing one is a broken reader, so
# `record()` fills every field and never drops one.
RECORD_FIELDS = (
    "build_id",
    "build_created",
    "job",
    "test",
    "source",
    "timestamp",
    "verdict",
    "exit_code",
    "detail",
    "revision",
    "artifacts_dir",
    "log",
    "results",
)


@dataclass
class Outcome:
    """One (build, test) and what came of it."""

    build_id: str = ""
    test: str = ""
    verdict: str = errors.VERDICT_ERROR
    exit_code: int = errors.EXIT_INFRA
    detail: str = ""
    # TAP summary as the guest printed it: {"total": N, "failed": N, "skipped": N}
    results: dict = field(default_factory=dict)
    # Source revision of the tested kernel, when the build node carried one.
    revision: dict = field(default_factory=dict)
    build_created: str = ""
    job: str = ""
    source: str = ""
    timestamp: str = ""
    artifacts_dir: str = ""
    log: str = ""

    def record(self):
        """This outcome as the ledger record: every field present, no extras."""
        data = asdict(self)
        return {k: data[k] for k in RECORD_FIELDS}

    def json(self):
        """The record as the ledger writes it: keys sorted, one-space indent."""
        return json.dumps(self.record(), indent=1, sort_keys=True)

    @property
    def passed(self):
        return self.verdict == errors.VERDICT_PASS

    def print(self, stream=None):
        """One line an operator can grep: verdict, test, build, TAP counts, reason."""
        counts = ""
        if self.results:
            counts = (f"  {self.results.get('total', 0)} cases,"
                      f" {self.results.get('failed', 0)} failed,"
                      f" {self.results.get('skipped', 0)} skipped")
        print(f"{self.verdict:<10} {self.test:<16} {self.build_id}  {self.detail}{counts}",
              file=stream, flush=True)

    @classmethod
    def infra(cls, detail, **kw):
        """An outcome for a run that never got a verdict (bad flags, unreachable, timeout)."""
        return cls(verdict=errors.VERDICT_INFRA, exit_code=errors.EXIT_INFRA, detail=detail, **kw)
