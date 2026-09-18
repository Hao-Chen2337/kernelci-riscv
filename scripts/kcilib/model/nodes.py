# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""native layer: typed node + the two pullers; raw dicts end here."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence

from kcilib import api as _api
from kcilib.table.build import (
    ORIGIN_API,
    ORIGIN_API_LOCAL,
)

# What a failed transfer arrives as: the class the resident worker retries and
# treats every other exception as "handled".  It is requests' own, and it is
# read from the client module's namespace because kcilib.api is this layer's
# only edge onto the network - which HTTP library sits under it is its
# business, not ours.
_RequestException: type[Exception] = _api.requests.exceptions.RequestException

# Where a node came from: the constants live with the Build they describe
# (kcilib.table.build), because the table and the sources need to name an origin
# and may not import this layer back.  origin_for() stays here - it is a fact
# about API URLs, not about builds.

# The kbuild job this configuration reads.
DEFAULT_KBUILD_JOB = "kbuild-gcc-14-riscv"
# The pull-lab runtime this worker claims.
DEFAULT_JOB_RUNTIME = "pull-labs-riscv"

# The eight operator suffixes kernelci-api understands (api/db.py
# OPERATOR_MAP): the only "__x" a filter key here may end in.
OPERATORS = ("lt", "lte", "gt", "gte", "ne", "re", "in", "nin")

# The events API refuses recursive=true above this page size; a larger limit
# is capped rather than handed over as a 400.
EVENTS_PAGE_MAX = 1000


def origin_for(api_url: str) -> str:
    """The origin of the nodes *api_url* serves.

    Production and any other remote deployment are both ORIGIN_API: a second
    official API is still an official one.  Only the local default - this
    deployment's own stack, or no URL at all, which the client reads as that
    same default - is ORIGIN_API_LOCAL.
    """
    url = (api_url or "").rstrip("/")
    if url == _api.PRODUCTION_API:
        return ORIGIN_API
    local = (_api.local_api_url() or "").rstrip("/")
    if not url or url == local or url == _api.LOCAL_API:
        return ORIGIN_API_LOCAL
    return ORIGIN_API


def _remember(nodes: list[KernelCINode], node: KernelCINode) -> KernelCINode:
    """Keep one entry per id in *nodes*: a re-read replaces what it repeats.

    The API serves the same node in many events and many pages, and a stale
    copy of it is worse than none (its artifacts move as the node runs), so
    the newest read wins instead of the first.
    """
    for index, known in enumerate(nodes):
        if node.node_id and known.node_id == node.node_id:
            nodes[index] = node
            return node
    nodes.append(node)
    return node


def _is_our_runtime(node: dict) -> bool:
    """True when a job node claims this worker's runtime.

    A job whose data.runtime is another lab's is not ours to run; a job that
    names no runtime at all is claimed, which is poll's own rule.
    """
    data = node.get("data")
    runtime = data.get("runtime") if isinstance(data, dict) else None
    return not runtime or runtime == DEFAULT_JOB_RUNTIME


class KernelCINode:
    """One node exactly as the API served it, behind typed accessors.

    The raw mapping stays inside: a caller reads a field by name and gets the
    type it expects ("" or None instead of a missing key), so no other layer
    has to spell "data.kernel_revision" or guess what a node without an
    artifact looks like.
    """

    def __init__(self, raw: dict) -> None:
        self._raw: dict = raw

    @property
    def node_id(self) -> str:
        """The API's id for this node ("" when it carries none)."""
        return str(self._raw.get("id") or "")

    @property
    def kind(self) -> str:
        """checkout, kbuild or job."""
        return str(self._raw.get("kind") or "")

    @property
    def name(self) -> str:
        """The job or build name (e.g. kbuild-gcc-14-riscv)."""
        return str(self._raw.get("name") or "")

    @property
    def state(self) -> str:
        """The node's state: running, available, closing or done."""
        return str(self._raw.get("state") or "")

    @property
    def result(self) -> str:
        """pass, fail, incomplete or skip ("" before it ran)."""
        return str(self._raw.get("result") or "")

    @property
    def created(self) -> str:
        """When the node was created, as the API renders it (ISO-8601)."""
        return str(self._raw.get("created") or "")

    @property
    def tree(self) -> str | None:
        """The kernel tree this node was built from."""
        return self._revision("tree")

    @property
    def branch(self) -> str | None:
        """The branch inside that tree."""
        return self._revision("branch")

    @property
    def commit(self) -> str | None:
        """The commit the build or test ran on."""
        return self._revision("commit")

    @property
    def describe(self) -> str | None:
        """git describe of that commit (v7.3-rc2-655-g...)."""
        return self._revision("describe")

    @property
    def artifacts(self) -> Mapping[str, str]:
        """Artifact key -> URL, as served (empty values dropped)."""
        raw = self._raw.get("artifacts")
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items() if value}

    def artifact(self, key: str) -> str | None:
        """The URL of one artifact, or None when this node has not got it."""
        return self.artifacts.get(key)

    def raw(self) -> dict:
        """The node as the API served it.

        The one place a raw node leaves this layer: build_ref_from_node() and
        the rest of the table layer read the API's own shape, and re-spelling
        it here would be a second definition of what a node is.
        """
        return self._raw

    @property
    def _kernel_revision(self) -> dict:
        """The data.kernel_revision mapping ({} when the node has none)."""
        data = self._raw.get("data")
        if not isinstance(data, dict):
            return {}
        revision = data.get("kernel_revision")
        return revision if isinstance(revision, dict) else {}

    def _revision(self, key: str) -> str | None:
        value = self._kernel_revision.get(key)
        return str(value) if value else None

    def __repr__(self) -> str:
        return f"<KernelCINode {self.kind} {self.node_id} {self.state}>"


