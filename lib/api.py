# SPDX-License-Identifier: LGPL-2.1-or-later
"""The only HTTP that talks to KernelCI.

Four callers share it and all want the same three things: a `/latest` base,
paging that does not silently truncate, and "the API answered, but not with
JSON" as an ApiError instead of a `ValueError` that kills the caller.

接口形状（C++，只有声明）：include/kci/remote.hpp §4 API 客户端。
"""

import json
import os
import re
import threading
import time
from typing import Any

import requests

from .errors import ApiError

# The public API; a deployment overrides it with KCI_API_URL.
PRODUCTION = "https://api.kernelci.org"
LOCAL = "http://127.0.0.1:8001"
TIMEOUT = 60
# /nodes page size when the caller does not say, and the most a recursive
# /events read accepts (the API answers 400 above it).
PAGE = 200
EVENTS_PAGE_MAX = 1000
# The node kinds a summary counts, and the page size it counts them with.
COUNTED_KINDS = ("checkout", "kbuild", "job")
COUNT_LIMIT = 1000
# An object's repr, with the memory address a page has no use for: urllib3 puts
# one inside the text of a failed connection, and `/remote` prints that text.
OBJECT_REPR = re.compile(r"<[^<>]{0,80} at 0x[0-9a-fA-F]+>")

# How many times a read retries a connection error (the local API drops idle
# ones).  A write does not: a duplicated node is worse than a failure.
RETRIES = 3

# How long one API answer stays usable by a *later* request, and how many answers
# the process keeps.  Five seconds, because that is the page's own poll interval
# (`gui._JS` asks every 2s): within it the answer cannot have changed in a way a
# reader could have acted on, and the page prints the age of what it shows
# (`gui._refresh`) rather than passing a cached answer off as a fresh one.
# `?ttl=<seconds>` sets it per request and `?fresh=1` turns it off (`gui._ttl_of`).
#
# Only *API* reads are ever kept here.  The operator's own facts - `builds.json`,
# `var/results`, `var/runs`, `var/downloads`, `worker-state.json` - do not come
# through this module at all and stay per request, which is what "a refresh
# re-reads files" means (`docs/gui-rework/01-perf.md` §D2).
DEFAULT_TTL = 5
# The longest a request may ask for with `?ttl=`, and therefore the longest an entry
# is ever kept: what bounds the memory is `MAX_CACHE`, and what bounds the lie a
# cached answer could tell is this - the page prints the age either way (`gui._refresh`).
MAX_TTL = 300
MAX_CACHE = 32
# The body is read in pieces this size so the clock can end a stream the API is
# trickling (`_read`): 32 KB is one to two seconds of the 20-35 KB/s the production
# API streams at, so the deadline is noticed while it is happening, and a 175 KB
# page of builds is still only a handful of reads.
CHUNK = 32768
# The bounds one query may carry.  A window has to become a date the platform
# can print (`time.gmtime` refuses an epoch outside its range, and that OSError
# reached a page as an HTTP 500), and a row cap has to be a number the API is
# asked for.  `gui` builds its select boxes out of these same two: a box and
# a clamp that are written twice drift apart, and these did.
MAX_WINDOW_DAYS = 3650
MAX_ROWS = 1000

# What one *request* has already asked for, and what it may spend asking.
#
# This is the API layer's half of `gui._request_scratch()` and it is cleared the
# same way, at the start of every request: `protocol_version` is `HTTP/1.1`, so one
# keep-alive connection carries many requests on the *same* thread, and a memo that
# outlived its request would answer the next one with what the last one read.  It
# is deliberately not a field on `Api` either: `Gui._client()` builds a fresh client
# for every read of a page that switched base (`?api=`), so a memo kept on the
# instance would be empty exactly where the duplicate reads are.
_SCOPE = threading.local()
# What a scope is when no request has begun one: nothing to serve from and no
# deadline to keep, i.e. exactly the behaviour this module had before the scope
# existed.  A caller that is not a served request - a probe calling
# `Gui.render()` directly - therefore gets no cache and no deadline unless it says
# so itself with `begin_request()`.
_NO_SCOPE = {"memo": {}, "ttl": 0.0, "deadline": None, "budget": 0.0, "age": None}

