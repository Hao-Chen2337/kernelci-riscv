# SPDX-License-Identifier: LGPL-2.1-or-later
"""The machine interface: `/summary.json`, `/api/analysis/drift`, `/api/analysis/trend`.

Three answers that are contracts: fields are added here and none are
removed.  Each is computed from the same reads the pages use (`_state`, `all_locals`,
`remote_rows`), so a JSON reader and a page can never be told two different things
about one build - which is the whole reason they are here and not in `server.py`: the
route table says *which* URL answers, and what it answers is this."""

from typing import Any

from .. import errors, layout
from .. import re as re_mod
from ..drift import Drift
from ..i18n import DEFAULT_LANG, t
from ..kbuild import KBUILD_JOB, SCAN, Kbuilds
from ..re import Records
from .forms import _token
from .models import Filter
from .pairs import _artifact_of, _ref_of, _same_branch
from .schema import ACTIONS
from .values import _tally


class ReportsMixin:
    def summary(self, api: str = "") -> dict[str, Any]:
        """Everything the first screen shows - also the `/summary.json` contract.

        `api` is the raw `?api=` of the request (a name, an address, or nothing), so
        the machine interface can ask the same question the page can.  It goes through
        `self.apis.of()` exactly like a page's own query does: one spelling per base,
        and a value nobody knows falls back to the startup base.
        """
        table, records = self._state()
        check = Filter(limit=self.rows, origin="any", api=self.apis.of(api))
        remote = self.remote_rows(check)
        rows = self.local_rows(check)
        return {"remote": {"query": self.remote_query(check),
                           # The three counts, kept apart here too: the JSON is the
                           # same data the page prints, so it must not flatten them.
                           "shown": len(remote), "kept": remote.kept,
                           "total": remote.total, "limit": check.limit,
                           "coverage": remote.coverage(),
                           "rows": [self.remote_row(one, self.all_locals().get(one.build_id))
                                    for one in remote]},
                "local": [self.local_row(one) for one in rows],
                "correspondence": _tally(rows, {one.build_id for one in remote}),
                "pulls": self.pull_acts(),
                "jobs": self.job_rows(check),
                "runs": self.status(),
                "ledger": {"records": len(records), "tally": records.tally(),
                           "builds": len(Records.builds()), "dir": layout.results()},
                "table": {"builds": len(table), "file": layout.index()},
                "note": remote.note, "actions": list(ACTIONS)}

    def drift(self, older: str, newer: str, lang: str = DEFAULT_LANG,
              api: str = "", catalogue: "Kbuilds | None" = None) -> dict[str, Any]:
        """The config difference between two builds, by id - `{}` with a reason when unreadable.

        `api` is the request's raw `?api=`, read through the same `Apis.of()` the
        pages use, so `/api/analysis/drift?api=production` and the `/analysis` page
        with the box on `production` are one question.

        `catalogue` is the builds the caller has *already* read - on the page, the
        very rows its list offers (`_known_builds`).  `Drift` needs both builds
        to fetch their `.config`, and the API cannot be asked for a build id: without
        them it scans the window once per id.  On production, where
        `kbuild-gcc-14-riscv` answers nearly two thousand nodes, that was two scans of
        a thousand nodes on top of the read the page had already made - the reason
        `/analysis` took over fifty seconds.

        A caller with no page behind it (the `/api/analysis/drift` endpoint) gets one
        read made here instead, used for both ids: one read rather than two scans.
        """
        older, newer = _token(older), _token(newer)
        if not (older and newer):
            return {"error": t(lang, "error.two_build_ids"), "older": older, "newer": newer}
        base = self.apis.base(self.apis.of(api))
        client = self._client(base)
        if catalogue is None:
            # As wide as the scan it replaces (`kbuild.SCAN`), and made once.
            catalogue = Kbuilds(client, items=self.remote_rows(
                Filter(limit=SCAN, api=self.apis.of(api)), lang=lang))
        try:
            # `job` is the storage fallback's directory prefix (`drift._config_url`),
            # and it used to be `""` here: that built `kbuild-<id>/.config` where this
            # deployment's storage serves `kbuild-gcc-14-riscv-<id>/.config`, so the
            # fallback the docstring promises could only ever answer 404 - and the
            # refusal message named a URL nobody would have asked for
            # (`06-analysis.md` §A7.2, page-only: the CLI always passed its default).
            report = Drift.between(client, KBUILD_JOB, older, newer, catalogue=catalogue)
        except errors.KciError as exc:
            return {"error": str(exc), "older": older, "newer": newer,
                    "older_ref": _ref_of(catalogue, older),
                    "newer_ref": _ref_of(catalogue, newer),
                    "same": _same_branch(catalogue, older, newer)}
        return {"older": older, "newer": newer, "drifted": report.drifted(),
                "added": report.added, "removed": report.removed, "changed": report.changed,
                # The two sides as a reader names a build (tree/branch · describe), and
                # whether this is one kernel's drift at all: the numbers are the same
                # either way, but 616/618/99 across two trees must not be read as one
                # kernel moving (`06-analysis.md` §D1).  Both come from the catalogue
                # the caller already read - one dict scan, no request.
                "older_ref": _ref_of(catalogue, older),
                "newer_ref": _ref_of(catalogue, newer),
                # The raw artifacts, for the reader who wants the file rather than our
                # reading of it: the URL is already on the `Kbuild`, so this is a dict
                # lookup and not a read (`06-analysis.md` §A10.4's `可以打开一个文本查看`).
                "older_url": _artifact_of(catalogue, older, "_config"),
                "newer_url": _artifact_of(catalogue, newer, "_config"),
                "same": _same_branch(catalogue, older, newer),
                "summary": {"added": len(report.added), "removed": len(report.removed),
                            "changed": len(report.changed)}}

    def trend(self, test: str, scope: int = 20) -> dict[str, Any]:
        """One test's timeline: the series, and where it went pass -> fail.

        **Every field the record has, not five of them.**  A point used to carry
        `build_id`, `timestamp`, `verdict`, `source` and whether it is a regression -
        so the four facts a reader could see were in a `title=` and nothing else, and
        the `exit_code`, the `detail`, the log path and the TAP counts the record holds
        (`lib/out.py: RECORD_FIELDS`) never reached the page that had the file open.
        The selected run's block (`_record_block`) is what reads them, and a cell
        carries enough to name *one* record: `(build_id, timestamp)` is unique in the
        ledger (`var/results/<build>/<test>.json` is one file per pair, and the file's
        own timestamp is the record's).

        `/api/analysis/trend` is a contract: fields are added here and
        none are removed.
        """
        records = self._state()[1]
        series = records.series(test)[-max(1, int(scope)):]
        pairs = re_mod.transitions(records, test)
        marks = {one.build_id for pair in pairs for one in pair}
        return {"test": test,
                "points": [{"build_id": one.build_id, "timestamp": one.timestamp,
                            "verdict": one.verdict, "source": one.source,
                            "exit_code": one.exit_code, "detail": one.detail,
                            "results": dict(one.results or {}),
                            "log": one.log, "artifacts_dir": one.artifacts_dir,
                            "revision": dict(one.revision or {}), "job": one.job,
                            "regression": one.build_id in marks} for one in series],
                "transitions": len(pairs)}



