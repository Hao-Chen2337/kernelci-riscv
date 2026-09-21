# SPDX-License-Identifier: LGPL-2.1-or-later
"""One background activity: what is running, what it printed, and how it ended.

Draft this file is built from (``lib/flow.hpp`` §14)::

    Run = Job 与「跑」分开之后多出来的那个词
        Job     规格   可复用、无副作用
        Run     发生   一次执行，有开始、有日志、有终点
        Outcome 产物   判决，进账本

Two things this buys that a subprocess in memory cannot:

* **A page that survives a restart.**  Each activity is a directory with a
  `run.json` (kind, argv, pid, start, state, exit) and a `run.log`; `load_all()`
  scans them, so "what was running" has an answer after the GUI is restarted -
  the old dashboard lost its action history every time.
* **Re-run.**  An activity records the exact command it started, which is the
  same command an operator would type; running it again is copying that argv,
  not remembering which button was pressed.

An activity is never a second implementation: `argv` is the command line, full
stop.  Anything the page can do, a person can type.

接口形状（C++，只有声明）：include/kci/flow.hpp §14 Run。
"""

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field

from . import atomic, errors, layout

# What an activity can be.  The names are the page's vocabulary; `argv` is what
# actually decides what happens.
KINDS = ("job", "pull", "run", "fetch", "worker", "runday", "table", "results",
         "stack", "verify", "drift", "trend", "prune", "gui")

RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

# Activities whose argv writes to the ledger or the downloads - only one of
# these may run at a time.  The rule itself lives with the page that can start
# two of them: `lib/gui/schema.py` names the actions, `lib/gui/actions.py`
# (`busy()`) is what refuses the second one.
WRITERS = ("job", "pull", "run", "fetch", "worker", "runday", "table", "stack",
           "prune")

# The activities THIS process started, and their exit codes once the reaper
# thread has them (`None` while the run is still going).  A run must not depend
# on a page's poll to leave `running`: the poll is a page's convenience, and the
# writer gate reads the state - so a closed tab would keep every writer shut.
_LIVE: dict[str, "int | None"] = {}


def _settle_when_done(run: "Run", process: "subprocess.Popen") -> None:
    """Wait for one activity's child and settle it, whatever the page is doing."""
    try:
        code = process.wait()
    except Exception:                       # noqa: BLE001 - a wait that fails is "no code"
        code = None
    _LIVE[run.id] = code
    if run.state == RUNNING:                # cancel() may have settled it first
        run._settle(code)


