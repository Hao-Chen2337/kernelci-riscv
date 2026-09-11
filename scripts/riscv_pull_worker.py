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

Baked guest images are cached in work/env/baked/ keyed on the bake inputs
(rootfs URL + modules URL + modules-load.d list + DISK_SIZE), so the second
job with the same inputs skips a ~144MB download and a 4GB mkfs.ext4; see
baked_rootfs_image().  Each entry is ~4GB (sparse), at most
BAKE_CACHE_MAX_ENTRIES are kept, and `rm -rf work/env/baked` clears them.

Full parameter and behavior reference: docs/INTERNAL-NOTES.md (internal).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timedelta, timezone

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
    """Remove ANSI colour/control sequences from tuxrun console output.

    Returns *text* itself when there is nothing to strip: a real job's console
    runs to megabytes and its callers slice bounded windows out of the result,
    so an unconditional copy is pure overhead."""
    if ANSI_RE.search(text) is None:
        return text
    return ANSI_RE.sub("", text)


def stamp(message):
    """Progress line with a clock.

    Added after a `worker --once` run took 17m42s where the internal notes
    promised ~7 minutes, and ~14 of those minutes sat between two jobs with no
    way to tell where they went: every line looked alike and the only clock was
    the log file's.  The two phases that can take minutes - preparing the guest
    (download + baking a 4GB ext4 per job) and tuxrun itself - now report their
    own duration, so the next report can attribute the time instead of guessing.
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


BASE_URI = "https://api.kernelci.org"
EVENTS_PATH = "/events"
REQUEST_TIMEOUT = 60
DISK_SIZE = "4G"  # ext4 image size; unrelated to QEMU memory
# Baked-image cache limits (see baked_rootfs_image): each entry is a full
# DISK_SIZE image, so the cache is bounded by entry count.  Two or three
# entries cover the real input sets (kselftest-riscv bakes no modules,
# kselftest-kvm bakes modules.tar.xz, a different rootfs is a third).
BAKE_CACHE_MAX_ENTRIES = 3
BAKE_CACHE_TMP_AGE_S = 3600  # a killed bake's .tmp is ignored, then aged out
DEFAULT_TIMEOUT = 1800  # seconds, when the job def carries no timeout
LOG_LIMIT = 2 << 20  # cap of log text embedded in a result body
MAX_DOWNLOAD_SIZE = 4 << 30  # 4 GiB per download; rootfs tarballs fit easily
CURSOR_OVERLAP_S = 900  # re-scan window: the events API is not sorted
SEEN_LIMIT = 20000  # seen-node ids kept in the state file; sized far
# beyond what one CURSOR_OVERLAP_S window can produce, so eviction can
# never re-expose a recently processed node to a re-run.
# Per-read gap, not a total budget: artifact hosts (storage.kernelci.org,
# files.kernelci.org) go quiet mid-transfer often enough that the old 300s
# meant "hang for five minutes, then retry".  60s of silence is a stalled
# connection; a slow-but-moving download is unaffected.
DOWNLOAD_TIMEOUT = 60

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


def _resume_offset(part_path, meta_path, url):
    """Bytes already on disk for *url* from an earlier attempt (0 = start over).

    production storage truncates big transfers routinely (a 144MB rootfs
    arriving as 1.3MB is ordinary), and restarting from zero each time means a
    flaky link never finishes.  The partial file is only trusted when its
    sidecar says it belongs to *url* and does not already exceed the expected
    size - otherwise a stale partial would be prepended to good data."""
    try:
        with open(meta_path) as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return 0
    if not isinstance(meta, dict) or meta.get("url") != url:
        return 0
    try:
        size = os.path.getsize(part_path)
    except OSError:
        return 0
    total = meta.get("total")
    if isinstance(total, int) and size > total:
        return 0
    return size


def _write_resume_meta(meta_path, url, total):
    tmp_path = f"{meta_path}.tmp"
    with open(tmp_path, "w") as handle:
        json.dump({"url": url, "total": total}, handle)
    os.replace(tmp_path, meta_path)


def download(url, dest, max_size=MAX_DOWNLOAD_SIZE):
    """Stream *url* to *dest*, verifying size and resuming partial transfers.

    The bytes land in ``<dest>.part`` and are only renamed into place once the
    full length has arrived, so *dest* is never a half file.  A truncated or
    stalled attempt keeps its partial data (with a sidecar recording which URL
    it belongs to), and the next attempt - even a later run of the same
    command - asks the server for the remainder with a Range request."""
    print(f"Downloading {url}")
    last_error = None
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    part_path = f"{dest}.part"
    meta_path = f"{dest}.part.json"
    for attempt in range(3):
        try:
            offset = _resume_offset(part_path, meta_path, url)
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            if offset:
                print(f"  resuming at {offset} bytes")
            with requests.get(
                url, stream=True, timeout=DOWNLOAD_TIMEOUT,
                allow_redirects=False, headers=headers
            ) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    raise requests.exceptions.RequestException(
                        f"refusing redirect for {url}"
                    )
                if offset and response.status_code == 200:
                    # Server ignored the Range header: start from scratch
                    # rather than appending to a file it knows nothing about.
                    print("  server ignored the Range request; restarting")
                    offset = 0
                    headers = {}
                elif offset and response.status_code != 206:
                    raise requests.exceptions.RequestException(
                        f"unexpected status {response.status_code} for a "
                        f"resumed download of {url}"
                    )
                response.raise_for_status()
                total = None
                content_range = response.headers.get("Content-Range")
                if content_range and "/" in content_range:
                    try:
                        total = int(content_range.rsplit("/", 1)[1])
                    except ValueError:
                        total = None
                if total is None:
                    length = response.headers.get("Content-Length")
                    try:
                        total = int(length) + offset if length else None
                    except ValueError:
                        total = None
                if total is not None and total > max_size:
                    raise OSError(f"Download too large {url}: {total} > {max_size}")
                size = offset
                try:
                    with open(part_path, "ab" if offset else "wb") as handle:
                        for chunk in response.iter_content(chunk_size=1 << 20):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            size += len(chunk)
                            if size > max_size:
                                raise OSError(
                                    f"Download too large {url}: > {max_size}")
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    # Keep what arrived: the next attempt resumes from here.
                    _write_resume_meta(meta_path, url, total)
                    raise
            _write_resume_meta(meta_path, url, total)
            if total is not None and size != total:
                raise OSError(f"Truncated download {url}: {size}/{total} bytes")
            os.replace(part_path, dest)
            if os.path.exists(meta_path):
                os.unlink(meta_path)
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
    max_size=MAX_DOWNLOAD_SIZE, image_path=None
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

    image_path: where the ext4 file is written (default <workspace>/rootfs.ext4).
    Callers that publish the image somewhere else (the baked-image cache, whose
    temporary file must sit in the cache directory so the publish is a rename)
    pass it explicitly.  Everything else - tarball, extracted tree - still
    lives under *workspace* and is discarded with it.
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
    image = image_path or os.path.join(workspace, "rootfs.ext4")
    print(f"Building ext4 image (mkfs.ext4 -d) -> {image}")
    subprocess.run(
        ["mkfs.ext4", "-F", "-d", root_dir, image, DISK_SIZE],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return image


_SIZE_UNITS = {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}


def disk_size_bytes(size=DISK_SIZE):
    """DISK_SIZE ("4G") in bytes, for validating a cached image's length."""
    match = re.fullmatch(r"(\d+)\s*([KMGT]?)", size.strip().upper())
    if not match or match.group(2) not in _SIZE_UNITS:
        raise ValueError(f"unsupported image size: {size!r}")
    return int(match.group(1)) * _SIZE_UNITS[match.group(2)]


