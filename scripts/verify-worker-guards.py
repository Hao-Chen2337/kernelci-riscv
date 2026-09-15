#!/usr/bin/env python3
"""Adversarial guard tests for riscv_pull_worker.py.

Covers the review findings that are testable offline: ANSI stripping,
TAP edge cases, infra detection, log capping, test-type validation, and -
since round 3 - the state machine the worker runs on: the state file and the
cursor it stores, how a result is classified when the callback is missing,
unreachable or refusing, the resume/416 download path, the console-log archive
and the timeout clamp.  Those are the paths where a bug loses a result or
wedges an artifact, and none of them had a test.
Run from anywhere:

    python3 scripts/verify-worker-guards.py
"""
import argparse as _ap
import importlib.util
import json
import os
import sys
import tempfile
import time as _time
from contextlib import contextmanager

import requests as _real_requests

spec = importlib.util.spec_from_file_location(
    "worker",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "riscv_pull_worker.py"))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def check(condition, message):
    """A guard that also holds under `python3 -O` / PYTHONOPTIMIZE=1.

    These checks used to be `assert` statements.  run.sh fails the `verify`
    gate on a non-zero exit, but -O strips every assert, so a broken check
    printed "ALL GUARD CHECKS PASSED" and exited 0: the gate reported success
    precisely when it had verified nothing.
    """
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def test_strip_ansi():
    check(w.strip_ansi("\x1b[0;32mok 1\x1b[0m") == "ok 1",
          "SGR colour codes not stripped")
    check(w.strip_ansi("\x1b]0;title\x07plain") == "plain",      # OSC BEL
          "OSC BEL sequence not stripped")
    check(w.strip_ansi("\x1b]8;;http://x\x1b\\text") == "text",  # OSC ST
          "OSC ST sequence not stripped")
    check(w.strip_ansi("\x1b[2Jclear") == "clear",               # CSI letter
          "CSI letter-final sequence not stripped")
    check(w.strip_ansi("plain text 100%") == "plain text 100%",
          "plain text was mangled")
    print("test_strip_ansi OK")


def test_tap_summary():
    # CRLF + ANSI + timestamp prefixes
    out = (
        "\x1b[0;90m2026-09-08T09:39:07\x1b[0m \x1b[0;32mok 1 selftests: kvm: a\x1b[0m\r\n"
        "2026-09-08T09:39:08 not ok 2 selftests: kvm: b # TIMEOUT 120 seconds\r\n"
        "2026-09-08T09:39:09 ok 3 selftests: kvm: c # SKIP\r\n"
    )
    summary, tests_out, per = w.tap_summary(out, "kselftest-kvm")
    check(summary == {"total": 3, "failed": 1, "skipped": 1}, summary)
    check(per == {"a": "pass", "b": "fail", "c": "skip"}, per)
    check(tests_out["kselftest-kvm"]["status"] == "fail", tests_out)

    # "not ok" must not be double-counted as ok (the old bug)
    summary2, _, per2 = w.tap_summary(
        "2026-09-08T00:00:00 ok 1 selftests: riscv: x\n"
        "2026-09-08T00:00:00 not ok 2 selftests: riscv: y\n",
        "kselftest-riscv")
    check(summary2 == {"total": 2, "failed": 1, "skipped": 0}, summary2)
    check(per2 == {"x": "pass", "y": "fail"}, per2)

    # started but never finished -> fail
    summary3, _, per3 = w.tap_summary(
        "2026-09-08T00:00:00 # selftests: kvm: ghost\n"
        "2026-09-08T00:00:00 ok 1 selftests: kvm: real\n",
        "kselftest-kvm")
    check(summary3["failed"] == 1 and per3["ghost"] == "fail", (summary3, per3))

    # all-skip: still has results (visible skips), suite passes
    summary4, _, per4 = w.tap_summary(
        "2026-09-08T00:00:00 ok 1 selftests: kvm: s1 # SKIP\n", "kselftest-kvm")
    check(summary4 == {"total": 1, "failed": 0, "skipped": 1}, summary4)
    check(per4 == {"s1": "skip"}, per4)

    # malformed/glued/uppercase failures must still be detected
    # (round 2: these used to be false greens)
    weird = ("  not  ok 1 selftests: kvm: a\n"
             "NOT OK 2 selftests: kvm: b\n"
             "not\tok 3 selftests: kvm: c\n"
             "not\x1b[31mok 4 selftests: kvm: d\n"
             "notok 5 selftests: kvm: e\n")
    sw, _, pw = w.tap_summary(weird, "kselftest-kvm")
    check(sw["failed"] == 5, (sw, pw))
    check(pw == {"a": "fail", "b": "fail", "c": "fail",
                 "d": "fail", "e": "fail"}, pw)

    # garbage: no TAP -> fail, never pass
    summary5, tests5, per5 = w.tap_summary("nothing relevant here\n", "kselftest-kvm")
    check(summary5["failed"] == 1 and tests5["kselftest-kvm"]["status"] == "fail",
          (summary5, tests5))
    check(per5 == {}, per5)
    print("test_tap_summary OK")


