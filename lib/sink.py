# SPDX-License-Identifier: LGPL-2.1-or-later
"""Where an Outcome goes: the ledger always and first, the callback only when the job asked.

The ledger is the durable record (`var/results/<build-id>/<test>.json`); the
callback POSTs the LAVA body the pipeline is the only parser of, with its token
read from the environment at the instant of delivery.

接口形状（C++，只有声明）：include/kci/engine.hpp §13 结果去哪里。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import requests
import yaml

from . import atomic, errors, layout, tests
from .errors import (
    CallbackMissingURLError,
    CallbackPermanentError,
    CallbackTransientError,
)
from .judge import LAVA_CASE_RE, strip_ansi, tap_summary
from .out import RECORD_FIELDS, Outcome

if TYPE_CHECKING:
    from .job import Job

LEDGER = "ledger"
CALLBACK = "callback"

# A remote token shared with the pipeline admins: read from the environment
# every time it is needed, never a parameter, never held in a config object.
TOKEN_ENV = "PULL_LABS_CALLBACK_TOKEN"

# ...and when the environment has nothing, this deployment's rendered settings,
# which is the second half of the resolution `deploy/stack.sh` already does.  The
# name is `layout.state()`'s, so a moved workspace moves it (grep `local-callback`).
SETTINGS_NAME = "local-callback.toml"

# The runtime section's one line, read with the regex `stack.sh` uses rather than
# parsed: python3 here is 3.10 and has no `tomllib`, `lib/config.py` records the
# project's refusal to add dependencies, and the renderer emits exactly this shape.
TOKEN_LINE_RE = re.compile(
    r"^\s*" + re.escape(tests.DEFAULT_LAB) + r"\s*=\s*\{[^}]*callback_token\s*=\s*\"([^\"]*)\"",
    re.MULTILINE)

# The POST: one timeout, three attempts, `time.sleep(2 * n)` between them.
REQUEST_TIMEOUT = 60
ATTEMPTS = 3

# The pipeline keeps about 200 characters of the reason it reads, and the body
# embeds at most this much console.
ERROR_MSG_LIMIT = 200
LOG_LIMIT = 2 << 20

# LAVA's job statuses: 2 = Complete, 3 = Incomplete - what the pipeline reads as
# an infrastructure problem rather than as a test result.
LAVA_STATUS_COMPLETE = 2
LAVA_STATUS_INCOMPLETE = 3

# The case a kselftest run is filed under: `0_kselftest.<suite>` in the lava case
# list, and that suite's per-test rows under the same key in `results`.
SUITE_CASE_PREFIX = "0_kselftest."
KSELFTEST_PREFIX = "kselftest-"

# The boot cases replayed from tuxrun's own LAVA lines, and the timestamp such a
# line is stamped with.
BOOT_CASES = ("login-action", "kernel-messages")
LAVA_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

# The pipeline finds its node through these two names: they must match the
# deployment, and a mismatch loses the result silently.  Knobs, not secrets.
API_CONFIG_NAME_ENV = "KCI_API_CONFIG_NAME"
STORAGE_CONFIG_NAME_ENV = "KCI_STORAGE_CONFIG_NAME"
DEFAULT_API_CONFIG_NAME = "docker-host"
DEFAULT_STORAGE_CONFIG_NAME = "docker-host"

# What a run that is not a plain pass says about itself when the outcome has no
# reason at all; an incomplete node with no reason is what this avoids.
NO_REASON = "no verdict"


class Sink:
    """One place an outcome can go: its name, whether this run wants it, one delivery."""

    def name(self) -> str:
        """What a caller reports this sink as."""
        raise NotImplementedError

    def wants(self, job: Job, outcome: Outcome) -> bool:
        """Should this sink receive that outcome?"""
        raise NotImplementedError

    def deliver(self, job: Job, outcome: Outcome) -> str:
        """Send it; return a one-line note for the console, or ''."""
        raise NotImplementedError


class Ledger(Sink):
    """The durable record: one JSON file per (build, test).  History, never pruned."""

    def name(self) -> str:
        """`"ledger"`."""
        return LEDGER

    def wants(self, job: Job, outcome: Outcome) -> bool:
        """Always: a callback that fails may not take the record down with it."""
        return True

    def deliver(self, job: Job, outcome: Outcome) -> str:
        """Write the record and name where it went; a write that failed is reported, never fatal."""
        filled = replace(outcome, build_id=outcome.build_id or job.build_id,
                         test=outcome.test or job.test)
        try:
            path = self.write(filled)
        except OSError as error:
            return f"NOT recorded: {error}"
        return f"recorded in {path}"

    @staticmethod
    def write(outcome: Outcome | dict) -> str:
        """Write one record atomically; a key outside RECORD_FIELDS raises rather than being dropped."""
        filled = _filled(outcome)
        path = layout.results(filled.build_id, filled.test)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic.write_text(path, filled.json())
        return path

    @staticmethod
    def read(build_id: str = "") -> list[Outcome]:
        """The records of one build (or of every build); an unreadable one raises, never a skip."""
        records: list[Outcome] = []
        for name in [build_id] if build_id else Ledger.builds():
            records += _build_records(name)
        return records

    @staticmethod
    def builds() -> list[str]:
        """The build ids the ledger knows, newest record first."""
        root = layout.results()
        if not os.path.isdir(root):
            return []
        known = []
        for name in sorted(os.listdir(root)):
            if not os.path.isdir(os.path.join(root, name)):
                continue
            records = _build_records(name)
            if records:
                # Ordered by the newest timestamp IN the records, not by
                # directory mtime: a copy or a restore would sort as if it had
                # just run.  The name breaks a tie, so the order is stable.
                known.append((max(one.timestamp or "" for one in records), name))
        known.sort(reverse=True)
        return [name for _newest, name in known]


class Callback(Sink):
    """The result as the pipeline expects it: one POST of a LAVA-compatible body."""

    def __init__(self, url: str = "", session: requests.Session | None = None) -> None:
        self.url = url
        self.session = session

    def name(self) -> str:
        """`"callback"`."""
        return CALLBACK

    def wants(self, job: Job, outcome: Outcome) -> bool:
        """Only when a URL is known: this sink's own, else the definition's."""
        return bool(self.url or callback_url(job))

    def deliver(self, job: Job, outcome: Outcome) -> str:
        """POST the body; 4xx is permanent, 5xx or a network failure is retried, then transient."""
        url = self.url or callback_url(job)
        if not url:
            raise CallbackMissingURLError(
                "no callback URL in the job definition; result NOT reported, kept pending")
        return _post(url, lava_body(job, outcome), self.session)


def lava_body(job: Job, outcome: Outcome, console: str = "") -> dict:
    """The LAVA-compatible body for one run: the definition, the case lists and the log as YAML text.

    Byte-level contract with the pipeline's callback endpoint, replayed through
    the real upstream parser by `docs/gui-rework/tools/verify_callback_body.py`.  The verdict
    is the outcome's; the console adds only what the body replays from it.
    """
    output = console or _archived_console(outcome.log)
    test = job.test or outcome.test
    cases = [{"name": name, "result": result, "metadata": {}}
             for name, result in _console_cases(output)]
    results = {}
    # Whether the console itself shows a failure - a boot case, or a job case -
    # as opposed to a verdict we only hold in the ledger.
    evidence = any(case.get("result") == "fail" for case in cases)
    if test.startswith(KSELFTEST_PREFIX):
        # The suite case is what flips the job node to fail when tuxrun exited 0
        # with failing selftests, so it exists for every kselftest run.
        tap = tap_summary(output, test)
        suite_key = SUITE_CASE_PREFIX + test.removeprefix(KSELFTEST_PREFIX)
        cases.append({"name": suite_key, "result": "fail" if tap.failed else "pass",
                      "metadata": {}})
        results[suite_key] = yaml.safe_dump(
            [{"name": name, "result": result, "metadata": {}}
             for name, result in tap.per_test.items()])
        # A row the console actually printed is evidence; the suite case above
        # is a summary of those rows and is NOT evidence on its own.
        evidence = any(result == "fail" for result in tap.per_test.values())
    status = _status(outcome, cases, evidence)
    cases.insert(0, {"name": "job", "metadata": _job_metadata(outcome, status)})
    results["lava"] = yaml.safe_dump(cases)
    definition = {"metadata": {"api_config_name": _api_config_name(),
                               "storage_config_name": _storage_config_name()}}
    return {
        "definition": yaml.safe_dump(definition),
        "results": results,
        "status": status,
        "log": yaml.safe_dump(_log_lines(output)),
        "actual_device_id": tests.device(job.definition()),
    }


def verdict_from_body(body: dict) -> Outcome:
    """The outcome a body reports, read back OUT of it: the record and the pipeline cannot disagree."""
    status = body.get("status")
    error = _job_case_metadata(body)
    if status != LAVA_STATUS_COMPLETE:
        detail = error.get("error_msg") or f"lava status {status} (incomplete)"
        return Outcome(verdict=errors.VERDICT_INFRA, exit_code=errors.EXIT_INFRA, detail=detail)
    for name, result in _lava_cases(body):
        # A Complete job is not automatically a pass: tuxrun exits 0 even when
        # every selftest failed, so the suite case carries that verdict.
        if result == "fail" and (name.startswith(SUITE_CASE_PREFIX) or name in BOOT_CASES):
            return Outcome(verdict=errors.VERDICT_FAIL, exit_code=errors.EXIT_TEST_FAIL,
                           detail=f"{name}: fail")
    return Outcome(verdict=errors.VERDICT_PASS, exit_code=errors.EXIT_PASS,
                   detail=error.get("error_msg") or "")


def _settings_token() -> str:
    """The token this deployment rendered into its settings, or '' if it cannot be read.

    Never raises: the ledger is written before any callback (`deliver`), and
    losing that record to an unreadable settings file would be worse than the
    401 the missing header causes.
    """
    try:
        with open(layout.state(SETTINGS_NAME), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""
    match = TOKEN_LINE_RE.search(text)
    return match.group(1) if match else ""


def callback_token() -> str:
    """The callback token, at the instant of delivery: the environment, else the settings.

    `deploy/stack.sh` resolves this itself and exports the result into the worker
    it spawns, so `stack.sh --worker` always worked.  The two other ways of
    running one had no environment to inherit: `python3 pull_worker.py --once` run
    by hand after `stack.sh --seed` - a script cannot export into its parent shell
    - and a worker spawned from the GUI page, which passes no `env=` and so
    inherited the *GUI server's* environment, in which nothing had ever set
    `PULL_LABS_CALLBACK_TOKEN`.  Both sent no `Authorization` header at all, so
    every callback came back 401 while the ledger recorded the run: the work
    happened and the API said it never did.

    The environment still wins verbatim and is never rewritten - an operator's
    exported token is what `_post` will send.  Only the settings file's value is
    stripped of its leading `Token `, because the renderer writes the header the
    callback compares (`callback_token = "Token <bare>"`) while `_post` re-adds
    that prefix itself; read verbatim it produced `Token Token <bare>`, which
    401'd exactly as hard as sending nothing.
    """
    token = os.environ.get(TOKEN_ENV) or ""
    if token:
        return token
    configured = _settings_token()
    if configured.startswith("Token "):
        return configured[len("Token "):]
    return configured


def deliver(job: Job, outcome: Outcome, sinks: tuple[Sink, ...] | None = None) -> dict[str, str]:
    """Hand one outcome to every sink that wants it, the ledger first and unconditional.

    Returns `{sink name: note}`; a caller's own set is used as given except that
    a missing ledger is added in front, so no order can lose the record.
    """
    chosen = (Ledger(), Callback()) if sinks is None else tuple(sinks)
    if not any(one.name() == LEDGER for one in chosen):
        chosen = (Ledger(), *chosen)
    return {one.name(): one.deliver(job, outcome)
            for one in chosen if one.wants(job, outcome)}


# --- the callback body's pieces ---------------------------------------------


def callback_url(job: Job) -> str:
    """The callback URL the job definition records, or ''."""
    section = job.definition().get("callback") or {}
    return (section.get("url") or "") if isinstance(section, dict) else ""


def _post(url: str, body: dict, session: requests.Session | None = None) -> str:
    """POST *body* with the token read now; a 5xx or a network failure is retried, a 4xx is not."""
    token = callback_token()
    headers = {"Authorization": f"Token {token}"} if token else {}
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            response = (session or requests).post(
                url, json=body, headers=headers, timeout=REQUEST_TIMEOUT,
                allow_redirects=False)
        except requests.exceptions.RequestException as error:
            last = error
        else:
            if response.is_redirect or response.is_permanent_redirect:
                # Never follow a redirect with the shared token attached.
                raise CallbackPermanentError(f"callback redirected ({response.status_code})")
            if response.status_code < 400:
                return f"result posted (HTTP {response.status_code})"
            if response.status_code < 500:
                raise CallbackPermanentError(f"callback returned {response.status_code}")
            last = requests.exceptions.HTTPError(
                f"callback returned {response.status_code}")
        time.sleep(2 * (attempt + 1))
    raise CallbackTransientError(str(last))


def _status(outcome: Outcome, cases: list[dict], evidence: bool) -> int:
    """LAVA's job status: Complete once a verdict exists AND the console shows it.

    Complete is what lets the pipeline read the case list as the result.  A
    failure the *console* shows - a failing TAP row, a failing boot case - is
    Complete with a failing case; a failure we can only assert (no TAP at all, a
    canceled job, no boot output) is Incomplete, never green.  The suite case
    the body synthesises from the counts is not evidence: reading it as such
    reported a canceled job as `pass` to the pipeline while the ledger said
    `fail`, and a result that is green in one place and red in the other is the
    one disagreement this body may not have.
    """
    if outcome.exit_code == errors.EXIT_INFRA:
        return LAVA_STATUS_INCOMPLETE
    if outcome.passed or evidence:
        return LAVA_STATUS_COMPLETE
    return LAVA_STATUS_INCOMPLETE


def _job_metadata(outcome: Outcome, status: int) -> dict:
    """The `job` case's metadata: where a run that is not a plain pass names its reason."""
    if status == LAVA_STATUS_COMPLETE:
        return {}
    # `Infrastructure` when we never got a verdict (what `is_infra_error()` reads),
    # `Job` when the run failed on its own - the old body's two spellings, both
    # carrying the judge's bounded reason, whose useful end is last.
    kind = "Infrastructure" if outcome.exit_code == errors.EXIT_INFRA else "Job"
    return {"error_type": kind, "error_msg": (outcome.detail or NO_REASON)[-ERROR_MSG_LIMIT:]}


