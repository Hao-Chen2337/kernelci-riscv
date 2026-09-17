"""The poll loop: the node re-check, the cursor, the seen set, the batch flush."""
import os
import tempfile

from kcilib.core import config
from kcilib.run import jobrun, poll

from .support import _poll_config, _Response, check, read_state, stub_requests


def test_iso_ago():
    ts = poll.iso_ago("2026-09-08T12:00:00.000000", 900)
    check(ts == "2026-09-08T11:45:00", ts)
    print("test_iso_ago OK")


def test_handle_event_non_json():
    """#11: an HTML error page from the API must not kill the whole worker."""
    poll_config = _poll_config("unused-state.json")
    event = {"node": {"id": "node-1", "artifacts": {}}}
    html_page = _Response(502, json_error=ValueError("Expecting value: line 1"))
    with stub_requests(poll, get=lambda url, **kw: html_page):
        handled = poll.handle_event(event, poll_config, config.RunConfig(), {},
                                    jobrun.run_node)
    check(handled is False,
          "a non-JSON node body must be retried, not handled and marked seen")
    with stub_requests(poll,
                       get=lambda url, **kw: _Response(200, json_body=["nope"])):
        check(poll.handle_event(event, poll_config, config.RunConfig(), {},
                                jobrun.run_node) is False,
              "a node body that is not an object must be retried too")
    print("test_handle_event_non_json OK")


def test_poll_loop_persists_cursor_and_seen():
    """#25: a handled node is marked seen and the cursor advances, persisted."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        poll_config = _poll_config(state_file)
        node_id = "a" * 24
        events = [{"node": {"id": node_id,
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
        check(state["seen"] == [node_id], f"the handled node was not marked "
                                          f"seen: {state}")
        check(state["timestamp"] == "2026-09-08T00:00:00.000000", state)
        check(state["pending"] == {}, state)
    print("test_poll_loop_persists_cursor_and_seen OK")