def test_job_error():
    check(w.tuxrun_job_error(
        2, "2026-09-08T00:00:00 JobError: Your job cannot terminate cleanly."),
        "JobError in the log must be detected")
    # a test whose NAME mentions JobError must not be misclassified
    check(not w.tuxrun_job_error(
        0, "ok 1 selftests: kvm: job_error_checker_test\n"),
        "a test NAME containing job_error must not be read as a JobError")
    # authoritative: LAVA self-reported Infrastructure on the job case
    check(w.tuxrun_infra_error(
        1, "2026-09-08T00:00:00 {'definition': 'lava', 'case': 'job', "
           "'result': 'fail', 'error_msg': 'Connection closed', "
           "'error_type': 'Infrastructure'}"),
        "LAVA's own Infrastructure job result must be detected")
    check(not w.tuxrun_infra_error(
        0, "2026-09-08T00:00:00 {'case': 'job', 'result': 'pass'}"),
        "a passing job case must not be read as Infrastructure")
    print("test_job_error OK")


def test_lava_body_cap_and_boot_guard():
    import argparse as _ap
    args = _ap.Namespace(api_config_name="docker-host",
                         storage_config_name="docker-host")
    big = "2026-09-08T00:00:00 filler line\n" * (w.LOG_LIMIT // 20 + 1000)
    body = w.lava_body("qemu-riscv64", 0, big, args)
    import yaml as _yaml
    log_lines = _yaml.safe_load(body["log"])
    total = sum(len(ln.get("msg", "")) for ln in log_lines)
    check(total <= w.LOG_LIMIT + (1 << 16), f"log too big: {total}")
    # rc 0 without any boot case -> incomplete, not a fake pass
    check(body["status"] == 3, body["status"])
    print("test_lava_body_cap_and_boot_guard OK")


def test_build_command_validation():
    import argparse as _ap
    args = _ap.Namespace(tuxrun_bin="tuxrun", platform="qemu-riscv64",
                         rootfs="", cpu="rv64,v=true", container_runtime="",
                         kvm_tests=w.KVM_TEST_SUBSET,
                         max_download_size=w.MAX_DOWNLOAD_SIZE)
    job = {"artifacts": {"kernel": "http://x/Image"},
           "tests": [{"type": "kselftest-kvm; rm -rf /"}]}
    try:
        w.build_command(job, args, "/tmp/fake")
        raise AssertionError("invalid test type must be rejected")
    except KeyError as e:
        check("invalid test type" in str(e), e)
    print("test_build_command_validation OK")


def test_iso_ago():
    ts = w.iso_ago("2026-09-08T12:00:00.000000", 900)
    check(ts == "2026-09-08T11:45:00", ts)
    print("test_iso_ago OK")


# --- the risky half: state, cursor, callback classification, downloads -------


class _Response:
    """Minimal stand-in for a requests response (see stub_requests)."""

    def __init__(self, status_code=200, headers=None, chunks=(),
                 json_body=None, json_error=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.is_redirect = status_code in (301, 302, 303, 307, 308)
        self.is_permanent_redirect = status_code in (301, 308)
        self._chunks = list(chunks)
        self._json_body = json_body
        self._json_error = json_error

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise w.requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1 << 20):
        yield from self._chunks

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_body


class _RequestsStub:
    """Replaces worker.requests: get/post are stubbed, the exception classes
    stay the real ones so the worker's except clauses still match."""

    def __init__(self, get=None, post=None):
        self.exceptions = _real_requests.exceptions
        self._get = get
        self._post = post

    def get(self, url, **kwargs):
        if self._get is None:
            raise AssertionError(f"unexpected GET {url}")
        return self._get(url, **kwargs)

    def post(self, url, **kwargs):
        if self._post is None:
            raise AssertionError(f"unexpected POST {url}")
        return self._post(url, **kwargs)


@contextmanager
def stub_requests(get=None, post=None):
    real = w.requests
    w.requests = _RequestsStub(get, post)
    try:
        yield
    finally:
        w.requests = real


@contextmanager
def no_sleep():
    """The worker retries with time.sleep; a test must not wait for it."""
    real = _time.sleep
    _time.sleep = lambda _seconds: None
    try:
        yield
    finally:
        _time.sleep = real


def test_post_result_classification():
    """#3: a result that was not posted must never look posted."""
    check(issubclass(w.CallbackMissingURLError, w.CallbackTransientError),
          "a missing callback URL must take the transient path (keep the "
          "result, retry) - the permanent path gives up and marks the node "
          "seen")
    with no_sleep(), stub_requests():     # no HTTP call may happen at all
        try:
            w.post_result("", "tok", {"status": 2})
            check(False, "post_result with no callback URL returned normally "
                         "(the caller then logs 'result posted')")
        except w.CallbackMissingURLError as error:
            check("pending" in str(error), error)
        except Exception as error:  # noqa: BLE001 - the point of the test
            check(False, f"missing callback URL raised {error!r}")

    status = {"code": 200}
    with no_sleep(), stub_requests(post=lambda url, **kw: _Response(status["code"])):
        w.post_result("http://cb", "tok", {"status": 2})
        w.post_result("http://cb", "tok", {"status": 2})
        status["code"] = 403
        try:
            w.post_result("http://cb", "tok", {"status": 2})
            check(False, "a 4xx from the callback must raise (it used to be "
                         "reported as posted)")
        except w.CallbackPermanentError:
            pass
        status["code"] = 503
        try:
            w.post_result("http://cb", "tok", {"status": 2})
            check(False, "a 5xx from the callback must raise after the retries")
        except w.CallbackTransientError:
            pass
    print("test_post_result_classification OK")


def test_download_complete_part_and_416():
    """#7: a complete .part is published, a bogus one is not trusted."""
    with tempfile.TemporaryDirectory() as tmp:
        url = "http://storage/Image"
        dest = os.path.join(tmp, "Image")
        part = f"{dest}.part"
        meta = f"{dest}.part.json"

        # (a) full-size .part + matching sidecar: publish, no HTTP request
        with open(part, "wb") as handle:
            handle.write(b"x" * 1000)
        with open(meta, "w") as handle:
            json.dump({"url": url, "total": 1000}, handle)
        with stub_requests():   # any GET raises AssertionError
            w.download(url, dest, max_size=1 << 20)
        check(os.path.getsize(dest) == 1000, "complete .part was not published")
        check(not os.path.exists(part), ".part left behind after publishing")
        check(not os.path.exists(meta), "sidecar left behind after publishing")

        # (b) a 416 whose Content-Range total equals the offset: the server
        # itself confirms the partial file was the whole artifact
        os.unlink(dest)
        with open(part, "wb") as handle:
            handle.write(b"y" * 500)
        with open(meta, "w") as handle:
            json.dump({"url": url, "total": 1000}, handle)
        ranges = []

        def get_416(_url, **kwargs):
            ranges.append(kwargs.get("headers", {}).get("Range"))
            return _Response(416, headers={"Content-Range": "bytes */500"})

        with no_sleep(), stub_requests(get=get_416):
            w.download(url, dest, max_size=1 << 20)
        check(os.path.getsize(dest) == 500, "a 416 = complete was not published")
        check(ranges == ["bytes=500-"], ranges)

        # (c) a 416 that does not match: the partial is dropped and the
        # transfer restarts from zero instead of wedging the artifact
        os.unlink(dest)
        with open(part, "wb") as handle:
            handle.write(b"z" * 10)
        with open(meta, "w") as handle:
            json.dump({"url": url, "total": 1000}, handle)
        seen = []

        def get_restart(_url, **kwargs):
            seen.append(kwargs.get("headers", {}).get("Range"))
            if len(seen) == 1:
                return _Response(416, headers={"Content-Range": "bytes */1000"})
            return _Response(200, headers={"Content-Length": "1000"},
                             chunks=[b"a" * 1000])

        with no_sleep(), stub_requests(get=get_restart):
            w.download(url, dest, max_size=1 << 20)
        check(seen[0] == "bytes=10-", seen)
        check(seen[1] is None, f"the restart still resumed: {seen}")
        check(os.path.getsize(dest) == 1000, "restart did not fetch the file")

        # a sidecar for another URL must never be used to publish
        with open(part, "wb") as handle:
            handle.write(b"w" * 20)
        with open(meta, "w") as handle:
            json.dump({"url": "http://other/Image", "total": 20}, handle)
        check(w._publish_complete_part(part, meta, dest, url, 1 << 20) == 0,
              "a sidecar naming another URL must not publish the .part")
    print("test_download_complete_part_and_416 OK")


def test_state_roundtrip():
    """load_state/save_state: what the pending set survives on."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "state.json")
        empty = w.load_state(path)
        check(empty == {"timestamp": None, "seen": [], "pending": {}}, empty)
        state = {
            "timestamp": "2026-09-08T00:00:00.000000",
            "seen": ["a" * 24],
            "pending": {"b" * 24: {"callback": "http://cb",
                                   "body": {"status": 2}}},
        }
        w.save_state(path, state)
        check(w.load_state(path) == state, "state did not survive a round trip")
        with open(path, "w") as handle:
            handle.write("{ not json")
        check(w.load_state(path)["timestamp"] is None,
              "a corrupt state file must be refused, not trusted")
        with open(path, "w") as handle:
            json.dump({"seen": "not-a-list"}, handle)
        check(w.load_state(path)["seen"] == [],
              "a state file of the wrong shape must be refused")
    print("test_state_roundtrip OK")


def test_start_cursor():
    """#8: the persisted cursor is authoritative, --since is a bootstrap."""
    stored = "2026-09-08T00:00:00.000000"
    since = "2020-01-01T00:00:00"
    check(w.start_cursor(stored, since, False) == stored,
          "the persisted cursor must win over --since")
    check(w.start_cursor(stored, since, True) == since,
          "--ignore-state-cursor must force --since")
    check(w.start_cursor(stored, None, True) == stored,
          "--ignore-state-cursor without --since must fall back to the cursor")
    check(w.start_cursor(None, since, False) == since,
          "--since seeds a state file that has no cursor")
    check(w.start_cursor(None, None, False) == "1970-01-01T00:00:00.000000",
          "no cursor anywhere must scan the whole available queue")
    check(w.start_cursor("not-a-timestamp", since, False) == since,
          "an unparseable stored cursor must be refused, not handed to "
          "iso_ago (that ValueError used to kill the worker at startup)")
    check(w.start_cursor(None, "not-a-timestamp", False)
          == "1970-01-01T00:00:00.000000",
          "an unparseable --since must be refused too")
    print("test_start_cursor OK")


def test_clamp_timeout():
    """#15: the clamp is reported, and both bounds are configurable."""
    check(w.clamp_timeout(600, 1200) == (600, ""),
          "a timeout inside the bounds must not be touched")
    effective, note = w.clamp_timeout(1800, 1200)
    check(effective == 1200, effective)
    check("1800" in note and "1200" in note,
          f"the clamp must name both timeouts: {note!r}")
    check("--max-timeout" in note, note)
    effective, note = w.clamp_timeout(10, 1200)
    check(effective == w.MIN_TIMEOUT and "--min-timeout" in note,
          (effective, note))
    print("test_clamp_timeout OK")


def test_archive_console_log():
    """#6: the console outlives the workspace, and the archive is bounded."""
    node_id = "6aa387ecba3aeacda180ff12"
    with tempfile.TemporaryDirectory() as tmp:
        workspace = os.path.join(tmp, "job-1")
        log_dir = os.path.join(tmp, "logs")
        os.makedirs(workspace)
        console = "".join(f"console line {i}\n" for i in range(20))
        with open(os.path.join(workspace, "tuxrun.log"), "w") as handle:
            handle.write(console)
        kept = w.archive_console_log(workspace, log_dir, node_id)
        check(kept == os.path.join(log_dir, f"{node_id}.log"), kept)
        with open(kept) as handle:
            check(handle.read() == console,
                  "the archived console differs from the original")

        # a workspace without a console archives nothing and does not fail
        empty = os.path.join(tmp, "job-2")
        os.makedirs(empty)
        check(w.archive_console_log(empty, log_dir, "other") == "",
              "a job without a console must archive nothing")

        # an id that tries to escape the log directory is neutralised
        escaped = w.archive_console_log(workspace, log_dir, "../../etc/passwd")
        check(os.path.dirname(escaped) == log_dir,
              f"node id escaped the log directory: {escaped}")

        # pruning keeps only the newest entries
        for i in range(5):
            path = os.path.join(log_dir, f"node{i}.log")
            with open(path, "w") as handle:
                handle.write("x")
            os.utime(path, (1000 + i, 1000 + i))
        before = len(os.listdir(log_dir))
        removed = w.prune_console_logs(log_dir, keep=3)
        left = sorted(os.listdir(log_dir))
        check(len(left) == 3, f"prune kept {len(left)} of {before}: {left}")
        check(len(removed) == before - 3, removed)
        check("node4.log" in left, f"prune removed the newest entry: {left}")
        # a file the worker did not write is never pruned
        with open(os.path.join(log_dir, "callback-received.json"), "w") as fh:
            fh.write("{}\n")
        w.prune_console_logs(log_dir, keep=0)
        check(os.path.exists(os.path.join(log_dir, "callback-received.json")),
              "pruning removed a file that is not an archived console")
    print("test_archive_console_log OK")


def test_handle_event_non_json():
    """#11: an HTML error page from the API must not kill the whole worker."""
    args = _ap.Namespace(api_url="http://api", platform=None, runtime=None)
    event = {"node": {"id": "node-1", "artifacts": {}}}
    html_page = _Response(502, json_error=ValueError("Expecting value: line 1"))
    with stub_requests(get=lambda url, **kw: html_page):
        handled = w.handle_event(event, args, {})
    check(handled is False,
          "a non-JSON node body must be retried, not handled and marked seen")
    with stub_requests(get=lambda url, **kw: _Response(200, json_body=["nope"])):
        check(w.handle_event(event, args, {}) is False,
              "a node body that is not an object must be retried too")
    print("test_handle_event_non_json OK")


def _run_job_args(tmp):
    """Every field run_job()/handle_event() read, for the offline job tests."""
    return _ap.Namespace(
        api_url="http://api", platform=None, runtime=None,
        output_dir=os.path.join(tmp, "out"), keep_workspace=False,
        log_dir=os.path.join(tmp, "logs"), tuxrun_bin="tuxrun",
        cpu="rv64", container_runtime="", kvm_tests=w.KVM_TEST_SUBSET,
        max_download_size=(1 << 20), api_config_name="docker-host",
        storage_config_name="docker-host", kvm_full=False, rootfs="",
        max_timeout=1200, min_timeout=w.MIN_TIMEOUT,
    )


def test_missing_callback_keeps_result_pending():
    """#3 end to end: a job whose definition has no callback URL must not be
    reported as posted, and must not be marked seen - the result it just
    produced is the only copy."""
    node_id = "6aa387ecba3aeacda180ff12"
    job_def = {"callback": {}, "environment": {"platform": "qemu-riscv64"},
               "artifacts": {"kernel": "http://x/Image"},
               "tests": [{"type": "boot"}]}
    event = {"node": {"id": node_id,
                      "artifacts": {"job_definition": "http://x/job.yaml"}},
             "data": {"data": {"platform": "qemu-riscv64",
                               "runtime": "pull-labs-riscv"}}}

    def fake_run_command(cmd, timeout_s, workspace):
        with open(os.path.join(workspace, "tuxrun.log"), "w") as handle:
            handle.write("2026-09-08T00:00:00 console\n")
        return 0, "2026-09-08T00:00:00 console\n"

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "out"))
        args = _run_job_args(tmp)
        reports = {}
        real_retrieve, real_run_command = w.retrieve_job_definition, w.run_command
        w.retrieve_job_definition = lambda url: job_def
        w.run_command = fake_run_command
        try:
            with no_sleep(), stub_requests(
                get=lambda url, **kw: _Response(200, json_body={"state": "available"})
            ):
                handled = w.handle_event(event, args, reports)
        finally:
            w.retrieve_job_definition = real_retrieve
            w.run_command = real_run_command
        check(handled is False,
              "a job with no callback URL must not be treated as handled "
              "(that marks the node seen and drops the result)")
        check(node_id in reports,
              "the produced result must stay queued for re-posting")
        check(not reports[node_id][0],
              f"the queued report must keep the (empty) callback: {reports}")
        check(reports[node_id][2].get("status") == 3,
              f"the report must be the run's real body: {reports}")
    print("test_missing_callback_keeps_result_pending OK")


