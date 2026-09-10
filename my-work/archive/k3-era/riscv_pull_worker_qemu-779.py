#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""RISC-V QEMU pull-lab worker for KernelCI.

A lab-side executor for ``pull_labs`` jobs on the ``qemu-riscv64`` platform:
polls the events API for ``available`` job nodes carrying a
``job_definition`` artifact, boots the kernel under ``qemu-system-riscv64``
on a PTY and runs baseline / kselftest / kvm-kselftest jobs, then posts the
result back as a PULL_LABS body (summary / tests / artifacts.log).

QEMU hardware parameters are owned by the lab (see ``--qemu-*`` options;
defaults mirror the ``qemu-riscv64`` context in ``config/platforms.yaml``).
"""

import argparse
import gzip
import hashlib
import json
import os
import pty
import re
import select
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time

import requests

BASE_URI = "https://staging.kernelci.org:9000/latest"
EVENTS_PATH = "/events"
POLL_PERIOD = 30  # seconds between event polls
REQUEST_TIMEOUT = 60  # API calls
DOWNLOAD_TIMEOUT = 600  # large artifact downloads
DISK_SIZE = "4G"  # ext4 image size; unrelated to QEMU_MEMORY

# Done markers are echoed with a "" split ("===BOOT_""OK===") so the shell's
# echo of the command line never contains the marker text that the executed
# command prints ("===BOOT_OK==="); the reader matches executed output only.
BOOT_OK = "===BOOT_OK==="
KSELFTEST_DONE = "===KSELFTEST_DONE==="

SHELL_PROMPT_RE = re.compile(r"(^|\n)(/ |~ )?#\s*$")

DEFAULT_PROFILE = {
    "binary": os.environ.get("QEMU_BIN", "qemu-system-riscv64"),
    "cpu": os.environ.get("QEMU_CPU", "rv64,v=true"),
    "machine": os.environ.get("QEMU_MACHINE", "virt"),
    "memory": os.environ.get("QEMU_MEMORY", "4G"),
}

# Curated subset of the kvm selftest collection, run with run_kselftest.sh -t.
# perf/stress tests (memslot_perf, mmu_stress, dirty_log_perf, ...) are
# minute-scale workloads that are meaningless under TCG; get-reg-list is a
# known version-drift tracker (kernel newer than the test's blessed list),
# not a riscv regression.  kvm_page_table_test has an internal 120s timeout
# that occasionally trips under TCG load (~1 in 4 runs).  Override via
# --kvm-tests or KVM_TEST_SUBSET.
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


# --- Download and unpack helpers ---

def download(url, dest, expected_sha256=None):
    """Stream *url* to *dest*, verifying size and optional sha256."""
    print(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
        r.raise_for_status()
        length = r.headers.get("Content-Length")
        length = int(length) if length else None
        hasher = hashlib.sha256() if expected_sha256 else None
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                if hasher:
                    hasher.update(chunk)
    size = os.path.getsize(dest)
    if length is not None and size != length:
        os.unlink(dest)
        raise OSError(f"Truncated download {url}: {size}/{length} bytes")
    if hasher and hasher.hexdigest() != expected_sha256:
        os.unlink(dest)
        raise OSError(f"Checksum mismatch for {url}")
    print(f"           -> {dest} ({size} bytes)")


def download_kernel(kernel_url, workspace, expected_sha256=None):
    """Fetch the kernel image; riscv kbuild uploads it gzip-compressed."""
    image_path = os.path.join(workspace, "Image")
    if kernel_url.endswith(".gz"):
        download(kernel_url, f"{image_path}.gz", expected_sha256)
        with (
            gzip.open(f"{image_path}.gz", "rb") as fi,
            open(image_path, "wb") as fo,
        ):
            shutil.copyfileobj(fi, fo)
    else:
        download(kernel_url, image_path, expected_sha256)


def safe_members(tf, max_bytes=8 << 30):
    """Yield members safe to extract unprivileged: no dev/FIFO nodes,
    no absolute/``..`` paths, no escaping links, total size capped."""
    total = 0
    for member in tf.getmembers():
        parts = member.name.replace("\\", "/").split("/")
        if member.name.startswith("/") or ".." in parts:
            continue
        if member.isdev() or member.isfifo():
            continue
        if member.issym() or member.islnk():
            target = os.path.normpath(os.path.join(
                os.path.dirname(member.name), member.linkname))
            if target.startswith(".."):
                continue
        total += member.size
        if total > max_bytes:
            raise tarfile.TarError(f"tarball too large: > {max_bytes} bytes")
        yield member


def extract_tarball(tarball, dest_dir):
    """Extract *tarball* under *dest_dir*; returns the real root directory
    (some tarballs wrap the filesystem in a single top-level directory)."""
    os.makedirs(dest_dir, exist_ok=True)
    print(f"Extracting tarball -> {dest_dir}")
    with tarfile.open(tarball) as tf:
        tf.extractall(dest_dir, members=safe_members(tf))
    entries = os.listdir(dest_dir)
    if len(entries) == 1 and os.path.isdir(os.path.join(dest_dir, entries[0])):
        dest_dir = os.path.join(dest_dir, entries[0])
    return dest_dir


def bake_rootfs_image(workspace, rootfs_url, kselftest_url, modules_url=None,
                      checksums=None):
    """Bake the nfsroot tarball (+ kselftest/modules unpacked inside) into
    an ext4 image via mkfs.ext4 -d: no loop mount, no root.  Same delivery
    as tuxrun - the pipeline's riscv kernels lack virtio-9p."""
    checksums = checksums or {}
    download(rootfs_url, os.path.join(workspace, "rootfs.tar.xz"),
             expected_sha256=checksums.get("rootfs"))
    root_dir = extract_tarball(
        os.path.join(workspace, "rootfs.tar.xz"),
        os.path.join(workspace, "rootfs"))

    download(kselftest_url, os.path.join(workspace, "kselftest.tar"),
             expected_sha256=checksums.get("kselftest"))
    kselftest_dir = os.path.join(root_dir, "opt", "kselftest")
    os.makedirs(kselftest_dir, exist_ok=True)
    with tarfile.open(os.path.join(workspace, "kselftest.tar")) as tf:
        tf.extractall(kselftest_dir, members=safe_members(tf))

    if modules_url:
        download(modules_url, os.path.join(workspace, "modules.tar.xz"),
                 expected_sha256=checksums.get("modules"))
        with tarfile.open(os.path.join(workspace, "modules.tar.xz")) as tf:
            tf.extractall(root_dir, members=safe_members(tf))

    image = os.path.join(workspace, "rootfs.ext4")
    print(f"Building ext4 image (mkfs.ext4 -d) -> {image}")
    subprocess.run(
        ["mkfs.ext4", "-F", "-d", root_dir, image, DISK_SIZE],
        check=True, stdout=subprocess.DEVNULL,
    )
    return image


