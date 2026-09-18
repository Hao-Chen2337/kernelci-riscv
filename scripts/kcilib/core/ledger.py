# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Durable (build, test, verdict) ledger of the local RISC-V pull lab.

Path layout and key set are the contract, not an implementation detail::

    work/results/<build-id>/<test>.json   -   build_id, build_created, job,
    test, source, timestamp, verdict, exit_code, detail, revision,
    artifacts_dir, log, results

Every outcome is recorded (a failed run most of all), through a temporary file
and a rename, so a reader may trust any file it finds.  Keys are written sorted
and indented by one space, so identical outcomes diff cleanly.
Rationale: docs/code-notes/W2c-kcilib.md.
"""

import json
import os
import time

from kcilib import repo_root
from kcilib.core import layout

# Derived from this file's own location, never a hardcoded path: work/ is
# gitignored and regenerable.  repo_root() walks up to run.sh - a fixed
# dirname() count landed in scripts/.
ROOT = repo_root()
# layout owns where records live; RESULTS_DIR is that answer with the override
# left out, because a module constant is frozen at import and has never followed
# $KCI_RESULTS_DIR - the call-time answer is results_dir() below.
RESULTS_DIR = os.fspath(layout.default_results())

# Overridable for testing, not deployment: ./run.sh verify drives a real
# run_node() that would otherwise leave records in the repository's work/ tree.
# Only the root moves - the layout stays the contract.
RESULTS_DIR_ENV = "KCI_RESULTS_DIR"


def results_dir():
    """The directory records live in: work/results, or $KCI_RESULTS_DIR."""
    # layout.results() is the one owner of that path and reads the same variable.
    # A set override is returned as it was given rather than pathlib-normalised,
    # so this function's value is byte for byte what it has always been.
    return os.environ.get(RESULTS_DIR_ENV) or os.fspath(layout.results())

# The one place the record's key set is defined: write_result() fills what a
# caller leaves out and refuses anything else, so a typo cannot drop a field.
RESULT_FIELDS = (
    "build_id",
    "build_created",
    "job",
    "test",
    # Which writer filed the record ("fetch" one-shot runner, "worker", "table"):
    # a reader that cannot tell them apart cannot tell a re-run from a job.
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

# The writer's historical fallbacks: "" for a missing name, {} for a revision.
_FIELD_DEFAULTS = {
    "build_created": None,
    "job": "",
    "source": "",
    "timestamp": None,  # replaced by the write time below
    "verdict": None,
    "exit_code": None,
    "detail": None,
    "revision": {},
    "artifacts_dir": None,
    "log": None,
    "results": None,
}


def test_of(definition):
    """A job definition -> the test name its record is filed under.

    ``tests[0].type``, then ``tests[0].id``, then ``"boot"``.  The name is part of
    the layout below, so the rule lives with it: kcilib.table.jobspec.test_of and
    the run path (kcilib.run.jobrun.record_result) both call this one, instead of
    keeping a copy each.

    The run path's copy had no type check, and it runs OUTSIDE run_node's error
    handling, so a definition shaped ``{"tests": ["boot"]}`` raised AttributeError
    out of run_node - poll.handle_event reads that as "handled", marks the node
    seen, and the node's result is never posted and never retried.  A malformed
    tests[0] is therefore "boot" here, never an exception.
    """
    tests = definition.get("tests") or [{}]
    if not isinstance(tests, (list, tuple)):
        # `tests: 5` / `tests: true` is not a list at all; tests[0] would raise
        # TypeError, and a raise here is the failure this function exists to stop.
        return "boot"
    first = tests[0] if tests and isinstance(tests[0], dict) else {}
    return first.get("type") or first.get("id") or "boot"


def result_path(build_id, test):
    """The record path for one (build, test): the only place the layout lives."""
    return os.path.join(results_dir(), build_id, f"{test}.json")


def write_result(build_id, test, payload):
    """Write the record for one (build, test) and return the path written.

    *payload* carries the outcome; the build and test identity comes from the
    arguments, so a record can never be filed under a path naming another run."""
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
        # Without a timestamp a record cannot be lined up with its build.
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

    An unrun test is simply absent; an unparseable record raises rather than
    being skipped - a ledger that quietly loses rows is worse than none."""
    directory = os.path.join(results_dir(), build_id)
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

def list_builds():
    """Every build id the ledger holds a record for, newest record first.

    Ordered by the newest timestamp IN the records, not by directory mtime (a
    copy or a restore would sort as if it had just run); an unreadable record
    raises here too."""
    root = results_dir()
    if not os.path.isdir(root):
        return []
    builds = []
    for name in sorted(os.listdir(root)):
        if not os.path.isdir(os.path.join(root, name)):
            continue
        records = read_results(name)
        if not records:
            continue
        newest = max(
            (record.get("timestamp") or "") for record in records.values()
        )
        builds.append((newest, name))
    # The name breaks a tie, so same-second builds still come back stably.
    builds.sort(reverse=True)
    return [name for _newest, name in builds]
