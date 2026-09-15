# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Durable (build, test, verdict) ledger of the local RISC-V pull lab.

Every run of scripts/fetch-and-run-latest.py records what it tested and how it
ended, because the run itself leaves nothing durable: its workspace is a
gitignored work/downloads/<build-id>/ that the next run overwrites and its
console only exists in the terminal it was started from.  The record is
written for EVERY outcome - a failed run is exactly the one worth having a
record of - so writing it must not be the thing that fails: records are
written to a temporary file and renamed into place, and a reader may
therefore trust any file it finds.

The path layout and the key set are the contract, not an implementation
detail (a report, a regression tracker or an operator reads them without
importing this module)::

    work/results/<build-id>/<test>.json

      build_id, build_created, job, test, timestamp, verdict, exit_code,
      detail, revision, artifacts_dir, log, results

Keys are written sorted and indented by one space, so two records of the same
outcome are byte-identical and diff cleanly.
"""

import json
import os
import time

# Repository layout derived from this file's own location (never a hardcoded
# absolute path): work/ is gitignored and holds regenerable runtime artifacts.
ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
RESULTS_DIR = os.path.join(ROOT, "work", "results")

# The one place the record's key set is defined: `write_result()` fills the
# fields a caller leaves out and refuses fields that are not here, so a typo
# cannot quietly drop a field from the record.
RESULT_FIELDS = (
    "build_id",
    "build_created",
    "job",
    "test",
    "timestamp",
    "verdict",
    "exit_code",
    "detail",
    "revision",
    "artifacts_dir",
    "log",
    "results",
)

# Taken from the fallbacks the writer has always used: a build without a name
# is "" and one without a revision is {}, not null.
_FIELD_DEFAULTS = {
    "build_created": None,
    "job": "",
    "timestamp": None,  # replaced by the write time below
    "verdict": None,
    "exit_code": None,
    "detail": None,
    "revision": {},
    "artifacts_dir": None,
    "log": None,
    "results": None,
}


def result_path(build_id, test):
    """The record path for one (build, test): the only place the layout lives."""
    return os.path.join(RESULTS_DIR, build_id, f"{test}.json")


def write_result(build_id, test, payload):
    """Write the record for one (build, test) and return the path written.

    *payload* carries the outcome - build_created, job, verdict, exit_code,
    detail, revision, artifacts_dir, log, results (and optionally timestamp) -
    while the build and test identity comes from the arguments, so a record
    can never be filed under a path that names a different run."""
    if not build_id or not test:
        raise ValueError(
            f"a result record needs a build id and a test name, got "
            f"{build_id!r} / {test!r}"
        )
    unknown = sorted(set(payload) - set(RESULT_FIELDS))
    if unknown:
        # Silently dropping an unknown key is how a record loses its verdict.
        raise ValueError(
            f"unknown result field(s) {', '.join(unknown)}; "
            f"the record holds {', '.join(RESULT_FIELDS)}"
        )
    for field, value in (("build_id", build_id), ("test", test)):
        if field in payload and payload[field] != value:
            raise ValueError(
                f"payload {field} {payload[field]!r} disagrees with the "
                f"argument {value!r}; the record would contradict its path"
            )
    record = dict(_FIELD_DEFAULTS)
    record.update(payload)
    record["build_id"] = build_id
    record["test"] = test
    if not record["timestamp"]:
        # A record that does not say when it was written cannot be lined up
        # with the build it describes.
        record["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    path = result_path(build_id, test)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as handle:
        json.dump(record, handle, indent=1, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return path


def read_results(build_id):
    """Every recorded record of one build, keyed by test name.

    A test that was never run is simply absent ({} for a build nothing is
    recorded for), and a record that cannot be parsed raises rather than being
    skipped: a ledger that quietly loses rows is worse than no ledger."""
    directory = os.path.join(RESULTS_DIR, build_id)
    records = {}
    if not os.path.isdir(directory):
        return records
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue  # a .tmp left by a killed write is not a record
        path = os.path.join(directory, name)
        try:
            with open(path) as handle:
                records[name[: -len(".json")]] = json.load(handle)
        except (ValueError, OSError) as error:
            raise ValueError(
                f"result record {path} is unreadable: {error}"
            ) from error
    return records
