"""The run path: job definition -> argv -> console, and the timeout clamp."""
import os
import tempfile

from kcilib.core import cli, config, ledger
from kcilib.run import artifacts, jobrun

from .support import check


def test_build_command_validation():
    run_config = config.RunConfig(
        tuxrun_bin="tuxrun", platform="qemu-riscv64", rootfs="",
        cpu="rv64,v=true", container_runtime="",
        kvm_tests=None,
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
          and defaults.run.kvm_tests is None,
          f"the CLI defaults drifted from the config defaults: {defaults}")
    print("test_build_command_validation OK")


def test_build_command_argv():
    """The tuxrun argv is a contract with no other guard: pin it, entry by entry.

    Two entry points print this command line and this repository's archived
    consoles quote it, but until now the only thing covered about build_command
    was that an invalid test type is rejected - the flag ORDER, the
    --rootfs/--modules/--tests omission rules and the one-entry-per-parameter rule
    were prose in kcilib/run/runner.py.  A refactor that "tidied" any of them
    would have passed ./run.sh verify and only shown up when a real job ran.

    Everything below is stubbed that would download or bake (a 4GB mkfs.ext4, a
    100MB kselftest tarball): this guard is about the argv, not the artifacts.
    """
    jobrun.baked_rootfs_image = lambda *_a, **_k: "/tmp/baked.ext4"
    presented = ("memslot_modification_stress_test", "kvm_create_vm",
                 "dirty_log_perf_test", "set_memory_region_test")
    jobrun.kselftest_kvm_tests = lambda _url, max_size=None: presented

    def run_config(**over):
        fields = {
            "tuxrun_bin": "tuxrun", "platform": "qemu-riscv64", "rootfs": "",
            "cpu": "rv64", "container_runtime": "docker", "kvm_tests": None,
            "kvm_full": False, "max_download_size": (1 << 20),
        }
        fields.update(over)
        return config.RunConfig(**fields)

    derived_subset = ("TST_CASENAME=kvm:kvm_create_vm "
                      "kvm:set_memory_region_test")

    head = ["tuxrun", "--runtime", "docker", "--device", "qemu-riscv64",
            "--kernel", "http://x/Image", "--boot-args", "rw"]
    kvm_head = head + ["--rootfs", "http://x/r.ext4", "--modules",
                       "http://x/m.tar.xz"]
    riscv_artifacts = {"kernel": "http://x/Image",
                       "rootfs": "http://x/r.ext4",
                       "kselftest": "http://x/ks.tar.xz"}
    kvm_artifacts = dict(riscv_artifacts, modules="http://x/m.tar.xz")

    for name, job, run_cfg, expected in (
            # boot: no rootfs in the definition, so no --rootfs/--tests at all
            # (tuxrun's built-in disk), and the parameters list is never empty.
            ("boot", {"artifacts": {"kernel": "http://x/Image"},
                      "tests": [{"type": "boot"}]}, run_config(),
             head + ["--parameters", "cpu=rv64"]),
            # a cpio ramdisk in the definition is not bootable by the qemu
            # device: warned about, and NOT passed to tuxrun.
            ("boot with a ramdisk",
             {"artifacts": {"kernel": "http://x/Image",
                            "ramdisk": "http://x/initrd"},
              "tests": [{"type": "boot"}]}, run_config(),
             head + ["--parameters", "cpu=rv64"]),
            # kselftest: one --tests entry, KSELFTEST as its own parameter, and
            # no --modules (only kvm needs the module tarball).
            ("kselftest-riscv", {"artifacts": riscv_artifacts,
                                 "tests": [{"type": "kselftest-riscv"}]},
             run_config(),
             head + ["--rootfs", "http://x/r.ext4", "--tests",
                     "kselftest-riscv", "--parameters", "cpu=rv64",
                     "KSELFTEST=http://x/ks.tar.xz"]),
            # kvm: the cpu gains h=true, and a hand-named subset travels as ONE
            # --parameters entry (a joined string is what the callers print).
            ("kselftest-kvm with --kvm-tests",
             {"artifacts": kvm_artifacts, "tests": [{"type": "kselftest-kvm"}]},
             run_config(kvm_tests=["a", "b"]),
             kvm_head + ["--tests", "kselftest-kvm", "--parameters",
                         "cpu=rv64,h=true", "KSELFTEST=http://x/ks.tar.xz",
                         "TST_CASENAME=kvm:a kvm:b"]),
            # --kvm-full: the whole collection, so no TST_CASENAME (and no
            # tarball read at all - that is the point of the flag).
            ("kselftest-kvm --kvm-full",
             {"artifacts": kvm_artifacts, "tests": [{"type": "kselftest-kvm"}]},
             run_config(kvm_full=True),
             kvm_head + ["--tests", "kselftest-kvm", "--parameters",
                         "cpu=rv64,h=true", "KSELFTEST=http://x/ks.tar.xz"]),
            # default: derived from the build's own tarball minus KVM_SKIP_TESTS,
            # sorted; the stress/perf tests are in that skip list.
            ("kselftest-kvm derived from the tarball",
             {"artifacts": kvm_artifacts, "tests": [{"type": "kselftest-kvm"}]},
             run_config(),
             kvm_head + ["--tests", "kselftest-kvm", "--parameters",
                         "cpu=rv64,h=true", "KSELFTEST=http://x/ks.tar.xz",
                         derived_subset]),
            # a tar rootfs is baked to ext4 and passed as file://; the modules
            # are baked INTO it, so --modules must disappear again.
            ("kselftest-kvm with a baked tar rootfs",
             {"artifacts": dict(kvm_artifacts,
                                rootfs="http://x/r.tar.xz"),
              "tests": [{"type": "kselftest-kvm"}]}, run_config(),
             head + ["--rootfs", "file:///tmp/baked.ext4", "--tests",
                     "kselftest-kvm", "--parameters", "cpu=rv64,h=true",
                     "KSELFTEST=http://x/ks.tar.xz", derived_subset]),
    ):
        argv, label = jobrun.build_command(job, run_cfg, "/tmp/fake-workspace")
        check(argv == expected,
              f"{name}: the tuxrun argv changed.\n  got      {argv}\n"
              f"  expected {expected}")
        check(label == job["tests"][0]["type"], (name, label))

    # The omission rules are the half a reviewer cannot see in a passing run.
    boot_argv, _ = jobrun.build_command(
        {"artifacts": {"kernel": "http://x/Image"}, "tests": [{"type": "boot"}]},
        run_config(), "/tmp/fake-workspace")
    for flag in ("--rootfs", "--modules", "--tests"):
        check(flag not in boot_argv,
              f"boot must not pass {flag}: {boot_argv}")
    print("test_build_command_argv OK")


