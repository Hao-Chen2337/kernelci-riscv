# Code notes: local job table (group C)

Long-form explanation that was cut out of the comments and docstrings of the four
files below. The code now carries only the short version; this file keeps the
reasoning, the history behind a few gotchas, and the contracts that used to be
spelled out inline.

## scripts/kcilib/table/localrun.py

Views and execution: how the rows of the local job table become a real run, and
how a run is looked up again afterwards.

The layer joins three things:

    BuildIndex (which builds exist)   ledger (what has been run)   API (upstream state)
                             \              |              /
                              \             v             /
                               todo()  --->  run_job()

`ran_tests()` and `todo()` are pure reads: they answer "how much is left to run"
without touching the network, so the table stays usable while the local API
stack is down.

`run_job()` is deliberately a thin shell. It only wraps
`kcilib.run.jobrun.run_node` - which already owns download, rootfs bake,
execution, judging, archiving and recording - and reshapes the return value into
a RunOutcome. It re-implements none of those steps, because 19 guard checks pin
that behaviour down; duplicating any of them here would put the table outside
the guards' reach.

A definition without a callback URL still runs, still archives, still records -
nobody is notified. That is exactly the "make your own job locally" shape: it
touches no API and does not depend on any upstream configuration being merged.

`ran_tests()`: "has it run" has one source, the ledger. The API records *node
state*; the ledger records what *this machine actually ran*. Both are needed, but
only the ledger can answer the question offline.

`todo()`: pure subtraction of the ledger from the index. It returns three
things:

* `specs` - the pending list, each entry still carrying its BuildRef;
* `skipped` - `[(build_id, test, reason)]`: builds that are missing an artifact
  are dropped here rather than silently;
* `builds_checked` - how many builds were inspected, so a "0 pending" answer can
  be told apart from "the index is empty or the filter selected nothing".

`outcome_from()`: the verdict is derived from the callback body
(`callback.verdict_from_body`) instead of re-parsing the console log. The ledger
and the upstream callback must end up with the same conclusion, and re-parsing
would be a second, independent judgement.

`run_job()` and the report triple: `run_node` hands back
`(callback_url, token, body)`, and that triple is the *only* possible source of a
callback. It used to be dropped here (only the URL was kept), which is why
`./run.sh run --callback-url URL` never actually POSTed anything: the help text
and the jobspec documentation were describing a report-back that did not exist.
The sink layer (`kcilib/sink.py`) needs something it can send, so the triple now
travels in `outcome["report"]` - and is `None` when the definition has no
callback section.

The `source="table"` argument: the ledger's source field says which writer filed
the row. Inside jobrun it used to be hardcoded to `"worker"`, so every run driven
by the local table was misfiled as a worker run.

`_record_path()`: the ledger path a run landed in. The path is recomputed from the
artifact URLs in the definition, using the same `result_path` the executor writes
through - so it is a *prediction*, not a receipt. A failed ledger write is only a
warning inside jobrun and does not stop the callback, so the prediction would
otherwise survive and the tool would report a file that does not exist.
`os.path.exists` turns the prediction into a fact.

## scripts/kcilib/table/jobspec.py

From one build to the tests to run: a row of the table, and the definition handed
to the execution layer.

Two objects, not to be confused:

* **JobSpec** is a *row of the table* - `(build_id, test, timeout_s)`. It can be
  stored, printed, and compared against "has this run". It deliberately does
  **not** carry a callback URL, because that is only known at run time.
* **JobDefinition** is the *complete definition given to the execution layer* -
  artifacts / tests / environment / callback. Its field names are exactly what the
  upstream `pull_labs.jinja2` template renders, so
  `kcilib.run.jobrun.run_node` cannot tell - and does not need to tell - whether
  the definition came from the official API or was assembled locally: one function
  consumes both sources.

The consequence is that "I make a job locally and run it" and "I claim an upstream
job and run it" are *the same thing at the execution layer*. The only difference
is whether `job_definition()` is given a `callback_url`:

* callback URL given -> the callback section is written into the definition and
  results are reported back;
* no callback URL -> no callback section, so only the ledger is written.

`DEFAULT_TESTS` holds the three tests this configuration claims, matching the
three `runtime=pull-labs-riscv` entries of
`config/scheduler-pull-labs.yaml` one for one (that file holds 44 entries in
total; only three of them match).

Timeout defaults: `boot` only has to start the kernel, the two kselftest
collections are long runs. An unknown test falls back to 1800 s.

`JobSpec` is intentionally three fields: it is *intent*, not *instructions*. One
more field and it stops being a checklist you can hold in your hand. `build` is
held aside rather than folded into `as_row()` so a row can be printed with just
the ids.

