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
    bars        _test_bars: one region per test, tally() each   (below, `lib/re.py`)
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
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from ... import api as api_mod
from ... import errors, layout, sink
from ... import re as re_mod
from ... import run as run_mod
from ...build import Build
from ...i18n import DEFAULT_LANG, t
from ...kbuild import Kbuild, Kbuilds
from ...tests import DEFAULT_TESTS, TESTS
from .. import values
from ..activities import WORKER_KIND
from ..forms import _names
from ..models import Filter
from ..pairs import _build_ref
from ..schema import (
    API_TIMEOUT,
    CHART_MODES,
    DEFAULT_DELTA,
    DEFAULT_TZ,
    EVIDENCE,
    JOB_STATES,
    KINDS,
    LIVE_KEPT,
    MODE_EACH,
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
    # Which tests this render draws a line per.  `?tests=` is the trend page's own
    # axis and the reason it can be a set at all (`models.Filter.tests`); every other
    # page asks nothing and lands on the catalogue's whole set, which is what these
    # two readers iterated before the key existed - so a page that has no such filter
    # is byte-for-byte the page it was.
    chosen = _names(check.tests) or DEFAULT_TESTS
    # Which question the chart below answers.  `mode` is `/trend`'s page state
    # (`schema.PAGE_STATE`) and not a `Filter` field, so it is read off the check the
    # way `/runs` reads `kind` - and a value the box does not offer falls back to the
    # accumulated reading rather than reaching the arithmetic, which is the one place a
    # stray string could turn a curve into an empty picture.
    mode = str(getattr(check, "mode", "") or "")
    mode = mode if mode in CHART_MODES else CHART_MODES[0]
    queue, queue_why = _queue(gui, check)
    return {
        "builds": _builds(gui, check, held, answer, lang),
        "pulls": _pulls(gui.pull_acts()),
        "gap": _gap(gui.job_rows(check)),
        "ledger": _ledger(records),
        "worker": _worker(gui, activities, processes, check.tz),
        # The reason rides beside the rows and not inside them: an empty queue and a
        # queue nobody could ask are two different sentences, and the reader answers
        # both with the same empty list.  Dropping it here is what let `/worker` print
        # "the API answered, and its queue holds nothing" over a read that never
        # arrived - the catalogue has had `empty.queue_no_answer` for exactly this the
        # whole time, and nothing could reach it.
        "queue": queue,
        "queue_why": queue_why,
        "return_path": _return_path(gui, queue),
        "runs": _runs(activities, processes, check.tz),
        "picks": _picks(ordered, edges, records, check),
        "bars": _test_bars(ordered, records, chosen),
        "timelines": _timelines(ordered, records, chosen),
        "series": _series(ordered, gui, records, chosen, mode),
        "mode": mode,
        "drift": _drift(edges),
        # How many `.config` files this render had to read over the API rather than find
        # on disk, counted where the reads happen (`api.note_fetch`, called by
        # `drift._config_text`).  Read here, **after** the edges above, because the
        # comparisons are the reads it counts - a page that pulled forty files and said
        # nothing is the one thing the freshness rule in this layer is against.
        "fetched": api_mod.fetches(),
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
    * **`source`** is `Local.origin()` - where the bytes came from, read off the newest
      act's URLs (`models.Local.origin` says why it is the act and not the card).  The
      value is one of `models.COPY_ORIGINS`; the words are the page's (`col.provenance`).
    * **`in_table`** is `build_row.in_table` - the local table's own answer to "is there
      a card for this build".
    * **`present`**/**`present_paths`** are `Local.present`, the artifacts whose file is
      on disk: the names for the cell, the paths for its `title=`.  A *different*
      question from `checks`, which is the three a test needs.

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
        copy = one["local"]
        # The artifacts whose file is on disk *right now*, as `{name: path}` - the
        # whole of `Local.present`, `config` included: this is the resource column's
        # answer and it asks what is here, not which of the three a test needs.
        #
        # `config` is then **widened to the shared cache** and the other three are not,
        # because that is the only one of the four with a second home: this build's own
        # directory (what a pull left) and `var/configs/<sha256(url)>.config` (what any
        # comparison that ever read this build's URL left, and what the drift analysis
        # reads - `Build.artifact_path` is the one function that knows both).  A config
        # in the cache is the same bytes from the same URL, so the column that says what
        # this build can be asked about has to count it; `Build.present()` alone answered
        # **0 of 1702** builds on the production stack while 319 configs sat in the cache
        # (`ls var/configs/*.config | wc -l`), i.e. the column drew `—` for every row of
        # a build the comparison page would happily diff (「先看本身有没有，再看配置偏移的
        # 缓存」).  `bytes_mib` above is deliberately *not* widened: `Local.size()` sums
        # the files in this build's own directory, and counting a shared 194 KB file once
        # per build would be a byte count that adds up to more than the disk holds.
        present = {name: path for name, path in (copy.present if copy else {}).items()
                   if path}
        if kbuild is not None and (path := Build(kbuild).artifact_path("config")):
            present["config"] = path
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
            # Where the bytes came from (`Local.origin`), one of `models.COPY_ORIGINS` or
            # `""` for a copy no act describes.  This is a *value* and not a word: the
            # three words are the page's, and `""` is the dash it draws for "nothing
            # recorded" - which is not a fourth origin and must not be spelled as one.
            "source": copy.origin() if copy is not None else "",
            # Is this build in the local table?  `build_row.in_table` is that answer
            # already (`Local.card is not None`) - the same fact the card view is a
            # view *of*, and not a second reading of it.
            "in_table": bool(one["in_table"]),
            # What is on disk, by the names the page uses for artifacts everywhere
            # (`Local.present`, one `os.path.isfile` each, `config` included), and
            # those files' paths for the cell's `title=`.  The three ticks beside this
            # column ask the same question about the three a test needs; this answers
            # it about everything, which is why the two are not one column.
            "present": sorted(present),
            "present_paths": ", ".join(present[name] for name in sorted(present)),
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
            processes: dict[str, Any], tz: str = DEFAULT_TZ) -> dict[str, Any]:
    """What the poll loop is doing: the live process, and the state file it writes.

    Two readers, and neither is interpreted here.  `Gui.worker_state()` is the JSON
    `lib/poller.py` wrote, read as the document it is (`STATE_FIELDS` is
    `timestamp`/`seen`/`pending`/`refused`, and the cursor is the `timestamp` - the
    poller's own name for it, not a second timestamp this page keeps).  The process
    side is `Gui.run_rows()`'s own worker row, which is where `running`, `pid`,
    `argv` and the age come from: `uptime` is `Run.age()`'s answer and not a
    subtraction here.

    Four counts and not three, because `seen` and `refused` answer different
    questions and the operator asked for the second one by name.  `seen` is how many
    node ids the loop has dealt with; `refused` is how many of those it put down
    without running, and a worker older than that field answers `0` for it while its
    `seen` still holds the nodes - which is why the page prints the two beside each
    other instead of subtracting one from the other.

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
    refused = state.get("refused") or {}
    return {
        "running": bool(live),
        "run_id": newest["id"] if newest is not None else "",
        "pid": process.pid if process is not None else 0,
        "started": values._clock(newest["started"], tz, "%Y-%m-%dT%H:%M:%S")
                   if newest is not None else "",
        "uptime": newest["age"] if newest is not None else "",
        "argv": " ".join(newest["argv"]) if newest is not None else "",
        "state_file": layout.worker_state(),
        "cursor": str(state.get("timestamp") or ""),
        "seen": len(stored), "pending": len(pending), "refused": len(refused),
    }


def fate_of(one: dict[str, Any]) -> str:
    """What this machine did with a queue node, as one of `schema.LOCAL_FATES`.

    Four answers and they are ordered by how much is *known*, not by how good the
    news is - `held` is the one that is certain (only `_remember_pending` writes it,
    and it runs after the job's ledger sink has already been written), `refused` is
    the poller's own sentence, and `ran` is what is left when a node is in `seen`
    with nothing recorded against it.  That last one is a **default and not a
    finding**: nothing on this disk keys a run to a node id, so "dealt with, no
    reason to think otherwise" is the strongest true statement.  A worker older than
    `poller.refuse` writes no refusals at all, and its nodes land here.

    Read in one place because two readers need the same word - the table's cell and
    the `local` filter that selects it - and a filter that disagreed with the cell
    it selects would be a page arguing with itself.
    """
    if one.get("held"):
        return "held"
    if one.get("refused"):
        return "refused"
    return "ran" if one.get("claimed") else "never"


def _queue(gui: Any, check: Filter) -> tuple[list[dict[str, Any]], str]:
    """The API's job queue, newest first, and why it is empty - the rows `Gui.job_node_rows` answers.

    Read as wide as `/worker` reads it (`QUEUE_ROWS`, because the page's own
    platform and runtime boxes are built out of the same answer) and printed as
    wide as this filter's `limit`, exactly as `worker.py` does: one read of
    the largest collection in the API for one question.

    **Newest first, and it was not.**  `Kjobs.getjob` reads the API oldest-first on
    purpose (`lib/kjob.py` says why: a worker taking the *head* of a queue wants the
    end that has been waiting longest), so a page that printed that order put the
    node an operator is watching for at the bottom of fifty.  The sort is here and
    not in the reader, because the worker's claim loop needs the other order and
    this is the one caller that does not.

    `check.local` is applied here too, after the read and before the cap: it is a
    condition on the *rows*, but not one the API can be asked (`seen`/`pending`/
    `refused` are files on this disk), so it cannot ride `getjob`'s filters and it
    must be applied before `limit` or a page of fifty would show however many of
    them happened to be local.

    The state is `check.state or "available"`, which is the shipped route's own
    default (`schema.PAGE_STATE` for `/worker`): a worker page is about what a worker
    can *claim*, and a table of 200 finished nodes beside a "nothing to claim"
    badge is two true sentences that mean nothing together.  `Filter.state` also
    spells the *kbuild* state axis, and the two vocabularies overlap where they
    must (`done`, `running`); a `/worker` URL says `?state=available`, which
    `_named` carries through untouched, so the page key and this one are one
    string.
    """
    state = check.state or JOB_STATES[1]
    wanted = str(getattr(check, "local", "") or "any")
    found, why = gui.job_node_rows(check, state, QUEUE_ROWS)
    rows = [{
        "node_id": one["node_id"], "name": one["name"], "state": one["state"],
        # `result` is `""` on a node that has not run yet (`lib/kjob.py` reads the
        # API's own field), and the design's shape says `None`: both are falsy, and
        # `None` is the one a page can compare against without a second spelling of
        # "no answer".
        "result": one["result"] or None, "platform": one["platform"],
        "runtime": one["runtime"], "created": one["created"],
        "claimed": one["claimed"], "definition": one["definition"],
        "held": one["held"], "refused": one["refused"], "build_id": one["build_id"],
        # The pipeline route, for the `route` column.  Named here for the reason the
        # `definition_url` note below gives - this projection *is* a whitelist, and a
        # key left out of it renders as the design's dash on every row rather than
        # failing: the column drew `—` for every node until this line existed.
        "path": one["path"],
        # The URL itself, and not just the `definition` boolean beside it.  This
        # projection is a whitelist - every key a page reads has to be named here -
        # and `_return_path` reads this one off the rows it is handed.  Leaving it out
        # was silent: the panel kept rendering, and rendered its *empty* state, which
        # is a sentence about the queue rather than about the missing key.  A field
        # that only the empty state depends on has no way to fail loudly.
        "definition_url": one["definition_url"],
    } for one in found]
    if wanted != "any":
        rows = [one for one in rows if fate_of(one) == wanted]
    rows.sort(key=lambda one: (str(one["created"]), str(one["node_id"])), reverse=True)
    return rows[:check.limit], why


# ------------------------------------------------------------------- the runs
def _return_path(gui: Any, queue: list[dict[str, Any]]) -> dict[str, Any]:
    """Where a finished job's report goes, what signs it, and what is still waiting.

    The operator lost an afternoon to this exact question - a job ran, the ledger had
    the row, and the API said the node was never reported - and every fact needed to
    answer it was on the disk or one read away, in four places: the definition artifact
    (the `callback.url` the report is POSTed to), `sink.callback_token` (the token,
    whose *source* is the part that can be wrong), the state file's `pending` (reports
    written and refused), and the definition's own `token_name`.

    **One definition is read, not one per row.**  Every node in a queue was dispatched
    by the same lab and carries the same callback block, so the answer is one answer;
    fetching it per row would be thirty HTTP reads for one sentence.  The first row that
    names a definition is the one read, and the `definition` key in the answer is which
    row it came from, so a reader who wants to check that claim can.

    The token's **value never reaches this dict** - `sink.token_source()` answers which
    of the two places a token would be read from, and a page that cannot leak a secret
    is worth more than a page that shows one.  The definition's `token_name` is not read
    at all: nothing in this tree ever used it, what is really sent is
    `Authorization: Token <the token>`, and the row that printed it was the row that sent
    the operator looking for a token named in a file that has nothing to do with the
    header.

    **One destination, resolved here.**  `destination` is `sink.delivery_url`'s own
    answer for this definition - the same call the worker's delivery and the re-post make
    - so the panel's one row about where reports go cannot disagree with what the worker
    does.  It is resolved *in this layer* rather than left to each of the three readers
    to work out, and that is the opposite of what this function used to do: the value was
    withheld on the argument that a resolved URL would be a second owner for "which one is
    in force", which is true only while a page draws the definition's URL and the
    override as two separate answers.  The panel draws one, so there is one owner, and it
    is `sink.delivery_url` - by way of this reader, which does not decide anything itself.
    `override` rides beside it because the box is prefilled with what would be *written*,
    and empty (or `sink.OFF`) is not the same thing as the destination.
    """
    url = next((str(one.get("definition_url") or "") for one in queue
                if one.get("definition_url")), "")
    callback = why = ""
    if url:
        try:
            definition = gui.job_definition(url)
        except errors.KciError as exc:
            why = str(exc)
        else:
            block = definition.get("callback") if isinstance(definition, dict) else None
            if isinstance(block, dict):
                callback = str(block.get("url") or "")
    return {"definition": url, "callback": callback,
            "override": sink.callback_override(),
            "destination": sink.delivery_url(callback),
            "why": why, "token_source": sink.token_source(),
            "pending": _pending(gui.worker_state())}


def _pending(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The reports written and not delivered, as rows: the node, where it was going, and what it says.

    `pending` is the state file's third list and the only one whose contents are a
    *record* rather than a fact about the loop, so it is read here rather than counted:
    a bare count on the panel is what left the operator unable to tell "nothing is
    waiting" from "six things are waiting and I cannot see them".  The reason a
    delivery failed is deliberately not among the keys - it is not stored (the report
    is what has to survive the process, not the error), and inventing one from the
    callback's URL would be this layer guessing at an HTTP answer it never saw.  The
    run's own log has it.
    """
    rows = []
    for node_id, entry in sorted((state.get("pending") or {}).items()):
        entry = entry if isinstance(entry, dict) else {}
        record = entry.get("record") if isinstance(entry.get("record"), dict) else {}
        rows.append({"node_id": str(node_id),
                     # The URL the *re-post* will use and not the one in the file: the
                     # stored one is the definition's (`Poller._remember_pending` says
                     # why), and a column headed "callback" over a row that is about to
                     # be posted somewhere else is the table disagreeing with the
                     # worker.  Same resolution the worker itself calls.
                     "callback": sink.delivery_url(str(entry.get("callback") or "")),
                     "verdict": str(record.get("verdict") or ""),
                     "detail": str(record.get("detail") or "")})
    return rows


def _runs(activities: list[dict[str, Any]], processes: dict[str, Any],
          tz: str = DEFAULT_TZ) -> list[dict[str, Any]]:
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
            "started": values._clock(one["started"], tz),
            "ended": values._clock(one["ended"], tz) or None,
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
        # Two different questions about one artifact, and this page has to ask both.
        # `config_url` is where the bytes *would* come from - the card's own artifact URL,
        # which is the `title=` a reader who wants the raw file follows.  `config` is
        # whether there is anything to read **here and now**, which is the tick, and it is
        # `Build.artifact_path` and not `present()`: a config this build never pulled is
        # still readable if a comparison of it ever filled the shared cache
        # (`var/configs/<sha256(url)>.config`), and that is the same bytes from the same
        # URL - so a `—` there was the page saying "no config" about a build `/analysis`
        # would happily compare (「先看本身有没有，再看配置偏移的缓存」).  The two are not
        # interchangeable in either direction: `config_url` is never empty (it falls back
        # to the storage service), so driving the tick from it would tick every row.
        config_url = kbuild.artifact("_config") if kbuild is not None else ""
        config = Build(kbuild).artifact_path("config") if kbuild is not None else ""
        rows.append({
            "build_id": build_id, "kbuild": kbuild,
            "created": str(kbuild.created or "") if kbuild is not None else "",
            "tree": str(kbuild.tree or "") if kbuild is not None else "",
            "branch": str(kbuild.branch or "") if kbuild is not None else "",
            "series": _series_of(revision.get("describe")),
            "verdict": found.items[-1].verdict if found.items else "",
            "config": bool(config), "config_url": config_url,
            "records": len(found),
            "held": bool(local is not None and local.present),
            "ref": _build_ref(kbuild),
            "line": _build_line(kbuild, revision, build_id),
            "marks": _build_marks(config, config_url, local, len(found), lang),
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


def _build_marks(config: str, config_url: str, local: Any, records: int,
                 lang: str = DEFAULT_LANG) -> str:
    """Three marks per row: can this build be compared, is there a copy here, has it run.

    They are the facts that decide the questions a reader is about to ask, and two of
    them are what makes a doomed pair visible **before** it is picked: `config -` is a
    build no comparison can use (`06-analysis.md` §A7), and the artifact URL is in the
    `title=` for the reader who wants the raw file.

    `config` and `config_url` are the two halves of that first mark and they answer two
    questions: the first is whether the bytes are readable **here** (this build's own
    copy, or the shared config cache it shares with every comparison - `_build_rows`,
    which computes both halves of this mark, says why both count), and the second is
    where a reader would go for the original.
    The URL is therefore the `title=` even on a row whose mark is a dash: "not on this
    disk" and "not anywhere" are different facts, and the URL is how a reader tells them
    apart.  It is never the *tick*, because `Build.config_url` falls back to the storage
    service and is non-empty for every build.
    """
    def mark(word: str, yes: bool, title: str = "") -> str:
        attr = f' title="{html.escape(title)}"' if title else ""
        return (f'<span class="{"yes" if yes else "no"}"{attr}>'
                f'{html.escape(word)} {"&#10003;" if yes else "&mdash;"}</span>')

    held = bool(local is not None and local.present)
    return ('<span class="marks">'
            + mark(t(lang, "word.config"), bool(config), config_url) + " "
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


def _test_bars(ordered: list[dict[str, Any]], records: Any,
               chosen) -> list[dict[str, Any]]:
    """One region per test, one bar per build inside it: what answered, and how.

    The panel reads this as a **region per test** (`chosen`, `DEFAULT_TESTS` order or the
    set the reader picked) and, inside a region, one line per build of the page's order -
    the region's own three totals in its heading, that build's own three numbers on its
    line.  Two scopes of one arithmetic and not two readers: the totals are the sum of
    the lines below them.

    The three numbers are **this build's own run for this test** and not a running total -
    the distinction the design's panel exists to draw, and the reason a region may hold a
    row that is all zeros.

    **They are the run's own case counts where it has them, and its verdict where it does
    not** (`_tally`).  They used to be the ledger's verdict words tallied, which made every
    line in every region read `1 0 0` - one record, passed - while the record beside the
    page was saying `10 selftests: 10 pass, 0 fail, 0 skip`.  The operator read the panel
    as a lie about the run (「我要显示的是更详细的数值，比如 8 2 0 或者 10 0 0 或者 12 2 0
    等等，而不是什么 1 0 0」) and it was one: *one* there was the number of records, not
    the number of cases.  A region's heading is still the sum of the lines under it, so
    the two scopes stay one arithmetic - but the unit is now the test's own, which is what
    makes a heading a fact about the window rather than a count of rows drawn.
    """
    out = []
    for test in chosen:
        scoped = records.for_test(test)
        bars = []
        for one in ordered:
            record = scoped.for_build(str(one["build_id"])).last(test)
            bars.append({"build_id": str(one["build_id"]), **_tally(record)})
        out.append({"test": test, "bars": bars,
                    **{name: sum(bar[name] for bar in bars)
                       for name in ("ok", "bad", "warn")}})
    return out


def _tally(record) -> dict[str, int]:
    """One record as the design's three numbers: `ok`, `bad`, and what did not answer.

    **The record's own case counts when it has them.**  `results` is the TAP summary
    (`lib/judge.py`: `total`, `failed`, `skipped`), so a kselftest run of twelve cases
    with one failure and three skips is `8 1 3` - the three numbers the record's own
    `detail` line prints, which is the whole point of the panel and the reason it cannot
    be a tally of records.

    **Its verdict when it has none.**  `boot` reports no case counts (`results` is `{}`),
    and one boot that answered is honestly `1 0 0`: the number is the run, because the
    run is the only thing there is to count.  Saying so is `page.analysis.bars_sub`'s job
    and not this function's - a reader who sees `1 0 0` beside a `10 0 0` has to be told
    the unit is the test's own.

    **The three words are still the triad they were.**  `ok` is how many cases answered
    and passed, `bad` how many failed, and `warn` is **what did not answer** - the record's
    own skips where it counts cases, and its verdict where it does not.  `incomplete` and
    `error` are two verdicts of the ledger (`lib/errors.py`) and one thing to a reader: the
    run produced no verdict *about the kernel*.  A verdict this function has never been
    taught falls in there too, which is the honest place for it - an unknown word is not a
    pass.

    A pair with no record is all zeros, which `ui.test_bars` draws as the design's dash:
    zero records and zero passes are different facts, and only one of them is a zero.
    """
    if record is None:
        return {"ok": 0, "bad": 0, "warn": 0}
    results = getattr(record, "results", None) or {}
    total = int(results.get("total") or 0)
    if total > 0:
        failed = max(0, int(results.get("failed") or 0))
        skipped = max(0, int(results.get("skipped") or 0))
        return {"ok": max(0, total - failed - skipped), "bad": failed, "warn": skipped}
    verdict = str(getattr(record, "verdict", "") or "")
    if verdict == errors.VERDICT_PASS:
        return {"ok": 1, "bad": 0, "warn": 0}
    if verdict == errors.VERDICT_FAIL:
        return {"ok": 0, "bad": 1, "warn": 0}
    return {"ok": 0, "bad": 0, "warn": 1}


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


def _timelines(rows: list[dict[str, Any]], records: Any,
               tests: tuple[str, ...] = DEFAULT_TESTS) -> list[dict[str, Any]]:
    """One line per test: how many records, the newest verdict, and the run of them.

    **Every one of the four answers is about `rows`** - the page's own order, filtered,
    sorted and capped the way the reader asked for it.  It used to be two answers about
    that window and three about the whole ledger: `marks` came from the newest
    `check.limit` builds in *date* order while `runs`, `last` and `regressions` were
    `Records.series(test)`/`values._last_verdict`/`re.transitions()` over every record the
    ledger holds.  A reader who narrowed the page to one tree, or reversed the order, got
    a sparkline of one population and three numbers of another - and the numbers were the
    ones that looked authoritative, because they are integers in a column.

    So the three counts and the marks all read one `Records` - `for_builds(rows)` - and
    the axis is `rows` itself, in `rows`' order: cells, counts and the curve below them are
    one answer about one window, which is what the panel's sub-line now says.  Narrowing
    the ledger first is also the cheaper reader, not just the honest one: `_wave_slots`
    looks each build up by id, and every lookup it makes is inside this subset anyway.

    `None` is a position and not a run: the design draws it as an empty square
    (`no record`), which is how a test that *stopped* is visible instead of a line
    that pretends it never ran.

    `tests` is the set this axis draws one row per - `DEFAULT_TESTS` for every page
    that asks for nothing, and the reader's own combination on the page that has a
    box for it (`/trend`).  It is a *subset* of the catalogue and never a fourth
    name: `lib/tests.py:TESTS` is what the filter accepts, so a value outside it
    never reaches here (`forms._tests_many`).

    Two lists of pairs ride along, and they are two questions about one window:
    `transitions` is the regressions **the count is `len()` of**, and `comparisons` is
    every adjacent pair of this test's records in the window whether or not it counted.
    Both are read off the same `series` and the same `pairs`, so a row marked as a
    regression in one is a row of the other - the panel draws the second and marks it
    with the first, which is what makes a four-row "where did it break" and a sixty-row
    "what did I compare" one answer instead of two.
    """
    window = records.for_builds(str(one["build_id"]) for one in rows)
    found = []
    for test in tests:
        marks = _wave_slots(rows, window, test)
        # This test's records **in the window**, oldest first - the order
        # `re.transitions` reads them in, and the order the comparisons below are taken
        # between.  Read once: `runs` is its length and both lists below walk it.
        series = window.series(test)
        # The transitions **themselves**, not only their number: `regressions` is the
        # count a reader scans for, and the panel prints these rows under the table so
        # the count can be checked against the pairs it was counted from - which build
        # passed, which one then failed, and when each was recorded.  It is the same
        # answer the config-drift sections give for two builds' options, and it is why
        # the count above is `len(pairs)` and not a second reading of the ledger.
        pairs = re_mod.transitions(window, test)
        # Which comparisons the ledger called a regression, as the pair of build ids
        # `transitions` returned them under.  A comparison is a regression **when it is
        # one of these**, and not when it happens to go pass -> fail: consecutive
        # failures are one regression (`re.transitions` says why), so the run of fails
        # after the first is compared and is not counted, and reading the verdicts alone
        # would report three regressions where the column says one.
        regressed = {_pair_key(failed, passed) for failed, passed in pairs}
        found.append({
            "test": test, "runs": len(series),
            "last": _last_verdict(window, test),
            "regressions": len(pairs),
            "marks": [one["verdict"] or None for one in marks],
            "transitions": [{"test": test,
                             "passed": str(getattr(passed, "build_id", "") or ""),
                             "failed": str(getattr(failed, "build_id", "") or ""),
                             "passed_at": str(getattr(passed, "timestamp", "") or ""),
                             "failed_at": str(getattr(failed, "timestamp", "") or "")}
                            for failed, passed in pairs],
            # **Every comparison this window made**, adjacent record against adjacent
            # record, and not only the ones that counted.  The `transitions` list above
            # answers "where did it break"; this one answers "what did I compare", which
            # is the other half of the same question and the one the operator asked for
            # when the panel showed four rows and the ledger held sixty
            # (「我是想叫你列出所有比较的那个东西，一个类似分析的列表，看看我比较的是什么」).
            # A window with 21 `kselftest-riscv` records makes 20 comparisons and 3 of
            # them are regressions, and the ratio is the thing a four-row panel hid.
            "comparisons": [{"test": test,
                             "older": str(getattr(older, "build_id", "") or ""),
                             "newer": str(getattr(newer, "build_id", "") or ""),
                             "older_at": str(getattr(older, "timestamp", "") or ""),
                             "newer_at": str(getattr(newer, "timestamp", "") or ""),
                             "older_verdict": str(getattr(older, "verdict", "") or ""),
                             "newer_verdict": str(getattr(newer, "verdict", "") or ""),
                             "regression": _pair_key(newer, older) in regressed}
                            for older, newer in pairwise(series)],
        })
    return found


def _pair_key(failed, passed) -> tuple[str, str]:
    """A `(failed, passed)` transition's two build ids, as the key the comparisons match on.

    `re.transitions` hands back `(failed, passed)` - newest first - and a comparison is
    `(older, newer)`, so the two are the same pair of records read in opposite directions
    and the key is spelled once, here, rather than reversed at each of the two call sites.
    A build id is unique within one test's series (`var/results/<build>/<test>.json` is one
    file per pair), so the two ids identify the pair.
    """
    return (str(getattr(failed, "build_id", "") or ""),
            str(getattr(passed, "build_id", "") or ""))


def _series(ordered: list[dict[str, Any]], gui: Any, records: Any,
            tests: tuple[str, ...] = DEFAULT_TESTS,
            mode: str = "") -> list[dict[str, Any]]:
    """One line per test across the positions of the page's order: the pass rate.

    The design's chart panel (`ui.line_chart`, `ui.legend`) draws one polyline per
    test with `x` on **the order** and `y` on a percentage, so this key is that
    pair of answers as rows: `slots` is how many positions the axis has, `ends` the
    two builds under its ends, `runs` the number the legend prints beside each
    name, and `points` the `(position, percent)` pairs the line is drawn through.
    Every row carries the axis as well as its own points, so a row is complete on
    its own (`slots` and `ends` are the same in all of them - there is one axis).

    **What a point means is `mode`'s, and `_points` is where that is decided.**  The
    two readings are the accumulated pass rate (the default, and every page but
    `/trend` asks for nothing) and each build's own numbers; `_points` documents both,
    including why the accumulated one now carries a value across a position the ledger
    has nothing for instead of leaving the line broken there.

    What this key owes the renderer is unchanged: the points are `(position, percent)`
    pairs on **the order's** positions, and a position this test has no run for is a
    position with no *run* - whether it also draws a point is `mode`'s business, and
    `carried` on the point says which kind of point it is.

    `kept` is the legend's numerator and **not** `len(points)`.  The two are the same
    number on the per-build reading and are not on the accumulated one, where a position
    inside the run draws a point it has no record for (`_points` carries the value): the
    first draft printed the drawn points over the total, and the local stack rendered
    `31 / 26 runs` - more runs on the legend than the ledger has.  `kept` counts the
    points that *are* records, which is what the legend is a statement about, and it is
    computed here rather than at the renderer because `carried` is this layer's word.

    The points come from `Gui.trend(test, scope)`, which owns "this test's records
    with their regressions" (a point carries the record's `verdict` and whether the
    ledger called it a regression); the run count comes from `Records.series(test)`,
    the reader `trend` is built on and the number `timelines.runs` already prints.
    `Gui.trend` is asked for the whole series, so a record for a build this page
    does not list is dropped by the mapping below and never by a cap here; where a
    build has several records for one test the newest speaks, which is the rule
    `_wave_slots` and `timelines.marks` use for the same axis.

    `tests` is the set this draws a line per, exactly as `_timelines` takes it: the
    catalogue's whole set unless the page has a box for choosing (`/trend`), so the
    legend names the tests that were asked for and the colour slots follow the list
    (`_chart_series` reserves a slot per position in it).
    """
    slots = len(ordered)
    ends = ((str(ordered[0]["build_id"]), str(ordered[-1]["build_id"]))
            if ordered else ("", ""))
    found = []
    for test in tests:
        history = records.series(test)
        newest: dict[str, dict[str, Any]] = {}
        # `trend`'s points are the series oldest first, so the last write per build
        # is that build's newest record - no second lookup, no second parse.
        for point in gui.trend(test, max(1, len(history)))["points"]:
            newest[str(point["build_id"])] = point
        points = _points(ordered, newest, mode)
        found.append({"test": test, "runs": len(history), "slots": slots,
                      "ends": ends, "mode": mode,
                      "kept": sum(1 for one in points if not one["carried"]),
                      "points": points})
    return found


def _points(ordered: list[dict[str, Any]], newest: dict, mode: str) -> list[dict[str, Any]]:
    """One test's line as the `(position, percent)` pairs the chart draws.

    One axis, two questions, and `mode` picks which - the switch the operator asked for
    (「切换一种模式就是改成能显示具体每一项的通过数值那种」).  `schema.CHART_MODES` holds
    the vocabulary and `data.rows` has already refused anything outside it, so this
    function only has to answer the two.

    **`MODE_CUMULATIVE` - the accumulated pass rate.**  At position *i* it is the share
    of this test's runs, up to and including *i*, that came back `pass`.  Two properties
    of it are worth spelling out, because both have been read off the picture wrongly:

    * **It accumulates from the left end of the order, not from the oldest build.**  The
      axis is the reader's own order (`sort`), so on a page sorted newest-first the first
      position is the newest build and the curve runs backwards through time.  That is
      not a bug and it cannot be fixed here - the axis is the order, and the order is the
      question - so the panel's caption says which end the accumulation starts at
      (`page.analysis.chart_cap`).
    * **A position with no record carries the previous value.**  It used to be left out,
      and the picture was a line broken into as many pieces as the window had gaps: the
      operator read four or five separate measurements where there is one curve
      (「如果是累计为什么还会有断层存在呢」).  Carrying is not an invention - if nothing
      ran at a position then the accumulated rate *is* the previous one - and the point
      is marked `carried` so a tooltip can say "no record here, the value is the previous
      one's" rather than pretending a run happened.  Nothing is carried **before the
      first record** or **after the last**: a rate with no runs behind it is not a rate,
      and a flat line to the right edge would claim a test was still being measured.

    **`MODE_EACH` - each build's own numbers.**  Every point is that one run and never a
    running total, so the line moves at every build and a position with no record is a
    gap, exactly as the timeline's empty square above says.  The percentage is
    `_own_pct`, which prefers the record's own case counts.
    """
    points: list[dict[str, Any]] = []
    runs = 0
    passed = 0
    for at, one in enumerate(ordered):
        point = newest.get(str(one["build_id"]))
        if point is None:
            # No record here.  In the accumulating reading the value stands still, and
            # only once it has a value to stand still at - a carried point before the
            # first run would be a number with nothing behind it.
            if mode == MODE_EACH or not runs:
                continue
            points.append({"at": at, "build_id": "", "pct": points[-1]["pct"],
                           "verdict": "", "regression": False, "carried": True})
            continue
        runs += 1
        if mode == MODE_EACH:
            pct = _own_pct(point)
        else:
            if point["verdict"] == errors.VERDICT_PASS:
                passed += 1
            pct = round(100.0 * passed / runs, 1)
        points.append({"at": at, "build_id": str(one["build_id"]), "pct": pct,
                       "verdict": point["verdict"],
                       "regression": bool(point["regression"]), "carried": False})
    return points


def _own_pct(point: Mapping[str, Any]) -> float:
    """One record's own pass rate, as a percentage.

    **The record's own case counts when it has them.**  `results` is the TAP summary
    (`lib/judge.py`: `{"total", "failed", "skipped"}`), so a kselftest record that ran
    twelve cases and failed one is `91.7` and not a flat `100` - which is the number the
    operator was reading off the detail line and expecting to see on the chart
    (「理论应该 100 和 80」).  A percentage is the only way one axis can carry both a
    twelve-case suite and a boot.

    **Its verdict when it has none.**  `boot` reports no TAP counts at all (`results` is
    `{}`), and "did this build boot" is still a question with an answer: 100 for a pass
    and 0 for everything else.  An undefined would leave `boot` without a line, which is
    the one test whose line a reader is surest of.

    The pass count is derived and clamped: `total - failed - skipped` is what the record
    means by "passed" (`judge.tap_summary` counts the three and the detail line prints
    them), and a record whose three numbers disagree cannot make the curve go below zero.
    """
    results = point.get("results") or {}
    total = int(results.get("total") or 0)
    if total > 0:
        failed = max(0, int(results.get("failed") or 0))
        skipped = max(0, int(results.get("skipped") or 0))
        return round(100.0 * max(0, total - failed - skipped) / total, 1)
    return 100.0 if point.get("verdict") == errors.VERDICT_PASS else 0.0


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
        ("bars", f'{len(found["bars"])} regions, '
                 + (", ".join(f'{one["test"]}: {one["ok"]}/{one["bad"]}/{one["warn"]} '
                              f'over {len(one["bars"])} builds'
                              for one in found["bars"]) or "-")),
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
