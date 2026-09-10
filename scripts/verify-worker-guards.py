#!/usr/bin/env python3
"""Adversarial guard tests for riscv_pull_worker.py.

Covers the review findings that are testable offline: ANSI stripping,
TAP edge cases, infra detection, log capping and test-type validation.
Run from anywhere:

    python3 scripts/verify-worker-guards.py
"""
import importlib.util
import os

spec = importlib.util.spec_from_file_location(
    "worker",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "riscv_pull_worker.py"))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def test_strip_ansi():
    assert w.strip_ansi("\x1b[0;32mok 1\x1b[0m") == "ok 1"
    assert w.strip_ansi("\x1b]0;title\x07plain") == "plain"      # OSC BEL
    assert w.strip_ansi("\x1b]8;;http://x\x1b\\text") == "text"  # OSC ST
    assert w.strip_ansi("\x1b[2Jclear") == "clear"               # CSI letter final
    assert w.strip_ansi("plain text 100%") == "plain text 100%"
    print("test_strip_ansi OK")


def test_tap_summary():
    # CRLF + ANSI + timestamp prefixes
    out = (
        "\x1b[0;90m2026-09-08T09:39:07\x1b[0m \x1b[0;32mok 1 selftests: kvm: a\x1b[0m\r\n"
        "2026-09-08T09:39:08 not ok 2 selftests: kvm: b # TIMEOUT 120 seconds\r\n"
        "2026-09-08T09:39:09 ok 3 selftests: kvm: c # SKIP\r\n"
    )
    summary, tests_out, per = w.tap_summary(out, "kselftest-kvm")
    assert summary == {"total": 3, "failed": 1, "skipped": 1}, summary
    assert per == {"a": "pass", "b": "fail", "c": "skip"}, per
    assert tests_out["kselftest-kvm"]["status"] == "fail"

    # "not ok" must not be double-counted as ok (the old bug)
    summary2, _, per2 = w.tap_summary(
        "2026-09-08T00:00:00 ok 1 selftests: riscv: x\n"
        "2026-09-08T00:00:00 not ok 2 selftests: riscv: y\n",
        "kselftest-riscv")
    assert summary2 == {"total": 2, "failed": 1, "skipped": 0}, summary2
    assert per2 == {"x": "pass", "y": "fail"}

    # started but never finished -> fail
    summary3, _, per3 = w.tap_summary(
        "2026-09-08T00:00:00 # selftests: kvm: ghost\n"
        "2026-09-08T00:00:00 ok 1 selftests: kvm: real\n",
        "kselftest-kvm")
    assert summary3["failed"] == 1 and per3["ghost"] == "fail", (summary3, per3)

    # all-skip: still has results (visible skips), suite passes
    summary4, _, per4 = w.tap_summary(
        "2026-09-08T00:00:00 ok 1 selftests: kvm: s1 # SKIP\n", "kselftest-kvm")
    assert summary4 == {"total": 1, "failed": 0, "skipped": 1}, summary4
    assert per4 == {"s1": "skip"}

    # malformed/glued/uppercase failures must still be detected
    # (round 2: these used to be false greens)
    weird = ("  not  ok 1 selftests: kvm: a\n"
             "NOT OK 2 selftests: kvm: b\n"
             "not\tok 3 selftests: kvm: c\n"
             "not\x1b[31mok 4 selftests: kvm: d\n"
             "notok 5 selftests: kvm: e\n")
    sw, _, pw = w.tap_summary(weird, "kselftest-kvm")
    assert sw["failed"] == 5, (sw, pw)
    assert pw == {"a": "fail", "b": "fail", "c": "fail",
                  "d": "fail", "e": "fail"}

    # garbage: no TAP -> fail, never pass
    summary5, tests5, per5 = w.tap_summary("nothing relevant here\n", "kselftest-kvm")
    assert summary5["failed"] == 1 and tests5["kselftest-kvm"]["status"] == "fail"
    assert per5 == {}
    print("test_tap_summary OK")


def test_job_error():
    assert w.tuxrun_job_error(
        2, "2026-09-08T00:00:00 JobError: Your job cannot terminate cleanly.")
    # a test whose NAME mentions JobError must not be misclassified
    assert not w.tuxrun_job_error(
        0, "ok 1 selftests: kvm: job_error_checker_test\n")
    # authoritative: LAVA self-reported Infrastructure on the job case
    assert w.tuxrun_infra_error(
        1, "2026-09-08T00:00:00 {'definition': 'lava', 'case': 'job', "
           "'result': 'fail', 'error_msg': 'Connection closed', "
           "'error_type': 'Infrastructure'}")
    assert not w.tuxrun_infra_error(
        0, "2026-09-08T00:00:00 {'case': 'job', 'result': 'pass'}")
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
    assert total <= w.LOG_LIMIT + (1 << 16), f"log too big: {total}"
    # rc 0 without any boot case -> incomplete, not a fake pass
    assert body["status"] == 3, body["status"]
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
        assert "invalid test type" in str(e), e
    print("test_build_command_validation OK")


def test_iso_ago():
    ts = w.iso_ago("2026-09-08T12:00:00.000000", 900)
    assert ts == "2026-09-08T11:45:00", ts
    print("test_iso_ago OK")


test_strip_ansi()
test_tap_summary()
test_job_error()
test_lava_body_cap_and_boot_guard()
test_build_command_validation()
test_iso_ago()
print("\nALL GUARD CHECKS PASSED")
