#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Guest rootfs baking: nfsroot tar.xz -> bootable ext4 image, plus its cache.

Moved VERBATIM out of scripts/riscv_pull_worker.py, which owned it until now:
``bake_rootfs_image()`` turns the nfsroot tar.xz artifact into an ext4 image
tuxrun can boot (``mkfs.ext4 -d``: no loop mount, no root) and bakes
modules.tar.xz into /lib/modules with a modules-load.d conf so ``modprobe kvm``
works at boot; ``baked_rootfs_image()`` puts a cache in front of it, keyed on
the exact bake inputs.  Both the worker and scripts/fetch-and-run-latest.py need
exactly this code - the fetch script carries an inlined copy of it - so this
module is also the deduplication of that copy.

HOW THE ROOT IS DERIVED.  ``bake_cache_dir()`` defaults to
``<repo>/work/env/baked`` and takes ``<repo>`` from THIS file's location - never
from the CWD, never from a hardcoded absolute path - exactly as ledger.py takes
``work/results`` from its own location and as the worker did with its own
``__file__``.  That is the ONE expression that had to change when the code
moved: the worker sits at ``scripts/riscv_pull_worker.py`` and needed two
``dirname()``s to reach the repository root, while this file sits one directory
deeper at ``scripts/kcilib/bake.py`` and needs three.  Both spellings resolve to
the same directory::

    worker: dirname(dirname(realpath(scripts/riscv_pull_worker.py)))
    here:   dirname(dirname(dirname(realpath(scripts/kcilib/bake.py))))

``realpath`` rather than abspath is kept on purpose (see bake_cache_dir): a
symlinked launcher must not place the multi-GB cache next to the symlink,
outside the gitignored work/.

TWO SEAMS the moved code reaches for by name, both module attributes so a caller
can re-bind them exactly as the worker's guard tests re-bind
``artifacts.requests``:

  * ``stamp()`` - the ``[HH:MM:SS] `` progress printer, byte-identical to the
    worker's own stamp(); every line a bake prints goes through it;
  * ``download()`` - ``kcilib.artifacts.download``, the transfer the worker's
    own ``download()`` wrapper delegates to (that wrapper only re-binds
    ``artifacts.requests`` first, so it is the same transfer and the same
    printed lines).

Importing this module has no side effects: nothing here reads the environment,
touches the filesystem or prints until a function is called.
"""

import hashlib
import json
import os
import re
import subprocess
import tarfile
import time
from datetime import datetime, timezone

from kcilib.artifacts import MAX_DOWNLOAD_SIZE, download


def stamp(message):
    """Progress line with a clock.

    Added after a `worker --once` run took 17m42s where the internal notes
    promised ~7 minutes, and ~14 of those minutes sat between two jobs with no
    way to tell where they went: every line looked alike and the only clock was
    the log file's.  The two phases that can take minutes - preparing the guest
    (download + baking a 4GB ext4 per job) and tuxrun itself - now report their
    own duration, so the next report can attribute the time instead of guessing.

    Moved here with the bake machinery - same f-string, same flush=True - so
    every line a bake prints stays byte-identical to the worker's.  The worker
    keeps its own stamp() for its non-bake lines, and a caller may re-bind
    ``kcilib.bake.stamp`` just as it re-binds this module's ``download``.
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


DISK_SIZE = "4G"  # ext4 image size; unrelated to QEMU memory
# Baked-image cache limits (see baked_rootfs_image): each entry is a full
# DISK_SIZE image, so the cache is bounded by entry count.  Two or three
# entries cover the real input sets (kselftest-riscv bakes no modules,
# kselftest-kvm bakes modules.tar.xz, a different rootfs is a third).
BAKE_CACHE_MAX_ENTRIES = 3
BAKE_CACHE_TMP_AGE_S = 3600  # a killed bake's .tmp is ignored, then aged out


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
    # THREE dirname()s, where the worker (scripts/riscv_pull_worker.py) needed
    # two: this file lives one level deeper, in scripts/kcilib/.  Both spellings
    # resolve to the repository root, so both reach the same work/env/baked.
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.realpath(__file__))))
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
