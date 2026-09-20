# SPDX-License-Identifier: LGPL-2.1-or-later
"""The tuxrun argv, and running it: one spelling, never a shell.

A timed-out run still returns the console it produced, and the whole process
group is killed.

接口形状（C++，只有声明）：include/kci/engine.hpp §11 Runner。
"""

import os
import re
import shlex
import signal
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import errors

if TYPE_CHECKING:
    from .config import RunConfig
    from .job import Job

# The wall clock a run gets when its caller names no timeout, and the extra it
# gets on top of the job's own timeout before we stop waiting for it.
TIMEOUT = 60 * 30
GRACE = 180

# The two test types whose flag set differs from the others.  `tests.TESTS` owns
# the catalogue; this module only knows how a name is spelled on the command line.
BOOT = "boot"
KSELFTEST_KVM = "kselftest-kvm"
# What a test type may look like, i.e. what tuxrun has a class for.
TEST_TYPE_RE = re.compile(r"[a-z0-9][a-z0-9-]*")

# Debian images ship an unconfigured fstab, so / mounts read-only and the LAVA
# test shell dies writing results.  Harmless for buildroot.
BOOT_ARGS = "rw"
# QEMU cpu properties when the caller names none; a KVM job needs the H extension.
CPU = "rv64,v=true,ssnpm=true"


@dataclass
class Result:
    """One tuxrun process: its exit status, and everything it printed."""

    returncode: int | None
    console: str


def argv(job: "Job", config: "RunConfig") -> tuple[list[str], str]:
    """`(argv, label)`: the tuxrun command line for one job, and its test name.

    Each artifact is the local copy `Job.make()` made when there is one, else the
    URL the definition names - so a definition the API sent runs against exactly
    what it says, and our own jobs run against the bytes we downloaded.
    """
    definition = job.definition()
    artifacts = _artifacts(definition)
    local = dict(job.local or {})
    test = _test_type(definition)
    _reject_test_type(test)
    command = [
        config.tuxrun_bin,
        "--runtime", config.container_runtime,
        "--device", config.device,
        "--kernel", _local(_artifact(local, artifacts, "kernel", test)),
        "--boot-args", BOOT_ARGS,
    ]
    # A test with no disk of its own boots tuxrun's built-in image; one that needs
    # a disk and has none is refused here rather than started without it.
    rootfs = "" if test == BOOT else _artifact(local, artifacts, "rootfs", test)
    if rootfs:
        command += ["--rootfs", _local(rootfs)]
    # kselftest-kvm is the only test that wants kvm.ko at boot, and a disk baked on
    # this machine already carries the modules (Build.rootfs(with_modules=True)) -
    # the --modules overlay lands after boot, which is too late.
    modules = str(local.get("modules") or artifacts.get("modules") or "")
    if test == KSELFTEST_KVM and modules and not _baked(local.get("rootfs") or ""):
        command += ["--modules", _local(modules)]
    if test != BOOT:
        command += ["--tests", test]
    parameters = _parameters(test, local, artifacts, config.params, job.params)
    command += ["--parameters", *parameters]
    return command, test


def execute(argv: Sequence[str], cwd: str | None = None,
            timeout: int = TIMEOUT) -> Result:
    """Run tuxrun once, from *cwd*, and return its exit status and console.

    `returncode` is None when the timeout hit, and the console collected up to
    that point comes back either way - a timed-out boot is exactly when it is
    worth reading.  A timeout kills the child's whole process group, because
    tuxrun's container runtime outlives tuxrun itself.
    """
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout + GRACE)
    except subprocess.TimeoutExpired:
        _kill(process)
        stdout, stderr = process.communicate()
        return Result(None, _console(stdout, stderr))
    return Result(process.returncode, _console(stdout, stderr))


def _artifacts(definition: dict) -> dict:
    """The definition's artifacts as `name -> path or URL`; {} for anything else."""
    artifacts = definition.get("artifacts")
    return artifacts if isinstance(artifacts, dict) else {}


