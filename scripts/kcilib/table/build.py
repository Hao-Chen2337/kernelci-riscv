# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""A build: one KernelCI kbuild, as the single object everything speaks.

Build is the vocabulary.  It is the table's row (as_row/from_row), the card the
model hands around (artifacts, revision, origin, notes) and the thing a test
asks for artifacts (missing_for).  It used to be three classes - BuildRef in
this layer, Kbuild in the model, and the raw node dict - and the conversions
between them made a round trip: a card was written out as a row and read back as
a card, while jobs_from_build() did on the far side exactly what
Kbuild.to_jobs() already did.  One concept, one name, one place.

Identity is build_id, not the node id: node ids are per-database, so the local
and the production API disagree about the same build.  build_id is parsed out of
the artifact URLs and is therefore the same everywhere.

Rationale: docs/REFACTOR-D-BRIEF.md 2.1.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from kcilib.api import PRODUCTION_API, KernelCI
from kcilib.run.artifacts import build_id_from_artifacts

# Artifact keys the executor knows, named as upstream renders them; _config
# is only used for drift, but is the sole source of the build configuration.
ARTIFACT_KEYS = ("kernel", "kselftest_tar_xz", "kselftest", "modules", "_config")

# Minimum artifacts per test: a kernel always, plus the selftest tarball.
REQUIRED_FOR = {
    "boot": ("kernel",),
    "kselftest-riscv": ("kernel", "kselftest_tar_xz"),
    "kselftest-kvm": ("kernel", "kselftest_tar_xz", "modules"),
}

# Where a build came from.  These live here, with the object they describe,
# because every layer above (table, model, sources) needs to name an origin and
# none of them may import the model back.
ORIGIN_API = "api"
ORIGIN_API_LOCAL = "api_local"
ORIGIN_SELF_BUILD = "self_build"
ORIGIN_IMPORTED = "imported"
ORIGIN_HANDMADE = "handmade"

# Origins an upstream index would also know about; the rest are ours alone.
OFFICIAL_ORIGINS = (ORIGIN_API, ORIGIN_API_LOCAL)

# What merge() fills in when this build lacks it and the other has it.
# Artifacts are merged apart, key by key, since they are a mapping.
_FILLABLE = ("tree", "branch", "commit", "describe", "created", "node_id")


def source_for(origin: str) -> str:
    """Origin -> the coarse official|local column the index stores."""
    return "official" if origin in OFFICIAL_ORIGINS else "local"


@dataclass
class Build:
    """One build.  Everything a run needs of it, plus what we know about it."""

    build_id: str
    artifacts: dict = field(default_factory=dict)
    tree: str | None = None
    branch: str | None = None
    commit: str | None = None
    describe: str | None = None
    created: str | None = None
    node_id: str | None = None          # source node id (a reference column)
    origin: str = ORIGIN_API            # api | api_local | self_build | ...
    labels: tuple = ()
    notes: str = ""

    @property
    def source(self) -> str:
        """The index's coarse column - derived, so it cannot disagree with origin."""
        return source_for(self.origin)

    # ---- the artifacts the executor wants, under its own names -----------

    @property
    def kernel(self) -> str | None:
        """The kernel image URL; None when this build shipped none."""
        return self.artifacts.get("kernel") or None

    @property
    def modules(self) -> str | None:
        """The modules tarball URL (kselftest-kvm needs it)."""
        return self.artifacts.get("modules") or None

    @property
    def kselftest(self) -> str | None:
        """The selftest tarball, under either of the API's two spellings."""
        return (self.artifacts.get("kselftest")
                or self.artifacts.get("kselftest_tar_xz") or None)

    @property
    def config(self) -> str | None:
        """The kernel config artifact (drift checks read it)."""
        return self.artifacts.get("_config") or None

    # ---- what a test needs of this build --------------------------------

    def missing_for(self, test: str) -> list[str]:
        """Artifacts *test* needs and this build has not (empty = it can run).

        Missing artifacts are normal, not an error: a failed build has none.
        An empty answer means "this test can be scheduled on this build".
        """
        needed = REQUIRED_FOR.get(test, ("kernel",))
        return [key for key in needed if not self.artifacts.get(key)]

    def merge(self, other: Build) -> bool:
        """Fill in what this build lacks from *other*; True when it changed.

        Same build_id only: two ids are two builds, and blending them would file
        one build's artifacts under the other's name.  Fields already set win,
        so the first source (usually the more detailed one) survives.
        """
        if other.build_id != self.build_id:
            return False
        changed = False
        for key, value in other.artifacts.items():
            if value and not self.artifacts.get(key):
                self.artifacts[key] = value
                changed = True
        for name in _FILLABLE:
            mine, theirs = getattr(self, name), getattr(other, name)
            if mine is None and theirs is not None:
                setattr(self, name, theirs)
                changed = True
        extra = tuple(label for label in other.labels if label not in self.labels)
        if extra:
            self.labels = self.labels + extra
            changed = True
        if other.notes and not self.notes:
            self.notes = other.notes
            changed = True
        return changed

    def __str__(self) -> str:
        """The id, then the revision, so a log line says which kernel it is."""
        where = " ".join(part for part in (self.tree, self.describe) if part)
        return f"{self.build_id[:12]} ({where})" if where else self.build_id

    # ---- storage --------------------------------------------------------

    def as_row(self) -> dict:
        """The SQLite row: exactly the columns the index table stores."""
        return {
            "build_id": self.build_id,
            "tree": self.tree,
            "branch": self.branch,
            "commit": self.commit,
            "describe": self.describe,
            "created": self.created,
            "node_id": self.node_id,
            "source": self.source,
            "artifacts": json.dumps(self.artifacts, sort_keys=True),
        }

    @classmethod
    def from_row(cls, row: Mapping) -> Build:
        """The index row back as a build (the inverse of as_row())."""
        values = dict(row)
        artifacts = json.loads(values.pop("artifacts") or "{}")
        source = values.pop("source", "official")
        return cls(
            artifacts={key: value for key, value in artifacts.items()
                       if key in ARTIFACT_KEYS and value},
            origin=ORIGIN_API if source == "official" else ORIGIN_HANDMADE,
            **values)