def mount_cmd(source, fstype, target):
    """mount(8) fails under the bare init=/bin/sh bootstrap (EPERM:
    libmount needs /proc/self/mountinfo before /proc exists), so fall back
    to the raw mount syscall via the rootfs python3."""
    prog = (
        "import ctypes; ctypes.CDLL(None, use_errno=True).mount("
        f"b'{source}', b'{target}', b'{fstype}', 0, None)"
    )
    return (
        f"mount -t {fstype} {source} {target} 2>/dev/null || "
        f'python3 -c "{prog}"'
    )


_MOUNT_PROC = mount_cmd("proc", "proc", "/proc")
_MOUNT_SYS = mount_cmd("sysfs", "sysfs", "/sys")


def qemu_cmd(profile, kernel, initrd=None, drive=None, append=None):
    """Common qemu-system-riscv64 argv (see config/platforms.yaml)."""
    cmd = [
        profile["binary"], "-machine", profile["machine"],
        "-cpu", profile["cpu"], "-m", profile["memory"], "-smp", "4",
        "-kernel", kernel,
    ]
    if initrd:
        cmd += ["-initrd", initrd]
    if drive:
        cmd += ["-drive", drive]
    return cmd + ["-append", append, "-nographic", "-no-reboot"]


def guest_bootstrap(run_lines):
    """Shared guest prologue: mounts plus the test commands (/proc is
    needed by pointer_masking's /proc/self/exe fork+exec subtest)."""
    return (
        "export PATH=/sbin:/bin:/usr/sbin:/usr/bin\n"
        "mount -t devtmpfs devtmpfs /dev 2>/dev/null\n"
        f"{_MOUNT_PROC}\n"
        f"{_MOUNT_SYS}\n"
        f"{run_lines}\n"
        f'echo ===KSELFTEST_""DONE===\n'
    )