def _human_size(count):
    """Bytes as a short human string (used in the cache log lines)."""
    value = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{count}B"


def bake_cache_dir():
    """Where baked guest images are cached.

    Default ``work/env/baked/``: ``work/`` is gitignored and already the
    documented home of the multi-GB guest testbed (``work/env/rootfs-kvm.ext4``),
    so the big regenerable files stay in one place that no one commits.  A
    separate *subdirectory* rather than that exact path, because
    ``work/env/rootfs-kvm.ext4`` is a different artifact owned by
    ``./run.sh provision`` and its ``work/env/.manifest.json``: two writers on
    one file would race, and one fixed filename cannot hold the several
    distinct input sets a worker sees (kselftest-riscv bakes no modules,
    kselftest-kvm bakes modules.tar.xz, a lab may point --rootfs elsewhere).

    Override with KCI_BAKE_CACHE_DIR; disable with KCI_BAKE_CACHE=0 (then every
    job bakes into its own workspace, as before).  Returns "" when disabled."""
    if os.environ.get("KCI_BAKE_CACHE", "").strip().lower() in ("0", "off",
                                                               "no", "false"):
        return ""
    override = os.environ.get("KCI_BAKE_CACHE_DIR", "").strip()
    if override:
        return override
    # realpath, not abspath: a symlinked launcher (a wrapper script in /tmp, a
    # symlink in ~/bin) would otherwise place the multi-GB cache next to the
    # symlink - outside the gitignored work/ - and silently stop reusing it
    # whenever the two entry points are invoked differently.
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return os.path.join(root, "work", "env", "baked")


