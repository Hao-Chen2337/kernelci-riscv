"""Build and execute the tuxrun command line - the single copy.

Two entry points drive tuxrun: scripts/riscv_pull_worker.py (build_command +
run_command) and scripts/fetch-and-run-latest.py (run_once).  Both assembled
the same argv in the same order and both turned tuxrun's two output streams
into one console, so the assembly and the execution live here instead of
twice.

Preserved verbatim from those callers - do not "tidy" any of it:

  * argv[0] is the tuxrun executable, followed by --runtime, --device,
    --kernel, --boot-args, --rootfs, --modules, --tests, --parameters in
    exactly that order.
  * each --parameters value is its own argv entry and is never joined into
    one string: a value may itself contain spaces (``TST_CASENAME=kvm:a
    kvm:b`` is ONE entry), and ``" ".join(argv)`` is what both callers print
    and what the archived consoles in this repo show.
  * --modules is only ever passed for the kvm case; the *caller* decides
    (the worker drops it again when the modules are baked into the image).
  * stdout and stderr are captured separately and concatenated afterwards,
    never interleaved - see run_tuxrun.

Nothing in this module prints.  The worker prints ``Running: <cmd>`` and
fetch-and-run-latest prints ``running: <cmd>``; those two literals differ, so
they stay where they are.
"""
import subprocess


def build_tuxrun_argv(*, tuxrun_bin, runtime, device, kernel,
                      boot_args="rw", rootfs=None, modules=None,
                      tests=None, parameters=None):
    """Assemble one tuxrun command line and return it as a list of str.

    The keywords are explicit and keyword-only so both callers can pass their
    own variables straight through with no reshaping.

    kcilib.run.jobrun.build_command() (the worker path) - device is
    run_config.platform, runtime is runtime_name(run_config), kernel is the
    job's kernel artifact, tests is the collection list, and the kvm subset
    travels as ONE ``TST_CASENAME=kvm:a kvm:b`` parameter entry::

        build_tuxrun_argv(
            tuxrun_bin=run_config.tuxrun_bin, runtime=runtime_name(run_config),
            device=run_config.platform, kernel=kernel_url, boot_args="rw",
            rootfs=rootfs_arg, modules=modules_url, tests=tests,
            parameters=parameters)

    scripts/fetch-and-run-latest.py (run_once) - the executable is the module
    constant TUXRUN, the device is fixed at qemu-riscv64, kernel and rootfs
    are URLs served by its own artifact server, and TST_CASENAME is again one
    space-joined entry.  The "args" below is that script's OWN parsed command
    line: phase 4 moved the worker onto kcilib.core.config.RunConfig and left the
    one-shot fetch path on its own argparse namespace (see the config.py
    docstring for why the two are not one object yet)::

        build_tuxrun_argv(
            tuxrun_bin=TUXRUN, runtime=args.runtime, device="qemu-riscv64",
            kernel=f"{base}/Image", boot_args="rw",
            rootfs=f"file://{os.path.abspath(rootfs)}",
            modules=modules and f"{base}/modules.tar.xz",
            tests=TESTS[args.test], parameters=params)

    Omission rules, exactly as in the callers:

    * ``boot_args`` defaults to "rw"; both callers pass "rw" literally.
    * --rootfs is omitted when rootfs is falsy (the boot job with no rootfs),
      --modules when modules is falsy, and --tests when tests is falsy (the
      boot case: neither caller passes --tests at all).
    * --parameters is omitted when ``parameters is None``; a list is passed
      through unchanged, empty list included, because both callers append the
      flag unconditionally.  An empty list therefore still reaches tuxrun,
      which rejects it loudly, instead of the flag disappearing silently.
    """
    argv = [
        tuxrun_bin,
        "--runtime",
        runtime,
        "--device",
        device,
        "--kernel",
        kernel,
        # Debian images (e.g. trixie-kselftest) ship an UNCONFIGURED
        # fstab with no root entry, so the kernel mounts / read-only
        # and systemd never remounts it; the LAVA test shell then dies
        # with "Read-only file system" when writing results.  rw is
        # harmless for images that remount themselves (buildroot).
        "--boot-args",
        boot_args,
    ]
    # An explicit --rootfs overrides whatever the job definition carries:
    # the lab owns its guest images (e.g. point at a local mirror when
    # storage.kernelci.org is throttled).
    if rootfs:
        argv += ["--rootfs", rootfs]
    # modules.tar.xz is only needed by kselftest-kvm (kvm.ko loaded at
    # boot).  For boot/kselftest-riscv it is a needless 100MB+ download
    # that adds a flaky network dependency per job - skip it.
    if modules:
        argv += ["--modules", modules]
    if isinstance(tests, str):
        # A bare string would splat into one --tests entry per character: a
        # silently wrong command line is worse than refusing, and the callers
        # pass a list.
        tests = [tests]
    if tests:
        argv += ["--tests", *tests]
    if parameters is not None:
        argv += ["--parameters", *parameters]
    return argv


