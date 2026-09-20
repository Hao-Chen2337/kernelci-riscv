# SPDX-License-Identifier: LGPL-2.1-or-later
"""Every path this project writes, in one file.

The workspace root is `var/`, not the old tree's `work/`: the two trees run side
by side while this one is built, and the old readers raise on a record they
cannot parse, so a shared directory would turn one tree's run into a failure in
the other.  `var/` is regenerable except the ledger, which is history.

One function per thing on disk, so a moved directory is one edit.  The old
four-category theory (input / derived / output / state, with a `category_of()`
that raised on anything unregistered) is gone.

接口形状（C++，只有声明）：include/kci/base.hpp §2 路径。
"""

import os

from . import repo_root

# Together with WORK_NAME, the one knob a deployment needs to move the workspace.
WORK_ENV = "KCI_WORK_DIR"
WORK_NAME = "var"

# The ledger's own escape hatch, and it is inherited from the tree this one
# replaces: `kcilib.core.ledger` reads the same variable, `$KCI_RESULTS_DIR`, and
# the old tree's contract named it ("`work/results/<build-id>/<test>.json`, or
# `$KCI_RESULTS_DIR`").  It is the one seam that lets a test - or a second
# deployment on one checkout - run without touching real history, and the
# gate pins the empty report through it (point it at a temporary directory and
# `python3 results.py` must answer "no result records in <that directory>", not
# this machine's records).  Not honouring it turned the old tree's `verify` red the
# moment the dispatcher started routing `results` here - which is how this was
# found, and `verify.py`'s checks keep the property pinned.
RESULTS_ENV = "KCI_RESULTS_DIR"


def work():
    """The workspace root: `var/`, or $KCI_WORK_DIR."""
    return os.environ.get(WORK_ENV) or os.path.join(repo_root(), WORK_NAME)


# --- what we fetched -------------------------------------------------------

def downloads(build_id=None):
    """`var/downloads/<build-id>/` - one directory per fetched build."""
    return _under("downloads", build_id)


def inputs(build=None):
    """A fetched build's local copy: `Build.dir`."""
    return downloads(build)


def provenance(build_id):
    """`var/downloads/<build-id>/provenance.json` - what was pulled, from where, when.

    It sits inside the build's own directory so deleting the copy deletes the
    claim with it: a record that outlives its bytes would be a lie.
    """
    return os.path.join(downloads(build_id), "provenance.json")


def workspaces(name=None):
    """`var/workspaces/<name>/` - one job's scratch directory.

    Not `runs/`: that directory holds *activities* (a `Run` with its own
    `run.json`), and a job workspace is not an activity - the worker and the
    command line run jobs that nobody started from a page.  Two kinds of thing
    in one directory is how a reader ends up guessing which is which.
    """
    return _under("workspaces", name)


# --- what we derived -------------------------------------------------------

def baked(name=None):
    """`var/baked/` - guest images baked from a rootfs tarball.

    Kept between runs because a bake measured on this machine takes 66-124s (a
    144MB download plus a 4GB `mkfs.ext4`); the image is a pure function of its
    inputs, so nothing here is history.
    """
    return _under("baked", name)


def configs(name=None):
    """`var/configs/` - kernel `.config` files kept from a previous download.

    A `.config` is a text artifact read to be *compared*, not to be run, so it
    lives here rather than under `downloads/<id>/`: that directory is a build's
    runnable copy, and a config is not part of what a test boots.

    The file is named after the digest of the URL it came from (`lib/drift.py`),
    so the same config fetched by two pages is fetched once and a config that
    moves is a different file rather than a stale one.  Regenerable: deleting
    this directory costs one download per config and loses nothing.
    """
    return _under("configs", name)


def runs(run_id=None):
    """`var/runs/<run-id>/` - one job's scratch directory, deleted when it is done."""
    return _under("runs", run_id)


# --- what a run produced ---------------------------------------------------

def logs(name=None):
    """`var/logs/` - archived consoles and action logs; the only copy of a real run."""
    return _under("logs", name)


def serve(name=None):
    """`var/serve/` - the artifacts this deployment serves to the local stack."""
    return _under("serve", name)


def results(build_id=None, test=None):
    """`var/results/<build-id>/<test>.json` - the ledger.  History, never pruned.

    `$KCI_RESULTS_DIR` replaces the whole tree when it is set - reads and writes
    both, because `Ledger` and every reader ask this one function (see RESULTS_ENV).
    """
    base = os.environ.get(RESULTS_ENV) or _under("results")
    if build_id:
        base = os.path.join(base, build_id)
    return os.path.join(base, f"{test}.json") if build_id and test else base


def state(name=None):
    """`var/state/` - deployment facts: which build is served, which tree was seeded."""
    return _under("state", name)


# --- the files that are not per-build --------------------------------------

def worker_state():
    """The resident worker's cursor/seen/pending file (see poller.Poller)."""
    return os.environ.get("KCI_WORKER_STATE") or state("worker-state.json")


def worker_lock():
    """The flock that keeps one worker per deployment."""
    return worker_state() + ".lock"


def index():
    """`var/state/builds.json` - the local build table (the old tree used sqlite)."""
    return state("builds.json")


def _under(first, *rest):
    parts = [work()] + [first] + [p for p in rest if p]
    return os.path.join(*parts)
