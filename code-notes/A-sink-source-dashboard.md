# Group A code notes: sink.py, source.py, dashboard.py

Long-form rationale that used to live in the docstrings and comments of these
three files.  The code now carries one-line summaries plus a pointer here.

## scripts/kcilib/sink.py

### Why the layer exists

"Where a result goes" used to be spread over two places: the ledger was written
unconditionally by the execution layer (`record_result` -> `ledger.write_result`,
kcilib/run/jobrun.py:491), while posting back to the callback was the caller's
own job (kcilib/run/poll.py:238, `post_result`), and scripts/local-jobs.py
decided on the basis of the `--callback-url` argparse value
(scripts/local-jobs.py:264).  No single place could answer "where will this run
send its result".  Every caller wrote its own test, and adding one more
destination (a webhook, a dashboard, another pipeline) meant editing every
caller again.  This module turns that into an explicit, pluggable concept:

    one sink = a name + a switch (wants) + one delivery (deliver)

`sinks_for(definition)` is the single decision point, and it decides from the
**job definition** - the thing the run layer actually sees
(scripts/kcilib/table/jobspec.py:103) - not from an argparse value and not from
the caller's wishes.

### Why the ledger is unconditional

The ledger is the only landing place that depends on no external service: it
must work offline, with no token and no URL.  A failed or interrupted run is
precisely the one that most needs a record (that is the reason given at the top
of kcilib/core/ledger.py).  So `LedgerSink.wants()` is always true - no input
can make the ledger absent - and `sinks_for()` always puts it first.

### Why the callback is conditional

Posting back is the **upstream's** business: only a definition that carries
`callback.url` (this local table is wired to some pipeline) has anywhere to
send.  And "post once with no URL" is not "post one time fewer": in that case
`post_result` raises `CallbackMissingURLError`, which is transient
(kcilib/run/callback.py:332) and turns a run that had already finished back into
pending.  So this switch may only be driven by "does the definition carry a
url" (`callback.callback_url`, kcilib/run/callback.py:292); the caller must not
decide it.

### What this layer deliberately does not do

* **It does not rewrite delivery-failure semantics.**  4xx is a permanent
  failure; 5xx and network errors are retried 3 times and then transient - all
  of that lives in `kcilib.run.callback.post_result`
  (kcilib/run/callback.py:345).  This module only calls it, and does not swallow
  its exceptions: "not delivered" must never look like "delivered".
* **It does not rewrite the ledger.**  The write point is the execution layer.
  Calling `ledger.write_result` again from here would make records *fewer*, not
  better: the execution layer writes the complete record with log/results, while
  the caller only holds a RunOutcome; and the RunOutcome's record/callback_url/
  status are not ledger fields and are rejected outright by
  `ledger.write_result` (kcilib/core/ledger.py:108).  So the ledger sink's
  "delivery" is **fetching back** that record, not writing it again.
* **It does not build a body.**  The callback wants the
  `(callback_url, token, body)` tuple run_node returned, and `body` is produced
  by `lava_body` (kcilib/run/callback.py:82).  Assembling a "close enough" body
  here would send the upstream a format nobody recognises.

### Details kept as one-liners in the code

* The token is not in the definition and not in a file: run_node reads it from
  the environment when the run finishes (kcilib/run/jobrun.py:391), and it
  travels inside `report`.
* `LedgerSink.deliver` returns `(outcome or {}).get("record")` - the record,
  not a new write.
* Order is a contract: the ledger is always first, so a failing callback happens
  *after* the record is on disk and cannot make it disappear.
* `deliver()` skips a callback sink that has no `report`: that is "there is no
  body to send", not "sending failed".  A real failure still raises out of
  `post_result`.

## scripts/kcilib/source.py

### One definition, several choosers

The repository has exactly one job-definition shape (built by
`kcilib/table/jobspec.job_definition`, isomorphic with the rendered upstream
template), so "run a job" has exactly one path.  What varies is only **who
decides which jobs run**:

    table    local index minus the ledger      synchronous, caller-driven   ./run.sh run --source table
    newest   newest usable production build    synchronous, caller-driven   ./run.sh run --source newest

### Why `events` (the worker taking jobs) is not a source

It is not a matter of "fetch a batch of jobs": it polls, stores a cursor,
deduplicates, takes a lock, and keeps results whose post failed so they can be
resent.  Those are the states of a **long-running process**, which a `jobs()`
iterator cannot express.  Squeezing it into this interface would only produce a
fake uniformity.

### What is really shared

The **boundary**.  Both sources end up producing a job definition handed to the
same `run_node`.  Hence the decoupling rules:

    source does not know how a job runs (it imports no runner/judge/bake)
    runner does not know where a job came from (it receives one definition)
    sink   does not know who started the run (ledger always, callback only with a URL)

### Details kept as one-liners in the code

* `NewestSource` is what `./run.sh fetch` does, expressed as a source: query the
  production API, take the newest passing build, offer it as the three specs.
  It reads only - no token, no local stack.
* `NewestSource.build()` widens the window 3 -> 7 -> 30 -> 180 days, because the
  API pages old-first and a quiet tree can be days behind; without the widening
  that used to look like "no build".
* `get_source()` raises `SystemExit` with the list of known names, and reminds
  the reader that the events source is the worker (`./run.sh worker`).

## scripts/dashboard.py

### Why not the upstream frontend

kernelci-frontend is a 2024 Flask application pinned to Flask 1.0 / werkzeug
0.16 / pymongo 3.9, with its configuration in a separate repository
(kernelci-frontend-config), and it connects straight to MongoDB.  Installing it
means standing up a second, old environment plus a config file plus a database
connection - and what it shows is the data *it* wants to show, not this local
table.

### What this page reads

Only our own three things: the build index, the ledger, and optionally the local
API statistics.  All of them are already in kcilib, so the page needs zero extra
dependencies and fits in one file.

### Why it binds 127.0.0.1

The page is for a human, not for the network, so it binds loopback only; and it
needs no authentication because it writes nothing.

### Details kept as one-liners in the code

* `_api_stats()` goes through `kcilib.api` like every other reader of the API.
  The page used to open its own urllib request, which is how five copies of the
  same call came to exist.
* `collect()` returns plain data so the same structure can be served to a
  browser and to machines (`/summary.json`).
* `Handler.log_message` still prints its one line per request.