def _console_cases(console: str) -> list[tuple[str, str]]:
    """The `(name, result)` pairs of tuxrun's own LAVA case lines, in console order."""
    return [(match.group(1), match.group(2))
            for match in LAVA_CASE_RE.finditer(strip_ansi(console))
            if match.group(1) in BOOT_CASES]


def _log_lines(console: str) -> list[dict]:
    """The console's tail as LAVA output.yaml lines: `{dt, lvl, msg}`, blanks dropped."""
    lines = []
    for raw in console[-LOG_LIMIT:].splitlines():
        line = strip_ansi(raw).rstrip()
        if not line.strip():
            continue
        stamp = LAVA_TS_RE.match(line)
        lines.append({
            "dt": stamp.group(0) if stamp else "",
            "lvl": "target",
            "msg": line[stamp.end():].lstrip() if stamp else line,
        })
    return lines


def _api_config_name() -> str:
    """The pipeline's API config name, from the deployment or its default."""
    return os.environ.get(API_CONFIG_NAME_ENV) or DEFAULT_API_CONFIG_NAME


def _storage_config_name() -> str:
    """The pipeline's storage config name, from the deployment or its default."""
    return os.environ.get(STORAGE_CONFIG_NAME_ENV) or DEFAULT_STORAGE_CONFIG_NAME


