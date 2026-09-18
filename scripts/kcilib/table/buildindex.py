# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Local build index: a table that only answers "which builds can be run".

Only what is needed to run is kept (build_id, tree, commit, artifact URLs) plus
one own field, source; a local copy of full nodes would be a second truth that
drifts. The key is build_id, not the node id, which is per-instance: build_id
comes from the artifact URLs and is stable. Defaults to work/builds.db (sqlite,
gitignored; deleting it loses no upstream data).
"""

import os
import sqlite3

from kcilib import repo_root
from kcilib.core import layout
from kcilib.table.build import Build

# Walked up from the package (kcilib.repo_root), never a fixed dirname() depth.
ROOT = repo_root()
DEFAULT_PATH = os.fspath(layout.index())

_COLUMNS = ("build_id", "tree", "branch", "commit", "describe", "created",
            "node_id", "source", "artifacts")
# `commit` is a SQL keyword: quoted as an identifier, plain as a Python name.
# Unquoted, SQLite read "commit TEXT," as the COMMIT statement - a syntax error.
_SQL_COLUMNS = tuple(f'"{name}"' if name == "commit" else name
                     for name in _COLUMNS)
_INSERT = ("INSERT INTO builds (" + ", ".join(_SQL_COLUMNS) + ") VALUES ("
           + ", ".join("?" * len(_COLUMNS)) + ") ON CONFLICT(build_id) DO UPDATE"
           " SET artifacts = excluded.artifacts, source = excluded.source")
_SELECT = "SELECT " + ", ".join(_SQL_COLUMNS) + " FROM builds"


class BuildIndex:
    """The build index table. Writes are idempotent: add() returns False for a known id."""

    def __init__(self, path=None):
        self.path = path or os.environ.get("KCI_BUILD_INDEX") or DEFAULT_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS builds ("
            " build_id TEXT PRIMARY KEY,"
            ' tree TEXT, branch TEXT, "commit" TEXT, describe TEXT,'
            " created TEXT, node_id TEXT, source TEXT, artifacts TEXT,"
            " first_seen TEXT DEFAULT CURRENT_TIMESTAMP)")
        self._db.commit()

    def add(self, build):
        """Insert a row, or refresh the artifact URLs of a build already known.

        Returns True for a new build, so callers can report how many were added
        instead of reading idempotency as "nothing happened".
        """
        row = build.as_row()
        known = self._db.execute(
            "SELECT build_id FROM builds WHERE build_id = ?",
            (build.build_id,)).fetchone()
        self._db.execute(_INSERT,
                         tuple(row[column] for column in _COLUMNS))
        self._db.commit()
        return known is None

    def add_all(self, builds):
        """Insert many. Returns (added, already known)."""
        added = sum(1 for build in builds if self.add(build))
        return added, len(builds) - added

    def get(self, build_id):
        row = self._db.execute(_SELECT + " WHERE build_id = ?",
                               (build_id,)).fetchone()
        return self._row_to_build(row) if row else None

    def all(self):
        rows = self._db.execute(_SELECT + " ORDER BY created DESC").fetchall()
        return [self._row_to_build(row) for row in rows]

    def newest(self, count):
        return self.all()[:count]

    def count(self):
        return self._db.execute("SELECT COUNT(*) FROM builds").fetchone()[0]

    @staticmethod
    def _row_to_build(row):
        """One row back as a Build - kcilib.table.build owns that conversion."""
        return Build.from_row(dict(zip(_COLUMNS, row)))
