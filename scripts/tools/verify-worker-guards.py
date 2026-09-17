#!/usr/bin/env python3
"""Adversarial guard tests for the RISC-V pull-lab worker's behaviour.

Offline checks for the paths where a bug loses a result or wedges an artifact:
ANSI and TAP edge cases, infra detection, log capping, the state file and its
cursor, callback classification, the resume/416 download path, the console
archive, the timeout clamp, and round B's kcilib/api.py and kcilib/source.py.

Every check drives the module that OWNS the behaviour and patches THAT module's
seam (poll, jobrun, callback, artifacts, api, source) - never a re-export in the
worker, which would only test the shim.  The state file is driven through
kcilib.core.state.StateFile, the object the poll loop writes.

Rationale: docs/docs/code-notes/W2d-tools.md.

    python3 scripts/tools/verify-worker-guards.py
"""
import json
import os
import sys
import tempfile
import time as _time
from contextlib import contextmanager

import requests as _real_requests

# kcilib sits next to this file; resolved through this file's own directory.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # scripts/ holds kcilib

from kcilib.core import cli, config, ledger, params
from kcilib.core.state import SEEN_LIMIT, StateFile
from kcilib.run import artifacts, callback, jobrun, judge, poll


def check(condition, message):
    """A guard that also holds under `python3 -O` / PYTHONOPTIMIZE=1.

    These used to be `assert`s, and -O strips those: a broken check exited 0,
    so the gate reported success precisely when it had verified nothing.
    """
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def test_strip_ansi():
    check(judge.strip_ansi("\x1b[0;32mok 1\x1b[0m") == "ok 1",
          "SGR colour codes not stripped")
    check(judge.strip_ansi("\x1b]0;title\x07plain") == "plain",      # OSC BEL
          "OSC BEL sequence not stripped")
    check(judge.strip_ansi("\x1b]8;;http://x\x1b\\text") == "text",  # OSC ST
          "OSC ST sequence not stripped")
    check(judge.strip_ansi("\x1b[2Jclear") == "clear",               # CSI letter
          "CSI letter-final sequence not stripped")
    check(judge.strip_ansi("plain text 100%") == "plain text 100%",
          "plain text was mangled")
    print("test_strip_ansi OK")


def test_tap_summary():
    # CRLF + ANSI + timestamp prefixes
    out = (
        "\x1b[0;90m2026-09-08T09:39:07\x1b[0m \x1b[0;32mok 1 selftests: kvm: a\x1b[0m\r\n"
        "2026-09-08T09:39:08 not ok 2 selftests: kvm: b # TIMEOUT 120 seconds\r\n"
        "2026-09-08T09:39:09 ok 3 selftests: kvm: c # SKIP\r\n"
    )
    summary, tests_out, per = judge.tap_summary(out, "kselftest-kvm")
    check(summary == {"total": 3, "failed": 1, "skipped": 1}, summary)
    check(per == {"a": "pass", "b": "fail", "c": "skip"}, per)
    check(tests_out["kselftest-kvm"]["status"] == "fail", tests_out)

    # "not ok" must not be double-counted as ok (the old bug)
    summary2, _, per2 = judge.tap_summary(
        "2026-09-08T00:00:00 ok 1 selftests: riscv: x\n"
        "2026-09-08T00:00:00 not ok 2 selftests: riscv: y\n",
        "kselftest-riscv")
    check(summary2 == {"total": 2, "failed": 1, "skipped": 0}, summary2)
    check(per2 == {"x": "pass", "y": "fail"}, per2)

    # started but never finished -> fail
    summary3, _, per3 = judge.tap_summary(
        "2026-09-08T00:00:00 # selftests: kvm: ghost\n"
        "2026-09-08T00:00:00 ok 1 selftests: kvm: real\n",
        "kselftest-kvm")
    check(summary3["failed"] == 1 and per3["ghost"] == "fail", (summary3, per3))

    # all-skip: still has results (visible skips), suite passes
    summary4, _, per4 = judge.tap_summary(
        "2026-09-08T00:00:00 ok 1 selftests: kvm: s1 # SKIP\n", "kselftest-kvm")
    check(summary4 == {"total": 1, "failed": 0, "skipped": 1}, summary4)
    check(per4 == {"s1": "skip"}, per4)

    # malformed/glued/uppercase failures must still be detected (round 2)
    weird = ("  not  ok 1 selftests: kvm: a\n"
             "NOT OK 2 selftests: kvm: b\n"
             "not\tok 3 selftests: kvm: c\n"
             "not\x1b[31mok 4 selftests: kvm: d\n"
             "notok 5 selftests: kvm: e\n")
    sw, _, pw = judge.tap_summary(weird, "kselftest-kvm")
    check(sw["failed"] == 5, (sw, pw))
    check(pw == {"a": "fail", "b": "fail", "c": "fail",
                 "d": "fail", "e": "fail"}, pw)

    # garbage: no TAP -> fail, never pass
    summary5, tests5, per5 = judge.tap_summary("nothing relevant here\n",
                                               "kselftest-kvm")
    check(summary5["failed"] == 1 and tests5["kselftest-kvm"]["status"] == "fail",
          (summary5, tests5))
    check(per5 == {}, per5)
    print("test_tap_summary OK")


def test_job_error():
    check(judge.tuxrun_job_error(
        2, "2026-09-08T00:00:00 JobError: Your job cannot terminate cleanly."),
        "JobError in the log must be detected")
    # a test whose NAME mentions JobError must not be misclassified
    check(not judge.tuxrun_job_error(
        0, "ok 1 selftests: kvm: job_error_checker_test\n"),
        "a test NAME containing job_error must not be read as a JobError")
    # authoritative: LAVA self-reported Infrastructure on the job case
    check(judge.tuxrun_infra_error(
        1, "2026-09-08T00:00:00 {'definition': 'lava', 'case': 'job', "
           "'result': 'fail', 'error_msg': 'Connection closed', "
           "'error_type': 'Infrastructure'}"),
        "LAVA's own Infrastructure job result must be detected")
    check(not judge.tuxrun_infra_error(
        0, "2026-09-08T00:00:00 {'case': 'job', 'result': 'pass'}"),
        "a passing job case must not be read as Infrastructure")
    print("test_job_error OK")