def build_from_node(node, origin=ORIGIN_API) -> Build:
    """Turn a complete node into a Build. Pure: no network, no disk.

    *node* is any KernelCI-shaped dict: official, copied or hand-made (which is
    why this layer takes nodes, not ids).  build_id is parsed from the artifact
    URLs, falling back to the node id; a node with no kernel artifact raises
    ValueError, since it cannot be run at all.
    """
    if not isinstance(node, dict):
        raise TypeError(f"a node must be a dict, got {type(node).__name__}")
    artifacts = node.get("artifacts") or {}
    if not artifacts.get("kernel"):
        raise ValueError(
            f"node {node.get('id') or '?'} has no kernel artifact; it cannot "
            "be run, so it does not belong in the build index")
    revision = (node.get("data") or {}).get("kernel_revision") or {}
    build_id = build_id_from_artifacts(artifacts) or str(node.get("id") or "")
    if not build_id:
        raise ValueError("node has neither a build id in its artifact URLs nor "
                         "a node id; nothing stable to file it under")
    return Build(
        build_id=build_id,
        artifacts={key: artifacts[key] for key in ARTIFACT_KEYS
                   if artifacts.get(key)},
        tree=revision.get("tree"),
        branch=revision.get("branch"),
        commit=revision.get("commit"),
        describe=revision.get("describe"),
        created=node.get("created"),
        node_id=str(node.get("id") or "") or None,
        origin=origin,
    )


@dataclass
class BuildQuery:
    """Which builds to look for: explicit fields, no "last N days" guess.

    Each field maps to one API filter parameter (or one local filter), so the
    call site reads as what it finds rather than as a day-count magic number.
    """

    job: str = "kbuild-gcc-14-riscv"
    trees: tuple = ()               # empty = any tree
    result: str | None = "pass"     # "pass" / None (all); local filter
    since: str | None = None        # ISO8601, inclusive
    until: str | None = None        # ISO8601, exclusive (local)
    require: tuple = ("kernel",)    # artifact keys that must exist
    limit: int = 200
    order: str = "newest"           # newest | oldest
    api: str = PRODUCTION_API

    def as_params(self):
        """Filters the API itself supports; the rest are applied locally."""
        params = {"kind": "kbuild", "name": self.job, "limit": str(self.limit)}
        if self.since:
            params["created__gte"] = self.since
        if len(self.trees) == 1:
            params["data.kernel_revision.tree"] = self.trees[0]
        return params

    def accepts(self, build):
        """Apply locally the conditions the API does not support.

        Returns (ok, reason); reason is empty when ok is True, so a caller can
        report why nodes were dropped instead of filtering them silently.
        """
        if self.trees and build.tree not in self.trees:
            return False, f"tree {build.tree!r} not in {list(self.trees)}"
        if self.until and (build.created or "") >= self.until:
            return False, f"created {build.created} >= until {self.until}"
        for key in self.require:
            if not build.artifacts.get(key):
                return False, f"missing artifact {key!r}"
        return True, ""


def builds_from_nodes(nodes, query=None, origin=ORIGIN_API):
    """Nodes -> (builds, dropped); dropped is a list of (id, reason)."""
    query = query or BuildQuery()
    builds, dropped = [], []
    for node in nodes:
        try:
            build = build_from_node(node, origin=origin)
        except ValueError as error:
            dropped.append((str(node.get("id") or "?"), str(error)))
            continue
        ok, reason = query.accepts(build)
        if ok:
            builds.append(build)
        else:
            dropped.append((build.build_id, reason))
    return builds, dropped


def fetch_nodes(query):
    """Ask the API for a batch of nodes, through kcilib.api (the only client).

    Only building the filter parameters is local knowledge here.
    """
    return KernelCI(query.api).nodes(**query.as_params())


def builds_from_production_api(query=None):
    """Production API -> (builds sorted by query.order, dropped (id, reason)).

    Read-only, no token needed.
    """
    query = query or BuildQuery()
    nodes = fetch_nodes(query)
    if query.result:
        # result is not an API filter, so filter locally: incomplete nodes come
        # back from the API too, with missing or incomplete artifacts.
        nodes = [n for n in nodes if n.get("result") == query.result]
    builds, dropped = builds_from_nodes(nodes, query)
    builds.sort(key=lambda b: b.created or "", reverse=(query.order == "newest"))
    return builds, dropped
