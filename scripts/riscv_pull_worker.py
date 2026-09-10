#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""RISC-V QEMU pull-lab worker for KernelCI (tuxrun engine).

Lab-side executor for ``pull_labs`` jobs on the ``qemu-riscv64`` platform.
Polls the events API for ``available`` job nodes carrying a
``job_definition`` artifact, then executes each job with ``tuxrun`` and
posts the result back.

Results are ALWAYS reported as a **LAVA-compatible callback body**: that is
the only format the pipeline's callback endpoint (lava_callback.py +
kernelci.runtime.lava.Callback) ingests, and the path real pull labs (demo,
aws-ec2) use in production.  There is no server-side parser for the
PULL_LABS protocol body, so that format is not offered at all - sending it
would silently lose the result.

tuxrun owns everything about "talking to the guest" (QEMU boot, serial
console, login, test delivery and result collection) inside the
``linaro/tuxrun-dispatcher`` container - this file only maps a job
definition onto a tuxrun command line, judges the TAP output, and keeps the
pull protocol robust (state cursor, seen-node dedup, flock, retries,
callbacks).

Downloads are size-capped and the embedded log is length-capped.

Auth contract: the job definition's callback.token_name is the "remote
token" name the pipeline admins registered; the worker sends its value as
the whole Authorization header ("Token <secret>") read from the
PULL_LABS_CALLBACK_TOKEN environment variable - exactly what
lava_callback.py compares against the [runtime] settings.