def test_lava_body_cap_and_boot_guard():
    run_config = config.RunConfig(api_config_name="docker-host",
                                  storage_config_name="docker-host")
    big = "2026-09-08T00:00:00 filler line\n" * (callback.LOG_LIMIT // 20 + 1000)
    body = callback.lava_body("qemu-riscv64", 0, big, run_config)
    import yaml as _yaml
    log_lines = _yaml.safe_load(body["log"])
    total = sum(len(ln.get("msg", "")) for ln in log_lines)
    check(total <= callback.LOG_LIMIT + (1 << 16), f"log too big: {total}")
    # rc 0 without any boot case -> incomplete, not a fake pass
    check(body["status"] == 3, body["status"])
    print("test_lava_body_cap_and_boot_guard OK")


def test_build_command_validation():
    run_config = config.RunConfig(
        tuxrun_bin="tuxrun", platform="qemu-riscv64", rootfs="",
        cpu="rv64,v=true", container_runtime="",
        kvm_tests=params.KVM_TEST_SUBSET,
        max_download_size=artifacts.MAX_DOWNLOAD_SIZE)
    job = {"artifacts": {"kernel": "http://x/Image"},
           "tests": [{"type": "kselftest-kvm; rm -rf /"}]}
    try:
        jobrun.build_command(job, run_config, "/tmp/fake")
        raise AssertionError("invalid test type must be rejected")
    except KeyError as e:
        check("invalid test type" in str(e), e)

    # ... and the flag -> field mapping is itself a tested thing (#phase 4):
    # config.from_args() is the ONE place a parsed command line becomes the two
    # config objects.
    args = cli.parse_args([
        "--api-url", "http://api", "--platform", "qemu-x86_64",
        "--runtime", "other-lab", "--output-dir", "/tmp/out",
        "--log-dir", "/tmp/logs", "--state-file", "/tmp/state.json",
        "--poll-period", "7", "--max-retries", "9", "--max-download-mb", "8",
        "--max-timeout", "1200", "--min-timeout", "90", "--tuxrun-bin", "/bt",
        "--container-runtime", "docker", "--rootfs", "/tmp/r.ext4",
        "--cpu", "rv64", "--kvm-tests", "a", "b", "--api-config-name", "cfg",
        "--storage-config-name", "store", "--once", "--kvm-full",
        "--keep-workspace", "--ignore-state-cursor"])
    configs = config.from_args(args)
    for field_name, expected in (
            ("api_url", "http://api"), ("platform", "qemu-x86_64"),
            ("runtime", "other-lab"), ("state_file", "/tmp/state.json"),
            ("poll_period", 7), ("max_retries", 9), ("once", True),
            ("ignore_state_cursor", True)):
        check(getattr(configs.poll, field_name) == expected,
              f"--{field_name} did not reach PollConfig.{field_name}: "
              f"{getattr(configs.poll, field_name)!r}")
    for field_name, expected in (
            ("output_dir", "/tmp/out"), ("log_dir", "/tmp/logs"),
            ("tuxrun_bin", "/bt"), ("container_runtime", "docker"),
            ("rootfs", "/tmp/r.ext4"), ("cpu", "rv64"),
            ("api_config_name", "cfg"), ("storage_config_name", "store")):
        check(getattr(configs.run, field_name) == expected,
              f"--{field_name} did not reach RunConfig.{field_name}: "
              f"{getattr(configs.run, field_name)!r}")
    check(configs.run.max_download_size == (8 << 20),
          f"--max-download-mb was not shifted to bytes: "
          f"{configs.run.max_download_size!r}")
    check(configs.run.platform == configs.poll.platform
          and configs.run.kvm_tests == ["a", "b"] and configs.run.kvm_full,
          "the run config lost a platform / kvm selection")
    # The defaults are the CLI's own: one home (kcilib.core.config), two readers.
    defaults = config.from_args(cli.parse_args([]))
    check(defaults.run.log_dir == config.LOG_DIR
          and defaults.run.max_timeout == config.DEFAULT_MAX_TIMEOUT
          and defaults.run.min_timeout == jobrun.MIN_TIMEOUT
          and defaults.poll.api_url == config.BASE_URI
          and defaults.poll.state_file == config.DEFAULT_STATE_FILE
          and defaults.run.kvm_tests == params.KVM_TEST_SUBSET,
          f"the CLI defaults drifted from the config defaults: {defaults}")
    print("test_build_command_validation OK")


def test_iso_ago():
    ts = poll.iso_ago("2026-09-08T12:00:00.000000", 900)
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
            raise _real_requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1 << 20):
        yield from self._chunks

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_body


class _RequestsStub:
    """Replaces a module's requests: get/post stubbed, exception classes real
    so the module's except clauses still match."""

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
def stub_requests(module, get=None, post=None):
    """Replace the `requests` of the module that OWNS the call.

    That module-level name is what the code resolves - kcilib.run.callback for
    the result POST, kcilib.run.artifacts for a transfer, kcilib.run.poll for
    the node-state GET - so stubbing the worker's would not be seen at all.
    """
    real = module.requests
    module.requests = _RequestsStub(get, post)
    try:
        yield
    finally:
        module.requests = real


@contextmanager
def no_sleep():
    """The code under test retries with time.sleep; a test must not wait."""
    real = _time.sleep
    _time.sleep = lambda _seconds: None
    try:
        yield
    finally:
        _time.sleep = real


def read_state(path):
    """The state file's three documented fields, as the operators read them.

    kcilib.core.state.StateFile owns the file; this is the guards' own view of
    the {timestamp, seen, pending} document it writes.
    """
    state = StateFile(path).load()
    return {
        "timestamp": state.cursor,
        "seen": list(state.seen),
        "pending": dict(state.pending),
    }


def write_state(path, document):
    """Write a state document through kcilib.core.state.StateFile (atomic rename)."""
    state = StateFile(path)
    state.cursor = document.get("timestamp")
    state.seen = list(document.get("seen", []))
    state.pending = dict(document.get("pending") or {})
    state.save()


def test_post_result_classification():
    """#3: a result that was not posted must never look posted."""
    check(issubclass(callback.CallbackMissingURLError,
                     callback.CallbackTransientError),
          "a missing callback URL must take the transient path (keep the "
          "result, retry) - the permanent path gives up and marks the node "
          "seen")
    with no_sleep(), stub_requests(callback):  # no HTTP call may happen at all
        try:
            callback.post_result("", "tok", {"status": 2})
            check(False, "post_result with no callback URL returned normally "
                         "(the caller then logs 'result posted')")
        except callback.CallbackMissingURLError as error:
            check("pending" in str(error), error)
        except Exception as error:  # noqa: BLE001 - the point of the test
            check(False, f"missing callback URL raised {error!r}")

    status = {"code": 200}
    with no_sleep(), stub_requests(
            callback, post=lambda url, **kw: _Response(status["code"])):
        callback.post_result("http://cb", "tok", {"status": 2})
        callback.post_result("http://cb", "tok", {"status": 2})
        status["code"] = 403
        try:
            callback.post_result("http://cb", "tok", {"status": 2})
            check(False, "a 4xx from the callback must raise (it used to be "
                         "reported as posted)")
        except callback.CallbackPermanentError:
            pass
        status["code"] = 503
        try:
            callback.post_result("http://cb", "tok", {"status": 2})
            check(False, "a 5xx from the callback must raise after the retries")
        except callback.CallbackTransientError:
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
        with stub_requests(artifacts):   # any GET raises AssertionError
            artifacts.download(url, dest, max_size=1 << 20)
        check(os.path.getsize(dest) == 1000, "complete .part was not published")
        check(not os.path.exists(part), ".part left behind after publishing")
        check(not os.path.exists(meta), "sidecar left behind after publishing")

        # (b) a 416 whose Content-Range total equals the offset: the server
        # itself confirms the partial was the whole artifact
        os.unlink(dest)
        with open(part, "wb") as handle:
            handle.write(b"y" * 500)
        with open(meta, "w") as handle:
            json.dump({"url": url, "total": 1000}, handle)
        ranges = []

        def get_416(_url, **kwargs):
            ranges.append(kwargs.get("headers", {}).get("Range"))
            return _Response(416, headers={"Content-Range": "bytes */500"})

        with no_sleep(), stub_requests(artifacts, get=get_416):
            artifacts.download(url, dest, max_size=1 << 20)
        check(os.path.getsize(dest) == 500, "a 416 = complete was not published")
        check(ranges == ["bytes=500-"], ranges)

        # (c) a mismatched 416 drops the partial, so the transfer restarts
        # from zero instead of wedging the artifact
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

        with no_sleep(), stub_requests(artifacts, get=get_restart):
            artifacts.download(url, dest, max_size=1 << 20)
        check(seen[0] == "bytes=10-", seen)
        check(seen[1] is None, f"the restart still resumed: {seen}")
        check(os.path.getsize(dest) == 1000, "restart did not fetch the file")

        # a sidecar for another URL must never be used to publish
        with open(part, "wb") as handle:
            handle.write(b"w" * 20)
        with open(meta, "w") as handle:
            json.dump({"url": "http://other/Image", "total": 20}, handle)
        check(artifacts.publish_complete_part(
                  part, url=url, max_size=1 << 20) == 0,
              "a sidecar naming another URL must not publish the .part")
    print("test_download_complete_part_and_416 OK")


