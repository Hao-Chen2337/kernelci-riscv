# SPDX-License-Identifier: LGPL-2.1-or-later
"""`Build`, plus the constants and the names the whole build half is written in.

`Build` is one build's local copy - a `Kbuild` plus `var/downloads/<build-id>/` -
and everything else in this package imports the artifact vocabulary, the size
limits and `_Permanent` from here, so "what artifacts exist" and "how big a
transfer may be" have exactly one spelling.

**This is where the package's one cycle is cut.**  `fetch` and `rootfs` need the
constants and the sizes owned here, so this module cannot import them back at
module level; the three `Build` methods that reach outward (`merge`, `_fetch`,
`rootfs`) import what they call *inside* the method.  That is the same device the
single-module `lib/build.py` already used for `kbuild`, and it is what keeps the
rest of the package a straight downward graph.

接口形状（C++，只有声明）：include/kci/local.hpp §7 Build。
"""

import json
import os
import shutil
from dataclasses import dataclass, field, replace

from .. import atomic, errors, layout
from ..kbuild import Kbuild, _stamp
from ..tests import ROOTFS_URL, needs

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
        # Imported here, not at the top: see this module's docstring for the cycle.
        from .rootfs import bake_rootfs
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
        # Imported here, not at the top: see this module's docstring for the cycle.
        from .fetch import _names_this_build
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
        # Imported here, not at the top: see this module's docstring for the cycle.
        from .fetch import download
        from .rootfs import _kernel
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
            atomic.write_json(layout.provenance(self.build_id), record,
                              indent=1, sort_keys=True)
        except OSError as problem:
            raise errors.ArtifactError(
                f"cannot record the pull of {self.build_id} in {self.path}: {problem}") from problem


class _Permanent(errors.ArtifactError):
    """A failure retrying cannot fix: a 4xx, a redirect, an artifact that is too big."""
