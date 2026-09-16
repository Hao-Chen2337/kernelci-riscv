#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Job definition -> tuxrun argv -> run -> judge -> report body.

The middle of the worker's job path, moved VERBATIM out of
scripts/riscv_pull_worker.py: the bodies, the comments and every printed line
are the worker's own - only the imports are new.  ``build_command()`` maps a
job definition onto a tuxrun argv (baking a disk rootfs out of a tarball
artifact when the job carries one), ``run_command()`` runs it and captures the
console into the workspace, ``run_node()`` drives the two and turns the outcome
into a LAVA callback body.  The console archive (``archive_console_log()`` and
``prune_console_logs()``) travels with them because run_node's ``finally`` is
what keeps a real run's evidence alive past the per-job workspace that held it
(#6).

THIS MODULE DOES NOT KNOW THE API EXISTS.  ``run_node(node, run_config)`` takes
the job definition the events API served plus a kcilib.config.RunConfig and
returns the report tuple; fetching nodes, the cursor and the flock are
kcilib.poll's business, and the poll loop hands this function its config rather
than this module reaching for anything global.  A caller that has never polled
anything (a replay of a saved job definition, an offline test) can run a node
with a RunConfig it built by hand.

WHAT IT DELEGATES - and why each seam has to stay exactly where it is:

* the judging is kcilib.judge's, and specifically the three predicates
  (``tuxrun_invocation_error`` / ``tuxrun_job_error`` / ``tuxrun_infra_error``)
  plus ``tap_summary`` and ``tuxrun_error_message``.  NOT ``judge_run``: its
  timeout wording differs, and swapping it in would change the ``error_msg``
  that reaches the callback for a timed-out job;
* the command line is ``kcilib.runner.build_tuxrun_argv`` (flag order, the rw
  boot-args rationale and the --rootfs/--modules/--tests omission rules live
  there) and the execution is ``kcilib.runner.run_tuxrun`` - the worker's
  ``timeout_s + 180`` grace, the workspace as cwd, and
  ``stream_separator="\n"`` so the console keeps its blank line where stdout
  and stderr meet;
* the guest image is ``kcilib.bake.baked_rootfs_image``: the same bake and the
  same cache the worker used to own, so "guest prepared in Ns" and the bake
  cache lines are unchanged;
* the progress printer is imported from ``kcilib.bake.stamp`` (the shared
  implementation) instead of being copied a third time.  Its ``[HH:MM:SS] ``
  line is byte-identical to the worker's own stamp(), and a caller that
  re-binds ``kcilib.bake.stamp`` - or this module's ``stamp`` - moves every
  line of this module with it, exactly as the offline guard tests re-bind
  module attributes;
* ``run_node()`` does NOT post the result: it returns the
  ``(callback_url, token, body)`` tuple and the poll loop posts it.  The token
  is read from the environment here and is never persisted (kcilib.callback).

Nothing was "tidied": the archived consoles under work/logs, the printed
lines and the state file are test fixtures.  Every string, comment and
f-string below is the worker's, character for character.

The worker's CLI (kcilib/cli.py) and the flag -> field mapping
(kcilib/config.py) are the only things above this module; nothing here reads a
command line, and no field is named after a flag.
"""

import os
import re
import shutil
import tempfile
import time

from kcilib.bake import baked_rootfs_image, stamp
from kcilib.callback import lava_body
from kcilib.judge import (
    tap_summary,
    tuxrun_error_message,
    tuxrun_infra_error,
    tuxrun_invocation_error,
    tuxrun_job_error,
)
from kcilib.params import KVM_TEST_SUBSET, cpu_for, kvm_allow_list
from kcilib.runner import build_tuxrun_argv, run_tuxrun

DEFAULT_TIMEOUT = 1800  # seconds, when the job def carries no timeout
# Bounds applied to whatever the job definition asked for.  The clamp used to
# be a silent max(60, min(timeout_s, config.max_timeout)): a definition asking
# for 1800s was cut to the 1200s the shell entry points pass, the job was
# killed at 20 minutes and reported as Infrastructure, and nothing in the log
# said the timeout had been reduced.  Both bounds now have a name, a CLI flag
# and a line of their own the moment they bite (see clamp_timeout).
MIN_TIMEOUT = 60  # floor: below this tuxrun cannot even boot a guest

# Where the per-job tuxrun console is archived before its workspace is removed
# (#6): the console is written inside the workspace and the workspace is
# deleted at the end of every job, so the only local copy of a real run used to
# disappear with it - all that survived was the callback's LOG_LIMIT-capped
# copy, and nothing at all when the callback failed.  Anchored to the
# repository root rather than the CWD, so "the logs are in work/logs" holds
# whatever directory the worker was started from (work/ is the gitignored tree
# this repo already treats as durable).
LOG_ARCHIVE_KEEP = 200  # newest archived consoles kept in LOG_DIR

TAR_SUFFIXES = (".tar", ".tar.gz", ".tar.xz", ".tgz")
TEST_TYPE_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def runtime_name(run_config):
    """Pick a container runtime tuxrun can drive (podman preferred)."""
    if run_config.container_runtime:
        return run_config.container_runtime
    return "podman" if shutil.which("podman") else "docker"


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

    # An explicit --rootfs overrides whatever the job definition carries:
    # the lab owns its guest images (e.g. point at a local mirror when
    # storage.kernelci.org is throttled).
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
        # Modules are already inside the baked image; the --modules LAVA
        # overlay lands after boot and cannot load kvm.ko at boot time.
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
            # Curated subset instead of the whole collection: the LKFT
            # script hands TST_CASENAME to `run_kselftest.sh -t`, which
            # matches each kvm:name entry exactly (allow-list).  kvm.ko is
            # loaded at boot: modules.tar.xz is baked into /lib/modules and
            # a modules-load.d conf modprobes it (see bake_rootfs_image).
            # The LKFT "modules" test is a load/unload round-trip and must
            # NOT be used here (verified: it unloads kvm again before
            # kselftest runs).
            if run_config.kvm_full:
                # whole collection: no allow-list; LKFT runs every kvm test.
                pass
            else:
                subset = list(run_config.kvm_tests or KVM_TEST_SUBSET)
                parameters.append(
                    "TST_CASENAME=" + (
                        # the curated list itself is kcilib.params' business
                        kvm_allow_list() if subset == KVM_TEST_SUBSET
                        else " ".join(f"kvm:{name}" for name in subset)
                    )
                )
    # Flag order, the rw boot-args rationale (Debian images mount / read-only
    # without it) and the omission rules for --rootfs/--modules/--tests all
    # live in kcilib.runner.build_tuxrun_argv.
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

    Archiving every job's console is a real disk cost (one 25-minute kselftest
    console is hundreds of KB, and a resident lab runs hundreds of jobs a
    month), so the archive is bounded by count and pruned oldest-first - the
    same shape as prune_bake_cache.  Only ``<node id>.log`` files this module
    writes are considered, so a hand-placed file in the same directory is never
    removed.  Returns the names it removed."""
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

    The console is written inside the per-job workspace and the workspace is
    deleted at the end of every job unless --keep-workspace is passed - which
    neither shell entry point does - so the only local copy of a real run's
    console used to disappear with it (#6).  All that survived was the copy
    embedded in the callback body, capped at LOG_LIMIT, and nothing at all when
    the callback itself failed.

    Returns the archived path, or "" when the job produced no console.  Raises
    OSError when the copy itself fails, so the caller can keep the workspace
    instead of deleting the last copy of the evidence."""
    if not log_dir or not node_id:
        return ""
    source = os.path.join(workspace, "tuxrun.log")
    if not os.path.isfile(source):
        return ""
    # The node id comes from the API and ends up in a filename: keep it to
    # characters that cannot escape the log directory.
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

    Clamping a job definition's timeout is intended (a definition must not be
    able to run forever), but it used to be silent: a definition asking for
    1800s, cut to the 1200s the shell entry points pass, was killed at 20
    minutes and reported as Infrastructure with nothing in the log saying the
    timeout had been reduced - indistinguishable from a job that genuinely
    needs more time.  Both bounds are now named, both are CLI flags
    (--min-timeout / --max-timeout) and every clamp is announced.  (#15)"""
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


def run_node(node, run_config, node_id=None):
    """Execute one job definition in a per-job workspace and return the
    report tuple (callback_url, token, body); the caller posts it.  Every
    failure inside is converted into an infra-error LAVA body, so a report
    is always produced (unless the workspace itself cannot be created).

    *node* is a job definition exactly as the events API served it and
    *run_config* is a kcilib.config.RunConfig - the two things a run needs, and
    the API is not one of them.  *node_id* labels the progress lines and names
    the archived console log (see archive_console_log)."""
    environment = node.get("environment", {})
    system = environment.get("platform", run_config.platform)
    callback = node.get("callback", {})
    callback_url = callback.get("url")
    # The callback token is a "remote token" name shared with the pipeline
    # admins; the worker holds the secret in an env var.
    callback_token = os.environ.get("PULL_LABS_CALLBACK_TOKEN")
    timeout_s = next(
        (
            t.get("timeout_s")
            for t in node.get("tests", [])
            if t.get("timeout_s")
        ),
        DEFAULT_TIMEOUT,
    )
    timeout_s, clamp_note = clamp_timeout(
        timeout_s, run_config.max_timeout, run_config.min_timeout
    )
    if clamp_note:
        # Announced once per job, before anything runs: the effective timeout
        # is the number to look at first when a job comes back Infrastructure
        # after a kill (#15).
        stamp(f"{node_id or 'job'}: {clamp_note}")

    own_base = not run_config.output_dir
    base = run_config.output_dir or tempfile.mkdtemp(prefix="riscv-pull-")
    workspace = os.path.join(base, f"job-{time.time_ns()}")
    os.makedirs(workspace, exist_ok=True)
    returncode, output = 3, ""
    tap = None
    infra = False
    error_msg = ""
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
            # e.g. kselftest-riscv before the tuxlava class lands upstream,
            # artifacts the dispatcher container cannot reach, or the serial
            # connection dying mid-run: report an infra error with the reason.
            # The reason is built for the callback's 200-character window
            # instead of being sliced out of the tail of a 7KB argparse line.
            infra = True
            error_msg = tuxrun_error_message(output, label)
        if label.startswith("kselftest-"):
            # tuxrun returns 0 even when selftests fail; judge from the TAP.
            # Computed even on infra failures, so a suite that died mid-run
            # keeps the per-test results it produced.
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
            # Keep the workspace when its console could not be archived: it is
            # the only surviving copy of the run, and deleting it is exactly
            # the evidence loss this archiving exists to stop (#6).
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
    return callback_url, callback_token, body
