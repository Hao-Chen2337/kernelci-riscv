# SPDX-License-Identifier: LGPL-2.1-or-later
"""The local half of a build: the bytes we fetch, the guest disk we bake, the table.

`Build` is one build - a `Kbuild` plus `var/downloads/<build-id>/`; `Builds` is
the table of them, one JSON file at `layout.index()`.  The downloader here is the
only one in the tree.

接口形状（C++，只有声明）：include/kci/local.hpp §7 Build / Builds。
"""

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields, replace

import requests

from . import errors, layout, tests
from .kbuild import Kbuild, build_id_of
from .tests import DEFAULT_TESTS, KVM_SKIP_TESTS, ROOTFS_URL, TESTS, needs

# Canonical name -> the API's own spellings for it, and the file it becomes
# here.  `kselftest` is our name for it (the API says `kselftest_tar_xz`), and
# the kernel artifact arrives gzipped (see `_kernel`).
ARTIFACTS = {
    "kernel": (("kernel",), "Image"),
    "modules": (("modules",), "modules.tar.xz"),
    "kselftest": (("kselftest", "kselftest_tar_xz"), "kselftest.tar.xz"),
    "config": (("_config",), ".config"),
}

# The artifacts `make()` fetches when the caller does not name any.
WANT = ("kernel", "modules", "kselftest")

# The build this deployment serves, as data (`publish_local()` writes it, and
# retention and the local stack's seeding read it): `var/state/served.json`.
SERVED_NAME = "served.json"

# Where a local copy records where it came from: one file inside the copy itself
# (`var/downloads/<build-id>/provenance.json`), so deleting the copy deletes the
# record with it and no record can ever outlive the bytes it describes.
# How many pulls that file remembers.  It describes the copy as it is now; the
# full history of pull *acts* is the runs tree (`var/runs/<id>/`).
PROVENANCE_ACTS = 20

# A guest disk for tuxrun: the nfsroot tarball unpacked into an ext4 image.
# `mkfs.ext4 -d` populates it from a directory - no loop mount and no root.
DISK_SIZE = "4G"
TAR_SUFFIXES = (".tar.xz", ".tar.gz", ".tgz", ".tar")

# 4 GiB per transfer: a rootfs tarball fits easily, anything bigger is not ours.
MAX_SIZE = 4 << 30
# Per-read gap, not a total budget: artifact hosts go quiet mid-transfer.
TIMEOUT = 60
CHUNK = 1 << 20
ATTEMPTS = 3


