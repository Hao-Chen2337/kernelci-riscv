# SPDX-License-Identifier: LGPL-2.1-or-later
"""The builds the KernelCI API knows: read-only, and the top of the run path.

Draft this file is built from (``lib/kbuild``)::

    struct kbuildnode { dict kbuildnode }
    class kbuild {
        list kbuildnode
        kbuild (api)
        getnew(tree,)
        getdays(tree,)
        get(tree,)
        考虑去重
        print
    }

Identity is `build_id`, parsed out of the artifact URLs - NOT the node id:
node ids are per-database and the local and production APIs disagree about the
same build.  Dedup is by `build_id` (the draft's 考虑去重), so a build seen
twice is one entry.

接口形状（C++，只有声明）：include/kci/remote.hpp §5 Kbuild / Kbuilds。
"""

import re
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TextIO

from .api import MAX_WINDOW_DAYS, Api
from .errors import ApiError, ConfigError

# The kbuild job this deployment runs: one name, so "the newest riscv build"
# cannot quietly become some other configuration's build.
KBUILD_JOB = "kbuild-gcc-14-riscv"

# Artifact keys the executor knows, named as upstream renders them; _config is
# only used for drift, but is the sole source of the build configuration.
ARTIFACT_KEYS = ("kernel", "kselftest_tar_xz", "kselftest", "modules", "_config")

# A build is usable when the node is finished and carries a kernel.  What a
# *test* needs beyond that is the catalogue's business (`lib/tests.py`).
USABLE_STATE = ("done", "available")

# The build id inside an artifact URL: /<job>-<24 hex>/<file>.  Identity is this,
# never the node id, so it survives a re-import into another database.
BUILD_ID_RE = re.compile(r"/([^/?\s]+?)-([0-9a-f]{24})(?:[/?]|$)")

# The API's own filter vocabulary for a revision field.
TREE_FILTER = "data.kernel_revision.tree"
BRANCH_FILTER = "data.kernel_revision.branch"

# How far back `getnew()` looks before it gives up: "nothing in three days" is
# not "no build", so the window widens instead of answering None.
WINDOWS = (3, 7, 30, 180)

# The API's own spellings for "a build that finished and passed" - the filter a
# caller wants when it is choosing a build to *use* rather than one to look at:
# `provision.py` pins the kernel this deployment serves from such a build
# (a failed one is not what a stack should seed), and `drift.py` compares the two
# newest of them.  Two callers, one spelling.
PASSED_FILTER = {"state": "done", "result": "pass"}

# The most a "find this build id" scan will read (see `Kbuilds.get`): the API has
# no way to ask for an id, so a miss means a walk, and an uncapped walk of a
# production-sized window is thousands of requests for a page that is waiting.
SCAN = 1000


@dataclass(frozen=True)
class Kbuild:
    """One build in the API, as far as a run cares about it."""

    node_id: str = ""
    build_id: str = ""
    tree: str = ""
    branch: str = ""
    arch: str = ""
    defconfig: str = ""
    compiler: str = ""
    created: str = ""
    state: str = ""
    result: str = ""
    # artifact name -> URL, exactly as the node spells it (kernel, modules,
    # kselftest, _config, ...).  Names are the API's, not ours.
    artifacts: dict[str, str] = field(default_factory=dict)
    revision: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> "Kbuild":
        """A node document as a Kbuild; raises ApiError when it is not a kbuild node."""
        if not isinstance(node, dict):
            raise ApiError(f"a node must be an object, got {type(node).__name__}")
        kind = str(node.get("kind") or "")
        if kind and kind != "kbuild":
            raise ApiError(f"node {node.get('id') or '?'} is a {kind} node, not a kbuild")
        data = node.get("data")
        data = data if isinstance(data, dict) else {}
        revision = data.get("kernel_revision")
        revision = revision if isinstance(revision, dict) else {}
        artifacts = _artifacts(node.get("artifacts"))
        if not artifacts.get("kernel"):
            raise ApiError(f"node {node.get('id') or '?'} has no kernel artifact, "
                           "so it cannot be run and is not a build")
        # The build id inside the artifact URLs is the identity both APIs agree
        # on; a locally made kernel has none, and its node id is the only stable
        # name it has - the same fallback the old tree used.
        build_id = build_id_of(artifacts) or str(node.get("id") or "")
        if not build_id:
            raise ApiError(f"node {node.get('id') or '?'} has neither a build id in "
                           "its artifact URLs nor a node id; nothing to file it under")
        return cls(
            node_id=str(node.get("id") or ""),
            build_id=build_id,
            tree=_text(revision.get("tree")),
            branch=_text(revision.get("branch")),
            arch=_text(data.get("arch")),
            defconfig=_text(data.get("defconfig")),
            compiler=_text(data.get("compiler")),
            created=_text(node.get("created")),
            state=_text(node.get("state")),
            result=_text(node.get("result")),
            artifacts=artifacts,
            revision=revision,
        )

    def artifact(self, name: str) -> str:
        """The URL of one artifact, or '' - never a KeyError."""
        return self.artifacts.get(name) or ""

    def usable(self) -> tuple[bool, str]:
        """Could a run start from this build?  `(ok, reason)`; the reason is printed."""
        if self.state and self.state not in USABLE_STATE:
            return False, f"state {self.state!r} is not one of {'/'.join(USABLE_STATE)}"
        # Arch is NOT a criterion here: a real node carries no `data.arch` at all
        # (it is read from the kbuild job name this deployment runs), so checking
        # it rejected every production build.  The field stays informational.
        #
        # What a *test* needs is the catalogue's business (`lib/tests.py`), and a
        # per-test gap is `Build.missing()`'s; repeating the table here was a
        # second copy in a second spelling.
        if not self.artifact("kernel"):
            return False, "the node names no kernel artifact"
        return True, ""

    def describe(self) -> str:
        """`tree-branch-arch-defconfig`, the label runs and records are named with."""
        return "-".join(part for part in (self.tree, self.branch, self.arch, self.defconfig)
                        if part)


