# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Build references: turn one KernelCI node into a single table row.

Everything downstream needs a stable build identity, and a node id is not
it: ids are per-database, so local and production disagree. Stable instead
are the id in the artifact URLs and tree/commit; BuildRef keeps only what
the executor needs. Rationale: docs/docs/code-notes/B-delivery-buildref.md.
"""

import json
from dataclasses import dataclass, field

from kcilib.api import KernelCI
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

PRODUCTION_API = "https://api.kernelci.org"
REQUEST_TIMEOUT = 60


@dataclass
class BuildRef:
    """One row per build: identity, artifact URLs, provenance.

    *build_id* is half the primary key (the test name is the other half).
    """

    build_id: str
    artifacts: dict = field(default_factory=dict)
    tree: str | None = None
    branch: str | None = None
    commit: str | None = None
    describe: str | None = None
    created: str | None = None
    node_id: str | None = None          # source node id (a reference column)
    source: str = "official"            # official | local

    def missing_for(self, test):
        """Artifacts *test* is missing (empty tuple = it has them all).

        Missing artifacts are normal, not an error: a failed build has none.
        """
        needed = REQUIRED_FOR.get(test, ("kernel",))
        return tuple(key for key in needed if not self.artifacts.get(key))

    def as_row(self):
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


def build_ref_from_node(node, source="official"):
    """Turn a complete node into a BuildRef. Pure: no network, no disk.

    *node* is any KernelCI-shaped dict: official, copied or hand-made (which
    is why this layer takes nodes, not ids). build_id is parsed from the
    artifact URLs, falling back to the node id; a node with no kernel
    artifact raises ValueError, since it cannot be run at all.
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
    return BuildRef(
        build_id=build_id,
        artifacts={key: artifacts[key] for key in ARTIFACT_KEYS
                   if artifacts.get(key)},
        tree=revision.get("tree"),
        branch=revision.get("branch"),
        commit=revision.get("commit"),
        describe=revision.get("describe"),
        created=node.get("created"),
        node_id=str(node.get("id") or "") or None,
        source=source,
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

    def accepts(self, ref):
        """Apply locally the conditions the API does not support.

        Returns (ok, reason); reason is empty when ok is True, so a caller can
        report why nodes were dropped instead of filtering them silently.
        """
        if self.trees and ref.tree not in self.trees:
            return False, f"tree {ref.tree!r} not in {list(self.trees)}"
        if self.until and (ref.created or "") >= self.until:
            return False, f"created {ref.created} >= until {self.until}"
        for key in self.require:
            if not ref.artifacts.get(key):
                return False, f"missing artifact {key!r}"
        return True, ""


def build_refs_from_nodes(nodes, query=None, source="official"):
    """Nodes -> (refs, dropped); dropped is a list of (id, reason)."""
    query = query or BuildQuery()
    refs, dropped = [], []
    for node in nodes:
        try:
            ref = build_ref_from_node(node, source=source)
        except ValueError as error:
            dropped.append((str(node.get("id") or "?"), str(error)))
            continue
        ok, reason = query.accepts(ref)
        if ok:
            refs.append(ref)
        else:
            dropped.append((ref.build_id, reason))
    return refs, dropped


def fetch_nodes(query):
    """Ask the API for a batch of nodes, through kcilib.api (the only client).

    Only building the filter parameters is local knowledge here.
    """
    return KernelCI(query.api).nodes(**query.as_params())


def builds_from_production_api(query=None):
    """Production API -> (refs sorted by query.order, dropped (id, reason)).

    Read-only, no token needed.
    """
    query = query or BuildQuery()
    nodes = fetch_nodes(query)
    if query.result:
        # result is not an API filter, so filter locally: incomplete nodes come
        # back from the API too, with missing or incomplete artifacts.
        nodes = [n for n in nodes if n.get("result") == query.result]
    refs, dropped = build_refs_from_nodes(nodes, query)
    refs.sort(key=lambda r: r.created or "", reverse=(query.order == "newest"))
    return refs, dropped
