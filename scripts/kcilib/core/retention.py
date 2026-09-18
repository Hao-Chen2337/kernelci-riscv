# SPDX-License-Identifier: LGPL-2.1-or-later
#
r"""Retention for work/downloads/: which fetched builds ./run.sh prune keeps.

Each fetched build is ~45 MB and a daily fetch loop is ~16 GB a year, so the
directory is bounded: the newest KEEP builds, plus the one build this deployment
actually serves (work/env/build.env records it, and work/serve/Image serves it -
pruning that build breaks the next `./run.sh stack --seed`).  Everything else is
removed.  `./run.sh fetch --provision-only` and the stack write both files, so
this module reads the same two records they do: build.env's KCI_BUILD_COMMIT/
KCI_BUILD_DIR and each directory's node.json.

WHY IT IS NOT IN run.sh ANY MORE.  This was 76 lines of Python inside a heredoc
in run.sh, and it is the only path that deletes a user's OWN retained data -
work/downloads/, ~45 MB per build, the thing ./run.sh fetch worked to obtain.
(jobrun.py and fetch-and-run-latest.py also rmtree, but only a per-job temp
workspace they created themselves; that is cleanup, not retention.)  The guard suite imports kcilib and nothing
else, so no check could reach it - the retention rule was simultaneously the most
destructive and the only completely untested thing here.  run.sh keeps what is
its own: the flags, their validation and the decision to call this at all.

The decision and the deletion are separated on purpose: plan() returns the list
prune() deletes, so a --dry-run and a real run cannot disagree about which build
is which (they used to be the same `if` in one loop, and this keeps them one).

    python3 -m kcilib.core.retention --downloads DIR [--keep N] \
        [--build-env FILE] [--dry-run]
"""

import argparse
import json
import os
import re
import shutil
import sys
import time

# The newest builds kept when the caller does not say.  run.sh's --keep is the
# caller-facing spelling and must stay >= 1: the newest build is the one a local
# stack serves.
DEFAULT_KEEP = 5


def served_build(build_env):
    """(commit, build directory name) of the build work/env/build.env records.

    Both halves come from the file ./run.sh provision wrote, and either can be
    empty (no build provisioned yet, or a hand-edited file): an empty answer
    means "no build is protected by provenance", never an exception.
    """
    commit = build_dir_id = ""
    if not build_env or not os.path.exists(build_env):
        return commit, build_dir_id
    with open(build_env) as handle:
        text = handle.read()
    match = re.search(r"^KCI_BUILD_COMMIT=(\S+)", text, re.MULTILINE)
    commit = match.group(1) if match else ""
    match = re.search(r"^KCI_BUILD_DIR=(\S+)", text, re.MULTILINE)
    build_dir_id = os.path.basename(match.group(1)) if match else ""
    return commit, build_dir_id


def recorded_commit(path):
    """Commit of the kbuild the directory was downloaded from (node.json)."""
    try:
        with open(os.path.join(path, "node.json")) as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return ""
        revision = (data.get("data") or {})
        if not isinstance(revision, dict):
            return ""
        revision = revision.get("kernel_revision") or {}
        if not isinstance(revision, dict):
            return ""
        return revision.get("commit") or ""
    except (OSError, ValueError):
        return ""


def download_entries(downloads):
    """[(mtime, name, path, size)] for the build directories, newest first.

    A file (not a directory) is ignored, and an unreadable file inside a build
    counts as 0 bytes rather than failing the whole listing: a prune must not be
    stopped by one protected or vanished file.
    """
    entries = []
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
        entries.append((os.path.getmtime(path), name, path, size))
    entries.sort(reverse=True)
    return entries


def plan(downloads, keep=DEFAULT_KEEP, build_env=""):
    """The retention decision as data: (lines_to_print, [(path, size)] to remove).

    *lines* are exactly what prune() prints, in order; the removals are the rows
    the same pass marked PRUNE, so the dry run and the real run share one
    decision instead of two that can drift.
    """
    if not os.path.isdir(downloads):
        return [f"nothing to prune: {downloads} does not exist"], []
    commit, build_dir_id = served_build(build_env)
    entries = download_entries(downloads)
    newest = {name for _m, name, _p, _s in entries[:keep]}
    lines = [
        f"work/downloads: {len(entries)} build(s); keeping the newest {keep}"
        + (f" and the build.env build ({commit[:12]})" if commit else "")
    ]
    to_remove = []
    for mtime, name, path, size in entries:
        if name in newest:
            why = "keep: newest"
        elif name == build_dir_id or (commit and recorded_commit(path) == commit):
            why = "keep: the build work/env/build.env records and work/serve/Image serves"
        else:
            why = "PRUNE"
            to_remove.append((path, size))
        lines.append(
            f"  {name}  {size / 1e6:8.1f} MB  "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))}  {why}"
        )
    return lines, to_remove


def prune(downloads, keep=DEFAULT_KEEP, build_env="", dry=False,
          remove=shutil.rmtree, out=print):
    """Print the retention table and apply it; returns the number of builds removed.

    *dry* prints the same table and removes nothing.  *remove* and *out* are
    parameters so a test can drive both faces of this without deleting anything
    or capturing stdout.
    """
    lines, to_remove = plan(downloads, keep, build_env)
    for line in lines:
        out(line)
    if not os.path.isdir(downloads):
        return 0
    freed = sum(size for _path, size in to_remove)
    if not dry:
        for path, _size in to_remove:
            remove(path)
    out(
        ("would remove" if dry else "removed")
        + f" {len(to_remove)} build(s), {freed / 1e6:.1f} MB"
        + (" (dry run: nothing was deleted)" if dry else "")
    )
    return len(to_remove)


def main(argv=None):
    """The command line run.sh prune calls (flags only; run.sh validates them).

    The output is the contract: ./run.sh prune's own help text and the notes in
    docs/code-notes/W2b-entrypoints.md describe these lines.
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m kcilib.core.retention",
        description="Keep the newest fetched builds and the one this "
                    "deployment serves; remove the rest.",
    )
    parser.add_argument("--downloads", required=True,
                        help="the work/downloads directory to prune")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help=f"newest builds to keep (default {DEFAULT_KEEP})")
    parser.add_argument("--build-env", default="",
                        help="work/env/build.env: the build this deployment "
                             "serves is never pruned")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the decision, delete nothing")
    args = parser.parse_args(argv)
    if args.keep < 1:
        raise SystemExit(
            "prune: --keep must be at least 1 - the newest build is the one "
            "./run.sh stack --seed serves")
    prune(args.downloads, keep=args.keep, build_env=args.build_env,
          dry=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