@dataclass
class Run:
    """One activity: the command, the process, its log, and how it ended."""

    id: str = ""
    kind: str = "job"
    state: str = RUNNING
    what: str = ""
    argv: list = field(default_factory=list)
    pid: int = 0
    dir: str = ""
    log: str = ""
    started: float = 0.0
    ended: float = 0.0
    exit_code: int | None = None

    # --- lifecycle ---------------------------------------------------------

    @staticmethod
    def _free_id(started: float, kind: str) -> str:
        """An id no activity is using: the stamp, and `-2`, `-3` … only on a collision.

        The id is a second-resolution timestamp plus the kind, which is what an
        operator reads in `/runs` and what `/api/runs/<id>/log` takes.  Two
        activities of one kind started inside the same second therefore wanted the
        same id - and the id *is* the directory, so the second one's
        `open(log, "w")` truncated the first one's log and both wrote a single
        `run.json`: two commands, one row, and a log that was a mixture of them.
        Observed with two `results` clicks a second apart, which left one
        `…005544-results` whose log ended in a torn line belonging to the other run.

        The stamp stays the whole id whenever it is free, so an id already read from
        the page, copied into a command, or bookmarked keeps working.  A suffix
        appears only when it has to.
        """
        stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime(started))
        name = f"{stamp}-{kind}"
        for suffix in range(2, 100):
            if not os.path.exists(layout.runs(name)):
                return name
            name = f"{stamp}-{kind}-{suffix}"
        raise errors.ConfigError(
            f"99 activities of kind {kind!r} already started in the second beginning "
            f"{stamp}: refusing to share a directory with any of them")

    @classmethod
    def start(cls, kind, argv, what="", cwd=None):
        """Start one activity and return it, already on disk and running."""
        if kind not in KINDS:
            raise errors.ConfigError(f"unknown activity {kind!r}; known: {', '.join(KINDS)}")
        if not argv:
            raise errors.ConfigError("an activity needs a command line")
        started = time.time()
        # The directory is created with `exist_ok=False` and the log with mode `"x"`,
        # so the guarantee `_free_id` just checked cannot be undone between the check
        # and the write.  A collision here is a race, not a re-run, and it must fail
        # loudly rather than truncate somebody else's log.
        for _ in range(3):
            run_id = cls._free_id(started, kind)
            home = layout.runs(run_id)
            try:
                os.makedirs(home)
                break
            except FileExistsError:
                continue
        else:
            raise errors.ConfigError(f"cannot get an activity directory of its own for {kind!r}")
        log = os.path.join(home, "run.log")
        handle = open(log, "x", encoding="utf-8")           # noqa: SIM115 - the child writes here
        try:
            # argv is ours and there is no shell: nothing here is interpolated
            process = subprocess.Popen(
                list(argv), cwd=cwd or layout.work(), stdout=handle, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True)
        finally:
            handle.close()
        run = cls(id=run_id, kind=kind, state=RUNNING, what=what or " ".join(argv),
                  argv=list(argv), pid=process.pid, dir=home, log=log, started=started)
        run.save()
        # The child is waited for here, by a thread of this process, and NOT by a
        # page's poll.  A run settled only "on sight" stays `running` for ever when
        # the tab that started it is closed, or when the reader is a second
        # instance - which is not the parent and so cannot `waitpid` - and a
        # `running` writer keeps the writer gate shut with it.
        _LIVE[run.id] = None
        threading.Thread(target=_settle_when_done, args=(run, process), daemon=True).start()
        return run

    def alive(self):
        """Is the process still there?  A dead `running` becomes `failed`."""
        if self.state != RUNNING or not self.pid:
            return False
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            self._settle(None)
            return False
        except PermissionError:
            return True
        return True

    def reap(self):
        """Read the exit status if the process is gone; returns True when it ended."""
        if self.state != RUNNING:
            return True
        if self.id in _LIVE:
            # This process started it: the reaper thread owns the child, so asking
            # `waitpid` here would race it for the status and could report a run
            # that passed as failed.
            code = _LIVE[self.id]
            if code is None:
                return False
            self._settle(code)
            return True
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            # Not our child any more (the GUI restarted): the pid decides.
            if self.alive():
                return False
            self._settle(None)
            return True
        except OSError:
            self._settle(None)
            return True
        if pid == 0:
            return False                    # still running: 0 is the pid, not the status
        self._settle(os.waitstatus_to_exitcode(status))
        return True

    def cancel(self):
        """Ask the whole process group to stop - a job's children are its own."""
        if self.state != RUNNING or not self.pid:
            return False
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            self._settle(None)
            return False
        for _ in range(40):                     # ten seconds, then stop asking
            if self.reap():
                break
            time.sleep(0.25)
        else:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            self._settle(None)
        self.state = CANCELLED
        self.save()
        return True

    def _settle(self, code):
        """Move out of `running`: the exit code decides between done and failed."""
        self.ended = time.time()
        self.exit_code = code
        if self.state == CANCELLED:
            pass
        elif code in (0, None):
            self.state = DONE if code == 0 else FAILED
        else:
            self.state = FAILED
        self.save()

    # --- the record --------------------------------------------------------

    def save(self):
        """Write `run.json` next to the log; tmp + rename, so a reader never sees half."""
        path = os.path.join(self.dir, "run.json")
        # Not synced: this file is rewritten on every state change, and nothing
        # reads it back but a later process, which is the case the rename covers.
        atomic.write_json(path, asdict(self), indent=1, sort_keys=True, fsync=False)

    @classmethod
    def load(cls, run_id):
        """One activity by id, or None when there is no such directory."""
        path = os.path.join(layout.runs(run_id), "run.json")
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        known = {key: data[key] for key in asdict(cls()) if key in data}
        return cls(**known)

    @staticmethod
    def load_all():
        """Every activity on disk, newest first; a stale `running` is settled on sight."""
        home = layout.runs()
        if not os.path.isdir(home):
            return []
        found = []
        for name in sorted(os.listdir(home), reverse=True):
            run = Run.load(name)
            if run is None:
                continue
            if run.state == RUNNING and not run.reap():
                pass                                # still ours and still going
            found.append(run)
        return found

    def log_since(self, offset=0):
        """`(text, new offset)`: the bytes appended since the reader last looked."""
        try:
            size = os.path.getsize(self.log)
        except OSError:
            return "", offset
        if offset >= size:
            return "", size
        with open(self.log, encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            return handle.read(), size

    # --- what a page shows -------------------------------------------------

    def seconds(self):
        """How long it has been running (or ran)."""
        end = self.ended or time.time()
        return max(0.0, end - self.started)

    def age(self):
        """How long ago it started, as a page prints it."""
        delta = max(0.0, time.time() - self.started)
        # `(limit, unit, seconds)` - the divisor is spelled out and is not the
        # limit divided by something.  It used to be `limit / 60`, which was
        # right for minutes by accident (3600/60) and wrong for hours by a factor
        # of 24: an activity two hours old printed `5h`.
        for limit, unit, size in ((60, "s", 1), (3600, "m", 60), (86400, "h", 3600)):
            if delta < limit:
                return f"{int(delta / size)}{unit}"
        return f"{int(delta / 86400)}d"

    def line(self):
        """One line for a table: id, kind, state, how long, exit code, what."""
        code = "-" if self.exit_code is None else self.exit_code
        return (f"{self.id:<22} {self.kind:<7} {self.state:<9} {self.age():>5} "
                f"exit={code!s:<4} {self.what[:60]}")
