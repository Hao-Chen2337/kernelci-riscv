#!/usr/bin/env python3
"""Verify lava_body() output against the REAL production parser
(kernelci.runtime.lava.Callback) and every method lava_callback.py calls."""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# Import kernelci-core from THIS checkout, never from some other deployment
# that happened to be hardcoded here: a hardcoded path made a fresh clone's
# verify results silently depend on the machine it was run from.
sys.path.insert(0, os.path.join(ROOT, "kernelci-core"))
from kernelci.runtime.lava import Callback

spec = importlib.util.spec_from_file_location(
    "riscv_pull_worker",
    os.path.join(HERE, "riscv_pull_worker.py"))
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

FIXTURES = os.path.join(HERE, "fixtures")
PASS_LOG = os.path.join(FIXTURES, "tuxrun-pass.log")
FAIL_LOG = os.path.join(FIXTURES, "tuxrun-fail.log")


def check(condition, message):
    """A guard that also holds under `python3 -O` / PYTHONOPTIMIZE=1.

    These checks used to be `assert` statements.  run.sh fails the `verify`
    gate on a non-zero exit, but -O strips every assert, so a broken check
    printed "ALL PARSER CHECKS PASSED" and exited 0: the gate reported
    success precisely when it had verified nothing.
    """
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def fake_args():
    return argparse.Namespace(
        api_config_name="docker-host", storage_config_name="docker-host")


def run_case(tag, log_path, returncode, expect_status):
    print(f"\n===== {tag} =====")
    with open(log_path, encoding="utf-8") as f:
        output = f.read()
    body = worker.lava_body("qemu-riscv64", returncode, output, fake_args())
    with open(f"/tmp/lava-body-{tag}.json", "w") as f:
        json.dump(body, f, indent=1)

    cb = Callback(body)
    status = cb.get_job_status()
    check(status == expect_status, f"status {status} != {expect_status}")
    print("get_job_status:", status)
    print("get_meta(api_config_name):", cb.get_meta("api_config_name"))
    print("get_meta(storage_config_name):", cb.get_meta("storage_config_name"))
    print("get_device_id:", cb.get_device_id())
    print("is_infra_error:", cb.is_infra_error())

    lp = cb.get_log_parser()
    check(lp is not None,
          "log parser is None -> result would be forced incomplete")
    text = lp.get_text()
    print(f"log parser OK, {len(text.splitlines())} target lines, "
          f"sample: {text.splitlines()[0][:60] if text else '(empty)'}")

    results = cb.get_results()
    print("get_results:", results)

    job_node = {"id": "test", "name": "baseline-riscv64-qemu-pulltest",
                "result": status, "data": {}, "artifacts": {}}
    hierarchy = cb.get_hierarchy(results, job_node)
    print("get_hierarchy job result:", hierarchy["node"]["result"])
    print("child nodes:", [c["node"]["name"] for c in hierarchy["child_nodes"]])


