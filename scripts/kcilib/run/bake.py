#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Guest rootfs baking: nfsroot tar.xz -> bootable ext4 image, plus its cache.

bake_rootfs_image() turns the nfsroot tar.xz artifact into an ext4 image tuxrun
can boot (mkfs.ext4 -d: no loop mount, no root) and bakes modules.tar.xz into
/lib/modules with a modules-load.d conf so modprobe kvm works at boot;
baked_rootfs_image() puts a cache in front of it, keyed on the exact bake inputs.

Two seams are reached for by name and are re-bindable module attributes, as the
guard tests expect: ``stamp()`` (the [HH:MM:SS] progress printer) and
``download()`` (kcilib.run.artifacts.download).  Importing this module has no
side effects.  Rationale: docs/code-notes/W2c-kcilib.md.
"""

import hashlib
import json
import os
import re
import subprocess
import tarfile
import time
from datetime import datetime, timezone

from kcilib import repo_root
from kcilib.run.artifacts import MAX_DOWNLOAD_SIZE, download


def stamp(message):
    """Progress line with a clock.

    A run that took 17m42s against a promised ~7 left 14 minutes between two
    jobs with nothing to attribute them to, so each phase reports its own
    duration.  A caller may re-bind ``kcilib.run.bake.stamp`` as it re-binds
    ``download``.
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


DISK_SIZE = "4G"  # ext4 image size; unrelated to QEMU memory
# Each entry is a full DISK_SIZE image, so the cache is bounded by entry count;
# three cover the real input sets (no modules, modules, another rootfs).
BAKE_CACHE_MAX_ENTRIES = 3
BAKE_CACHE_TMP_AGE_S = 3600  # a killed bake's .tmp is ignored, then aged out


def _safe_member(member):
    """Reject archive members that could escape the extraction directory:
    absolute paths and ``..`` components.  Symlinks with absolute targets are
    ALLOWED - rootfs tarballs legitimately ship them (./init -> /usr/lib/
    systemd/systemd) and extraction only stores the link text.  Hardlink
    targets stay strict: tarfile resolves them with os.link() on the host."""
    name = member.name.replace("\\", "/")
    if name in ("", ".") or name.startswith("/"):
        return False
    if any(part == ".." for part in name.split("/")):
        return False
    target = getattr(member, "linkname", "") or ""
    # Hardlinks only: they are resolved on the host with os.link().
    if member.issym() or not target:
        return True
    return not (
        target.startswith("/")
        or any(part == ".." for part in target.replace("\\", "/").split("/"))
    )


def _extract(archive, dest_dir):
    """Extract a tarball under *dest_dir*, then unwrap a single top dir.

    Device/FIFO members are skipped: mknod fails for an unprivileged lab user,
    and mkfs.ext4 -d populates /dev from the tree anyway.  Members that could
    escape *dest_dir* are skipped too."""
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

    boot_modules drops a modules-load.d conf into the tree so the guest
    modprobes them at boot.  modules_url (kselftest-kvm) also unpacks
    modules.tar.xz under /lib/modules: the --modules LAVA overlay arrives only
    after boot, so without baking them in every kvm test skips with "Cannot
    open '/dev/kvm'".

    image_path is where the ext4 file goes (default <workspace>/rootfs.ext4);
    the cache passes its own so the publish is a rename.  The tarball and the
    extracted tree always live under *workspace*.
    """
    tar_path = os.path.join(workspace, "rootfs.tar")
    download(rootfs_url, tar_path, max_size=max_size)
    root_dir = _extract(tar_path, os.path.join(workspace, "rootfs"))
    if modules_url:
        mod_tar = os.path.join(workspace, "modules.tar")
        download(modules_url, mod_tar, max_size=max_size)
        # It ships lib/modules/<version>/, i.e. exactly where uname -r looks.
        _extract(mod_tar, root_dir)
    if boot_modules:
        conf_dir = os.path.join(root_dir, "etc", "modules-load.d")
        # Refuse to write through a symlink (tar-slip): our own writes must
        # stay inside the extracted tree, whatever the tarball links to.
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

    Default ``work/env/baked/``, a subdirectory of the gitignored work/ that
    already holds the multi-GB guest testbed - a separate directory, because
    ``work/env/rootfs-kvm.ext4`` belongs to ./run.sh provision and one filename
    cannot hold the several input sets a worker sees.

    Override with KCI_BAKE_CACHE_DIR; disable with KCI_BAKE_CACHE=0 (every job
    then bakes into its own workspace, as before).  Returns "" when disabled."""
    if os.environ.get("KCI_BAKE_CACHE", "").strip().lower() in ("0", "off",
                                                               "no", "false"):
        return ""
    override = os.environ.get("KCI_BAKE_CACHE_DIR", "").strip()
    if override:
        return override
    # repo_root() walks up to run.sh: a fixed dirname() count put the cache in
    # scripts/work/env/baked.  realpath, not abspath, so a symlinked launcher
    # does not place a multi-GB cache next to the symlink.
    return os.path.join(repo_root(), "work", "env", "baked")