def test_state_roundtrip():
    """kcilib.core.state.StateFile: what the pending set survives on."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "state.json")
        empty = read_state(path)
        check(empty == {"timestamp": None, "seen": [], "pending": {}}, empty)
        state = {
            "timestamp": "2026-09-08T00:00:00.000000",
            "seen": ["a" * 24],
            "pending": {"b" * 24: {"callback": "http://cb",
                                   "body": {"status": 2}}},
        }
        write_state(path, state)
        check(read_state(path) == state, "state did not survive a round trip")
        with open(path, "w") as handle:
            handle.write("{ not json")
        check(read_state(path)["timestamp"] is None,
              "a corrupt state file must be refused, not trusted")
        with open(path, "w") as handle:
            json.dump({"seen": "not-a-list"}, handle)
        check(read_state(path)["seen"] == [],
              "a state file of the wrong shape must be refused")
    print("test_state_roundtrip OK")


def test_start_cursor():
    """#8: the persisted cursor is authoritative, --since is a bootstrap."""
    stored = "2026-09-08T00:00:00.000000"
    since = "2020-01-01T00:00:00"
    check(poll.start_cursor(stored, since, False) == stored,
          "the persisted cursor must win over --since")
    check(poll.start_cursor(stored, since, True) == since,
          "--ignore-state-cursor must force --since")
    check(poll.start_cursor(stored, None, True) == stored,
          "--ignore-state-cursor without --since must fall back to the cursor")
    check(poll.start_cursor(None, since, False) == since,
          "--since seeds a state file that has no cursor")
    check(poll.start_cursor(None, None, False) == "1970-01-01T00:00:00.000000",
          "no cursor anywhere must scan the whole available queue")
    check(poll.start_cursor("not-a-timestamp", since, False) == since,
          "an unparseable stored cursor must be refused, not handed to "
          "iso_ago (that ValueError used to kill the worker at startup)")
    check(poll.start_cursor(None, "not-a-timestamp", False)
          == "1970-01-01T00:00:00.000000",
          "an unparseable --since must be refused too")
    print("test_start_cursor OK")


