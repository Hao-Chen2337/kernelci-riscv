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
import urllib.parse
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

# The history that sits beside each record: one line per run of one pair, oldest
# first (`layout.results_history`).  **The suffix must not end in `.json`**, and that
# is the whole reason it is spelled this way: `_build_records` lists a build's
# directory with `name.endswith(".json")`, so a history named `<test>.json` - or
# `<test>.history.json` - would be read back as a second record of the same pair, and
# every reader of the ledger would see a pair that disagrees with itself.  `.jsonl`
# cannot match that test, and it says what the file is: one JSON object per line.
HISTORY_SUFFIX = ".history.jsonl"

# A remote token shared with the pipeline admins: read from the environment
# every time it is needed, never a parameter, never held in a config object.
TOKEN_ENV = "PULL_LABS_CALLBACK_TOKEN"

# ...and when the environment has nothing, this deployment's rendered settings,
# which is the second half of the resolution `deploy/stack.sh` already does.  The
# name is `layout.state()`'s, so a moved workspace moves it (grep `local-callback`).
SETTINGS_NAME = "local-callback.toml"

# Where a report goes when the operator says so rather than the definition
# (`callback_override`).  One URL, one line, under `var/state/` beside the worker's
# own file - and absent, which is the ordinary case, means the definition's URL.
OVERRIDE_NAME = "callback-url"

# The one value that file may hold instead of a URL: not a destination but the decision
# that there is none ("关掉回调" - run here and report nowhere).  It is a word rather than
# an empty file because **absent and empty are already taken**: the file missing or blank
# is the ordinary case and means the definition's URL, so "turn it off" needs a spelling
# of its own or the two would be one.  `off` and not a `scheme:` shape, because every
# value this file accepts is a URL and a URL cannot be a bare word - and because it is
# what an operator would type into the box if the box did not say it first.
OFF = "off"

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
    """The durable record: one current JSON file per (build, test), and its history.

    Two files per pair, not one.  `<test>.json` is the pair's *current* answer and is
    rewritten by every run - every reader in this tree joins on it (`Ledger.read`,
    `re.Records`, the GUI's counts) - and `<test>.history.jsonl` keeps the runs it
    replaced, because the question the current file cannot answer is the one the
    operator asked of a pair that failed: how often did this run, and what did it say
    each time.  Both are history and neither is pruned.
    """

    def name(self) -> str:
        """`"ledger"`."""
        return LEDGER

    def wants(self, job: Job, outcome: Outcome) -> bool:
        """Always: a callback that fails may not take the record down with it."""
        return True

    def deliver(self, job: Job, outcome: Outcome) -> str:
        """Write the record and name where it went; a write that failed is reported, never fatal.

        **`LedgerError` is caught with `OSError`, and that is not the same list by
        accident.**  `write` raises `LedgerError` for the one failure `OSError` does not
        describe - a history line that cannot be read back, which is a fact about the
        bytes already on disk rather than about this call (`_history_at`).  A ledger that
        let that escape would be the opposite of what this class promises: `sink.deliver`
        builds its notes in one dict comprehension, so a sink that raises takes every
        sink behind it down with it, and the callback - the delivery the operator is
        actually waiting on - would never be sent because a *record* could not be written.
        """
        filled = replace(outcome, build_id=outcome.build_id or job.build_id,
                         test=outcome.test or job.test)
        try:
            path = self.write(filled)
        except (OSError, errors.LedgerError) as error:
            return f"NOT recorded: {error}"
        return f"recorded in {path}"

    @staticmethod
    def write(outcome: Outcome | dict) -> str:
        """Write one record atomically; a key outside RECORD_FIELDS raises rather than being dropped.

        **One run writes two files**, and the second is what makes a re-run worth
        asking for: `<test>.json` stays the pair's current answer, exactly as it was,
        while `_append_history` adds this run to `<test>.history.jsonl` (see
        `HISTORY_SUFFIX` for why the history is not a second `.json`).

        **The history line goes first and the record second**, so that `deliver`'s
        message is true whichever of the two fails: that note is about the record -
        `recorded in <path>`, or `NOT recorded: <why>` - and writing the record last
        makes a history that could not be written mean "nothing was written", rather
        than a record that landed under a note saying it did not.
        """
        filled = _filled(outcome)
        path = layout.results(filled.build_id, filled.test)
        _append_history(filled)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic.write_text(path, filled.json())
        return path

    @staticmethod
    def history(build_id: str, test: str) -> list[Outcome]:
        """Every record this pair ever wrote, oldest first; `[]` when it has none.

        The surviving record is the newest run of a pair and this is all of them, which
        is what the page's run-history panel needs: a run whose record a later one
        replaced is still a run whose verdict can be read (`builds._run_history_panel`).

        A line this reader cannot parse raises, naming its file and line - the same
        rule and the same vocabulary as `_record_at`, for the same reason: a reader that
        silently dropped lines would answer "what did this pair do" with a shorter list
        and no way for the answer to say so.
        """
        return _history_at(layout.results_history(build_id, test))

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
        """Only when a URL is known: this sink's own, else the definition's.

        **`OFF` is not a fall-through.**  This sink is handed what `delivery_url`
        resolved, and "off" is a resolution - a deployment that has turned the callback
        off must not find the definition's URL underneath it, which is exactly what the
        `or callback_url(job)` below would do with an empty value.  So the check comes
        first, and an off callback is one this run does not want: `deliver_all` skips it,
        the ledger still gets its record, and nothing goes pending over a report that was
        never meant to be sent.
        """
        if self.url == OFF:
            return False
        return bool(self.url or callback_url(job))

    def deliver(self, job: Job, outcome: Outcome) -> str:
        """POST the body; 4xx is permanent, 5xx or a network failure is retried, then transient."""
        url = self.url or callback_url(job)
        if url == OFF:
            # Reached only by the re-post, which calls this directly and not through
            # `wants` (`poller._repost_pending`): a report the operator's own setting has
            # nowhere to send stays pending rather than being thrown away, so turning the
            # callback back on delivers it.  Transient for the same reason.
            raise CallbackMissingURLError(
                f"callbacks are off (var/state/{OVERRIDE_NAME} says {OFF!r}); "
                "result NOT reported, kept pending")
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


