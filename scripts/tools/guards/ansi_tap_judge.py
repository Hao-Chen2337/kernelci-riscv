"""ANSI stripping, the TAP parser, infra detection, the LAVA body's guards."""
from kcilib.core import config
from kcilib.run import callback, judge

from .support import check


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
