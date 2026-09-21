# SPDX-License-Identifier: LGPL-2.1-or-later
"""One atomic write: a file is written beside itself, then renamed over itself.

Seven call sites in this tree wrote the same two steps by hand - the body into
`<path>.tmp`, then `os.replace` - and it is not a pattern worth keeping seven
copies of.  A reader must never open a file that is halfway written, and the way
that stays true is that there is exactly one place that writes.

**What this deliberately does not do.**  It does not create the parent
directory: every caller did that itself, some once around several writes and one
(`Run.save()`) not at all, so doing it here would quietly turn a missing
directory from a failure into a directory.  It does not choose the dump's shape
either: `indent`, `sort_keys` and the rest differ per site and are passed
through, never normalised.  `fsync` differs too - `lib/run.py` rewrites a
`run.json` on every state change and does not sync it, while the ledger, the
served record, the build table, the poller's state and the config cache all do -
so the default is to sync, and that one caller says `fsync=False`.
"""

import json
import os

from . import errors


class DiskError(errors.InfraError, OSError):
    """The filesystem refused an I/O this tree needed: exit 3, a named path, no traceback.

    The two writers below let the `OSError` out as itself, so a read-only workspace,
    a `chmod 000` directory or a full disk reached the entry point as a traceback
    carrying the interpreter's exit 1 - the code this tree reserves for "a test
    failed" (`lib/errors.py`) - and a write that never happened was reported as a
    test result: `table.py pull` in a read-only workspace said exactly that.
    `retention.py` raises this too, for a directory it cannot list and a build it
    cannot remove.  The message is `drift.py:_read()`'s spelling: the path that
    could not be written, then the OS's own reason.

    **An `OSError` as well as an `InfraError`, deliberately.**  Four callers catch
    `OSError` around these writers and mean something by it: `drift.py`'s
    `_keep_config` swallows it ("a cache that cannot be written is not a failure"),
    `sink.py`'s `Ledger.deliver` turns it into `NOT recorded: <why>`, and
    `build/model.py` and `build/publish.py` re-raise it as the `ArtifactError` that
    names the build.  A type those four no longer match would turn a cache miss into
    a failed drift and a record that explains itself into a crash - so this is both,
    and the repair reaches exactly the callers that had no handler at all.
    """


def write_json(path, data, *, fsync=True, **dump_kwargs):
    """`data` written as JSON at `path`, atomically: `<path>.tmp`, then renamed over it.

    `**dump_kwargs` are `json.dump`'s own - the caller's `indent`, `sort_keys`
    and anything else it named.

    A write the filesystem refuses is a `DiskError`, never a bare `OSError`.
    """
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, **dump_kwargs)
            _settle(handle, fsync)
        os.replace(tmp, path)
    except OSError as error:
        raise DiskError(f"cannot write {path}: {error}") from error


def write_text(path, text, *, encoding="utf-8", fsync=True):
    """`text` written at `path`, atomically, in `encoding` - a record's JSON, or a kept file.

    A write the filesystem refuses is a `DiskError`, never a bare `OSError`.
    """
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding=encoding) as handle:
            handle.write(text)
            _settle(handle, fsync)
        os.replace(tmp, path)
    except OSError as error:
        raise DiskError(f"cannot write {path}: {error}") from error


def _settle(handle, fsync):
    """Get the bytes out of the process; with `fsync`, also onto the disk."""
    handle.flush()
    if fsync:
        os.fsync(handle.fileno())
