"""The poll loop: the node re-check, the cursor, the seen set, the batch flush."""
import os
import tempfile

import requests
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


def test_job_definition_failure_is_transient():
    """A job-definition fetch that fails must be RETRIED, never marked seen.

    The node-state re-check has been guarded since #11; the job-definition fetch
    one line later has not, and it is the same hazard with a worse ending:
    handle_event converts requests.exceptions.RequestException into "retry next
    poll", but its last `except Exception` returns True - which the loop reads as
    "handled" and marks the node seen.  So anything else raised here (a stale
    redirect, an HTML error page, a JSON body of the wrong shape, or an
    api.APIError, which is a RuntimeError) makes the node vanish: no result is
    ever posted and the node is never retried.  The three shapes the API has
    produced on this path must all arrive as RequestException.
    """
    from kcilib import api

    with tempfile.TemporaryDirectory() as tmp:
        poll_config = _poll_config(os.path.join(tmp, "state.json"))
        url = "http://x/jobdef"
        event = {"node": {"id": "node-1", "artifacts": {
            "job_definition": url}},
            "data": {"data": {"platform": "qemu-riscv64"}}}
        available = _Response(200, json_body={"state": "available"})

        def node_answers(jobdef):
            def get(target, **_kwargs):
                return available if target.endswith("/node/node-1") else jobdef
            return get

        for name, jobdef in (
                ("a 502 error page",
                 _Response(502, json_error=ValueError("Expecting value"))),
                # A 200 carrying an HTML body: raise_for_status() cannot catch
                # this one, the parse is the only thing that fails, and that is
                # the branch a later "tidy-up" is most likely to simplify into a
                # plain ValueError.
                ("an HTML body behind a 200",
                 _Response(200, json_error=ValueError("Expecting value"))),
                ("a redirect", _Response(302, json_body={})),
                ("a JSON body of the wrong shape",
                 _Response(200, json_body=["not", "an", "object"])),
        ):
            with stub_requests(poll, get=node_answers(jobdef)):
                accepted = False
                try:
                    poll.retrieve_job_definition(url)
                    accepted = True
                except requests.exceptions.RequestException:
                    pass  # what handle_event converts into "retry"
                except Exception as error:  # noqa: BLE001 - report the type
                    # check() rather than a bare raise: the AssertionError for the
                    # "accepted" case below would otherwise be caught by this same
                    # except and re-wrapped, making the failure message claim the
                    # opposite of what happened.
                    check(False,
                          f"{name} raised {type(error).__name__}, which "
                          "handle_event does not treat as transient - the node "
                          f"would be marked seen with its result never posted "
                          f"({error})")
                check(not accepted,
                      f"{name} was accepted as a job definition")
                handled = poll.handle_event(event, poll_config,
                                            config.RunConfig(), {},
                                            jobrun.run_node)
            check(handled is False,
                  f"{name} must leave the node available for the next poll, "
                  "not handled")

        # api.APIError is the other type this path must never leak: it is a
        # RuntimeError, so handle_event would mark the node seen.  Pinned by
        # checking the class hierarchy, not by driving kcilib.api itself.
        check(issubclass(api.APIError, RuntimeError)
              and not issubclass(api.APIError,
                                 requests.exceptions.RequestException),
              "api.APIError stopped being an uncaught-by-handle_event type; "
              "this guard's premise changed")
    print("test_job_definition_failure_is_transient OK")


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