def _archived_console(path: str) -> str:
    """The console a run archived at *path*, or '' when there is none left to read."""
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        # An unreadable console is not a reason to keep a finished result
        # pending; the body reports what it has, exactly as it would for a run
        # that printed nothing.
        return ""


# --- reading a body back ----------------------------------------------------


def _lava_cases(body: dict) -> list[tuple[str, str]]:
    """The `(name, result)` pairs of a body's lava case list, never raising."""
    return [(str(case.get("name") or ""), str(case.get("result") or ""))
            for case in _lava_case_dicts(body)]


def _job_case_metadata(body: dict) -> dict:
    """The metadata of a body's 'job' case (where an infrastructure failure names itself)."""
    for case in _lava_case_dicts(body):
        if case.get("name") == "job":
            metadata = case.get("metadata")
            return metadata if isinstance(metadata, dict) else {}
    return {}


def _lava_case_dicts(body: dict) -> list[dict]:
    """A body's lava cases as dicts: the list is a YAML string inside the body."""
    raw = (body.get("results") or {}).get("lava") or ""
    try:
        cases = yaml.safe_load(raw)
    except yaml.YAMLError:
        return []
    return [case for case in cases if isinstance(case, dict)] if isinstance(cases, list) else []


# --- the ledger's records ---------------------------------------------------


