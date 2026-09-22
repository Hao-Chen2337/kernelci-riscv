# SPDX-License-Identifier: LGPL-2.1-or-later
"""The rotation: watch the API, run what appears, report it, remember what was done.

Draft this file is built from (``lib/poller``)::

    class poller {
        class job
        date d
        time t
        poller(d)
        { date ... }
    }

This is the most complex thing in the project and it is deliberately one class
with its own state file, because its complexity is real and its parts are not
separable: the cursor, the seen set and the unposted reports are three views of
one question - "what has this worker already dealt with?"  Split across modules
they were 1,100 lines and four seams; here they are one file.

What it guarantees, each of which was a real bug once:

* one worker per deployment (flock), and a second one exits instead of racing
* the cursor is authoritative and only advances when a whole batch was handled;
  `since` only seeds a file that has no cursor, and a 15-minute overlap re-scans
  a window the events feed may have delivered out of order
* a node with a pending report is re-posted, never re-run
* state is flushed to disk after every event and on SIGTERM, so a killed worker
  does not lose a result or repeat a run
* a node is marked seen once its **run** is over, whether or not the report was
  accepted - the two are separate debts, and the paragraph above says which one
  the retry pays.  "Only once its report was really accepted" is what this said,
  and it made the two lines above untrue: an unaccepted report left the node
  unseen, an unseen node is claimed again, and claiming again runs the job.

接口形状（C++，只有声明）：include/kci/flow.hpp §15 Poller。
"""

import calendar
import fcntl
import json
import os
import signal
import time

from . import atomic, errors, layout, sink
from .build import Build
from .config import RunConfig
from .job import Job, Jobs
from .kbuild import Kbuilds
from .kjob import Kjob
from .out import Outcome

POLL_PERIOD = 5
CURSOR_OVERLAP_S = 900      # the events feed is not ordered; re-scan a window
SEEN_LIMIT = 20000          # oldest ids are evicted past this
MAX_RETRIES = 5             # consecutive failed batches before giving up
EVENTS_LIMIT = 1000
REPOST_EVERY = 12           # polls between re-posts of a report the callback refused

# The state file's shape is a contract: operators read it, and an older worker
# must not misread what a newer one wrote.  The callback token is NOT in it.
STATE_FIELDS = ("timestamp", "seen", "pending")


