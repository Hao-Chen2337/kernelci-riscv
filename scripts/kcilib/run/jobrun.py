#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Job definition -> tuxrun argv -> run -> judge -> report body.

THIS MODULE DOES NOT KNOW THE API EXISTS: run_node(node, run_config, node_id)
takes the job definition the events API served plus a
kcilib.core.config.RunConfig and returns the (callback_url, token, body) report
tuple - the poll loop posts it.  A caller that never polled anything (a replay of
a saved job definition, an offline test) can run a node with a hand-built
RunConfig.  The console archive travels with run_node() because its ``finally``
is what keeps a real run's evidence alive past the per-job workspace.

WHAT IT DELEGATES, and why each seam stays where it is: judging is
kcilib.run.judge's three predicates plus tap_summary/tuxrun_error_message - NOT
judge_run(), whose timeout wording would change the error_msg a timed-out job
reports; the command line and its execution are kcilib.run.runner's (flag order,
the timeout+180 grace, stream_separator="\n"); the guest image is
kcilib.run.bake.baked_rootfs_image's, cache included; the progress printer is
kcilib.run.bake.stamp, which a caller may re-bind.  Nothing here reads a command
line.  Rationale: docs/code-notes/W2c-kcilib.md.
"""

import os
import re
import shutil
import tempfile
import time

from kcilib.core import config, ledger
from kcilib.core.params import cpu_for, kvm_tests_to_run
from kcilib.run import callback
from kcilib.run.artifacts import build_id_from_artifacts, kselftest_kvm_tests
from kcilib.run.bake import baked_rootfs_image, stamp
from kcilib.run.callback import lava_body, verdict_from_body
from kcilib.run.judge import (
    tap_summary,
    tuxrun_error_message,
    tuxrun_infra_error,
    tuxrun_invocation_error,
    tuxrun_job_error,
)
from kcilib.run.runner import build_tuxrun_argv, run_tuxrun

DEFAULT_TIMEOUT = 1800  # seconds, when the job def carries no timeout
# Bounds applied to whatever the job definition asked for.  The clamp used to be
# silent - a job killed early reported Infrastructure with nothing saying why -
# so both bounds have a name, a CLI flag and a logged line (see clamp_timeout).
# Defined in kcilib.core.config (with the flags that carry them) and imported
# here, so the run layer depends on core and not the other way round; the names
# stay attributes of this module for the callers that patch them.
MIN_TIMEOUT = config.MIN_TIMEOUT

# Newest archived consoles kept in LOG_DIR.  The console lives inside the
# per-job workspace and the workspace is deleted at the end of every job, so
# without this the only local copy of a real run disappeared with it.
LOG_ARCHIVE_KEEP = config.LOG_ARCHIVE_KEEP

TAR_SUFFIXES = (".tar", ".tar.gz", ".tar.xz", ".tgz")
TEST_TYPE_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def runtime_name(run_config):
    """Pick a container runtime tuxrun can drive (podman preferred)."""
    if run_config.container_runtime:
        return run_config.container_runtime
    return "podman" if shutil.which("podman") else "docker"


def _test_entries(node):
    """A definition's dict test entries - the safe reading of ``node["tests"]``.

    Returns [] for anything that is not a list of dicts.  Both lookups that read
    this list OUTSIDE run_node's try use it (the timeout below, and
    kcilib.core.ledger.test_of which names the record): a definition the API
    queued with a string, a null, a number or no list at all must cost at most an
    infra report, never an exception escaping run_node - poll.handle_event reads
    an escaping exception as "handled" and marks the node seen, so the run is
    never posted and never retried.
    """
    tests = node.get("tests")
    if not isinstance(tests, (list, tuple)):
        return []
    return [test for test in tests if isinstance(test, dict)]


def build_command(node, run_config, workspace):
    """Map a job definition onto a tuxrun argv; bakes a disk rootfs if the
    artifact is a tarball.  Returns (argv, label) or raises KeyError."""
    node_artifacts = node.get("artifacts", {})
    tests = node.get("tests", []) or [{}]
    test = tests[0]
    test_type = test.get("type") or "boot"
    if not TEST_TYPE_RE.fullmatch(test_type):
        raise KeyError(f"invalid test type in job definition: {test_type!r}")
    kernel_url = node_artifacts.get("kernel")
    if not kernel_url:
        raise KeyError("job definition has no kernel artifact")

    parameters = [f"cpu={cpu_for(run_config.cpu, test_type)}"]

    # An explicit --rootfs overrides the job definition's: the lab owns its
    # guest images (e.g. a local mirror when storage.kernelci.org is throttled).
    rootfs_url = run_config.rootfs or node_artifacts.get("rootfs")
    if not rootfs_url and node_artifacts.get("ramdisk"):
        print(
            "Warning: job definition carries a cpio ramdisk; the qemu "
            "device cannot boot it - using tuxrun's built-in disk "
            "(pass --rootfs to override)"
        )
    boot_modules = ["kvm"] if test_type == "kselftest-kvm" else None
    modules_url = (
        node_artifacts.get("modules") if test_type == "kselftest-kvm" else None
    )
    rootfs_arg = None
    if rootfs_url and rootfs_url.endswith(TAR_SUFFIXES):
        image = baked_rootfs_image(
            workspace,
            rootfs_url,
            test_type,
            boot_modules=boot_modules,
            modules_url=modules_url,
            max_size=run_config.max_download_size,
        )
        rootfs_arg = f"file://{image}"
        # Already baked in; the --modules LAVA overlay lands after boot, too late.
        modules_url = None
    elif rootfs_url:
        rootfs_arg = rootfs_url
    elif test_type != "boot":
        raise KeyError("job definition has no rootfs for a kselftest job")

    label = test_type
    test_args = None
    if test_type != "boot":
        kselftest_url = node_artifacts.get("kselftest")
        if not kselftest_url:
            raise KeyError("job definition has no kselftest artifact")
        parameters.append(f"KSELFTEST={kselftest_url}")
        test_args = [test_type]
        if test_type == "kselftest-kvm":
            # Exclusion, not an allow-list: LKFT hands TST_CASENAME to
            # `run_kselftest.sh -t`.  The list is everything the build's own
            # kselftest tarball ships minus KVM_SKIP_TESTS, so a test an older
            # kernel never built is simply absent instead of failing the suite
            # with "No such test".  LKFT's "modules" test must NOT be named
            # here - it unloads kvm again before kselftest runs.
            if run_config.kvm_full:
                # whole collection: no TST_CASENAME; LKFT runs every kvm test.
                pass
            elif run_config.kvm_tests:
                # explicit override: a hand-named list, used verbatim.
                parameters.append(
                    "TST_CASENAME="
                    + " ".join(f"kvm:{name}" for name in run_config.kvm_tests)
                )
            else:
                present = kselftest_kvm_tests(
                    kselftest_url, max_size=run_config.max_download_size)
                to_run = kvm_tests_to_run(present)
                if not to_run:
                    # No kvm collection, or every test is excluded: run the whole
                    # collection so the gap surfaces, rather than an empty -t.
                    print("Warning: no runnable kvm tests in the build's "
                          "kselftest tarball; running the whole collection")
                else:
                    parameters.append(
                        "TST_CASENAME="
                        + " ".join(f"kvm:{name}" for name in to_run)
                    )
    # Flag order and the --rootfs/--modules/--tests omission rules live in
    # kcilib.run.runner.build_tuxrun_argv.
    argv = build_tuxrun_argv(
        tuxrun_bin=run_config.tuxrun_bin,
        runtime=runtime_name(run_config),
        device=run_config.platform,
        kernel=kernel_url,
        boot_args="rw",
        rootfs=rootfs_arg,
        modules=modules_url,
        tests=test_args,
        parameters=parameters,
    )
    return argv, label


def run_command(cmd, timeout_s, workspace):
    """Run tuxrun, capture its output into the workspace log and return
    (returncode, output).  returncode is None when the run timed out; the
    partial output is still written to the log."""
    log_path = os.path.join(workspace, "tuxrun.log")
    print("Running:", " ".join(cmd))
    proc = run_tuxrun(
        cmd,
        timeout=timeout_s + 180,  # a little grace past the job timeout
        log_path=log_path,
        cwd=workspace,
        stream_separator="\n",
    )
    return proc.returncode, proc.stdout


def prune_console_logs(log_dir, keep=LOG_ARCHIVE_KEEP):
    """Keep only the newest *keep* archived consoles in *log_dir*.

    Consoles are hundreds of KB each and a resident lab runs hundreds of jobs a
    month, so the archive is bounded by count and pruned oldest-first.  Only
    this module's own ``<node id>.log`` files are considered; returns the names
    it removed."""
    try:
        names = [
            name
            for name in os.listdir(log_dir)
            if re.fullmatch(r"[A-Za-z0-9._-]+\.log", name)
        ]
    except OSError:
        return []
    entries = []
    for name in names:
        try:
            entries.append((os.path.getmtime(os.path.join(log_dir, name)), name))
        except OSError:
            continue
    entries.sort()
    removed = []
    for _mtime, name in entries[: max(0, len(entries) - keep)]:
        try:
            os.unlink(os.path.join(log_dir, name))
            removed.append(name)
        except OSError:
            pass
    if removed:
        print(f"Pruned {len(removed)} archived console log(s) from {log_dir} "
              f"(keeping the newest {keep})")
    return removed


def archive_console_log(workspace, log_dir, node_id):
    """Copy the job's tuxrun console out of the workspace before it is removed.

    The workspace is deleted at the end of every job, so without this the only
    local copy of a real run's console disappeared with it.  Returns the
    archived path, or "" when there was no console; raises OSError when the copy
    fails, so the caller keeps the workspace instead of deleting the evidence."""
    if not log_dir or not node_id:
        return ""
    source = os.path.join(workspace, "tuxrun.log")
    if not os.path.isfile(source):
        return ""
    # The node id comes from the API and becomes a filename: keep it safe.
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(node_id))
    if not safe_id:
        return ""
    os.makedirs(log_dir, exist_ok=True)
    target = os.path.join(log_dir, f"{safe_id}.log")
    shutil.copyfile(source, target)
    prune_console_logs(log_dir)
    return target


def clamp_timeout(timeout_s, max_timeout, min_timeout=MIN_TIMEOUT):
    """Apply the worker's timeout bounds and report it when they bite.

    Returns (effective_timeout, note); note is "" when nothing was clamped.
    Clamping is intended - a definition must not run forever - but it must never
    be silent, or an early kill reads as a job that genuinely needed more time."""
    effective = max(min_timeout, min(timeout_s, max_timeout))
    if effective == timeout_s:
        return effective, ""
    if timeout_s > max_timeout:
        return effective, (
            f"job timeout {timeout_s}s reduced to {effective}s "
            f"(--max-timeout {max_timeout}); the job definition asked for more"
        )
    return effective, (
        f"job timeout {timeout_s}s raised to {effective}s "
        f"(--min-timeout {min_timeout})"
    )


# Who filed the ledger record.  Hardcoding "worker" filed local-job-table runs as
# if the resident worker had taken them; the field is only worth having if true.
SOURCE_WORKER = "worker"
SOURCE_TABLE = "table"


def record_result(node, node_id, body, tap, log_path, source=SOURCE_WORKER):
    """File this run in the durable ledger and return the path written.

    kcilib.core.ledger owns the layout and the key set; this is the worker's
    NAMING of the run, written for every outcome - a failed run is exactly the
    one worth having a record of.  The build comes from the job's artifact URLs,
    or the node id when no URL names one (a made-up id would be worse).  The
    verdict comes from the callback BODY, not from a second look at the console,
    so record and pipeline cannot disagree.  A failed write is reported and
    returned as "", never raised.  The test name is kcilib.core.ledger.test_of -
    one owner, and it never raises, so a malformed definition cannot cost the node
    its callback (see that function).
    """
    test = ledger.test_of(node)
    # The artifacts must be a mapping before the build id is parsed out of them:
    # this is the other outside-the-try lookup, and a definition whose artifacts
    # is a string or a number would raise here and cost the node its callback.
    artifacts = node.get("artifacts")
    build_id = (
        build_id_from_artifacts(artifacts) if isinstance(artifacts, dict) else ""
    ) or node_id or ""
    if not build_id:
        print("Warning: no build id in the job's artifacts and no node id; "
              "the run is NOT recorded in work/results")
        return ""
    verdict, exit_code, detail = verdict_from_body(body)
    summary = tap[1] if tap else None
    try:
        return ledger.write_result(build_id, test, {
            "job": node.get("name") or node_id or "",
            "source": source,
            "verdict": verdict,
            "exit_code": exit_code,
            "detail": detail,
            "log": _relative_to_repo(log_path),
            "results": summary,
        })
    except (OSError, ValueError) as error:
        print(f"Warning: could not record this run in the result ledger "
              f"({error}); the callback is unaffected")
        return ""


def _relative_to_repo(path):
    """*path* relative to the repository root, or as given when it is outside.

    The one-shot runner stores repository-relative paths in the same field, so a
    reader lining the two writers' rows up must not have to guess.
    """
    if not path:
        return None
    try:
        return os.path.relpath(path, ledger.ROOT)
    except ValueError:  # different drive on Windows; keep the path as given
        return path

def run_node(node, run_config, node_id=None, source=SOURCE_WORKER):
    """Execute one job definition in a per-job workspace and return the
    report tuple (callback_url, token, body); the caller posts it.  Every
    failure inside becomes an infra-error LAVA body, so a report is always
    produced (unless the workspace itself cannot be created).

    *node* is a job definition as the events API served it and *run_config* a
    kcilib.core.config.RunConfig - the API is not one of them.  *node_id* labels
    the progress lines and names the archived console log."""
    environment = node.get("environment", {})
    system = environment.get("platform", run_config.platform)
    # Both come from kcilib.run.callback, which owns "where does this result go":
    # sink.CallbackSink.wants() reads the same URL helper, and the token is read
    # from the environment by the same function for the first post and for every
    # re-post from the state file.  The results are named report_* here because
    # run_node used to hold a local named callback (the definition's callback
    # section), which would shadow the module and defeat the call.
    report_url = callback.callback_url(node)
    report_token = callback.callback_token()
    # Only dict entries are read, via the same safe reading as the ledger naming:
    # this runs OUTSIDE the try below, so a tests entry that is a string or None
    # (the API queues those too) used to raise AttributeError right here and cost
    # the node its result.
    timeout_s = next(
        (
            test.get("timeout_s")
            for test in _test_entries(node)
            if test.get("timeout_s")
        ),
        DEFAULT_TIMEOUT,
    )
    timeout_s, clamp_note = clamp_timeout(
        timeout_s, run_config.max_timeout, run_config.min_timeout
    )
    if clamp_note:
        # Announced before anything runs: the effective timeout is the number to
        # look at first after a kill.
        stamp(f"{node_id or 'job'}: {clamp_note}")

    own_base = not run_config.output_dir
    base = run_config.output_dir or tempfile.mkdtemp(prefix="riscv-pull-")
    workspace = os.path.join(base, f"job-{time.time_ns()}")
    os.makedirs(workspace, exist_ok=True)
    returncode, output = 3, ""
    tap = None
    infra = False
    error_msg = ""
    # Set by the finally block below; the ledger record names it, so a reader
    # reaches the evidence from the record.
    archived = None
    try:
        started = time.time()
        cmd, label = build_command(node, run_config, workspace)
        stamp(f"{label}: guest prepared in {time.time() - started:.1f}s "
              "(artifact download + ext4 bake)")
        started = time.time()
        returncode, output = run_command(cmd, timeout_s, workspace)
        stamp(f"{label}: tuxrun finished in {time.time() - started:.1f}s "
              f"(exit {returncode})")
        if returncode is None:
            # Timed out; the partial console output is preserved in the log.
            infra = True
            error_msg = "tuxrun timed out"
        elif (
            tuxrun_invocation_error(returncode, output)
            or tuxrun_job_error(returncode, output)
            or tuxrun_infra_error(returncode, output)
        ):
            # e.g. a missing tuxlava class, artifacts the dispatcher cannot
            # reach, or the serial connection dying mid-run: report an infra
            # error, with a reason built for the callback's 200-character window.
            infra = True
            error_msg = tuxrun_error_message(output, label)
        if label.startswith("kselftest-"):
            # tuxrun returns 0 even when selftests fail, so judge from the TAP;
            # computed even on infra failures, so a suite that died mid-run keeps
            # the per-test results it produced.
            summary, _tests_out, per_test = tap_summary(output, label)
            tap = (label, summary, per_test)
    except Exception as error:  # noqa: BLE001 - any failure becomes an infra-error report
        print(f"Job failed in preparation/execution: {error}")
        infra = True
        error_msg = str(error)
    finally:
        keep_workspace = run_config.keep_workspace
        try:
            archived = archive_console_log(workspace, run_config.log_dir,
                                           node_id)
        except OSError as error:
            # The workspace is now the only copy of the run: keep it rather than
            # delete the evidence.
            keep_workspace = True
            print(
                f"Warning: could not archive the console log to "
                f"{run_config.log_dir} ({error}); keeping the workspace at "
                f"{workspace}"
            )
        else:
            if archived:
                stamp(f"{node_id or 'job'}: console log kept at {archived}")
        if not keep_workspace:
            if own_base:
                shutil.rmtree(base, ignore_errors=True)
            else:
                shutil.rmtree(workspace, ignore_errors=True)
    body = lava_body(
        system,
        returncode,
        output,
        run_config,
        tap=tap,
        infra=infra,
        error_msg=error_msg,
    )
    # Filed next to the one-shot runner's rows, before the caller posts, so a
    # callback that never lands still leaves a record of what ran.
    record = record_result(node, node_id, body, tap, archived, source=source)
    if record:
        stamp(f"{node_id or 'job'}: recorded in {_relative_to_repo(record)}")
    return report_url, report_token, body
