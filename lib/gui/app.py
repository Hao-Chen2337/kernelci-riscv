# SPDX-License-Identifier: LGPL-2.1-or-later
"""`Gui`: the object the entry point builds, assembled out of the modules around it.

The fields (`host`, `port`, `rows`, `refresh`, `api`, and the two test overrides that
hand a page a fixed table and ledger), `serve()`, and the class itself - and nothing
else: every method lives in the module that owns what it does (`reads`, `actions`,
`shell`, and one module per page) and is mixed in here, so `Gui` is still the one name
the entry point and the tools import and `from lib import gui; gui.Gui(...)` still
works.

The field order is the dataclass's, so `Gui(port=..., rows=..., refresh=..., api=...)`
keeps its positional meaning; the bases are order-free, since no method calls `super()`."""

from dataclasses import dataclass

from . import server
from .actions import ActionsMixin
from .activities import ActivitiesMixin
from .fields import FieldsMixin
from .pages.analysis import AnalysisMixin
from .pages.builds import BuildsMixin
from .pages.jobs import JobsMixin
from .pages.runs import RunsMixin
from .pages.worker import WorkerMixin
from .reads import ReadsMixin
from .reports import ReportsMixin
from .schema import HOST, PORT, REFRESH, ROWS
from .shell import ShellMixin


@dataclass
class Gui(FieldsMixin, ReadsMixin, ActivitiesMixin, ReportsMixin, ActionsMixin, ShellMixin,
          BuildsMixin, JobsMixin, RunsMixin, WorkerMixin, AnalysisMixin):
    """The pages: what the API has, what we hold, and the record that ties the two."""

    host: str = HOST
    port: int = PORT
    rows: int = ROWS
    refresh: int = REFRESH
    api_url: str = ""
    # Explicit overrides for tests and for anything that wants to hand the page a
    # fixed table and ledger (`/tmp/**`'s probes do exactly that).  Left as `None`
    # by the entry point: a page that froze its two local reads at startup showed
    # yesterday's ledger until it was restarted.
    builds: object = None
    records: object = None
    api: object = None
    # No `note` here on purpose: the server is threaded, so a failure kept on the
    # instance would be printed by whichever request was rendering at that moment.
    # Every read returns its own reason instead (see `Remote.note`).

    def serve(self) -> int:
        """Serve until interrupted; a taken port is reported, never silently swapped."""
        return server.serve(self)