class Poller:
    """The resident worker: claim `available` jobs from the events API and run them."""

    def __init__(self, api, run=None, runtime=None, platform=None, tests=None, state_file=None,
                 period=POLL_PERIOD, max_retries=MAX_RETRIES, since=""):
        self.api = api
        self.run = run
        # The LAB name (pull-labs-riscv) - what a job node's data.runtime says.
        # The container runtime is the run config's business, not a claim filter.
        self.runtime = runtime or ""
        self.platform = platform or ""
        self.tests = tuple(tests) if tests else ()
        self.state_file = state_file or layout.worker_state()
        self.period = period
        self.max_retries = max_retries
        self.since = since
        self.state = {"timestamp": None, "seen": [], "pending": {}}
        self._seen_index = set()
        self._lock = None
        self._stopping = False
        self._dirty = False
        self._repost_at = 0.0       # first poll re-posts at once; see `loop`

    # --- the loop ----------------------------------------------------------

    def loop(self):
        """Poll forever: fetch events, handle each, flush, sleep.  SIGTERM flushes and exits."""
        self._acquire()
        self.load()
        self._arm_signals()
        failures = 0
        while not self._stopping:
            # Every poll and not once at startup: `resident` has no next startup, so a
            # report `handle` kept had no second chance to be delivered - the only
            # thing that could still clear it was another *run* of the same job, which
            # is exactly what must not happen.  Throttled, because an endpoint that is
            # refusing must not be asked twelve times a minute for ever; the first
            # poll is not throttled (`_repost_at` starts at 0), so a report kept
            # before a restart still goes out immediately.
            now = time.monotonic()
            if now >= self._repost_at:
                self._repost_pending()
                self._repost_at = now + self.period * REPOST_EVERY
            try:
                batch = self.events()
            except Exception as exc:  # noqa: BLE001 - every failure here is retryable
                failures += 1
                print(f"! events fetch failed ({failures}/{self.max_retries}): {exc}", flush=True)
                if failures >= self.max_retries:
                    self.flush()
                    raise SystemExit(1) from None
                self._sleep()
                continue
            failures = 0
            self._drain(batch)
            self._sleep()
        self.flush()

    def once(self):
        """Handle the current queue and return - what `pull_worker.py --once` means.

        **An API that cannot be asked is a refusal, not a failure.**  The worker used to
        let `ApiError` escape, so a poll against an API that was down (or slow, or
        unreachable through a proxy) exited 1 with a traceback - and the page showed it as
        `failed` in 0s, which is exactly the operator's 「轮转方面 worker 不能用」: there was
        nothing to run, nothing ran, and the page blamed the worker.  The queue is the
        API's, so "the API did not answer" is an answer this program can honestly give:
        it is reported in words, the exit code says "nothing was claimed" rather than
        "something broke", and the refusal text is what the page prints.
        """
        self._acquire()
        self.load()
        self._repost_pending()
        try:
            found = self.events()
        except errors.ApiError as exc:
            # Exit 3 is this program's "we never got an answer" code
            # (`lib/errors.py`'s header: 3 = infra, and the pipeline reads it as
            # infrastructure rather than as a test result), which is exactly what a
            # queue nobody could be asked about is.  The sentence above it is what the
            # page renders instead of a bare `failed`.
            print(f"nothing claimed: the API did not answer: {exc}", flush=True)
            return errors.EXIT_INFRA
        # No `event(s)`: this line is printed for a reader (`accept.py`'s W3 check calls
        # a machine plural invented by the page, and a log is a page of a kind).
        count = len(found)
        print(f"asked the queue: {count} event{'s' if count != 1 else ''} in this window",
              flush=True)
        self._drain(found)
        self.flush()
        return errors.EXIT_PASS

    def run_day(self, day, tree="riscv", tests=None):
        """Run everything a given day's builds can run - the rotation, not the queue.

        The draft's `runday's`: the API's queue is not the only thing worth
        running, and "everything from Tuesday" is the case the one-shot fetch
        and the resident worker both leave out.

        The registration travels with the pull, not with this loop: `Job.make()`
        writes the bytes and the pull record and then registers the build it
        pulled, so a day the worker fetched itself is a day the builds page has a
        card for - and one build this machine cannot fetch is an infra Outcome of
        its own rather than an exception that ends the day.  The guard that makes
        it an Outcome is `Job.run()`'s; calling `make()` out here, as this loop
        and `table.py run` both did, put the very same download outside it.
        """
        config = self.run or RunConfig()
        outcomes = []
        for kbuild in Kbuilds(self.api).getdays(tree, 1):
            if day and not kbuild.created.startswith(day):
                continue
            outcomes += Jobs.for_build(Build(kbuild), tests or self.tests).run(
                config, sinks=config.sinks(), source="runday")
        return outcomes

    # --- one batch ---------------------------------------------------------

    def _drain(self, batch):
        """Handle a batch; the cursor advances only if every event was handled.

        **An empty batch still writes the cursor.**  It used to advance only when the
        batch named a newer node, so a poll that found nothing left `timestamp: null` - and
        the next poll started from `--since` (or "now") all over again instead of from where
        the last one got to.  Both halves of that are wrong for an operator: the state file
        never showed the worker had run at all, and the start of every run was a fresh
        15-minute window rather than the one the last run finished with.  The cursor is a
        *time this worker got to*, and reaching the end of an empty queue is getting there.
        """
        handled_all = True
        newest = self.state.get("timestamp") or ""
        for node in batch:
            if self._stopping:
                handled_all = False
                break
            if node.created and node.created > newest:
                newest = node.created
            if self.seen(node.node_id):
                continue
            try:
                handled = self.handle(node)
            except Exception as exc:  # noqa: BLE001 - one bad node may not kill the loop
                print(f"! {node.node_id}: {exc}", flush=True)
                handled = False
            finally:
                self.flush()                      # a killed worker must not redo this
            if handled:
                self.mark_seen(node.node_id)
                self.flush()
            else:
                handled_all = False
        if handled_all:
            # The newest event we saw, or - when there were none - the window this poll
            # actually asked about, which is `start_cursor`'s answer and therefore always
            # a real timestamp.  `_dirty` is what makes `flush()` write it: a state dict
            # that changes without the flag is a change that never reaches the disk, which
            # is the other half of why `timestamp` stayed `null` for ever.
            self.state["timestamp"] = newest or self.start_cursor()
            if self.state["timestamp"]:
                self._dirty = True
        # A poll that claimed nothing is not a silent one: the line is what the activity's
        # log shows, and "asked, found nothing" is the difference the operator could not
        # see between a working worker and a broken one.
        if not batch:
            print(f"nothing to claim: the queue is empty as of {self.state['timestamp']}",
                  flush=True)
        return handled_all

    def handle(self, node):
        """Run one claimed node and deliver its report; True means "may mark seen"."""
        claimed = self._claim(node)
        if claimed is None:
            return True                           # gone, or not ours: nothing to retry
        definition = claimed.definition(self.api)
        job = Job.from_definition(definition)
        # The ledger always, and a callback whose URL comes from the *definition*
        # the pipeline sent - that is what dispatching a job means here.  A sink
        # set built from the command line would only work when the operator
        # passed --callback-url, and the worker line would silently never post.
        forward = _Forward((sink.Ledger(), sink.Callback()))
        try:
            job.run(self.run, sinks=(forward,), source="worker")
        except Exception as exc:  # noqa: BLE001 - a failed delivery must stay retryable
            # The ledger row is already written (it is the first sink); what is
            # missing is the callback, and the report is kept for `_repost_pending`
            # to pay on a later poll - re-posted, never re-run.
            #
            # **So the node is marked seen anyway**, and "True" here is the whole
            # fix: returning False left it unseen, which reads as "try again" - but
            # a retry at this level is a *run*, and the run is the thing that has
            # just finished.  The resident worker re-ran the identical job on every
            # poll until it was killed by hand (41 workspaces, ~17s apart, from one
            # job definition whose ledger write could never succeed), and because
            # `_drain` holds the cursor while any event is unhandled it never
            # advanced its window either, so it could not get past the node.  The
            # debt recorded below is the *report*; the job is done and marking it
            # seen is what says so.
            self._remember_pending(claimed, definition, forward.outcome)
            print(f"! {node.node_id}: report not delivered ({exc}); kept pending", flush=True)
            return True
        return True

    def _claim(self, node):
        """This node as it is NOW, or None when it is not ours to run.

        The events feed replays history: a node that was `available` an hour ago
        may be done by now.  Re-reading is what makes "claim" mean anything.
        """
        if not node.node_id:
            return None
        fresh = Kjob.from_node(self.api.node(node.node_id))
        if not fresh.claimable(self.runtime):
            return None
        if self.platform and fresh.platform and fresh.platform != self.platform:
            return None
        return fresh

    # --- the state file ----------------------------------------------------

    def load(self):
        """Read cursor/seen/pending; a corrupt file is refused with a warning, never trusted."""
        try:
            with open(self.state_file, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except FileNotFoundError:
            return self.state
        except (OSError, ValueError) as exc:
            print(f"! {self.state_file} unreadable ({exc}); starting from an empty state",
                  flush=True)
            return self.state
        if not isinstance(loaded, dict):
            print(f"! {self.state_file} is not an object; starting from an empty state",
                  flush=True)
            return self.state
        # Keys this module does not own are carried through untouched: an older
        # worker must not silently drop what a newer one wrote.
        self.state.update(loaded)
        self.state.setdefault("timestamp", None)
        self.state.setdefault("seen", [])
        self.state.setdefault("pending", {})
        self._seen_index = set(self.state["seen"])
        return self.state

    def flush(self):
        """Write the state atomically; called after every event, and on a signal."""
        if not self._dirty:
            return
        directory = os.path.dirname(self.state_file) or "."
        os.makedirs(directory, exist_ok=True)
        atomic.write_json(self.state_file, self.state, indent=1, sort_keys=True)
        self._dirty = False

    def seen(self, node_id):
        """Has this node already been dealt with?"""
        return node_id in self._seen_index

    def mark_seen(self, node_id):
        """Remember a node, oldest entries evicted past SEEN_LIMIT."""
        if not node_id or node_id in self._seen_index:
            return
        self.state["seen"].append(node_id)
        self._seen_index.add(node_id)
        extra = len(self.state["seen"]) - SEEN_LIMIT
        if extra > 0:
            for gone in self.state["seen"][:extra]:
                self._seen_index.discard(gone)
            del self.state["seen"][:extra]
        self._dirty = True

    def pending(self, node_id, report=None):
        """The unposted report for a node: set it, or read it back to re-post."""
        if report is None:
            return self.state["pending"].get(node_id) or {}
        if report:
            self.state["pending"][node_id] = report
        else:
            self.state["pending"].pop(node_id, None)
        self._dirty = True
        return report

    # --- the events feed ---------------------------------------------------

    def start_cursor(self):
        """Where the first poll starts: `--since` if given, else the cursor, else now.

        **`--since` outranks the persisted cursor**, which reverses the order this
        applied and is what makes the option mean anything.  Cursor-first meant
        `--since` was only ever consulted on a state file that had no cursor yet -
        so the operator's one way to reach work this worker never saw (a stack
        seeded with build timestamps from days ago, a deployment that was down over
        a weekend) did nothing at all on any deployment that had ever run once, and
        did it silently.  An instant the operator typed is a thing they meant; a
        stamp the file happens to hold is not, and when the two disagree the
        argument is the one to believe.

        Re-scanning from `--since` on every start is safe because `seen` answers
        it: a node already handled is skipped, and one that finished long ago fails
        `Kjob.claimable` even if it is not.
        """
        return self.since or self.state.get("timestamp") or _iso_now()

    def events(self):
        """One batch from the events API, with the overlap window applied."""
        since = iso_ago(self.start_cursor(), CURSOR_OVERLAP_S)
        return [Kjob.from_node(node)
                for node in self.api.events(kind="job", state="available", since=since)]

    # --- delivery that outlives the process --------------------------------

    def _repost_pending(self):
        """Re-post reports that were written but never accepted - never re-run them."""
        for node_id, entry in list(self.state["pending"].items()):
            if not isinstance(entry, dict):
                self.pending(node_id, {})
                continue
            try:
                job = Job.from_definition(entry.get("definition") or {})
                outcome = Outcome(**{k: v for k, v in (entry.get("record") or {}).items()
                                     if k in Outcome.__dataclass_fields__})
                sink.Callback(entry.get("callback") or "").deliver(job, outcome)
            except Exception as exc:  # noqa: BLE001 - stays pending, retried next poll
                print(f"! {node_id}: report still pending ({exc})", flush=True)
                continue
            self.pending(node_id, {})
            self.mark_seen(node_id)
            print(f"  {node_id}: pending report delivered", flush=True)
        self.flush()

    def _remember_pending(self, node, definition, outcome):
        """Keep a report the callback endpoint refused, without the token.

        What is stored is enough to re-post and not enough to re-run, which is
        the whole point: a node whose run finished must never be run twice.
        """
        self.pending(node.node_id, {
            # The definition is the authority: an upstream job node carries no
            # callback URL of its own, so the node field is usually empty.
            "callback": _callback_url(definition) or node.callback_url,
            "definition": definition,
            "record": outcome.record() if isinstance(outcome, Outcome) else {},
        })

    # --- process discipline ------------------------------------------------

    def _acquire(self):
        """One worker per deployment: the second one exits instead of racing."""
        os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
        handle = open(self.state_file + ".lock", "w", encoding="utf-8")  # noqa: SIM115 - flock lifetime
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            print("Another worker instance holds the lock; exiting.", flush=True)
            raise SystemExit(1) from None
        self._lock = handle

    def _arm_signals(self):
        """SIGTERM/SIGINT flush the state before leaving; a killed worker loses nothing."""
        def stop(_signum, _frame):
            self._stopping = True
            self.flush()
            raise SystemExit(0)

        for name in ("SIGTERM", "SIGINT"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), stop)

    def _sleep(self):
        """Sleep in small steps so a signal is noticed promptly."""
        deadline = time.monotonic() + self.period
        while not self._stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def _callback_url(definition):
    """Where a definition says its result goes, or ''."""
    callback = definition.get("callback") if isinstance(definition, dict) else None
    return str(callback.get("url") or "") if isinstance(callback, dict) else ""


