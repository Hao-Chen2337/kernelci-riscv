# SPDX-License-Identifier: LGPL-2.1-or-later
"""The design's rows: this console's own readers, reshaped into the dict one screen draws.

Every screen of `design/kernelci-design.html` reads its rows out of **one plain
dict** and knows nothing else about where they came from.  That is the seam the
prototype documents - `proto/data.py` is the fixture, `proto/pages.py` is the five
consumers - and this module is the other side of it: the same keys, filled from
the readers that already exist instead of from a hand-typed fixture.

    rows(gui, check, lang) -> dict

`gui` is the console (`lib.gui.app.Gui`), `check` the request's `Filter` (or
`None` for "no conditions"), `lang` `"en"` or `"zh"`.  It is called once per
request, and every reader it calls is memoised for that request (`Gui._state`,
`all_locals`, `runs`, `todo`, and `lib/api.py`'s per-request memo), so a key that
uses an answer another key already read costs nothing.

**The board's fixture is not a target.**  A measured comparison of
`design/kernelci-design.html` against this workspace found 63 of the board's 64
`/analysis/<id>` ids nowhere in `var/`, the repository or the reachable API; the
rows it draws step back in a fixed 3h10m rhythm with a period-7 tree pattern, and
its ledger additions are two byte-identical 8-row blocks.  So the board's numbers
are a *drawing*, and a panel here that comes out sparser is right rather than
short: three tests and not five (the board's `ltp-riscv-tests` and
`libhugetlbfs` exist nowhere on this machine, and offering a filter value no row
can satisfy is the defect this console is being rebuilt to remove), ~22 builds
with records and not 24, and lines with breaks where the ledger has nothing.  The
densities to reproduce are the reader's; the *layout* is the board's.

**What would break without it.**  The design's markup has no other way to be a
console: replace this one function with the fixture and the board is a drawing
again; replace it with *anything that computes* and the console has a second
answer to questions the tree already answers once.  So nothing here decides
anything:

* a verdict is the record's own word (`lib/out.py`, written by `lib/judge.py`);
* a tally is `Records.tally()`, and a set of them is `Records.for_test`/
  `for_build` - never a count kept here;
* a gap is `re.todo()` (through `Gui.job_rows`, which merges it with the ledger);
* a transition is `re.transitions()`, a config difference is `lib/drift.py`'s
  `Drift`, and the three numbers of a delta are `len()` of what `Drift` answered
  - the same three numbers `ui.delta` prints;
* which builds a list is about, in what order, is `_build_rows`/`_sort_rows`, the
  same pair the shipped `/analysis` page reads;
* a chart point is `Gui.trend`'s own point and `Records.series`'s own history, and
  a pass rate is a ratio of the record's verdict *words* accumulated over the
  positions the page displays - the same accumulation `_series` below documents,
  expressed as a share because the design's `y` axis is a percentage;
* which artifacts a build is missing is `Build.missing()`, which is what
  `Gui.job_rows` reads for its `reason` column.

**It writes nothing, and it owns no path.**  Every path a `counts` source names
comes from `lib/layout.py`; nothing in this file opens a file for writing, and
`docs/gui-rework/tools/check_structure.py` fails the tree for a path spelled here
by hand.  The one reader below that *caches* - `Drift`, through
`layout.configs()` - is the engine's own cache, and it is why the first read of a
new config pair costs two downloads and every read after it costs nothing.

**The shape is not the fixture's, it is the design's.**  Where the prototype's
hand-typed row has a field no reader can honestly fill, the field is produced
with the rows it can have and the difference is named in the module that draws it
rather than guessed here: `here` is `Local.state`'s own five-word verdict and not
the fixture's *whole/partial/card only*, `checks` is what is **on disk**
(`Build.present()`, the design's tick `title="present"`) and not what a card
declares, and a `delta` that was refused comes back as `None` - a number that was
not read is not a number.

Column-for-column the mapping, and the reader behind each key:

    builds      Gui.build_rows + Gui.remote_rows + all_locals   (`reads.py`)
    pulls       Gui.pull_acts                                   (`activities.py`)
    gap         Gui.job_rows (re.todo + Records)                (`activities.py`)
    ledger      Records                                         (`lib/re.py`)
    worker      Gui.worker_state + Gui.run_rows                 (`activities.py`)
    queue       Gui.job_node_rows                               (`activities.py`)
    runs        Gui.run_rows                                    (`activities.py`)
    picks       _build_rows/_sort_rows + Gui._config_edges      (below, `reads.py`)
    bars        Records.for_test/for_build .tally()             (`lib/re.py`)
    timelines   Records.series/transitions + _wave_slots below
    series      Gui.trend + Records.series                      (`reports.py`)
    drift       Gui._config_edges' Drift reports                (`lib/drift.py`)
    counts      the seven readers `_counts` below names
    option lists schema.py's constants, values._vocabulary, Gui.apis.entries

`series` is the one key the prototype's dict does not have, and the one the
design's chart panel needs: `lib/gui/design/ui.py` draws it with
`line_chart(series, slots, ends, …)` over a `.legend` of `[(test, runs), …]`, so
this key is that pair of answers as data - one row per test, `slots`/`ends` the
shared axis, `runs` the legend's number, and `points` the `(position, percent)`
pairs `line_chart` splines.  `tests` is `lib/tests.py:TESTS` rather than the
tests any page happens to have seen, because that tuple is also what
`Filter.test` accepts: offering a fourth name would be a filter value the filter
itself refuses (`models.Filter.from_query`'s `one_of`).  On this workspace the
two agree exactly - the 60 records carry `boot` (22), `kselftest-riscv` (19) and
`kselftest-kvm` (19), and nothing else.
"""

import html
import re
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ... import api as api_mod
from ... import errors, layout
from ... import re as re_mod
from ... import run as run_mod
from ...i18n import DEFAULT_LANG, t
from ...kbuild import Kbuild, Kbuilds
from ...tests import DEFAULT_TESTS, TESTS
from ..activities import WORKER_KIND
from ..models import Filter
from ..pairs import _build_ref
from ..schema import (
    API_TIMEOUT,
    DEFAULT_DELTA,
    EVIDENCE,
    JOB_STATES,
    KINDS,
    LIVE_KEPT,
    ORIGINS,
    PILL_WORDS,
    QUEUE_ROWS,
    ROWS,
    SORTS,
)
from ..sorting import _sort_label, _sort_rows
from ..values import _host, _human, _last_verdict, _short, _vocabulary

if TYPE_CHECKING:
    from ...re import Records