def _test_type(definition: dict) -> str:
    """The definition's first test type, or `boot` when it names no test."""
    tests = definition.get("tests")
    if not isinstance(tests, (list, tuple)):
        return BOOT
    first = next((item for item in tests if isinstance(item, dict)), {})
    return str(first.get("type") or BOOT)


def _reject_test_type(test: str) -> None:
    """Refuse a test type tuxrun has no class for, before anything is spawned."""
    if not TEST_TYPE_RE.fullmatch(test):
        raise errors.ConfigError(f"invalid test type in job definition: {test!r}")


def _baked(rootfs: str) -> bool:
    """True for a guest disk on this machine: one `Build.rootfs()` prepared here."""
    return bool(rootfs) and "://" not in rootfs


def _artifact(local: dict, artifacts: dict, name: str, test: str) -> str:
    """One artifact that must be there: the local copy, else the definition's URL."""
    value = str(local.get(name) or artifacts.get(name) or "")
    if not value:
        raise errors.ConfigError(f"job definition has no {name} artifact for {test}")
    return value


def _local(value: str) -> str:
    """A local path as `file://`; a URL or a tuxrun `$BUILD/` path is left alone.

    tuxrun reads every path-ish option - and `--parameters KSELFTEST=` - through
    `tuxrun.utils.pathurlnone`, which read-only bind-mounts a local file into the
    container, so this deployment's artifacts are handed over where they lie and
    nothing is re-served over HTTP.
    """
    if "://" in value or value.startswith("$"):
        return value
    if not os.path.isabs(value):
        raise errors.ConfigError(f"artifact path is not absolute: {value!r}")
    return f"file://{value}"


def _parameters(test: str, local: dict, artifacts: dict, *overrides: dict) -> list[str]:
    """The `--parameters` values: cpu, then the test's own, then the callers' extras.

    One value is one argv element, spaces and all (`TST_CASENAME=kvm:a kvm:b`);
    a later override wins, so the job's own params beat the deployment's.
    """
    extras: dict = {}
    for override in overrides:
        extras.update(override or {})
    # These two are inputs to the spelling below, not tuxrun parameters.
    kvm_tests = _kvm_tests(extras.pop("kvm_tests", None))
    cpu = _cpu(str(extras.pop("cpu", "") or ""), test)
    values = []
    if cpu:
        values.append(f"cpu={cpu}")
    if test != BOOT:
        kselftest = _artifact(local, artifacts, "kselftest", test)
        values.append(f"KSELFTEST={_local(kselftest)}")
    # The exclusion list is `tests.KVM_SKIP_TESTS`; the bare names that survived it
    # arrive in `params["kvm_tests"]`, and LKFT hands this one value to
    # `run_kselftest.sh -t`.  No names means none are named: the whole collection.
    if test == KSELFTEST_KVM and kvm_tests:
        values.append("TST_CASENAME=" + " ".join(f"kvm:{name}" for name in kvm_tests))
    values += [f"{key}={value}" for key, value in extras.items()]
    return values


def _cpu(given: str, test: str) -> str:
    """The QEMU cpu property string: the caller's, else $QEMU_CPU, else the default."""
    cpu = given or os.environ.get("QEMU_CPU") or CPU
    if test == KSELFTEST_KVM and "h=" not in cpu:
        cpu += ",h=true"
    return cpu


def _kvm_tests(names: "Sequence[str] | str | None") -> list[str]:
    """The curated KVM test names, from a list or from a space-separated string."""
    if isinstance(names, str):
        return shlex.split(names)
    return [str(name) for name in names or ()]


def _kill(process: subprocess.Popen) -> None:
    """Kill the child's whole process group; start_new_session made it the leader."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:  # already gone; the reap that follows is what matters
        pass


def _console(stdout: str, stderr: str) -> str:
    """The two captured streams as one console, separated rather than interleaved."""
    return f"{stdout or ''}\n{stderr or ''}"