def test_clamp_timeout():
    """#15: the clamp is reported, and both bounds are configurable."""
    check(jobrun.clamp_timeout(600, 1200) == (600, ""),
          "a timeout inside the bounds must not be touched")
    effective, note = jobrun.clamp_timeout(1800, 1200)
    check(effective == 1200, effective)
    check("1800" in note and "1200" in note,
          f"the clamp must name both timeouts: {note!r}")
    check("--max-timeout" in note, note)
    effective, note = jobrun.clamp_timeout(10, 1200)
    check(effective == jobrun.MIN_TIMEOUT and "--min-timeout" in note,
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
        kept = jobrun.archive_console_log(workspace, log_dir, node_id)
        check(kept == os.path.join(log_dir, f"{node_id}.log"), kept)
        with open(kept) as handle:
            check(handle.read() == console,
                  "the archived console differs from the original")

        # a workspace without a console archives nothing and does not fail
        empty = os.path.join(tmp, "job-2")
        os.makedirs(empty)
        check(jobrun.archive_console_log(empty, log_dir, "other") == "",
              "a job without a console must archive nothing")

        # an id that tries to escape the log directory is neutralised
        escaped = jobrun.archive_console_log(
            workspace, log_dir, "../../etc/passwd")
        check(os.path.dirname(escaped) == log_dir,
              f"node id escaped the log directory: {escaped}")

        # pruning keeps only the newest entries
        for i in range(5):
            path = os.path.join(log_dir, f"node{i}.log")
            with open(path, "w") as handle:
                handle.write("x")
            os.utime(path, (1000 + i, 1000 + i))
        before = len(os.listdir(log_dir))
        removed = jobrun.prune_console_logs(log_dir, keep=3)
        left = sorted(os.listdir(log_dir))
        check(len(left) == 3, f"prune kept {len(left)} of {before}: {left}")
        check(len(removed) == before - 3, removed)
        check("node4.log" in left, f"prune removed the newest entry: {left}")
        # a file the worker did not write is never pruned
        with open(os.path.join(log_dir, "callback-received.json"), "w") as fh:
            fh.write("{}\n")
        jobrun.prune_console_logs(log_dir, keep=0)
        check(os.path.exists(os.path.join(log_dir, "callback-received.json")),
              "pruning removed a file that is not an archived console")
    print("test_archive_console_log OK")


def test_handle_event_non_json():
    """#11: an HTML error page from the API must not kill the whole worker."""
    poll_config = _poll_config("unused-state.json")
    event = {"node": {"id": "node-1", "artifacts": {}}}
    html_page = _Response(502, json_error=ValueError("Expecting value: line 1"))
    with stub_requests(poll, get=lambda url, **kw: html_page):
        handled = poll.handle_event(event, poll_config, config.RunConfig(), {},
                                    jobrun.run_node)
    check(handled is False,
          "a non-JSON node body must be retried, not handled and marked seen")
    with stub_requests(poll,
                       get=lambda url, **kw: _Response(200, json_body=["nope"])):
        check(poll.handle_event(event, poll_config, config.RunConfig(), {},
                                jobrun.run_node) is False,
              "a node body that is not an object must be retried too")
    print("test_handle_event_non_json OK")


def _run_job_config(tmp):
    """Every field run_node()/handle_event() read off the run config."""
    return config.RunConfig(
        platform="qemu-riscv64",
        output_dir=os.path.join(tmp, "out"), keep_workspace=False,
        log_dir=os.path.join(tmp, "logs"), tuxrun_bin="tuxrun",
        cpu="rv64", container_runtime="", kvm_tests=params.KVM_TEST_SUBSET,
        max_download_size=(1 << 20), api_config_name="docker-host",
        storage_config_name="docker-host", kvm_full=False, rootfs="",
        max_timeout=1200, min_timeout=jobrun.MIN_TIMEOUT,
    )


def _poll_config(state_file, **over):
    """Every field poll_loop()/handle_event() read off the poll config."""
    fields = {
        "api_url": "http://api", "platform": None, "runtime": None,
        "state_file": state_file, "since": None, "once": True,
        "poll_period": 0, "max_retries": 1, "ignore_state_cursor": False,
    }
    fields.update(over)
    return config.PollConfig(**fields)


def test_missing_callback_keeps_result_pending():
    """#3 end to end: no callback URL -> not posted and not marked seen, because
    the result it just produced is the only copy."""
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
        run_config = _run_job_config(tmp)
        poll_config = _poll_config("unused-state.json")
        reports = {}
        # The ledger root is redirected for the duration: this test drives a
        # REAL run_node(), and the record it files must not land in the
        # repository's work/results/ - `./run.sh verify` would dirty the tree it
        # is verifying.
        results_dir = os.path.join(tmp, "results")
        real_results_env = os.environ.get(ledger.RESULTS_DIR_ENV)
        os.environ[ledger.RESULTS_DIR_ENV] = results_dir
        baked, stamped = [], []
        real_retrieve = poll.retrieve_job_definition
        real_run_command = jobrun.run_command
        real_bake = jobrun.baked_rootfs_image
        real_stamp = jobrun.stamp
        poll.retrieve_job_definition = lambda url: job_def
        jobrun.run_command = fake_run_command

        def no_bake(*bake_args, **bake_kwargs):
            baked.append((bake_args, bake_kwargs))
            return "/tmp/not-baked.ext4"

        # run_node() resolves both as kcilib.run.jobrun module globals, which is
        # where the seam is: a boot job must never bake.
        jobrun.baked_rootfs_image = no_bake
        jobrun.stamp = stamped.append
        try:
            with no_sleep(), stub_requests(
                poll,
                get=lambda url, **kw: _Response(
                    200, json_body={"state": "available"})
            ):
                handled = poll.handle_event(event, poll_config, run_config,
                                            reports, jobrun.run_node)
        finally:
            poll.retrieve_job_definition = real_retrieve
            jobrun.run_command = real_run_command
            jobrun.baked_rootfs_image = real_bake
            jobrun.stamp = real_stamp
        check(baked == [], f"a boot job must not bake a guest image: {baked}")
        check(stamped, "the job's progress lines must still be stamped")
        check(handled is False,
              "a job with no callback URL must not be treated as handled "
              "(that marks the node seen and drops the result)")
        check(node_id in reports,
              "the produced result must stay queued for re-posting")
        check(not reports[node_id][0],
              f"the queued report must keep the (empty) callback: {reports}")
        check(reports[node_id][2].get("status") == 3,
              f"the report must be the run's real body: {reports}")

        # The same run must also be in the ledger: the worker used to file
        # nothing, so work/results/ held only the one-shot runner's rows.  The
        # build id falls back to the job node id, as this job names no build.
        record_path = ledger.result_path(node_id, "boot")
        check(os.path.isfile(record_path),
              f"the run must be recorded at {record_path}")
        record = ledger.read_results(node_id)["boot"]
        check(record["verdict"] == judge.VERDICT_INFRA,
              f"the record must carry the body's verdict: {record['verdict']}")
        check(record["source"] == "worker",
              f"the record must name its writer: {record['source']}")
        check(record["exit_code"] == judge.EXIT_INFRA,
              f"the record must carry the body's exit code: {record['exit_code']}")
        check(record["log"] and record["log"].endswith(".log"),
              f"the record must point at the archived console: {record['log']}")
        # This file lives in scripts/tools/, so the repository root is two up.
        repo_results = os.path.join(HERE, os.pardir, os.pardir, "work", "results")
        check(not os.path.isdir(repo_results)
              or node_id not in os.listdir(repo_results),
              "the record must not land in the repository's work/results/")
    if real_results_env is None:
        os.environ.pop(ledger.RESULTS_DIR_ENV, None)
    else:
        os.environ[ledger.RESULTS_DIR_ENV] = real_results_env
    print("test_missing_callback_keeps_result_pending OK")


def test_state_flushed_before_a_crash():
    """#9: a kill mid-batch must not lose a collected result.

    handle_event() queues a report and then raises, which is what a crash looks
    like from poll_loop's side: the state file must already hold the report, so
    the next start re-posts it instead of re-running tuxrun."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        poll_config = _poll_config(state_file)
        events = [{"node": {"id": "node-1"},
                   "timestamp": "2026-09-08T00:00:00.000000"}]

        def fake_handle(_event, _poll_config, _run_config, reports, _run_node):
            reports["node-1"] = ("http://cb", "tok", {"status": 2})
            raise RuntimeError("worker killed mid-batch")

        real_fetch, real_handle = poll.fetch_nodes, poll.handle_event
        poll.fetch_nodes = lambda *_a, **_k: events
        poll.handle_event = fake_handle
        try:
            try:
                poll.poll_loop(poll_config, jobrun.run_node, config.RunConfig())
                check(False, "the simulated crash did not propagate")
            except RuntimeError:
                pass
        finally:
            poll.fetch_nodes, poll.handle_event = real_fetch, real_handle
        state = read_state(state_file)
        check(state["pending"].get("node-1", {}).get("body") == {"status": 2},
              f"the unposted result did not survive the crash: {state}")
        check("node-1" not in state["seen"],
              f"a node whose result is still pending must not be seen: {state}")
    print("test_state_flushed_before_a_crash OK")


def test_poll_loop_persists_cursor_and_seen():
    """#25: a handled node is marked seen and the cursor advances, persisted."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        poll_config = _poll_config(state_file)
        node_id = "a" * 24
        events = [{"node": {"id": node_id,
                            "artifacts": {"job_definition": "http://x/job"}},
                   "timestamp": "2026-09-08T00:00:00.000000"}]
        real_fetch, real_handle = poll.fetch_nodes, poll.handle_event
        poll.fetch_nodes = lambda *_a, **_k: events
        poll.handle_event = lambda *_a, **_k: True
        try:
            poll.poll_loop(poll_config, jobrun.run_node, config.RunConfig())
        finally:
            poll.fetch_nodes, poll.handle_event = real_fetch, real_handle
        state = read_state(state_file)
        check(state["seen"] == [node_id], f"the handled node was not marked "
                                          f"seen: {state}")
        check(state["timestamp"] == "2026-09-08T00:00:00.000000", state)
        check(state["pending"] == {}, state)
    print("test_poll_loop_persists_cursor_and_seen OK")


def test_port_probe():
    """#4: the port check the stack makes is kcilib.core.ports', not a second copy.

    scripts/run-local-stack.sh calls `python3 -m kcilib.core.ports --host 0.0.0.0`,
    so that contract is what is checked: a free port passes, a foreign listener
    exits 1 naming port, holder and KCI_*_PORT, our own compose project is no
    conflict, and an EMPTY owner is never ours.
    """
    import socket

    from kcilib.core import ports

    # Explicit ports, NOT port 0: an ephemeral port makes this test depend on
    # the machine's ephemeral pool, and a box whose pool is exhausted fails
    # bind(0) with EADDRINUSE, which reads as "the port probe is broken".  The
    # stack's own ports (8001-8999) sit outside that range anyway.
    def _bind(host, wanted):
        for offset in range(32):
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, wanted + offset))
            except OSError:
                sock.close()
                continue
            return sock, wanted + offset
        check(False, f"no free port in {wanted}..{wanted + 31} for the probe test; "
                     f"the machine may be out of sockets (see 'ss -s')")
    held, taken = _bind("0.0.0.0", 18801)
    held.listen(1)
    spare, free = _bind("127.0.0.1", 18851)
    spare.close()

    real_compose = ports._compose_project
    real_free = ports.port_is_free
    try:
        # A port nobody holds: no refusal, whatever the compose answer is.
        ports._compose_project = lambda _port: ""
        ports.require_port_free(free, "artifact server", "KCI_SERVE_PORT",
                                host="0.0.0.0")

        # Somebody else holds it: exit 1 naming port, holder and the way out.
        try:
            ports.require_port_free(taken, "artifact server", "KCI_SERVE_PORT",
                                    host="0.0.0.0")
        except SystemExit as refusal:
            # The refusal is a message SystemExit: python prints it to stderr
            # and exits 1, so `refusal.code` is the MESSAGE, not 1.  The exit
            # status is checked below through the real command line.
            message = str(refusal)
            check(isinstance(refusal.code, str) and "already in use" in message,
                  f"a taken port must refuse with a message: {refusal.code!r}")
            for needle in (str(taken), "artifact server", "KCI_SERVE_PORT"):
                check(needle in message,
                      f"the refusal must name {needle!r}: {message}")
        else:
            check(False, "a taken port must refuse")

        # Published by OUR compose project: not a conflict.
        ports._compose_project = lambda _port: "kcirv"
        ports.require_port_free(taken, "artifact server", "KCI_SERVE_PORT",
                               project="kcirv", host="0.0.0.0")

        # An empty owner is NOT ours: an unnamed deployment must not wave a
        # foreign listener through in silence.
        ports._compose_project = lambda _port: ""
        try:
            ports.require_port_free(taken, "artifact server", "KCI_SERVE_PORT",
                                    project="", host="0.0.0.0")
        except SystemExit:
            pass
        else:
            check(False, "an empty owner must not be read as our own project")

        # The host is forwarded, not defaulted away: probing 127.0.0.1 for a
        # 0.0.0.0 service is the weaker check.
        seen = []

        def recording_probe(port, host=ports.DEFAULT_HOST):
            seen.append(host)
            return True

        ports.port_is_free = recording_probe
        ports.require_port_free(1234, "x", "KCI_X_PORT", host="0.0.0.0")
        ports.require_port_free(1234, "x", "KCI_X_PORT")
        check(seen == ["0.0.0.0", ports.DEFAULT_HOST],
              f"the probe host must be forwarded, got {seen}")

        # The command line run-local-stack.sh calls, end to end: exit 1 on a
        # taken port with the refusal on stderr, exit 0 on a free one.
        import subprocess
        # PYTHONPATH is scripts/ (where kcilib lives), not this file's directory.
        env = dict(os.environ, PYTHONPATH=os.path.dirname(HERE))

        def probe(port):
            return subprocess.run(
                [sys.executable, "-m", "kcilib.core.ports", "--require", str(port),
                 "--label", "artifact server", "--override", "KCI_SERVE_PORT",
                 "--host", "0.0.0.0", "--project", "kcirv"],
                cwd=HERE, env=env, check=False, capture_output=True,
                text=True)

        ports._compose_project = lambda _port: ""
        taken_run = probe(taken)
        check(taken_run.returncode == 1,
              f"the CLI must exit 1 on a taken port, got {taken_run.returncode}")
        check("already in use" in taken_run.stderr,
              f"the refusal must reach stderr: {taken_run.stderr!r}")
        free_run = probe(free)
        check(free_run.returncode == 0,
              f"the CLI must exit 0 on a free port, got {free_run.returncode}: "
              f"{free_run.stderr!r}")
    finally:
        ports._compose_project = real_compose
        ports.port_is_free = real_free
        held.close()
    print("test_port_probe OK")


