# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""本地构建索引:一张只回答"有哪些构建可跑"的表。

为什么是索引而不是数据库:构建的全部信息已经在 KernelCI 的 API 里了,本地再存
一份完整节点就是第二份真相,迟早对不上。这里只存"够不够跑"的那几列
(build_id / tree / commit / 构件 URL),外加唯一一个自有字段 source(这一行是
官方搬来的还是自己造的)。

键是 build_id,不是节点 id:节点 id 由"哪个库"分配,本地库和生产库各发各的,
同一个构建在两边的 id 毫无关系(见 kcilib/table/buildref.py 的说明)。build_id 是从
构件 URL 解析出来的,跨库稳定。

默认落在 work/builds.db(sqlite,单文件,无服务)。work/ 是 gitignore 的,删掉它
不丢任何上游数据 —— 重跑一次 index 就回来了。
"""

import json
import os
import sqlite3

from kcilib import repo_root
from kcilib.table.buildref import ARTIFACT_KEYS, BuildRef

# Walked up (kcilib.repo_root), not counted: see that function for the bug a
# fixed dirname() depth caused after the package move.
ROOT = repo_root()
DEFAULT_PATH = os.path.join(ROOT, "work", "builds.db")

_COLUMNS = ("build_id", "tree", "branch", "commit", "describe", "created",
            "node_id", "source", "artifacts")
# `commit` is a SQL keyword: every appearance as an IDENTIFIER is quoted, while the
# Python-side name stays unquoted. (An unquoted column made SQLite parse
# "commit TEXT," as the COMMIT statement - a syntax error at CREATE TABLE.)
_SQL_COLUMNS = tuple(f'"{name}"' if name == "commit" else name
                     for name in _COLUMNS)
_INSERT = ("INSERT INTO builds (" + ", ".join(_SQL_COLUMNS) + ") VALUES ("
           + ", ".join("?" * len(_COLUMNS)) + ") ON CONFLICT(build_id) DO UPDATE"
           " SET artifacts = excluded.artifacts, source = excluded.source")
_SELECT = "SELECT " + ", ".join(_SQL_COLUMNS) + " FROM builds"


class BuildIndex:
    """构建索引表。所有写入都是幂等的:add() 对已知的 build_id 返回 False。"""

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

    def add(self, ref):
        """插入一行;已经存在就更新构件地址(同一个构建可能补传产物)。

        返回 True 表示这是新构建 —— 调用方靠它给出"这次多了几个"的答案,而不是
        把幂等悄悄当成"什么都没发生"。
        """
        row = ref.as_row()
        known = self._db.execute(
            "SELECT build_id FROM builds WHERE build_id = ?",
            (ref.build_id,)).fetchone()
        self._db.execute(_INSERT,
                         tuple(row[column] for column in _COLUMNS))
        self._db.commit()
        return known is None

    def add_all(self, refs):
        """批量插入。返回 (新增数, 已知数)。"""
        added = sum(1 for ref in refs if self.add(ref))
        return added, len(refs) - added

    def get(self, build_id):
        row = self._db.execute(_SELECT + " WHERE build_id = ?",
                               (build_id,)).fetchone()
        return self._row_to_ref(row) if row else None

    def all(self):
        rows = self._db.execute(_SELECT + " ORDER BY created DESC").fetchall()
        return [self._row_to_ref(row) for row in rows]

    def newest(self, count):
        return self.all()[:count]

    def count(self):
        return self._db.execute("SELECT COUNT(*) FROM builds").fetchone()[0]

    @staticmethod
    def _row_to_ref(row):
        values = dict(zip(_COLUMNS, row))
        artifacts = json.loads(values.pop("artifacts") or "{}")
        return BuildRef(
            artifacts={key: value for key, value in artifacts.items()
                       if key in ARTIFACT_KEYS and value},
            **values)
