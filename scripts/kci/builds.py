# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The middle kbuild layer: one build as a card, and the cards collected.

A Kbuild holds what running a test needs of a build - an id, artifact URLs,
revision - plus the fields this layer adds (origin, labels, notes); Kbuilds is
the collection of them.  Both wrap kcilib.table.buildref, so a card and a
table row come out of the one conversion and cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING

from kcilib.run.artifacts import build_id_from_artifacts as _build_id_of
from kcilib.table import buildref as _buildref
from kcilib.table import jobspec as _jobspec

from .nodes import (
    ORIGIN_API,
    ORIGIN_API_LOCAL,
    ORIGIN_HANDMADE,
    KbuildPuller,
    KernelCINode,
    origin_for,
)

if TYPE_CHECKING:                       # .jobs imports this module
    from .jobs import Job, Jobs

# Origins the table layer files as "official": the production API and the
# local one serve the same kind of node.  Everything else - imported,
# self-built, handmade - is "local", because no upstream index has it.
_OFFICIAL_ORIGINS = (ORIGIN_API, ORIGIN_API_LOCAL)

# What Kbuild.merge() fills in when this card lacks it and the other has it.
# Artifacts are merged apart, key by key, since they are a mapping.
_FILLABLE = ("tree", "branch", "commit", "describe", "created", "node_id")


def _source_for(origin: str) -> str:
    """Origin -> the table layer's source column (official | local)."""
    return "official" if origin in _OFFICIAL_ORIGINS else "local"


class Kbuild:
    """One build card: what we run needs, plus our own fields."""

    def __init__(self, build_id: str,
                 artifacts: Mapping[str, str] | None = None, *,
                 tree: str | None = None, branch: str | None = None,
                 commit: str | None = None, describe: str | None = None,
                 created: str | None = None, node_id: str | None = None,
                 origin: str = ORIGIN_API, labels: tuple = (),
                 notes: str = "") -> None:
        self.build_id: str = build_id
        self.artifacts: dict[str, str] = dict(artifacts or {})
        self.tree: str | None = tree
        self.branch: str | None = branch
        self.commit: str | None = commit
        self.describe: str | None = describe
        self.created: str | None = created
        self.node_id: str | None = node_id
        self.origin: str = origin
        self.labels: tuple[str, ...] = tuple(labels)
        self.notes: str = notes

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

        Delegated to the table layer, which owns the requirement table; an
        empty answer here means "this test can be scheduled on this build".
        """
        return list(self._ref().missing_for(test))

    def merge(self, other: Kbuild) -> bool:
        """Fill in what this card lacks from *other*; True when it changed.

        Same build_id only: two ids are two builds, and blending them would
        file one build's artifacts under the other's name.  Fields already set
        win, so the first source (usually the more detailed one) survives.
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
        extra = tuple(label for label in other.labels
                      if label not in self.labels)
        if extra:
            self.labels = self.labels + extra
            changed = True
        if other.notes and not self.notes:
            self.notes = other.notes
            changed = True
        return changed

    def to_jobs(self, tests: Sequence[str] | None = None) -> Jobs:
        """This card -> the jobs to run on it (tests it cannot support skip).

        Imported here, not at module level: .jobs imports this module.
        """
        from .jobs import Job, Jobs
        names = tuple(tests) if tests else tuple(_jobspec.DEFAULT_TESTS)
        return Jobs([
            Job(self.build_id, test, artifacts=dict(self.artifacts),
                origin=self.origin, notes=self.notes, build=self)
            for test in names if not self.missing_for(test)
        ])

    def __str__(self) -> str:
        """The id, then the revision, so a log line says which kernel it is."""
        where = " ".join(part for part in (self.tree, self.describe) if part)
        return f"{self.build_id[:12]} ({where})" if where else self.build_id

    # ---- the one conversion into the table layer ------------------------

    def _ref(self) -> _buildref.BuildRef:
        """This card as the table layer's BuildRef (no second conversion)."""
        return _buildref.BuildRef(
            build_id=self.build_id, artifacts=dict(self.artifacts),
            tree=self.tree, branch=self.branch, commit=self.commit,
            describe=self.describe, created=self.created,
            node_id=self.node_id, source=_source_for(self.origin))


