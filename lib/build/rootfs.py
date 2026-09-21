# SPDX-License-Identifier: LGPL-2.1-or-later
"""The guest disk: the kernel artifact made bootable, and the rootfs baked into ext4.

`bake_rootfs()` is module-level on purpose - the worker runs definitions the API
sent, which have no local `Build`, and mkfs still has to happen here, on the
host, never in the container.  `kvm_tests()` reads the same tarball's `kvm/` dir
for the tests a kernel actually built.

Nothing here is a path of its own: the image name comes from `layout.baked()`,
and the URL that names it is a copy's (`fetch.download`), never a second
downloader.
"""

import gzip
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile

from .. import errors, layout
from ..tests import KVM_SKIP_TESTS
from .fetch import _remove, download
from .model import DISK_SIZE, TAR_SUFFIXES


def _kernel(url, dest):
    """Leave the bootable image at `dest`: the artifact copied, or gunzipped when it is gzip.

    A gzip's trailer ISIZE is the proof that an earlier decompression finished: a
    half-gunzipped Image exists and is not empty, so existence proves nothing.
    """
    raw = f"{dest}.gz"  # Image -> Image.gz, the name the artifact arrives under
    download(url, raw)
    size = _gzip_size(raw)
    if os.path.isfile(dest) and os.path.getsize(dest) == (size or os.path.getsize(raw)):
        return dest
    part = f"{dest}.part"
    if size is None:
        shutil.copyfile(raw, part)
    else:
        try:
            with gzip.open(raw, "rb") as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst)
        except OSError as error:
            _remove(part)
            raise errors.ArtifactError(f"{raw} is not a whole gzip: {error}") from error
    os.replace(part, dest)
    return dest


def _gzip_size(path):
    """The uncompressed size in a gzip file's trailing ISIZE, or None when it is not gzip."""
    try:
        with open(path, "rb") as handle:
            if handle.read(2) != b"\x1f\x8b":
                return None
            handle.seek(-4, os.SEEK_END)
            return int.from_bytes(handle.read(4), "little") or None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# The bake
# ---------------------------------------------------------------------------

def _bake_key(rootfs_url, modules_url=""):
    """A short stable name for one bake's inputs: the rootfs, and the modules unpacked into it."""
    return hashlib.sha256(f"{rootfs_url}|{modules_url}".encode()).hexdigest()[:16]


def _unpack(archive, dest):
    """Extract a tarball under `dest`, skipping what the guard refuses; unwrap one top dir."""
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not _refusal(member.name, _kind(member), member.linkname or ""):
                tar.extract(member, dest)
    return _unwrap(dest)


def _unwrap(dest):
    """`dest`, or its only child when that child is a directory (a rootfs tarball carries one)."""
    entries = os.listdir(dest)
    if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])):
        return os.path.join(dest, entries[0])
    return dest


def _kind(member):
    """A tar member's kind as a word: file, dir, symlink, hardlink, dev or fifo."""
    if member.isdev():
        return "dev"
    if member.isfifo():
        return "fifo"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    return "dir" if member.isdir() else "file"


def _refusal(name, kind="file", linkname=""):
    """Why a member may not be extracted, or '' - the member's own spelling, no I/O.

    A symlink's target is only text (rootfs tarballs ship absolute ones), while a
    hardlink's is resolved on the host, so that one is checked too.
    """
    name = name.replace("\\", "/")
    if name in ("", ".") or name.startswith("/"):
        return f"absolute or empty name: {name!r}"
    if ".." in name.split("/"):
        return f"'..' in the path: {name!r}"
    if kind in ("dev", "fifo"):
        return f"{kind} member: {name}"
    target = (linkname or "").replace("\\", "/")
    if kind == "hardlink" and target and (target.startswith("/") or ".." in target.split("/")):
        return f"hardlink target escapes: {name} -> {target}"
    return ""


def _modules_load(tree, names):
    """Write `etc/modules-load.d/kernelci.conf` in `tree`, refusing to write through a symlink."""
    conf_dir = tree
    for part in ("etc", "modules-load.d"):
        conf_dir = os.path.join(conf_dir, part)
        if os.path.islink(conf_dir):
            raise errors.ArtifactError(f"refusing to write through a symlink: {conf_dir}")
    os.makedirs(conf_dir, exist_ok=True)
    conf = os.path.join(conf_dir, "kernelci.conf")
    if os.path.islink(conf):
        os.unlink(conf)
    with open(conf, "w") as handle:
        handle.write("\n".join(names) + "\n")


def kvm_tests(tarball):
    """The KVM selftest binaries a kselftest tarball ships, minus the ones TCG cannot pass.

    The executable bit is the filter, not a fixed list: the tarball's `kvm/` dir
    holds the test binaries (mode +x) beside `config` and `settings` (mode -x),
    and a test the kernel never built is simply absent - so an old kernel cannot
    make us ask tuxrun for a test that does not exist.
    """
    names = set()
    with tarfile.open(tarball) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not (member.mode & 0o111):
                continue
            parts = member.name.replace("\\", "/").split("/")
            if len(parts) >= 2 and parts[-2] == "kvm":
                names.add(parts[-1])
    return sorted(names - set(KVM_SKIP_TESTS))


def bake_rootfs(url, with_modules=False, modules_url=""):
    """A rootfs URL as a bootable ext4 path: baked once, reused while the file is there.

    Module-level because the worker runs definitions the API sent, which have no
    local `Build` - but mkfs still has to happen here, on the host, never in the
    container.  A URL that is already a disk (or a local path) is returned as is.
    """
    if not url or not url.endswith(TAR_SUFFIXES):
        return url
    image = layout.baked(f"{_bake_key(url, modules_url if with_modules else '')}.ext4")
    if os.path.isfile(image):
        return image
    parent = os.path.dirname(image)
    if parent:
        os.makedirs(parent, exist_ok=True)
    work = tempfile.mkdtemp(prefix="kci-bake-")
    part = ""
    try:
        root = _unpack(download(url, os.path.join(work, "rootfs.tar.xz")),
                       os.path.join(work, "tree"))
        if with_modules:
            if not modules_url:
                raise errors.ArtifactError("this job wants modules on the disk but the "
                                           "definition names no modules artifact")
            _unpack(download(modules_url, os.path.join(work, "modules.tar.xz")), root)
            _modules_load(root, ("kvm",))
        # mkfs writes in place: a killed bake must not leave a file under the name
        # a later run reuses unchanged.
        handle, part = tempfile.mkstemp(dir=parent or ".", suffix=".part")
        os.close(handle)
        print(f"baking {image} ({DISK_SIZE}, mkfs.ext4 -d)", flush=True)
        subprocess.run(["mkfs.ext4", "-F", "-d", root, part, DISK_SIZE],
                       check=True, stdout=subprocess.DEVNULL)
        os.replace(part, image)
        part = ""
        return image
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if part:
            _remove(part)