def run_kselftest_tap_cases():
    """The bug this guards: tuxrun exits 0 even when selftests fail, so a
    LAVA body built from the exit code alone would report a PASS node and
    drop every per-test result.  With the TAP wired in, the same run must
    produce per-test child results and a job-level 'fail'."""
    output = (
        "2026-09-08T00:00:00 lava-dispatcher, installed at version: 2026.05\n"
        "start: 0 validate\n"
        "ok 1 selftests: riscv: vector\n"
        "ok 2 selftests: riscv: hwprobe # SKIP\n"
        "not ok 3 selftests: riscv: mm\n"
    )
    print("\n===== kselftest TAP: rc=0 + not ok -> job fail =====")
    summary, _tests_out, per_test = worker.tap_summary(output, "kselftest-riscv")
    print("tap summary:", summary, "per_test:", per_test)
    check(summary["failed"] == 1, summary)
    body = worker.lava_body("qemu-riscv64", 0, output, fake_args(),
                            tap=("kselftest-riscv", summary, per_test))
    with open("/tmp/lava-body-kselftest-fail.json", "w") as f:
        json.dump(body, f, indent=1)

    cb = Callback(body)
    check(cb.get_job_status() == "pass",
          "job completed: status stays 2, the hierarchy carries the fail")
    results = cb.get_results()
    print("get_results:", results)
    check(results["kselftest.riscv"]["mm"] == "fail", results)
    check(results["kselftest.riscv"]["vector"] == "pass", results)
    check(results["kselftest.riscv"]["hwprobe"] == "skip", results)

    job_node = {"id": "test", "name": "kselftest-riscv-pull-labs",
                "result": "pass", "data": {}, "artifacts": {}}
    hierarchy = cb.get_hierarchy(results, job_node)
    print("get_hierarchy job result:", hierarchy["node"]["result"])
    print("child nodes:", [c["node"]["name"] for c in hierarchy["child_nodes"]])
    check(hierarchy["node"]["result"] == "fail", hierarchy)
    print("FAIL-carrying TAP flips the job node to fail: OK")

    # Same TAP with every test passing must stay pass.
    output_pass = (
        "2026-09-08T00:00:00 lava-dispatcher, installed at version: 2026.05\n"
        "ok 1 selftests: riscv: vector\n"
        "ok 2 selftests: riscv: hwprobe\n"
    )
    summary, _tests_out, per_test = worker.tap_summary(output_pass, "kselftest-riscv")
    check(summary["failed"] == 0, summary)
    body = worker.lava_body("qemu-riscv64", 0, output_pass, fake_args(),
                            tap=("kselftest-riscv", summary, per_test))
    cb = Callback(body)
    job_node = {"id": "test", "name": "kselftest-riscv-pull-labs",
                "result": "pass", "data": {}, "artifacts": {}}
    hierarchy = cb.get_hierarchy(cb.get_results(), job_node)
    check(hierarchy["node"]["result"] == "pass", hierarchy)
    print("All-pass TAP keeps the job node pass: OK")


def run_no_tap_case():
    """A kselftest job whose tuxrun run failed before any test ran (no TAP
    lines, e.g. artifacts the dispatcher cannot reach) must NOT become a
    pass node: no TAP -> suite fail, JobError -> infrastructure."""
    print("\n===== kselftest no-TAP + JobError -> incomplete/infra =====")
    output = (
        "2026-09-08T00:00:00 Resource not available: Connection refused\n"
        "2026-09-08T00:00:00 JobError: Your job cannot terminate cleanly.\n"
        "2026-09-08T00:00:00 {'definition': 'lava', 'case': 'job', "
        "'result': 'fail'}\n"
    )
    check(worker.tuxrun_job_error(1, output), "JobError must be detected")
    summary, tests_out, per_test = worker.tap_summary(output, "kselftest-kvm")
    print("tap summary:", summary, tests_out)
    check(summary["failed"] == 1, summary)
    check(tests_out["kselftest-kvm"]["status"] == "fail", tests_out)
    body = worker.lava_body("qemu-riscv64", 2, output, fake_args(),
                            tap=("kselftest-kvm", summary, per_test),
                            infra=True, error_msg=output)
    cb = Callback(body)
    check(cb.get_job_status() == "incomplete", cb.get_job_status())
    check(cb.is_infra_error(), "JobError must map to Infrastructure")
    print("no-TAP suite fail + JobError infra: OK")


def run_infra_case():
    """An infrastructure failure (tuxrun exit 2, e.g. unknown test class)
    must surface as error_type=Infrastructure on the job node."""
    print("\n===== infra error: rc=2 -> incomplete + Infrastructure =====")
    output = ("usage: tuxrun [options]\ntuxrun: error: argument --tests: "
              "invalid choice: 'kselftest-riscv'\n")
    body = worker.lava_body("qemu-riscv64", 2, output, fake_args(),
                            infra=True, error_msg=output)
    cb = Callback(body)
    check(cb.get_job_status() == "incomplete", cb.get_job_status())
    check(cb.is_infra_error() is True, "infra flag must set Infrastructure")
    print("is_infra_error:", cb.is_infra_error(), "-> OK")


run_case("pass", PASS_LOG, 0, "pass")
run_case("fail", FAIL_LOG, 1, "incomplete")
run_kselftest_tap_cases()
run_infra_case()
run_no_tap_case()
print("\nALL PARSER CHECKS PASSED")
