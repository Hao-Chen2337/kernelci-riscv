# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The one owner of where bytes live in this repository.

Four categories, one directory each - they may not mix::

    work/inputs/<build-id>/   input     one build's fetched bytes
    work/derived/             derived   recomputable from the inputs, deletable
    work/runs/<run-id>/       output    a console and what this run recorded
    work/state/               state     which build this deployment serves

work/serve/ holds only published copies of outputs, so it is not a fifth
category - it is an output tree with an audience.

Nothing has moved yet.  Every accessor whose data still sits on a legacy path
returns that path (so today's readers keep working), and legacy_map() registers
each legacy path with the tree it is destined for.  Rationale:
docs/REFACTOR-D-BRIEF.md 2.2.
"""

import fnmatch
import os
import pathlib
from enum import Enum

from kcilib import repo_root

__all__ = [
    "Category", "baked", "cache", "category_of", "default_results",
    "deployment_env", "derived", "downloads", "env", "generated", "index",
    "inputs", "kselftest_cache", "legacy_map", "logs", "results", "root",
    "run", "runs", "seed_env", "serve", "state",
]

# ledger.results_dir() answers the same question and is the contract for
# records; spelled here (not imported) so wiring ledger to layout cannot make a
# cycle, and named once so the two cannot drift apart by a typo.
_RESULTS_DIR_ENV = "KCI_RESULTS_DIR"


class Category(str, Enum):
    """What a path under work/ is - a str so a table, a guard and a log line agree."""

    INPUT = "input"
    DERIVED = "derived"
    OUTPUT = "output"
    STATE = "state"


def root():
    """The repository root as a Path - walked up to by repo_root(), never counted."""
    return pathlib.Path(repo_root())


def inputs(build_id):
    """One build's fetched bytes: one directory per build, so a re-fetch cannot mix two."""
    return _child(root() / "work" / "inputs", build_id, "build id")


def derived():
    """Recomputable from the inputs, so deleting it costs time and never data."""
    return root() / "work" / "derived"


def baked():
    """The bake cache's destination: one image per input set, so it belongs under derived/."""
    return derived() / "baked"


def runs():
    """Per-run output, because a console belongs to the run and not to the build it ran."""
    return root() / "work" / "runs"


def run(run_id):
    """One run's own directory - a run id names a directory, never a path."""
    return _child(runs(), run_id, "run id")


def logs():
    """Today's console archive (work/logs); runs()/<run-id>/ is where 2.2 sends it."""
    return root() / "work" / "logs"


def results():
    """The ledger's directory verbatim: work/results, or $KCI_RESULTS_DIR over it."""
    override = os.environ.get(_RESULTS_DIR_ENV)
    return pathlib.Path(override) if override else default_results()


def default_results():
    """work/results without the environment: the module constant a frozen name needs.

    results() answers "where do records go NOW"; this answers "what is the path
    itself", which is what a constant like ledger.RESULTS_DIR must be - a name
    frozen at import may not follow $KCI_RESULTS_DIR.
    """
    return root() / "work" / "results"


def env():
    """Today's mixed work/env: inputs, derived bytes and deployment state at once.

    Deliberately unclassified - see category_of().  It is the directory this
    migration dissolves, so it is addressed here and never given a category.
    """
    return root() / "work" / "env"


def kselftest_cache():
    """The extracted kselftest tree (work/env/kselftest): derived, so it may be rebuilt."""
    return env() / "kselftest"


def index():
    """The local build index (work/builds.db): re-pullable from the API, so derived."""
    return root() / "work" / "builds.db"


def generated(name):
    """A file rendered into work/ by this repository, e.g. local-callback.toml."""
    if not name or "/" in name or os.sep in name or name in (".", ".."):
        raise ValueError(f"a generated file names one file under work/, got {name!r}")
    return root() / "work" / name


def state():
    """What this deployment serves and seeded - a fact about the deployment, not fetched bytes."""
    return root() / "work" / "state"


def downloads():
    """Today's fetched build tree (work/downloads); inputs(build_id) is its destination."""
    return root() / "work" / "downloads"


def deployment_env():
    """Today's record of the build this deployment serves; state()/build.env is its destination."""
    return root() / "work" / "env" / "build.env"


def seed_env():
    """Today's record of the tree that was seeded; state()/seed.env is its destination."""
    return root() / "work" / "env" / "seed.env"


def serve():
    """Only what is published to the outside, so nothing private may be written here."""
    return root() / "work" / "serve"


def cache():
    """Today's bake cache (work/env/baked), readable until baked() holds the data."""
    return root() / "work" / "env" / "baked"


def category_of(path):
    """Which category *path* is, for the new tree and the legacy one alike.

    A path layout cannot place is a bug, not a default: an unknown path raises
    rather than being filed under a guessed category, because the guess is how
    two kinds of byte end up in one directory again."""
    override = os.environ.get(_RESULTS_DIR_ENV)
    if override and _within(path, override):
        # results() can be moved by the environment, and what results() returns
        # must still classify - otherwise the record's own path has no category.
        return Category.OUTPUT
    relative = _relative(path)
    parts = relative.split("/")
    if len(parts) >= 2 and parts[0] == "work":
        destination = _TREES.get(parts[1])
        if destination is not None:
            return destination
    key = _longest_legacy_key(relative)
    if key is None:
        raise ValueError(
            f"{relative!r} belongs to no layout category: register it in "
            f"legacy_map() if it is a real path, or stop writing it"
        )
    return _LEGACY[key]


def legacy_map():
    """The legacy path -> category table: where each old path's bytes are headed.

    A copy, so a caller can print or migrate it without editing the one table
    that decides where bytes go."""
    return dict(_LEGACY)


# The destination tree of each new category, keyed by the directory under work/.
_TREES = {
    "inputs": Category.INPUT,
    "derived": Category.DERIVED,
    "runs": Category.OUTPUT,
    "state": Category.STATE,
}

# Every legacy path with a reader today, and the category of the bytes in it.
# A pattern may name one id with *: the file it matches still has a category, and
# the category is what tells the migration which tree the file has to end up in.
_LEGACY = {
    # fetched bytes: today one build's inputs live in two directories
    "work/downloads": Category.INPUT,
    "work/env/Image.gz": Category.INPUT,
    "work/env/full.rootfs.tar.xz": Category.INPUT,
    "work/env/trixie-full.rootfs.tar.xz": Category.INPUT,
    "work/env/kselftest": Category.INPUT,
    # recomputable from those inputs without the network
    "work/env/Image": Category.DERIVED,
    "work/env/rootfs-kvm.ext4": Category.DERIVED,
    "work/env/baked": Category.DERIVED,
    "work/builds.db": Category.DERIVED,
    "work/local-callback.toml": Category.DERIVED,
    "work/cb-config": Category.DERIVED,
    # what a run produced, and what is published from it
    "work/results": Category.OUTPUT,
    "work/logs": Category.OUTPUT,
    "work/serve": Category.OUTPUT,
    # A fetched build's directory is input, but every console written beside it
    # is output - and the archived console is named after the build, so the
    # generic pattern has to exist or it files a console as an input.
    "work/downloads/*/*.log": Category.OUTPUT,
    "work/downloads/*/tuxrun.log": Category.OUTPUT,
    "work/downloads/*/serve.log": Category.OUTPUT,
    # what this deployment serves, seed and runs
    "work/env/build.env": Category.STATE,
    "work/env/seed.env": Category.STATE,
    "work/env/images.env": Category.STATE,
    "work/env/.manifest.json": Category.STATE,
    "work/env/stack-*.pids": Category.STATE,
}


def _child(base, name, what):
    """A directory name, not a path: an id holding a separator writes under another id's name."""
    if not name or name in (".", "..") or os.sep in name or "/" in name or "\\" in name:
        raise ValueError(f"a {what} names one directory, got {name!r}")
    return base / name


def _relative(path):
    """Repo-relative and unresolved: work/serve/Image is a symlink and stays published."""
    given = os.fspath(path)
    relative = os.path.relpath(given, repo_root()) if os.path.isabs(given) else os.path.normpath(given)
    relative = relative.replace(os.sep, "/")
    if relative == ".." or relative.startswith("../"):
        raise ValueError(f"{path!r} is outside the repository, so it has no layout category")
    return relative


def _within(path, base):
    """True when *path* is *base* or under it, compared without resolving symlinks."""
    given = os.path.normpath(os.path.abspath(os.fspath(path)))
    against = os.path.normpath(os.path.abspath(os.fspath(base)))
    return given == against or given.startswith(against + os.sep)


def _longest_legacy_key(relative):
    """The most specific registered key matching *relative*, so a file may be filed apart from its directory."""
    best = None
    for key in _LEGACY:
        if not _matches(relative, key):
            continue
        if best is None or len(key) > len(best):
            best = key
    return best


def _matches(relative, key):
    """A key matches its own directory and everything under it, or by pattern when it has one."""
    if relative == key or relative.startswith(key + "/"):
        return True
    return "*" in key and fnmatch.fnmatchcase(relative, key)
