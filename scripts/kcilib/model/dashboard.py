# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The local read-only job-table page, as a background process.

scripts/dashboard.py is the page (it renders the local job table, binds
127.0.0.1 and writes nothing); `./run.sh dashboard` is its entry point.  This
class starts that script, reads back the URL it really bound - --port is a
preference, a taken port moves the page to the next free one - and stops it
again.  It renders nothing itself.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

from kcilib import repo_root
from kcilib.core.ports import port_is_free

# Once the page is serving it prints its banner, and the URL in that banner is
# the port it REALLY bound (it binds before printing, so a URL seen here is a
# URL that answers).  A guard reads this text out of scripts/dashboard.py, so
# rewording the banner fails loudly instead of silently downgrading every
# start() to "the port you asked for".
BANNER = "local job table on "
URL_IN_BANNER = re.compile(re.escape(BANNER) + r"(http://\S+)")

# `./run.sh dashboard`'s own default, and how long the page may take to print
# its banner (it imports kernelci-core's config before it binds).
DEFAULT_PORT = 8079
START_TIMEOUT = 30.0
STOP_TIMEOUT = 10.0

# How much of the page's own output is kept for a failure message; the rest is
# dropped as it arrives (see _watch: the pipe has to stay drained).
TAIL_LINES = 50


def _url_in(text: str) -> str:
    """The URL of the page's banner in *text*, or "" for anything else."""
    match = URL_IN_BANNER.search(text)
    return match.group(1) if match else ""


class Dashboard:
    """The read-only local job table page, started and stopped from here.

    ``notes`` carries what could not be read back (today: a page that stayed
    alive without printing its banner, so the requested port was assumed).
    """

    def __init__(self, port: int = DEFAULT_PORT, api_url: str | None = None,
                 rows: int | None = None) -> None:
        """*port* is a preference; *api_url*/*rows* are passed only when given.

        Leaving api_url None keeps the page's own default (kcilib.api's local
        URL), which is the same one run.sh would use - spelling it again
        here would be a second default that can drift.
        """
        self.root: Path = Path(repo_root())
        self.port: int = port
        self.api_url: str | None = api_url
        self.rows: int | None = rows
        self.notes: list[str] = []
        self._proc: subprocess.Popen[str] | None = None
        self._url: str = ""
        self._tail: deque[str] = deque(maxlen=TAIL_LINES)

    # ---- the command line (asserted by a guard, never executed by it) ----

    def _argv(self) -> list[str]:
        """The command `./run.sh dashboard` runs, as a list.

        No --host: the page's own default is 127.0.0.1, and a read-only page
        must not be talked into binding anything else.
        """
        argv = [sys.executable, str(self.root / "scripts" / "dashboard.py"),
                "--port", str(self.port)]
        if self.api_url:
            argv += ["--api-url", self.api_url]
        if self.rows is not None:
            argv += ["--rows", str(self.rows)]
        return argv

    @property
    def url(self) -> str:
        """The page's URL: the one it bound, or the one it would bind."""
        return self._url or f"http://127.0.0.1:{self.port}/"

    # ---- running it ------------------------------------------------------

    def start(self) -> str:
        """Start the page and return the URL it is serving on.

        --port is a preference, so the URL is read back from the page's own
        banner instead of assumed; if the process is alive but never printed
        one, the requested port is returned and `notes` says so.  A page that
        exited instead of serving raises RuntimeError carrying its output.
        """
        if self.is_up():
            return self.url
        self._tail.clear()
        self._url = ""
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self._proc = subprocess.Popen(
            self._argv(), cwd=str(self.root), env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True)
        printed = self._watch(self._proc, timeout=START_TIMEOUT)
        if self._url:
            self.port = urlsplit(self._url).port or self.port
            return self._url
        if self._proc.poll() is not None:
            raise RuntimeError(
                f"scripts/dashboard.py exited {self._proc.returncode} instead "
                f"of serving: {self.output() or '(no output)'}")
        if not printed:
            self.notes.append(
                f"the page did not print its banner within "
                f"{START_TIMEOUT:.0f}s; assuming the requested port "
                f"{self.port}")
        return self.url

    def stop(self) -> int:
        """Stop the page and return its exit status (0 when none was running).

        Terminated, then killed if it does not go within STOP_TIMEOUT: the page
        holds no state, so there is nothing to lose by asking twice.  The
        status of a process stopped by a signal is negative (-15 for
        SIGTERM).
        """
        proc = self._proc
        if proc is None or proc.poll() is not None:
            self._proc = None
            self._url = ""
            return 0
        proc.terminate()
        try:
            proc.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=STOP_TIMEOUT)
        status = proc.returncode or 0
        self._proc = None
        self._url = ""
        return status

    def is_up(self) -> bool:
        """True while the page THIS object started is still serving.

        The answer comes from the child and from a bind of its port - the probe
        kcilib.core.ports owns, the same one the stack makes - never from an
        HTTP request, which would make this class a client of its own page.
        """
        if self._proc is None or self._proc.poll() is not None:
            return False
        return not port_is_free(self.port)

    def output(self) -> str:
        """The page's own output, as far as it was kept (TAIL_LINES)."""
        return "\n".join(self._tail)

    def _watch(self, proc: subprocess.Popen[str], timeout: float) -> bool:
        """Read the page's output until its banner appears; is *timeout* up?

        Read in a thread because readline() on a pipe takes no deadline,
        and the pipe must be drained for as long as the page lives: a page
        whose output nobody reads blocks on a full pipe the next time
        somebody refreshes it.
        """
        found = threading.Event()

        def read() -> None:
            stream: IO[str] | None = proc.stdout
            if stream is None:
                found.set()
                return
            for line in stream:
                self._tail.append(line.rstrip("\n"))
                if not self._url:
                    self._url = _url_in(line)
                    if self._url:
                        found.set()
            found.set()

        threading.Thread(target=read, daemon=True).start()
        return found.wait(timeout)
