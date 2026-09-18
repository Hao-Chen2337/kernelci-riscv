# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Persisted worker state: poll cursor, seen node ids, unposted results.

A restart must not re-run a job whose result is already held, so the cursor is
authoritative (--since only seeds a file that has none), `seen` makes a late
event re-post rather than re-run, and `pending` holds a callback body whose
POST failed.  The shape is a contract - operators hand-edit the file and an
older worker reads what a newer one wrote::

    {
      "timestamp": "2026-09-15T16:08:08.858000",   // cursor, or null
      "seen": ["6aa8f22af456c71d47ca435d", ...],   // oldest first
      "pending": {"<node id>": {"callback": "<url>", "body": {...}}}
    }

The callback token is deliberately not in it (read from the environment when
the body is posted), and the file is written through a temp file and a rename,
so a worker killed while saving leaves the previous state behind.
Rationale: docs/code-notes/W2c-kcilib.md.
"""

import json
import os

# Seen-node ids kept, evicted oldest first, sized far beyond what one re-scan
# window (CURSOR_OVERLAP_S) can produce.  Read at call time so a test can shrink
# it.
SEEN_LIMIT = 20000

# The fields this module owns; anything else is carried through (see _extra).
STATE_FIELDS = ("timestamp", "seen", "pending")


def _empty_state():
    """The state of a worker that has never run - and of an unreadable file.

    An unparseable file must not kill the worker and must not be trusted, so
    callers get this empty state either way; load() says which one happened."""
    return {"timestamp": None, "seen": [], "pending": {}}


class StateFile:
    """The worker's cursor, seen set and unposted results on disk.

    ::

        state = StateFile(path)          # path=None: nothing is persisted
        state.load()                     # missing/corrupt file -> empty state
        state.cursor, state.seen, state.pending
        state.mark_seen(node_id)         # dedup, evicting past SEEN_LIMIT
        state.save()                     # atomic; no-op when nothing changed

    `seen` is the on-disk list (oldest first) and is what a caller reads and
    writes; `pending` maps a node id to `{"callback": ..., "body": ...}`, so a
    caller rebuilds the tuple it posts with the token from the environment."""

    def __init__(self, path):
        self.path = path
        self.cursor = None
        self.seen = []
        # Accelerator for has_seen(), rebuilt whenever it disagrees with the
        # list, so a caller appending to .seen directly cannot desync it.
        self._seen_set = set()
        self.pending = {}
        self._extra = {}
        # Bytes of the last document written, and the re-entrancy flag: a signal
        # handler must not write the same temporary file twice.
        self._written = None
        self._saving = False

    def load(self):
        """Read the file into this object and return it.

        A missing file is an empty state, no warning.  A corrupt or wrong-shaped
        one is refused loudly and replaced in memory by an empty state, never
        trusted."""
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
        # Keys this module does not own are kept: dropping a field an operator
        # or a newer worker put there would lose it silently.
        self._extra = {
            key: value for key, value in state.items() if key not in STATE_FIELDS
        }
        # The next save() must write: the file on disk may be hand-formatted.
        self._written = None
        return self

    def save(self):
        """Write the state out atomically; True when the file was written.

        Called after EVERY event, not once per batch - and from the SIGTERM/
        SIGINT handler, hence the re-entrancy guard.  A worker killed after a
        transient callback failure used to lose the report and re-run tuxrun for
        a node whose result it already had.  The write is skipped only when the
        document is unchanged, so an eviction at SEEN_LIMIT (same length,
        different ids) is not mistaken for "nothing changed"."""
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

        Only a node that was actually processed belongs here: marking an
        incomplete first event seen would hide the later, complete one."""
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