# The three artifacts the design's card column draws, in the order it draws them:
# `lib/build/model.py`'s `ARTIFACTS` minus `config`.  The names belong to that
# table and the *subset* belongs to the design - `config` is the comparison input
# and not part of what a build needs to run (`tests.TESTS[x]["needs"]` names the
# other three and never it), so a tick for it would be a fourth cell answering a
# question no column asks.  The order is the prototype's (`proto/pages.py`'s
# `ARTIFACTS`), which is also the order the board draws them in.
CARD_ARTIFACTS = ("kernel", "kselftest", "modules")

# What one MiB is, for the `bytes_mib` column: the shape's own unit, not a
# formatting choice - `builds.py`'s `_bytes_cell` prints `_human(size)` in the
# same cell, and the fixture's `bytes_mib` is a float a page formats itself.
MIB = 1 << 20


def rows(gui: Any, check: "Filter | None" = None,
         lang: str = DEFAULT_LANG) -> dict[str, Any]:
    """Every row the design's five screens read, from this request's own reads.

    One function and not five, because the design's dict *is* one request: the
    filter bar, the number strip and the five screens are drawn from the same
    answer, and a screen that read its own half would be a second question.

    `check` is the request's filter; `None` means the console's own default
    (`rows` wide, `origin="any"`, the default comparison cap), which is what every
    internal reader in `lib/gui/` does with a filter nobody passed.
    """
    if check is None:
        check = Filter(limit=gui.rows, origin="any", delta=DEFAULT_DELTA)
    table, records = gui._state()
    held = gui.all_locals()
    answer = gui.remote_rows(check, held, lang)
    # Every activity, once: `/runs`, the live strip and the `activities` count are
    # three readings of one answer (`Gui.runs()` is memoised for the request).
    activities = gui.run_rows()
    # The analysis half, in the order `/analysis` builds it: the pool the page can
    # name, the filter's own order, then the comparisons of the head of that order.
    # `Gui._known_builds` reads the API a second time at `check.limit` - the same
    # HTTP answer as `remote_rows` above (one query, one memo) and the only reader
    # that also hands back the local cards as `Kbuild`s, which `Drift` needs.
    known, builds = gui._known_builds(check.api, check.limit)
    catalogue = Kbuilds(gui._client(gui.api_base(check)), items=builds)
    pool = _build_rows(known, builds, check, records, held, lang)
    ordered = _sort_rows(pool, check.sort)[:check.limit]
    head = ordered[:max(0, check.delta)]
    edges = gui._config_edges(head, catalogue, check, lang) if len(head) > 1 else []
    # `Gui.runs()` is the activities themselves - `run_rows` is the same list as
    # rows, and it carries no `pid` - so the one field the row shape needs and the
    # row reader does not hand on is read from the objects it was built from
    # (memoised with them: no second walk of `var/runs/`).
    processes = {one.id: one for one in gui.runs()}
    return {
        "builds": _builds(gui, check, held, answer, lang),
        "pulls": _pulls(gui.pull_acts()),
        "gap": _gap(gui.job_rows(check)),
        "ledger": _ledger(records),
        "worker": _worker(gui, activities, processes),
        "queue": _queue(gui, check),
        "runs": _runs(activities, processes),
        "picks": _picks(ordered, edges, records, check),
        "bars": _bars(ordered, records, check),
        "timelines": _timelines(pool, records, check),
        "series": _series(ordered, gui, records),
        "drift": _drift(edges),
        "activities": _live(activities),
        "counts": _counts(gui, table, records, held, check, lang),
        "apis": [(name, base) for name, base in gui.apis.entries()],
        "sorts": _sorts(lang),
        "trees": _vocabulary("tree", check, answer, table),
        "branches": _vocabulary("branch", check, answer, table),
        "arches": _vocabulary("arch", check, answer, table),
        "defconfigs": _vocabulary("defconfig", check, answer, table),
        "compilers": _vocabulary("compiler", check, answer, table),
        "tests": list(TESTS),
        # The kinds the console's own buttons start (`schema.KINDS`'s values, the
        # same eight the prototype lists) rather than the kinds that happen to be
        # on disk: a kind nobody has run yet is still one a button can start.
        "kinds": sorted(set(KINDS.values())),
        "run_states": list(PILL_WORDS["run"]),
        "origins": list(ORIGINS),
        "evidences": list(EVIDENCE),
        "drawn": time.strftime("%Y-%m-%d %H:%M:%S"),
        # The four directories this dict was read out of, in the order the design's
        # footer names them.  `layout`'s own accessors, so a moved directory is one
        # edit in one file - and absolute, because that is what `layout` answers and
        # a second spelling of the workspace here is the thing check 4 forbids.
        "drawn_from": [layout.index(), layout.downloads(), layout.results(),
                        layout.runs()],
    }


# ------------------------------------------------------------------ the builds
def _builds(gui: Any, check: Filter, held: dict, answer: Any,
            lang: str) -> list[dict[str, Any]]:
    """One row per build id: the card, the bytes, the pull record, the API, the ledger.

    `Gui.build_rows` already assembles exactly these facts for the shipped `/`
    page - the union of the API's answer and this disk, capped once, newest first -
    so this is a rename into the design's shape and not a second union.  What each
    cell became:

    * **`checks`** is what is *on disk* per artifact (`Local.present`, one
      `os.path.isfile` each), which is the design's tick with `title="present"`.
      It is deliberately not "what the card declares": a card with nothing behind
      it is precisely the row the three ticks exist to make visible, and reading
      the card's URLs would tick all three for a copy with no bytes at all.
    * **`here`** is `Local.state` - the engine's own five-word verdict on what this
      machine holds (`pulled`/`unrecorded`/`registered`/`made-here`/`empty`).  The
      fixture's `whole`/`partial`/`card only` is a word this tree does not have a
      reader for, and inventing one here would be a second opinion about a
      directory next to `Local.state`'s.
    * **`api`** is the API's own answer for this row, `(state, result, node_id)`,
      or `None` when this page's answer did not carry it.  `None` covers two
      different facts that `builds._api_cell` tells apart (a copy with no remote
      counterpart at all, and one outside the window's cap) - the fixture's shape
      has one slot for both, and the page prints its own sentence for it.
    * **`ran`** is one `(test, verdict-or-None)` per `DEFAULT_TESTS`, from
      `records.last(test, build_id)` - the ledger's own answer, which does not care
      whether the table or only a directory named this build.

    **One row is one id, and this function does not enforce that**: `build_rows`
    collects its ids from the API's answer as they come, while its own lookup dict
    is keyed by `build_id`, so an API that answers the same build on two nodes
    makes two rows here.  This deployment's local stack does exactly that today -
    it answers 5 kbuild nodes for 3 distinct ids, `6aade015d96a8203de6dff37` three
    times - so `?origin=card` renders 55 rows for 53 builds.  The reader that owns
    that promise is `BuildsMixin.build_rows` ("one row per build id" is its own
    docstring); deduplicating here would make this dict disagree with the page it
    is replacing, which is the one thing a reshape may not do.
    """
    found = []
    for one in gui.build_rows(check, held, answer, lang):
        kbuild = one["remote"]
        found.append({
            "build_id": one["build_id"], "tree": one["tree"], "branch": one["branch"],
            "created": one["created"],
            "checks": {name: name in set(one["present"]) for name in CARD_ARTIFACTS},
            "here": one["state"],
            # `local.size()` sums the files it found, so a copy with nothing on disk
            # has 0 bytes and not "unknown": the dash and the zero are the same fact
            # and the fixture prints the dash.
            "bytes_mib": round(one["size"] / MIB, 1) if one["size"] else None,
            "acts": one["acts"], "acts_host": ", ".join(one["act_hosts"]),
            "acts_when": one["act_at"],
            "api": ((kbuild.state, kbuild.result, _short(kbuild.node_id))
                    if kbuild is not None else None),
            "ran": [(test, one["verdicts"].get(test) or None) for test in DEFAULT_TESTS],
        })
    return found