def test_build_ref_and_jobspec():
    """The local job table's two pure layers: node -> BuildRef -> JobSpec.

    Both are pure, so they need no network, API or run.  Pinned down: a node
    whose artifacts name no build falls back to the node id, and a build lacking
    a collection's tarball SKIPs loudly instead of dying 20 minutes into a job."""
    from kcilib.table import buildref, jobspec

    node = {
        "id": "6aa822fcf84821b97339d2f9",
        "created": "2026-09-16T01:22:08Z",
        "data": {"kernel_revision": {"tree": "net-next", "commit": "348ea4642f56",
                                     "describe": "v7.3-rc2-758-g87b80c2f6b05c"}},
        "artifacts": {
            "kernel": "http://172.17.0.1:8999/Image",
            "kselftest_tar_xz": ("https://files.kernelci.org/"
                                 "kbuild-gcc-14-riscv-6aa3689720239ade90209d50/"
                                 "kselftest.tar.xz"),
            "modules": ("https://files.kernelci.org/"
                        "kbuild-gcc-14-riscv-6aa3689720239ade90209d50/"
                        "modules.tar.xz"),
        },
    }
    ref = buildref.build_ref_from_node(node)
    check(ref.build_id == "6aa3689720239ade90209d50",
          f"the build id must come from the artifact URL, got {ref.build_id}")
    check(ref.node_id == "6aa822fcf84821b97339d2f9",
          f"the source node id is kept as a reference, got {ref.node_id}")
    check(ref.tree == "net-next" and ref.commit == "348ea4642f56",
          f"tree/commit must come from the node: {ref.tree}/{ref.commit}")
    check(ref.missing_for("kselftest-kvm") == (),
          "this node carries everything the kvm collection needs")

    local_only = dict(node, artifacts={"kernel": "http://172.17.0.1:8999/Image"})
    fallback = buildref.build_ref_from_node(local_only)
    check(fallback.build_id == "6aa822fcf84821b97339d2f9",
          f"without a build id the node id stands in, got {fallback.build_id}")

    for broken in ({}, dict(node, artifacts={})):
        try:
            buildref.build_ref_from_node(broken)
        except ValueError:
            pass
        else:
            check(False, f"a node without a kernel must be refused: {broken}")

    specs, skipped = jobspec.jobs_from_build(fallback,
                                             tests=("boot", "kselftest-kvm"))
    check([spec.test for spec in specs] == ["boot"],
          f"only boot is runnable without the kselftest tarball: {specs}")
    check(skipped and skipped[0][0] == "kselftest-kvm",
          f"the skipped test must be reported: {skipped}")
    check(all(spec.timeout_s for spec in specs),
          "every spec must carry a timeout (the runner needs one)")

    plain = jobspec.job_definition(specs[0])
    check("callback" not in plain,
          "without a callback URL the definition must carry no callback section")
    check(set(plain) == {"artifacts", "tests", "environment"},
          f"unexpected definition keys: {sorted(plain)}")
    check(plain["environment"]["platform"] == "qemu-riscv64",
          f"platform must be qemu-riscv64: {plain['environment']}")
    with_cb = jobspec.job_definition(specs[0],
                                     callback_url="http://127.0.0.1:8003/n/1")
    check(with_cb["callback"]["url"] == "http://127.0.0.1:8003/n/1",
          "a callback URL must reach the definition, or the result is never posted")

    from kcilib.table.buildindex import BuildIndex
    with tempfile.TemporaryDirectory() as tmp:
        index = BuildIndex(os.path.join(tmp, "builds.db"))
        check(index.add(ref) is True, "the first add is new")
        check(index.add(ref) is False, "the second add must be a no-op")
        check(index.count() == 1, f"one row expected, got {index.count()}")
        roundtrip = index.get(ref.build_id)
        check(roundtrip and roundtrip.artifacts == ref.artifacts,
              f"artifacts must survive the roundtrip: {roundtrip.artifacts}")
        check(roundtrip.commit == ref.commit, "the commit column must roundtrip")
    print("test_build_ref_and_jobspec OK")


def test_worker_lock():
    """#25: a second worker on the same state file must refuse to start.

    Two workers on one state file would each see half the queue and fight over
    the same workspaces and ports."""
    import fcntl

    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        # The file must stay open for the flock to be held (SIM115 deliberate,
        # as in poll_loop).
        holder = open(state_file + ".lock", "w")  # noqa: SIM115
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            poll_config = _poll_config(state_file)
            try:
                poll.poll_loop(poll_config, jobrun.run_node, config.RunConfig())
                check(False, "a second worker was allowed to start while the "
                             "lock was held")
            except SystemExit as exit_error:
                check(exit_error.code == 1, f"expected exit 1, got {exit_error}")
        finally:
            holder.close()
    print("test_worker_lock OK")


def test_seen_eviction():
    """#25: the seen set stays bounded - the oldest id is evicted."""
    limit = SEEN_LIMIT
    new_id = "f" * 24
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        old = [f"{i:024x}" for i in range(limit)]
        check(new_id not in old, "the test's new node id collides with an old one")
        write_state(state_file, {"timestamp": "2026-09-08T00:00:00.000000",
                                 "seen": old, "pending": {}})
        poll_config = _poll_config(state_file)
        events = [{"node": {"id": new_id,
                            "artifacts": {"job_definition": "http://x/job"}},
                   "timestamp": "2026-09-08T00:00:00.000000"}]
        real_fetch, real_handle = poll.fetch_nodes, poll.handle_event
        poll.fetch_nodes = lambda *_a, **_k: events
        poll.handle_event = lambda *_a, **_k: True
        try:
            poll.poll_loop(poll_config, jobrun.run_node, config.RunConfig())
        finally:
            poll.fetch_nodes, poll.handle_event = real_fetch, real_handle
        state = read_state(state_file)
        check(len(state["seen"]) == limit, len(state["seen"]))
        check(state["seen"][-1] == new_id, state["seen"][-1])
        check(old[0] not in state["seen"],
              "the oldest seen id must be the one evicted")
        check(old[1] in state["seen"], "eviction removed more than the oldest")
    print("test_seen_eviction OK")


# --- round B: the one API client, and the two pull sources -----------------


class _FakeSession:
    """A stand-in for requests.Session, INJECTED onto the client.

    kcilib/api.py resolves self.session at call time, so replacing that one
    attribute is the seam: no request leaves the machine, and the kwargs the
    client passes - allow_redirects above all - stay observable.
    """

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs)


def _api_client(handler, base="http://x:8001", **kwargs):
    """A KernelCI whose session answers *handler* and records the calls."""
    from kcilib.api import KernelCI

    client = KernelCI(base, **kwargs)
    client.session = _FakeSession(handler)
    return client


def test_api_latest_prefix():
    """kcilib/api.py: one /latest base, whatever form the caller passes.

    The /latest prefix is what the hand-written clients disagreed about, so both
    accepted forms must address the SAME endpoint - not merely both "work".
    """
    from kcilib.api import KernelCI

    check(KernelCI("http://x:8001").latest == "http://x:8001/latest",
          "a bare base must be extended with /latest")
    check(KernelCI("http://x:8001/latest").latest == "http://x:8001/latest",
          "a base that already ends in /latest must not gain a second one")
    check(KernelCI("http://x:8001/").latest == "http://x:8001/latest",
          "a trailing slash must not produce //latest")
    check(KernelCI("http://x:8001/latest/").latest == "http://x:8001/latest",
          "a trailing slash after /latest must be trimmed, not doubled")

    urls, params = [], []

    def page(url, kwargs):
        urls.append(url)
        params.append(kwargs.get("params") or {})
        return _Response(200, json_body={"items": [], "total": 0})

    for base in ("http://x:8001", "http://x:8001/latest"):
        check(_api_client(page, base).all_nodes(limit=7) == [],
              f"the empty page was not returned for base {base}")
    check(urls == ["http://x:8001/latest/nodes"] * 2,
          f"both base forms must hit the same URL: {urls}")
    check(all(entry.get("limit") == 7 and entry.get("offset") == 0
              for entry in params), params)

    # An absolute URL is used as given: a job definition URL is external.
    forwarded = []

    def absolute(url, _kwargs):
        forwarded.append(url)
        return _Response(200, json_body={"artifacts": {}, "tests": []})

    _api_client(absolute).job_definition("http://elsewhere/job.yaml")
    check(forwarded == ["http://elsewhere/job.yaml"],
          f"an absolute URL must be passed through: {forwarded}")
    print("test_api_latest_prefix OK")


