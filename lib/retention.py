# SPDX-License-Identifier: LGPL-2.1-or-later
"""Retention for `var/downloads/`: which fetched builds `prune.py` keeps.

Each fetched build is tens of MB and a daily fetch loop runs to gigabytes a year,
so the directory is bounded: **the newest KEEP builds, plus the one this
deployment serves** - deleting that one leaves `var/serve/Image` pointing at a
build whose bytes are gone, which breaks the next seed.  Everything else goes.

This is the old tree's `kcilib/core/retention.py`, and the one decision it made
that nothing else can make is the same: *which* build is protected.  The old rule
read it from two files it also had to trust - `work/env/build.env`'s
`KCI_BUILD_COMMIT`/`KCI_BUILD_DIR`, and each directory's `node.json`.  This tree
records the same act once, as data (`lib/build.py`'s `publish_local()` writes
`var/state/served.json`), so the served build is protected by the id that record
names; there is no `node.json` here to match a commit against, and no second
opinion about what "the served build" means.

The decision and the deletion are separated on purpose (`plan()` returns what
`prune()` deletes), so `--dry-run` and a real run cannot disagree about which
build is which - one pass, each row marked PRUNE or not.

It is the only code in this tree that deletes a user's own retained bytes, so it
takes its target as an argument defaulting to the real one: a test drives it over
a temporary directory, never the deployment's.
"""

import os
import shutil
import time

from . import build as build_mod
from . import layout

# The newest builds kept when the caller does not say.  The number is the old
# tree's policy value (`kcilib/core/policy.py: downloads_keep = 5`) and it is
# unchanged on purpose: the size of a fetch, the cadence of the loop and the
# operator's own `python3 prune.py --help` all still describe 5.
DEFAULT_KEEP = 5


def entries(downloads):
    """`[(mtime, name, path, size)]` for the build directories, newest first.

    A file (not a directory) is ignored, and an unreadable file inside a build
    counts as 0 bytes rather than failing the whole listing: a prune must not be
    stopped by one protected or vanished file.
    """
    found = []
    if not os.path.isdir(downloads):
        return found
    for name in sorted(os.listdir(downloads)):
        path = os.path.join(downloads, name)
        if not os.path.isdir(path):
            continue
        size = 0
        for root, _dirs, files in os.walk(path):
            for filename in files:
                try:
                    size += os.path.getsize(os.path.join(root, filename))
                except OSError:
                    pass
        found.append((os.path.getmtime(path), name, path, size))
    found.sort(reverse=True)
    return found


def plan(downloads=None, keep=DEFAULT_KEEP, served=None):
    """The retention decision as data: `(lines_to_print, [(path, size)] to remove)`.

    *lines* are what `prune()` prints, in order.  Every row says why it is kept -
    the operator reading a prune is asking exactly that, and a table of names with
    no reason is the one shape this must not have.

    *served* is the record `publish_local()` wrote (`lib/build.py: served()`);
    `{}` means this deployment serves nothing yet, and then nothing is protected
    by provenance.
    """
    downloads = downloads or layout.downloads()
    if not os.path.isdir(downloads):
        return [f"nothing to prune: {downloads} does not exist"], []
    served = served if served is not None else build_mod.served()
    served_id = str(served.get("build_id") or "")
    rows = entries(downloads)
    newest = {name for _m, name, _p, _s in rows[:max(int(keep), 0)]}
    lines = [
        f"{downloads}: {len(rows)} build(s); keeping the newest {keep}"
        + (f" and the served build ({served_id})" if served_id else "")
    ]
    # A served image nobody recorded is the one state this must not guess about:
    # `var/serve/Image` exists, so this deployment serves *something*, but no
    # record says which build's bytes they are (published before
    # `lib/build.py`'s `_remember_served()` existed, or the record was removed).
    # Protecting nothing silently would let a prune delete the very build the
    # stack seeds from; refusing to prune would be a worse answer.  Said out loud,
    # the operator can re-publish (which records it) or name the build himself.
    if not served_id and os.path.isfile(layout.serve("Image")):
        lines.append(
            f"  ! {layout.serve('Image')} exists but no {layout.state('served.json')} "
            "names its build - nothing is protected by provenance; re-run provision "
            "to record it")
    removals = []
    for mtime, name, path, size in rows:
        if name in newest:
            why = "keep: newest"
        elif served_id and name == served_id:
            why = "keep: the build var/state/served.json names and var/serve/Image serves"
        else:
            why = "PRUNE"
            removals.append((path, size))
        lines.append(f"  {name}  {size / 1e6:8.1f} MB  "
                     f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))}  {why}")
    return lines, removals


def prune(downloads=None, keep=DEFAULT_KEEP, served=None, dry=False,
          remove=shutil.rmtree, out=print):
    """Print the retention table and apply it; returns the number of builds removed.

    *dry* prints the same table and removes nothing.  *remove* and *out* are
    parameters so a test can drive both faces of this without deleting anything or
    capturing stdout - the old tree's module took the same two, and for the same
    reason: this is the one deleting path, and a test has to be able to reach it.
    """
    downloads = downloads or layout.downloads()
    lines, removals = plan(downloads, keep, served)
    for line in lines:
        out(line)
    if not os.path.isdir(downloads):
        return 0
    freed = sum(size for _path, size in removals)
    if not dry:
        for path, _size in removals:
            remove(path)
    out(("would remove" if dry else "removed")
        + f" {len(removals)} build(s), {freed / 1e6:.1f} MB"
        + (" (dry run: nothing was deleted)" if dry else ""))
    return len(removals)