class KbuildPuller:
    """Fetch kbuild nodes; the collection itself.

    The API URL is the only input, because it is the only thing that differs
    between a local and a production read; every filter is built here.  What
    has been fetched stays in *nodes*, so a second question about the same
    build is answered without a second request.
    """

    def __init__(self, api_url: str = _api.local_api_url()) -> None:
        self.api_url: str = api_url
        self.nodes: list[KernelCINode] = []
        self._client: _api.KernelCI = _api.KernelCI(api_url)

    def newest(self, tree: str | None = None, result: str = "pass",
               windows: Sequence[int] = (3, 7, 30, 180),
               ) -> KernelCINode | None:
        """The newest kbuild matching *tree* and *result*, or None.

        The window starts at three days and grows to 7/30/180 before None is
        the answer, because "nothing in three days" is not "no build".  The
        fresh window is walked page by page - the API serves the oldest match
        first, so the newest one is picked by created, not by position.
        """
        for days in windows:
            found = self.last_days(days, tree=tree, result=result)
            if found:
                return max(found, key=lambda node: node.created)
        return None

    def last_days(self, days: int, tree: str | None = None,
                  result: str = "pass") -> list[KernelCINode]:
        """Every kbuild of the last *days* days (all pages of that window).

        Returns what this call collected: a node already known is refreshed in
        place rather than added twice.
        """
        params = self._params(kind="kbuild", name=DEFAULT_KBUILD_JOB,
                              tree=tree, result=result,
                              created__gte=self._window(days))
        return self._append(self._client.all_nodes(**params))

    def find(self, **filters: object) -> list[KernelCINode]:
        """One page of kbuilds matching *filters* (kind and name defaulted).

        Every filter is the API's own: "tree=x" is shorthand for
        data.kernel_revision.tree=x, and any key may carry one of OPERATORS
        ("created__gte=2026-01-01T00:00:00").  An operator outside that set is
        a ValueError here, not a filter the API silently drops.
        """
        return self._append(self._client.nodes(**self._params(**filters)))

    def get_node(self, node_id: str) -> KernelCINode | None:
        """One kbuild by id: the collection first, the API only on a miss.

        A miss is None rather than a raise: this is a lookup ("do we have this
        build?"), and the caller's next move is to look for another one.  The
        API answers a miss two ways - HTTP 404, or 200 with a null body (the
        endpoint is Union[Node, None]) - so both arrive as None.  A malformed
        id (HTTP 400) still raises: the caller wrote a bad id, and None would
        hide that.
        """
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        try:
            raw = self._client.get(f"/node/{node_id}")
        except _RequestException as error:
            response = getattr(error, "response", None)
            if response is not None and response.status_code == 404:
                return None
            raise
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise _api.APIError(f"/node/{node_id} did not return an object")
        return _remember(self.nodes, KernelCINode(raw))

    def clear(self) -> None:
        """Forget every node collected so far."""
        self.nodes.clear()

    def __iter__(self) -> Iterator[KernelCINode]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def __repr__(self) -> str:
        return f"<KbuildPuller {self.api_url} {len(self.nodes)} node(s)>"

    def _params(self, **filters: object) -> dict:
        """The API's own filter parameters for *filters*.

        None and "" mean "not asked for" and drop out, so a caller may pass a
        field it does not have.  What is left is the query string itself: the
        API translates "__op" into its mongo operator and reads a dotted key as
        a path, so nothing here rewrites a value.
        """
        params: dict = {}
        for key, value in filters.items():
            if value is None or value == "":
                continue
            name, _, operator = key.partition("__")
            if operator and operator not in OPERATORS:
                raise ValueError(
                    f"unknown filter operator {operator!r} in {key!r}; the "
                    f"API knows: {', '.join(OPERATORS)}")
            if name == "tree":
                key = "data.kernel_revision.tree"
                if operator:
                    key = f"{key}__{operator}"
            params[key] = value
        params.setdefault("kind", "kbuild")
        params.setdefault("name", DEFAULT_KBUILD_JOB)
        params.setdefault("limit", _api.PAGE_LIMIT)
        return params

    def _window(self, days: int) -> str:
        """The ISO-8601 timestamp *days* days back (UTC, seconds)."""
        return time.strftime("%Y-%m-%dT%H:%M:%S",
                             time.gmtime(time.time() - days * 86400))

    def _append(self, nodes: list[dict]) -> list[KernelCINode]:
        """Wrap the served nodes, keep one entry per id, return them all.

        An entry that is not an object is skipped: there is no node in it to
        read, and one malformed page item must not cost the whole batch.
        """
        return [_remember(self.nodes, KernelCINode(raw))
                for raw in nodes if isinstance(raw, dict)]


