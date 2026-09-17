"""The state file, the cursor rule and the bounded seen set."""
import json
import os
import tempfile

from kcilib.core import config
from kcilib.core.state import SEEN_LIMIT
from kcilib.run import jobrun, poll

from .support import _poll_config, check, read_state, write_state


def test_state_roundtrip():
    """kcilib.core.state.StateFile: what the pending set survives on."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "state.json")
        empty = read_state(path)
        check(empty == {"timestamp": None, "seen": [], "pending": {}}, empty)
        state = {
            "timestamp": "2026-09-08T00:00:00.000000",
            "seen": ["a" * 24],
            "pending": {"b" * 24: {"callback": "http://cb",
                                   "body": {"status": 2}}},
        }
        write_state(path, state)
        check(read_state(path) == state, "state did not survive a round trip")
        with open(path, "w") as handle:
            handle.write("{ not json")
        check(read_state(path)["timestamp"] is None,
              "a corrupt state file must be refused, not trusted")
        with open(path, "w") as handle:
            json.dump({"seen": "not-a-list"}, handle)
        check(read_state(path)["seen"] == [],
              "a state file of the wrong shape must be refused")
    print("test_state_roundtrip OK")


def test_start_cursor():
    """#8: the persisted cursor is authoritative, --since is a bootstrap."""
    stored = "2026-09-08T00:00:00.000000"
    since = "2020-01-01T00:00:00"
    check(poll.start_cursor(stored, since, False) == stored,
          "the persisted cursor must win over --since")
    check(poll.start_cursor(stored, since, True) == since,
          "--ignore-state-cursor must force --since")
    check(poll.start_cursor(stored, None, True) == stored,
          "--ignore-state-cursor without --since must fall back to the cursor")
    check(poll.start_cursor(None, since, False) == since,
          "--since seeds a state file that has no cursor")
    check(poll.start_cursor(None, None, False) == "1970-01-01T00:00:00.000000",
          "no cursor anywhere must scan the whole available queue")
    check(poll.start_cursor("not-a-timestamp", since, False) == since,
          "an unparseable stored cursor must be refused, not handed to "
          "iso_ago (that ValueError used to kill the worker at startup)")
    check(poll.start_cursor(None, "not-a-timestamp", False)
          == "1970-01-01T00:00:00.000000",
          "an unparseable --since must be refused too")
    print("test_start_cursor OK")


def test_seen_eviction():
    """#25: the seen set stays bounded - the oldest id is evicted."""
    limit = SEEN_LIMIT
    new_id = "f" * 24
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        old = [f"{i:024x}" for i in range(limit)]
        check(new_id not in old, "the test's new node id collides with an old one")
        write_state(state_file, {"timestamp": "2026-09-08T00:00:00.000000",
                                 "seen": old, "pending": {}})
        poll_config = _poll_config(state_file)
        events = [{"node": {"id": new_id,
                            "artifacts": {"job_definition": "http://x/job"}},
                   "timestamp": "2026-09-08T00:00:00.000000"}]
        real_fetch, real_handle = poll.fetch_nodes, poll.handle_event
        poll.fetch_nodes = lambda *_a, **_k: events
        poll.handle_event = lambda *_a, **_k: True
        try:
            poll.poll_loop(poll_config, jobrun.run_node, config.RunConfig())
        finally:
            poll.fetch_nodes, poll.handle_event = real_fetch, real_handle
        state = read_state(state_file)
        check(len(state["seen"]) == limit, len(state["seen"]))
        check(state["seen"][-1] == new_id, state["seen"][-1])
        check(old[0] not in state["seen"],
              "the oldest seen id must be the one evicted")
        check(old[1] in state["seen"], "eviction removed more than the oldest")
    print("test_seen_eviction OK")