def _filled(outcome: Outcome | dict) -> Outcome:
    """*outcome* as a full Outcome; a key outside RECORD_FIELDS raises rather than being dropped."""
    data = outcome.record() if isinstance(outcome, Outcome) else dict(outcome)
    unknown = sorted(set(data) - set(RECORD_FIELDS))
    if unknown:
        # Silently dropping an unknown key is how a record loses its verdict.
        raise ValueError(f"unknown result field(s) {', '.join(unknown)}; "
                         f"the record holds {', '.join(RECORD_FIELDS)}")
    filled = Outcome(**{name: value for name, value in data.items() if name in RECORD_FIELDS})
    if not filled.build_id or not filled.test:
        # The path is the identity of the row; a record without one is not a row.
        raise ValueError("a result record needs a build id and a test name, got "
                         f"{filled.build_id!r} / {filled.test!r}")
    return filled


def _build_records(build_id: str) -> list[Outcome]:
    """Every record of one build, in test-name order; none when it has no directory."""
    directory = layout.results(build_id)
    if not os.path.isdir(directory):
        return []
    return [_record_at(os.path.join(directory, name))
            for name in sorted(os.listdir(directory)) if name.endswith(".json")]


def _record_at(path: str) -> Outcome:
    """One record file as an Outcome; an unreadable or foreign one raises, naming the file.

    **A `LedgerError`, not a `ValueError`.**  It used to raise plain `ValueError` /
    `TypeError` (the old tree did too), which no entry point's `except
    errors.KciError` could catch: `results.py` on a corrupt record printed a
    traceback and exited 1 - the code that means "a test failed" - while the truth
    is "we never got what we came for" (3).  Same writer, same reader, one
    vocabulary.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise errors.LedgerError(
            f"result record {path} is unreadable: {error}") from error
    if not isinstance(data, dict):
        raise errors.LedgerError(f"result record {path} is not an object")
    unknown = sorted(set(data) - set(RECORD_FIELDS))
    if unknown:
        raise errors.LedgerError(
            f"result record {path} holds field(s) {', '.join(unknown)} "
            "this reader does not own")
    return Outcome(**{name: value for name, value in data.items() if name in RECORD_FIELDS})
