# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The result report: LAVA-compatible body assembly and its delivery.

A finished pull-lab job has exactly one durable output - the callback POST -
so the two halves of it live here rather than in each entry point:

* ``lava_body()`` assembles the **LAVA-compatible callback body**, the only
  format the pipeline's callback endpoint (lava_callback.py +
  kernelci.runtime.lava.Callback) ingests; there is no server-side parser for
  the PULL_LABS protocol body, so any other format would silently lose the
  result;
* ``post_result()`` delivers it and, crucially, *says what happened*: the
  "result posted" line belongs to a real 2xx and nothing else.

Both were moved out of scripts/riscv_pull_worker.py unchanged: the bodies, the
comments and the printed lines are byte-for-byte the same, and nothing had to
be renamed to become module-level.  The worker keeps its own policy - the poll
loop, the job mapping, the baked guest cache, the console archive and the
re-post-from-state rule.

Three behaviours are load-bearing and are not to be "improved":

* a job definition without a callback URL raises ``CallbackMissingURLError``
  (a subclass of the *transient* error) instead of returning quietly, so the
  caller keeps the result pending rather than logging "result posted" while the
  result exists nowhere (#3);
* a 4xx is permanent, a 5xx/network error is retried (3 attempts) and then
  transient; both raise, so "not posted" can never look like "posted";
* the callback token comes from the environment at post time.  It is never a
  parameter of ``lava_body()``, never a field of the body, and never written to
  the state file - ``pending_entry()``/``report_from_pending()`` below are the
  round trip that keeps it that way (see kcilib.state.StateFile).

The judged verdicts are *inputs*, never re-derived here: ``tap`` is
``(label, summary, per_test)`` - the ``summary`` and ``per_test`` halves of the
5-tuple ``kcilib.judge.judge_run()`` returns, paired with the test label exactly
as the worker's ``run_job()`` builds it - and ``error_msg`` is the ``detail`` that
goes with them.  This module never runs tuxrun, never parses TAP and never
reads a job definition.
"""

import os
import re
import time

import requests
import yaml

from kcilib.judge import LAVA_CASE_RE, strip_ansi

# HTTP timeout for the callback POST; the same value the worker polls its APIs
# with.
REQUEST_TIMEOUT = 60
LOG_LIMIT = 2 << 20  # cap of log text embedded in a result body


LAVA_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def lava_body(
    system, returncode, output, args, tap=None, infra=False, error_msg=""
):
    """Build a LAVA-compatible callback body: the only format the pipeline's
    callback endpoint (kernelci.runtime.lava.Callback) ingests.

    Required pieces, mirroring a real LAVA server callback:
      - status: LAVA numeric job status (2=Complete, 3=Incomplete)
      - definition: YAML whose metadata carries api_config_name /
        storage_config_name (what get_meta() reads)
      - results.lava: case/stage list; login-action and kernel-messages are
        replayed from tuxrun's own LAVA lines so boot results get the usual
        'setup' hierarchy
      - results.<suite>: per-test entries keyed 0_kselftest.<collection>;
        the parser builds a suite node whose children are the tests and
        flips the job to 'fail' when any failed (tuxrun exits 0 even then)
      - log: LAVA output.yaml format (list of {dt, lvl, msg}); without it
        the endpoint forces 'incomplete'

    tap is (label, summary, per_test) from tap_summary().  infra marks an
    infrastructure error via the 'job' stage metadata (what
    Callback.is_infra_error() reads).
    """
    status = 2 if returncode == 0 else 3
    if tap:
        # TAP available = the job DID complete (tuxrun exits 0/1/2 by LKFT
        # result plumbing); the per-test hierarchy drives the final result,
        # so the job stays Complete unless this is an infra error.
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
        # rc 0 without any boot case lines means the log does not show a
        # real boot; never report that as pass.
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
                "api_config_name": args.api_config_name,
                "storage_config_name": args.storage_config_name,
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


# The report tuple a caller posts is (callback_url, token, body); these are the
# two expressions the worker resolves it from - the callback URL recorded in the
# job definition (run_job's job.get("callback", {}) / callback.get("url")) and
# the token, which is read from the environment every time it is needed because
# it is a "remote token" name shared with the pipeline admins and is never
# persisted.
CALLBACK_TOKEN_ENV = "PULL_LABS_CALLBACK_TOKEN"


def callback_url(job):
    """The callback URL a pull-labs job definition records, or None."""
    return job.get("callback", {}).get("url")


def callback_token():
    """The callback token, from the environment (never from a file)."""
    return os.environ.get(CALLBACK_TOKEN_ENV)


def callback_target(job):
    """The (callback_url, token) pair that heads a report tuple."""
    return callback_url(job), callback_token()


def pending_entry(report):
    """The persistable half of a (callback_url, token, body) report tuple.

    The token is dropped on purpose: the state file holds the callback URL and
    the body only, and the token is re-read from the environment when the body
    is posted again (report_from_pending)."""
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

    Deliberately treated as transient rather than as a give-up.  The run has
    already happened and its result is the only copy, so the caller keeps it in
    the persisted pending set and does not mark the node seen; an operator who
    fixes the job definition (or the deployment's callback) then gets the
    result posted instead of losing it.  The old code printed a warning and
    returned normally, so the caller went on to log "result posted to the
    callback" while the job stayed available forever and the result existed
    nowhere (#3)."""


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
