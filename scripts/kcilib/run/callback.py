# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The result report: LAVA-compatible body assembly and its delivery.

lava_body() builds the LAVA-compatible callback body - the ONLY format the
pipeline's callback endpoint (kernelci.runtime.lava.Callback) ingests, so any
other would silently lose the result - and post_result() delivers it and says
what happened: "result posted" belongs to a real 2xx and nothing else.

Three behaviours are load-bearing and are not to be "improved": a definition
without a callback URL raises CallbackMissingURLError (a *transient* error) so
the caller keeps the result pending instead of logging "result posted" while
the result exists nowhere; 4xx is permanent, 5xx/network is retried 3 times and
then transient, so "not posted" can never look like "posted"; and the token
comes from the environment at post time - never a parameter here, never in the
body, never in the state file.

The verdicts are inputs, never re-derived here: *tap* is
(label, summary, per_test) and *error_msg* is the matching detail.  This module
never runs tuxrun, never parses TAP and never reads a job definition.
Rationale: docs/code-notes/W2c-kcilib.md.
"""

import os
import re
import time

import requests
import yaml

from kcilib.run.judge import (
    EXIT_INFRA,
    EXIT_PASS,
    EXIT_TEST_FAIL,
    LAVA_CASE_RE,
    VERDICT_FAIL,
    VERDICT_INFRA,
    VERDICT_PASS,
    strip_ansi,
)

# HTTP timeout for the callback POST; the same value the worker polls its APIs
# with.
REQUEST_TIMEOUT = 60
LOG_LIMIT = 2 << 20  # cap of log text embedded in a result body


LAVA_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

# The prefix of the suite case lava_body() files a kselftest run under
# ("0_kselftest.<suite>"): it marks the selftest verdict rather than a boot case.
SUITE_CASE_PREFIX = "0_kselftest."
# LAVA's status for a job whose result could not be produced; 2 is Complete.
LAVA_STATUS_INCOMPLETE = 3
LAVA_STATUS_COMPLETE = 2


def lava_body(
    system, returncode, output, run_config, tap=None, infra=False, error_msg=""
):
    """Build a LAVA-compatible callback body: the only format the pipeline's
    callback endpoint (kernelci.runtime.lava.Callback) ingests.

    Pieces, mirroring a real LAVA server callback: status (2=Complete,
    3=Incomplete); definition YAML carrying api_config_name/storage_config_name;
    results.lava with login-action and kernel-messages replayed from tuxrun's own
    LAVA lines (so boot results get the usual 'setup' hierarchy);
    results.<suite> keyed 0_kselftest.<collection>, which the parser turns into a
    suite node and flips to 'fail' when a test failed (tuxrun exits 0 even then);
    and log in LAVA output.yaml format - without it the endpoint forces
    'incomplete'.

    tap is (label, summary, per_test) from tap_summary(); *infra* marks an
    infrastructure error via the 'job' stage metadata (what
    Callback.is_infra_error() reads).  Only run_config's two config names are
    read; the body is a pure function of the verdicts.
    """
    status = 2 if returncode == 0 else 3
    if tap:
        # TAP available = the job DID complete; the per-test hierarchy drives
        # the result, so it stays Complete unless this is an infra error.
        status = 2 if not infra else 3
    cases = [{"name": "job", "metadata": {}}]
    boot_cases = []
    for raw in output.splitlines():
        line = strip_ansi(raw)
        match = LAVA_CASE_RE.search(line)
        if not match or match.group(1) not in (
            "login-action",
            "kernel-messages",
        ):
            continue
        cases.append(
            {
                "name": match.group(1),
                "result": match.group(2),
                "metadata": {},
            }
        )
        boot_cases.append(match.group(1))
    if infra:
        cases[0]["metadata"] = {
            "error_type": "Infrastructure",
            "error_msg": error_msg[-200:],
        }
    elif returncode != 0:
        last = next(
            (line for line in reversed(output.splitlines()) if line.strip()),
            "tuxrun failed",
        )
        cases[0]["metadata"] = {"error_type": "Job", "error_msg": last[-200:]}
    elif not tap and not boot_cases:
        # rc 0 with no boot case lines is not a real boot; never report a pass.
        status = 3
        cases[0]["metadata"] = {
            "error_type": "Job",
            "error_msg": "no login/kernel-messages cases in tuxrun log",
        }
    results = {}
    if tap:
        label, summary, per_test = tap
        suite = label[len("kselftest-") :]
        suite_key = f"0_kselftest.{suite}"
        cases.append(
            {
                "name": suite_key,
                "result": "fail" if summary["failed"] else "pass",
                "metadata": {},
            }
        )
        results[suite_key] = yaml.safe_dump(
            [
                {"name": name, "result": result, "metadata": {}}
                for name, result in per_test.items()
            ]
        )
    results["lava"] = yaml.safe_dump(cases)

    log_lines = []
    for raw in output[-LOG_LIMIT:].splitlines():
        line = strip_ansi(raw).rstrip()
        if not line.strip():
            continue
        match = LAVA_TS_RE.match(line)
        log_lines.append(
            {
                "dt": match.group(0) if match else "",
                "lvl": "target",
                "msg": line[match.end() :].lstrip() if match else line,
            }
        )

    definition = yaml.safe_dump(
        {
            "metadata": {
                "api_config_name": run_config.api_config_name,
                "storage_config_name": run_config.storage_config_name,
            },
        }
    )
    return {
        "definition": definition,
        "results": results,
        "status": status,
        "log": yaml.safe_dump(log_lines),
        "actual_device_id": system,
    }


# A report tuple is (callback_url, token, body).  The token is a "remote token"
# shared with the pipeline admins: read from the environment every time it is
# needed, and never persisted.
CALLBACK_TOKEN_ENV = "PULL_LABS_CALLBACK_TOKEN"


def _lava_cases(body):
    """The (name, result) pairs of a body's lava case list, never raising.

    The list is a YAML string inside the body - the format the pipeline's
    callback parses - so it is read back the same way.  An unreadable body
    yields no cases: reading a verdict must not break a run that already
    finished.
    """
    raw = (body.get("results") or {}).get("lava") or ""
    try:
        cases = yaml.safe_load(raw)
    except yaml.YAMLError:
        return []
    if not isinstance(cases, list):
        return []
    return [
        (str(case.get("name") or ""), str(case.get("result") or ""))
        for case in cases
        if isinstance(case, dict)
    ]


def verdict_from_body(body):
    """The ledger's (verdict, exit_code, detail) for a body lava_body() built.

    Read back OUT OF the body on purpose: the body is what upstream received, so
    the record cannot disagree with the pipeline.  Computing the verdict a second
    time from the console (judge_run(), the one-shot path's route) would be a
    second opinion about the same run - "the ledger says pass and the pipeline
    says fail" is the confusion a durable record exists to remove.

    status 3 is LAVA's Incomplete (infrastructure), 2 is Complete.  A Complete
    job is not automatically a pass: tuxrun exits 0 even when every selftest
    fails, so the suite case carries the verdict.
    """
    status = body.get("status")
    error = _job_case_metadata(body)
    if status != LAVA_STATUS_COMPLETE:
        detail = error.get("error_msg") or ""
        if not detail:
            detail = f"lava status {status} (incomplete)"
        return VERDICT_INFRA, EXIT_INFRA, detail
    for name, result in _lava_cases(body):
        if result != "fail":
            continue
        if name.startswith(SUITE_CASE_PREFIX) or name in (
            "login-action",
            "kernel-messages",
        ):
            return VERDICT_FAIL, EXIT_TEST_FAIL, f"{name}: fail"
    return VERDICT_PASS, EXIT_PASS, error.get("error_msg") or ""


def _job_case_metadata(body):
    """The metadata of the body's 'job' case, or {} when it has none.

    Where an infrastructure failure names itself (error_type Infrastructure).
    """
    for case in _lava_case_dicts(body):
        if case.get("name") == "job":
            metadata = case.get("metadata")
            return metadata if isinstance(metadata, dict) else {}
    return {}


def _lava_case_dicts(body):
    """The body's lava cases as dicts (the shape _lava_cases() flattens)."""
    raw = (body.get("results") or {}).get("lava") or ""
    try:
        cases = yaml.safe_load(raw)
    except yaml.YAMLError:
        return []
    if not isinstance(cases, list):
        return []
    return [case for case in cases if isinstance(case, dict)]

def callback_url(job):
    """The callback URL a pull-labs job definition records, or None."""
    return job.get("callback", {}).get("url")


def callback_token():
    """The callback token, from the environment (never from a file)."""
    return os.environ.get(CALLBACK_TOKEN_ENV)


def pending_entry(report):
    """The persistable half of a (callback_url, token, body) report tuple.

    The token is dropped on purpose: the state file holds the URL and the body
    only, and the token is re-read from the environment on the next post."""
    return {"callback": report[0], "body": report[2]}


def report_from_pending(pending):
    """Rebuild the (callback_url, token, body) tuple to re-post.

    A pending entry holds no token, so the token comes from the environment here
    exactly as it did for the original post."""
    return pending["callback"], callback_token(), pending["body"]


class CallbackPermanentError(Exception):
    """The callback endpoint rejected the result (4xx): retrying is pointless."""


class CallbackTransientError(Exception):
    """Network/5xx trouble posting the result: retry later."""


class CallbackMissingURLError(CallbackTransientError):
    """The job definition carries no callback URL: there is nowhere to post.

    Deliberately transient rather than a give-up: the run already happened and
    its result is the only copy, so the caller keeps it pending and does not mark
    the node seen - an operator who fixes the definition then gets it posted
    instead of losing it.  Returning normally logged "result posted" while the
    result existed nowhere."""


def post_result(callback, token, body):
    """Post a result body to the recorded callback endpoint, retrying a few
    times - a single network blip must not lose a result.

    Raises CallbackPermanentError / CallbackTransientError instead of returning
    quietly, so a caller can never mistake "not posted" for "posted"."""
    if not callback:
        raise CallbackMissingURLError(
            "no callback URL in the job definition; result NOT reported, "
            "kept pending"
        )
    headers = {}
    if token:
        headers["Authorization"] = f"Token {token}"
    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(
                callback,
                json=body,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
            print(f"Callback status: {response.status_code}")
            if response.is_redirect or response.is_permanent_redirect:
                # Never follow a redirect with the shared token attached.
                raise CallbackPermanentError(
                    f"callback redirected ({response.status_code})"
                )
            if response.status_code < 400:
                return
            if response.status_code < 500:
                raise CallbackPermanentError(
                    f"callback returned {response.status_code}"
                )
            last_error = requests.exceptions.HTTPError(
                f"callback returned {response.status_code}"
            )
            print(f"Callback attempt {attempt + 1}/3 failed: {last_error}")
            time.sleep(2 * (attempt + 1))
        except CallbackPermanentError:
            raise
        except requests.exceptions.RequestException as error:
            last_error = error
            print(f"Callback attempt {attempt + 1}/3 failed: {error}")
            time.sleep(2 * (attempt + 1))
    raise CallbackTransientError(str(last_error))