@dataclass
class Build:
    """One build's local copy: `var/downloads/<build-id>/`."""

    kbuild: Kbuild | None = None
    path: str = ""
    # Artifact name -> local file, filled by make().
    files: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.kbuild is not None and not self.path:
            self.path = layout.downloads(self.kbuild.build_id)

    # --- identity ----------------------------------------------------------

    @property
    def build_id(self):
        """The identity: the kbuild's build_id, or the name of `path` when there is none."""
        return ((self.kbuild.build_id if self.kbuild is not None else "")
                or os.path.basename(self.path))

    def describe(self):
        """The label a run and its record are named with: the kbuild's, else the id."""
        label = self.kbuild.describe() if self.kbuild is not None else ""
        return label or self.build_id

    # --- the bytes ---------------------------------------------------------

    def make(self, want: "tuple[str, ...] | list[str]" = WANT) -> "Build":
        """Download what a run needs into `path`, proving each file, and fill `files`.

        Idempotent - a file already there at the size this copy's own record
        proved it at, or at the size the host reports, is not fetched again - and
        loud: an artifact this build does not have, or bytes that cannot be
        proven complete, is an ArtifactError.

        Each call leaves one act in `var/downloads/<build-id>/provenance.json`:
        which URL every artifact came from, how many bytes were proven, and when.
        That record is what makes "this local copy came from that remote build" a
        fact instead of an assumption from two equal build ids - so a record that
        cannot be written fails the pull, and one that fails halfway is still
        recorded (with the reason) before the error goes on.

        **The record is also a witness the host cannot take away.**  `_complete()`
        alone proves a local file against the *host's* current size, so an origin
        that is down un-proves bytes that are on this disk: the operator's own
        `6aa3689720239ade90209d50` and `6aadee70d96a8203de6e8452` have a complete
        27 MB Image, a pull record naming the URL it came from, and a `kernel`
        URL on `172.17.0.1:8999` - the local stack's artifact server, up only
        while he runs it.  Every run therefore re-asked a dead host and died
        after three attempts, on bytes it already had, and the run line reported
        "the artifact never arrived" for a copy that had arrived two days before.
        `_recorded()` is consulted first: the same URL, the size that transfer
        proved, and the file is that size - which is exactly what a fresh HEAD
        would have said, asked of the copy instead of of the network.  tuxrun
        reads these files as `file://` anyway (`runner._local`), so the origin is
        not needed to run what it once delivered; a URL the card no longer names,
        or a file whose size the record does not match, still goes to the host.
        """
        entries: list[dict] = []
        try:
            for name in want:
                url = self._url(name)
                if not url:
                    raise errors.ArtifactError(f"build {self.build_id} has no {name} artifact")
                dest = self._local(name)
                before = os.path.getsize(dest) if os.path.isfile(dest) else 0
                self.files[name] = self._already_proven(name, url, dest) or self._fetch(name, url)
                entries.append({"artifact": name, "url": url,
                                "bytes": os.path.getsize(dest),
                                "transferred": os.path.getsize(dest) != before})
        except errors.KciError as problem:
            self._remember(entries, str(problem))
            raise
        self._remember(entries, "")
        return self

    def present(self) -> dict[str, str]:
        """The artifacts whose local file is on disk, as `{name: path}` (the shape `files` has)."""
        return {name: self._local(name) for name in self._present()}

    def provenance(self) -> dict:
        """The pull acts recorded for this local copy, newest first; `{}` when there are none.

        A copy that was never pulled through `make()` has no record - the worker
        preparing one artifact for a job, an older version of this tree, or a
        hand-copied directory all look the same here, and that is the honest
        answer: the bytes are ours, but where they came from is not recorded.
        """
        try:
            with open(layout.provenance(self.build_id), encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, ValueError):
            return {}
        return stored if isinstance(stored, dict) else {}

    def _recorded(self, name, url):
        """The bytes this copy's own record proved for `name` from `url`, or 0.

        Only acts that succeeded are read (`error` empty): a failed act recorded
        the reason it failed, not a size worth believing.  The URL has to match
        the one being asked for now, because a card whose `kernel` URL the
        operator or the API changed is a different artifact as far as this record
        can tell - and then the host is asked, as before.
        """
        for act in self.provenance().get("acts", []):
            if not isinstance(act, dict) or act.get("error"):
                continue
            for entry in act.get("entries") or ():
                if not isinstance(entry, dict):
                    continue
                if entry.get("artifact") == name and entry.get("url") == url:
                    return entry.get("bytes") or 0
        return 0

    def _already_proven(self, name, url, dest):
        """`dest` when this copy's record already proved this artifact, else ''.

        `make()` asks this before `_fetch()`: see its docstring for the two builds
        whose complete local copy used to be un-provable because the host that
        served it was switched off.
        """
        recorded = self._recorded(name, url)
        if recorded and os.path.isfile(dest) and os.path.getsize(dest) == recorded:
            return dest
        return ""

    def missing(self, test):
        """What is still missing to run `test` here, with a reason each; empty = it can run."""
        try:
            wanted = needs(test)
        except errors.ConfigError as error:
            return [str(error)]
        return [reason for reason in (self._lacking(name) for name in wanted) if reason]

    def rootfs(self, url="", with_modules=False):
        """The guest disk tuxrun boots: `layout.baked(<key>.ext4)`, baked once and reused."""
        return bake_rootfs(url or ROOTFS_URL, with_modules,
                           modules_url=self._url("modules"))

    def merge(self, other):
        """Take the artifact URLs this build lacks from `other` (a Build or a Kbuild).

        A URL the card already holds is the card's own and stays (first wins):
        rewording 53 records to say what they already said is how two writers
        lose each other's work.  The one exception is a URL that names no build.

        **A URL that does not carry this build's id is not this build's artifact
        URL.**  It is where *this deployment* happened to hand the kernel over -
        `publish_local`'s `file://…/var/serve/Image`, or the local stack's
        artifact server, `http://172.17.0.1:8999/Image`, both of which answer
        only while the operator runs them.  Because this method only ever filled
        *gaps*, `table.py index` could not heal such a card from the API that
        knows the build's real URL: two of the 53 cards here sat on a dead host
        for two days, and every `table.py run` of them died on its first build
        while the API had been serving the same artifact from
        `files.kernelci.org` all along.  So an incoming URL that DOES name this
        build replaces a held one that names nothing; every other URL is still
        the card's, and an incoming URL that names a *different* build is
        ignored rather than believed.
        """
        if other.build_id != self.build_id:
            raise errors.ConfigError(f"cannot merge {other.build_id} into {self.build_id}")
        if self.kbuild is None:
            self.kbuild = other.kbuild if isinstance(other, Build) else other
            return
        artifacts = dict(self.kbuild.artifacts)
        for key, url in other.artifacts.items():
            if not url:
                continue
            held = artifacts.get(key, "")
            if not held or (_names_this_build(url, self.build_id)
                            and not _names_this_build(held, self.build_id)):
                artifacts[key] = url
        self.kbuild = replace(self.kbuild, artifacts=artifacts)

    def remove(self):
        """Delete this build's local copy (what `python3 prune.py` does)."""
        shutil.rmtree(self.path, ignore_errors=True)
        self.files = {}

    def print(self, stream=None):
        """One line: the build's id, label, directory, and the artifacts on disk."""
        print(f"{self.build_id}  {self.describe()}  {self.path}  "
              f"{' '.join(self._present()) or '-'}", file=stream)

    # --- one artifact, by our name for it ----------------------------------

    def _url(self, name):
        """The URL of one artifact under our name for it, or '' - the API's keys are its own."""
        artifacts = (self.kbuild.artifacts if self.kbuild is not None else None) or {}
        for key in ARTIFACTS[name][0]:
            if artifacts.get(key):
                return artifacts[key]
        return ""

    def _local(self, name):
        """Where one artifact of this build lives: `<path>/<file>`."""
        return os.path.join(self.path, ARTIFACTS[name][1])

    def _present(self):
        """The artifacts of this build whose local file is on disk."""
        return [name for name in ARTIFACTS if os.path.isfile(self._local(name))]

    def _lacking(self, name):
        """Why this build cannot give `name`, or '': no URL, or no bytes here yet."""
        if not self._url(name):
            return f"{name}: the build has no {name} artifact"
        path = self._local(name)
        if not os.path.isfile(path) or not os.path.getsize(path):
            return f"{name}: not downloaded yet ({path})"
        return ""

    def _fetch(self, name, url):
        """One artifact made local, and where it landed."""
        dest = self._local(name)
        if name == "kernel":
            return _kernel(url, dest)
        return download(url, dest)

    def _remember(self, entries, error):
        """Append one pull act to this copy's record: what landed, from where, when.

        Refuses to write an empty act (a call that resolved nothing and failed on
        its first artifact is not a pull), and a record this cannot write is a
        failed pull: the evidence matters as much as the bytes.
        """
        if not entries:
            return
        acts = [{"at": _stamp(), "error": error, "entries": entries}]
        acts += [one for one in self.provenance().get("acts", []) if isinstance(one, dict)]
        record = {"build_id": self.build_id,
                  "node_id": self.kbuild.node_id if self.kbuild is not None else "",
                  "acts": acts[:PROVENANCE_ACTS]}
        try:
            os.makedirs(self.path, exist_ok=True)
            path = layout.provenance(self.build_id)
            with open(f"{path}.tmp", "w", encoding="utf-8") as handle:
                json.dump(record, handle, indent=1, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(f"{path}.tmp", path)
        except OSError as problem:
            raise errors.ArtifactError(
                f"cannot record the pull of {self.build_id} in {self.path}: {problem}") from problem

class _Permanent(errors.ArtifactError):
    """A failure retrying cannot fix: a 4xx, a redirect, an artifact that is too big."""


def _names_this_build(url, build_id):
    """Does `url` carry `build_id`?  The question `Build.merge()` turns on.

    `build_id_of()` reads the id out of an artifact URL and searches the keys a
    kbuild's artifacts use, so one URL is asked as `{"kernel": url}` on purpose:
    every artifact of one build is filed under the same `<name>-<build id>`
    directory, and a URL that names none of them (`/Image`, `file://…/Image`)
    cannot say which build it is.
    """
    return bool(build_id) and build_id_of({"kernel": url}) == build_id


def download(url, dest, expected=None, max_size=MAX_SIZE):
    """Fetch `url` into `dest`, resuming, and publish it only when it is whole.

    A short transfer, a refused range or a redirect is an ArtifactError, never a
    `dest` that half exists; a local path or `file://` URL is copied instead.
    """
    source = _local_source(url)
    if source:
        return _copy(source, dest, expected, max_size)
    if _complete(dest, url, expected, max_size):
        return dest
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    part = f"{dest}.part"
    last = None
    for attempt in range(ATTEMPTS):
        try:
            offset = os.path.getsize(part) if os.path.isfile(part) else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            if offset:
                print(f"  resuming {os.path.basename(dest)} at {offset} bytes", flush=True)
            with requests.get(url, stream=True, headers=headers, timeout=TIMEOUT,
                              allow_redirects=False) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    raise _Permanent(f"refusing a redirect for {url}")
                if offset and response.status_code == 416:
                    # The host refuses `bytes=<offset>-`: a total equal to the
                    # offset means the file was whole all along.
                    if _content_range_total(response) == offset:
                        os.replace(part, dest)
                        print(f"  {dest} ({offset} bytes, the host confirms it)", flush=True)
                        return dest
                    _remove(part)
                    offset = 0
                    continue
                if offset and response.status_code == 200:
                    # The Range was ignored: start over rather than keep bytes the
                    # host knows nothing about.
                    offset = 0
                elif offset and response.status_code != 206:
                    raise _status_error(response.status_code, f"resuming {url}")
                if response.status_code not in (200, 206):
                    raise _status_error(response.status_code, url)
                proof = _remote_total(response, offset) or expected
                if proof is not None and proof > max_size:
                    raise _Permanent(f"{url} is {proof} bytes; refusing it")
                size = _read(response, part, offset, max_size)
            if proof is not None and size != proof:
                raise errors.ArtifactError(f"{url} is truncated: {size} of {proof} bytes")
            os.replace(part, dest)
            print(f"  {dest} ({size} bytes)", flush=True)
            return dest
        except _Permanent:
            raise
        except errors.ArtifactError as error:
            # Truncation and 5xx are worth another attempt; a 404 is not.
            last = error
        except (requests.RequestException, OSError) as error:
            # Every transport failure leaves here as one of ours: a caller must
            # not have to know what a requests exception is, and a raw one would
            # reach the entry point as a traceback with exit 1 - the one exit
            # code that means "a test failed".
            last = error
            if attempt < ATTEMPTS - 1:
                print(f"  attempt {attempt + 1}/{ATTEMPTS} failed: {error}", flush=True)
                time.sleep(2 * (attempt + 1))
    # **"The way there is broken" is not "this build cannot be fetched."**  Both used to
    # leave here as `ArtifactError`, so a caller could not tell a 404 on one artifact (a
    # fact about that build: `deadbeef1234` has no `modules` URL at all) from a proxy that
    # cannot connect (a fact about the network, and true of every build).  The transport
    # failure keeps its own type - `InfraError`, the exit-3 "we never got what we came for"
    # of `lib/errors.py` - and a caller that wants to stop pulling when the network is down
    # can finally see which one it is.  `table.py pull` is the first such caller.
    if isinstance(last, requests.RequestException):
        raise errors.InfraError(
            f"{url}: gave up after {ATTEMPTS} attempts: {last}") from last
    raise errors.ArtifactError(
        f"{url}: gave up after {ATTEMPTS} attempts: {last}") from last


def _status_error(code, what):
    """A 4xx is permanent, anything else is worth retrying."""
    message = f"unexpected status {code} for {what}"
    return _Permanent(message) if 400 <= code < 500 else errors.ArtifactError(message)


def _complete(path, url, expected=None, max_size=MAX_SIZE):
    """True when `path` is already the whole artifact: its size is the proven one."""
    if not os.path.isfile(path):
        return False
    size = os.path.getsize(path)
    known = expected if expected is not None else _remote_size(url)
    return bool(known) and size == known and size <= max_size


def _remote_size(url):
    """The size the host reports for `url`, or None - one HEAD, no body."""
    try:
        with requests.head(url, timeout=TIMEOUT, allow_redirects=False) as response:
            if response.is_redirect or response.status_code != 200:
                return None
            length = response.headers.get("Content-Length")
    except (requests.RequestException, OSError):
        return None
    return int(length) if length and length.isdigit() else None


def _remote_total(response, offset):
    """The whole artifact's size as this response reports it, or None."""
    total = _content_range_total(response)
    if total is not None:
        return total
    length = response.headers.get("Content-Length")
    return int(length) + offset if length and length.isdigit() else None


def _content_range_total(response):
    """The total in a `Content-Range` header - `bytes 1-9/10` and `bytes */10` both carry it."""
    value = response.headers.get("Content-Range") or ""
    tail = value.rsplit("/", 1)[-1]
    return int(tail) if "/" in value and tail.isdigit() else None


def _read(response, part, offset, max_size):
    """Append the body to the partial file and return the size it now has."""
    size = offset
    with open(part, "ab" if offset else "wb") as handle:
        for chunk in response.iter_content(CHUNK):
            if not chunk:
                continue
            handle.write(chunk)
            size += len(chunk)
            if size > max_size:
                raise errors.ArtifactError(f"more than {max_size} bytes arrived")
        handle.flush()
        os.fsync(handle.fileno())
    return size


def _local_source(url):
    """`url` as a local path when it names one (`file://` or a bare path), else ''."""
    if url.startswith("file://"):
        return url[len("file://"):] or ""
    if "://" in url:
        return ""
    return url if os.path.isfile(url) else ""


def _copy(source, dest, expected=None, max_size=MAX_SIZE):
    """Copy a local artifact into `dest`, proving its size the way a download does."""
    size = os.path.getsize(source)
    if size <= 0 or size > max_size or (expected is not None and expected != size):
        raise errors.ArtifactError(f"{source} is {size} bytes; refusing it")
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    part = f"{dest}.part"
    shutil.copyfile(source, part)
    os.replace(part, dest)
    return dest


def _remove(path):
    """Delete `path` if it is there; a leftover temp file is never worth failing a run over."""
    try:
        os.unlink(path)
    except OSError:
        pass


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


# ---------------------------------------------------------------------------
# Publishing the kernel this deployment serves
# ---------------------------------------------------------------------------

def _stamp():
    """Now, in the one timestamp spelling this tree writes (UTC, seconds)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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


def publish_local(run):
    """Publish `var/serve/Image` as the build this deployment serves; nothing is run.

    The URL it is recorded under is `--parameter kernel_url=`, else
    `$KCI_KERNEL_URL`, else the file itself; the identity is `--parameter
    tree|branch|commit|describe|defconfig=`, else the `KCI_BUILD_*` environment.
    Returns the exit status.
    """
    image = os.path.abspath(layout.serve("Image"))
    if not os.path.isfile(image):
        raise errors.ArtifactError(f"nothing to publish: {image} is not there")
    url = run.params.get("kernel_url") or os.environ.get("KCI_KERNEL_URL") or f"file://{image}"
    commit = _fact("commit", run)
    kbuild = Kbuild(
        build_id=_published_id(url, commit),
        tree=_fact("tree", run),
        branch=_fact("branch", run),
        arch="riscv64",
        defconfig=_fact("defconfig", run),
        created=_stamp(),
        artifacts={"kernel": url},
        revision={"commit": commit, "describe": _fact("describe", run)},
    )
    table = Builds.load()
    table.merge((kbuild,))
    table.save()
    _remember_served(kbuild, url)
    print(f"published {kbuild.build_id}: {url}  ({layout.index()})")
    return errors.EXIT_PASS


def served() -> dict:
    """The build this deployment serves, as `publish_local()` recorded it; `{}` if none.

    Two readers need this and neither can get it from the table: retention must
    never delete the build `var/serve/Image` is, and the local stack seeds its
    jobs from the build it serves.  The card in `var/state/builds.json` cannot
    answer either question - it says a kernel exists, not that *this* deployment
    serves it, and a card survives a re-provision.  A file that is missing or
    unreadable answers `{}`: "no build published yet" is a state, not an error.
    """
    try:
        with open(layout.state(SERVED_NAME), encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def provision(api, tree="riscv", branch=None) -> "Kbuild":
    """Fetch the newest **passing** production build's kernel and serve it here.

    This is the act `python3 provision.py` performs, and it is the old tree's
    `kcilib/deploy/provision.py` with one reader instead of three: the build is
    chosen from the API (`Kbuilds.getnew(..., passing=True)` - done and passed, the
    window widening until one exists), its kernel is materialized by the same
    `make()` every other fetch uses, `var/serve/Image` is a symlink to it rather
    than a second 27 MB copy (the old `work/serve/Image -> ../env/Image` did the
    same), and `_remember_served()` writes the record the stack's seed reads.

    The *kernel release* is what a seeded stack's `modprobe` matches, so the
    kernel and the modules the record names must come from the same build - both
    are read off this one card, never mixed.

    Returns the card it published.
    """
    from . import kbuild as kbuild_mod
    card = kbuild_mod.Kbuilds(api).getnew(tree, branch, passing=True)
    build = Build(card).make(("kernel",))
    _link_served(build)
    Builds.load().remember(build)
    _remember_served(card, card.artifact("kernel"))
    return card


def _link_served(build) -> str:
    """Point `var/serve/Image` at `build`'s local kernel; return the link's path.

    A symlink, not a copy: the image the stack serves *is* the build's artifact,
    and a copy is one more 27 MB that can disagree with the bytes next to it.  It
    is written relatively (`../downloads/<id>/Image`) so the workspace survives
    being copied or mounted somewhere else.

    **What was at the path is never deleted silently.**  Our own link goes (it is
    a previous provisioning, and the record of it is rewritten in the same call);
    a *regular file* is either replaced - when its bytes are the kernel we are
    about to serve anyway, so nothing is lost - or moved aside to
    `Image.kept-<stamp>` with a line saying so.  The old tree solved this by
    refusing to touch an existing non-empty image at all (`delivery._ensure_symlink`
    returned early), which kept a hand-placed kernel safe but also meant a
    re-provision served the old bytes while the record named the new build - a lie
    in the one file the stack seeds from.  Moving it aside keeps both promises.
    """
    source = build._local("kernel")
    if not os.path.isfile(source):
        raise errors.ArtifactError(
            f"cannot serve {build.build_id}: {source} is not there")
    link = os.path.abspath(layout.serve("Image"))
    os.makedirs(os.path.dirname(link), exist_ok=True)
    target = os.path.relpath(source, os.path.dirname(link))
    if os.path.islink(link):
        os.unlink(link)
    elif os.path.isfile(link):
        if _same_bytes(link, source):
            print(f"{link} was already {build.build_id}'s kernel; replaced by the link")
            os.unlink(link)
        else:
            kept = f"{link}.kept-{_stamp().replace(':', '')}"
            os.replace(link, kept)
            print(f"! {link} held an image this deployment never recorded "
                  f"({os.path.getsize(kept)} bytes); kept it at {kept}")
    try:
        os.symlink(target, link)
    except OSError as problem:
        raise errors.ArtifactError(f"cannot publish {link}: {problem}") from problem
    return link


def _same_bytes(first, second):
    """Are two files the same bytes?  Read in chunks: an Image is 27 MB."""
    if os.path.getsize(first) != os.path.getsize(second):
        return False
    with open(first, "rb") as left, open(second, "rb") as right:
        while True:
            one, two = left.read(CHUNK), right.read(CHUNK)
            if one != two:
                return False
            if not one:
                return True


def _remember_served(kbuild, url):
    """Write `var/state/served.json` atomically - the act, not just its side effect.

    The old tree recorded the same facts as shell variables in
    `work/env/build.env`, which `run-local-stack.sh` *sourced*; this is that file's
    content as data, written by the same command that publishes the image, so the
    facts and the bytes cannot disagree.  Every key the seed read is here, under
    the name it means rather than the name a shell needed:

        KCI_BUILD_DIR      -> build_dir      (the artifact directory all of them
                                              live under: modules, kselftest, .config)
        KCI_KERNEL_URL     -> kernel_url     KCI_MODULES_URL -> modules
        KCI_ROOTFS_URL     -> rootfs         (the lab's own guest disk, not a build's)
        KCI_BUILD_COMMIT   -> commit         KCI_BUILD_DESCRIBE -> describe
        KCI_BUILD_TREE     -> tree           KCI_BUILD_BRANCH -> branch
        KCI_BUILD_URL      -> tree_url       KCI_BUILD_VERSION/PATCHLEVEL/TAGS -> version
    """
    revision = kbuild.revision or {}
    version = revision.get("version")
    if not isinstance(version, dict):
        # `{"version": N, "patchlevel": N}` or a bare int: `.get()` on the int
        # raised AttributeError and lost the whole file (the old tree's N10).
        version = {"version": version} if isinstance(version, int) else {}
    record = {
        "build_id": kbuild.build_id,
        "node_id": kbuild.node_id,
        "kernel_url": url,
        "build_dir": url.rsplit("/", 1)[0],
        "modules": kbuild.artifact("modules"),
        "kselftest": kbuild.artifact("kselftest_tar_xz") or kbuild.artifact("kselftest"),
        "config": kbuild.artifact("_config"),
        "rootfs": tests.ROOTFS_URL,
        "image": os.path.abspath(layout.serve("Image")),
        "tree": kbuild.tree, "branch": kbuild.branch, "arch": kbuild.arch,
        "defconfig": kbuild.defconfig, "compiler": kbuild.compiler,
        "created": kbuild.created, "state": kbuild.state, "result": kbuild.result,
        "commit": revision.get("commit", ""), "describe": revision.get("describe", ""),
        "tree_url": revision.get("url", ""),
        "version": version.get("version") or "", "patchlevel": version.get("patchlevel") or "",
        "tags": list(revision.get("commit_tags") or []),
        "at": _stamp(),
    }
    path = layout.state(SERVED_NAME)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(f"{path}.tmp", "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(f"{path}.tmp", path)
    except OSError as problem:
        # Loud, and fatal: a published image the deployment cannot name is one
        # retention may prune and the stack cannot seed from.
        raise errors.ArtifactError(
            f"published {kbuild.build_id} but could not record it in {path}: {problem}") from problem


def _fact(name, run):
    """One build fact: `--parameter <name>=`, else `$KCI_BUILD_<NAME>`, else ''."""
    return run.params.get(name) or os.environ.get(f"KCI_BUILD_{name.upper()}", "")


def _published_id(url, commit):
    """The id a local kernel is filed under: the URL's, else the commit's, else a refusal."""
    found = build_id_of({"kernel": url})
    if found:
        return found
    if commit:
        return commit[:12]
    raise errors.ConfigError("a published kernel needs an id: a URL that carries one, or a commit")


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

class Builds:
    """The local table: the builds this machine has, as one JSON file."""

    def __init__(self, items=()):
        self.items = list(items)

    @classmethod
    def load(cls, path=None):
        """Read the table; a missing, unreadable or unparsable file is an empty table."""
        try:
            with open(path or layout.index(), encoding="utf-8") as handle:
                stored = json.load(handle)
            records = stored.values() if isinstance(stored, dict) else stored
            return cls(Build(_kbuild(record)) for record in records
                       if isinstance(record, dict) and record.get("build_id"))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path=None):
        """Write the table atomically: one object keyed by build id, keys sorted."""
        path = path or layout.index()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(f"{path}.tmp", "w", encoding="utf-8") as handle:
            json.dump({build.build_id: _record(build) for build in self.items},
                      handle, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(f"{path}.tmp", path)

    def fetch(self, api, tree="", days=7, limit=200):
        """Ask the API for builds of the last `days` days (`tree=''` = any) and fold them in.

        The cap is applied to *usable* builds, so the read itself stays uncapped:
        a window whose newest nodes are still running would otherwise fill the cap
        with builds nobody can run, and the table would register nothing.  A cap
        below one is refused rather than applied - `[:0]` registers nothing, and
        `[:-5]` silently drops the five newest builds, which are the five the
        caller asked for.
        """
        from . import kbuild
        if int(limit) < 1:
            raise errors.ConfigError(f"--limit must be at least 1, got {limit}")
        self.merge(kbuild.Kbuilds(api).getdays(tree, days)[:int(limit)])

    def get(self, build_id):
        """The build held for `build_id`; a ConfigError when the table holds none."""
        for build in self.items:
            if build.build_id == build_id:
                return build
        raise errors.ConfigError(f"no build {build_id!r} in {layout.index()}")

    def newest(self):
        """The most recently created build here; a ConfigError when the table is empty."""
        if not self.items:
            raise errors.ConfigError(f"the build table {layout.index()} is empty")
        return max(self.items, key=_created)

    def merge(self, other):
        """Fold in a `Kbuilds` or another `Builds`: one entry per build_id, the first wins."""
        for item in other:
            kbuild = item.kbuild if isinstance(item, Build) else item
            if not kbuild.build_id:
                raise errors.ConfigError("a build with no build_id cannot go in the table")
            held = next((one for one in self.items if one.build_id == kbuild.build_id), None)
            if held is None:
                self.items.append(Build(kbuild))
            else:
                held.merge(kbuild)

    def remember(self, build):
        """Fold one pulled build into the table and save it: a pull is also a registration.

        `Build.make()` writes bytes and a pull record and knows nothing about the
        table, so `runday`, `run_latest`, the worker and every job's own `make()`
        left copies that the page could only render as "no card in the local
        table" - pulled, run, and not in the book, with a drill-down whose two
        buttons both refused with `no build ... in builds.json`.  Every command
        that pulls says so here instead, and the page's three facts stay three:
        card, bytes, act.

        The base is the file, read again here and not the copy the caller loaded
        before a download that can take twenty minutes: `save()` writes every
        record, so a stale snapshot would drop what another command registered
        while we pulled, and would put back a card the operator pruned.  A build
        the file already holds is left exactly as it is - the card is the
        operator's, a re-pull adds nothing to it that its own artifact URLs do
        not already say, and rewriting 27 records to say nothing is how two
        writers lose each other's work.  A build with no kbuild, or with no
        build_id, is a directory with no name to file it under.

        A pull that raised never reaches here: `make()` records its own failed
        act and the caller stops, so a failed pull leaves no card behind.
        """
        if build.kbuild is None or not build.kbuild.build_id:
            return self
        held = Builds.load()
        if not any(one.build_id == build.build_id for one in held):
            held.merge([build])
            held.save()
        self.items = held.items          # this handle now says what the file says
        return self

    def make(self, tests=None):
        """Download, for every build here, whatever a test it cannot run still needs."""
        for build in self.items:
            for test in (tests or DEFAULT_TESTS):
                entry = TESTS.get(test)
                if entry and build.missing(test):
                    build.make(entry["needs"])

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def print(self, stream=None):
        """One line per build, newest first."""
        for build in sorted(self.items, key=_created, reverse=True):
            build.print(stream)


def _record(build):
    """One build as the object the table stores: the kbuild's own fields."""
    return asdict(build.kbuild) if build.kbuild is not None else {"build_id": build.build_id}


def _kbuild(record):
    """One stored object back as a `Kbuild`, dropping keys this version does not know."""
    known = {one.name for one in fields(Kbuild)}
    return Kbuild(**{key: value for key, value in record.items() if key in known})


def _created(build):
    """A build's creation time, or '' - the field the table sorts by."""
    return (build.kbuild.created if build.kbuild is not None else "") or ""