def cache_dir_writable(cachedir):
    """True when a file can actually be created in *cachedir*.

    os.makedirs(exist_ok=True) succeeds on an existing but unwritable directory
    and os.access is unreliable for root and ACLs, so probe by writing -
    otherwise mkfs.ext4 fails the job on a cache that is only an optimisation.
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

    Everything mkfs.ext4's result depends on - both tarballs, the modules-load.d
    list and the image size; omitting any would hand a job an image built from
    other inputs."""
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

    A hit requires all of: a regular file, not a symlink, resolving inside the
    cache directory (a symlink could hand tuxrun an unrelated disk), a sidecar
    recording byte-identical *inputs*, and an image of the expected size.  The
    sidecar is published LAST, so an interrupted bake is never trusted."""
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

    Written only after the image is in place, so a crash in between leaves an
    image nobody trusts rather than a sidecar promising a missing file."""
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

    Each entry is a ~4GB image, so an unbounded cache fills a disk one input
    change at a time.  Only this module's own files are touched: ``<key>.ext4``
    plus ``<key>.json`` and ``<key>.<suffix>.tmp<pid>``.

    Enumerated from BOTH kinds, because an image whose sidecar write failed is
    unusable for reuse: it counts against the cap, and is dropped once it is
    older than the publish window (a younger one may belong to a live publish)."""
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
    # keep_key counts towards the cap, it is only exempt from *eviction* -
    # otherwise a long bake racing another publisher leaves max_entries + 1.
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
        # Only this module's own leftovers.  A fresh one may belong to a bake
        # still running - the age test protects it, not the key.
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
    publishing is one rename on one filesystem: a reader sees the previous entry
    or the complete new image, never a half-written one.  The size is checked
    before the rename - anything but DISK_SIZE is not the image."""
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

    Without it a batch re-downloaded the same ~144MB nfsroot tarball and
    re-baked the same 4GB image per job; the bake is a function of the inputs in
    bake_cache_inputs(), so a second job with the same ones gets it from disk.

    The key is the *URL*, not the bytes: content replaced behind an unchanged
    URL is not noticed.  Production URLs embed the build id or a rootfs version
    directory, so they are immutable in practice - if you repoint one at
    different content, run with ``KCI_BAKE_CACHE=0`` or ``rm -rf work/env/baked``."""
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
            # An unusable cache must not fail the job: bake as before, without it.
            stamp(f"{label}: bake cache unusable ({error}); baking without it")
            cachedir = ""
    if cachedir and not cache_dir_writable(cachedir):
        stamp(f"{label}: bake cache {cachedir} exists but is not writable; "
              "baking without it")
        cachedir = ""
    if cachedir:
        # In the cache directory, so the publish is a same-filesystem rename
        # even when the workspace sits on another mount (the default is /tmp).
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
        # Deliberately broad: any cache-specific failure (disk full, a directory
        # turned read-only, a failed rename) falls back to the pre-cache
        # behaviour - and the retry cannot loop, it writes into the workspace.
        if not target:
            raise
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
        # Caching is an optimisation: report a failed publish and hand tuxrun
        # the image that WAS baked, instead of failing the job.  An image
        # without its sidecar is never reused and prune ages it out.
        stamp(f"{label}: could not publish the baked image to the cache "
              f"({error}); using it from the workspace instead")
        return image
    stamp(f"{label}: guest rootfs baked in {baked_s:.1f}s -> {published} "
          f"(key {key}); the next job with the same inputs reuses it")
    for name in prune_bake_cache(cachedir, key):
        stamp(f"{label}: bake cache pruned {name}")
    return published
