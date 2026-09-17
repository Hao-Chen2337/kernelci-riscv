# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Persisted worker state: poll cursor, seen node ids, unposted results.

The RISC-V pull-lab worker has to survive a restart in the middle of a batch
without re-running a job whose result it already holds:

* the cursor says where the next poll resumes scanning (it is authoritative -
  `--since` only seeds a state file that has no cursor yet),
* `seen` says which nodes already ran, so a late event for one of them is
  re-posted, never re-run,
* `pending` holds a LAVA callback body whose POST failed transiently, so
  the next start can post it again without re-running tuxrun.

Those three fields are a contract, not an implementation detail: operators
hand-edit the file and an older worker must read a file a newer one wrote, so
the shape is exactly the one the worker has always written::

    {
      "timestamp": "2026-09-15T16:08:08.858000",   // cursor, or null
      "seen": ["6aa8f22af456c71d47ca435d", ...],   // oldest first
      "pending": {"<node id>": {"callback": "<url>", "body": {...}}}
    }

The callback *token* is deliberately not part of that shape: it is read from
the environment when the body is posted and is never written to disk.

The file is written through a temporary file and a rename, so a worker killed
while saving leaves the previous state behind rather than a half-written one -
the pending result that survives a crash is the whole point of the file.
"""

import json
import os

# Seen-node ids kept in the state file, evicted oldest first.  Sized far
# beyond what one re-scan window (CURSOR_OVERLAP_S) can produce, so eviction
# can never re-expose a recently processed node to a re-run.  Read at call
# time rather than captured per instance, so a test can shrink it.
SEEN_LIMIT = 20000

# The fields this module owns, in the order they are written.  Anything else
# found in a state file is carried through untouched (see _extra).
STATE_FIELDS = ("timestamp", "seen", "pending")


def _empty_state():
    """The state of a worker that has never run - and of an unreadable file.

    A state file that cannot be parsed must not kill the worker far away from
    the file that caused it, and it must not be trusted either, so callers get
    this same empty state either way; load() says which one happened."""
    return {"timestamp": None, "seen": [], "pending": {}}


class StateFile:
    """The worker's cursor, seen set and unposted results on disk.

    ::

        state = StateFile(path)          # path=None: nothing is persisted
        state.load()                     # missing/corrupt file -> empty state
        state.cursor, state.seen, state.pending
        state.mark_seen(node_id)         # dedup, evicting past SEEN_LIMIT
        state.add_pending(node_id, callback, body)
        state.pop_pending(node_id)       # the entry, or None
        state.save()                     # atomic; no-op when nothing changed

    `seen` is the on-disk list (oldest first, duplicates impossible) and is
    what a caller reads and writes; `has_seen()` is the membership test that
    stays cheap once the list is at SEEN_LIMIT.  `pending` maps a node id to
    the stored `{"callback": ..., "body": ...}` dict, so a caller rebuilds the
    (callback, token, body) tuple it posts with the token from the environment."""

    def __init__(self, path):
        self.path = path
        self.cursor = None
        self.seen = []
        # Accelerator for has_seen(): the worker tests every event of every
        # poll against up to SEEN_LIMIT ids.  It is rebuilt whenever it
        # disagrees with the list, so a caller that appends to .seen directly
        # cannot silently desynchronise it.
        self._seen_set = set()
        self.pending = {}
        self._extra = {}
        # Bytes of the last document this object wrote, and the re-entrancy
        # flag: a signal handler saving while a save is in progress must not
        # write the same temporary file twice.
        self._written = None
        self._saving = False

    def load(self):
        """Read the file into this object and return it.

        A file that does not exist yet is simply an empty state (the first run
        of a fresh worker, no warning).  A file that exists but is corrupt or
        of an unexpected shape is refused loudly - it is the state that keeps
        a restarted worker from re-running jobs - and replaced in memory by an
        empty state, never trusted."""
        self._reset()
        if not self.path or not os.path.exists(self.path):
            return self
        try:
            with open(self.path) as handle:
                state = json.load(handle)
            if (
                not isinstance(state, dict)
                or not isinstance(state.get("seen"), list)
                or not isinstance(state.get("pending", {}), dict)
                or (
                    state.get("timestamp") is not None
                    and not isinstance(state.get("timestamp"), str)
                )
            ):
                raise ValueError("state file has unexpected shape")
        except (ValueError, OSError):
            print(f"Warning: state file {self.path} unreadable; starting fresh")
            return self
        self.cursor = state.get("timestamp")
        self.seen = list(state.get("seen", []))
        self._seen_set = set(self.seen)
        self.pending = dict(state.get("pending") or {})
        # Keys this module does not own are kept: the worker used to rewrite
        # the very dict it had read, and dropping a field an operator or a
        # newer worker put there would lose it silently.
        self._extra = {
            key: value for key, value in state.items() if key not in STATE_FIELDS
        }
        # The next save() must write: the file on disk may be hand-formatted,
        # and the worker's first flush after a load has always written.
        self._written = None
        return self

    def save(self):
        """Write the state out atomically; True when the file was written.

        Called after EVERY event, not once per batch (#9): a worker killed
        after a transient callback failure but before the batch ended used to
        lose the report, the pending entry and the seen update, so the next
        start re-ran tuxrun for a node whose result it already had - exactly
        what the "re-posted, never re-run" contract promises not to do.  It is
        also called from the SIGTERM/SIGINT handler, hence the re-entrancy
        guard.

        The other guard keeps that honest rather than expensive: a batch of a
        thousand events with nothing new to record must not rewrite a state
        file that can carry up to SEEN_LIMIT node ids a thousand times.  The
        comparison is on the document that would be written, so an eviction at
        SEEN_LIMIT - same length, different ids - is not mistaken for "nothing
        changed" and silently left unwritten."""
        if not self.path or self._saving:
            return False
        payload = json.dumps(self._document())
        if payload == self._written:
            return False
        self._saving = True
        try:
            tmp_path = f"{self.path}.tmp"
            with open(tmp_path, "w") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
            self._written = payload
        finally:
            self._saving = False
        return True

    def mark_seen(self, node_id):
        """Record *node_id* as processed; True when it was not there already.

        Only a node that was actually processed belongs here: the first event
        for a node may arrive before its job_definition artifact is attached,
        and marking such an event seen would hide the later, complete one."""
        if len(self._seen_set) != len(self.seen):
            # A caller mutated .seen itself; resynchronise before deciding.
            self._seen_set = set(self.seen)
        if node_id in self._seen_set:
            return False
        self.seen.append(node_id)
        self._seen_set.add(node_id)
        while len(self.seen) > SEEN_LIMIT:
            self._seen_set.discard(self.seen.pop(0))
        return True

    def has_seen(self, node_id):
        """Whether *node_id* was already processed (the dedup test)."""
        if len(self._seen_set) != len(self.seen):
            self._seen_set = set(self.seen)
        return node_id in self._seen_set

    def add_pending(self, node_id, callback, body):
        """Remember a result body whose callback POST did not go through.

        The body is stored exactly as it will be posted, so a later run can
        re-post it without re-running the job that produced it."""
        self.pending[node_id] = {"callback": callback, "body": body}

    def pop_pending(self, node_id):
        """Forget and return the pending entry for *node_id*, or None.

        Called once the body is posted, or once the callback failed
        permanently: a node must never keep a body it can no longer post."""
        return self.pending.pop(node_id, None)

    def _reset(self):
        """Back to the empty state, keeping only the accelerator consistent."""
        empty = _empty_state()
        self.cursor = empty["timestamp"]
        self.seen = empty["seen"]
        self._seen_set = set()
        self.pending = empty["pending"]
        self._extra = {}
        self._written = None

    def _document(self):
        """The JSON document, in the key order existing state files use."""
        document = {
            "timestamp": self.cursor,
            "seen": list(self.seen),
            "pending": dict(self.pending),
        }
        document.update(self._extra)
        return document
