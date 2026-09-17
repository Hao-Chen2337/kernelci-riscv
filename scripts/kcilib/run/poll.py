#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The poll loop: events API -> handle_event -> run_node -> post the result.

THIS IS THE ONLY LAYER ON THE RUN PATH THAT TALKS TO THE EVENTS API; running one
is not its business, and neither is state.  The loop is handed the run function
and its config (kcilib.run.jobrun.run_node and a kcilib.core.config.PollConfig),
so it can run a node without importing the run path - which is also what makes
the run path testable: a test injects a stub run_node rather than patching an
import.

StateFile owns the state file (cursor, seen set, pending reports: one document,
written atomically after EVERY event); callback owns the post and the pending
round trip; bake.stamp owns the progress lines.  "Result posted" is printed only
after post_result() returned without raising, i.e. after a real 2xx, and the
cursor advances only once a whole batch succeeded - --since seeds a state file
that has no cursor, --ignore-state-cursor forces it.  The token is never
persisted.  Nothing here reads a command line.
Rationale: docs/docs/code-notes/W2c-kcilib.md.
"""

import signal
import time
from datetime import datetime, timedelta

import requests

from kcilib.core.state import StateFile
from kcilib.run.bake import stamp
from kcilib.run.callback import (
    CallbackPermanentError,
    CallbackTransientError,
    pending_entry,
    post_result,
    report_from_pending,
)

EVENTS_PATH = "/events"
REQUEST_TIMEOUT = 60
CURSOR_OVERLAP_S = 900  # re-scan window: the events API is not sorted


def _latest_base(api_url):
    """The canonical /latest base (production serves only that form)."""
    return api_url if api_url.endswith("/latest") else f"{api_url}/latest"


def fetch_nodes(api_url, timestamp):
    """Fetch the available job nodes (the events API call, and nothing else)."""
    url = (
        f"{_latest_base(api_url)}{EVENTS_PATH}?state=available&kind=job&limit=1000"
        f"&recursive=true&from={timestamp}"
    )
    print(url)
    response = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as error:
        raise requests.exceptions.RequestException(
            f"Invalid JSON from events API: {error}"
        ) from error


def retrieve_job_definition(url):
    print(f"Retrieving job definition from: {url}")
    response = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
    if response.is_redirect or response.is_permanent_redirect:
        raise requests.exceptions.RequestException(
            f"refusing redirect for {url}"
        )
    response.raise_for_status()
    # Same rule as the node API: a non-JSON body or a wrong-shaped one is a
    # transient fetch error, so the node is retried rather than given up on.
    try:
        job = response.json()
    except ValueError as error:
        raise requests.exceptions.RequestException(
            f"non-JSON body from the job definition URL "
            f"(HTTP {response.status_code}): {error}"
        ) from error
    if not isinstance(job, dict):
        raise requests.exceptions.RequestException(
            f"job definition at {url} is {type(job).__name__}, not an object"
        )
    return job


def handle_event(event, poll_config, run_config, reports, run_node):
    """Process one job event.

    A node that already produced a report is retried by re-posting that report
    only - tuxrun is never re-run for the same node.  Returns True when the
    event is fully handled (or deliberately given up on) so the caller may mark
    it seen; *run_node* is the run function the loop was handed - this layer
    knows the API, that one knows tuxrun, and neither imports the other."""
    node = event.get("node", {})
    node_id = node.get("id", "unknown")
    node_artifacts = node.get("artifacts", {})

    # The events stream returns historical snapshots: only act on jobs that are
    # still available NOW, so a fresh worker never replays yesterday's queue.
    try:
        response = requests.get(
            f"{_latest_base(poll_config.api_url)}/node/{node_id}", timeout=30
        )
        # A proxy's HTML error page is not JSON: make it an ordinary API error
        # (log, skip this event, retry next poll) instead of a ValueError that
        # kills the whole worker.
        response.raise_for_status()
        try:
            current = response.json()
        except ValueError as error:
            raise requests.exceptions.RequestException(
                f"non-JSON body from the node API "
                f"(HTTP {response.status_code}): {error}"
            ) from error
    except requests.exceptions.RequestException as error:
        print(f"{node_id}: node state check failed: {error}")
        return False
    if not isinstance(current, dict):
        # Wrong-shaped JSON must not become an AttributeError that kills the loop.
        print(f"{node_id}: node state check returned {type(current).__name__}, "
              "not a node object")
        return False
    if current.get("state") != "available":
        return True
    job_definition_url = node_artifacts.get("job_definition", "")
    if not job_definition_url or not job_definition_url.startswith("http"):
        return True  # not a pull_labs job; nothing to do

    data = event.get("data", {}).get("data", {})
    platform = data.get("platform")
    runtime = data.get("runtime")
    if poll_config.platform and platform != poll_config.platform:
        return True
    if poll_config.runtime and runtime != poll_config.runtime:
        return True

    stamp(
        f"Processing job {node_id} (platform: {platform}, runtime: {runtime})"
    )

    cached = reports.get(node_id)
    if cached:
        callback_url, callback_token, body = cached
        try:
            post_result(callback_url, callback_token, body)
            del reports[node_id]
            print(f"{node_id}: cached result posted on retry")
            return True
        except CallbackPermanentError as error:
            del reports[node_id]
            print(
                f"{node_id}: permanent callback failure ({error}); "
                "giving up on this node"
            )
            return True
        except CallbackTransientError as error:
            print(f"{node_id}: cached result not posted yet: {error}")
            return False

    try:
        job = retrieve_job_definition(job_definition_url)
        report = run_node(job, run_config, node_id)
    except requests.exceptions.RequestException as error:
        status_code = getattr(
            getattr(error, "response", None), "status_code", None
        )
        if status_code is not None and status_code < 500:
            print(
                f"{node_id}: job definition fetch failed with "
                f"{status_code} ({error}); giving up on this node"
            )
            return True
        print(f"{node_id}: transient job definition fetch error: {error}")
        return False
    except Exception as error:  # noqa: BLE001 - run_node converts its own failures; give up on the rest
        import traceback

        print(f"Unexpected failure processing {node_id}: {error}")
        traceback.print_exc()
        return True  # run_node converts its own failures; give up on the rest

    callback_url, callback_token, body = report
    try:
        post_result(callback_url, callback_token, body)
        stamp(f"{node_id}: result posted to the callback")
        return True
    except CallbackPermanentError as error:
        print(
            f"{node_id}: permanent callback failure ({error}); "
            "giving up on this node"
        )
        return True
    except CallbackTransientError as error:
        reports[node_id] = report
        print(
            f"{node_id}: result not posted yet ({error}); "
            "re-posting next poll (no re-run)"
        )
        return False


def iso_ago(timestamp, seconds):
    """*timestamp* minus *seconds*, as an ISO-8601 string."""
    return (
        datetime.fromisoformat(timestamp) - timedelta(seconds=seconds)
    ).isoformat()


def _parseable_iso(value):
    """True for a timestamp string iso_ago() and the events API can consume.

    A hand-edited state file would otherwise raise ValueError inside iso_ago and
    kill the worker at startup, far from the file that caused it."""
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def start_cursor(state_timestamp, since, ignore_state_cursor):
    """The timestamp the first poll scans from, and say which one it is.

    The persisted cursor is authoritative; --since only seeds a state file that
    has none.  --since used to win, so a worker started the next day never
    looked back at a job that arrived yesterday and is still available - it sat
    in the queue forever, with no error anywhere."""
    stored = state_timestamp if _parseable_iso(state_timestamp) else None
    if state_timestamp and stored is None:
        print(f"Warning: state file cursor {state_timestamp!r} is not an "
              "ISO-8601 timestamp; ignoring it")
    if ignore_state_cursor:
        if since:
            print(f"Poll cursor: {since} (--since, forced by "
                  f"--ignore-state-cursor; the persisted cursor "
                  f"{stored or '<none>'} is overridden)")
            return since
        print("Warning: --ignore-state-cursor given without --since; "
              "falling back to the persisted cursor")
    if stored:
        if since:
            print(f"Poll cursor: {stored} (persisted in the state file); "
                  f"--since {since} is ignored - pass --ignore-state-cursor "
                  "to use it instead")
        else:
            print(f"Poll cursor: {stored} (persisted in the state file)")
        return stored
    if since and not _parseable_iso(since):
        print(f"Warning: --since {since!r} is not an ISO-8601 timestamp; "
              "ignoring it")
        since = None
    if since:
        print(f"Poll cursor: {since} (--since; the state file has no cursor "
              "yet)")
        return since
    print("Poll cursor: 1970-01-01T00:00:00.000000 (no cursor in the state "
          "file and no --since: scanning the whole available queue)")
    return "1970-01-01T00:00:00.000000"


def poll_loop(poll_config, run_node, run_config):
    """Poll the API forever (or once) and run every node this worker claims.

    *poll_config* is a kcilib.core.config.PollConfig, so the loop is driven by a
    value rather than by whatever the process parsed.  *run_node* and
    *run_config* are passed through to handle_event(); the loop never runs a job
    itself."""
    import fcntl

    state_file = poll_config.state_file
    lock_file = f"{state_file}.lock"
    lock = None
    try:
        lock = open(lock_file, "w")  # noqa: SIM115 - must stay open for the whole poll loop (flock lifetime)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another worker instance holds the lock; exiting.")
        raise SystemExit(1)

    state = StateFile(state_file).load()
    # start_cursor() decides which cursor wins and says so on stdout: the
    # operator needs that before reading anything else.
    print(f"State file: {state_file}", flush=True)
    timestamp = start_cursor(state.cursor, poll_config.since,
                             poll_config.ignore_state_cursor)
    # Unposted results from a previous run (--once exiting on a transient
    # callback failure): re-post them without re-running tuxrun.  The token is
    # re-read from the environment and never persisted.
    reports = {}
    for node_id, pending in state.pending.items():
        if isinstance(pending, dict) and pending.get("callback") and pending.get("body"):
            # kcilib.run.callback owns this round trip: the stored entry holds
            # the URL and body but never the token, which comes from the env.
            reports[node_id] = report_from_pending(pending)

    def flush():
        """Write the cursor and the unposted reports out now.

        Called after EVERY event, not once per batch: a worker killed after a
        transient callback failure used to lose the report and re-run tuxrun for
        a node whose result it already had.  StateFile.save() owns the
        re-entrancy and unchanged-document guards that make this cheap."""
        state.cursor = timestamp
        # The persistable half of a report tuple: url and body, never the token.
        state.pending = {
            node_id: pending_entry(report)
            for node_id, report in reports.items()
        }
        state.save()

    def flush_and_exit(signum, _frame):
        """A SIGTERM/SIGINT must not cost the results already collected."""
        print(f"Received signal {signum}: flushing state, then exiting.",
              flush=True)
        flush()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, flush_and_exit)
    signal.signal(signal.SIGINT, flush_and_exit)
    retry_count = 0
    while True:
        # The events API is not sorted, so re-scan a trailing window and dedup
        # via `seen`; a cursor that only advances would skip late events.
        try:
            events = fetch_nodes(
                poll_config.api_url, iso_ago(timestamp, CURSOR_OVERLAP_S)
            )
            retry_count = 0
        except requests.exceptions.RequestException as error:
            retry_count += 1
            print(
                f"Error fetching events (attempt {retry_count}/"
                f"{poll_config.max_retries}): {error}"
            )
            if retry_count >= poll_config.max_retries:
                print(f"Max retries ({poll_config.max_retries}) reached. "
                      "Exiting.")
                raise SystemExit(1)
            print(f"Retrying in {poll_config.poll_period} seconds...")
            time.sleep(poll_config.poll_period)
            continue
        if not events:
            print(
                f"No new events, sleeping for {poll_config.poll_period} "
                "seconds",
                flush=True,
            )
            time.sleep(poll_config.poll_period)
            continue

        print(f"Got {len(events)} events", flush=True)
        # The cursor advances only when the whole batch succeeded.
        all_ok = True
        processed = 0
        for event in events:
            node_id = event.get("node", {}).get("id") or "unknown"
            if state.has_seen(node_id):
                continue
            handled = False
            try:
                handled = handle_event(event, poll_config, run_config,
                                       reports, run_node)
                if handled and node_id and event.get("node", {}).get(
                    "artifacts", {}
                ).get("job_definition"):
                    # Only remember nodes that were actually processed: the
                    # first event may arrive before job_definition is attached,
                    # and marking that seen would hide the later, complete one.
                    state.mark_seen(node_id)
                    processed += 1
            finally:
                # One flush per event, in a `finally` so it runs for an event
                # that raised too: whatever handle_event() changed survives.
                flush()
            if not handled:
                all_ok = False
        if all_ok:
            timestamp = max(
                (e.get("timestamp") or timestamp for e in events),
                default=timestamp,
            )
        else:
            print(
                "Some events failed; cursor not advanced, will retry next poll",
                flush=True,
            )
            # Never busy-loop on a failing batch: the API needs a breather and
            # the failure is usually environmental (404 jobdef, network).
            time.sleep(poll_config.poll_period)
        # Persists the cursor advanced above; seen/pending were flushed per event.
        flush()
        if poll_config.once:
            print(
                f"--once: batch processed ({processed} node(s) run); the "
                f"cursor ({timestamp}) and any unposted result are in "
                f"{state_file} - exiting",
                flush=True,
            )
            break
