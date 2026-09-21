# SPDX-License-Identifier: LGPL-2.1-or-later
"""The jobs the KernelCI API knows: the queue the worker claims from.

Draft this file is built from (``lib/kjob``)::

    struct kjobnode { kjobnode }
    class kjob {
        list kjobnode
        kjob(api)
        getjob(过滤参数)
        print
    }

Two things live here and they are the same node kind: a **queue entry** (state
`available`, with a job_definition URL to fetch) and a **finished run** (state
`done`, with a result).  The worker reads the first, the trend tool the second.

Filtering is by the API's own vocabulary - `getjob(state=..., name=...,
device=...)` - because that is what callers actually have: a runtime name from
the deployment config, a job name from a command line.

接口形状（C++，只有声明）：include/kci/remote.hpp §6 Kjob / Kjobs。
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, TextIO

from .api import Api
from .errors import ApiError
from .kbuild import _artifacts, _text

AVAILABLE = "available"
DONE = "done"
# The artifact a pull-lab job carries its definition under - the thing a worker
# fetches before it can run anything.
DEFINITION_ARTIFACT = "job_definition"
# The API's own filter vocabulary for the device a job ran on.
DEVICE_FILTER = "data.device"


@dataclass(frozen=True)
class Kjob:
    """One job node: either something to run, or something that ran."""

    node_id: str = ""
    name: str = ""
    state: str = ""
    result: str = ""
    platform: str = ""
    runtime: str = ""
    created: str = ""
    # Where the definition is fetched from; a node without one cannot be run.
    definition_url: str = ""
    callback_url: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    # The raw node, for readers that need a field this class does not name.
    node: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> "Kjob":
        """A node document as a Kjob; a non-object is an ApiError, not an AttributeError."""
        if not isinstance(node, dict):
            raise ApiError(f"a node must be an object, got {type(node).__name__}")
        data = node.get("data")
        data = data if isinstance(data, dict) else {}
        artifacts = _artifacts(node.get("artifacts"))
        return cls(
            node_id=str(node.get("id") or ""),
            name=_text(node.get("name")),
            state=_text(node.get("state")),
            result=_text(node.get("result")),
            platform=_text(data.get("platform")),
            runtime=_text(data.get("runtime")),
            created=_text(node.get("created")),
            definition_url=artifacts.get(DEFINITION_ARTIFACT, ""),
            callback_url=_text(data.get("callback_url")),
            artifacts=artifacts,
            node=node,
        )

    def claimable(self, runtime: str = "") -> bool:
        """Is this ours to run: available, has a definition, and the runtime matches?"""
        if self.state != AVAILABLE:
            return False
        if not self.definition_url.startswith(("http://", "https://")):
            return False              # no definition URL: not a pull-lab job
        return not runtime or self.runtime == runtime

    def definition(self, api: Api) -> dict[str, Any]:
        """Fetch and parse the job definition this node points at (a plain dict)."""
        if not self.definition_url:
            raise ApiError(f"job node {self.node_id or '?'} has no "
                           f"{DEFINITION_ARTIFACT} artifact; it is not a pull-lab job")
        definition = api.get(self.definition_url)
        if not isinstance(definition, dict):
            raise ApiError(f"the job definition at {self.definition_url} is "
                           f"{type(definition).__name__}, not an object")
        return definition

    def print(self, stream: TextIO | None = None) -> None:
        """One line: the node, what it is, and whether it can still be claimed."""
        print(f"{self.node_id}  {self.state:<9}  {self.result or '-':<10}  "
              f"{self.created}  {self.name}  {self.runtime or '-'}  "
              f"{self.definition_url or 'no definition'}", file=stream)


class Kjobs:
    """A set of job nodes, gathered from an API with the API's own filters."""

    def __init__(self, api: Api | None = None, items: Iterable[Kjob] = ()) -> None:
        self.api = api
        self.items = list(items)
        # What the API said it has for the last read, `None` when it did not say
        # (see `getjob`): a page quotes this instead of counting its own rows.
        self.total: int | None = None

    def getjob(self, state: str | None = None, name: str | None = None,
               device: str | None = None, kind: str = "job",
               limit: int | None = None) -> list[Kjob]:
        """The job nodes matching the filters (过滤参数), as the API served them.

        `limit` caps the read at the **head** of the answer, which is what a reader
        of a queue wants: the API hands nodes out oldest first, so taking the newest
        `limit` of a production-sized queue (`kind=job` answers 4.7 million) would
        both miss the claimable end and cost tens of thousands of requests.  The
        API's own count is left in `self.total` for the caller to quote; a caller
        that passes no `limit` still gets everything, which is what the worker's own
        claim loop needs.
        """
        filters: dict[str, Any] = {"state": state, "name": name, DEVICE_FILTER: device}
        client = self._client()
        nodes = client.nodes(kind=kind, filters=filters, limit=limit, newest=False)
        self.total = getattr(client, "last_total", None)
        found = []
        for node in nodes:
            if not isinstance(node, dict):
                continue          # one malformed page item must not cost the batch
            found.append(Kjob.from_node(node))
        self._keep(found)
        return found

    def available(self, runtime: str = "") -> list[Kjob]:
        """The queue: nodes this worker may claim right now."""
        return [job for job in self.getjob(state=AVAILABLE) if job.claimable(runtime)]

    def done(self, name: str) -> list[Kjob]:
        """Finished runs of one job, oldest first - the order a trend needs."""
        found = self.getjob(state=DONE, name=name)
        return sorted(found, key=lambda job: (job.created, job.node_id))

    def merge(self, other: "Kjobs") -> None:
        """Add another Kjobs' nodes, dropping ones already here."""
        self._keep(other.items)

    def __iter__(self) -> Iterator[Kjob]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def print(self, stream: TextIO | None = None) -> None:
        """One line per node, oldest first."""
        for job in sorted(self.items, key=lambda job: (job.created, job.node_id)):
            job.print(stream)

    def _keep(self, jobs: Iterable[Kjob]) -> None:
        """Remember nodes this collection has not got yet, one entry per node id."""
        known = {job.node_id for job in self.items}
        for job in jobs:
            if job.node_id not in known:
                known.add(job.node_id)
                self.items.append(job)

    def _client(self) -> Api:
        """The API client, or an ApiError naming what is missing."""
        if self.api is None:
            raise ApiError("Kjobs needs an Api to ask which jobs exist")
        return self.api