Job mapping (test types rendered by config/runtime/*-pull-labs.jinja2):
  boot              -> ``tuxrun --device qemu-riscv64 --kernel <url>`` with
                       the default ext4 buildroot rootfs (the job def only
                       carries a cpio ramdisk, which the qemu device cannot
                       boot; override with --rootfs for a specific disk).
  kselftest-<coll>  -> ``--tests kselftest-<coll>`` plus a ``rootfs`` disk
                       (nfsroot tar.xz is baked to ext4 here) and the
                       kselftest tarball delivered as a LAVA overlay via
                       ``--parameters KSELFTEST=<url>``.

Known gaps (verified against tuxrun 1.10.0 / tuxlava 0.24.0):
  * ``kselftest-riscv`` needs the companion tuxlava class in config/
    dir (tuxlava-kselftest-riscv.patch); without it tuxrun exits 2 and
    the job is reported as an infra error instead of running.
  * ``kselftest-kvm`` runs the curated KVM_TEST_SUBSET (9 tests) via the
    LKFT ``TST_CASENAME`` allow-list, forwarded by the patched template;
    perf/stress tests are excluded because they are meaningless under
    TCG.  kvm.ko is loaded at boot via /etc/modules-load.d/kernelci.conf
    baked into tar.xz rootfs (verified locally on both a kvm-enabled
    buildroot image and the production trixie-kselftest riscv64 rootfs:
    7 pass / 2 skip, exit 0; see work/env/).  With
    tuxrun's default ext4 rootfs, supply a pre-built kvm-enabled image
    instead.
  * ``--api-config-name`` / ``--storage-config-name`` must match the
    pipeline deployment's api/storage config names, otherwise the
    callback endpoint cannot find the node or upload artifacts.

Lab requirements: ``pip install tuxrun`` + podman/docker able to pull
``linaro/tuxrun-dispatcher`` (QEMU runs inside it); cpu features like
Vector/H go through ``--parameters cpu=...``.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timedelta

import requests
import yaml

# CSI (ESC [ params letter), OSC (ESC ] ... BEL/ST) sequences, and stray C0
# control characters (an unterminated CSI leaves raw ESC/params behind).
# Tab, LF and CR are kept: they are part of the console text structure.
ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|[\x00-\x08\x0b-\x1f\x7f]"
)


def strip_ansi(text):
    """Remove ANSI colour/control sequences from tuxrun console output."""
    return ANSI_RE.sub("", text)


BASE_URI = "https://staging.kernelci.org:9000/latest"
EVENTS_PATH = "/events"
REQUEST_TIMEOUT = 60
DISK_SIZE = "4G"  # ext4 image size; unrelated to QEMU memory
DEFAULT_TIMEOUT = 1800  # seconds, when the job def carries no timeout
LOG_LIMIT = 2 << 20  # cap of log text embedded in a result body
MAX_DOWNLOAD_SIZE = 4 << 30  # 4 GiB per download; rootfs tarballs fit easily
CURSOR_OVERLAP_S = 900  # re-scan window: the events API is not sorted
SEEN_LIMIT = 20000  # seen-node ids kept in the state file; sized far
# beyond what one CURSOR_OVERLAP_S window can produce, so eviction can
# never re-expose a recently processed node to a re-run.

TAR_SUFFIXES = (".tar", ".tar.gz", ".tar.xz", ".tgz")
TEST_TYPE_RE = re.compile(r"[a-z0-9][a-z0-9-]*")

# Curated kvm selftest subset (riscv64).  perf/stress tests (memslot_perf,
# mmu_stress, dirty_log_perf, ...) are minute-scale workloads that are
# meaningless under TCG; get-reg-list is a version-drift tracker, not a
# riscv regression; kvm_page_table_test has an internal 120s timeout that
# occasionally trips under TCG load.  Passed to the LKFT script as a
# TST_CASENAME allow-list ("kvm:name kvm:name ...").  Override with
# --kvm-tests.
KVM_TEST_SUBSET = [
    "set_memory_region_test",
    "kvm_create_max_vcpus",
    "kvm_binary_stats_test",
    "kvm_page_table_test",
    "ebreak_test",
    "guest_print_test",
    "steal_time",
    "sbi_pmu_test",
    "irqfd_test",
]


def runtime_name(args):
    """Pick a container runtime tuxrun can drive (podman preferred)."""
    if args.container_runtime:
        return args.container_runtime
    return "podman" if shutil.which("podman") else "docker"


def download(url, dest, max_size=MAX_DOWNLOAD_SIZE):
    """Stream *url* to *dest*, verifying size."""
    print(f"Downloading {url}")
    with requests.get(
        url, stream=True, timeout=REQUEST_TIMEOUT, allow_redirects=False
    ) as response:
        if response.is_redirect or response.is_permanent_redirect:
            raise requests.exceptions.RequestException(
                f"refusing redirect for {url}"
            )
        response.raise_for_status()
        length = response.headers.get("Content-Length")
        try:
            length = int(length) if length else None
        except ValueError:
            length = None
        if length is not None and length > max_size:
            raise OSError(f"Download too large {url}: {length} > {max_size}")
        size = 0
        try:
            with open(dest, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    size += len(chunk)
                    if size > max_size:
                        raise OSError(f"Download too large {url}: > {max_size}")
        except Exception:
            if os.path.exists(dest):
                os.unlink(dest)
            raise
    if length is not None and size != length:
        os.unlink(dest)
        raise OSError(f"Truncated download {url}: {size}/{length} bytes")
    print(f"           -> {dest} ({size} bytes)")


def _extract(archive, dest_dir):
    """Extract a tarball under *dest_dir*, then unwrap a single top dir.

    Device/FIFO members are skipped: rootfs tarballs ship /dev nodes and
    mknod fails for an unprivileged lab user (trixie-full.rootfs.tar.xz
    reproduces this), while mkfs.ext4 -d populates them from the tree
    anyway."""
    os.makedirs(dest_dir, exist_ok=True)
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            if member.isdev() or member.isfifo():
                continue
            tf.extract(member, dest_dir)
    entries = os.listdir(dest_dir)
    if len(entries) == 1 and os.path.isdir(os.path.join(dest_dir, entries[0])):
        dest_dir = os.path.join(dest_dir, entries[0])
    return dest_dir


def bake_rootfs_image(
    workspace, rootfs_url, boot_modules=None, max_size=MAX_DOWNLOAD_SIZE
):
    """Turn the nfsroot tar.xz artifact into an ext4 image tuxrun can boot
    (mkfs.ext4 -d: no loop mount, no root).  kselftest/modules are injected
    by tuxrun as LAVA overlays instead of being baked in.

    When boot_modules is given, a /etc/modules-load.d/kernelci.conf is
    dropped into the extracted tree before mkfs.ext4, so the guest loads
    those modules at boot (systemd-modules-load or busybox S11modules)
    before the tests run - kselftest-kvm needs kvm.ko loaded and /dev/kvm
    present, which udev/devtmpfs rules then create.
    """
    tar_path = os.path.join(workspace, "rootfs.tar")
    download(rootfs_url, tar_path, max_size=max_size)
    root_dir = _extract(tar_path, os.path.join(workspace, "rootfs"))
    if boot_modules:
        conf_dir = os.path.join(root_dir, "etc", "modules-load.d")
        os.makedirs(conf_dir, exist_ok=True)
        with open(os.path.join(conf_dir, "kernelci.conf"), "w") as conf:
            conf.write("\n".join(boot_modules) + "\n")
    image = os.path.join(workspace, "rootfs.ext4")
    print(f"Building ext4 image (mkfs.ext4 -d) -> {image}")
    subprocess.run(
        ["mkfs.ext4", "-F", "-d", root_dir, image, DISK_SIZE],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return image


def cpu_for(args, test_type):
    """CPU property string; KVM jobs need the H extension enabled."""
    cpu = args.cpu
    if test_type == "kselftest-kvm" and "h=" not in cpu:
        cpu += ",h=true"
    return cpu


def build_command(job, args, workspace):
    """Map a job definition onto a tuxrun argv; bakes a disk rootfs if the
    artifact is a tarball.  Returns (argv, label) or raises KeyError."""
    artifacts = job.get("artifacts", {})
    tests = job.get("tests", []) or [{}]
    test = tests[0]
    test_type = test.get("type") or "boot"
    if not TEST_TYPE_RE.fullmatch(test_type):
        raise KeyError(f"invalid test type in job definition: {test_type!r}")
    kernel_url = artifacts.get("kernel")
    if not kernel_url:
        raise KeyError("job definition has no kernel artifact")

    cmd = [
        args.tuxrun_bin,
        "--runtime",
        runtime_name(args),
        "--device",
        args.platform,
        "--kernel",
        kernel_url,
        # Debian images (e.g. trixie-kselftest) ship an UNCONFIGURED
        # fstab with no root entry, so the kernel mounts / read-only
        # and systemd never remounts it; the LAVA test shell then dies
        # with "Read-only file system" when writing results.  rw is
        # harmless for images that remount themselves (buildroot).
        "--boot-args",
        "rw",
    ]
    parameters = [f"cpu={cpu_for(args, test_type)}"]

    rootfs_url = artifacts.get("rootfs") or args.rootfs
    if not rootfs_url and artifacts.get("ramdisk"):
        print(
            "Warning: job definition carries a cpio ramdisk; the qemu "
            "device cannot boot it - using tuxrun's built-in disk "
            "(pass --rootfs to override)"
        )
    boot_modules = ["kvm"] if test_type == "kselftest-kvm" else None
    if rootfs_url and rootfs_url.endswith(TAR_SUFFIXES):
        image = bake_rootfs_image(
            workspace,
            rootfs_url,
            boot_modules=boot_modules,
            max_size=args.max_download_size,
        )
        cmd += ["--rootfs", f"file://{image}"]
    elif rootfs_url:
        cmd += ["--rootfs", rootfs_url]
    elif test_type != "boot":
        raise KeyError("job definition has no rootfs for a kselftest job")

    if artifacts.get("modules"):
        cmd += ["--modules", artifacts["modules"]]

    label = test_type
    if test_type != "boot":
        kselftest_url = artifacts.get("kselftest")
        if not kselftest_url:
            raise KeyError("job definition has no kselftest artifact")
        parameters.append(f"KSELFTEST={kselftest_url}")
        tests = [test_type]
        if test_type == "kselftest-kvm":
            # Curated subset instead of the whole collection: the LKFT
            # script hands TST_CASENAME to `run_kselftest.sh -t`, which
            # matches each kvm:name entry exactly (allow-list).  kvm.ko
            # itself is loaded at boot via the modules-load.d conf baked
            # into the rootfs (see bake_rootfs_image); the LKFT "modules"
            # test is a load/unload round-trip and must NOT be used here
            # (verified: it unloads kvm again before kselftest runs).
            if args.kvm_full:
                # whole collection: no allow-list; LKFT runs every kvm test.
                pass
            else:
                subset = args.kvm_tests or KVM_TEST_SUBSET
                parameters.append(
                    "TST_CASENAME=" + " ".join(
                        f"kvm:{name}" for name in subset)
                )
        cmd += ["--tests", *tests]
    cmd += ["--parameters", *parameters]
    return cmd, label


def run_command(cmd, timeout_s, workspace):
    """Run tuxrun, capture its output into the workspace log and return
    (returncode, output).  returncode is None when the run timed out; the
    partial output is still written to the log."""
    log_path = os.path.join(workspace, "tuxrun.log")
    print("Running:", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s + 180,  # a little grace past the job timeout
            cwd=workspace,
        )
    except subprocess.TimeoutExpired as error:
        output = f"{error.stdout or ''}\n{error.stderr or ''}"
        with open(log_path, "w") as f:
            f.write(output)
        return None, output
    output = f"{proc.stdout}\n{proc.stderr}"
    with open(log_path, "w") as f:
        f.write(output)
    return proc.returncode, output


def tap_summary(output, label):
    """Count top-level TAP results for a kselftest job from the tuxrun
    console log.  tuxrun/LAVA report "job pass" even when a selftest fails,
    so the worker must read the TAP lines itself: any top-level ``not ok``
    (or a started test that never reported) makes the job fail.  Each
    console line may carry an ANSI colour code and a log timestamp."""
    output = strip_ansi(output)
    collection = (
        label[len("kselftest-") :] if label.startswith("kselftest-") else label
    )
    marker = "selftests: " + collection + ":"
    # Tolerate leading whitespace and any split between "not"/"ok" (spaces,
    # tabs, CR, or stripped control chars gluing them into "notok"); match
    # case-insensitively so "NOT OK" still counts as a failure.  The ok
    # pattern's lookbehind keeps glued "notok" out of ok_m; spaced-out
    # "not ok" lines may still match ok_m but the not_ok loop overwrites
    # them afterwards, so the final per_test result is always fail.
    line = r"(?m)^[ \t]*(?:\S+ )?"
    ok_m = re.findall(
        line + rf"(?<!not)ok \d+ {re.escape(marker)}\s+(\S+)(.*)",
        output,
        re.IGNORECASE,
    )
    not_ok = re.findall(
        line + rf"not[ \t\r]*ok \d+ {re.escape(marker)}\s+(\S+)",
        output,
        re.IGNORECASE,
    )
    started = set(re.findall(line + rf"# {re.escape(marker)}\s+(\S+)", output))
    if not ok_m and not not_ok and not started:
        # No TAP at all: the suite never ran (tuxrun job-level failure).
        # Never report that as pass - mark the suite failed so the node
        # surfaces as fail instead of a false green.
        return (
            {"total": 0, "failed": 1, "skipped": 0},
            {label: {"status": "fail"}},
            {},
        )
    ok_names = {name for name, _ in ok_m}
    finished = ok_names | set(not_ok)
    missing = started - finished
    # One entry per test name, last result wins (duplicate lines do not
    # inflate the counts).
    per_test = {}
    for name, rest in ok_m:
        per_test[name] = "skip" if "# SKIP" in rest else "pass"
    for name in not_ok:
        per_test[name] = "fail"
    for name in missing:
        per_test.setdefault(name, "fail")
    skipped = sum(1 for r in per_test.values() if r == "skip")
    failed = sum(1 for r in per_test.values() if r == "fail")
    summary = {"total": len(per_test), "failed": failed, "skipped": skipped}
    status = "pass" if failed == 0 else "fail"
    return summary, {label: {"status": status}}, per_test


LAVA_CASE_RE = re.compile(r"'case': '([^']+)'.*?'result': '(pass|fail|skip)'")
LAVA_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def lava_body(
    system, returncode, output, args, tap=None, infra=False, error_msg=""
):
    """Build a LAVA-compatible callback body (what production's
    lava_callback.py + kernelci.runtime.lava.Callback actually ingests).

    The pipeline's callback endpoint parses every body with the LAVA
    Callback class; the pull_labs protocol body is not wired there, so a
    lab that wants its results to land in nodes must speak LAVA format.
    Required pieces, mirroring a real LAVA server callback:
      - status: LAVA numeric job status (2=Complete, 3=Incomplete)
      - definition: YAML string whose metadata carries api_config_name
        and storage_config_name (what get_meta() reads)
      - results.lava: YAML list of case/stage dicts; login-action and
        kernel-messages cases are replayed from tuxrun's own LAVA log
        lines so boot results get the usual 'setup' hierarchy
      - results.<suite>: for a kselftest job, one entry per TAP test
        (from tap_summary), keyed 0_kselftest.<collection> with a
        matching stage in results.lava; the parser then builds a suite
        node whose children are the individual tests and flips the job
        result to 'fail' when any of them failed - even though tuxrun
        exits 0 when a selftest fails
      - log: LAVA output.yaml format (list of {dt, lvl, msg}); without
        it the endpoint forces the result to 'incomplete'

    tap is (label, summary, per_test) as returned by tap_summary().
    infra marks an infrastructure error; it is reported through the
    'job' stage metadata, which is what Callback.is_infra_error() and
    the callback endpoint's error handling read.
    """
    status = 2 if returncode == 0 else 3
    if tap:
        # A kselftest job whose TAP is available DID complete: tuxrun
        # exits 0/1/2 depending on the LKFT result plumbing (1 = some
        # tests failed, 2 = no LAVA cases emitted, e.g. missing
        # python3-tap in the rootfs).  The per-test hierarchy below is
        # what must drive the final pass/fail, so the job stays Complete
        # (status 2) unless this is an infrastructure error.
        status = 2 if not infra else 3
    cases = [{"name": "job", "metadata": {}}]
    boot_cases = []
    for raw in output.splitlines():
        line = strip_ansi(raw)
        match = LAVA_CASE_RE.search(line)
        if not match or match.group(1) not in (
            "login-action",
            "kernel-messages",
        ):
            continue
        cases.append(
            {
                "name": match.group(1),
                "result": match.group(2),
                "metadata": {},
            }
        )
        boot_cases.append(match.group(1))
    if infra:
        cases[0]["metadata"] = {
            "error_type": "Infrastructure",
            "error_msg": error_msg[-200:],
        }
    elif returncode != 0:
        last = next(
            (line for line in reversed(output.splitlines()) if line.strip()),
            "tuxrun failed",
        )
        cases[0]["metadata"] = {"error_type": "Job", "error_msg": last[-200:]}
    elif not tap and not boot_cases:
        # rc 0 without any boot case lines means the log does not show a
        # real boot; never report that as pass.
        status = 3
        cases[0]["metadata"] = {
            "error_type": "Job",
            "error_msg": "no login/kernel-messages cases in tuxrun log",
        }
    results = {}
    if tap:
        label, summary, per_test = tap
        suite = label[len("kselftest-") :]
        suite_key = f"0_kselftest.{suite}"
        cases.append(
            {
                "name": suite_key,
                "result": "fail" if summary["failed"] else "pass",
                "metadata": {},
            }
        )
        results[suite_key] = yaml.safe_dump(
            [
                {"name": name, "result": result, "metadata": {}}
                for name, result in per_test.items()
            ]
        )
    results["lava"] = yaml.safe_dump(cases)

    log_lines = []
    for raw in output[-LOG_LIMIT:].splitlines():
        line = strip_ansi(raw).rstrip()
        if not line.strip():
            continue
        match = LAVA_TS_RE.match(line)
        log_lines.append(
            {
                "dt": match.group(0) if match else "",
                "lvl": "target",
                "msg": line[match.end() :].lstrip() if match else line,
            }
        )

    definition = yaml.safe_dump(
        {
            "metadata": {
                "api_config_name": args.api_config_name,
                "storage_config_name": args.storage_config_name,
            },
        }
    )
    return {
        "definition": definition,
        "results": results,
        "status": status,
        "log": yaml.safe_dump(log_lines),
        "actual_device_id": system,
    }


def pollevents(api_url, timestamp):
    url = (
        f"{api_url}{EVENTS_PATH}?state=available&kind=job&limit=1000"
        f"&recursive=true&from={timestamp}"
    )
    print(url)
    response = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as error:
        raise requests.exceptions.RequestException(
            f"Invalid JSON from events API: {error}"
        ) from error


def retrieve_job_definition(url):
    print(f"Retrieving job definition from: {url}")
    response = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
    if response.is_redirect or response.is_permanent_redirect:
        raise requests.exceptions.RequestException(
            f"refusing redirect for {url}"
        )
    response.raise_for_status()
    return response.json()


class CallbackPermanentError(Exception):
    """The callback endpoint rejected the result (4xx): retrying is pointless."""


class CallbackTransientError(Exception):
    """Network/5xx trouble posting the result: retry later."""


def post_result(callback, token, body):
    """Post a result body to the recorded callback endpoint, retrying a few
    times - a single network blip must not lose a result."""
    if not callback:
        print("Warning: no callback URL in job definition, result not reported")
        return
    headers = {}
    if token:
        headers["Authorization"] = f"Token {token}"
    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(
                callback,
                json=body,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
            print(f"Callback status: {response.status_code}")
            if response.is_redirect or response.is_permanent_redirect:
                # Never follow a redirect with the shared token attached.
                raise CallbackPermanentError(
                    f"callback redirected ({response.status_code})"
                )
            if response.status_code < 400:
                return
            if response.status_code < 500:
                raise CallbackPermanentError(
                    f"callback returned {response.status_code}"
                )
            last_error = requests.exceptions.HTTPError(
                f"callback returned {response.status_code}"
            )
            print(f"Callback attempt {attempt + 1}/3 failed: {last_error}")
            time.sleep(2 * (attempt + 1))
        except CallbackPermanentError:
            raise
        except requests.exceptions.RequestException as error:
            last_error = error
            print(f"Callback attempt {attempt + 1}/3 failed: {error}")
            time.sleep(2 * (attempt + 1))
    raise CallbackTransientError(str(last_error))


def tuxrun_invocation_error(returncode, output):
    """argparse-level failures (unknown test class, bad flag) exit 2 and
    print usage - an infra problem, not a test result."""
    return (
        returncode == 2
        and "error:" in output
        and ("usage:" in output or "invalid choice" in output)
    )


def tuxrun_job_error(returncode, output):
    """A tuxrun run that never reached the tests: LAVA's own
    infrastructure-level failure marker (unreachable artifacts, corrupt
    images, invalid job data).  Genuine boot/test failures do not print
    this line.  - an infra problem, not a test result."""
    return "cannot terminate cleanly" in strip_ansi(output)


JOB_CASE_INFRA_RE = re.compile(
    r"'case': 'job'.*?'error_type': 'Infrastructure'"
)


def tuxrun_infra_error(returncode, output):
    """Authoritative infra signal: the final LAVA job case self-reports
    error_type 'Infrastructure' (e.g. serial connection closed mid-run).
    String heuristics above are only fallbacks for cases where LAVA does
    not emit this line."""
    return bool(JOB_CASE_INFRA_RE.search(strip_ansi(output)))


def run_job(job, args):
    """Execute one job definition in a per-job workspace and return the
    report tuple (callback_url, token, body); the caller posts it.  Every
    failure inside is converted into an infra-error LAVA body, so a report
    is always produced (unless the workspace itself cannot be created)."""
    environment = job.get("environment", {})
    system = environment.get("platform", args.platform)
    callback = job.get("callback", {})
    callback_url = callback.get("url")
    # The callback token is a "remote token" name shared with the pipeline
    # admins; the worker holds the secret in an env var.
    callback_token = os.environ.get("PULL_LABS_CALLBACK_TOKEN")
    timeout_s = next(
        (
            t.get("timeout_s")
            for t in job.get("tests", [])
            if t.get("timeout_s")
        ),
        DEFAULT_TIMEOUT,
    )
    timeout_s = max(60, min(timeout_s, args.max_timeout))

    own_base = not args.output_dir
    base = args.output_dir or tempfile.mkdtemp(prefix="riscv-pull-")
    workspace = os.path.join(base, f"job-{time.time_ns()}")
    os.makedirs(workspace, exist_ok=True)
    returncode, output = 3, ""
    tap = None
    infra = False
    error_msg = ""
    try:
        cmd, label = build_command(job, args, workspace)
        returncode, output = run_command(cmd, timeout_s, workspace)
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
            infra = True
            error_msg = output[-2000:]
        if label.startswith("kselftest-"):
            # tuxrun returns 0 even when selftests fail; judge from the TAP.
            # Computed even on infra failures, so a suite that died mid-run
            # keeps the per-test results it produced.
            summary, _tests_out, per_test = tap_summary(output, label)
            tap = (label, summary, per_test)
    except Exception as error:
        print(f"Job failed in preparation/execution: {error}")
        infra = True
        error_msg = str(error)
    finally:
        if not args.keep_workspace:
            if own_base:
                shutil.rmtree(base, ignore_errors=True)
            else:
                shutil.rmtree(workspace, ignore_errors=True)
    body = lava_body(
        system,
        returncode,
        output,
        args,
        tap=tap,
        infra=infra,
        error_msg=error_msg,
    )
    return callback_url, callback_token, body


def handle_event(event, args, reports):
    """Process one job event.

    A node whose execution already produced a report is retried by
    re-posting that report only - tuxrun is never re-run for the same
    node.  Returns True when the event is fully handled (or deliberately
    given up on) so the caller may mark it seen."""
    node = event.get("node", {})
    node_id = node.get("id", "unknown")
    artifacts = node.get("artifacts", {})

    # The events stream returns historical snapshots (state at event
    # time); a node may have been taken/run since.  Only act on jobs
    # that are still available NOW, so a fresh worker never replays
    # yesterday's queue.
    try:
        current = requests.get(
            f"{args.api_url}/latest/node/{node_id}", timeout=30
        ).json()
    except requests.exceptions.RequestException as error:
        print(f"{node_id}: node state check failed: {error}")
        return False
    if current.get("state") != "available":
        return True
    job_definition_url = artifacts.get("job_definition", "")
    if not job_definition_url or not job_definition_url.startswith("http"):
        return True  # not a pull_labs job; nothing to do

    data = event.get("data", {}).get("data", {})
    platform = data.get("platform")
    runtime = data.get("runtime")
    if args.platform and platform != args.platform:
        return True
    if args.runtime and runtime != args.runtime:
        return True

    print(
        f"Processing job {node_id} (platform: {platform}, runtime: {runtime})"
    )

    cached = reports.get(node_id)
    if cached:
        callback_url, callback_token, body = cached
        try:
            post_result(callback_url, callback_token, body)
            del reports[node_id]
            print(f"{node_id}: cached result posted on retry")
            return True
        except CallbackPermanentError as error:
            del reports[node_id]
            print(
                f"{node_id}: permanent callback failure ({error}); "
                "giving up on this node"
            )
            return True
        except CallbackTransientError as error:
            print(f"{node_id}: cached result not posted yet: {error}")
            return False

    try:
        job = retrieve_job_definition(job_definition_url)
        report = run_job(job, args)
    except requests.exceptions.RequestException as error:
        status_code = getattr(
            getattr(error, "response", None), "status_code", None
        )
        if status_code is not None and status_code < 500:
            print(
                f"{node_id}: job definition fetch failed with "
                f"{status_code} ({error}); giving up on this node"
            )
            return True
        print(f"{node_id}: transient job definition fetch error: {error}")
        return False
    except Exception as error:
        import traceback

        print(f"Unexpected failure processing {node_id}: {error}")
        traceback.print_exc()
        return True  # run_job converts its own failures; give up on the rest

    callback_url, callback_token, body = report
    try:
        post_result(callback_url, callback_token, body)
        return True
    except CallbackPermanentError as error:
        print(
            f"{node_id}: permanent callback failure ({error}); "
            "giving up on this node"
        )
        return True
    except CallbackTransientError as error:
        reports[node_id] = report
        print(
            f"{node_id}: result not posted yet ({error}); "
            "re-posting next poll (no re-run)"
        )
        return False


def save_state(state_file, state):
    if not state_file:
        return
    tmp_path = f"{state_file}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, state_file)


def load_state(state_file):
    if not state_file or not os.path.exists(state_file):
        return {"timestamp": None, "seen": []}
    try:
        with open(state_file) as f:
            state = json.load(f)
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("seen"), list)
            or (
                state.get("timestamp") is not None
                and not isinstance(state.get("timestamp"), str)
            )
        ):
            raise ValueError("state file has unexpected shape")
        return state
    except (ValueError, OSError):
        print(f"Warning: state file {state_file} unreadable; starting fresh")
        return {"timestamp": None, "seen": []}


def iso_ago(timestamp, seconds):
    """*timestamp* minus *seconds*, as an ISO-8601 string."""
    return (
        datetime.fromisoformat(timestamp) - timedelta(seconds=seconds)
    ).isoformat()


def poll_loop(args):
    import fcntl

    state_file = args.state_file
    lock_file = f"{state_file}.lock"
    lock = None
    try:
        lock = open(lock_file, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another worker instance holds the lock; exiting.")
        raise SystemExit(1)

    state = load_state(state_file)
    seen_order = list(state.get("seen", []))
    seen = set(seen_order)
    timestamp = (
        args.since or state.get("timestamp") or "1970-01-01T00:00:00.000000"
    )
    reports = {}
    retry_count = 0
    while True:
        # The events API is not sorted and can deliver events out of order,
        # so re-scan a trailing window and dedup via `seen` - a cursor that
        # only ever advances would silently skip late events.
        try:
            events = pollevents(
                args.api_url, iso_ago(timestamp, CURSOR_OVERLAP_S)
            )
            retry_count = 0
        except requests.exceptions.RequestException as error:
            retry_count += 1
            print(
                f"Error fetching events (attempt {retry_count}/"
                f"{args.max_retries}): {error}"
            )
            if retry_count >= args.max_retries:
                print(f"Max retries ({args.max_retries}) reached. Exiting.")
                raise SystemExit(1)
            print(f"Retrying in {args.poll_period} seconds...")
            time.sleep(args.poll_period)
            continue
        if not events:
            print(
                f"No new events, sleeping for {args.poll_period} seconds",
                flush=True,
            )
            time.sleep(args.poll_period)
            continue

        print(f"Got {len(events)} events", flush=True)
        # Only advance the cursor when the whole batch succeeded, so a
        # failed job is retried next poll; a job done once is skipped.
        all_ok = True
        for event in events:
            node_id = event.get("node", {}).get("id") or "unknown"
            if node_id in seen:
                continue
            if not handle_event(event, args, reports):
                all_ok = False
            elif node_id and event.get("node", {}).get("artifacts", {}).get(
                "job_definition"
            ):
                # Only remember nodes that were actually processed.  The
                # first event for a node may arrive before its
                # job_definition artifact is attached (e.g. create then
                # update), and handle_event() skips such events silently;
                # marking them seen would hide the later, complete event.
                seen.add(node_id)
                if node_id not in seen_order:
                    seen_order.append(node_id)
                while len(seen_order) > SEEN_LIMIT:
                    seen.discard(seen_order.pop(0))
        if all_ok:
            timestamp = max(
                (e.get("timestamp") or timestamp for e in events),
                default=timestamp,
            )
        else:
            print(
                "Some events failed; cursor not advanced, will retry next poll",
                flush=True,
            )
            # Never busy-loop on a failing batch: the API needs a breather
            # and the failure is usually environmental (404 jobdef, network).
            time.sleep(args.poll_period)
        save_state(state_file, {"timestamp": timestamp, "seen": seen_order})
        if args.once:
            print("--once: batch processed, exiting", flush=True)
            break


def main():
    parser = argparse.ArgumentParser(
        description="Run KernelCI pull_labs qemu-riscv64 jobs with tuxrun."
    )
    parser.add_argument(
        "--api-url",
        default=BASE_URI,
        help="KernelCI API base URL to poll for events.",
    )
    parser.add_argument(
        "--platform",
        default="qemu-riscv64",
        help="tuxrun device / platform filter (default: qemu-riscv64).",
    )
    parser.add_argument(
        "--runtime",
        default="pull-labs-riscv",
        help="Filter jobs by runtime/lab name (default: pull-labs-riscv).",
    )
    parser.add_argument(
        "--output-dir",
        help="Place per-job workspaces under this directory "
        "(cleaned unless --keep-workspace is given).",
    )
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Do not remove per-job workspaces.",
    )
    parser.add_argument(
        "--state-file",
        default="riscv-pull-worker-state.json",
        help="Persist cursor + processed node ids here.",
    )
    parser.add_argument(
        "--since", help="Poll events starting from this timestamp."
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Max consecutive API retries (default: 5).",
    )
    parser.add_argument(
        "--poll-period",
        type=int,
        default=30,
        help="Seconds between event polls (default: 30).",
    )
    parser.add_argument(
        "--tuxrun-bin",
        default="tuxrun",
        help="tuxrun executable (default: tuxrun).",
    )
    parser.add_argument(
        "--container-runtime",
        default="",
        help="podman or docker for the dispatcher image "
        "(default: podman, falling back to docker).",
    )
    parser.add_argument(
        "--cpu",
        default=os.environ.get("QEMU_CPU", "rv64,v=true"),
        help="QEMU cpu properties (default: rv64,v=true; "
        "KVM jobs add ,h=true).",
    )
    parser.add_argument(
        "--rootfs",
        default="",
        help="Rootfs disk URL for boot jobs whose job "
        "definition only carries a ramdisk (default: "
        "tuxrun's built-in buildroot disk).",
    )
    parser.add_argument(
        "--max-timeout",
        type=int,
        default=7200,
        help="Upper bound for a job's timeout_s (default: 7200).",
    )
    parser.add_argument(
        "--max-download-mb",
        type=int,
        default=4096,
        dest="max_download_size",
        help="Max download size in MiB (default: 4096).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process the currently available jobs once and exit "
        "(one-shot local loop test), instead of polling forever.",
    )
    parser.add_argument(
        "--kvm-full",
        action="store_true",
        help="Run the whole kvm collection (no TST_CASENAME allow-list). "
        "perf/stress time out under TCG; timeouts are reported as "
        "incomplete, never fail. Default: curated 9-test subset.",
    )
    parser.add_argument(
        "--kvm-tests",
        nargs="+",
        default=KVM_TEST_SUBSET,
        metavar="NAME",
        help="Curated kvm selftest names run via the LKFT "
        "TST_CASENAME allow-list (default: the 9 tests "
        "in KVM_TEST_SUBSET).  kvm.ko is loaded at boot "
        "through the modules-load.d conf baked into "
        "tar.xz rootfs; with a pre-built ext4 rootfs "
        "the image must load kvm itself.",
    )
    parser.add_argument(
        "--api-config-name",
        default=os.environ.get("KCI_API_CONFIG_NAME", "docker-host"),
        help="api_config_name embedded in the LAVA callback "
        "definition metadata; MUST match the pipeline "
        "deployment's api config name (docker-host is "
        "the local dev compose).",
    )
    parser.add_argument(
        "--storage-config-name",
        default=os.environ.get("KCI_STORAGE_CONFIG_NAME", "docker-host"),
        help="storage_config_name embedded in the LAVA "
        "callback definition metadata; MUST match the "
        "pipeline deployment's storage config name.",
    )
    args = parser.parse_args()
    args.max_download_size = args.max_download_size << 20
    poll_loop(args)


if __name__ == "__main__":
    main()