def test_api_all_nodes_pages():
    """kcilib/api.py: all_nodes() walks {items,total,offset}, and stops.

    A missing page used to look exactly like "no such build".  Three endings
    are checked: the total is reached, a short page when there is no total, and
    an empty page when the total is stale.
    """
    import kcilib.api as kcapi

    limit = kcapi.PAGE_LIMIT
    first = [{"id": f"{i:024x}"} for i in range(limit)]
    rest = [{"id": f"{i:024x}"} for i in range(limit, limit + 50)]

    def paging(batches, total=None, offsets=None):
        """Answer in the given batches; the offset asked for is recorded."""
        def handler(_url, kwargs):
            asked = (kwargs.get("params") or {}).get("offset")
            offsets.append(asked)
            if len(offsets) > 8:
                # A walk that never ends must fail here, not hang the suite.
                check(False, "all_nodes() did not terminate: "
                             f"{len(offsets)} requests, offsets {offsets}")
            index = len(offsets) - 1
            body = {"items": batches[index] if index < len(batches) else [],
                    "offset": asked}
            if total is not None:
                body["total"] = total
            return _Response(200, json_body=body)
        return handler

    # (a) the total is reported: two pages, and the walk ends at the total.
    offsets = []
    nodes = _api_client(
        paging([first, rest], total=limit + 50, offsets=offsets)).all_nodes()
    check(len(nodes) == limit + 50,
          f"expected {limit + 50} nodes, got {len(nodes)}")
    check(offsets == [0, limit],
          f"the second page must be asked for at offset {limit}: {offsets}")
    check(nodes[0]["id"] == first[0]["id"]
          and nodes[-1]["id"] == rest[-1]["id"],
          "the pages must be concatenated in creation order")

    # (b) no total at all: a page shorter than the limit is the end.
    offsets = []
    nodes = _api_client(paging([first, rest], offsets=offsets)).all_nodes()
    check(len(nodes) == limit + 50,
          f"a short page must not truncate the walk: {len(nodes)}")
    check(offsets == [0, limit], offsets)

    # (c) a total that never arrives (10**6 with 250 nodes): the short page and
    # then the empty one end it, so the walk stays bounded.
    offsets = []
    nodes = _api_client(
        paging([first, rest], total=10 ** 6, offsets=offsets)).all_nodes()
    check(len(nodes) == limit + 50, len(nodes))
    check(offsets == [0, limit, limit + 50],
          f"an empty page is the only stop left here: {offsets}")

    # (d) an empty first page: one request, no nodes, no spin.
    offsets = []
    check(_api_client(
        paging([], total=10 ** 6, offsets=offsets)).all_nodes() == [],
        "an empty page must end the walk")
    check(offsets == [0], f"an empty page must end it at once: {offsets}")
    print("test_api_all_nodes_pages OK")


def test_api_non_json_is_api_error():
    """kcilib/api.py: a body that is not JSON is an APIError, not a ValueError.

    A proxy answers an HTML page; response.json() raises ValueError, which used
    to escape the client and kill callers that catch only API errors.  The stub
    raises what requests really raises, not a bare ValueError.
    """
    import kcilib.api as kcapi

    check(issubclass(kcapi.APIError, RuntimeError),
          "APIError is the client's own error type")
    check(not issubclass(kcapi.APIError, ValueError),
          "APIError must not be a ValueError - it replaces that escape")
    # The exception response.json() really raises for an HTML body: requests'
    # JSONDecodeError where it has one (2.27+), json.JSONDecodeError before.
    # Both are ValueError, which is what _json() catches.
    decoder_error = getattr(_real_requests.exceptions, "JSONDecodeError",
                            json.JSONDecodeError)
    check(issubclass(decoder_error, ValueError),
          "the decoder error _json() catches must be a ValueError")

    # NB: raise_for_status() runs first, so the not-JSON path is a 2xx whose
    # body is HTML (a captive proxy, an SSO page).
    html = _Response(200, json_error=decoder_error(
        "Expecting value", "<html>not json</html>", 0))
    definition_url = "http://scheduler/job.yaml"
    # get() hands back whatever parsed; the typed readers are the ones that owe
    # the caller a shape, and they refuse a page that is not an object (below).
    typed_reads = (
        ("nodes()", lambda client: client.nodes()),
        ("all_nodes()", lambda client: client.all_nodes()),
        ("node()", lambda client: client.node("abc")),
        ("events()", lambda client: client.events()),
        ("job_definition()", lambda client: client.job_definition(
            definition_url)),
    )
    for label, call in (("get()", lambda client: client.get("/nodes")),
                        *typed_reads):
        try:
            call(_api_client(lambda _url, _kwargs: html))
        except kcapi.APIError as error:
            check("did not return JSON" in str(error), f"{label}: {error}")
        else:
            check(False, f"{label} must refuse a body that is not JSON")

    # JSON that is not an object: each reader says so, instead of handing a
    # list to code that indexes it as a page.
    not_an_object = _Response(200, json_body=["no"])
    for label, call in typed_reads:
        try:
            call(_api_client(lambda _url, _kwargs: not_an_object))
        except kcapi.APIError:
            pass
        else:
            check(False, f"{label} must refuse JSON that is not an object")

    # A 5xx stays requests' HTTPError (callers catch RequestException) and must
    # never be turned into an empty page.
    server_error = _Response(502, json_body={})
    try:
        _api_client(lambda _url, _kwargs: server_error).get("/nodes")
    except _real_requests.exceptions.HTTPError:
        pass
    else:
        check(False, "a 502 must raise, not return an empty page")
    print("test_api_non_json_is_api_error OK")


def test_api_refuses_redirect():
    """kcilib/api.py: job_definition() refuses a redirect.

    A redirect means something in between is answering, so the refusal comes
    first - a 3xx carrying a good JSON body is exactly what a "does the body
    parse?" check would wave through.
    """
    import kcilib.api as kcapi

    url = "http://scheduler/job.yaml"
    for status in (301, 302, 303, 307, 308):
        redirect = _Response(status, headers={"Location": "http://whom/"},
                             json_body={"artifacts": {}, "tests": []})
        # The response is bound as a default so the lambda does not close over
        # the loop variable (ruff B023: every call would see the last redirect).
        client = _api_client(lambda _url, _kwargs, reply=redirect: reply)
        try:
            client.job_definition(url)
        except kcapi.APIError as error:
            check("redirect" in str(error), f"{status}: {error}")
        else:
            check(False, f"a {status} redirect must be refused")
        check(client.session.calls[0][1].get("allow_redirects") is False,
              f"the {status} refusal holds only because allow_redirects=False "
              "reaches the session")
        check(client.session.calls[0][0] == url,
              "the definition URL is absolute: it must be used as given, not "
              "re-based under /latest")

    # The same flag on the successful path, so an endpoint that STARTS
    # redirecting is never silently followed.
    client = _api_client(lambda _url, _kwargs: _Response(
        200, json_body={"artifacts": {"kernel": "http://x/Image"},
                        "tests": [{"type": "boot"}]}))
    definition = client.job_definition(url)
    check(definition["tests"][0]["type"] == "boot", definition)
    check(client.session.calls[0][1].get("allow_redirects") is False,
          "even a plain definition fetch must not follow redirects")
    print("test_api_refuses_redirect OK")


