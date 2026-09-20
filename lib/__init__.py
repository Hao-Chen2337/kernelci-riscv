# SPDX-License-Identifier: LGPL-2.1-or-later
"""The middle layer: one run is pick a build -> make it local -> run a job -> get an outcome.

Everything above this package (the four entry points, the GUI, the viewers) is a
selector or a viewer; everything below it is the outside world (KernelCI HTTP,
tuxrun/QEMU, the filesystem).  Nothing in here imports an entry point or a tool.

    api     the only KernelCI HTTP
    kbuild / kjob     what the API has      (remote, read-only)
    build  / job      what we do with it    (local, has side effects)
    out               what came back
    judge / runner    TAP -> verdict, argv -> console
    sink              where an outcome goes
    poller            the rotation: watch the API, run what appears
    layout / config   where bytes live, what the operator asked for
    errors            one exception root, three exit codes
    gui / drift / re  viewers over the same objects

Draft this package is built from: the extensionless files in this directory
(kbuild, build, kjob, job, out, poller) -- kept as written, superseded by the
``.py`` beside them.
"""

import os

__all__ = ["repo_root"]

# The walk below is done at most once per process and then remembered.  The answer
# cannot change while a process runs, and it is not free: `layout.work()` calls it,
# every `layout.*` path calls `work()`, and one page render makes hundreds of those.
# Measured on `/jobs` before this cache: **153 `repo_root()` calls, 306 `os.path.exists`
# calls, inside a 10.3 ms render** - the walk was most of what a warm page cost, and a
# warm page is the click-to-click time the operator actually feels.  (`/runs` was 10
# calls / 20 stats.)  After it: 1 call, 2 stats.
#
# What is deliberately *not* cached is `$KCI_WORK_DIR`: `layout.work()` still reads it
# on every call, because a test that points the workspace somewhere else has to work -
# `docs/gui-rework/tools/test_config_cache.py` is exactly that test.
_ROOT: "str | None" = None


# What the root of this repository is, for `repo_root()`: two files only this
# checkout has, both stable across any move *inside* the tree.  The sentinel used to
# be `run.sh` - the old tree's dispatcher, and for two years the one file that meant
# "this is the root" - and it was deleted with that tree (2026-09-20).  A tree whose
# root only one file can name is a tree that dies with that file; `lib/layout.py`
# (this package's own path owner) plus `README.md` is the pair that replaces it.
ROOT_MARKERS = ("lib/layout.py", "README.md")


def repo_root():
    """The repository root: the directory holding this package and the README (walked up).

    Walked once; see `_ROOT` for why.  Never counted in `os.path.dirname()` levels:
    a fixed count pointed one level short after a package move, so every artifact
    went to the wrong place and the ledger read back empty, with nothing raised.
    The sentinel is `None` rather than the empty string so that a root which
    genuinely cannot be found still raises on every call instead of being
    remembered as missing.
    """
    global _ROOT
    if _ROOT is not None:
        return _ROOT
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if all(os.path.exists(os.path.join(here, marker)) for marker in ROOT_MARKERS):
            _ROOT = here
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    raise RuntimeError(
        f"no repository root above {os.path.abspath(__file__)}: a directory holding "
        f"{' and '.join(ROOT_MARKERS)}")
