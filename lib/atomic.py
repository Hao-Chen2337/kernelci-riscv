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


def write_json(path, data, *, fsync=True, **dump_kwargs):
    """`data` written as JSON at `path`, atomically: `<path>.tmp`, then renamed over it.

    `**dump_kwargs` are `json.dump`'s own - the caller's `indent`, `sort_keys`
    and anything else it named.
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, **dump_kwargs)
        _settle(handle, fsync)
    os.replace(tmp, path)


def write_text(path, text, *, encoding="utf-8", fsync=True):
    """`text` written at `path`, atomically, in `encoding` - a record's JSON, or a kept file."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding=encoding) as handle:
        handle.write(text)
        _settle(handle, fsync)
    os.replace(tmp, path)


def _settle(handle, fsync):
    """Get the bytes out of the process; with `fsync`, also onto the disk."""
    handle.flush()
    if fsync:
        os.fsync(handle.fileno())
