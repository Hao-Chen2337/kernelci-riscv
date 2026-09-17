"""Build and execute the tuxrun command line - the single copy.

Two entry points drive tuxrun and both assembled the same argv, so the assembly
and the execution live here instead of twice.  Preserved verbatim, do not
"tidy": the flag order (--runtime, --device, --kernel, --boot-args, --rootfs,
--modules, --tests, --parameters), one argv entry per --parameters value (a
value may contain spaces), --modules only for the kvm case, and stdout/stderr
captured separately and concatenated, never interleaved.  Nothing here prints -
the two callers log the command line with different wording.
Rationale: docs/code-notes/W2c-kcilib.md.
"""
import subprocess


def build_tuxrun_argv(*, tuxrun_bin, runtime, device, kernel,
                      boot_args="rw", rootfs=None, modules=None,
                      tests=None, parameters=None):
    """Assemble one tuxrun command line and return it as a list of str.

    Keyword-only, so both callers pass their own variables straight through
    with no reshaping.

    Omission rules, exactly as in the callers: --rootfs, --modules and --tests
    are each omitted when falsy, while --parameters is omitted only when it is
    None - an empty list still reaches tuxrun, which rejects it loudly, instead
    of the flag disappearing silently.  Rationale: docs/code-notes/W2c-kcilib.md.
    """
    argv = [
        tuxrun_bin,
        "--runtime",
        runtime,
        "--device",
        device,
        "--kernel",
        kernel,
        # Debian images ship an unconfigured fstab, so / mounts read-only and
        # the LAVA test shell dies writing results.  Harmless for buildroot.
        "--boot-args",
        boot_args,
    ]
    # An explicit --rootfs overrides the job definition's: the lab owns its
    # guest images (e.g. a local mirror when storage.kernelci.org is throttled).
    if rootfs:
        argv += ["--rootfs", rootfs]
    # Only kselftest-kvm needs modules.tar.xz (kvm.ko at boot); for
    # boot/kselftest-riscv it is a needless 100MB+ flaky dependency per job.
    if modules:
        argv += ["--modules", modules]
    if isinstance(tests, str):
        # A bare string would splat into one --tests entry per character; the
        # callers pass a list.
        tests = [tests]
    if tests:
        argv += ["--tests", *tests]
    if parameters is not None:
        argv += ["--parameters", *parameters]
    return argv


def run_tuxrun(argv, timeout=None, log_path=None, *, cwd=None,
               stream_separator="\n"):
    """Run a tuxrun argv and return the CompletedProcess for that run.

    ``subprocess.run(argv, capture_output=True, text=True, check=False)``:
    never through a shell, and a non-zero exit is a value, not an exception.

    *timeout* goes straight to subprocess.run (None: no timeout; the grace past
    the job timeout is the caller's business).  *cwd* is tuxrun's working
    directory, None inheriting the caller's.  *log_path*, when given, receives
    the merged console - partial output included on a timeout - and its parent
    directories are NOT created, so an unusable path raises OSError.

    *stream_separator* goes between the captured stdout and stderr, which are
    concatenated rather than interleaved: the worker writes "\n" (the default)
    and fetch-and-run-latest "" - two real, byte-different archived consoles.
    The timeout path needs no knob, both callers spell it the same way.

    ``returncode`` is None on a timeout (TimeoutExpired is swallowed: it is an
    infrastructure failure, not a test failure), ``stdout`` is the merged
    console and ``stderr`` is empty.  Rationale: docs/code-notes/W2c-kcilib.md.
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

    Shared by both exits of run_tuxrun: a timed-out run still produced a partial
    console worth keeping."""
    if not log_path:
        return
    with open(log_path, "w") as handle:
        handle.write(output)