class JobPuller:
    """Fetch job nodes and their definitions.

    The pull-lab queue is what the events API answers with; a job's definition
    is what its job_definition artifact points at.  Both go through one client,
    so a transfer failure arrives as the exception type the worker retries.
    """

    def __init__(self, api_url: str = _api.local_api_url()) -> None:
        self.api_url: str = api_url
        self.nodes: list[KernelCINode] = []
        self._client: _api.KernelCI = _api.KernelCI(api_url)

    def from_events(self, state: str = "available",
                    since: str | None = None,
                    limit: int = 1000) -> list[KernelCINode]:
        """The job nodes the events API queues up right now.

        The read is recursive on purpose: an event's own snapshot predates the
        job's artifacts, and the artifact URLs are what definition() needs.  A
        job of another runtime is skipped (poll's rule), and *limit* is capped
        at the page size a recursive read allows instead of becoming a 400.
        """
        params: dict[str, object] = {
            "state": state,
            "kind": "job",
            "limit": max(1, min(int(limit), EVENTS_PAGE_MAX)),
            "recursive": "true",
        }
        if since:
            params["from"] = since
        raws: list[dict] = []
        for event in self._events(params):
            node = event.get("node") or event.get("data")
            if isinstance(node, dict) and _is_our_runtime(node):
                raws.append(node)
        return self._append(raws)

    def get_node(self, node_id: str) -> KernelCINode:
        """One job node by id, read live.

        Unlike KbuildPuller.get_node this always asks the API: the point of the
        call is the current node - the one whose artifacts definition() needs -
        and a queued event's snapshot does not carry them.
        """
        return _remember(self.nodes, KernelCINode(self._client.node(node_id)))

    def definition(self, node: KernelCINode) -> dict:
        """The job definition *node* points at: the executor's input.

        A redirect, a non-JSON body and a wrong-shaped body are all transient
        here (RequestException), because the worker retries exactly that type
        and would otherwise file the event as handled and lose the job.  A node
        with no job_definition artifact is not a fetch failure at all: it is
        not a pull-lab job, which no retry can change.
        """
        url = node.artifact("job_definition")
        if not url:
            raise ValueError(
                f"job node {node.node_id or '?'} has no job_definition "
                "artifact; it is not a pull-lab job")
        try:
            return self._client.job_definition(url)
        except _api.APIError as error:
            raise _RequestException(str(error)) from error

    def clear(self) -> None:
        """Forget every node collected so far."""
        self.nodes.clear()

    def __iter__(self) -> Iterator[KernelCINode]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def __repr__(self) -> str:
        return f"<JobPuller {self.api_url} {len(self.nodes)} node(s)>"

    def _events(self, params: dict) -> list[dict]:
        """One events read, with a non-JSON body made retryable.

        /events answers with a bare list, so the client's {items} unwrap - the
        one that raises on a list - is not the read to use; get() is, and both
        shapes are accepted here.  A body that is neither is a
        RequestException: the resident worker retries that class and treats
        every other exception as handled, i.e. as a job dropped on the floor.
        """
        try:
            events = self._client.get("/events", params)
        except _api.APIError as error:
            raise _RequestException(
                f"events API did not answer with JSON: {error}") from error
        if isinstance(events, dict):
            events = events.get("items") or []
        if not isinstance(events, list):
            raise _RequestException(
                f"/events returned {type(events).__name__}, not a list of "
                "events")
        return [event for event in events if isinstance(event, dict)]

    def _append(self, nodes: list[dict]) -> list[KernelCINode]:
        """Wrap the served nodes, keep one entry per id, return them all."""
        return [_remember(self.nodes, KernelCINode(raw))
                for raw in nodes if isinstance(raw, dict)]