def cache_dir_writable(cachedir):
    """True when a file can actually be created in *cachedir*.

    ``os.makedirs(exist_ok=True)`` succeeds on a directory that exists but is
    not writable - a read-only mount, or ``work/env/baked`` left root-owned by
    a single ``sudo`` run - and ``os.access`` is unreliable for root and ACLs,
    so probe by writing.  Without this probe the bake was aimed into such a
    directory and ``mkfs.ext4`` failed the whole job, making an optional
    optimisation able to break jobs that worked before it existed.
    """
    if not cachedir:
        return False
    probe = os.path.join(cachedir, f".probe{os.getpid()}")
    try:
        with open(probe, "w") as handle:
            handle.write("")
        os.unlink(probe)
        return True
    except OSError:
        return False


def bake_cache_inputs(rootfs_url, modules_url, boot_modules):
    """The complete input set of a bake, as one comparable string.

    Everything mkfs.ext4's result depends on: the rootfs tarball, the modules
    tarball, the modules-load.d list baked into the tree and the image size.
    A key that omitted any of these would hand a job an image built from other
    inputs, so the test for "changed URL must not reuse" is exactly this
    serialisation."""
    return json.dumps(
        {
            "rootfs": rootfs_url,
            "modules": modules_url or "",
            "boot_modules": sorted(boot_modules or []),
            "disk_size": DISK_SIZE,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def bake_cache_key(inputs):
    """Short stable filename for an input set (sha256 of the serialisation)."""
    return hashlib.sha256(inputs.encode()).hexdigest()[:16]


def _cache_path(cachedir, key, suffix):
    return os.path.join(cachedir, f"{key}{suffix}")


def cached_rootfs_image(cachedir, inputs):
    """The cached image baked from exactly *inputs*, or "" on a miss.

    A hit requires ALL of: a regular file that is not a symlink and resolves
    inside the cache directory (a symlink could otherwise hand tuxrun an
    unrelated disk outside it), a sidecar recording byte-identical *inputs*,
    and an image whose size is both the recorded size and the size mkfs.ext4
    was asked to write.  The sidecar is published LAST, so an interrupted bake
    leaves an entry that is simply never trusted."""
    if not cachedir:
        return ""
    key = bake_cache_key(inputs)
    image = _cache_path(cachedir, key, ".ext4")
    if os.path.islink(image) or not os.path.isfile(image):
        return ""
    cachedir = os.path.realpath(cachedir)
    if os.path.dirname(os.path.realpath(image)) != cachedir:
        return ""
    try:
        with open(_cache_path(cachedir, key, ".json")) as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return ""
    if not isinstance(record, dict) or record.get("inputs") != inputs:
        return ""
    expected = disk_size_bytes()
    size = os.path.getsize(image)
    if size != expected or record.get("size") != expected:
        return ""
    return image


def _write_cache_sidecar(cachedir, key, record):
    """Write the entry's sidecar atomically (tmp + rename, like save_manifest).

    Written only after the image is in place: a crash in between leaves an
    image nobody trusts rather than a sidecar promising a file that is not
    there."""
    path = _cache_path(cachedir, key, ".json")
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as handle:
        json.dump(record, handle, indent=1, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def prune_bake_cache(cachedir, keep_key, max_entries=BAKE_CACHE_MAX_ENTRIES):
    """Bound the cache: drop the least recently published entries and any
    leftover temporary file from a bake that was killed.

    Each entry is a full-size image (~4GB), so an unbounded cache fills a disk
    one input change at a time.  Only files this module creates are touched:
    ``<key>.ext4`` + ``<key>.json`` pairs and ``<key>.<suffix>.tmp<pid>``.

    Enumerated from BOTH file kinds: a publish that wrote the image and then
    failed to write its sidecar used to be invisible here (only ``*.json`` was
    listed), so each occurrence parked another ~4GB forever.  Such an image is
    unusable for reuse, so it is counted against the cap and removed once it is
    older than the publish window - younger ones may belong to a publish that is
    still running (image renamed, sidecar next)."""
    try:
        names = sorted(os.listdir(cachedir))
    except OSError:
        return []
    removed = []
    now = time.time()
    keys = {}
    for name in names:
        match = re.fullmatch(r"([0-9a-f]{16})\.(json|ext4)", name)
        if match:
            keys.setdefault(match.group(1), set()).add(match.group(2))
    entries = []
    for key in sorted(keys):
        parts = keys[key]
        image = _cache_path(cachedir, key, ".ext4")
        sidecar = _cache_path(cachedir, key, ".json")
        if "json" in parts and "ext4" not in parts:
            # sidecar without an image: an entry somebody removed by hand
            try:
                os.unlink(sidecar)
                removed.append(os.path.basename(sidecar))
            except OSError:
                pass
            continue
        if os.path.islink(image):
            continue
        try:
            mtime = os.path.getmtime(image)
        except OSError:
            continue
        if "json" not in parts:
            # Published image whose sidecar is missing: never reusable.  Count
            # it so it cannot accumulate silently, and drop it once it is old
            # enough that no live publish can own it.
            entries.append((mtime, key))
            if now - mtime > BAKE_CACHE_TMP_AGE_S:
                try:
                    os.unlink(image)
                    removed.append(os.path.basename(image))
                except OSError:
                    pass
                entries.pop()
            continue
        entries.append((mtime, key))
    entries.sort(reverse=True)
    # keep_key counts towards the cap (it is one of the entries on disk); it is
    # only exempt from *eviction*.  Skipping it while counting could leave
    # max_entries + 1 entries behind after a long bake raced another publisher.
    evictable = [key for _, key in entries if key != keep_key]
    overflow = len(entries) - max_entries
    for key in evictable[:max(0, overflow)]:
        for suffix in (".ext4", ".json"):
            path = _cache_path(cachedir, key, suffix)
            try:
                os.unlink(path)
                removed.append(os.path.basename(path))
            except OSError:
                pass
    for name in names:
        # Only this module's own leftovers: "<key>.ext4.tmp<pid>" from a bake
        # and "<key>.json.tmp<pid>" from a sidecar write.  A fresh one may
        # belong to a bake still running (the age test is what protects it, not
        # the key), and an old one is what a killed process left behind.
        if ".tmp" not in name:
            continue
        path = os.path.join(cachedir, name)
        try:
            if now - os.path.getmtime(path) > BAKE_CACHE_TMP_AGE_S:
                os.unlink(path)
                removed.append(name)
        except OSError:
            pass
    return removed


def publish_baked_image(cachedir, key, inputs, image, baked_s):
    """Move a freshly baked image into the cache.

    The bake wrote ``<key>.ext4.tmp<pid>`` inside the cache directory, so
    publishing is one rename on one filesystem: a reader sees either the
    previous entry or the complete new image, never a half-written one, and a
    bake that is killed mid-way (leaving only the .tmp) cannot poison the
    entry.  The size is checked before the rename - mkfs.ext4 is handed
    DISK_SIZE, so anything else means the file in hand is not the image."""
    expected = disk_size_bytes()
    size = os.path.getsize(image)
    if size != expected:
        raise OSError(
            f"refusing to publish {image}: {size} bytes, expected {expected}"
        )
    final = _cache_path(cachedir, key, ".ext4")
    os.replace(image, final)
    _write_cache_sidecar(
        cachedir,
        key,
        {
            "inputs": inputs,
            "key": key,
            "size": size,
            "disk_size": DISK_SIZE,
            "baked_s": round(baked_s, 1),
            "created": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "image": final,
        },
    )
    return final


def baked_rootfs_image(
    workspace, rootfs_url, label, boot_modules=None, modules_url=None,
    max_size=MAX_DOWNLOAD_SIZE
):
    """A bootable ext4 image for these inputs: reused from the cache when one
    was baked from exactly the same ones, otherwise baked and cached.

    A real batch spent ``kselftest-riscv: guest prepared in 144.4s`` and
    ``kselftest-kvm: guest prepared in 180.9s`` re-downloading the same ~144MB
    nfsroot tarball and re-baking the same 4GB ext4 image per job, while
    ``boot: guest prepared in 0.0s`` showed what a job costs without that step.
    The bake is a function of the inputs in bake_cache_inputs(), so the second
    job with the same ones gets the image from disk.

    The key is the *URL*, not the bytes: content that is replaced behind an
    unchanged URL is not noticed (adversarial review demonstrated it).  The
    production artifact URLs embed the build id
    (``/kbuild-gcc-14-riscv-<id>/``) or a rootfs version directory, so they are
    immutable in practice; if you ever repoint a URL at different content, run
    with ``KCI_BAKE_CACHE=0`` or ``rm -rf work/env/baked``.  Checking the bytes
    would mean downloading them, which is exactly what the cache exists to
    avoid."""
    inputs = bake_cache_inputs(rootfs_url, modules_url, boot_modules)
    cachedir = bake_cache_dir()
    key = bake_cache_key(inputs)
    hit = cached_rootfs_image(cachedir, inputs)
    if hit:
        stamp(f"{label}: guest rootfs cache hit {hit} "
              f"({_human_size(os.path.getsize(hit))}, key {key}) - "
              "no download, no bake")
        return hit
    started = time.time()
    target = ""
    if cachedir:
        try:
            os.makedirs(cachedir, exist_ok=True)
        except OSError as error:
            # An unusable cache directory must not fail the job: bake into the
            # workspace exactly as before and report the reason once.
            stamp(f"{label}: bake cache unusable ({error}); baking without it")
            cachedir = ""
    if cachedir and not cache_dir_writable(cachedir):
        stamp(f"{label}: bake cache {cachedir} exists but is not writable; "
              "baking without it")
        cachedir = ""
    if cachedir:
        # In the cache directory, so publish_baked_image is a same-filesystem
        # rename even when the workspace sits on another mount (the worker's
        # default workspace base is /tmp).
        target = _cache_path(cachedir, key, f".ext4.tmp{os.getpid()}")

    def _bake_into(image_path):
        return bake_rootfs_image(
            workspace,
            rootfs_url,
            boot_modules=boot_modules,
            modules_url=modules_url,
            max_size=max_size,
            image_path=image_path or None,
        )

    try:
        image = _bake_into(target)
    except Exception as error:
        # Deliberately broad: every cache-specific failure (disk full, the
        # directory turned read-only between the probe and mkfs, a publish that
        # cannot rename) must fall back to the pre-cache behaviour instead of
        # failing the run.
        if not target:
            raise
        # Cache-specific failures (disk full, the directory turned read-only
        # between the probe and mkfs, a publish that cannot rename) fall back to
        # the pre-cache behaviour instead of failing the run.  Only reachable
        # when a cache target was set, so the retry cannot loop: the second bake
        # writes into the workspace.
        stamp(f"{label}: baking into the cache failed ({error}); retrying "
              "without the cache")
        try:
            os.unlink(target)
        except OSError:
            pass
        target = ""
        cachedir = ""
        image = _bake_into("")
    except BaseException:
        if target:
            # Best effort: a killed process cannot run this, which is why the
            # reader ignores .tmp files and prune_bake_cache() ages them out.
            try:
                os.unlink(target)
            except OSError:
                pass
        raise
    baked_s = time.time() - started
    if not target:
        return image
    try:
        published = publish_baked_image(cachedir, key, inputs, image, baked_s)
    except OSError as error:
        # Caching is an optimisation: if the image cannot be moved into the
        # cache (a rename that fails, a full disk, a sidecar that cannot be
        # written), report it and hand tuxrun the image that WAS baked instead
        # of failing the job.  A published image without its sidecar is
        # unusable for reuse, so it counts against the cap and prune ages it
        # out (see prune_bake_cache).
        stamp(f"{label}: could not publish the baked image to the cache "
              f"({error}); using it from the workspace instead")
        return image
    stamp(f"{label}: guest rootfs baked in {baked_s:.1f}s -> {published} "
          f"(key {key}); the next job with the same inputs reuses it")
    for name in prune_bake_cache(cachedir, key):
        stamp(f"{label}: bake cache pruned {name}")
    return published


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
        image = baked_rootfs_image(
            workspace,
            rootfs_url,
            test_type,
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


def _quoted(text):
    """A dict key/value marker for *text*, in either quote style.

    A log line can be a plain Python repr (``'case': 'job'``), a JSON object
    (``"case": "job"``) or the repr of a repr - LAVA embeds the dispatcher's
    own repr inside its message, doubling the backslashes (``\\'case\\'``).
    Only the *markers* have to tolerate the escapes this way; a captured field
    value is matched in plain form (see _verdict_reason)."""
    return r"\\?['\"]" + re.escape(text) + r"\\?['\"]"


# LAVA's authoritative verdict: a job case dict carrying
# ``error_type: Infrastructure``.  The gap between the two fields is BOUNDED
# but spans newlines, so the same pattern reads a one-line repr, a JSON object
# and a pretty-printed multi-line dict - without letting the search wander
# across a multi-megabyte console the way an unbounded ``.*?`` would.
JOB_CASE_GAP = 8192
JOB_CASE_INFRA_RE = re.compile(
    _quoted("case") + r"\s*:\s*" + _quoted("job")
    + rf"[\s\S]{{0,{JOB_CASE_GAP}}}?"
    + _quoted("error_type") + r"\s*:\s*" + _quoted("Infrastructure")
)
# Fail-safe, deliberately NOT distance-bounded: the bounded pattern above is
# what makes the scan linear, but a case dict whose own text exceeds the gap
# (a very long error_msg) then fails to match and a real infrastructure failure
# is reported as an ordinary job failure (status 2 instead of 3, error_type Job
# instead of Infrastructure).  This literal check costs a plain substring search
# and can only ever *add* infra classifications, never remove one.
INFRA_MARKER_RE = re.compile(
    _quoted("error_type") + r"\s*:\s*" + _quoted("Infrastructure")
)


def tuxrun_infra_error(returncode, output):
    """Authoritative infra signal: the final LAVA job case self-reports
    error_type 'Infrastructure' (e.g. serial connection closed mid-run).
    String heuristics above are only fallbacks for cases where LAVA does
    not emit this line."""
    cleaned = strip_ansi(output)
    return bool(
        JOB_CASE_INFRA_RE.search(cleaned) or INFRA_MARKER_RE.search(cleaned)
    )


# The callback keeps only the last 200 characters of error_msg (see lava_body),
# so an infra reason has to fit in that window with its most useful part last.
ERROR_MSG_BUDGET = 190
TUXRUN_ERROR_LINE_RE = re.compile(r"^\s*(tuxrun: error: .*)$", re.MULTILINE)
INVALID_CHOICE_RE = re.compile(r"invalid choice: '([^']+)'")
CHOICES_TAIL_RE = re.compile(r"\s*\(choose from .*\)\s*$")
# Windows, never whole-console copies: a failed job's log reaches tens of
# megabytes, and the old ``" ".join(cleaned[start:].split())`` turned 14 MB of
# trailing output into a list of millions of token strings to produce a
# 190-character answer (+205 MB peak RSS).
ERROR_MSG_WINDOW = JOB_CASE_GAP + 4096  # the case dict + its trailing fields
ERROR_MSG_TAIL = 4096  # unrecognised failure: the reason is the very last text
ERROR_MSG_FIELD_RE = re.compile(
    _quoted("error_msg") + r"\s*:\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
)
ERROR_MSG_PLAIN_FIELD_RE = re.compile(
    r"[\"']error_msg[\"']\s*:\s*"
    r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
)


def missing_test_hint(output):
    """Name the documented one-time patch when tuxrun rejects a test name
    because tuxlava does not provide it.

    tuxrun builds ``--tests`` argparse ``choices`` from tuxlava's registry, so
    a tuxlava without the riscv kselftest class fails as
    ``invalid choice: 'kselftest-riscv'``.  Reported without this hint, that
    reaches the node as an unexplained infrastructure error."""
    match = INVALID_CHOICE_RE.search(strip_ansi(output))
    if not match or not match.group(1).startswith("kselftest"):
        return ""
    return (f"tuxlava has no '{match.group(1)}' class: apply the one-time "
            f"config/tuxlava-kselftest-riscv.patch (docs/RUNBOOK.md)")


def _condense(text):
    """Collapse every whitespace run (spaces, newlines, CRLF) into one space."""
    return " ".join(text.split())


def _repr_unescape(text):
    """Undo the backslash escapes of a repr'd log line (``\\'x\\'`` -> ``'x'``).

    Used on a bounded window only, never on the whole console."""
    if "\\" not in text:
        return text
    out = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            out.append(text[index + 1])
            index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def _clip_head(message, budget):
    """Keep the HEAD of *message*.

    argparse's own error line names the problem in its first words (the
    trailing choices list is dropped separately), so an oversized argparse
    message must not spend its budget on the tail of a test-class list."""
    if len(message) <= budget:
        return message
    if budget <= 3:
        return message[:max(budget, 0)]
    return message[:budget - 3] + "..."


def _clip_reason(message, budget):
    """Keep BOTH ends of a reason that does not fit.

    A failure mode is the END of a reason ("...: Read timed out.") while its
    head names the artifact or command that failed, and the callback keeps
    only the last 200 characters of what is sent.  The old
    ``message[:budget]`` kept just the head: node 6aa387ecba3aeacda180ff12
    was reported as "HTTPSConnectionPool(host='files." with the cause cut
    off."""
    if len(message) <= budget:
        return message
    if budget < 16:
        return message[:budget]
    tail = max(8, (budget - 5) // 3)
    return f"{message[:budget - tail - 5]} ... {message[-tail:]}"


def _clip_tail(message, budget):
    """Keep the TAIL: for an unrecognised failure the reason is the last thing
    the console printed (a traceback, a shutdown line, tar's short read)."""
    return message[-budget:] if budget > 0 else ""


def _compose(message, hint, clip):
    """Attach the actionable *hint* LAST and intact, inside ERROR_MSG_BUDGET.

    The hint is the only actionable part (the one-time tuxlava patch), and the
    callback keeps the LAST 200 characters of the body, so the hint is never
    truncated: the message yields budget to it instead.  Capping the hint at
    ``ERROR_MSG_BUDGET // 2`` dropped "(docs/RUNBOOK.md)" and cut the patch
    path for a long test-class name."""
    if not hint:
        return clip(message, ERROR_MSG_BUDGET)
    budget = ERROR_MSG_BUDGET - len(hint) - len(" | ")
    if budget <= 0:
        # A pathological class name: only the hint still fits, and its own
        # tail (the patch path) is the actionable part.
        return hint[-ERROR_MSG_BUDGET:]
    return f"{clip(message, budget)} | {hint}"


def _verdict_reason(cleaned, verdict):
    """The reason carried by the job case dict that *verdict* matched.

    The dict's own ``error_msg`` is the authoritative reason.  A 190-character
    prefix of the whole dict spends the budget on scaffolding
    ("'case': 'job', 'result': 'fail', ...") instead of on the failure, which
    is how a download timeout was reported as a URL fragment.

    The window reaches *before* the verdict as well as after it: LAVA's case
    dict does not fix the field order, and searching only forward could pick up
    the ``error_msg`` of the NEXT case instead of this one.  When several
    candidates are in range, the one closest to the verdict wins."""
    start = max(0, verdict.start() - ERROR_MSG_WINDOW)
    end = min(len(cleaned), verdict.end() + ERROR_MSG_WINDOW)
    window = cleaned[start:end]
    anchor = verdict.start() - start
    field = _closest(ERROR_MSG_FIELD_RE, window, anchor)
    if field is None:
        # Doubly-escaped repr (\\'error_msg\\': \\"...\\"): normalise the
        # bounded window and retry in plain form.
        window = _repr_unescape(window)
        field = _closest(ERROR_MSG_PLAIN_FIELD_RE, window, anchor)
    if field is None:
        return _condense(cleaned[verdict.start():end])
    value = field.group(1)
    if len(value) >= 2:
        value = _repr_unescape(value[1:-1])
    return _condense(value)


def _closest(pattern, window, anchor):
    """The match of *pattern* whose start is nearest *anchor*, or None."""
    best = None
    for match in pattern.finditer(window):
        if best is None or abs(match.start() - anchor) < abs(best.start() - anchor):
            best = match
    return best


def tuxrun_error_message(output, label=""):
    """The infra reason to report, built for the callback's 200-character window.

    tuxrun's argparse errors are a single very long line (the choices list runs
    to thousands of characters) and LAVA's dispatcher verdict is a case dict;
    in neither case is the useful text a slice of the console's tail.  Reporting
    ``output[-2000:]`` and letting the callback keep the last 200 characters of
    that produced "md-analyze', ..., 'zlib')\\n" for a run whose real problem was
    a missing test class.

    Three sources, in order of authority:
      * the first ``tuxrun: error:`` line, with the choices list dropped;
      * the LAST job-case Infrastructure verdict (a log can carry several
        attempts - only the final verdict is authoritative), reporting that
        verdict's own ``error_msg`` field rather than a prefix of the dict;
      * a bounded tail of the console, for anything unrecognised.

    ``label`` is accepted for the callers' sake; the reason does not depend on
    the test type."""
    cleaned = strip_ansi(output)
    hint = missing_test_hint(cleaned)
    match = TUXRUN_ERROR_LINE_RE.search(cleaned)
    if match:
        # With a hint present the marker is redundant (the hint already names
        # the rejected class), and its 21 characters are what the intact hint
        # needs to fit inside the budget.
        replacement = "" if hint else " (invalid test name)"
        message = _condense(CHOICES_TAIL_RE.sub(replacement, match.group(1)))
        return _compose(message, hint, _clip_head)
    verdict = None
    for verdict in JOB_CASE_INFRA_RE.finditer(cleaned):
        pass  # the LAST verdict wins: earlier ones are stale attempts
    if verdict is not None:
        return _compose(_verdict_reason(cleaned, verdict), hint, _clip_reason)
    # Nothing recognisable: the reason (a traceback, a shutdown line) sits at
    # the END of the output, so keep a bounded tail - the previous behaviour,
    # now without splitting the whole console.
    return _compose(
        _condense(cleaned[-ERROR_MSG_TAIL:]), hint, _clip_tail
    )


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
        started = time.time()
        cmd, label = build_command(job, args, workspace)
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

    stamp(
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
        stamp(f"{node_id}: result posted to the callback")
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
        "TST_CASENAME allow-list (default: the 8 tests "
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
