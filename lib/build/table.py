# SPDX-License-Identifier: LGPL-2.1-or-later
"""The local table: the builds this machine has, as one JSON file (`layout.index()`).

Offline by construction - `index` fills it from the API, everything else reads
the file - which is what lets `table.py run` and the page work with no network.
"""

import json
import os
from dataclasses import asdict, fields

from .. import atomic, errors, layout
from ..kbuild import Kbuild
from ..tests import DEFAULT_TESTS, TESTS
from .model import Build

# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

class Builds:
    """The local table: the builds this machine has, as one JSON file."""

    def __init__(self, items=()):
        self.items = list(items)

    @classmethod
    def load(cls, path=None):
        """Read the table; a missing, unreadable or unparsable file is an empty table."""
        try:
            with open(path or layout.index(), encoding="utf-8") as handle:
                stored = json.load(handle)
            records = stored.values() if isinstance(stored, dict) else stored
            return cls(Build(_kbuild(record)) for record in records
                       if isinstance(record, dict) and record.get("build_id"))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path=None):
        """Write the table atomically: one object keyed by build id, keys sorted."""
        path = path or layout.index()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        atomic.write_json(path, {build.build_id: _record(build) for build in self.items},
                          indent=1, sort_keys=True)

    def fetch(self, api, tree="", days=7, limit=200):
        """Ask the API for builds of the last `days` days (`tree=''` = any) and fold them in.

        The cap is applied to *usable* builds, so the read itself stays uncapped:
        a window whose newest nodes are still running would otherwise fill the cap
        with builds nobody can run, and the table would register nothing.  A cap
        below one is refused rather than applied - `[:0]` registers nothing, and
        `[:-5]` silently drops the five newest builds, which are the five the
        caller asked for.
        """
        from .. import kbuild
        if int(limit) < 1:
            raise errors.ConfigError(f"--limit must be at least 1, got {limit}")
        self.merge(kbuild.Kbuilds(api).getdays(tree, days)[:int(limit)])

    def get(self, build_id):
        """The build held for `build_id`; a ConfigError when the table holds none."""
        for build in self.items:
            if build.build_id == build_id:
                return build
        raise errors.ConfigError(f"no build {build_id!r} in {layout.index()}")

    def newest(self):
        """The most recently created build here; a ConfigError when the table is empty."""
        if not self.items:
            raise errors.ConfigError(f"the build table {layout.index()} is empty")
        return max(self.items, key=_created)

    def merge(self, other):
        """Fold in a `Kbuilds` or another `Builds`: one entry per build_id, the first wins."""
        for item in other:
            kbuild = item.kbuild if isinstance(item, Build) else item
            if not kbuild.build_id:
                raise errors.ConfigError("a build with no build_id cannot go in the table")
            held = next((one for one in self.items if one.build_id == kbuild.build_id), None)
            if held is None:
                self.items.append(Build(kbuild))
            else:
                held.merge(kbuild)

    def remember(self, build):
        """Fold one pulled build into the table and save it: a pull is also a registration.

        `Build.make()` writes bytes and a pull record and knows nothing about the
        table, so `runday`, `run_latest`, the worker and every job's own `make()`
        left copies that the page could only render as "no card in the local
        table" - pulled, run, and not in the book, with a drill-down whose two
        buttons both refused with `no build ... in builds.json`.  Every command
        that pulls says so here instead, and the page's three facts stay three:
        card, bytes, act.

        The base is the file, read again here and not the copy the caller loaded
        before a download that can take twenty minutes: `save()` writes every
        record, so a stale snapshot would drop what another command registered
        while we pulled, and would put back a card the operator pruned.  A build
        the file already holds is left exactly as it is - the card is the
        operator's, a re-pull adds nothing to it that its own artifact URLs do
        not already say, and rewriting 27 records to say nothing is how two
        writers lose each other's work.  A build with no kbuild, or with no
        build_id, is a directory with no name to file it under.

        A pull that raised never reaches here: `make()` records its own failed
        act and the caller stops, so a failed pull leaves no card behind.
        """
        if build.kbuild is None or not build.kbuild.build_id:
            return self
        held = Builds.load()
        if not any(one.build_id == build.build_id for one in held):
            held.merge([build])
            held.save()
        self.items = held.items          # this handle now says what the file says
        return self

    def make(self, tests=None):
        """Download, for every build here, whatever a test it cannot run still needs."""
        for build in self.items:
            for test in (tests or DEFAULT_TESTS):
                entry = TESTS.get(test)
                if entry and build.missing(test):
                    build.make(entry["needs"])

    def __iter__(self):
        """Every build here, **newest first** - the order this table is read in.

        `items` is in the file's own order, and `save()` writes the file with
        `sort_keys=True`, so iterating the list directly meant build_id order:
        `table.py todo` printed the oldest unrun pair first while `summary`
        (`print()` below), `jobs` and `results.py` all print newest first, and
        `todo | head -1` named the wrong end of the table.  The sort is here and
        not in each reader because every reader of this table wants this order -
        `print()` sorts by the same key, `newest()` takes the same maximum, and
        two spellings of one order is how they drift apart.  A build the file
        gives no `created` (an entry with no card) sorts last, as it did before.
        """
        return iter(sorted(self.items, key=_created, reverse=True))

    def __len__(self):
        return len(self.items)

    def print(self, stream=None):
        """One line per build, newest first - `__iter__`'s order, not a second one."""
        for build in self:
            build.print(stream)


def _record(build):
    """One build as the object the table stores: the kbuild's own fields."""
    return asdict(build.kbuild) if build.kbuild is not None else {"build_id": build.build_id}


def _kbuild(record):
    """One stored object back as a `Kbuild`, dropping keys this version does not know."""
    known = {one.name for one in fields(Kbuild)}
    return Kbuild(**{key: value for key, value in record.items() if key in known})


def _created(build):
    """A build's creation time, or '' - the field the table sorts by."""
    return (build.kbuild.created if build.kbuild is not None else "") or ""
