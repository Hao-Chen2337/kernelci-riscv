"""The run path: job definition -> argv -> console, and the timeout clamp."""
import os
import tempfile

from kcilib.core import cli, config, params
from kcilib.run import artifacts, jobrun

from .support import check


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