# --- QEMU driver ---

def serial_reader(master, proc, output, prompt_ready, done_seen, done_marker):
    """PTY reader thread body: collect serial output and watch for the
    shell prompt and the done marker.  Match on the full buffer first and
    truncate afterwards, so a marker followed by a burst is not missed."""
    tail = b""
    login_sent = False
    while True:
        r, _, _ = select.select([master], [], [], 1.0)
        if not r:
            if proc.poll() is not None:
                break
            continue
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        output.append(chunk.decode(errors="replace"))
        full = tail + chunk
        tail = full[-256:]
        full_text = full.decode(errors="replace")
        if done_marker and done_marker in full_text:
            done_seen.set()
        if prompt_ready.is_set():
            continue
        # Answer a login prompt, or signal a root shell prompt.
        if "login:" in full_text and not login_sent:
            login_sent = True
            try:
                os.write(master, b"root\n")
            except OSError:
                pass
        elif SHELL_PROMPT_RE.search(full_text):
            prompt_ready.set()


def drain_pty(master, output):
    """Read whatever is still buffered on the PTY (e.g. a final kernel
    message written right before QEMU exited) so it lands in the log."""
    import fcntl

    flags = fcntl.fcntl(master, fcntl.F_GETFL)
    fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    try:
        while True:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            output.append(chunk.decode(errors="replace"))
    finally:
        fcntl.fcntl(master, fcntl.F_SETFL, flags)