def token_source() -> str:
    """Which of the two places `callback_token()` reads a token from is answering.

    `"env"` is `$PULL_LABS_CALLBACK_TOKEN`, `"settings"` is the rendered
    `var/state/local-callback.toml`, and `""` is neither - the case where a callback
    goes out with no `Authorization` header and comes back 401 while the ledger records
    the run, which is the exact failure this function exists to make visible.

    **The token is not in the answer and must never be**, which is why the caller gets a
    word and not the value: `/worker` prints this, a page is a thing that gets
    screenshotted and pasted into a chat, and the difference between "env" and
    "settings" is the whole of what an operator can act on anyway (`deploy/stack.sh`
    exports the first; a hand-run `pull_worker.py` inherits neither).
    """
    if os.environ.get(TOKEN_ENV):
        return "env"
    return "settings" if _settings_token() else ""


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


def callback_override() -> str:
    """The URL this deployment reports to instead; '' for the definition's, `OFF` for none.

    The one setting on this console that changes where a *result* goes.  A job node
    carries the callback the pipeline that dispatched it declared - in production the
    pipeline's own endpoint - and an operator running this deployment against their own
    instance has no way to redirect that, because the URL arrives inside the definition
    and nothing local reads it: the worker's sinks are the definition's (`poller.handle`),
    and `--callback-url` is deliberately not a worker flag (`config.parse_poll`).  So the
    redirect lives where the rest of this deployment's state lives, `var/state/`, and the
    page that shows the return path is where it is set.

    Read at the instant of delivery and never cached, like `callback_token`: the worker
    is a long-lived process, and a setting the operator changes on the page has to take
    effect on the next delivery rather than on the next restart.

    Never raises.  An unreadable file means "no override" - the definition's URL is the
    documented behaviour, and a delivery that goes to the pipeline's endpoint because a
    local file was unreadable is better than a run whose result was thrown away.

    The file's third answer is `OFF`, the one value that is not a URL: the deployment
    reports nowhere (see `OFF`).  It is read here as itself and *not* folded into the
    empty answer, because the two mean opposite things - empty is "use the definition's"
    and `off` is "use nobody's".
    """
    try:
        with open(layout.state(OVERRIDE_NAME), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""
    return text.strip()


def set_callback_override(url: str) -> str:
    """Write (or, for an empty *url*, remove) the override; returns what is now in force.

    Three answers, and the return value is which one was written: a URL, `""` for "back
    to the definition's" (the file is removed), or `OFF` for "nowhere".

    **Only `http` and `https` with a host**, and that is the whole validation: this is a
    URL a *token* is POSTed to, so a value with no scheme would be handed to `requests`
    as a relative path (an error at delivery, long after the page said "saved"), and a
    value like `file:///etc/...` is not a place a report can go.  Query strings and paths
    are kept verbatim - the local stack's own callback carries both.  `OFF` passes that
    check by being caught before it: it is the one accepted value that is not a URL, and
    it is accepted because a reader who wants no callback has no URL to type.

    Raises `ConfigError` for a URL it will not write, which is the page's 409 and not a
    stack trace: the operator typed it, so the reader is the one who can fix it.
    """
    wanted = (url or "").strip()
    path = layout.state(OVERRIDE_NAME)
    if not wanted:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return ""
    if wanted.lower() == OFF:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        atomic.write_text(path, OFF + "\n")
        return OFF
    parts = urllib.parse.urlsplit(wanted)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise errors.ConfigError(f"not a callback URL: {wanted!r}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    atomic.write_text(path, wanted + "\n")
    return wanted


def delivery_url(url: str) -> str:
    """Where a report for this definition really goes: this deployment's override, else it.

    **The one place the choice is made.**  Two callers ask - the worker's delivery
    (`poller.Poller.handle`) and the re-post of a report that was refused
    (`poller.Poller._repost_pending`) - and a second copy of `override or url` is how the
    page and the worker would come to disagree about where the next report is going, which
    is the exact question the panel exists to answer.

    The answer may be `OFF`, and that is a real answer rather than an empty one: the
    worker builds `Callback(delivery_url(…))` from this and nothing else, so a deployment
    that reports nowhere has to arrive at the sink as `OFF` - an empty string here would
    fall through to the definition's URL inside `Callback.wants` and post to the very
    endpoint the operator turned off.

    A one-shot run is deliberately *not* a caller: `table.py run` posts only when it is
    given `--callback-url` (`RunConfig.sinks`), and a deployment setting that silently
    turned that on would have a command POST to a remote service it was never asked to
    talk to.
    """
    return callback_override() or url


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
    """Every record of one build, in test-name order; none when it has no directory.

    `.json` and nothing else: this listing is what makes `HISTORY_SUFFIX` load-bearing,
    because a pair's history sits in this same directory and must not be listed here as
    a second record of the pair.
    """
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
    return _outcome_of(data, f"result record {path}")


def _append_history(outcome: Outcome) -> None:
    """Add one record to its pair's history, unless that run is already in it.

    **The file is rewritten whole, through `lib/atomic.py`.**  Every write in this tree
    goes through those two functions for one reason - a reader must never open a file
    that is halfway written - and this is the one ledger file a *page* reads while a
    worker writes it (`Ledger.history`).  `open("a")` would append without that
    guarantee; the cost of the rewrite is a short line per run of a single pair.

    **The append is idempotent, and that is a requirement rather than a nicety.**
    `Ledger.write` is called more than once for one result in this tree (a retry, or a
    second sink's delivery), and a history that grew a line each time would answer
    "how often did this pair run" with a number that is not how often it ran.  The join
    is `_same_run`, which is the page's own join (`builds._ledger_run`) spelled the same
    way - so the history can never hold two lines a reader would join to one run.
    """
    path = layout.results_history(outcome.build_id, outcome.test)
    known = _history_at(path)
    if any(_same_run(one, outcome) for one in known):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic.write_text(path, "".join(json.dumps(one.record(), sort_keys=True) + "\n"
                                    for one in [*known, outcome]))


def _history_at(path: str) -> list[Outcome]:
    """Every record one history file holds, oldest first; a file that is not there is `[]`.

    A missing file is not an error: it is a pair no run has touched since the history
    was added, and a reader that raised there would make every ledger written before
    it unreadable.  An unreadable one is *not* "no history" either, and raises - the
    distinction `_record_at` already draws between a record that is not there and one
    that cannot be read.

    A blank line is stepped over; anything else that is not one record raises, naming
    the line.  `json.dumps` never writes a blank line, so a blank one is the file's own
    whitespace rather than a record, and nothing is lost by not reading it as one.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return []
    except OSError as error:
        raise errors.LedgerError(f"result history {path} is unreadable: {error}") from error
    records: list[Outcome] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError as error:
            raise errors.LedgerError(
                f"result history {path} line {number} is unreadable: {error}") from error
        records.append(_outcome_of(data, f"result history {path} line {number}"))
    return records


def _outcome_of(data, where: str) -> Outcome:
    """One already-parsed record as an Outcome; a foreign key set raises, naming *where*.

    `where` is the file - and the line, when the file is a history - so both readers
    refuse in the same three sentences and neither has to be recognised from its
    wording.  Two readers of one record shape is exactly how a field ends up dropped
    by one of them, which is what the unknown-key check exists to prevent.
    """
    if not isinstance(data, dict):
        raise errors.LedgerError(f"{where} is not an object")
    unknown = sorted(set(data) - set(RECORD_FIELDS))
    if unknown:
        raise errors.LedgerError(
            f"{where} holds field(s) {', '.join(unknown)} this reader does not own")
    return Outcome(**{name: value for name, value in data.items() if name in RECORD_FIELDS})


def _same_run(one: Outcome, other: Outcome) -> bool:
    """Whether two records are the same run: the console they name, else the stamp.

    `builds._ledger_run` reads a record against the runs of its pair in exactly this
    order - the console's file name when the record has one, and the run's start stamp
    when it has not - and this is that rule between two records instead of between a
    record and a run, so the history can never hold two lines the panel would join to
    one run.

    Two records that both name a console are the same run when they name the same file
    and not otherwise; as soon as one of them names none, the file names cannot decide
    it and the stamp (with the test and the build id) is what is left.  A record with no
    console is a run that printed nothing (`Job._keep_console` answers `""` for one) and
    its stamp is the same `started` string its console's file name would have been built
    from, which is why the fallback is the stamp on both sides of the ledger.
    """
    named = os.path.basename(str(one.log or ""))
    other_named = os.path.basename(str(other.log or ""))
    if named and other_named:
        return named == other_named
    return ((one.timestamp, one.test, one.build_id)
            == (other.timestamp, other.test, other.build_id))
