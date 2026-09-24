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
REFUSED_LIMIT = 20000       # the same, for the refusals beside them
MAX_RETRIES = 5             # consecutive failed batches before giving up
EVENTS_LIMIT = 1000
REPOST_EVERY = 12           # polls between re-posts of a report the callback refused

# The state file's shape is a contract: operators read it, and an older worker
# must not misread what a newer one wrote.  The callback token is NOT in it.
#
# `refused` is why a node is in `seen` without having run, per node id.  `seen`
# alone cannot say that, and the difference is not cosmetic: `_claim` answers
# None for a node that is already done, for one whose runtime is another lab's,
# and for one whose platform this host cannot boot, and all three used to be
# recorded as nothing at all - the node went into `seen`, `_drain`'s "already
# seen" skip made the decision permanent, and the page drew the same word for
# "this loop ran it" and "this loop looked at it and put it down".  A worker
# older than this field writes no `refused` entries, so a node it dealt with is
# still ambiguous; the page says so rather than picking the flattering reading.
STATE_FIELDS = ("timestamp", "seen", "pending", "refused")


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
        self.state = {"timestamp": None, "seen": [], "pending": {}, "refused": {}}
        self._seen_index = set()
        self._refused_index = {}
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
            # The newest event we saw, or - when there were none - **now**, which is
            # where this poll got to.  `events()` asks for the whole available queue and
            # puts no ceiling on the question, so an empty answer is the queue being
            # empty, and the present is what the cursor has got to.
            #
            # It used to fall back to `start_cursor()`, which reads as "the window we
            # asked about" and was in fact the window's *start*.  So the cursor sat one
            # overlap behind the present for ever - and it was the floor every later
            # poll was bounded by, which is how a node below it went invisible for good
            # (`start_cursor` carries the measurement).  The cursor is **not a floor any
            # more**; what is left here is the stamp the page reads as "when this worker
            # last got to", and it is still worth keeping honest.
            #
            # **`newest` is seeded from the cursor**, which is why the fallback has to be
            # chosen by `batch` and not by whether `newest` is empty: on an empty batch
            # `newest` holds the very value this line is supposed to replace, so
            # `newest or _iso_now()` hands the cursor back to itself and the stamp never
            # moves.  Measured, with a stub poller - the first version of this fix wrote
            # the old stamp back on every empty poll, which is the same stall this
            # paragraph is about, reached by a shorter route.
            #
            # `_dirty` is what makes `flush()` write it: a state dict that changes without
            # the flag is a change that never reaches the disk, which is the other half of
            # why `timestamp` stayed `null` for ever.
            self.state["timestamp"] = (newest or _iso_now()) if batch else _iso_now()
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
        #
        # ...unless this deployment has been told to report somewhere else, which is
        # what `sink.delivery_url` is for: the definition's URL is the default and not
        # the last word, and the page that draws this panel is where the last word is
        # set.  Resolved here, at delivery, and not when the worker started - a worker
        # runs for days and a setting that needed a restart would be a setting the
        # operator watches do nothing.
        forward = _Forward((sink.Ledger(),
                            sink.Callback(sink.delivery_url(_callback_url(definition)))))
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

        **Every `None` is recorded before it is returned.**  A refusal is a decision
        this loop made and then made permanent - `handle` returns True, `_drain` marks
        the node seen, and the "already seen" skip at the top of `_drain` means it is
        never looked at again.  Answered as nothing at all, that decision left the node
        indistinguishable from one that ran, and the operator's 「这六个到底是跑了还是
        没跑」 had no answer in any file on this disk.  The three reasons are separate
        strings rather than one word because they call for three different responses:
        a job claimed by another lab is not a fault, a platform this host cannot boot
        is a deployment gap, and a node already done is simply stale news.
        """
        if not node.node_id:
            return None
        fresh = Kjob.from_node(self.api.node(node.node_id))
        if not fresh.claimable(self.runtime):
            self.refuse(node.node_id, f"not claimable now: state={fresh.state or '?'}"
                                      f" result={fresh.result or '-'}"
                                      f" runtime={fresh.runtime or '-'}")
            return None
        if self.platform and fresh.platform and fresh.platform != self.platform:
            self.refuse(node.node_id, f"platform {fresh.platform} is not {self.platform}")
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
        self.state.setdefault("refused", {})
        self._seen_index = set(self.state["seen"])
        self._refused_index = dict(self.state["refused"])
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
                self._refused_index.pop(gone, None)
                self.state["refused"].pop(gone, None)
            del self.state["seen"][:extra]
        self._dirty = True

    def refuse(self, node_id, reason):
        """Record that this node was looked at and put down, and why.

        Keyed by node id, evicted with the `seen` entry it explains (`mark_seen`), so
        the two lists cannot drift: a refusal whose node is no longer in `seen` would
        be a reason for a decision nothing remembers making.  Not a `seen` mark on its
        own - the caller still marks it, because marking is what makes the refusal
        permanent and the two must happen together.
        """
        if not node_id or not reason:
            return
        self.state["refused"][node_id] = reason
        self._refused_index[node_id] = reason
        self._dirty = True

    def refused(self, node_id):
        """Why this node was put down, or `""` - including for a worker that never said."""
        return self._refused_index.get(node_id, "")

    def forget(self, node_id):
        """Take a node back out of `seen`, so the next poll looks at it again.

        The only way out of `seen`, and it exists because `seen` is otherwise forever:
        a node marked seen is skipped by `_drain` before `handle` is reached, so a
        decision that turned out to be wrong - a platform this host has since been able
        to boot, a runtime that has since been fixed, a run that died before its report
        was posted - could only be undone by hand-editing the JSON.

        The refusal goes with it, for the reason `refuse` gives: the two are one fact,
        and a reason for a decision nothing remembers making is worse than no reason.
        `pending` does **not**: a report written and not delivered is a run that really
        happened, and the worker re-posts those on its own (`_repost_pending`) without
        being asked.  Forgetting a node must never be a way to lose the record of one.

        Returns True when the node really was in `seen`, so the caller can say what it
        did rather than that it did something: an id nobody remembers and an id that was
        just un-remembered are the same request with different answers, and a page that
        printed one for the other would be inventing the second.
        """
        if not node_id or node_id not in self._seen_index:
            return False
        self._seen_index.discard(node_id)
        self.state["seen"] = [one for one in self.state["seen"] if one != node_id]
        if self._refused_index.pop(node_id, None) is not None:
            self.state["refused"].pop(node_id, None)
        self._dirty = True
        return True

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
        """The floor a poll asks from: `--since` if given, else **nothing at all**.

        **The persisted cursor is not a floor any more, and that is the fix for a
        worker that skipped work.**  This fell back to `state["timestamp"]`, which is a
        time this worker *got to* - and a time it got to is not a time before which
        there is no work.  The two came apart the moment a node was created below the
        cursor without being handled, in either of the two ways that happens here:

        - `deploy/stack.sh --seed` writes job nodes carrying the upstream build's own
          timestamps, so a queue seeded from a build stamped `2026-09-20T08:20` lands
          *behind* a cursor saying `2026-09-22T04:08`.  `actions.py`'s `--since` field
          records this one: it was reaching the page's `claimed: no` rows only by the
          operator hand-editing an argv.
        - A worker whose state file has no cursor floors at `now - 900s`, so a queue
          seeded in the fifteen minutes before it first ran was outside the window it
          opened - and the first run then wrote that node's own neighbours in as the
          new cursor.

        Neither node is ever fetched again, because the floor only moves forward: it
        overtakes them permanently.  Measured on the local stack, 2026-09-23, with the
        cursor left at `2026-09-22T04:08:01.967` by a batch that ran -
        `/events?kind=job&state=available&recursive=true&from=2026-09-22T03:53:01.967`
        returns **3** events while the same query with no `from` returns **18**, and
        none of the 15 the floor was hiding was in `seen`.  `/worker` drew six
        `available` rows the whole time.

        Nothing is needed in the floor's place, because **`state="available"` is already
        the bound**: a node that was run and reported leaves the queue, so what comes
        back is the outstanding work and nothing else, and `seen` is already the record
        of what this worker has dealt with.  The floor was the only thing that could
        hide a node the page was showing as pending - which is why the two disagreed.

        `--since` still floors the query and still means what it always did, the one way
        for an operator to say "only this window".  It is no longer the *only* way to
        reach seeded work; it is not needed for that at all now.
        """
        return self.since or ""

    def events(self):
        """One batch from the events API: the queue, however old its nodes are.

        The overlap still applies to an explicit `--since`, because the feed is not
        ordered and a window the operator typed must not miss an event that arrived
        while the previous poll was running.  With no `--since` there is no window to
        widen - `start_cursor` has what the floor used to cost.
        """
        floor = self.start_cursor()
        since = iso_ago(floor, CURSOR_OVERLAP_S) if floor else ""
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
                # Through `delivery_url` and not straight to the stored URL, which is
                # the *definition's*: re-posting is the moment the operator most needs
                # the override, because a report that is still waiting is usually one
                # that was going somewhere that refused it.  A repost that ignored a
                # setting the page had just shown them would leave the row pending for
                # ever with the page claiming a destination the worker never used.
                sink.Callback(sink.delivery_url(entry.get("callback") or "")).deliver(job, outcome)
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
            #
            # **The stored URL is the definition's and not the one this attempt used.**
            # An override is a decision the operator can change between the failure and
            # the re-post, and a row that recorded the overridden URL would repost to a
            # destination they had already abandoned (`_repost_pending` resolves again,
            # the page draws the same resolution).  What is durable here is what the
            # pipeline declared; what is in force is asked fresh.
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


def forget_node(node_id, state_file=None):
    """Take one node back out of `seen` on disk, under the worker's own lock.

    This is the page's write, and it is a *second* writer of a file that has one by
    design, so it goes through the same `flock` the worker takes: `Poller` keeps the
    whole state in memory and `flush()` rewrites the file wholesale, so a write from
    anywhere else while a worker holds it is not a merge - it is a change the worker's
    next flush silently undoes, and the operator would watch the button work and then
    stop working.  The lock is tried and **not waited on**: a page that blocked until a
    long-lived worker exited would hang the request, and the honest answer to "the
    worker is running" is to say so.

    Returns a dict rather than raising, because every outcome here is something the
    page has to say out loud and none of them is an error in this program:
    `{"forgotten": bool, "reason": str}` where `reason` is one of
    `""` (it was in `seen` and now is not), `"absent"` (nothing remembered it),
    `"locked"` (a worker holds the file), or `"unreadable"` (the file is not JSON).
    """
    path = state_file or layout.worker_state()
    try:
        # Held open on purpose, the same way `_acquire` holds it: the lock *is* the
        # handle, so the file has to outlive this line and be closed in the `finally`.
        handle = open(path + ".lock", "w", encoding="utf-8")  # noqa: SIM115 - flock lifetime
    except OSError:
        return {"forgotten": False, "reason": "locked"}
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"forgotten": False, "reason": "locked"}
        # The file is parsed here, before anything is constructed from it, and that is
        # not belt-and-braces: `load()` is written for a *worker*, which must not die
        # because the file is corrupt - it warns and starts from an empty state, and
        # that is right for a loop whose next poll would rebuild the file anyway.  A
        # page's write is not that.  `flush()` writes the state dict whole, so a
        # `Poller` that loaded a corrupt file and then flushed would replace the
        # operator's `seen`/`pending`/`refused` with the empty default and call it a
        # forget - one press, the whole state file gone, and "unreadable" is the word
        # this has to answer instead.
        try:
            with open(path, encoding="utf-8") as handle_in:
                json.load(handle_in)
        except FileNotFoundError:
            return {"forgotten": False, "reason": "absent"}
        except (OSError, ValueError):
            return {"forgotten": False, "reason": "unreadable"}
        # A `Poller` with no API: the three methods below touch the state file and
        # nothing else, and going through the class is what keeps one implementation
        # of the file's shape rather than a second reader of it here.
        poller = Poller(None, state_file=path)
        poller.load()
        done = poller.forget(node_id)
        poller.flush()
        return {"forgotten": done, "reason": "" if done else "absent"}
    finally:
        handle.close()


def _iso_now():
    """Now, in the spelling the values this stamp ends up beside are written in.

    Its one caller puts it in the **cursor** (`_drain`'s window end), and `_drain` keeps
    the cursor up to date by comparing it to a node's own `created` as *strings*.  That
    comparison is only meaningful while the two are spelled the same way, and a node's
    stamp is the API's (`2026-09-20T08:20:00.123456` - fractional seconds, no `Z`).  A
    trailing `Z` is not decoration here: `Z` sorts above `.`, so a cursor wearing one
    would outrank every node stamp in its own second and the cursor would stop advancing
    on them.  `iso_ago` reformats for the wire either way, so the query is unchanged by
    this.

    `start_cursor` used to be the other caller, and no longer is: the cursor is
    **information - when this worker last got to - and not a floor**, so no query is
    bounded by a value this writes.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


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


# The shapes `parse_iso` reads, in the order they are tried.  `_iso_now` writes the
# first of them, and the stamp this parse is actually handed the most is the second
# half of the same family: the cursor is usually a **node timestamp straight off the
# API**, and every one of those carries fractional seconds and no `Z`
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