def run_tuxrun(argv, timeout=None, log_path=None, *, cwd=None,
               stream_separator="\n"):
    """Run a tuxrun argv and return the CompletedProcess for that run.

    Same execution as both callers: ``subprocess.run(argv,
    capture_output=True, text=True, check=False)``, so tuxrun is never run
    through a shell and a non-zero exit is a value, not an exception.

    timeout
        Passed straight to subprocess.run; None means no timeout.  The worker
        passes ``timeout_s + 180`` (a little grace past the job timeout) and
        fetch-and-run-latest passes TUXRUN_TIMEOUT - the grace is the caller's
        business, not this function's.
    cwd
        Working directory for tuxrun; None inherits the caller's, which is
        what fetch-and-run-latest does.  The worker passes its per-job
        workspace.
    stream_separator
        Text placed between captured stdout and stderr when the run COMPLETES.
        Both callers concatenate the two streams instead of interleaving them,
        so a byte-for-byte identical console needs their exact separator: the
        worker writes ``f"{proc.stdout}\n{proc.stderr}"`` (the default here)
        and fetch-and-run-latest writes ``proc.stdout + proc.stderr`` (pass
        "").  The difference is real and visible in this repo's own artifacts:
        the archived consoles under work/logs/ carry one blank line where the
        streams meet, the fetch-and-run-latest consoles under
        work/downloads/<build>/ carry none, because tuxrun's LAVA console goes
        to stdout and its urllib3 warnings ("403 Client Error: ...") go to
        stderr.  The timeout path needs no such knob: both callers spell it
        ``f"{error.stdout or ''}\n{error.stderr or ''}"``, which is what
        happens here unconditionally.
    log_path
        When given, the merged console is written there with
        ``open(log_path, "w")`` - the same file both callers write today,
        partial output included on a timeout.  Missing parent directories are
        not created, exactly as before: a caller that hands over an unusable
        path gets an OSError rather than a run whose console vanished.
        Nothing is printed: the two callers log the command line themselves
        and with different wording.

    Returns a CompletedProcess whose ``returncode`` is None on a timeout
    (TimeoutExpired is swallowed here because that is what both callers do,
    and a timed-out run is an infrastructure failure, not a test failure),
    whose ``stdout`` is the merged console - the same bytes written to
    log_path, and what the callers hand to tap_summary / judge_run - and whose
    ``stderr`` is empty because the two streams were merged as they were
    captured.
    """
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = f"{error.stdout or ''}\n{error.stderr or ''}"
        _write_console_log(log_path, output)
        return subprocess.CompletedProcess(argv, None, output, "")
    output = f"{proc.stdout}{stream_separator}{proc.stderr}"
    _write_console_log(log_path, output)
    return subprocess.CompletedProcess(argv, proc.returncode, output, "")


def _write_console_log(log_path, output):
    """Write the console to log_path when one was asked for.

    Shared by both exits of run_tuxrun: a run that timed out still produced a
    partial console worth keeping (#2), so neither path may skip the write."""
    if not log_path:
        return
    with open(log_path, "w") as handle:
        handle.write(output)
