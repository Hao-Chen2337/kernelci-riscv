# SPDX-License-Identifier: LGPL-2.1-or-later
"""`Build`, plus the constants and the names the whole build half is written in.

`Build` is one build's local copy - a `Kbuild` plus `var/downloads/<build-id>/` -
and everything else in this package imports the artifact vocabulary, the size
limits and `_Permanent` from here, so "what artifacts exist" and "how big a
transfer may be" have exactly one spelling.

It owns one more pair no module under it could own: **where a build's `.config`
is** - the URL it comes from (`Build.config_url`) and the shared cache its bytes are
kept in (`config_path` / `Build.config_cache`).  `lib/drift.py` reads and writes
that cache, so it imports the two from here rather than digesting a URL a second
time.

**This is where the package's one cycle is cut.**  `fetch` and `rootfs` need the
constants and the sizes owned here, so this module cannot import them back at
module level; the three `Build` methods that reach outward (`merge`, `_fetch`,
`rootfs`) import what they call *inside* the method.  That is the same device the
single-module `lib/build.py` already used for `kbuild`, and it is what keeps the
rest of the package a straight downward graph.

接口形状（C++，只有声明）：include/kci/local.hpp §7 Build。
"""

import hashlib
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

# The environment variable naming this deployment's own artifact storage, and the
# address a build's config falls back to when its card names none.  One spelling,
# here: `Build.config_url` is the only reader, and it is the reader `lib/drift.py`
# asks - so a deployment that moves its storage moves it for both.
STORAGE_ENV = "KCI_STORAGE_URL"
STORAGE_DEFAULT = "http://127.0.0.1:8002"


def config_path(url):
    """Where one URL's `.config` is kept between downloads: `var/configs/<digest>`.

    The digest is of the URL, because that is what identifies the bytes: a config
    served under a different address is a different file, and the same address
    serving different bytes is the artifact store contradicting its own build id.
    The `.config` suffix is kept so a reader who finds the directory can open the
    file without asking what it is.

    **This is the tree's only digest of a config URL.**  `lib/drift.py` writes
    into this cache and reads out of it, `Build.config_cache` asks whether a
    build's config is in it, and a second sha256 spelled anywhere else would name
    a file the writer never wrote - a cache that never hits, which is exactly the
    × this pair exists to stop.
    """
    return layout.configs(hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".config")