def test_api_retries_a_dropped_connection():
    """kcilib/api.py: a dropped connection is retried; a 5xx is not.

    The local API closes idle keep-alive connections, so a dropped connection
    used to lose a page; retrying a 5xx would only slow a refusal down.
    """
    import kcilib.api as kcapi

    check(kcapi.KernelCI("http://x:8001").retries == 3,
          "the documented default is three attempts")
    attempts = []

    def dropped(_url, _kwargs):
        attempts.append(1)
        raise _real_requests.exceptions.ConnectionError("connection reset")

    def fails(client, **kwargs):
        try:
            client.get("/nodes", **kwargs)
        except _real_requests.exceptions.ConnectionError:
            return True
        return False

    client = _api_client(dropped)
    with no_sleep():
        check(fails(client), "a connection error must reach the caller")
        check(len(attempts) == 3, f"expected 3 attempts, got {len(attempts)}")
        attempts.clear()
        check(fails(client, retries=1), "retries=1 must still raise")
        check(len(attempts) == 1, attempts)
        attempts.clear()
        check(fails(client, retries=0), "retries=0 must still raise")
        check(len(attempts) == 1,
              f"retries=0 must still make one attempt: {len(attempts)}")

        # ... and a retry that succeeds returns the page.
        attempts.clear()

        def once_then_ok(_url, _kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise _real_requests.exceptions.ConnectionError("dropped")
            page = {"items": [{"id": "n"}], "total": 1}
            return _Response(200, json_body=page)

        nodes = _api_client(once_then_ok).all_nodes()
        check(nodes == [{"id": "n"}],
              f"the second attempt's page must be returned: {nodes}")

    attempts.clear()

    def refused(_url, _kwargs):
        attempts.append(1)
        return _Response(503, json_body={})

    try:
        _api_client(refused).get("/nodes")
    except _real_requests.exceptions.HTTPError:
        pass
    else:
        check(False, "a 503 must raise")
    check(len(attempts) == 1, f"a 5xx must not be retried: {len(attempts)}")
    print("test_api_retries_a_dropped_connection OK")


@contextmanager
def ledger_at(path):
    """Point the ledger's root at *path* for the duration.

    Same seam and reason as test_missing_callback_keeps_result_pending: a guard
    must not write into the repository's work/results/.
    """
    real = os.environ.get(ledger.RESULTS_DIR_ENV)
    os.environ[ledger.RESULTS_DIR_ENV] = path
    try:
        yield path
    finally:
        if real is None:
            os.environ.pop(ledger.RESULTS_DIR_ENV, None)
        else:
            os.environ[ledger.RESULTS_DIR_ENV] = real


@contextmanager
def no_api_calls():
    """Any use of the one API client fails for the duration.

    kcilib/source.py documents the table source as local-only (index minus
    ledger), so a request here means it grew a network dependency silently.
    """
    from kcilib.api import KernelCI

    def refuse(_self, *_args, **_kwargs):
        raise AssertionError("the table source must not talk to the API")

    real = KernelCI.get
    KernelCI.get = refuse
    try:
        yield
    finally:
        KernelCI.get = real


@contextmanager
def stub_newest_api(builds, windows, queries):
    """kcilib.source's two production-API seams, patched ON that module.

    NewestSource.build() resolves builds_from_production_api and _days_ago as
    globals of kcilib.source, so patching them there is what the code reads, and
    the window asked for becomes observable.  *builds* takes the attempt number;
    *windows* and *queries* collect what was asked for.
    """
    from kcilib import source as kcsource

    real_builds = kcsource.builds_from_production_api
    real_days_ago = kcsource._days_ago

    def fake_builds(query):
        queries.append(query)
        windows.append(query.since)
        return builds(len(windows)), []

    kcsource.builds_from_production_api = fake_builds
    kcsource._days_ago = lambda days: f"T-{days}d"
    try:
        yield kcsource
    finally:
        kcsource.builds_from_production_api = real_builds
        kcsource._days_ago = real_days_ago


def test_table_source_subtracts_the_ledger():
    """kcilib/source.py: TableSource is the index MINUS the ledger.

    A (build, test) the ledger already holds is not offered again, and a test
    the build cannot support is skipped WITH the artifact it is missing - never
    silently dropped.
    """
    from kcilib import source as kcsource
    from kcilib.table.buildindex import BuildIndex
    from kcilib.table.buildref import BuildRef

    build_id = "6aa3689720239ade90209d50"
    ref = BuildRef(
        build_id=build_id,
        # kernel + kselftest tarball, no modules: kselftest-kvm cannot run.
        artifacts={"kernel": f"http://x/{build_id}/Image",
                   "kselftest_tar_xz": f"http://x/{build_id}/ks.txz"},
        tree="riscv", commit="deadbeef", created="2026-09-16T00:00:00Z")

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "builds.db")
        index = BuildIndex(db)
        check(index.add(ref) is True, "the build must enter the index")
        with ledger_at(os.path.join(tmp, "results")), no_api_calls():
            specs, skipped, checked = kcsource.TableSource(db=db).jobs()
            check([(spec.build_id, spec.test) for spec in specs]
                  == [(build_id, "boot"), (build_id, "kselftest-riscv")],
                  f"the runnable tests must be offered: {specs}")
            check(checked == 1, f"one build was checked: {checked}")
            check(len(skipped) == 1, f"exactly one skip expected: {skipped}")
            skipped_build, skipped_test, reason = skipped[0]
            check((skipped_build, skipped_test) == (build_id, "kselftest-kvm"),
                  f"the unrunnable test must be reported: {skipped}")
            check("modules" in reason,
                  f"the skip must name the missing artifact: {reason!r}")

            # The ledger now holds a record for boot: it must be subtracted.
            ledger.write_result(build_id, "boot",
                                {"verdict": "pass", "source": "fetch"})
            specs2, _skipped2, checked2 = kcsource.TableSource(db=db).jobs()
            check([spec.test for spec in specs2] == ["kselftest-riscv"],
                  f"the ledger's boot row must be subtracted: {specs2}")
            check(checked2 == 1, checked2)

            # ... and with both recorded the list is empty while the skip is
            # still reported: "0 to do" and "2 tests were skipped" differ.
            ledger.write_result(build_id, "kselftest-riscv",
                                {"verdict": "pass", "source": "fetch"})
            specs3, skipped3, checked3 = kcsource.TableSource(db=db).jobs()
            check(specs3 == [], f"nothing is left to run: {specs3}")
            check(len(skipped3) == 1 and checked3 == 1,
                  f"an empty todo still says what it looked at: {skipped3}")

            # A narrowed test list still reports the skip it asked about.
            specs4, skipped4, _c = kcsource.TableSource(db=db).jobs(
                tests=["kselftest-kvm"])
            check(specs4 == [] and [test for _b, test, _r in skipped4]
                  == ["kselftest-kvm"], (specs4, skipped4))
    print("test_table_source_subtracts_the_ledger OK")


def test_newest_source_widens_the_window():
    """kcilib/source.py: NewestSource widens 3 -> 7 -> 30 -> 180 days.

    The production API pages old-first and a quiet tree can be days behind, so
    a hit on the first window stops the walk, a hit on a later one is still
    used, and the query asked is the one the caller described.
    """
    import calendar

    from kcilib.table.buildref import BuildRef

    ref = BuildRef(build_id="6aa3689720239ade90209d50",
                   artifacts={"kernel": "http://x/Image"},
                   tree="riscv", commit="deadbeef")

    # The real widening clock, before it is patched: an ISO8601 stamp that
    # really is N days back (the module builds it with time.gmtime).
    from kcilib import source as kcsource

    stamp = kcsource._days_ago(180)
    check(len(stamp) == 19 and "T" in stamp,
          f"_days_ago must produce ISO8601 seconds: {stamp!r}")
    gap = _time.time() - calendar.timegm(
        _time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))
    check(abs(gap - 180 * 86400) < 300,
          f"_days_ago(180) is {gap / 86400:.2f} days back, not 180")

    windows, queries = [], []
    with stub_newest_api(lambda attempt: [ref] if attempt >= 3 else [],
                         windows, queries) as kcsource:
        specs, skipped, checked = kcsource.NewestSource(
            job="kbuild-gcc-14-riscv", days=3).jobs()
    check(windows == ["T-3d", "T-7d", "T-30d"],
          "the window must widen one step at a time and stop at the first "
          f"hit: {windows}")
    check(queries and queries[0].job == "kbuild-gcc-14-riscv"
          and queries[0].result == "pass" and queries[0].trees == ()
          and queries[0].api == kcsource.PRODUCTION_API,
          f"the query must ask for passing builds of that job: {queries[0]}")
    check([spec.test for spec in specs] == ["boot"],
          f"only boot is runnable without the kselftest tarballs: {specs}")
    check([(build, test) for build, test, _reason in skipped]
          == [(ref.build_id, "kselftest-riscv"),
              (ref.build_id, "kselftest-kvm")],
          f"the skips must name the build they came from: {skipped}")
    check(all(reason for _b, _t, reason in skipped),
          f"a skip without a reason is the silent skip this is not: {skipped}")
    check(checked == 1, f"one build was offered: {checked}")

    # A custom first window leads the widening, and the walk still ends at the
    # last one when nothing is found.
    windows, queries = [], []
    with stub_newest_api(lambda _attempt: [], windows, queries) as kcsource:
        found = kcsource.NewestSource(days=1).build()
    check(windows == ["T-1d", "T-7d", "T-30d", "T-180d"],
          f"a custom window must lead the widening: {windows}")
    check(found is None,
          f"nothing found means None, not a made-up build: {found}")
    print("test_newest_source_widens_the_window OK")