`jobs_from_build()`: a pure function - no network, no disk, no test execution.
`build` may be a BuildRef or a **full node dict**, and accepting the latter is
deliberate: a locally invented node has no queryable id, and taking a node as
input treats official and home-made nodes alike. A build that is entirely
unusable (no kernel at all) yields empty `specs` and explains itself in
`skipped`. The reasons matter: a silent skip is the usual origin of "why did this
not run?".

`test_of()`: one place owns "what is this job called". The ledger files rows under
that name, and the run's own naming has to agree with the callback it produces.

`job_definition()`: `callback_url` is the *sink switch*. It lives here rather
than on JobSpec because at listing time nobody knows where results should go (a
local stack? production?). The produced shape is isomorphic to the upstream
template render, which is what makes both sources interchangeable for
`run_node`; a JobSpec that carries no build is a programming error and raises.

## scripts/kcilib/table/buildindex.py

A local index that answers one question: which builds can be run.

Why an index and not a database: everything about a build already lives in the
KernelCI API, so keeping a full local copy of the nodes would be a second truth
that eventually disagrees with the first. Only the columns needed to decide "can
this run" are stored - `build_id / tree / branch / commit / describe / created /
node_id / artifacts` - plus exactly one own field, `source`, saying whether the
row was pulled from upstream or invented locally.

The key is `build_id`, not the node id: node ids are allocated per instance, so
the local and production databases hand out unrelated ids for the same build (see
`kcilib/table/buildref.py`). `build_id` is parsed out of the artifact URLs and is
therefore stable across instances.

The database defaults to `work/builds.db` (sqlite, a single file, no server).
`work/` is git-ignored and deleting it loses no upstream data - one more
`index` run brings it back.

`ROOT` is walked up through `kcilib.repo_root()` rather than counted; a fixed
`dirname()` depth broke when the package moved.

The `commit` quoting gotcha: `commit` is a SQL keyword, so every appearance of it
as an *identifier* is quoted while the Python-side name stays plain. Left
unquoted, SQLite parsed `"commit TEXT,"` in the CREATE TABLE statement as the
COMMIT statement and failed with a syntax error.

Idempotency: every write on `BuildIndex` is idempotent, and `add()` returns
`True` when the build was new - the caller needs that to answer "how many were
added this time" instead of quietly reading idempotency as "nothing happened".
Re-adding a known build refreshes its artifact URLs, because a build can have
artifacts uploaded later. `add_all()` returns `(added, already known)`.

## scripts/local-jobs.py

The local job table as a command line: which builds can be run, what to run, what
has been run.

    ./run.sh build index [--days N] [--tree T]...   # pull the build index from the production API
    ./run.sh jobs  --build <id>                     # list the jobs a build would produce, run nothing
    ./run.sh todo  [--build <id>]                   # the list of what has not run yet
    ./run.sh summary                                # the ledger at a glance

None of the four depend on upstream configuration being merged: `index` only
reads the production API, everything else is computed locally. That is why the
table was already usable while the upstream pull request (1599) was still
unmerged - and it is the control group for "claim mode".

Why a separate entry point instead of folding it into the worker: the worker is a
*standing claimer*, and its problem domain is polling, cursors, deduplication and
redelivery. This table's problem domain is "I know which builds exist and which
ones I have run". The part both share - executing one job - already lives in
`kcilib`; what is left here is only the table.

`cmd_index`: read-only, needs no token. Dropped builds are reported by reason,
because "0 builds" is an answer people chase for hours, and when it happens the
cause is nearly always one of those few reasons. When the filter selects nothing
the command prints "nothing to add" instead of exiting silently - printing
nothing and exiting 0 would look like "no builds exist", while in fact it was the
filter that found nothing.

`cmd_run`: the source decides what runs, but the execution layer is always the
same `run_node`.

* `--source table` - the index minus the ledger (the default, table-driven).
* `--source newest` - the newest usable production build; this is what
  `./run.sh fetch` used to be, now just another source rather than a second
  execution path.
* `--build` is only meaningful with `source=table`, since `newest` has exactly
  one build anyway.

Where the results go is not decided in this command: the sinks come from the
**job definition** (`kcilib/sink.py`). "Was `--callback-url` given" is an argparse
question; "where do results go" is a definition question. Every job in one trip
shares the same sink, because the only input is the same `--callback-url`, so the
definitions are all built up front and the sink is computed once from the first
of them.

Delivery: for the ledger sink, "delivered" is the record the execution layer has
just written (`kcilib/run/jobrun.py`, `record_result`), which is read back and
printed. The callback sink needs the report triple from `run_node`, which
`run_job` now exposes as `outcome["report"]` (see `kcilib/table/localrun.py`) -
`None` when the definition has no callback section, in which case that sink is
not active and does not ask for it.
