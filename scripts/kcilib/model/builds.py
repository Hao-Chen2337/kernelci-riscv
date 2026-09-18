# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The collection of builds this run knows about.

Builds is the set, Build is the element (kcilib.table.build).  It exists so a
puller, a merge and a hand-made build all land in the same container with one
card per build_id - and so nothing above has to know whether a build came from
the production API, the local one, or a kernel we compiled ourselves.

The card class it used to hold (Kbuild) is gone: a Kbuild was a BuildRef with
three extra fields, and the conversion between the two made a round trip
(docs/REFACTOR-D-BRIEF.md 2.1).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from kcilib.run.artifacts import build_id_from_artifacts as _build_id_of
from kcilib.table.build import (
    ORIGIN_API,
    ORIGIN_HANDMADE,
    Build,
    build_from_node,
)

from .nodes import KbuildPuller, KernelCINode, origin_for


class Builds:
    """A collection of builds, one per build_id."""

    def __init__(self, source: KbuildPuller | Builds | Sequence[Build] | None = None) -> None:
        """Empty, or filled from a puller, another collection, or cards.

        A puller is the only source that knows an origin of its own, so nodes
        pulled from one are converted with the origin of the API they came
        from; everything else keeps the origin it already carries.  Builds of
        another Builds are shared, its container is not.
        """
        self.builds: list[Build] = []
        if source is None:
            return
        if isinstance(source, KbuildPuller):
            for node in source:
                self._absorb(node, origin_for(source.api_url))
        elif isinstance(source, Builds):
            self.builds.extend(source.builds)
        else:
            for build in source:
                self._collect(build)

    # ---- collecting -----------------------------------------------------

    def add(self, item: KernelCINode | Build) -> Build:
        """Collect *item*; the build held for its build_id, new or existing.

        A node does not say where it came from - that is the fetcher's
        knowledge - so a node added here lands as ORIGIN_API; make() is how a
        build of our own gets its origin.  A node with no kernel artifact is
        refused by the table layer (ValueError): it cannot be run at all.
        """
        if isinstance(item, Build):
            return self._collect(item)
        return self._absorb(item, ORIGIN_API)

    def merge(self, other: KbuildPuller | Builds) -> None:
        """Fold *other* in; a build already held only gains what it lacks."""
        if isinstance(other, KbuildPuller):
            for node in other:
                self._absorb(node, origin_for(other.api_url))
            return
        for build in other.builds:
            self._collect(build)

    def make(self, *, tree: str, commit: str, kernel: str,
             modules: str | None = None, kselftest: str | None = None,
             config: str | None = None, describe: str | None = None,
             build_id: str | None = None, origin: str = ORIGIN_HANDMADE,
             labels: tuple = (), notes: str = "") -> Build:
        """Hand-make a build for a kernel no node describes (self-built).

        The id is read from the kernel URL when it names one; otherwise the
        commit names it and a note records that, so an id we invented never
        reads as an official one.
        """
        artifacts = {"kernel": kernel}
        if modules:
            artifacts["modules"] = modules
        if kselftest:
            artifacts["kselftest_tar_xz"] = kselftest
        if config:
            artifacts["_config"] = config
        resolved = build_id or _build_id_of(artifacts)
        note = notes
        if not resolved:
            if not commit:
                raise ValueError(
                    "a build needs an id: pass build_id, or a kernel URL or "
                    "commit that names one")
            resolved = commit[:12]
            reason = f"id from commit {resolved}: no id in the kernel URL"
            note = f"{notes}; {reason}" if notes else reason
        return self._collect(Build(
            resolved, artifacts, tree=tree, commit=commit, describe=describe,
            origin=origin, labels=labels, notes=note))

    # ---- reading --------------------------------------------------------

    def __iter__(self) -> Iterator[Build]:
        return iter(self.builds)

    def __len__(self) -> int:
        return len(self.builds)

    def __getitem__(self, index: int) -> Build:
        return self.builds[index]

    # ---- staying unique by build_id -------------------------------------

    def _collect(self, build: Build) -> Build:
        """Hold *build*, unless its build_id is held: then fill that one in."""
        held = self._find(build.build_id)
        if held is None:
            self.builds.append(build)
            return build
        held.merge(build)
        return held

    def _absorb(self, node: KernelCINode, origin: str) -> Build:
        """One node -> one build, through the table layer's conversion."""
        return self._collect(build_from_node(node.raw(), origin=origin))

    def _find(self, build_id: str) -> Build | None:
        """The build held for *build_id*, or None (ids are the identity)."""
        for build in self.builds:
            if build.build_id == build_id:
                return build
        return None