class Kbuilds:
    """The middle kbuild layer: a collection of Kbuild cards."""

    def __init__(
            self,
            source: KbuildPuller | Kbuilds | Sequence[Kbuild] | None = None
    ) -> None:
        """Empty, or filled from a puller, another collection, or cards.

        A puller is the only source that knows an origin of its own, so nodes
        pulled from one are converted with the origin of the API they came
        from; everything else keeps the origin it already carries.  Cards of
        another Kbuilds are shared, its container is not.
        """
        self.builds: list[Kbuild] = []
        if source is None:
            return
        if isinstance(source, KbuildPuller):
            for node in source:
                self._absorb(node, origin_for(source.api_url))
        elif isinstance(source, Kbuilds):
            self.builds.extend(source.builds)
        else:
            for build in source:
                self._collect(build)

    # ---- collecting -----------------------------------------------------

    def add(self, item: KernelCINode | Kbuild) -> Kbuild:
        """Collect *item*; the card held for its build_id, new or existing.

        A node does not say where it came from - that is the fetcher's
        knowledge - so a node added here lands as ORIGIN_API; make() is how a
        card of our own gets its origin.  A node with no kernel artifact is
        refused by the table layer (ValueError): it cannot be run at all.
        """
        if isinstance(item, Kbuild):
            return self._collect(item)
        return self._absorb(item, ORIGIN_API)

    def merge(self, other: KbuildPuller | Kbuilds) -> None:
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
             labels: tuple = (), notes: str = "") -> Kbuild:
        """Hand-make a card for a kernel no node describes (self-built).

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
                    "a card needs an id: pass build_id, or a kernel URL or "
                    "commit that names one")
            resolved = commit[:12]
            reason = f"id from commit {resolved}: no id in the kernel URL"
            note = f"{notes}; {reason}" if notes else reason
        return self._collect(Kbuild(
            resolved, artifacts, tree=tree, commit=commit, describe=describe,
            origin=origin, labels=labels, notes=note))

    def to_jobs(self, tests: Sequence[str] | None = None) -> Jobs:
        """Every card x the tests it can support -> one Jobs container."""
        from .job import Jobs
        jobs: list[Job] = []
        for build in self.builds:
            jobs.extend(build.to_jobs(tests))
        return Jobs(jobs)

    # ---- reading --------------------------------------------------------

    def __iter__(self) -> Iterator[Kbuild]:
        return iter(self.builds)

    def __len__(self) -> int:
        return len(self.builds)

    def __getitem__(self, index: int) -> Kbuild:
        return self.builds[index]

    # ---- staying unique by build_id -------------------------------------

    def _collect(self, card: Kbuild) -> Kbuild:
        """Hold *card*, unless its build_id is held: then fill that one in."""
        held = self._find(card.build_id)
        if held is None:
            self.builds.append(card)
            return card
        held.merge(card)
        return held

    def _absorb(self, node: KernelCINode, origin: str) -> Kbuild:
        """One node -> one card, through the table layer's conversion."""
        ref = _buildref.build_ref_from_node(
            node.raw(), source=_source_for(origin))
        return self._collect(Kbuild(
            ref.build_id, dict(ref.artifacts), tree=ref.tree,
            branch=ref.branch, commit=ref.commit, describe=ref.describe,
            created=ref.created, node_id=ref.node_id, origin=origin))

    def _find(self, build_id: str) -> Kbuild | None:
        """The card held for *build_id*, or None (ids are the identity)."""
        for build in self.builds:
            if build.build_id == build_id:
                return build
        return None