class Kbuilds:
    """A set of builds, gathered from an API and deduplicated by build_id."""

    def __init__(self, api: Api | None = None, items: Iterable[Kbuild] = ()) -> None:
        self.api = api
        self.items = list(items)
        # What the API said its own `total` was for the last read, or None when
        # it did not say.  A caller may quote this; it may not count its own
        # rows in its place (what came back is what the read's cap allowed).
        self.total: int | None = None

    # --- where they come from ---------------------------------------------

    def getnew(self, tree: str, branch: str | None = None,
               passing: bool = False) -> Kbuild:
        """The newest usable build of `tree`, widening the search window until one exists.

        *passing* narrows "usable" to the builds this job finished and passed
        (`PASSED_FILTER`).  Provisioning asks for that: the kernel a local stack
        serves is one whose build passed, and a build nobody can call good is not
        a thing to seed jobs from.  The window widens the same way either way, and
        an empty page is never read as "no such build" (`getdays` looks at `total`).
        """
        extra = PASSED_FILTER if passing else None
        for days in WINDOWS:
            found = self.getdays(tree, days, branch, extra=extra)
            if found:
                return found[0]
        wanted = "passing " if passing else "usable "
        raise ApiError(f"no {wanted}{KBUILD_JOB} build of tree {tree!r} in the last "
                       f"{WINDOWS[-1]} days")

    def getdays(self, tree: str, days: int, branch: str | None = None,
                limit: int | None = None,
                extra: Mapping[str, str] | None = None) -> list[Kbuild]:
        """Every usable build of `tree` from the last `days` days, newest first.

        `days` <= 0 is not "nothing": it asks the API for the job's whole history
        (no `created__gte` at all).  `limit` caps the *read*, so it is the newest
        `limit` nodes that get looked at - the usable filter still runs
        afterwards, which is why a page must print both the number it asked for
        and the number it got.

        `extra` is any further API filter key this read has to carry, in the
        API's own spelling (`data.arch`, `state`, `result`: `gui.API_FILTERS`).
        It exists because three arguments are not a filter bar: the GUI's value
        axes were reaching the wire through an adapter that wrapped the whole
        *client* (`gui._Narrowed`, now deleted) so that `Api.nodes()`/`count()`
        would receive keys this method had no way to pass - an indirection that
        reads as "the client is narrowable" when the truth is "this read takes
        more keys".  A second caller had to be written twice for every new axis.
        The explicit arguments still win over `extra` for the keys they spell
        (`name`, `created__gte`, tree, branch): the caller that names a tree in
        the call is the one deciding that argument, and `extra` is what the read
        was *also* told.  `extra` is **not** a second way to build the window: a
        `created__gte` in it is kept only when `days` asked for no window.
        """
        found = [build for build in self._fetch(tree, days, branch, limit, extra)
                 if build.usable()[0]]
        self._keep(found)
        return found

    def get(self, build_id: str) -> Kbuild:
        """One build by build_id (not node id); the API can only be asked by scanning.

        The scan is capped at the newest `SCAN` nodes.  The API cannot be asked for
        a build id at all - it is parsed out of the artifact URLs - and an uncapped
        walk of one job's window costs a page's worth of requests per id: on
        production `kbuild-gcc-14-riscv` answers nearly two thousand nodes, so
        comparing two configs used to be eighteen requests.  A build anybody is
        looking at is one a page has just listed, so the newest nodes are the ones
        worth reading; a miss says exactly how far the read went.
        """
        for build in self.items:
            if build.build_id == build_id:
                return build
        for build in self._fetch("", WINDOWS[-1], None, SCAN):
            if build.build_id == build_id:
                self._keep([build])
                return build
        raise ApiError(f"no {KBUILD_JOB} build with id {build_id} among the newest "
                       f"{SCAN} node(s) of the last {WINDOWS[-1]} days")

    # --- the set itself ----------------------------------------------------

    def merge(self, other: "Kbuilds") -> None:
        """Add another Kbuilds' builds, dropping ones already here (draft: 考虑去重)."""
        self._keep(other.items)

    def __iter__(self) -> Iterator[Kbuild]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def print(self, stream: TextIO | None = None) -> None:
        """One line per build: build_id, tree/branch, age, and whether it is usable."""
        for build in self.items:
            ok, why = build.usable()
            verdict = "usable" if ok else f"unusable: {why}"
            print(f"{build.build_id}  {build.describe()}  {_age(build.created)}  "
                  f"{verdict}", file=stream)

    # --- the API read ------------------------------------------------------

    def _fetch(self, tree: str, days: int, branch: str | None,
               limit: int | None = None,
               extra: Mapping[str, str] | None = None) -> list[Kbuild]:
        """The job's kbuild nodes of the last `days` days, as builds, newest first.

        `days` <= 0 asks for the whole history: the API is only askable by window
        (`created__gte`), and "no window" has to be a query it can answer, not the
        `created__gte` of a window of zero days.

        `extra` is applied **first**, so the four keys spelled here overwrite it
        rather than the other way round - the same precedence the deleted
        `_Narrowed` adapter had (`{**page_keys, **caller_keys}`), which is what
        makes adding this argument a change in *where* the keys are passed and not
        in *what* is asked.  Measured on production both ways: `?tree=riscv` answers
        `total=80`, `?tree=riscv&arch=riscv` answers `total=79`.
        """
        filters: dict[str, Any] = {str(key): str(value)
                                   for key, value in dict(extra or {}).items()}
        filters["name"] = KBUILD_JOB
        if days and int(days) > 0:
            filters["created__gte"] = _iso_ago(int(days))
        if tree:
            filters[TREE_FILTER] = tree
        if branch:
            filters[BRANCH_FILTER] = branch
        client = self._client()
        nodes = client.nodes(kind="kbuild", filters=filters, limit=limit)
        self.total = getattr(client, "last_total", None)
        builds = []
        for node in nodes:
            if not isinstance(node, dict):
                continue          # one malformed page item must not cost the batch
            try:
                builds.append(Kbuild.from_node(node))
            except ApiError:
                continue          # a node naming no build is not one we can run
        return sorted(builds, key=lambda build: (build.created, build.build_id), reverse=True)

    def _keep(self, builds: Iterable[Kbuild]) -> None:
        """Remember builds this collection has not got yet, one entry per build_id."""
        known = {build.build_id for build in self.items}
        for build in builds:
            if build.build_id not in known:
                known.add(build.build_id)
                self.items.append(build)

    def _client(self) -> Api:
        """The API client, or an ApiError naming what is missing."""
        if self.api is None:
            raise ApiError("Kbuilds needs an Api to ask which builds exist")
        return self.api