def test_state_flushed_before_a_crash():
    """#9: a kill mid-batch must not lose a collected result.

    handle_event() is replaced by a stub that queues a report and then raises,
    which is what a crash (or a SIGKILL) after a transient callback failure
    looks like from poll_loop's side: the state file must already contain the
    report, so the next start re-posts it instead of re-running tuxrun."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        args = _ap.Namespace(state_file=state_file, since=None,
                            ignore_state_cursor=False, api_url="http://api",
                            max_retries=1, poll_period=0, once=True)
        events = [{"node": {"id": "node-1"},
                   "timestamp": "2026-09-08T00:00:00.000000"}]

        def fake_handle(_event, _args, reports):
            reports["node-1"] = ("http://cb", "tok", {"status": 2})
            raise RuntimeError("worker killed mid-batch")

        real_pollevents, real_handle = w.pollevents, w.handle_event
        w.pollevents = lambda *_a, **_k: events
        w.handle_event = fake_handle
        try:
            try:
                w.poll_loop(args)
                check(False, "the simulated crash did not propagate")
            except RuntimeError:
                pass
        finally:
            w.pollevents, w.handle_event = real_pollevents, real_handle
        state = w.load_state(state_file)
        check(state["pending"].get("node-1", {}).get("body") == {"status": 2},
              f"the unposted result did not survive the crash: {state}")
        check("node-1" not in state["seen"],
              f"a node whose result is still pending must not be seen: {state}")
    print("test_state_flushed_before_a_crash OK")


def test_poll_loop_persists_cursor_and_seen():
    """#25: a handled node is marked seen and the cursor advances - the poll
    loop's own state transitions, persisted to the state file it writes."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        args = _ap.Namespace(state_file=state_file, since=None,
                            ignore_state_cursor=False, api_url="http://api",
                            max_retries=1, poll_period=0, once=True)
        node_id = "a" * 24
        events = [{"node": {"id": node_id,
                            "artifacts": {"job_definition": "http://x/job"}},
                   "timestamp": "2026-09-08T00:00:00.000000"}]
        real_pollevents, real_handle = w.pollevents, w.handle_event
        w.pollevents = lambda *_a, **_k: events
        w.handle_event = lambda *_a, **_k: True
        try:
            w.poll_loop(args)
        finally:
            w.pollevents, w.handle_event = real_pollevents, real_handle
        state = w.load_state(state_file)
        check(state["seen"] == [node_id], f"the handled node was not marked "
                                          f"seen: {state}")
        check(state["timestamp"] == "2026-09-08T00:00:00.000000", state)
        check(state["pending"] == {}, state)
    print("test_poll_loop_persists_cursor_and_seen OK")