def test_newest_source_reports_no_build():
    """kcilib/source.py: nothing in 180 days is an empty list AND a reason.

    "0 to do" is an answer an operator cannot act on, so the source names the
    job and the window - after really looking that far back.
    """
    windows, queries = [], []
    with stub_newest_api(lambda _attempt: [], windows,
                         queries) as kcsource:
        specs, skipped, checked = kcsource.NewestSource(
            job="kbuild-gcc-14-riscv").jobs()
    check(specs == [] and checked == 0, (specs, checked))
    check(windows == ["T-3d", "T-7d", "T-30d", "T-180d"],
          f"every window must be tried before giving up: {windows}")
    check(len(skipped) == 1, f"one reason expected: {skipped}")
    subject, test, reason = skipped[0]
    check(subject == "kbuild-gcc-14-riscv" and test == "no usable build",
          f"the reason must say which job found nothing: {skipped}")
    check("kbuild-gcc-14-riscv" in reason and "180" in reason,
          f"the reason must name the job and the window: {reason!r}")
    print("test_newest_source_reports_no_build OK")


def test_get_source_unknown_name():
    """kcilib/source.py: an unknown --source exits with the real names in it.

    --source events is the trap: ./run.sh worker is the way to it, and the user
    must be told that rather than get a KeyError traceback.
    """
    from kcilib import source as kcsource

    try:
        kcsource.get_source("events")
    except SystemExit as refusal:
        message = str(refusal)
        check(isinstance(refusal.code, str),
              f"the refusal is a message SystemExit: {refusal.code!r}")
        for needle in ("events", "table", "newest", "run.sh worker"):
            check(needle in message,
                  f"the refusal must mention {needle!r}: {message}")
    else:
        check(False, "'events' is not a pull source and must be refused")

    check(sorted(kcsource.SOURCES) == ["newest", "table"],
          "the source table is the contract run.sh's --source reads: "
          f"{sorted(kcsource.SOURCES)}")

    with tempfile.TemporaryDirectory() as tmp:
        table = kcsource.get_source("table", db=os.path.join(tmp, "b.db"),
                                    tests=["boot"])
        check(isinstance(table, kcsource.JobSource) and table.name == "table",
              f"get_source('table') must build a pull source: {table!r}")
        check(table.tests == ("boot",), table.tests)
        newest = kcsource.get_source("newest", job="kbuild-gcc-14-riscv",
                                     days=7)
        check(newest.name == "newest" and newest.days == 7,
              f"get_source must forward the keyword arguments: {newest!r}")

    # The base class refuses to be a source: a subclass that forgets jobs()
    # fails loudly rather than answering "nothing to do".
    try:
        kcsource.JobSource().jobs()
    except NotImplementedError:
        pass
    else:
        check(False, "JobSource.jobs() must not return anything")
    print("test_get_source_unknown_name OK")


def test_no_repo_root_is_counted_with_dirname():
    """The repository root is walked up to (kcilib.repo_root), never counted.

    Three tools moved into scripts/tools/ and kept a counted root, each silently
    one level too deep: render-local-config.py rendered @KCI_ROOT@ as .../scripts
    so EVERY job node came back submit_error, and callback-catcher.py defaulted
    its log to scripts/work/logs/.  All still "worked" one directory up, so the
    rule is checked here: a module-level ROOT-ish name may not be built from
    os.path.dirname().
    """
    import glob
    import re

    import kcilib

    root = kcilib.repo_root()
    check(os.path.exists(os.path.join(root, "run.sh")),
          f"repo_root() must be the directory holding run.sh, got {root}")
    pattern = re.compile(r"^\s*([A-Z_]*ROOT[A-Z_]*)\s*=\s*os\.path\.dirname", re.MULTILINE)
    offenders = []
    scanned = 0
    for path in sorted(glob.glob(os.path.join(root, "scripts", "**", "*.py"),
                                 recursive=True)):
        scanned += 1
        with open(path, encoding="utf-8") as handle:
            for match in pattern.finditer(handle.read()):
                offenders.append(f"{os.path.relpath(path, root)}:{match.group(1)}")
    check(scanned > 10, f"only {scanned} python files scanned; the glob is wrong")
    check(not offenders,
          "a repo-root constant is built by counting dirname() levels; use "
          "kcilib.repo_root() instead (moving the file breaks the count "
          "silently): " + ", ".join(offenders))
    print("test_no_repo_root_is_counted_with_dirname OK")


def test_shell_scripts_reference_live_modules():
    """A file that moves must not leave a shell caller on the old path.

    scripts/run-local-stack.sh kept calling `python3 -m kcilib.ports` after
    ports.py moved into kcilib/core/, so `./run.sh stack` died at its first port
    check and no gate noticed.  Checked: every `python3 -m kcilib.<x>` must
    import, and every flat `scripts/<name>.py` must exist.
    """
    import glob
    import importlib.util
    import re

    import kcilib

    root = kcilib.repo_root()
    shells = [os.path.join(root, "run.sh")]
    shells += sorted(glob.glob(os.path.join(root, "scripts", "*.sh")))
    check(len(shells) > 1, f"expected run.sh and scripts/*.sh, found {shells}")

    module_re = re.compile(r"python3\s+-m\s+(kcilib(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
    flat_re = re.compile(r"scripts/([A-Za-z0-9_.-]+\.py)")
    modules = paths = 0
    for shell in shells:
        rel = os.path.relpath(shell, root)
        with open(shell, encoding="utf-8") as handle:
            text = handle.read()
        for name in module_re.findall(text):
            modules += 1
            check(importlib.util.find_spec(name) is not None,
                  f"{rel} runs `python3 -m {name}`, which does not import: "
                  f"the module moved (check the sub-package it lives in now)")
        for name in flat_re.findall(text):
            paths += 1
            check(os.path.exists(os.path.join(root, "scripts", name)),
                  f"{rel} refers to scripts/{name}, which does not exist: it "
                  f"moved (the offline tools live in scripts/tools/)")
    # Both patterns must match something, or this guard passes by finding
    # nothing the day the call sites are rewritten.
    check(modules >= 1, "no `python3 -m kcilib.*` reference found; the pattern is stale")
    check(paths >= 1, "no flat scripts/*.py reference found; the pattern is stale")
    print("test_shell_scripts_reference_live_modules OK")


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
test_port_probe()
test_build_ref_and_jobspec()
test_api_latest_prefix()
test_api_all_nodes_pages()
test_api_non_json_is_api_error()
test_api_refuses_redirect()
test_api_retries_a_dropped_connection()
test_table_source_subtracts_the_ledger()
test_newest_source_widens_the_window()
test_newest_source_reports_no_build()
test_get_source_unknown_name()
test_no_repo_root_is_counted_with_dirname()
test_shell_scripts_reference_live_modules()
test_worker_lock()
print("\nALL GUARD CHECKS PASSED")