def config_note(url):
    """The sidecar that says what the kept file is supposed to be: the same name, `.json`.

    A `.config` is a text file a reader may open, so the checksum cannot live in
    it.  It sits beside it: the URL it came from, how many bytes, and the sha256
    of those bytes.

    **Why a checksum and not just a size.**  A cache is only worth having if a
    damaged entry is *detected*, and a truncated config does not announce itself:
    a config cut off at 5 000 of 192 231 bytes still parses into 166 options, so
    the comparison answers **+5426 -8 ~1 instead of +618 -616 ~99, with zero HTTP
    calls and no sign that anything is wrong** - a confident, wrong drift report,
    which is the exact failure this tree refuses elsewhere ("an empty parse is an
    ERROR").  The same is true of a download truncated in transit: without a
    recorded size it would be cached as the truth for ever.

    What a kept file that does not match its note *means* - refuse it, loudly, and
    say so - is the cache reader's own reading (`lib/drift.py: _kept_config`);
    this function says where the note is, and nothing about what is in it.
    """
    return config_path(url)[:-len(".config")] + ".json"


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

        **An artifact with no URL is not a failure when its bytes are here.**  The
        URL is how a `want`-item is *fetched*; a run reads the file itself
        (`runner._local`), so a file that is already in place is taken as it stands
        whatever the card says about where it would have come from.  See the loop
        below: it is the difference between "this build cannot be run" and "this
        build has nothing left to download", and on this deployment one card lands
        in the first case with its `modules`, `kselftest` and `config` absent from
        the API's `artifacts` map.

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
                dest = self._local(name)
                if not url:
                    # **Bytes already here need no URL.**  The URL's only job is to
                    # fetch, and tuxrun reads these files as `file://` (`runner._local`),
                    # so a copy someone put in place by hand - or one an older tree, a
                    # worker, or a hand-copied directory left - is runnable as it
                    # stands.  Refusing here made that impossible for ever: on this
                    # deployment one card names no `modules`, `kselftest` or `config`
                    # URL, so its three pairs could never be run even with the bytes on
                    # disk, and `missing()` agreed with the refusal (`_lacking` asked
                    # about the URL first).  Nothing is *proven* about such a file - it
                    # is recorded in no act, so `provenance()` cannot say where it came
                    # from (`Local.state` reads `unrecorded`, which is the honest word
                    # for it) - and a file that is not there at all is still the
                    # ArtifactError it always was.
                    if os.path.isfile(dest) and os.path.getsize(dest):
                        self.files[name] = dest
                        continue
                    raise errors.ArtifactError(f"build {self.build_id} has no {name} artifact")
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
        """The artifacts whose local file is on disk, as `{name: path}` (the shape `files` has).

        **This build's own copy, and only its own copy** - one `os.path.isfile`
        under `var/downloads/<build-id>/`.  Three readers act on that answer
        literally, which is why it is not widened to the shared cache a config
        lives in (`artifact_path` is the reader for "can this be read at all"):

        * `make()`'s idempotence - a file already here is not fetched again;
        * a runner, which reads these files as `file://` (`runner._local`);
        * `lib/drift.py: _config_local`, which seeds `var/configs/` from *a copy a
          pull left here* and would otherwise report a cache **hit** as a copy
          that was **pulled** - a claim about where bytes came from, made on
          evidence that says only that they are somewhere on this disk.
        """
        return {name: self._local(name) for name in self._present()}

    def config_url(self, job=""):
        """This build's `.config` URL: the card's artifact, else this deployment's storage.

        The card's own `_config` (the API's spelling) or `.config` names the file.
        A card does not always carry one - on this deployment `config` is one of
        the artifacts a card can be missing - and then the file is where the
        deployment this workspace belongs to serves it:
        `<storage>/<job>-<node_id or build_id>/.config`.  `$KCI_STORAGE_URL` is
        read at call time and never at import, so a second workspace on one
        checkout picks its own up.

        `job` is that directory's *prefix* and not a tree: `kbuild` when the
        caller names none.  The API's own job name carries a compiler and a branch
        (`kbuild-gcc-14-riscv`), and this is the storage's shorter one.

        **One definition, two readers.**  This is the URL `lib/drift.py` compares
        two configs *by*, and the URL whose cache `config_cache` looks a kept copy
        up by - so "which URL is this build's config" has one answer in the tree,
        and the mark that says a config can be read cannot disagree with the fetch
        it predicts.
        """
        url = ""
        if self.kbuild is not None:
            url = self.kbuild.artifact("_config") or self.kbuild.artifact(".config")
        if url:
            return url
        storage = os.environ.get(STORAGE_ENV) or STORAGE_DEFAULT
        node = (self.kbuild.node_id if self.kbuild is not None else "") or self.build_id
        return f"{storage.rstrip('/')}/{job or 'kbuild'}-{node}/.config"

    def config_cache(self, job=""):
        """The kept copy of this build's config in `var/configs/`, or `""` when there is none.

        **Not `present()["config"]`, and the difference is the whole point of this
        method.**  `present()` answers what a *pull of this build* left in its own
        directory, and the config is usually not there: `make()` does not fetch it
        (`WANT` is the three a guest needs), so on this deployment
        `var/downloads/*/.config` is nothing at all.  What a reader wants from a
        config is not a file to boot but text to *compare*, and a comparison keeps
        it in `var/configs/` - one directory keyed by the config's URL
        (`config_path`) and shared by every build that ever named one.  A resource
        mark that asked only the first question therefore drew a `.config` this
        workspace had **already downloaded** as an absence: 319 kept configs, and
        a × beside every one of the builds that owned them.

        What "is there a copy" means here is one `os.path.isfile` and a non-zero
        size - the same reading `_why` makes of a zero-byte file, "a transfer that
        did not finish, not an artifact".  Whether the bytes can be **trusted** is
        a second question with its own answer, and it belongs to the cache's
        reader: `lib/drift.py: _kept_config` refuses a kept copy that does not
        match its sidecar rather than believing it.
        """
        path = config_path(self.config_url(job))
        return path if os.path.isfile(path) and os.path.getsize(path) else ""

    def artifact_path(self, name, job=""):
        """Where `name` can be **read**: this build's own copy first, then the config cache.

        `present()`'s sibling and the answer a mark is drawn from.  For the three
        artifacts a test runs the two agree, because the only place one of those
        lives is this build's own directory; for `config` they do not, and that is
        what this method is for - a config is read here (`<path>/.config`, if a
        pull left one) or in the shared cache (`config_cache`, if a comparison
        ever read this build's URL).

        The file has to exist and be non-empty, which is stricter than
        `present()`'s bare `os.path.isfile`: a position a reader cannot read a
        byte from is not an answer, and an empty file is a transfer that did not
        finish (`_why`).  `name` is one of `ARTIFACTS`, as it is for every other
        per-artifact method here (`_url`, `_why`, `_lacking`: an unknown name is a
        `KeyError` and not a quiet `""`).
        """
        local = self._local(name)
        if os.path.isfile(local) and os.path.getsize(local):
            return local
        if name == "config":
            return self.config_cache(job)
        return ""

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

    def lacking(self, test):
        """The same answer as `missing()` as `(artifact, why)` pairs, `why` a word.

        A page that draws *which* of the three states an artifact is in cannot read
        it out of a sentence: `missing()`'s two reasons are prose written for a
        reader (`kernel: not downloaded yet (<path>)`), and a cell that split them on
        their own `:` would be parsing the engine's English.  So the decision is made
        once, in `_why`, and the two readers are two spellings of it - this one for a
        page's pill, `missing()` for the sentence (`/jobs`' 构件 column draws the
        first and prints the second as the cell's `title=`).

        `why` is `"no-url"` (the card names no such artifact: nothing will ever fetch
        it) or `"no-bytes"` (it is named, and the file is not here yet: a pull fixes
        it).  An artifact whose file is already on disk is in neither list, whatever
        the card says - `make()` says why the bytes are what count.
        """
        try:
            wanted = needs(test)
        except errors.ConfigError as error:
            return [("", str(error))]
        return [(name, why) for name, why in ((one, self._why(one)) for one in wanted) if why]

    # The two words `lacking()` answers with, spelled once so a page and this module
    # cannot disagree about them.  They are values and not sentences, which is why
    # they are not in the catalogue: what a reader sees is the page's own word for
    # each (`col.artifact.no_url` / `col.artifact.no_bytes`).
    NO_URL = "no-url"
    NO_BYTES = "no-bytes"

    def _why(self, name):
        """Why this build cannot give `name`: `""`, `NO_URL` or `NO_BYTES`.

        **The file is asked first.**  `_lacking` used to ask about the URL first, so a
        copy whose bytes had been put in place by hand was reported un-runnable for
        ever - the one state the operator asked about (「没有网址理论也可以硬塞入资源？」).
        A file here is not a *proof* of where it came from (that is `provenance()`'s
        record, and a hand-placed file has none), but it is the thing a run reads.
        The size check is the same one `_lacking` always made: a zero-byte file is
        a transfer that did not finish, not an artifact.
        """
        path = self._local(name)
        if os.path.isfile(path) and os.path.getsize(path):
            return ""
        return self.NO_URL if not self._url(name) else self.NO_BYTES

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
        """Why this build cannot give `name`, or '' - `missing()`'s sentence for `_why`."""
        why = self._why(name)
        if not why:
            return ""
        if why == self.NO_URL:
            return f"{name}: the build has no {name} artifact"
        return f"{name}: not downloaded yet ({self._local(name)})"

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