# Answers, by `_key()`, with the monotonic time each was read.  Process-wide on
# purpose - this is the cache that makes a reload inside the TTL free, and four
# pages asking the identical question used to pay for it four times
# (`docs/gui-rework/01-perf.md` §F2.6).  Guarded by a lock because the console is
# threaded: two pages may store and evict at the same moment.
_CACHE: dict[tuple, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _scope() -> dict[str, Any]:
    """This thread's request scope, or a throwaway one when no request has begun.

    Only ever read through `begin_request()`, `read_age()` and `request_ttl()`; the
    one caller that reaches in is `Api._request`, which is where the reads are.

    **The no-request scope is not stored on the thread.**  It was, and that one
    line turned the memo from a per-*request* cache into a per-*thread* one: any
    long-lived process that never calls `begin_request()` - the resident worker,
    which polls for ever - got its first answer to a URL back on every later read,
    `ttl` of 0 notwithstanding.  That `ttl` only gates `_CACHE`; the `memo`
    short-circuit in `_request` is consulted before it and has no expiry at all.
    The damage was not hypothetical: `Poller._claim` re-reads a node precisely to
    find out whether it is *still* `available`, was told `available` for a node
    that had finished hours earlier, and so re-ran the whole job on every poll;
    and because the events URL carries a changing `from=`, the memo grew by an
    entry per poll on top of that.  A fresh dict per call is what the paragraph
    above `_NO_SCOPE` always promised - no cache - and what it now delivers.
    """
    found = getattr(_SCOPE, "scope", None)
    return found if found is not None else dict(_NO_SCOPE, memo={})


def begin_request(ttl: float | None = None, budget: float | None = None) -> dict[str, Any]:
    """Begin one request: an empty memo, this request's freshness, its deadline.

    Called at the top of every request the console serves (`gui.server.handler_for`'s
    `_route_get` and `_route_post`), because that is the only place that knows a new
    request has started - and the memo has to be empty for it, or a page would answer
    with what the *previous* request on the same keep-alive connection read.

    `ttl` is how long an answer read by an earlier request may be reused (`None` is
    `DEFAULT_TTL`, `0` is "do not").  `budget` is the wall-clock total this request
    may spend in the API, shared by *all* of its reads: one request, one deadline,
    so a page with four reads cannot cost four times what its source says it waits
    (`docs/gui-rework/01-perf.md` §F4b.2, where `/worker` promised 10s and took
    39.2s because the number was read as per call).
    """
    seconds = 0.0 if budget is None else max(0.0, float(budget))
    found = {"memo": {}, "age": None,
             "ttl": DEFAULT_TTL if ttl is None else max(0.0, float(ttl)),
             "budget": seconds,
             "deadline": time.monotonic() + seconds if seconds else None}
    _SCOPE.scope = found
    return found


def read_age() -> float | None:
    """The age of the oldest cached answer this request was served, `None` for none.

    A page prints it (`gui._refresh`).  An answer read from the cache and shown
    without its age is the page pretending it just asked, which is the one thing a
    cache here may not do (§D2).  *Oldest* and not newest: a page shows everything
    it read, and the stalest part of that is the honest number.
    """
    return _scope()["age"]


def request_ttl() -> float:
    """The freshness this request's API reads were given, in seconds.

    Read by the page that has to say so out loud: the refresh control's `title=`
    quotes it (`gui._refresh`).
    """
    return _scope()["ttl"]


def _key(base: str, method: str, url: str, params: Any) -> tuple:
    """One read's identity: the base it went to, the method, the URL, the query.

    The base is part of it because one console can read two APIs at once (`?api=`),
    and two of them answering the same path must not hand each other rows
    (§R5).  The token is not part of it: this process has one, and a key that held
    a bearer token would be a secret in a dictionary key.
    """
    return (base, method, url, json.dumps(params or {}, sort_keys=True, default=str))


def _cached(key: tuple, ttl: float):
    """`(response, age)` for a cached answer younger than `ttl`, else `None`."""
    if ttl <= 0:
        return None
    with _CACHE_LOCK:
        found = _CACHE.get(key)
    if found is None:
        return None
    age = time.monotonic() - found[0]
    if age >= ttl:
        return None                       # older than this request allows: ask again
    return found[1], age


def _remember(key: tuple, response: Any) -> None:
    """Keep one answer, evicting what is stale and then what is oldest.

    An entry is kept for `MAX_TTL` and not for `DEFAULT_TTL`, because the freshness
    a *reader* gets is decided at read time (`_cached(key, scope["ttl"])`): sweeping
    at the default would make `?ttl=<more>` unable to do what it says - a page that
    asked for 60s would find the answer its own previous read stored already thrown
    away by the next insert.  What is kept is bounded by `MAX_CACHE` either way, so
    the memory is a few dozen answers and never a leak.

    The response is kept and not the decoded body because every caller wants a
    different part of it (`json()` on a page, `.text` on a `.config`, `.content` in
    the harnesses), and it is safe to share: it was read to the end before it was
    stored (`_read`), so nothing about it is still a socket, and nothing mutates it.
    """
    now = time.monotonic()
    with _CACHE_LOCK:
        stale = [one for one, (at, _) in _CACHE.items() if now - at >= MAX_TTL]
        for one in stale:                 # a cache that grows is a leak, not a cache
            _CACHE.pop(one, None)
        while len(_CACHE) >= MAX_CACHE:
            _CACHE.pop(min(_CACHE, key=lambda one: _CACHE[one][0]), None)
        _CACHE[key] = (now, response)


class Api:
    """A KernelCI API client: reads page, writes do not."""

    def __init__(self, base="", token="", timeout=TIMEOUT):
        self.base = Api.url(base).rstrip("/")
        self.token = token or ""
        self.timeout = timeout
        self._session = requests.Session()
        # What the API said its own `total` was for the last `nodes()` read.  A
        # caller may quote this number; it may never compute one from what came
        # back, because what came back is what the cap allowed.
        self.last_total = None

    @staticmethod
    def url(explicit_url=""):
        """The API to talk to: the argument, else $KCI_API_URL, else the local stack."""
        return explicit_url or os.environ.get("KCI_API_URL") or LOCAL

    # --- the three verbs ---------------------------------------------------

    def get(self, path, params=None):
        """GET `path` (a full URL, or one under /latest) and decode JSON."""
        return self._decode(self._request("GET", path, params=params))

    def post(self, path, body, token=""):
        """POST `body` as JSON and require a 2xx; the one write this client has."""
        self._request("POST", path, body=body, token=token or self.token, retries=1)

    def text(self, url):
        """A plain-text artifact (a kernel `.config`) fetched by its full URL."""
        return self._request("GET", url).text

    # --- the node vocabulary -----------------------------------------------

    def nodes(self, kind="", filters=None, limit=None, offset=None, newest=True):
        """The matching nodes, in the API's own order, which is oldest first.

        `limit` is a cap on how many nodes come back - not a page size, which
        stays `PAGE`.  `limit=None` means "everything", which is what a caller that
        has to filter before it counts still gets.

        The API has no sort parameter (a `sort=` is read as an attribute filter and
        answers `total=0`), so with `newest` (the default) the *tail* is the part
        worth keeping: when the cap is smaller than the API's own `total`, the read
        starts at `total - limit` and costs a page or two instead of the whole
        answer.  That is what a page showing builds wants.

        `newest=False` keeps the *head* instead - the first `limit` nodes in the
        API's own order - which is what a reader of a queue wants: a worker claims
        the oldest claimable job, so the tail of four million of them is worth
        nothing.  This is not a detail: without it, one page load pages through the
        whole answer (production answers `kind=job` with 4.7 million nodes, so that
        is tens of thousands of requests and a page that never draws).

        An API that answers no `/count` is paginated once to learn its size, so the
        cap still takes the tail.  One that reports no `total` at all leaves
        nothing to jump to, and the cap then falls back to walking from the start.

        A page is never asked for more rows than the cap still wants: `PAGE` is 200
        and a page of this console shows 25-50 rows, so asking for the full page and
        slicing it is up to 4x the bytes, and the bytes are the cost (production
        streams `/nodes` at 20-35 KB/s and 175,082 B is what the 50 rows `/remote`
        keeps weigh - `docs/gui-rework/01-perf.md` §F3).  On this deployment that
        buys nothing today, because `/count` answers and `start` is already
        `total - want`, so the API sends only what is left; it is worth 4x on the
        path that runs when `/count` does *not* answer, which is the path a degraded
        API leaves this page on.
        """
        params = {name: value for name, value in dict(filters or {}).items()
                  if value is not None and value != ""}
        if kind:
            params["kind"] = kind
        # A caller's own `limit` filter has always been the page size (`Kjobs`
        # passes one): only the `limit` *argument* caps the whole read.
        page = int(params.pop("limit", PAGE))
        want = None if limit is None else max(0, int(limit))
        start = max(0, int(offset or 0))
        self.last_total = None
        if want is not None and want <= 0:
            return []
        items = []
        if want is not None and not start and newest:
            total = self.count(kind, params)
            self.last_total = total
            if total is None:
                # `want` rows and not `page`: the body carries `total` whatever
                # `limit` asked for, so learning the size never costs 200 rows when
                # 5 were wanted.  This is the path a degraded API leaves the page on.
                body, first = self._nodes_page(params, 0, _page_size(page, want, 0))
                total = _int_or_none(body.get("total"))
                self.last_total = total
                if total is None or total <= want:
                    # The first page is part of the answer when the cap covers it
                    # (or is all there is when the API reports no size at all).
                    items.extend(first)
                    if total is not None and len(items) >= total:
                        return items[:want]
                else:
                    start = total - want
            elif total > want:
                start = total - want
        elif want is not None and not newest:
            # The cap is the first `want` nodes: learn the size for the caller to
            # quote, but read no further than the cap.
            total = self.count(kind, params)
            self.last_total = total
        while True:
            body, batch = self._nodes_page(params, start + len(items),
                                           _page_size(page, want, len(items)))
            items.extend(batch)
            total = body.get("total")
            if total is not None:
                self.last_total = int(total)
            if want is not None and len(items) >= want:
                return items[:want]
            # A short page is not "there is no such build": while offset is
            # below the API's own total the walk goes on, and only a page that
            # really is empty ends it.
            if not batch:
                return items
            if total is not None and start + len(items) >= int(total):
                return items
            if total is None and len(batch) < page:
                return items

    def _nodes_page(self, params, offset, page):
        """One page of `/nodes` as `(body, items)`, with the shape checked once."""
        body = self.get("/nodes", dict(params, offset=offset, limit=page))
        if not isinstance(body, dict):
            raise ApiError(f"/nodes returned {type(body).__name__}, not an object")
        items = body.get("items") or []
        if not isinstance(items, list):
            raise ApiError(f"/nodes returned {type(items).__name__} items, not a list")
        return body, items

    def count(self, kind="", filters=None):
        """How many nodes the API says match, or `None` when it will not say.

        One request that carries no items, and the number is the API's own - a
        page may quote it and must never count its own rows in its place.
        """
        params = {name: value for name, value in dict(filters or {}).items()
                  if value is not None and value != ""}
        if kind:
            params["kind"] = kind
        params.pop("limit", None)
        try:
            body = self.get("/count", params)
        except ApiError:
            return None       # an API without /count still pages; the cap just costs pages
        if isinstance(body, bool):
            return None
        if isinstance(body, int):
            return body
        if isinstance(body, dict):
            for name in ("total", "count"):
                if isinstance(body.get(name), int):
                    return body[name]
        return None

    def node(self, node_id):
        """One node by id; a body that is not an object is an ApiError."""
        found = self.get(f"/node/{node_id}")
        if not isinstance(found, dict):
            raise ApiError(f"/node/{node_id} returned {type(found).__name__}, not an object")
        return found

    def events(self, kind="job", state="", since=""):
        """The nodes behind the events feed: read recursively, so their artifacts come too."""
        params = {"kind": kind, "limit": EVENTS_PAGE_MAX, "recursive": "true"}
        if state:
            params["state"] = state
        if since:
            params["from"] = since
        body = self.get("/events", {name: value for name, value in params.items() if value})
        if isinstance(body, dict):
            body = body.get("items")
        if not isinstance(body, list):
            raise ApiError(f"/events returned {type(body).__name__}, not a list of events")
        nodes = []
        for event in body:
            if not isinstance(event, dict):
                continue
            node = event.get("node") or event.get("data") or event
            if isinstance(node, dict):
                nodes.append(node)
        return nodes

    def counts(self, kinds=COUNTED_KINDS):
        """`{kind: [(name, count), ...]}`, biggest first; None when the API is down."""
        stats = {}
        for kind in kinds:
            try:
                nodes = self.nodes(kind=kind, filters={"limit": COUNT_LIMIT})
            except Exception:  # noqa: BLE001 - a summary must live without the API
                return None
            tally = {}
            for one in nodes:
                if not isinstance(one, dict):
                    continue
                name = str(one.get("name") or "?")
                tally[name] = tally.get(name, 0) + 1
            stats[kind] = sorted(tally.items(), key=lambda pair: -pair[1])
        return stats

    # --- transport ---------------------------------------------------------

    def _request(self, method, path, params=None, body=None, token="", retries=RETRIES):
        """One HTTP call: no redirects tolerated, a ConnectionError retried.

        A read is asked **once**.  The same `(base, method, url, params)` twice in
        one request is one answer - `/worker` asked the two heaviest queries in the
        API twice each, four calls and 680,254 bytes for a table of 50 rows
        (`docs/gui-rework/01-perf.md` §F4) - and the same question asked again
        inside `DEFAULT_TTL` seconds is answered from the process cache, with the
        age of that answer kept for the page to print.  A write is never
        remembered: `body is not None` is a POST, and a duplicated POST is a
        duplicated node.

        `timeout` used to be this method's only bound, and `requests` applies it to
        each *socket operation* - so it bounded the gap between two packets and
        nothing else, and a client configured for 5s waited 19.32s and returned
        happily (§F4b.1).  The body is therefore streamed and the clock is read
        between chunks (`_read`), and the request's own deadline - one per request,
        shared by every read it makes (`begin_request`) - is what stops a page.
        """
        url = self._full(path)
        scope = _scope()
        key = _key(self.base, method, url, params)
        if body is None:
            if key in scope["memo"]:
                return scope["memo"][key]
            found = _cached(key, scope["ttl"])
            if found is not None:
                response, age = found
                scope["memo"][key] = response
                oldest = scope["age"]
                scope["age"] = age if oldest is None else max(oldest, age)
                return response
        left = self._remaining()
        if left is not None and left <= 0:
            raise ApiError(f"{url} was not asked: this page already spent "
                           f"{scope['budget']:.0f}s on the API, which is its whole "
                           "budget for one request")
        headers = self._headers(token) if self._is_ours(url) else {}
        last = None
        for attempt in range(max(1, retries)):
            try:
                response = self._session.request(
                    method, url, params=params, json=body, headers=headers,
                    timeout=self._timeout(), stream=True, allow_redirects=False)
            except requests.exceptions.ConnectionError as error:
                # A refused connection is worth another attempt; a read timeout is
                # not - the endpoint answered nothing and will answer nothing
                # again a second later.
                last = error
                if attempt + 1 < retries:
                    time.sleep(attempt + 1)
                continue
            except requests.exceptions.RequestException as error:
                raise ApiError(f"{url} did not answer: {_why(error)}") from error
            try:
                self._refuse_redirect(response, url)
                self._raise_for_status(response, url)
            except ApiError:
                response.close()          # a refused body must not hold the socket
                raise
            self._read(response, url)
            if body is None:
                scope["memo"][key] = response
                _remember(key, response)
            return response
        # **No `attempt(s)` here.**  This sentence is *printed to the reader* - every page
        # that could not read the API carries it in its banner, and `accept.py`'s W3 check
        # calls a machine plural invented by the page ("a reader who sees `attempt(s)`
        # cannot tell whether the page tried once or many times").  The number is known at
        # this line, so it is spelled rather than bracketed.
        raise ApiError(f"{url} is not answering after {retries} "
                       f"attempt{'s' if retries != 1 else ''}: {_why(last)}") from last

    def _read(self, response, url):
        """The whole body, read here because a wall clock is what bounds a read.

        `requests` reads the body inside `request()` under the same per-socket
        timeout, so a 340 KB queue page arriving in a trickle can take any multiple
        of the number the caller set: `/worker`'s two reads measured 11.1s and
        13.5s against a 10s setting, and the same page was seen at 39s against it
        (`docs/gui-rework/01-perf.md` §F4b).  Streaming it and reading the clock
        between chunks is what makes that setting mean what its comment says.

        A body that **stops early is not a short answer**, and two things say so.
        `requests` raises its own exception for a stream that dies (`ChunkedEncodingError`,
        around urllib3's `IncompleteRead`) - and this loop is *outside* the `try` that
        turns `requests`' exceptions into an `ApiError`, so it is caught here: an API
        failure on a page is a sentence (`Remote.note`), and a raw exception from the
        transport layer is an HTTP 500.  Where urllib3 does *not* raise, the declared
        length is the only thing that says so - JSON cut mid-object either fails to
        parse with a message about a comma, or parses into something that is not the
        answer that was asked for.  That comparison is only meaningful when the bytes
        on the wire *are* the body: a `Content-Encoding` makes `Content-Length` the
        compressed size and this count the decoded one (`files.kernelci.org` compresses
        a `.config`; the API itself sends no encoding at all - §F3).

        The two attributes set at the end are the ones `Response.content` fills in
        itself when the body is read the ordinary way, so `.content`, `.text` and
        `.json()` behave exactly as every caller already expects.
        """
        chunks: list[bytes] = []
        try:
            for chunk in response.iter_content(CHUNK):
                chunks.append(chunk)
                left = self._remaining()
                if left is not None and left <= 0:
                    response.close()
                    raise ApiError(f"{url} is still streaming after the "
                                   f"{_scope()['budget']:.0f}s this page waits for the API "
                                   f"({sum(len(one) for one in chunks)} bytes so far)")
        except requests.exceptions.RequestException as error:
            response.close()
            raise ApiError(f"{url} stopped mid-body: {_why(error)}") from error
        body = b"".join(chunks)
        declared = response.headers.get("Content-Length") or ""
        if (declared.isdigit() and not response.headers.get("Content-Encoding")
                and len(body) != int(declared)):
            raise ApiError(f"{url} declared {declared} bytes and sent {len(body)}; "
                           "the answer is not the whole answer")
        response._content = body                      # what `Response.content` sets
        response._content_consumed = True             # ... when it reads the body

    def _remaining(self):
        """Seconds left of this request's API budget, or `None` when it has none.

        `None` is a caller that is not a served request (`Gui.render()` from a probe
        or a test): it gets a per-call timeout and no page deadline, exactly as this
        module behaved before the request scope existed.
        """
        deadline = _scope()["deadline"]
        return None if deadline is None else deadline - time.monotonic()

    def _timeout(self):
        """The socket timeout for the call about to be made, never past the deadline."""
        left = self._remaining()
        if left is None or not self.timeout:
            return self.timeout
        return max(0.1, min(self.timeout, left))

    @staticmethod
    def _refuse_redirect(response, url):
        """A 3xx is never the answer: something other than the API is answering.

        `allow_redirects=False` only declines to follow one - it does not
        notice that one arrived, so every 3xx is noticed here (including the
        ones that carry no Location, which requests does not call a redirect).
        """
        if 300 <= response.status_code < 400:
            raise ApiError(
                f"refusing redirect for {url} (HTTP {response.status_code}); "
                "the API is not where this URL says it is")

    @staticmethod
    def _raise_for_status(response, url):
        """A non-2xx is an ApiError naming the status - never requests' own exception."""
        if not response.ok:
            raise ApiError(f"{url} answered HTTP {response.status_code}")

    @staticmethod
    def _decode(response):
        """JSON or ApiError; never a ValueError in a caller's face."""
        try:
            return response.json()
        except ValueError as error:
            # A proxy's HTML error page: an ApiError, not a bare ValueError.
            raise ApiError(f"{response.url} did not return JSON: {error}") from error

    def _full(self, path):
        """`path` as a URL: an absolute one is used as given, a path goes under /latest."""
        if path.startswith(("http://", "https://")):
            return path
        return f"{self._latest()}{path}"

    def _is_ours(self, url):
        """True for a URL under this API - the only host that ever sees the token."""
        return url == self._latest() or url.startswith(f"{self._latest()}/")

    def _headers(self, token):
        """The authorization header, or none when there is no token to send."""
        token = token or self.token
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _latest(self):
        """The canonical /latest base (KernelCI serves everything under it)."""
        if self.base.endswith("/latest"):
            return self.base
        return f"{self.base}/latest"


def _int_or_none(value):
    """`value` as an int, or None when the API did not send a number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_size(page: int, want: int | None, got: int) -> int:
    """How many rows one `/nodes` page may ask for: the cap's remainder, never more.

    `PAGE` is 200 and a page of this console shows 25-50 rows, so asking for the
    full page and slicing it is up to 4x the bytes, and the bytes are the cost:
    production streams `/nodes` at 20-35 KB/s and the 50 rows `/remote` keeps weigh
    175,082 B, i.e. 5-9s (`docs/gui-rework/01-perf.md` §F3).  On this deployment
    that buys nothing on the `/count` path - `start` is already `total - want`
    there, so the API sends only what is left - and it is worth 4x on the path that
    runs when `/count` does *not* answer, which is the path a degraded API leaves
    this page on.  It also never asks for nothing: a page of 1 is what ends a walk
    that has already got everything it wanted.
    """
    if want is None:
        return page
    return min(page, max(1, want - got))


def _why(error):
    """A connection failure in one line: its class, and the reason underneath it.

    `requests`' own text carries pool internals and an object repr with a memory
    address, and that text is printed on a *page* - where the part that says what
    happened is the innermost reason (`[Errno 111] Connection refused`).  That
    reason is not always on `__cause__`: urllib3 hangs it off `reason`, and
    `requests` puts the whole `MaxRetryError` in `args[0]`.
    """
    cause = error
    for _ in range(8):
        under = (getattr(cause, "__cause__", None) or getattr(cause, "reason", None)
                 or next((one for one in getattr(cause, "args", ())
                          if isinstance(one, BaseException)), None))
        if under is None or under is cause:
            break
        cause = under
    # urllib3's own text opens with the pool object's repr - address and all -
    # and this line is printed on a page, so the repr goes.
    said = [one for one in getattr(cause, "args", ()) if isinstance(one, str)]
    text = " ".join((said[-1] if said else str(cause)).split())
    return f"{type(error).__name__}: {' '.join(OBJECT_REPR.sub('', text).split()).lstrip(': ')}"