def run_qemu(qemu, guest_cmds, timeout, done_marker=None):
    """Boot QEMU on a PTY, wait for a shell prompt, drive guest commands.

    A PTY is required: ``-nographic`` does not forward input from a plain
    pipe.  Guest poweroff is not trusted, so QEMU is killed from the host
    side once the done marker is seen or the deadline passes."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        qemu, stdin=slave, stdout=slave, stderr=slave, close_fds=True,
    )
    os.close(slave)

    output = []
    prompt_ready = threading.Event()
    done_seen = threading.Event()
    thread = threading.Thread(
        target=serial_reader,
        args=(master, proc, output, prompt_ready, done_seen, done_marker),
        daemon=True,
    )
    thread.start()
    try:
        deadline = time.time() + timeout
        # Wait for the prompt, but fail fast if QEMU dies at startup
        # (e.g. a bad -cpu option) instead of burning the whole timeout.
        while time.time() < deadline:
            if prompt_ready.is_set():
                try:
                    os.write(master, guest_cmds.encode())
                except OSError:
                    pass
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        # After the commands ran, wait for the done marker, a clean guest
        # exit, or the deadline - whichever comes first.
        while time.time() < deadline and proc.poll() is None:
            if done_marker and done_seen.is_set():
                time.sleep(2)  # let trailing output drain
                break
            time.sleep(0.5)
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        else:
            proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        drain_pty(master, output)
        try:
            os.close(master)
        except OSError:
            pass
        thread.join(timeout=5)
    return "".join(output)


def baseline_qemu(profile, kernel_url, ramdisk_url, workspace,
                  checksums=None):
    """Boot the kernel on a buildroot ramdisk and check it reaches a shell."""
    checksums = checksums or {}
    download_kernel(kernel_url, workspace,
                    expected_sha256=checksums.get("kernel"))
    download(ramdisk_url, os.path.join(workspace, "rootfs.cpio.gz"),
             expected_sha256=checksums.get("ramdisk"))
    qemu = qemu_cmd(
        profile, os.path.join(workspace, "Image"),
        initrd=os.path.join(workspace, "rootfs.cpio.gz"),
        # The cpio.gz is an initramfs, not a legacy block-device initrd:
        # there is no /dev/ram0 on modern kernels, so no root= here.
        append="console=ttyS0 earlycon=sbi",
    )
    guest_cmds = f'echo ===BOOT_""OK===\n'
    return qemu, guest_cmds


def kselftest_qemu(profile, kernel_url, rootfs_url, kselftest_url,
                   collections, workspace, checksums=None):
    """Boot the Debian kselftest rootfs and run a kselftest collection."""
    download_kernel(kernel_url, workspace,
                    expected_sha256=(checksums or {}).get("kernel"))
    image = bake_rootfs_image(workspace, rootfs_url, kselftest_url,
                              checksums=checksums)
    qemu = qemu_cmd(
        profile, os.path.join(workspace, "Image"),
        drive=f"file={image},if=virtio,format=raw",
        append="console=ttyS0 root=/dev/vda rw earlycon=sbi init=/bin/sh",
    )
    guest_cmds = guest_bootstrap(f"cd /opt/kselftest\n"
                                 f"sh run_kselftest.sh -c {collections}")
    return qemu, guest_cmds


def kselftest_kvm_qemu(profile, kernel_url, rootfs_url, modules_url,
                       kselftest_url, tests_subset, workspace,
                       checksums=None):
    """Boot with the H extension, load kvm.ko and run a curated KVM
    selftest subset (nested VMs under TCG; see KVM_TEST_SUBSET)."""
    download_kernel(kernel_url, workspace,
                    expected_sha256=(checksums or {}).get("kernel"))
    image = bake_rootfs_image(workspace, rootfs_url, kselftest_url,
                              modules_url, checksums=checksums)
    cpu = profile["cpu"]
    if "h=true" not in cpu:
        cpu += ",h=true"
    kvm_profile = dict(profile, cpu=cpu)
    qemu = qemu_cmd(
        kvm_profile, os.path.join(workspace, "Image"),
        drive=f"file={image},if=virtio,format=raw",
        append="console=ttyS0 root=/dev/vda rw earlycon=sbi init=/bin/sh",
    )
    tests = " ".join(f"-t kvm:{t}" for t in tests_subset)
    guest_cmds = guest_bootstrap(
        # kvm.ko has no module dependencies; devtmpfs creates /dev/kvm
        # once it is loaded.
        "insmod $(find /lib/modules -name kvm.ko | head -1)\n"
        "cd /opt/kselftest\n"
        f"sh run_kselftest.sh {tests}")
    return qemu, guest_cmds


# ---------------------------------------------------------------------------
# PULL_LABS protocol: poll, run, report
# ---------------------------------------------------------------------------

def pollevents(api_url, timestamp):
    url = (
        f"{api_url}{EVENTS_PATH}?state=available&kind=job&limit=1000"
        f"&recursive=true&from={timestamp}"
    )
    print(url)
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def retrieve_job_definition(url):
    print(f"Retrieving job definition from: {url}")
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def post_result(callback, token, body):
    """Post a PULL_LABS result body to the recorded callback endpoint, with
    a couple of retries - a single network blip must not lose a result."""
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
                callback, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
            print(f"Callback status: {response.status_code}")
            response.raise_for_status()
            return
        except requests.exceptions.RequestException as error:
            last_error = error
            print(f"Callback attempt {attempt + 1}/3 failed: {error}")
            time.sleep(2 * (attempt + 1))
    raise last_error


def error_body(system, message):
    """An infra-error result body (matches kernelci-core
    pull_labs.Callback.is_infra_error() via metadata.error_code)."""
    return {
        "metadata": {"system": system, "error_code": "Infrastructure"},
        "summary": {"total": 0, "failed": 0},
        "tests": {},
        "artifacts": {"log": message},
    }


def summarize_kselftest(output, collections):
    """TAP output -> (summary, tests_out).  A test that started but produced
    no result line (e.g. the runner crashed on it) counts as a failure."""
    ok = len(re.findall(r"^ok \d+ ", output, re.M))
    skip = len(re.findall(r"^ok \d+ [^\r\n]*# SKIP", output, re.M))
    ok -= skip
    not_ok = len(re.findall(r"^not ok \d+ ", output, re.M))
    started = set(re.findall(
        r"^# selftests: " + re.escape(collections) + r": (\S+)", output, re.M))
    finished = set(re.findall(
        r"^(?:ok|not ok) \d+ selftests: " + re.escape(collections) +
        r": (\S+)", output, re.M))
    missing = started - finished
    not_ok += len(missing)
    if missing:
        print(f"kselftest {collections}: {len(missing)} test(s) started "
              f"but never finished: {', '.join(sorted(missing))}")
    print(f"kselftest {collections}: {ok} ok, {skip} skipped, "
          f"{not_ok} not ok")
    status = "pass" if (ok > 0 and not_ok == 0) else "fail"
    summary = {"total": ok + skip + not_ok, "failed": not_ok,
               "skipped": skip}
    return summary, {f"kselftest-{collections}": {"status": status}}


def run_job(job, args):
    environment = job.get("environment", {})
    system = environment.get("platform", "qemu-riscv64")
    callback = job.get("callback", {})
    callback_url = callback.get("url")
    # The callback token is a "remote token" name shared with the pipeline
    # admins; the worker holds the secret in an env var.
    callback_token = os.environ.get("PULL_LABS_CALLBACK_TOKEN")
    checksums = job.get("integrity", {}).get("sha256", {})
    profile = getattr(args, "profile", DEFAULT_PROFILE)

    own_temp = not getattr(args, "output_dir", None)
    base = getattr(args, "output_dir", None) or tempfile.mkdtemp(
        prefix="riscv-pull-")
    workspace = os.path.join(base, f"job-{time.time():.0f}")
    os.makedirs(workspace, exist_ok=True)
    try:
        _run_job_in_workspace(job, args, workspace, profile, checksums,
                              callback_url, callback_token, system)
    finally:
        if own_temp and not getattr(args, "keep_workspace", False):
            shutil.rmtree(base, ignore_errors=True)


def _report_missing(callback_url, callback_token, system, message):
    print(f"Skipping - {message}")
    if callback_url:
        post_result(callback_url, callback_token,
                    error_body(system, message))


def _run_job_in_workspace(job, args, workspace, profile, checksums,
                          callback_url, callback_token, system):
    artifacts = job.get("artifacts", {})
    tests = job.get("tests", [])
    kernel_url = artifacts.get("kernel")
    if not kernel_url:
        return _report_missing(callback_url, callback_token, system,
                               "missing kernel artifact")

    picked = pick_driver(job, args, profile, checksums, workspace,
                         callback_url, callback_token, system)
    if picked is None:
        return
    is_kselftest, collections, qemu, guest_cmds = picked

    timeout = next(
        (t.get("timeout_s", 0) for t in tests if t.get("timeout_s")), 600)
    print("Booting QEMU:", " ".join(qemu))
    marker = KSELFTEST_DONE if is_kselftest else BOOT_OK
    output = run_qemu(qemu, guest_cmds, timeout, done_marker=marker)

    log_path = os.path.join(workspace, "qemu-test.log")
    with open(log_path, "w") as f:
        f.write(output)

    summary, tests_out = summarize_kselftest(output, collections) \
        if is_kselftest else summarize_boot(output)
    body = {
        "metadata": {"system": system},
        "summary": summary,
        "tests": tests_out,
        "artifacts": {"log": output},
    }
    post_result(callback_url, callback_token, body)


def summarize_boot(output):
    booted = (BOOT_OK in output) or ("/ #" in output)
    print(f"baseline boot: {'PASS' if booted else 'FAIL'}")
    summary = {"total": 1, "failed": 0 if booted else 1}
    return summary, {"boot": {"status": "pass" if booted else "fail"}}


def pick_driver(job, args, profile, checksums, workspace,
                callback_url, callback_token, system):
    """Pick a driver from the test type; returns (is_kselftest,
    collections, qemu, guest_cmds) or None after reporting a missing
    artifact."""
    artifacts = job.get("artifacts", {})
    tests = job.get("tests", [])
    kernel_url = artifacts.get("kernel")
    # "kselftest-kvm-*" needs the kvm module + H extension; other
    # "kselftest-*" types run a collection; anything else is baseline.
    is_kvm = any(t.get("type", "").startswith("kselftest-kvm")
                 for t in tests)
    is_kselftest = is_kvm or any(
        t.get("type", "").startswith("kselftest") for t in tests)
    collections = getattr(args, "collections", None)
    if not collections and is_kselftest:
        collections = tests[0].get("type", "kselftest-riscv").split(
            "kselftest-", 1)[-1]

    print("Booting QEMU",
          "kvm" if is_kvm else "kselftest" if is_kselftest else "baseline")
    if is_kvm:
        rootfs_url = artifacts.get("rootfs")
        modules_url = artifacts.get("modules")
        kselftest_url = artifacts.get("kselftest")
        if not (rootfs_url and modules_url and kselftest_url):
            return _report_missing(
                callback_url, callback_token, system,
                "job definition has no rootfs/modules/kselftest")
        subset = (getattr(args, "kvm_tests", None)
                  or tests[0].get("subset") or KVM_TEST_SUBSET)
        qemu, guest_cmds = kselftest_kvm_qemu(
            profile, kernel_url, rootfs_url, modules_url, kselftest_url,
            subset, workspace, checksums=checksums)
    elif is_kselftest:
        rootfs_url = artifacts.get("rootfs")
        kselftest_url = artifacts.get("kselftest")
        if not rootfs_url or not kselftest_url:
            return _report_missing(
                callback_url, callback_token, system,
                "job definition has no rootfs/kselftest")
        qemu, guest_cmds = kselftest_qemu(
            profile, kernel_url, rootfs_url, kselftest_url,
            collections, workspace, checksums=checksums)
    else:
        ramdisk_url = artifacts.get("ramdisk")
        if not ramdisk_url:
            return _report_missing(callback_url, callback_token, system,
                                   "job definition has no ramdisk")
        qemu, guest_cmds = baseline_qemu(
            profile, kernel_url, ramdisk_url, workspace,
            checksums=checksums)
    return is_kselftest, collections, qemu, guest_cmds


def handle_event(event, args, failures):
    """Process one job event; failures are counted per node."""
    node = event.get("node", {})
    node_id = node.get("id", "unknown")
    artifacts = node.get("artifacts", {})
    job_definition_url = artifacts.get("job_definition", "")

    if not job_definition_url or not job_definition_url.startswith("http"):
        return True  # not a pull_labs job; nothing to do

    data = event.get("data", {}).get("data", {})
    platform = data.get("platform")
    runtime = data.get("runtime")
    if getattr(args, "platform", None) and platform != args.platform:
        return True
    if getattr(args, "runtime", None) and runtime != args.runtime:
        return True

    print(f"Processing job {node_id} "
          f"(platform: {platform}, runtime: {runtime})")
    try:
        job = retrieve_job_definition(job_definition_url)
        run_job(job, args)
        return True
    except Exception as error:
        import traceback

        print(f"Error processing event {node_id}: {error}")
        traceback.print_exc()
        failures[node_id] = failures.get(node_id, 0) + 1
        if failures[node_id] >= 3:
            print(f"Giving up on {node_id} after "
                  f"{failures[node_id]} failures")
        return False


def save_state(state_file, state):
    if not state_file:
        return
    with open(state_file, "w") as f:
        json.dump(state, f)


def load_state(state_file):
    if not state_file or not os.path.exists(state_file):
        return {"timestamp": None, "seen": []}
    with open(state_file) as f:
        return json.load(f)


def poll_loop(args):
    import fcntl

    state_file = getattr(args, "state_file", None)
    lock_file = f"{state_file}.lock" if state_file else None
    lock = None
    if lock_file:
        lock = open(lock_file, "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("Another worker instance holds the lock; exiting.")
            raise SystemExit(1)

    state = load_state(state_file)
    seen = set(state.get("seen", []))
    timestamp = getattr(args, "since", None) or state.get("timestamp") \
        or "1970-01-01T00:00:00.000000"
    failures = {}
    retry_count = 0
    while True:
        try:
            events = pollevents(args.api_url, timestamp)
            retry_count = 0
        except requests.exceptions.RequestException as error:
            retry_count += 1
            print(f"Error fetching events (attempt {retry_count}/"
                  f"{args.max_retries}): {error}")
            if retry_count >= args.max_retries:
                print(f"Max retries ({args.max_retries}) reached. Exiting.")
                raise SystemExit(1)
            print(f"Retrying in {POLL_PERIOD} seconds...")
            time.sleep(POLL_PERIOD)
            continue
        if not events:
            print(f"No new events, sleeping for {POLL_PERIOD} seconds",
                  flush=True)
            time.sleep(POLL_PERIOD)
            continue

        print(f"Got {len(events)} events", flush=True)
        # Run every unprocessed event; only advance the cursor when the
        # whole batch succeeded, so a failed job is retried next poll.
        all_ok = True
        for event in events:
            node_id = event.get("node", {}).get("id")
            if node_id and node_id in seen:
                continue
            if not handle_event(event, args, failures):
                all_ok = False
            elif node_id:
                seen.add(node_id)
                if len(seen) > 1000:
                    seen = set(list(seen)[-1000:])
        if all_ok:
            # The events API is not sorted; never move the cursor backwards.
            timestamp = max(
                (e.get("timestamp", timestamp) for e in events),
                default=timestamp)
        else:
            print("Some events failed; cursor not advanced, "
                  "will retry next poll", flush=True)
        save_state(state_file, {"timestamp": timestamp, "seen": sorted(seen)})


def main():
    parser = argparse.ArgumentParser(
        description="Run KernelCI pull_labs qemu-riscv64 jobs on local QEMU.")
    parser.add_argument("--api-url", default=BASE_URI,
                        help="KernelCI API base URL to poll for events.")
    parser.add_argument("--platform", default="qemu-riscv64",
                        help=("Only pull jobs for this platform "
                              "(default: qemu-riscv64)."))
    parser.add_argument("--runtime", default="pull-labs-riscv",
                        help=("Only pull jobs for this runtime/lab name "
                              "(default: pull-labs-riscv)."))
    parser.add_argument("--collections", default=None,
                        help=("kselftest collection(s) to run (default: "
                              "taken from the job definition test type)."))
    parser.add_argument("--output-dir",
                        help="Directory to save kernels/rootfs/logs under.")
    parser.add_argument("--keep-workspace", action="store_true",
                        help="Do not remove per-job workspaces.")
    parser.add_argument("--state-file", default="riscv-pull-worker-state.json",
                        help=("Persist cursor + processed node ids here "
                              "(default: riscv-pull-worker-state.json)."))
    parser.add_argument("--since",
                        help="Poll events starting from this timestamp.")
    parser.add_argument("--max-retries", type=int, default=5,
                        help="Max consecutive API retries (default: 5).")
    parser.add_argument("--qemu-bin", default=DEFAULT_PROFILE["binary"])
    parser.add_argument("--qemu-cpu", default=DEFAULT_PROFILE["cpu"])
    parser.add_argument("--qemu-machine", default=DEFAULT_PROFILE["machine"])
    parser.add_argument("--qemu-memory", default=DEFAULT_PROFILE["memory"])
    parser.add_argument("--kvm-tests", nargs="*",
                        default=KVM_TEST_SUBSET,
                        help="KVM selftest subset (default: curated list).")
    args = parser.parse_args()
    args.profile = {
        "binary": args.qemu_bin,
        "cpu": args.qemu_cpu,
        "machine": args.qemu_machine,
        "memory": args.qemu_memory,
    }
    poll_loop(args)


if __name__ == "__main__":
    main()