def test_run_node_never_raises_on_a_malformed_definition():
    """run_node must produce a report for ANY definition shape - never raise.

    Its own contract is "every failure inside becomes an infra-error LAVA body, so
    a report is always produced", and poll.handle_event depends on it: an
    exception escaping run_node is read as "handled", so the node is marked seen
    and the run is never posted and never retried.  Two lookups read node["tests"]
    OUTSIDE run_node's try - the timeout list and the ledger's naming - and an
    entry that is not a dict ({"tests": ["boot"]} is a definition the API queues
    too) raised AttributeError there.  This guard pins the behaviour, not the
    symptom: five malformed shapes, each must come back as a report.
    """
    with tempfile.TemporaryDirectory() as tmp:
        real_results_env = os.environ.get(ledger.RESULTS_DIR_ENV)
        os.environ[ledger.RESULTS_DIR_ENV] = os.path.join(tmp, "results")
        saved = (jobrun.build_command, jobrun.run_command,
                 jobrun.archive_console_log, jobrun.stamp)
        jobrun.build_command = lambda *_a, **_k: (["tuxrun"], "boot")
        jobrun.run_command = lambda *_a, **_k: (0, "")
        jobrun.archive_console_log = lambda *_a, **_k: ""
        jobrun.stamp = lambda *_a, **_k: None
        run_config = config.RunConfig(
            platform="qemu-riscv64", output_dir=os.path.join(tmp, "out"),
            log_dir=os.path.join(tmp, "logs"), tuxrun_bin="tuxrun",
            container_runtime="docker")
        try:
            for definition in (
                    {"tests": ["boot"]},
                    {"tests": [None]},
                    {"tests": 5},
                    {"tests": {"a": 1}},
                    {"tests": [{"type": "boot"}], "artifacts": 5},
                    {"tests": [{"type": "boot"}], "artifacts": {"kernel": 5}},
                    {},  # no tests key at all
            ):
                try:
                    report = jobrun.run_node(definition, run_config, "n1")
                except Exception as error:  # noqa: BLE001 - that is the failure
                    check(False,
                          f"run_node raised {type(error).__name__} for "
                          f"{definition!r}: an exception escaping it makes "
                          "poll.handle_event mark the node seen, so the result "
                          "is never posted and never retried")
                    continue
                check(isinstance(report, tuple) and len(report) == 3,
                      f"run_node must return a (url, token, body) report, got "
                      f"{report!r}")
                check(isinstance(report[2], dict) and report[2].get("status"),
                      f"the report for {definition!r} carries no body: {report!r}")
                # ledger.test_of names the record for the same definition and must
                # not raise either - it is called from inside record_result, which
                # is itself outside run_node's try.
                try:
                    named = ledger.test_of(definition)
                except Exception as error:  # noqa: BLE001 - that is the failure
                    check(False, f"ledger.test_of raised {type(error).__name__} "
                                 f"for {definition!r}: the record's name is read "
                                 "outside run_node's try too")
                    continue
                check(named, (definition, named))
        finally:
            (jobrun.build_command, jobrun.run_command,
             jobrun.archive_console_log, jobrun.stamp) = saved
            if real_results_env is None:
                os.environ.pop(ledger.RESULTS_DIR_ENV, None)
            else:
                os.environ[ledger.RESULTS_DIR_ENV] = real_results_env
    print("test_run_node_never_raises_on_a_malformed_definition OK")


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