def _iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _Forward(sink.Sink):
    """The real sink set, wrapped so a delivery failure still leaves us the outcome.

    Without this the outcome would be lost with the exception, and the pending
    report - the whole point of the state file - would have nothing to carry.
    """

    def __init__(self, sinks):
        self.sinks = tuple(sinks)
        self.outcome = None

    def name(self):
        return "+".join(one.name() for one in self.sinks)

    def wants(self, job, outcome: Outcome) -> bool:
        self.outcome = outcome
        return any(one.wants(job, outcome) for one in self.sinks)

    def deliver(self, job, outcome: Outcome) -> str:
        notes = [one.deliver(job, outcome) for one in self.sinks if one.wants(job, outcome)]
        return " ".join(note for note in notes if note)


# The shapes `parse_iso` reads, in the order they are tried.  `_iso_now` and the
# console write the canonical one, but the stamp this parse is actually handed the
# most is neither of those: the cursor is a **node timestamp straight off the API**,
# and every one of those carries fractional seconds and no `Z`
# (`2026-09-20T08:20:00.123456`).  The console's `/worker` column prints a third
# near miss, `created[:16]`, which is why the seconds are optional here too.
ISO_SHAPES = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")


def parse_iso(stamp):
    """The instant `stamp` names, as epoch seconds - or None for anything unreadable.

    The cursor is stored *raw* and read here, rather than normalised on the way into
    the state file.  `_drain` keeps it up to date by string comparison (`node.created
    > newest`), and those comparisons are only meaningful while both sides are the
    API's own spelling: a cursor re-spelled with a trailing `Z` would sort *above*
    every node stamp sharing its second, since `Z` > `.`.  So the mismatch is
    repaired at the read, where it is a mismatch, and not at the write, where it
    would quietly become an ordering bug.

    The fractional part and the trailing `Z` are noise rather than information - the
    feed's own stamps are whole seconds.
    """
    text = str(stamp or "").strip().removesuffix("Z").split(".", 1)[0]
    for shape in ISO_SHAPES:
        try:
            # `timegm`, not `time.mktime(parsed) - time.timezone`: the stamp is UTC
            # by construction (`Z`, or the API's own clock).  The mktime form reads
            # it as local time and then corrects by the *standard* offset, which is
            # an hour out wherever DST is in effect.
            return calendar.timegm(time.strptime(text, shape))
        except ValueError:
            continue
    return None


def iso_ago(stamp, seconds):
    """`stamp` minus `seconds`, in the ISO shape the events feed wants.

    An unparsable stamp is treated as "now": a bad cursor must not stop the
    worker, and scanning a window twice is free - `seen` answers it.
    """
    base = parse_iso(stamp)
    if base is None:
        base = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base - seconds))
