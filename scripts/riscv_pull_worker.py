#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""RISC-V QEMU pull-lab worker for KernelCI (tuxrun engine).

Polls the events API for ``available`` pull_labs job nodes on qemu-riscv64,
executes each with tuxrun inside the linaro/tuxrun-dispatcher container, and
posts the result back as a **LAVA-compatible callback body** - the only format
the pipeline's callback endpoint (lava_callback.py + kernelci.runtime.lava.Callback)
ingests; there is no server-side parser for the PULL_LABS protocol body, so any
other format would silently lose the result.

Judging rule: tuxrun exits 0 even when selftests fail, so results come from
parsing the TAP lines (tap_summary); infra failures (bad flags, unreachable
artifacts, timeouts) are reported as incomplete + Infrastructure, never as a
test result.  Protocol robustness: state cursor, seen-node dedup, flock,
callback retries, and unposted results persisted across runs (re-posted,
never re-run).

Job mapping (rendered by config/runtime/*-pull-labs.jinja2):
  boot             -> ``tuxrun --device qemu-riscv64 --kernel <url>`` (a cpio
                      ramdisk in the job def is not bootable by the qemu
                      device; override with --rootfs).
  kselftest-<coll> -> ``--tests kselftest-<coll>`` + a rootfs disk (nfsroot
                      tar.xz baked to ext4) + ``--parameters KSELFTEST=<url>``.

Known gaps: kselftest-riscv needs the tuxlava class from
config/tuxlava-kselftest-riscv.patch (without it tuxrun exits 2 -> infra);
kselftest-kvm runs the curated KVM_TEST_SUBSET with kvm.ko loaded at boot
(modules.tar.xz baked into the ext4 image + modules-load.d conf);
--api-config-name / --storage-config-name must match the deployment or the
callback cannot find the node.

Full parameter and behavior reference: docs/tools-guide.md section 4.
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


BASE_URI = "https://api.kernelci.org"
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

# Curated kvm selftest subset (riscv64): functional coverage only. perf/stress
# tests measure TCG speed, not kernel regressions (see README section 2).
# kvm_page_table_test is excluded: under TCG-emulated H extension it runs
# nested-VM page-table stress for tens of minutes and hangs the whole job
# (verified in the real loop) - it stays available via --kvm-full/--kvm-tests.
# Passed to the LKFT script as a TST_CASENAME allow-list ("kvm:name ...").
# Override with --kvm-tests / --kvm-full.
KVM_TEST_SUBSET = [
    "set_memory_region_test",
    "kvm_create_max_vcpus",
    "kvm_binary_stats_test",
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
    """Stream *url* to *dest*, verifying size.  Retries a few times: production
    storage intermittently stalls/truncates (documented); a partial file is
    removed on failure so the next attempt starts clean."""
    print(f"Downloading {url}")
    last_error = None
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    for attempt in range(3):
        try:
            with requests.get(
                url, stream=True, timeout=300, allow_redirects=False
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
            return
        except (requests.exceptions.RequestException, OSError) as error:
            last_error = error
            if attempt < 2:
                print(f"  download attempt {attempt + 1}/3 failed: {error}; retrying")
                time.sleep(2 * (attempt + 1))
    raise last_error


def _safe_member(member):
    """Reject archive members that could escape the extraction directory:
    absolute member paths and ``..`` components.  Symlinks with absolute
    targets are ALLOWED - rootfs tarballs legitimately ship them
    (./init -> /usr/lib/systemd/systemd, ./dev/stdout -> /proc/self/fd/1);
    extraction only stores the link text, the link is meaningful inside the
    guest image, and nothing on the host follows it.  Hardlink targets stay
    strict: tarfile resolves them with os.link() on the host at extraction
    time, so an absolute target would genuinely escape."""
    name = member.name.replace("\\", "/")
    if name in ("", ".") or name.startswith("/"):
        return False
    if any(part == ".." for part in name.split("/")):
        return False
    target = getattr(member, "linkname", "") or ""
    # Hardlinks only: extraction resolves them on the host with os.link(),
    # so their targets stay strict.  Symlinks are just stored text.
    if member.issym() or not target:
        return True
    return not (
        target.startswith("/")
        or any(part == ".." for part in target.replace("\\", "/").split("/"))
    )


def _extract(archive, dest_dir):
    """Extract a tarball under *dest_dir*, then unwrap a single top dir.

    Device/FIFO members are skipped: rootfs tarballs ship /dev nodes and
    mknod fails for an unprivileged lab user (trixie-full.rootfs.tar.xz
    reproduces this), while mkfs.ext4 -d populates them from the tree
    anyway.  Members that could escape *dest_dir* (path traversal) are
    skipped too."""
    os.makedirs(dest_dir, exist_ok=True)
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            if not _safe_member(member) or member.isdev() or member.isfifo():
                continue
            tf.extract(member, dest_dir)
    entries = os.listdir(dest_dir)
    if len(entries) == 1 and os.path.isdir(os.path.join(dest_dir, entries[0])):
        dest_dir = os.path.join(dest_dir, entries[0])
    return dest_dir


def bake_rootfs_image(
    workspace, rootfs_url, boot_modules=None, modules_url=None,
    max_size=MAX_DOWNLOAD_SIZE
):
    """Turn the nfsroot tar.xz artifact into an ext4 image tuxrun can boot
    (mkfs.ext4 -d: no loop mount, no root).

    boot_modules: a /etc/modules-load.d/kernelci.conf is dropped into the
    tree before mkfs.ext4, so the guest modprobes those modules at boot.
    modules_url (kselftest-kvm): the modules.tar.xz is ALSO unpacked under
    /lib/modules before mkfs.ext4 - the --modules LAVA overlay is delivered
    only after boot and never lands in /lib/modules, so without baking them
    in, modprobe kvm at boot finds nothing and every kvm test skips with
    "Cannot open '/dev/kvm'".  kselftest/modules are otherwise injected by
    tuxrun as LAVA overlays instead of being baked in.
    """
    tar_path = os.path.join(workspace, "rootfs.tar")
    download(rootfs_url, tar_path, max_size=max_size)
    root_dir = _extract(tar_path, os.path.join(workspace, "rootfs"))
    if modules_url:
        mod_tar = os.path.join(workspace, "modules.tar")
        download(modules_url, mod_tar, max_size=max_size)
        # modules.tar.xz ships lib/modules/<version>/, so extracting at the
        # tree root puts them exactly where modprobe/uname -r looks.
        _extract(mod_tar, root_dir)
    if boot_modules:
        conf_dir = os.path.join(root_dir, "etc", "modules-load.d")
        # Refuse to write through a symlink (tar-slip via symlink): the
        # realpath must stay exactly where the lexical path is, inside the
        # extracted tree - absolute-target symlinks in the tarball are fine
        # as image content, but our own writes must never follow them.
        os.makedirs(conf_dir, exist_ok=True)
        if os.path.realpath(conf_dir) != os.path.abspath(conf_dir):
            raise OSError(f"refusing to write through symlink: {conf_dir}")
        conf_file = os.path.join(conf_dir, "kernelci.conf")
        if os.path.islink(conf_file):
            os.unlink(conf_file)
        with open(conf_file, "w") as conf:
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

    # An explicit --rootfs overrides whatever the job definition carries:
    # the lab owns its guest images (e.g. point at a local mirror when
    # storage.kernelci.org is throttled).
    rootfs_url = args.rootfs or artifacts.get("rootfs")
    if not rootfs_url and artifacts.get("ramdisk"):
        print(
            "Warning: job definition carries a cpio ramdisk; the qemu "
            "device cannot boot it - using tuxrun's built-in disk "
            "(pass --rootfs to override)"
        )
    boot_modules = ["kvm"] if test_type == "kselftest-kvm" else None
    modules_url = (
        artifacts.get("modules") if test_type == "kselftest-kvm" else None
    )
    if rootfs_url and rootfs_url.endswith(TAR_SUFFIXES):
        image = bake_rootfs_image(
            workspace,
            rootfs_url,
            boot_modules=boot_modules,
            modules_url=modules_url,
            max_size=args.max_download_size,
        )
        cmd += ["--rootfs", f"file://{image}"]
        # Modules are already inside the baked image; the --modules LAVA
        # overlay lands after boot and cannot load kvm.ko at boot time.
        modules_url = None
    elif rootfs_url:
        cmd += ["--rootfs", rootfs_url]
    elif test_type != "boot":
        raise KeyError("job definition has no rootfs for a kselftest job")

    # modules.tar.xz is only needed by kselftest-kvm (kvm.ko loaded at
    # boot).  For boot/kselftest-riscv it is a needless 100MB+ download
    # that adds a flaky network dependency per job - skip it.  With a
    # pre-built (non-baked) ext4 rootfs the image must provide kvm itself.
    if modules_url:
        cmd += ["--modules", modules_url]

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
            # matches each kvm:name entry exactly (allow-list).  kvm.ko is
            # loaded at boot: modules.tar.xz is baked into /lib/modules and
            # a modules-load.d conf modprobes it (see bake_rootfs_image).
            # The LKFT "modules" test is a load/unload round-trip and must
            # NOT be used here (verified: it unloads kvm again before
            # kselftest runs).
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
            check=False,
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
        label.removeprefix("kselftest-")
    )
    marker = "selftests: " + collection + ":"
    # Tolerate whitespace splits and glued variants ("notok", "NOT OK",
    # "not\x1b[31mok", "not  ok"): the ok pattern's lookbehind keeps glued
    # "notok" out of ok_m; the not_ok loop overwrites any split "not ok"
    # line afterwards, so the per-test result is always fail.
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
    """Build a LAVA-compatible callback body: the only format the pipeline's
    callback endpoint (kernelci.runtime.lava.Callback) ingests.

    Required pieces, mirroring a real LAVA server callback:
      - status: LAVA numeric job status (2=Complete, 3=Incomplete)
      - definition: YAML whose metadata carries api_config_name /
        storage_config_name (what get_meta() reads)
      - results.lava: case/stage list; login-action and kernel-messages are
        replayed from tuxrun's own LAVA lines so boot results get the usual
        'setup' hierarchy
      - results.<suite>: per-test entries keyed 0_kselftest.<collection>;
        the parser builds a suite node whose children are the tests and
        flips the job to 'fail' when any failed (tuxrun exits 0 even then)
      - log: LAVA output.yaml format (list of {dt, lvl, msg}); without it
        the endpoint forces 'incomplete'

    tap is (label, summary, per_test) from tap_summary().  infra marks an
    infrastructure error via the 'job' stage metadata (what
    Callback.is_infra_error() reads).
    """
    status = 2 if returncode == 0 else 3
    if tap:
        # TAP available = the job DID complete (tuxrun exits 0/1/2 by LKFT
        # result plumbing); the per-test hierarchy drives the final result,
        # so the job stays Complete unless this is an infra error.
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


def _latest_base(api_url):
    """KernelCI serves its API under the /latest prefix; the local dev API
    accepts both forms, production only the /latest one, so always target
    the canonical /latest base regardless of what the user passed."""
    return api_url if api_url.endswith("/latest") else f"{api_url}/latest"


def pollevents(api_url, timestamp):
    url = (
        f"{_latest_base(api_url)}{EVENTS_PATH}?state=available&kind=job&limit=1000"
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
    except Exception as error:  # noqa: BLE001 - any failure becomes an infra-error report
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
            f"{_latest_base(args.api_url)}/node/{node_id}", timeout=30
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
    except Exception as error:  # noqa: BLE001 - run_job converts its own failures; give up on the rest
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
        return {"timestamp": None, "seen": [], "pending": {}}
    try:
        with open(state_file) as f:
            state = json.load(f)
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("seen"), list)
            or not isinstance(state.get("pending", {}), dict)
            or (
                state.get("timestamp") is not None
                and not isinstance(state.get("timestamp"), str)
            )
        ):
            raise ValueError("state file has unexpected shape")
        return state
    except (ValueError, OSError):
        print(f"Warning: state file {state_file} unreadable; starting fresh")
        return {"timestamp": None, "seen": [], "pending": {}}


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
        lock = open(lock_file, "w")  # noqa: SIM115 - must stay open for the whole poll loop (flock lifetime)
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
    # Unposted results left over from a previous run (e.g. --once exiting on
    # a transient callback failure): re-post them without re-running tuxrun.
    # The token is re-read from the environment and never persisted.
    reports = {}
    for node_id, pending in (state.get("pending") or {}).items():
        if isinstance(pending, dict) and pending.get("callback") and pending.get("body"):
            reports[node_id] = (
                pending["callback"],
                os.environ.get("PULL_LABS_CALLBACK_TOKEN"),
                pending["body"],
            )
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
        state["pending"] = {
            node_id: {"callback": report[0], "body": report[2]}
            for node_id, report in reports.items()
        }
        state["timestamp"] = timestamp
        state["seen"] = seen_order
        save_state(state_file, state)
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
        help="Persist cursor + processed node ids + unposted result "
        "bodies here (unposted results are re-posted on the next run "
        "without re-running tuxrun).",
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
        default=os.environ.get("QEMU_CPU", "rv64,v=true,ssnpm=true"),
        help="QEMU cpu properties (default: rv64,v=true,ssnpm=true; "
        "KVM jobs add ,h=true).",
    )
    parser.add_argument(
        "--rootfs",
        default="",
        help="Rootfs disk URL overriding the job definition's rootfs "
        "(default: use the job definition's rootfs; tuxrun's built-in "
        "buildroot disk for boot jobs without one).",
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
        "incomplete, never fail. Default: curated 8-test subset.",
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