def test_worker_lock():
    """#25: a second worker on the same state file must refuse to start.

    Two workers on one state file would each see half the queue and fight over
    the same workspaces and ports; the flock is what prevents that."""
    import fcntl

    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        # The file must stay open for the flock to be held (SIM115 is
        # deliberate, exactly as in poll_loop).
        holder = open(state_file + ".lock", "w")  # noqa: SIM115
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            args = _ap.Namespace(state_file=state_file, since=None,
                                ignore_state_cursor=False, api_url="http://api",
                                max_retries=1, poll_period=0, once=True)
            try:
                w.poll_loop(args)
                check(False, "a second worker was allowed to start while the "
                             "lock was held")
            except SystemExit as exit_error:
                check(exit_error.code == 1, f"expected exit 1, got {exit_error}")
        finally:
            holder.close()
    print("test_worker_lock OK")


def test_seen_eviction():
    """#25: the seen set stays bounded - the oldest id is evicted, so the
    state file cannot grow without limit."""
    limit = w.SEEN_LIMIT
    new_id = "f" * 24
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        old = [f"{i:024x}" for i in range(limit)]
        check(new_id not in old, "the test's new node id collides with an old one")
        w.save_state(state_file, {"timestamp": "2026-09-08T00:00:00.000000",
                                  "seen": old, "pending": {}})
        args = _ap.Namespace(state_file=state_file, since=None,
                            ignore_state_cursor=False, api_url="http://api",
                            max_retries=1, poll_period=0, once=True)
        events = [{"node": {"id": new_id,
                            "artifacts": {"job_definition": "http://x/job"}},
                   "timestamp": "2026-09-08T00:00:00.000000"}]
        real_pollevents, real_handle = w.pollevents, w.handle_event
        w.pollevents = lambda *_a, **_k: events
        w.handle_event = lambda *_a, **_k: True
        try:
            w.poll_loop(args)
        finally:
            w.pollevents, w.handle_event = real_pollevents, real_handle
        state = w.load_state(state_file)
        check(len(state["seen"]) == limit, len(state["seen"]))
        check(state["seen"][-1] == new_id, state["seen"][-1])
        check(old[0] not in state["seen"],
              "the oldest seen id must be the one evicted")
        check(old[1] in state["seen"], "eviction removed more than the oldest")
    print("test_seen_eviction OK")


test_strip_ansi()
test_tap_summary()
test_job_error()
test_lava_body_cap_and_boot_guard()
test_build_command_validation()
test_iso_ago()
test_post_result_classification()
test_download_complete_part_and_416()
test_state_roundtrip()
test_start_cursor()
test_clamp_timeout()
test_archive_console_log()
test_handle_event_non_json()
test_missing_callback_keeps_result_pending()
test_state_flushed_before_a_crash()
test_poll_loop_persists_cursor_and_seen()
test_seen_eviction()
test_worker_lock()
print("\nALL GUARD CHECKS PASSED")