# ------------------------------------------------------------------ the pulls
def _pulls(acts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every pull act `Build.make()` recorded, newest first, as the panel's own row.

    `Gui.pull_acts()` is already one row per act with the build id, the time, the
    reason it failed and the entries; the four derived cells are the ones
    `builds._pulls_panel` prints, computed the same way from the same entries:

    * `transferred` counts the entries whose transfer actually moved bytes (the
      act's own `transferred` flag, written by `Build.make()`), which is the one
      number that tells a re-check from a real fetch;
    * `hosts` is `values._host` over the entries, deduplicated and sorted, with an
      empty host dropped - `file://` artifacts have none and `Local.hosts()` drops
      them for the same reason (a leading comma is not a machine);
    * `bytes_raw` is the act's own byte count (the sum of its entries) and `mib`
      its human spelling, kept apart because a table wants both;
    * `error` is `None` rather than `""` when the act succeeded, so a page can test
      it with `if row["error"]`.
    """
    found = []
    for one in acts:
        entries = [entry for entry in one["entries"] if isinstance(entry, dict)]
        hosts = {_host(str(entry.get("url") or "")) for entry in entries}
        found.append({
            "when": one["at"], "build_id": one["build_id"],
            "artifacts": one["entries_count"], "bytes_raw": one["bytes"],
            "mib": _human(one["bytes"]),
            "transferred": sum(1 for entry in entries if entry.get("transferred")),
            "hosts": ", ".join(sorted(host for host in hosts if host)),
            "error": one["error"] or None,
        })
    return found


# ------------------------------------------------------------------- the jobs
def _gap(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (build, test): whether it ran, and whether it *can* run here.

    `Gui.job_rows` merges the two halves the design's `/jobs` screen keeps on one
    page - `re.todo()` (the pairs with no record) and the ledger's own verdict for
    the rest - so this is a rename.  Two fields are worth stating:

    * `ready` is `not reason`: `reason` is `Build.missing(test)` joined, which is
      empty exactly when every artifact the test needs is on disk.  The design's
      queue panel uses it to disable the tick box of a row that cannot run, and it
      must be that predicate and not a second one written here.
    * `last`/`when` are `None` when the ledger has no record for the pair, so a
      page prints a dash rather than an empty cell that could be a verdict.
    """
    return [{
        "build_id": one["build_id"], "tree": one["tree"], "test": one["test"],
        "needs": one["needs"], "ready": not one["reason"], "runs": one["runs"],
        "last": one["verdict"] or None, "when": one["when"] or None,
        "gap": one["gap"],
    } for one in jobs]


def _ledger(records: Any) -> list[dict[str, Any]]:
    """The ledger in full, newest first: every record, whoever wrote it.

    `Records` is the only reader of `var/results/`, and `source` is its own field -
    the column the design's worker panel filters on to answer "did my worker run?"
    (`worker` is the word a `pull_worker.py` run writes).  The order is the newest
    record first, which is the order `builds.local` prints one build's records in;
    the ledger's own read order is a directory walk and means nothing to a reader.
    """
    newest = sorted(records, key=lambda one: (one.timestamp or "", one.build_id, one.test),
                    reverse=True)
    return [{
        "build_id": one.build_id, "test": one.test, "verdict": one.verdict,
        "exit": one.exit_code, "source": one.source, "when": one.timestamp,
        "detail": one.detail,
    } for one in newest]


# ----------------------------------------------------------------- the worker
def _worker(gui: Any, activities: list[dict[str, Any]],
            processes: dict[str, Any]) -> dict[str, Any]:
    """What the poll loop is doing: the live process, and the state file it writes.

    Two readers, and neither is interpreted here.  `Gui.worker_state()` is the JSON
    `lib/poller.py` wrote, read as the document it is (`STATE_FIELDS` is
    `timestamp`/`seen`/`pending`, and the cursor is the `timestamp` - the poller's
    own name for it, not a second timestamp this page keeps).  The process side is
    `Gui.run_rows()`'s own worker row, which is where `running`, `pid`, `argv` and
    the age come from: `uptime` is `Run.age()`'s answer and not a subtraction here.

    `pid` is read off the `Run` the row was built from, because `run_rows` does not
    hand it on: `pid` is a fact about a process and `run_rows` is a fact about a
    row.  The `Run`s are memoised with the rows (`Gui.runs()`), so this join costs
    no second walk of `var/runs/` - and the reader that would have to grow for this
    module to stop doing it is `Gui.run_rows` (one more key in its dict).
    """
    state = gui.worker_state()
    mine = [one for one in activities if one["kind"] == WORKER_KIND]
    live = [one for one in mine if one["state"] == run_mod.RUNNING]
    newest = (live or mine or [None])[0]
    process = processes.get(newest["id"]) if newest is not None else None
    stored = state.get("seen") or []
    pending = state.get("pending") or {}
    return {
        "running": bool(live),
        "run_id": newest["id"] if newest is not None else "",
        "pid": process.pid if process is not None else 0,
        "started": _clock(newest["started"], "%Y-%m-%dT%H:%M:%S")
                   if newest is not None else "",
        "uptime": newest["age"] if newest is not None else "",
        "argv": " ".join(newest["argv"]) if newest is not None else "",
        "state_file": layout.worker_state(),
        "cursor": str(state.get("timestamp") or ""),
        "seen": len(stored), "pending": len(pending),
    }


def _queue(gui: Any, check: Filter) -> list[dict[str, Any]]:
    """The API's job queue, newest first - the rows `Gui.job_node_rows` answers.

    Read as wide as `/worker` reads it (`QUEUE_ROWS`, because the page's own
    platform and runtime boxes are built out of the same answer) and printed as
    wide as this filter's `limit`, exactly as `worker.py` does: one read of
    the largest collection in the API for one question.

    The state is `check.state or "available"`, which is the shipped route's own
    default (`serve.py`'s `PAGE_STATE` for `/worker`): a worker page is about what a worker
    can *claim*, and a table of 200 finished nodes beside a "nothing to claim"
    badge is two true sentences that mean nothing together.  `Filter.state` also
    spells the *kbuild* state axis, and the two vocabularies overlap where they
    must (`done`, `running`); a `/worker` URL says `?state=available`, which
    `_named` carries through untouched, so the page key and this one are one
    string.
    """
    state = check.state or JOB_STATES[1]
    found, _why = gui.job_node_rows(check, state, QUEUE_ROWS)
    return [{
        "node_id": one["node_id"], "name": one["name"], "state": one["state"],
        # `result` is `""` on a node that has not run yet (`lib/kjob.py` reads the
        # API's own field), and the design's shape says `None`: both are falsy, and
        # `None` is the one a page can compare against without a second spelling of
        # "no answer".
        "result": one["result"] or None, "platform": one["platform"],
        "runtime": one["runtime"], "created": one["created"],
        "claimed": one["claimed"], "definition": one["definition"],
    } for one in found[:check.limit]]


# ------------------------------------------------------------------- the runs
def _runs(activities: list[dict[str, Any]], processes: dict[str, Any]) -> list[dict[str, Any]]:
    """Every background process this console started, newest first.

    `Gui.run_rows()` is the whole activity tree (`var/runs/<id>/run.json`), newest
    first, with the age and the exit code already decided by `lib/run.py`; the two
    conversions here are the shape's, not the reader's:

    * `started`/`ended` are epoch floats in `run.json` (what the 2 s poll compares
      against `data-drawn`, `07-shell.md` §C1) and clock times in the design's
      table.  `ended` is `0.0` while a run is going, which is not a time - hence
      `None` rather than `00:00:00`.
    * `argv` is a list on disk (it is what `Run.start()` passed to `Popen`) and one
      copyable string in the cell, which is what the design truncates and what an
      operator pastes into a shell.

    `pid` comes from the `Run` objects the rows were built from, for the reason
    `_worker` gives.
    """
    found = []
    for one in activities:
        process = processes.get(one["id"])
        found.append({
            "id": one["id"], "kind": one["kind"], "state": one["state"],
            "pid": process.pid if process is not None else 0,
            "started": _clock(one["started"]), "ended": _clock(one["ended"]) or None,
            "exit": one["exit_code"], "age": one["age"], "what": one["what"],
            "argv": " ".join(one["argv"]),
            # `tally` is the chip the script draws beside a `run`/`runday`/`table`
            # activity ("41 pass / 9 fail / 1 incomplete"), and it is the one cell the
            # second poll knows and the first paint did not: `/api/runs` answers
            # `run_rows()`, which carries it.  Twelve of this workspace's eighty
            # activities have one, so a page that left it out would draw twelve rows
            # that grow a chip two seconds after they were drawn.
            "tally": one.get("tally") or {},
        })
    return found


def _live(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The activity strip: everything running, then the last few that ended.

    The same rule the shipped live panel follows (`Gui.worker_bases` states it for
    the worker page): the running rows are the ones a reader is watching and the
    ended ones are context, so a list of eighty old activities is not a "live"
    panel.  `schema.LIVE_KEPT` is the same number the panel and the script share,
    imported rather than spelled again - one number, one place.
    """
    running = [one for one in activities if one["state"] == run_mod.RUNNING]
    ended = [one for one in activities if one["state"] != run_mod.RUNNING][:LIVE_KEPT]
    return [{
        "run_id": one["id"], "kind": one["kind"], "state": one["state"],
        "age": one["age"], "what": one["what"], "argv": " ".join(one["argv"]),
        "exit": one["exit_code"],
        # `seconds`, `started` and `ended` ride along because the panel's elapsed
        # cell is rewritten by the shipped script two seconds later from its own
        # `liveTime()`, and that function counts from `started`.  A server-drawn row
        # carrying only the coarser `age` would print one number and then change it on
        # the first poll, which reads as the page correcting itself.  The old shell's
        # panel (`Gui.run_rows()` rows) hands the same three fields over.
        "seconds": one.get("seconds"), "started": one.get("started"),
        "ended": one.get("ended"),
    } for one in (*running, *ended)]


# --------------------------------------------------------------- the analysis
def _build_rows(known: list[str], builds: list[Kbuild], check: Filter, records: "Records",
                held: Mapping[str, Any], lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
    """The builds this page can name, as rows: what it read, what it holds, what the ledger says.

    **The filter decides which builds are in this list.**  `tree`, `branch`, `arch`,
    `defconfig`, `compiler`, `state`, `result`, `text`, `origin`, `has`, `missing`,
    `evidence`, `ran` and `verdict` go through `Filter.accepts` - the same predicates
    every other table in this program uses - so the bar above the list means what it
    means everywhere else and the renderer computes nothing (`00-BRIEF.md` rule 2).

    Nothing here is fetched: the `Kbuild` comes from `_known_builds` (one read the page
    was making anyway), the local copy from `all_locals()` and the record count from
    `_state()`, both cached for this request.  The API cannot be asked for a build *by
    id* (`lib/kbuild.py: SCAN`, 116.8-137.9 s measured), so a chooser that wanted more
    detail per row would pay a hundred-second scan for it; everything a reader needs to
    tell two builds apart is in the row the page already has (`06-analysis.md` §A3).

    `known` is every id the page can name - including the directories under
    `var/downloads/` that no card names, which have no `Kbuild` at all.  They are rows
    too (the id, and what is on disk), they are simply not comparable: no card means no
    `_config` artifact, which is one of the three refusals §A7 measured.
    """
    cards = {build.build_id: build for build in builds}
    rows = []
    for build_id in known:
        kbuild = cards.get(build_id)
        local = held.get(build_id)
        if not check.accepts(kbuild, records, local):
            continue
        found = records.for_build(build_id)
        revision = (kbuild.revision or {}) if kbuild is not None else {}
        config = kbuild.artifact("_config") if kbuild is not None else ""
        rows.append({
            "build_id": build_id, "kbuild": kbuild,
            "created": str(kbuild.created or "") if kbuild is not None else "",
            "tree": str(kbuild.tree or "") if kbuild is not None else "",
            "branch": str(kbuild.branch or "") if kbuild is not None else "",
            "series": _series_of(revision.get("describe")),
            "verdict": found.items[-1].verdict if found.items else "",
            "config": bool(config), "config_url": config,
            "records": len(found),
            "held": bool(local is not None and local.present),
            "ref": _build_ref(kbuild),
            "line": _build_line(kbuild, revision, build_id),
            "marks": _build_marks(config, local, len(found), lang),
        })
    return rows


def _series_of(describe: Any) -> str:
    """The kernel series a build belongs to, out of its `describe` (`v6.12.108-2861-…` -> `v6.12`).

    The one signal this page has for "these are two different kernels" without reading a
    config.  It is searched for rather than anchored, because this deployment's newer
    builds carry a topic prefix (`asoc-fix-v7.3-rc3-803-g9f1c440f92830`) and an anchored
    pattern would call all of them series-less.  A describe string with no `v<major>.<minor>`
    (`next-20260915`) yields `''`, which `_chosen_pair` treats as *unknown* and never as
    a series of its own - the alternative would make two unknown builds "different".
    """
    found = re.search(r"\bv(\d+\.\d+)", str(describe or ""))
    return f"v{found.group(1)}" if found else ""


def _build_line(kbuild: "Kbuild | None", revision: Mapping[str, Any], build_id: str) -> str:
    """The two lines the operator asked for: what the build *is*, then its details.

    A native `<option>` cannot wrap to two lines - its content model is text, browsers
    render one line and ignore child elements (`06-analysis.md` §A4) - which is why the
    chooser is a table of links rather than a select box.  Line one is the fact that
    tells two builds apart, line two the fields a reader checks next.  The commit is
    shortened to twelve characters because the full forty are in the record's own
    `title` and on the correspondence page.
    """
    if kbuild is None:
        return (f'<code title="{html.escape(build_id)}">{html.escape(build_id)}</code>'
                '<br><span class="sub">-</span>')
    named = _build_ref(kbuild)
    detail = " · ".join(part for part in (str(kbuild.created or ""),
                                          str(kbuild.compiler or ""),
                                          str(kbuild.arch or ""),
                                          str(kbuild.defconfig or ""),
                                          str(revision.get("commit") or "")[:12]) if part)
    return (f'<b>{html.escape(named) or html.escape(build_id)}</b>'
            f'<br><span class="sub">{html.escape(detail)}</span>')


def _build_marks(config: str, local: Any, records: int, lang: str = DEFAULT_LANG) -> str:
    """Three marks per row: can this build be compared, is there a copy here, has it run.

    They are the facts that decide the questions a reader is about to ask, and two of
    them are what makes a doomed pair visible **before** it is picked: `config -` is a
    build no comparison can use (`06-analysis.md` §A7), and the artifact URL is in the
    `title=` for the reader who wants the raw file.
    """
    def mark(word: str, yes: bool, title: str = "") -> str:
        attr = f' title="{html.escape(title)}"' if title else ""
        return (f'<span class="{"yes" if yes else "no"}"{attr}>'
                f'{html.escape(word)} {"&#10003;" if yes else "&mdash;"}</span>')

    held = bool(local is not None and local.present)
    return ('<span class="marks">'
            + mark(t(lang, "word.config"), bool(config), config) + " "
            + mark(t(lang, "col.bytes"), held) + " "
            + f'<span>{t(lang, "mark.records")} {records}</span></span>')


def _picks(ordered: list[dict[str, Any]], edges: list[dict[str, Any]], records: Any,
           check: Filter) -> list[dict[str, Any]]:
    """The builds this page can name, in this page's order, with their neighbours' deltas.

    `ordered` is `_build_rows` + `_sort_rows` - the same two readers the shipped
    `/analysis` list uses, so the selection, the order and the adjacency are the
    engine's and not this module's.  A row's two deltas are the comparisons
    *around it in that order*, which is what makes `sort` a condition and not page
    state: `delta_up` is the edge the row before it made and `delta_down` the edge
    it makes with the row after, so a row at index `i` reads `edges[i-1]` and
    `edges[i]` - and `None` past the cap, where `_config_edges` was never asked
    (the cap is `check.delta`, and `_delta_cell` prints the same distinction).

    `None` covers two cases and the design's tuple has one slot for both: a pair
    *past the cap* and a pair the engine **refused** (no card, a `.config` that is
    not a kernel config, an id outside the scan).  A refused pair is not a zero -
    `pairs._delta_cell` prints the engine's own words for it - so a page that needs
    the reason asks `gui.drift(older, newer)`, which is the reader that has it.

    The verdict and the three TAP numbers come from the record for **the test this
    page is about** (`check.test`, else `DEFAULT_TESTS[0]` - the same expression
    `_analysis` uses), through `_last_verdict_row` below, so the pill and the
    counts beside it are about one run.  A record whose test died before TAP ran
    holds no counts, and `_cases_text`'s rule is followed here: `0/0` is a claim
    the ledger does not make, so the three numbers are `None` and the page prints
    a dash.  (On this deployment every `boot` record holds `results: {}` - boot is
    not a TAP test - so the counts fill in for the two kselftest tests and read as
    a dash under `?test=boot`.)

    `_build_rows` carries a `verdict` of its own for the same row - the build's
    newest record of *any* test - and that is what `sort=verdict` orders by; this
    cell is deliberately the test in force instead, because a pill and three counts
    under it have to be one run, and `_build_rows` does not say which record spoke.
    """
    test = check.test or DEFAULT_TESTS[0]
    found = []
    for at, one in enumerate(ordered):
        record = _last_verdict_row(records, test, str(one["build_id"]))
        results = record.get("results") or {}
        counted = bool(results.get("total")) or bool(results.get("failed"))
        found.append({
            "rank": at + 1, "build_id": one["build_id"], "tree": one["tree"],
            "branch": one["branch"],
            "describe": str((one["kbuild"].revision or {}).get("describe") or "")
                        if one["kbuild"] is not None else "",
            "verdict": record.get("verdict") or None,
            "total": int(results.get("total") or 0) if counted else None,
            "failed": int(results.get("failed") or 0) if counted else None,
            "skipped": int(results.get("skipped") or 0) if counted else None,
            "delta_up": _delta(edges, at - 1), "delta_down": _delta(edges, at),
        })
    return found


def _delta(edges: list[dict[str, Any]], at: int) -> "tuple[int, int, int] | None":
    """One edge as the design's `(added, removed, changed)`, or `None`.

    The three numbers are `len()` of what `Drift` answered - `added`, `removed` and
    `changed` are dicts of config options and the page prints their sizes, exactly
    as `ui.delta` does.  An edge that was refused (`report is None`,
    with the engine's reason in `error`) has no numbers and answers `None`, which
    `_picks` documents.
    """
    if not (0 <= at < len(edges)):
        return None
    report = edges[at].get("report")
    if report is None:
        return None
    return (len(report.added), len(report.removed), len(report.changed))


def _bars(ordered: list[dict[str, Any]], records: Any, check: Filter) -> list[dict[str, Any]]:
    """One bar per build for the test in force: what answered, and how it answered.

    The three numbers are **this build's own** records and not a running total -
    the distinction the design's panel exists to draw - and they are a tally of the
    ledger's own verdict words (`Records.for_test(...).for_build(...).tally()`,
    which is `Records.tally()` narrowed twice, not a count kept here).

    The ledger has four verdicts (`lib/errors.py`) and the design three colours:
    `pass` is `ok`, `fail` is `bad`, and the third is **what did not answer** -
    `incomplete` and `error` both mean the run produced no verdict about the
    kernel, which is one thing to a reader looking at a bar.  The scope is the test
    the page is about, like `_picks`, so the bar above a row and the pill in it are
    about the same run.
    """
    test = check.test or DEFAULT_TESTS[0]
    scoped = records.for_test(test)
    found = []
    for one in ordered:
        counts = scoped.for_build(str(one["build_id"])).tally()
        bad = counts.get(errors.VERDICT_FAIL, 0)
        ok = counts.get(errors.VERDICT_PASS, 0)
        found.append({"build_id": one["build_id"], "ok": ok, "bad": bad,
                      "warn": sum(many for verdict, many in counts.items()
                                  if verdict not in (errors.VERDICT_PASS,
                                                     errors.VERDICT_FAIL))})
    return found


def _wave_slots(rows: list[dict[str, Any]], records: "Records",
                test: str) -> list[dict[str, Any]]:
    """One slot per position of the page's order: the build, and what this test has for it.

    A slot is a *position*, not a run: the list is the page's whole order (gaps included),
    and every position the ledger has no record for is a slot with `gap` - which is how
    the chart can show a test that stopped, instead of a line that pretends it never ran.

    **`gap` is `not found`, and it used to be `found is None`.**  `_last_verdict_row`
    answers `{}` for a position with no record - it never answers `None` - so that test
    was false at *every* position: `gap` was always `False`, every no-record slot was
    handed on as a run whose verdict happened to be the empty string, and the two things
    that read it were both wrong at once.  `_wave_chart` never drew a single dashed gap
    cell or linked to `/jobs` (its gap branch is dead under `gap == False`), and
    `chart.band_sub` - `{ran} with a record, {gap} with none`, counted from these same
    slots - printed `50 with a record, 0 with none` over an order where the ledger had
    19.  The empty string is what gave it away: `verdict` is `""` for exactly the
    positions `gap` claimed did not exist, and the new line chart counted 16 runs where
    the sentence above it claimed 50.  Found while building `_trend_lines`; the two
    readers are correct as written and this one line was the whole of it.
    """
    slots = []
    for at, row in enumerate(rows):
        build_id = str(row["build_id"])
        found = _last_verdict_row(records, test, build_id)
        slots.append({
            "at": at, "build_id": build_id, "record": found,
            "verdict": str(found.get("verdict") or "") if found else "",
            "gap": not found,
        })
    return slots


def _last_verdict_row(records: "Records", test: str, build_id: str) -> dict[str, Any]:
    """The newest record for one (test, build) pair, as a plain dict, or `{}`.

    `Records.series` already answers this and hands back `Outcome` objects; the chart
    wants the record's own fields (verdict, results, timestamp) per column, so this is
    one lookup per build with no second parse - `Records` is in memory for the request.
    """
    found = records.series(test, build_id)
    if not found:
        return {}
    newest = found[-1]
    return {"verdict": getattr(newest, "verdict", ""),
            "timestamp": getattr(newest, "timestamp", ""),
            "source": getattr(newest, "source", ""),
            "exit_code": getattr(newest, "exit_code", None),
            "detail": getattr(newest, "detail", ""),
            "results": getattr(newest, "results", {}) or {}}


def _timelines(pool: list[dict[str, Any]], records: Any,
               check: Filter) -> list[dict[str, Any]]:
    """One line per test: how many records, the newest verdict, and the run of them.

    `runs` and `last` are `Records.series`/`values._last_verdict` and `regressions`
    is `re.transitions()` - the engine's own three answers, unchanged.

    `marks` is the one place this dict chooses a *position axis*, and the choice is
    stated rather than implied: **one mark per build, oldest first**, `None` where
    the ledger has nothing for that (build, test) pair.  A timeline is a test over
    time, so the axis is the date order and not the reader's sort (`sort` decides
    what is compared with what, and that is the `picks` list's job); the positions
    are the builds this page can name - the newest `check.limit` of them, which is
    the same window the `picks` list shows under the default order, kept newest
    rather than oldest so that "the last 25 builds" means the same thing in both
    panels.  `_wave_slots` below is the reader that already answers exactly this
    per position - it is what the wave chart of `/analysis` always drew - and `None`
    is a position and not a run: the design draws it as an empty square
    (`no record`), which is how a test that *stopped* is visible instead of a line
    that pretends it never ran.
    """
    marks_order = _sort_rows(pool, "date-asc")[-check.limit:]
    found = []
    for test in DEFAULT_TESTS:
        marks = _wave_slots(marks_order, records, test)
        found.append({
            "test": test, "runs": len(records.series(test)),
            "last": _last_verdict(records, test),
            "regressions": len(re_mod.transitions(records, test)),
            "marks": [one["verdict"] or None for one in marks],
        })
    return found


def _series(ordered: list[dict[str, Any]], gui: Any, records: Any) -> list[dict[str, Any]]:
    """One line per test across the positions of the page's order: the pass rate.

    The design's chart panel (`ui.line_chart`, `ui.legend`) draws one polyline per
    test with `x` on **the order** and `y` on a percentage, so this key is that
    pair of answers as rows: `slots` is how many positions the axis has, `ends` the
    two builds under its ends, `runs` the number the legend prints beside each
    name, and `points` the `(position, percent)` pairs the line is drawn through.
    Every row carries the axis as well as its own points, so a row is complete on
    its own (`slots` and `ends` are the same in all of them - there is one axis).

    **A point exists only where the ledger has a record.**  A position this test
    has nothing for is left out rather than drawn at zero or carried forward: a gap
    is not a failure, it is the same gap `timelines.marks` prints as an empty
    square - which is the break the design's own caption promises and its invented
    drawing does not have.  What a renderer does with a jump in `at` is the
    renderer's business (`ui.line_chart` draws the polyline it is given and leaves
    the missing position out of it); what this key owes it is that there is **no
    point** at a position the ledger has nothing for, so a break can be drawn at
    all.

    **The percentage is the record's own verdicts, accumulated over these
    positions.**  At position *i* it is the share of this test's runs up to and
    including *i* that came back `pass` - the accumulated shape
    `_series` below documents as the only honest one ("a build has at most
    one record for a test, so a per-class value that is not accumulated is `0` or
    `1` at every position - a rug and not a line"), expressed as a share because
    this axis is a percentage.  Nothing is classified here: the numerator is the
    count of `errors.VERDICT_PASS` among the record's own words and the denominator
    is how many runs are in the window, which is also why every test has a line -
    a TAP ratio would leave `boot`, which reports no TAP counts at all, without one.
    The accumulation is over the page's positions and not over the ledger's history,
    exactly as `_trend_lines` says, so the two pictures of one answer agree.

    The points come from `Gui.trend(test, scope)`, which owns "this test's records
    with their regressions" (a point carries the record's `verdict` and whether the
    ledger called it a regression); the run count comes from `Records.series(test)`,
    the reader `trend` is built on and the number `timelines.runs` already prints.
    `Gui.trend` is asked for the whole series, so a record for a build this page
    does not list is dropped by the mapping below and never by a cap here; where a
    build has several records for one test the newest speaks, which is the rule
    `_wave_slots` and `timelines.marks` use for the same axis.
    """
    slots = len(ordered)
    ends = ((str(ordered[0]["build_id"]), str(ordered[-1]["build_id"]))
            if ordered else ("", ""))
    found = []
    for test in DEFAULT_TESTS:
        history = records.series(test)
        newest: dict[str, dict[str, Any]] = {}
        # `trend`'s points are the series oldest first, so the last write per build
        # is that build's newest record - no second lookup, no second parse.
        for point in gui.trend(test, max(1, len(history)))["points"]:
            newest[str(point["build_id"])] = point
        points = []
        runs = 0
        passed = 0
        for at, one in enumerate(ordered):
            point = newest.get(str(one["build_id"]))
            if point is None:
                continue
            runs += 1
            if point["verdict"] == errors.VERDICT_PASS:
                passed += 1
            points.append({"at": at, "build_id": str(one["build_id"]),
                           "pct": round(100.0 * passed / runs, 1),
                           "verdict": point["verdict"],
                           "regression": bool(point["regression"])})
        found.append({"test": test, "runs": len(history), "slots": slots,
                      "ends": ends, "points": points})
    return found


def _drift(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The config difference of every pair that was read, as the command that answers it.

    One row per adjacent comparison of the head of the page's order - the same
    `edges` the `picks` column is built from, so the number in a row and the row in
    this table cannot disagree.  A pair the engine refused has no numbers and is
    **absent** here rather than printed as `0/0/0`: "no drift" and "not comparable"
    are different answers, and `_why_of` is where the second one is spelled out.
    """
    return [{
        "left": edge["older"].build_id, "right": edge["newer"].build_id,
        "added": len(edge["report"].added), "removed": len(edge["report"].removed),
        "changed": len(edge["report"].changed),
    } for edge in edges if edge.get("report") is not None]


# ------------------------------------------------------------- the number strip
def _counts(gui: Any, table: Any, records: Any, held: dict, check: Filter,
            lang: str) -> list[tuple[str, str, str]]:
    """The seven numbers the console prints above its tables, and where each came from.

    `builds._strip` is the reader of every one of them, and every one
    is read **uncapped** there for a reason worth keeping: a number a link
    reproduces cannot be a slice, so a chip counting 53 copies must not be built
    from a 50-row page.  The three parts of a row are the design's:

    * the **label**, from the catalogue in this response's language (`counts.*`),
      so the strip is translated like every other word on the page;
    * the **value**, as a string, because a chip is text and every one of these is
      a whole count;
    * the **source**, which is the sentence or the path that says where the number
      came from: `layout`'s own accessor for the three that are a file or a
      directory (`cards` is `layout.index()`, `here` is `layout.downloads()`,
      `activities` is `layout.runs()`), the catalogue's sentence for the three that
      are predicates over the disk (`counts.title_bytes`, `counts.title_acts` with
      the provenance path, `counts.title_records` with the count and the ledger's
      directory), and - for the gap - the strip's own `label.gap` plus the name of
      the function that answers it (`re.todo()`), which is what `builds._strip`
      prints and the one entry here that is a mechanism rather than a path.

    `gap` is this filter's own gap (`Gui.todo(check)`, already walked for
    `job_rows`, so no second walk of 156 pairs) - on a page that has narrowed the
    tests it is the narrower number, and on a page that has not it is the whole
    one the old strip printed.
    """
    return [
        (t(lang, "counts.cards"), str(len(table)), layout.index()),
        (t(lang, "counts.here"), str(len(held)), layout.downloads()),
        (t(lang, "counts.bytes"), str(sum(1 for one in held.values() if one.present)),
         t(lang, "counts.title_bytes")),
        (t(lang, "counts.acts"), str(len(gui.pull_acts())),
         t(lang, "counts.title_acts", provenance=layout.provenance("<build-id>"))),
        (t(lang, "counts.records"), str(len(records)),
         t(lang, "counts.title_records", n=len(records), dir=layout.results())),
        (t(lang, "counts.gap"), str(len(gui.todo(check))),
         t(lang, "label.gap") + " - re.todo()"),
        (t(lang, "counts.activities"), str(len(gui.runs())), layout.runs()),
    ]


def _sorts(lang: str) -> list[tuple[str, str]]:
    """Every order `/analysis` can be put in, as `(the value a URL carries, its name)`.

    `schema.SORTS` is the vocabulary and `sorting._sort_label` is the one function
    that turns a value into the words this reader sees (`date ↓`, `总分支 ↑`), so
    neither the values nor the labels are spelled here.  The empty value is the
    page's own default rather than a choice a box offers, which is why it is
    dropped: `?sort=` absent already means it.
    """
    return [(value, _sort_label(value, lang)) for value in SORTS if value]


def _clock(seconds: float, shape: str = "%H:%M:%S") -> str:
    """An activity's own epoch stamp as the design's table prints it; `0.0` is no time.

    `run.json` holds `started`/`ended` as epoch floats (`lib/run.py`), and `ended`
    is `0.0` while a run is going - which is why this answers `""` for a falsy
    stamp instead of `1970-01-01 00:00:00`, and why a caller can read "no end yet"
    off the same field it prints.
    """
    return time.strftime(shape, time.localtime(seconds)) if seconds else ""


# ---------------------------------------------------------------- the self-check
def _summaries(gui: Any, check: Filter, found: dict[str, Any]) -> list[tuple[str, str]]:
    """One line per key: the row count, or the one fact worth printing about it.

    Written as data and not as `print` calls so that the 27 keys are visibly the
    same 27 the contract names, in the contract's order - a key that quietly
    stopped being produced would be a missing line here and not a shorter table.

    Every list the console caps by `limit` says so and says what the cap is
    hiding (`53 cards on disk`, `99 pairs in the gap`), because a self-check whose
    numbers silently stopped at 25 would be the one report that hides a bug in the
    row cap.  The totals come from the same memoised reads (`_state`, `all_locals`,
    `todo`), so nothing here is read twice.
    """
    table, _records = gui._state()
    worker = found["worker"]
    newest_build = found["builds"][0]["build_id"][:16] if found["builds"] else "-"
    newest_pull = found["pulls"][0]["when"] if found["pulls"] else "-"
    pairs = len(table) * len(DEFAULT_TESTS)
    gaps = len(gui.todo(check))
    sources = ", ".join(sorted({one["source"] for one in found["ledger"]}))
    worker_said = (f'running={worker["running"]} pid={worker["pid"]} '
                   f'uptime={worker["uptime"] or "-"} cursor={worker["cursor"] or "-"} '
                   f'seen={worker["seen"]} pending={worker["pending"]}')
    live = sum(1 for one in found["activities"] if one["state"] == "running")
    deltas = sum(1 for one in found["picks"] if one["delta_down"])
    timelines = "; ".join(
        f'{one["test"]}: {one["runs"]} runs, {len(one["marks"])} marks, '
        f'last {one["last"] or "-"}, {one["regressions"]} regressions'
        for one in found["timelines"])
    series = "; ".join(
        f'{one["test"]}: {len(one["points"])} of {one["runs"]} runs over '
        f'{one["slots"]} positions, last '
        + (f'{one["points"][-1]["pct"]:g}%' if one["points"] else "-")
        for one in found["series"])
    counts = ", ".join(f"{label} {value}" for label, value, _ in found["counts"])
    queue_state = check.state or JOB_STATES[1]
    newest_run = (f'{found["runs"][0]["id"]} {found["runs"][0]["state"]}'
                  if found["runs"] else "-")
    builds_said = (f'{len(found["builds"])} rows of limit {check.limit}, newest '
                   f'{newest_build}; {len(table)} cards and {len(gui.all_locals())} '
                   "copies on disk")
    gap_said = (f'{len(found["gap"])} rows of limit {check.limit}, out of {pairs} '
                f'(build, test) pairs; {gaps} in the gap')
    queue_said = (f'{len(found["queue"])} rows of limit {check.limit}, '
                  f'state={queue_state} (an empty queue is a row count of 0, not a loss)')
    picks_said = (f'{len(found["picks"])} rows of limit {check.limit}, {deltas} with a '
                  "delta below")
    return [
        ("builds", builds_said),
        ("pulls", f'{len(found["pulls"])} rows, newest {newest_pull}'),
        ("gap", gap_said),
        ("ledger", f'{len(found["ledger"])} rows, sources {sources}'),
        ("worker", worker_said),
        ("queue", queue_said),
        ("runs", f'{len(found["runs"])} rows, newest {newest_run}'),
        ("picks", picks_said),
        ("bars", f'{len(found["bars"])} rows, first three '
                 + ", ".join(f'{one["ok"]}/{one["bad"]}/{one["warn"]}'
                             for one in found["bars"][:3])),
        ("timelines", timelines),
        ("series", series),
        ("drift", f'{len(found["drift"])} rows, '
                  + (", ".join(f'{one["added"]}/{one["removed"]}/{one["changed"]}'
                               for one in found["drift"]) or "-")),
        ("activities", f'{len(found["activities"])} rows, {live} running'),
        ("counts", f'{len(found["counts"])} rows: {counts}'),
        ("apis", f'{len(found["apis"])} rows: '
                 + ", ".join(f"{name}={base}" for name, base in found["apis"])),
        ("sorts", f'{len(found["sorts"])} rows: '
                  + ", ".join(f"{value} = {label}" for value, label in found["sorts"])),
        ("trees", f'{len(found["trees"])} names'),
        ("branches", f'{len(found["branches"])} names'),
        ("arches", f'{len(found["arches"])} names'),
        ("defconfigs", f'{len(found["defconfigs"])} names: '
                       + (", ".join(found["defconfigs"][:5]) or "-")),
        ("compilers", f'{len(found["compilers"])} names: '
                       + (", ".join(found["compilers"][:5]) or "-")),
        ("tests", ", ".join(found["tests"])),
        ("kinds", ", ".join(found["kinds"])),
        ("run_states", ", ".join(found["run_states"])),
        ("origins", ", ".join(found["origins"])),
        ("evidences", ", ".join(found["evidences"])),
        ("drawn", found["drawn"]),
        ("drawn_from", ", ".join(found["drawn_from"])),
    ]


def _self_check(gui: Any, lang: str = DEFAULT_LANG) -> int:
    """Print one line per key against the real workspace, and how long it took.

    `python3 -m lib.gui.design.data`, with the workspace `$KCI_WORK_DIR` names (or
    `var/`).  It reads and prints; it writes nothing, and the one reader it calls
    that *caches* (`Drift`, under `layout.configs()`) is named in this module's own
    docstring rather than hidden here.
    """
    started = time.monotonic()
    check = Filter(limit=gui.rows, origin="any", delta=DEFAULT_DELTA)
    # One request, the way `gui.server` begins one: `lib/api.py`'s memo is per
    # request, and without this the two API reads below would each open their own.
    api_mod.begin_request()
    found = rows(gui, check, lang)
    shown = _summaries(gui, check, found)
    print(f"lib/gui/design/data.py - {len(shown)} keys, workspace {layout.work()}")
    for name, said in shown:
        print(f"  {name:<11} {said}")
    print(f"  {'total':<11} {time.monotonic() - started:.2f}s")
    return 0


def main(argv: "list[str] | None" = None) -> int:
    """`python3 -m lib.gui.design.data [lang]`: the self-check above."""
    from ..app import Gui

    lang = (argv or [])[0] if argv else DEFAULT_LANG
    client = api_mod.Api(api_mod.Api.url(None), timeout=API_TIMEOUT)
    return _self_check(Gui(rows=ROWS, api=client), lang)


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
