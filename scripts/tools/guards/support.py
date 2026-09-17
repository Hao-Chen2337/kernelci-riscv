"""The helpers every guard module shares: the check, the stubs, the fixtures.

check() is not an assert, so python3 -O cannot turn the gate into a false green.
Rationale: docs/code-notes/W2d-tools.md.
"""
import os
import sys
import time as _time
from contextlib import contextmanager

import requests as _real_requests
from kcilib.core import config, params
from kcilib.core.state import StateFile
from kcilib.run import jobrun

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/tools


def check(condition, message):
    """A guard that also holds under `python3 -O` / PYTHONOPTIMIZE=1.

    These used to be `assert`s, and -O strips those: a broken check exited 0,
    so the gate reported success precisely when it had verified nothing.
    """
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


class _Response:
    """Minimal stand-in for a requests response (see stub_requests)."""

    def __init__(self, status_code=200, headers=None, chunks=(),
                 json_body=None, json_error=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.is_redirect = status_code in (301, 302, 303, 307, 308)
        self.is_permanent_redirect = status_code in (301, 308)
        self._chunks = list(chunks)
        self._json_body = json_body
        self._json_error = json_error

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _real_requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1 << 20):
        yield from self._chunks

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_body


class _RequestsStub:
    """Replaces a module's requests: get/post stubbed, exception classes real
    so the module's except clauses still match."""

    def __init__(self, get=None, post=None):
        self.exceptions = _real_requests.exceptions
        self._get = get
        self._post = post

    def get(self, url, **kwargs):
        if self._get is None:
            raise AssertionError(f"unexpected GET {url}")
        return self._get(url, **kwargs)

    def post(self, url, **kwargs):
        if self._post is None:
            raise AssertionError(f"unexpected POST {url}")
        return self._post(url, **kwargs)


@contextmanager
def stub_requests(module, get=None, post=None):
    """Replace the `requests` of the module that OWNS the call.

    That module-level name is what the code resolves - kcilib.run.callback for
    the result POST, kcilib.run.artifacts for a transfer, kcilib.run.poll for
    the node-state GET - so stubbing the worker's would not be seen at all.
    """
    real = module.requests
    module.requests = _RequestsStub(get, post)
    try:
        yield
    finally:
        module.requests = real


@contextmanager
def no_sleep():
    """The code under test retries with time.sleep; a test must not wait."""
    real = _time.sleep
    _time.sleep = lambda _seconds: None
    try:
        yield
    finally:
        _time.sleep = real


def read_state(path):
    """The state file's three documented fields, as the operators read them.

    kcilib.core.state.StateFile owns the file; this is the guards' own view of
    the {timestamp, seen, pending} document it writes.
    """
    state = StateFile(path).load()
    return {
        "timestamp": state.cursor,
        "seen": list(state.seen),
        "pending": dict(state.pending),
    }


def write_state(path, document):
    """Write a state document through kcilib.core.state.StateFile (atomic rename)."""
    state = StateFile(path)
    state.cursor = document.get("timestamp")
    state.seen = list(document.get("seen", []))
    state.pending = dict(document.get("pending") or {})
    state.save()


def _run_job_config(tmp):
    """Every field run_node()/handle_event() read off the run config."""
    return config.RunConfig(
        platform="qemu-riscv64",
        output_dir=os.path.join(tmp, "out"), keep_workspace=False,
        log_dir=os.path.join(tmp, "logs"), tuxrun_bin="tuxrun",
        cpu="rv64", container_runtime="", kvm_tests=params.KVM_TEST_SUBSET,
        max_download_size=(1 << 20), api_config_name="docker-host",
        storage_config_name="docker-host", kvm_full=False, rootfs="",
        max_timeout=1200, min_timeout=jobrun.MIN_TIMEOUT,
    )


def _poll_config(state_file, **over):
    """Every field poll_loop()/handle_event() read off the poll config."""
    fields = {
        "api_url": "http://api", "platform": None, "runtime": None,
        "state_file": state_file, "since": None, "once": True,
        "poll_period": 0, "max_retries": 1, "ignore_state_cursor": False,
    }
    fields.update(over)
    return config.PollConfig(**fields)


class _FakeSession:
    """A stand-in for requests.Session, INJECTED onto the client.

    kcilib/api.py resolves self.session at call time, so replacing that one
    attribute is the seam: no request leaves the machine, and the kwargs the
    client passes - allow_redirects above all - stay observable.
    """

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs)


def _api_client(handler, base="http://x:8001", **kwargs):
    """A KernelCI whose session answers *handler* and records the calls."""
    from kcilib.api import KernelCI

    client = KernelCI(base, **kwargs)
    client.session = _FakeSession(handler)
    return client