def _artifacts(raw: Any) -> dict[str, str]:
    """A node's `artifacts` as name -> URL, dropping entries that name no URL."""
    if not isinstance(raw, dict):
        return {}
    return {str(name): str(url) for name, url in raw.items()
            if isinstance(url, str) and url}


def build_id_of(artifacts: dict[str, str]) -> str:
    """The build id inside an artifact URL, or '' - fixed key order, never dict order."""
    for name in ARTIFACT_KEYS:
        found = BUILD_ID_RE.search(artifacts.get(name) or "")
        if found:
            return found.group(2)
    return ""


def _text(value: Any) -> str:
    """A field as the string this layer promises: '' for what the node does not carry."""
    return str(value) if value not in (None, "") else ""


def _stamp() -> str:
    """Now, in the one timestamp spelling this tree writes: UTC, second resolution.

    One owner, here, because the spelling is a contract between writers that
    never meet: a run's start, a pull act's `at`, the build a `publish_local()`
    files and the served record's `at` all have to sort and compare as strings
    (and `_age()` above reads the same shape back).  `lib/job.py` and every
    module of `lib/build/` import it from here instead of spelling `strftime`
    again - the rule `build_id_of()` already follows in this module.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_ago(days: int) -> str:
    """The ISO-8601 timestamp `days` days back (UTC, seconds).

    Every caller clamps a window; this is the second guard, because an absurd
    one reaches `time.gmtime` as an epoch outside the platform's range and comes
    back as `OSError: [Errno 75]` - which on a page is an HTTP 500, and a typo in
    a URL must not be able to produce one.
    """
    days = int(days)
    if days < 0 or days > MAX_WINDOW_DAYS:
        raise ConfigError(f"a window of {days} day(s) is outside 0..{MAX_WINDOW_DAYS}")
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400))


def _age(created: str) -> str:
    """`created` as `3h` / `2d`, or '' when it is not a timestamp this reader can read."""
    try:
        then = datetime.fromisoformat(created)
    except (TypeError, ValueError):
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - then).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"
