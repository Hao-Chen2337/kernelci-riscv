# Group W2c code notes: kcilib api/core/run

Long-form rationale that used to live in the docstrings and comments of these
files.  The code now carries one-line summaries plus a pointer here.

Source files covered (14 non-empty; `scripts/kcilib/core/__init__.py` is
empty and had nothing to move):

    scripts/kcilib/__init__.py
    scripts/kcilib/api.py
    scripts/kcilib/core/cli.py
    scripts/kcilib/core/config.py
    scripts/kcilib/core/ledger.py
    scripts/kcilib/core/params.py
    scripts/kcilib/core/ports.py
    scripts/kcilib/core/state.py
    scripts/kcilib/run/artifacts.py
    scripts/kcilib/run/bake.py
    scripts/kcilib/run/callback.py
    scripts/kcilib/run/jobrun.py
    scripts/kcilib/run/judge.py
    scripts/kcilib/run/poll.py
    scripts/kcilib/run/runner.py

Nothing here is new prose: every paragraph below is a compressed or verbatim
copy of text that was removed from those files.  Line-number citations that
survived in the old comments were rewritten as symbol names in the code, and
the history they carried is kept here.

## scripts/kcilib/__init__.py

### The three lines of the package

Layout as the module docstring used to spell it out (see also
docs/ARCHITECTURE.md):

    core/    cli config state ports params ledger        - plumbing both run paths share
    run/     poll jobrun runner judge bake artifacts callback delivery - the run path
    table/   buildref jobspec buildindex localrun        - the local job table
    api.py   the one KernelCI API client
    sink.py  where a result goes (ledger always, callback when the job says so)

### Why `repo_root()` walks up instead of counting `dirname()`

Modules sit at different depths (`api.py`, `core/x.py`, `run/y.py`,
`table/z.py`), and a fixed number of `dirname()` calls is a silent trap.
After the last package move, ledger/buildindex/config/bake each pointed one
level short - at `scripts/` - so every artifact was written to
`scripts/work/` and the ledger read back empty.  Nothing raised; the paths
were simply wrong.  Walking up to the directory that holds `run.sh` and
`scripts/` cannot drift that way.

The fallback branch (nothing matched) covers a checkout without `run.sh`, or
a harness that copied only `kcilib/`: it returns the old answer so callers get
a root rather than an exception.

## scripts/kcilib/api.py

### Why the module exists

The same three functions had been written out five times, roughly verbatim, in
scripts that all talk to the same API:

    scripts/fetch-and-run-latest.py   api_get / pick_newest
    scripts/tools/config_drift.py           api_get / fetch_all_nodes / list_nodes
    scripts/tools/regression_tracker.py     api_get / fetch_all_nodes / list_nodes
    scripts/kcilib/run/poll.py            fetch_nodes / retrieve_job_definition
    scripts/kcilib/table/buildref.py        fetch_nodes

Each had its own idea of the `/latest` prefix, its own pagination loop (or no
pagination at all) and its own retry story.  An API change then has to be made
in five places, and the four that were forgotten fail silently: a missing page
looks exactly like "the build does not exist".

### Why kernelci-core's own client is deliberately NOT here

Upstream's client is the right client for the *services* that already depend on
kernelci-core (the callback, the scheduler), but these scripts are standalone on
purpose: `./run.sh fetch` is documented as needing "no stack, no node, no
token", and requiring a cloned kernelci-core with a `kernelci.toml` would take
that away.  What we do owe the upstream client is its CONVENTIONS: the
`/latest` prefix, `{items,total,offset}` pagination, and JSON-or-error.

### Constants

* `PRODUCTION_API` is the public API; a deployment overrides the base with
  `KCI_API_URL` (see `client()`, whose own default is `LOCAL_API`).
* `PAGE_LIMIT = 200` is what the scripts that already paged used, and what the
  API serves happily.

### The client class

`KernelCI` is read-mostly: only what these scripts actually need - fetch
nodes (one page or all), one node, an event page, and a job definition.
Writes (creating nodes) are done by the scripts that own that decision, through
`post()`, so an accidental write is never one method call away from a read.

* `latest`: KernelCI serves everything under `/latest`; the dev API accepts
  both forms, production only the canonical one, so always target `/latest`.
* `get()`: retries a connection error (the local API drops idle ones, with a
  `time.sleep(attempt + 1)` backoff) and raises requests' own exceptions
  otherwise, so callers that already catch
  `requests.exceptions.RequestException` - `kcilib.run.poll` does - keep
  working.
* `_refuse_redirect()`: a 3xx is never the answer, it means something else is
  answering.  Only `job_definition()` used to check this, so a proxy that
  replied "302 + a perfectly valid JSON body" was accepted as data by every other
  reader - and 302+HTML merely looked like a JSON error, which hid the
  difference.  Asking not to follow redirects (`allow_redirects=False`) is not
  the same as noticing one arrived.
* `_json()`: a proxy's HTML error page is not JSON.  This used to escape as a
  bare `ValueError` and kill callers that only expect API errors.
* `all_nodes()`: `/nodes` returns results in creation order and truncates
  each response to the page limit, so a single request silently misses the
  newest nodes of a busy job - a missing page is indistinguishable from "no such
  build".  The response carries `{items,total,offset}`, which is what makes
  walking it possible without guessing (and, when `total` is absent, a short
  page is the end).
* `job_definition()`: the definition URL is handed out by the scheduler, so a
  redirect means something in between is answering instead - hence the refusal.

## scripts/kcilib/core/cli.py

### Provenance

Moved VERBATIM out of `scripts/riscv_pull_worker.py` (phase 4): the same
`add_argument` calls, in the same order, with the same help strings, so
`riscv_pull_worker.py --help` and every argparse error are byte for byte what
they were.  Only the default VALUES now come from `kcilib/core/config.py`: the
two config dataclasses are where "what the worker defaults to" lives, and a
parser that hard-coded its own copies could drift away from the config a
programmatic caller gets.

The one thing that is not a flag definition is the
`--min-timeout`/`--max-timeout` sanity check.  It must stay in
`parse_args()` so that it keeps reporting itself the way it always did
(argparse's usage on stderr, exit status 2); raising it from the config layer
would have changed those bytes.

### parse_args()

A `--min-timeout` above `--max-timeout` is refused with `parser.error()`:
otherwise `clamp_timeout()` would quietly return the floor and the "upper
bound" would mean nothing.

## scripts/kcilib/core/config.py

### Why two dataclasses replaced the 23-field argparse Namespace

Phase 4's last layer.  The library used to read a 23-field argparse Namespace -
every module reached into the parsed command line for its own settings - which
meant every module knew that the worker is a command line, and the poll loop
knew the shape of the run configuration as well.  Two small dataclasses replace
that namespace:

* `RunConfig` is everything ONE RUN needs - the tuxrun executable, the device,
  the guest images, the workspace and console-archive directories, the timeout
  bounds, the KVM selection - and nothing about the API.
  `jobrun.run_node(node, run_config)` can therefore be called by a caller that
  has never heard of the events API.
* `PollConfig` is the API side: where to poll, how often, how hard to retry,
  where the cursor lives, and which jobs this worker claims (platform /
  runtime).  `poll.poll_loop(poll_config, run_node, run_config)` owns it.

`from_args()` is the only place an argparse Namespace is read, so "which flag
lands in which field" is one screen of code a reviewer (and the guard tests) can
check in one look.  Programmatic callers - a test, or the one-shot runner -
build the dataclasses directly: `scripts/fetch-and-run-latest.py` builds a
`RunConfig` in its `main()` and reads the run-scoped fields
(`tuxrun_bin`, `cpu`, `kvm_full`, `container_runtime`, `rootfs`,
`output_dir`) from it, instead of reaching into its own argparse namespace at
the point of use.  What it keeps in that namespace is its deployment business
(which build to fetch, which port to serve it on, whether to provision only),
which is not part of "one run".

### DELIBERATELY NOT A FIELD: `RunConfig.runtime`

`--runtime` is the *lab* filter (the events API's `data.runtime`,
`pull-labs-riscv`), which is the poll layer's business and lives in
`PollConfig`; the runtime tuxrun is told to use (podman/docker) is
`RunConfig.container_runtime`.  One name for two meanings would be worse than
the missing field, so the container runtime keeps its own name - and
`jobrun.runtime_name()` still auto-detects podman, then docker, when it is
empty, exactly as before.

### Defaults and the environment

The defaults in this module ARE the CLI defaults: `kcilib/core/cli.py` builds
its parser from them, so the flags, their help text and their values cannot
drift away from the config a programmatic caller gets.  The environment-derived
ones (`QEMU_CPU`, `KCI_API_CONFIG_NAME`, `KCI_STORAGE_CONFIG_NAME`) are
`default_factory` functions, read when a config is built - the same moment
the old argparse defaults were evaluated.

### Field-level notes

* `REPO_ROOT`/`LOG_DIR`: the repository root, not the CWD.  `work/@ is the
  durable tree this repo already has, and "the logs are in work/logs" must hold
  whatever directory the worker was started from.
  `kcilib.repo_root()` walks up to `run.sh`; counting `dirname()` levels
  pointed at `scripts/` as soon as this module moved into `core/`.
* `DEFAULT_MAX_TIMEOUT`: the ceiling for a job definition's `timeout_s`,
  matching the pull-labs runtime's own timeout; its floor is
  `kcilib.run.jobrun.MIN_TIMEOUT`, which below cannot even boot a guest.  The
  CLI refuses `--min-timeout` above `--max-timeout`
  (`cli.parse_args`), so both bounds keep meaning something.
* `RunConfig.max_download_size` is in BYTES (the unit
  `kcilib.run.artifacts` and `kcilib.run.bake` take); the CLI flag is
  `--max-download-mb` and `from_args()` does the shift.
* `RunConfig.kvm_tests` is the same list object argparse's `--kvm-tests`
  defaults to; `build_command()` copies it and nobody mutates it.
* `PollConfig.platform`/`runtime` are the event filters: a job whose
  `data.platform` / `data.runtime` differs is skipped; None or "" means
  "claim everything".
* `from_args()` lists every field explicitly, so a flag that quietly stops
  reaching the library is visible here instead of being swallowed by a
  namespace; `scripts/tools/verify-worker-guards.py` drives this function too,
  so the mapping is a tested thing and not a claim.  The `--max-download-mb`
  -> bytes shift lives there (it used to be the worker's `main()`), and the
  timeout sanity check stays in `kcilib.core.cli.parse_args()` so it keeps
  printing argparse's usage and exiting 2.

## scripts/kcilib/core/ledger.py

### Why a ledger at all

Every run of `scripts/fetch-and-run-latest.py` records what it tested and how
it ended, because the run itself leaves nothing durable: its workspace is a
gitignored `work/downloads/<build-id>/` that the next run overwrites, and its
console only exists in the terminal it was started from.  The record is written
for EVERY outcome - a failed run is exactly the one worth having a record of -
so writing it must not be the thing that fails: records go to a temporary file
and are renamed into place, and a reader may therefore trust any file it finds.

### The contract

The path layout and the key set are the contract, not an implementation detail
(a report, a regression tracker or an operator reads them without importing this
module):

    work/results/<build-id>/<test>.json

      build_id, build_created, job, test, source, timestamp, verdict,
      exit_code, detail, revision, artifacts_dir, log, results

Keys are written sorted and indented by one space, so two records of the same
outcome are byte-identical and diff cleanly.

### Path derivation and the override

* `ROOT` is derived from this file's own location (never a hardcoded absolute
  path); `work/` is gitignored and holds regenerable runtime artifacts.
  `kcilib.repo_root()` WALKS UP to the directory holding `run.sh` instead of
  counting `dirname()` levels: a fixed count pointed one short (at
  `scripts/`) after the last package move, so every record was quietly written
  under `scripts/work/` and the ledger read back empty - no error, just the
  wrong place.
* `KCI_RESULTS_DIR` (`RESULTS_DIR_ENV`) exists for testing, not deployment:
  the guard suite drives a REAL `run_node()`
  (`scripts/tools/verify-worker-guards.py`,
  `test_missing_callback_keeps_result_pending`), so once the worker writes
  records too, an unredirectable root means `./run.sh verify` leaves records in
  the repository's `work/` tree.  The LAYOUT is still the contract - only the
  root moves.

### Fields

* `RESULT_FIELDS` is the one place the key set is defined:
  `write_result()` fills the fields a caller leaves out and refuses fields
  that are not here, so a typo cannot quietly drop a field from the record.
  (The in-function error text "Silently dropping an unknown key is how a record
  loses its verdict" is kept verbatim in the code.)
* `source` says which writer filed the record: `fetch` (the one-shot runner
  re-running one production build), `worker` (the resident poller taking lab
  jobs) or `table` (the local job table, see
  `jobrun.SOURCE_TABLE`).  Two writers with one layout is the point; a reader
  that cannot tell which one produced a row cannot tell a re-run from a
  dispatched job either.
* `_FIELD_DEFAULTS` are taken from the fallbacks the writer has always used: a
  build without a name is `""` and one without a revision is `{}`, not null.
* `write_result()`: `payload` carries the outcome - `build_created`,
  `job`, `verdict`, `exit_code`, `detail`, `revision`,
  `artifacts_dir`, `log`, `results` (and optionally `timestamp`) -
  while the build and test identity comes from the arguments, so a record can
  never be filed under a path that names a different run.  A record that does
  not say when it was written cannot be lined up with the build it describes,
  hence the written-for-you timestamp.

### Reading back

* `read_results()`: a test that was never run is simply absent (`{}` for a
  build nothing is recorded for), and a record that cannot be parsed raises
  rather than being skipped - a ledger that quietly loses rows is worse than no
  ledger.  A `.tmp` left by a killed write is not a record.
* `list_builds()`: ordered by the newest timestamp IN the records, not by
  directory mtime - a build whose directory was touched by a copy or a restore
  would otherwise sort as if it had just run.  An unreadable record raises here
  for the same reason `read_results()` does; the name breaks a tie so two
  builds recorded in the same second still come back in a stable order.

## scripts/kcilib/core/params.py

### Why these parameters are shared

The pull-lab worker and the one-shot fetch path run the same tuxrun invocations
on the same build, so the things that decide *what* is run - the curated KVM
allow-list and the QEMU cpu property string - live here rather than being copied
into each script.  They were moved out of `riscv_pull_worker.py` unchanged;
the worker keeps its `--kvm-tests` and `--kvm-full` flags as the overrides.

### KVM_TEST_SUBSET

These are the KVM selftests that behave under TCG.  The perf/stress tests in the
same collection (`demand_paging`, `access_tracking_perf`,
`dirty_log_perf` and friends) measure throughput, which has no meaning on an
emulator, and `kvm_page_table_test` hangs the job - all of them are
deliberately excluded (verified in the real loop) and stay available via
`--kvm-full`/`--kvm-tests`.  The list is passed to the LKFT script as a
`TST_CASENAME` allow-list (`kvm:name ...`).

### cpu_for() and kvm_allow_list()

`cpu_for()` takes the cpu string rather than an argparse namespace so both
entry points can use it with their own `--cpu` default; KVM jobs need the H
extension enabled.  `kvm_allow_list()` renders the subset in the form the LKFT
script wants: `kvm:name kvm:name ...`.

## scripts/kcilib/core/ports.py

### Why the probes exist

Every port this deployment uses is overridable (`KCI_*_PORT`) and nothing
checked whether the value was free before a service was started on it.  A port
held by an unrelated listener then surfaced three layers down as "X artifact
server failed" - with the real `EADDRINUSE` only inside
`/tmp/fs8999.log` - or as a compose bind failure that blamed the API.
`docs/HANDOVER.md` used to tell people to move the artifact server off 8999
"because the port is reserved"; that note is stale (8999 binds here), and the
check in this module is what answers the question where it matters instead of by
folklore.

Binding is the only honest test, for the same reason
`scripts/fetch-and-run-latest.py` probes its artifact server port by binding:
a listener that answers nothing still owns the port, and "something is there,
but it did not answer me, so carry on" is how a stale server ends up serving an
older build to a run that names a newer one.

### Why `run-local-stack.sh` probes through this module's command line

The shell used to carry its own copy of the bind test, the holder lookup and the
refusal text (three functions, ~49 lines, and the stale note in
`docs/HANDOVER.md` quoted them by line number).  Two implementations of "is
this port free" is one implementation too many: the shell's copy bound 0.0.0.0
and this module's default is 127.0.0.1, so the same question had two different
answers waiting to happen.  The shell now calls
`python3 -m kcilib.core.ports --require PORT ...`.

### Constants and helpers

* `DEFAULT_HOST` is 127.0.0.1: the stack binds 0.0.0.0, but a probe against a
  specific address is what the callers need for "is the port I am about to hand
  to a local client taken?".  A caller that must reproduce the stack's own bind
  passes `host="0.0.0.0"`.
* `KCI_COMPOSE_PROJECT` / `DEFAULT_COMPOSE_PROJECT`: `require_port_free()`
  exempts a port published by OUR compose project (the stack is partly up and
  compose reconciles it).  "Ours" is the same value `run-local-stack.sh`
  builds as its `PROJECT` variable, resolved here so a caller that does not
  name its project still means the default deployment.
* `NO_HOLDER` is what the holder line says when neither `ss` nor `lsof`
  could be run: an empty line would read as "no holder" inside the very message
  that exists to name the conflict.
* `_command_output()` returns the first two lines of stdout, or `""` - a
  probe, never a failure.  stderr is discarded exactly as the shell callers
  discarded it: `ss` absent, `lsof` denied and "no listener" all mean the
  same thing to the caller, which is why "could not be identified" is a sentence
  at the call site rather than an exception here.
* `port_is_free()`: a failed bind is the answer, not an error - the caller is
  asking whether a service may be started here, and anything already holding the
  port (a live listener, or a socket another process left behind) says no.
  `SO_REUSEADDR` is set because that is how the services themselves bind;
  without it a recently closed connection would look like a conflict.
* `port_holder()`: `ss` first (it names the process too), `lsof` second,
  and an explicit sentence last - this string is embedded in a refusal, and a
  refusal that cannot say who holds the port sends the reader hunting through
  service logs for a conflict that is not theirs.
* `_compose_project()`: a listener this repo started (the partly-up stack) is
  not a conflict, so the caller has to tell it from somebody else's.  Docker
  absent or unreadable reports no owner, which only costs the "(compose project
  ...)" hint.

### require_port_free()

Raises `SystemExit` (exit status 1, the code the shell's `exit 1` produced)
with the message `scripts/run-local-stack.sh` prints today, so the refusal
keeps the same detail wherever it is raised from: the port, the label of the
service that wanted it, the holder, and the variable that moves this deployment
instead.  A caller with its own wording keeps it by building the message from
`port_is_free()`/`port_holder()` itself.  `project` names the compose
project this deployment owns.

The empty-owner guard: the shell only exempted a port OWNED by our project, so
an empty owner compared against an empty project must not read as "ours", or a
foreign listener would be waved through in silence.

`host` is the address the probe binds and it is NOT decoration: the stack binds
0.0.0.0 (so a listener on any interface owns the port), while the default
127.0.0.1 only answers "is it taken for a local client".  Probing 127.0.0.1 for
a service that binds 0.0.0.0 would let a foreign listener on another interface
through, which is why `run-local-stack.sh` passes `host="0.0.0.0"` - the same
value `fetch-and-run-latest.py` already passes to `port_is_free()`.

Every override variable this check is called with is one of the
`KCI_*_PORT` entries listed at the top of `scripts/run-local-stack.sh`.

### main()

A taken port exits 1 with the refusal on stderr (`require_port_free()` raises
`SystemExit`); a free port, or one published by this deployment's own compose
project, exits 0 and prints nothing.

## scripts/kcilib/core/state.py

### Why the worker needs a state file

The RISC-V pull-lab worker has to survive a restart in the middle of a batch
without re-running a job whose result it already holds:

* the cursor says where the next poll resumes scanning (it is authoritative -
  `--since` only seeds a state file that has no cursor yet),
* `seen` says which nodes already ran, so a late event for one of them is
  re-posted, never re-run,
* `pending` holds a LAVA callback body whose POST failed transiently, so the
  next start can post it again without re-running tuxrun.

Those three fields are a contract, not an implementation detail: operators
hand-edit the file and an older worker must read a file a newer one wrote, so
the shape is exactly the one the worker has always written:

    {
      "timestamp": "2026-09-15T16:08:08.858000",   // cursor, or null
      "seen": ["6aa8f22af456c71d47ca435d", ...],   // oldest first
      "pending": {"<node id>": {"callback": "<url>", "body": {...}}}
    }

The callback *token* is deliberately not part of that shape: it is read from the
environment when the body is posted and is never written to disk.  The file is
written through a temporary file and a rename, so a worker killed while saving
leaves the previous state behind rather than a half-written one - the pending
result that survives a crash is the whole point of the file.

### Constants

* `SEEN_LIMIT` (20000): seen-node ids kept in the state file, evicted oldest
  first.  Sized far beyond what one re-scan window (`CURSOR_OVERLAP_S` in
  `kcilib/run/poll.py`) can produce, so eviction can never re-expose a
  recently processed node to a re-run.  Read at call time rather than captured
  per instance, so a test can shrink it.
* `STATE_FIELDS`: the fields this module owns, in the order they are written.
  Anything else found in a state file is carried through untouched (see
  `_extra`).

### _empty_state()

A state file that cannot be parsed must not kill the worker far away from the
file that caused it, and it must not be trusted either, so callers get this same
empty state either way; `load()` says which one happened.

### StateFile

The usage the class docstring used to spell out:

    state = StateFile(path)          # path=None: nothing is persisted
    state.load()                     # missing/corrupt file -> empty state
    state.cursor, state.seen, state.pending
    state.mark_seen(node_id)         # dedup, evicting past SEEN_LIMIT
    state.add_pending(node_id, callback, body)
    state.pop_pending(node_id)       # the entry, or None
    state.save()                     # atomic; no-op when nothing changed

`seen` is the on-disk list (oldest first, duplicates impossible) and is what a
caller reads and writes; `has_seen()` is the membership test that stays cheap
once the list is at `SEEN_LIMIT`.  `pending` maps a node id to the stored
`{"callback": ..., "body": ...}` dict, so a caller rebuilds the
`(callback, token, body)` tuple it posts with the token from the environment.

Internals:

* `_seen_set` is an accelerator for `has_seen()`: the worker tests every
  event of every poll against up to `SEEN_LIMIT` ids.  It is rebuilt whenever
  it disagrees with the list, so a caller that appends to `.seen` directly
  cannot silently desynchronise it.
* `_written` is the bytes of the last document this object wrote, and
  `_saving` is the re-entrancy flag: a signal handler saving while a save is
  in progress must not write the same temporary file twice.

### load()

A file that does not exist yet is simply an empty state (the first run of a
fresh worker, no warning).  A file that exists but is corrupt or of an
unexpected shape is refused loudly - it is the state that keeps a restarted
worker from re-running jobs - and replaced in memory by an empty state, never
trusted.

Keys this module does not own are kept in `_extra`: the worker used to rewrite
the very dict it had read, and dropping a field an operator or a newer worker
put there would lose it silently.  After a load `_written` is reset to None
because the next `save()` must write: the file on disk may be hand-formatted,
and the worker's first flush after a load has always written.

### save()

Called after EVERY event, not once per batch (#9): a worker killed after a
transient callback failure but before the batch ended used to lose the report,
the pending entry and the seen update, so the next start re-ran tuxrun for a node
whose result it already had - exactly what the "re-posted, never re-run"
contract promises not to do.  It is also called from the SIGTERM/SIGINT handler,
hence the re-entrancy guard.

The other guard keeps that honest rather than expensive: a batch of a thousand
events with nothing new to record must not rewrite a state file that can carry
up to `SEEN_LIMIT` node ids a thousand times.  The comparison is on the
document that would be written, so an eviction at `SEEN_LIMIT` - same length,
different ids - is not mistaken for "nothing changed" and silently left
unwritten.

### mark_seen() / has_seen() / add_pending() / pop_pending()

* `mark_seen()`: only a node that was actually processed belongs in the seen
  set - the first event for a node may arrive before its `job_definition`
  artifact is attached, and marking such an event seen would hide the later,
  complete one.  (The resync branch handles a caller that mutated `.seen`
  itself.)
* `add_pending()`: the body is stored exactly as it will be posted, so a later
  run can re-post it without re-running the job that produced it.
* `pop_pending()`: called once the body is posted, or once the callback failed
  permanently - a node must never keep a body it can no longer post.

`_reset()` and `_document()` keep the empty state and the key order existing
state files use.

## scripts/kcilib/run/artifacts.py

### The two rules this module keeps in one place (both were bugs once)

* A partial transfer is never lost and never trusted blindly.  The bytes land in
  `<dest>.part` beside a sidecar naming the URL they came from, so a later
  attempt - even a later run of the same command - resumes with a Range request
  instead of downloading a 144MB rootfs from zero again.
* A file is only reused once it has been PROVEN complete.  `os.path.exists()`
  adopted an `Image` that an interrupted run had left truncated and handed it
  to tuxrun as a kernel; a `.part` whose sidecar already records its own size
  used to be resumed from that total, which the server answered with 416
  "Requested Range Not Satisfiable" until somebody deleted the file by hand.

Nothing here swallows a failure: a transfer that cannot be shown complete
raises, or keeps its partial data on purpose.

### Constants

* `MAX_DOWNLOAD_SIZE` is 4 GiB per download; rootfs tarballs fit easily.
* `BUILD_ID_RE`: a KernelCI artifact URL names the build it belongs to in the
  first path segment after the host, `/<job-name>-<build-id>/<file>`, where the
  id is a 24-character kcidb node id
  (`kbuild-gcc-14-riscv-6aa3689720239ade90209d50`).  A pull-lab job definition
  carries no build id of its own - only artifact URLs - so this is where the
  worker's ledger takes "which build did this run test" from, instead of
  inventing a parallel identity.
* `BUILD_ID_ARTIFACT_KEYS` is read in this order so the answer never depends
  on dict order: the kernel first (the artifact that decides what was booted),
  then the test and module tarballs, then the config.
* `DOWNLOAD_TIMEOUT` is a per-read gap, not a total budget: the artifact hosts
  (storage.kernelci.org, files.kernelci.org) go quiet mid-transfer often enough
  that the old 300s meant "hang for five minutes, then retry".  60s of silence
  is a stalled connection; a slow-but-moving download is unaffected.

### Functions

* `build_id_from_artifacts()` returns "" when no artifact URL names a build: a
  job whose kernel is served from a local mirror (the local stack seeds exactly
  that) has no id to take, and a caller must decide what to file the run under
  rather than getting a fabricated one from here.
* `_resume_offset()`: production storage truncates big transfers routinely (a
  144MB rootfs arriving as 1.3MB is ordinary), and restarting from zero each time
  means a flaky link never finishes.  The partial file is only trusted when its
  sidecar says it belongs to *url* and does not already exceed the expected size
  - otherwise a stale partial would be prepended to good data.
* `publish_complete_part()`: a crash between the last byte and
  `os.replace` leaves the full file under `<dest>.part` beside a sidecar
  recording that exact size.  The old code resumed from that offset instead of
  publishing it, so every attempt asked for `bytes=<total>-` and the server
  answered 416 three times before raising: that artifact stayed undownloadable,
  and every job needing it reported Infrastructure, until somebody deleted the
  `.part` by hand (#7).  Only a sidecar that names *url* and a size that is
  exactly the recorded total makes a partial publishable - a short file is a
  normal resume and a long one is not trustworthy at all.  Without *url* there is
  nothing to compare the sidecar against, so a caller that knows the URL passes
  it.
* `_discard_partial()`: appending to a partial whose bytes cannot be trusted
  would hand the caller a file that is silently corrupt, so the transfer
  restarts from zero instead of risking that.
* `_content_range_total()` is shared by the 206 body (`bytes 100-999/1000`)
  and the 416 error form (`bytes */1000`), which both carry the total.
* `download()`: the bytes land in `<dest>.part` and are only renamed into
  place once the full length has arrived, so *dest* is never a half file.  A
  truncated or stalled attempt keeps its partial data (with a sidecar recording
  which URL it belongs to), and the next attempt - even a later run of the same
  command - asks the server for the remainder with a Range request.  In detail:
    * a `.part` an earlier run left complete (crash between the last write and
      the rename) is published before any range request is built: resuming from
      its own total is what produced the permanent 416 (#7);
    * a server that ignores the Range header makes the transfer restart from
      scratch rather than append to a file it knows nothing about;
    * a 416 means the partial is not what its sidecar claims or the artifact
      changed under us.  The server's own total is trusted: when it equals the
      offset the transfer was complete all along and the file is published;
      otherwise the stored bytes are unusable, so they are dropped and the
      transfer restarts (#7);
    * on any exception the partial data is kept, so the next attempt resumes
      from there;
    * a size that disagrees with the total raises "Truncated download" rather
      than publishing a short file.
* `gzip_isize()`: a complete *download* is not proof of a complete *gunzip* -
  the kernel is decompressed into its final name, so a run killed mid-gunzip
  leaves a truncated `Image` that still exists and is still non-empty.  The
  trailer is the only size a finished `.gz` carries, and reading 4 bytes costs
  nothing.
* `looks_complete()` is only consulted for a file with NO manifest record,
  i.e. the one case where a cache hit would otherwise adopt a file on trust
  (#13).

## scripts/kcilib/run/bake.py

### Provenance

Moved VERBATIM out of `scripts/riscv_pull_worker.py`, which owned it until
now: `bake_rootfs_image()` turns the nfsroot tar.xz artifact into an ext4
image tuxrun can boot (`mkfs.ext4 -d`: no loop mount, no root) and bakes
`modules.tar.xz` into `/lib/modules` with a modules-load.d conf so
`modprobe kvm` works at boot; `baked_rootfs_image()` puts a cache in front of
it, keyed on the exact bake inputs.  Both the worker and
`scripts/fetch-and-run-latest.py` need exactly this code - the fetch script
carries an inlined copy of it - so this module is also the deduplication of that
copy.

### HOW THE ROOT IS DERIVED

`bake_cache_dir()` defaults to `<repo>/work/env/baked` and takes `<repo>`
from THIS file's location - never from the CWD, never from a hardcoded absolute
path - exactly as `ledger.py` takes `work/results` from its own location and
as the worker did with its own `__file__`.  That is the ONE expression that had
to change when the code moved: the worker sits at
`scripts/riscv_pull_worker.py` and needed two `dirname()`s to reach the
repository root, while this file sits one directory deeper at
`scripts/kcilib/run/bake.py` and needs three.  Both spellings resolve to the
same directory:

    worker: dirname(dirname(realpath(scripts/riscv_pull_worker.py)))
    here:   dirname(dirname(dirname(realpath(scripts/kcilib/run/bake.py))))

(That last line is why `kcilib.repo_root()` walks up to `run.sh` today.)
`realpath` rather than `abspath` is kept on purpose: a symlinked launcher
must not place the multi-GB cache next to the symlink, outside the gitignored
`work/`.

### The two seams

Both are module attributes, so a caller can re-bind them exactly as the worker's
guard tests re-bind `artifacts.requests`:

* `stamp()` - the `[HH:MM:SS] ` progress printer, byte-identical to the
  worker's own `stamp()`; every line a bake prints goes through it;
* `download()` - `kcilib.run.artifacts.download`, the transfer the worker's
  own `download()` wrapper delegates to (that wrapper only re-binds
  `artifacts.requests` first, so it is the same transfer and the same printed
  lines).

Importing this module has no side effects: nothing here reads the environment,
touches the filesystem or prints until a function is called.

### stamp()

Added after a `worker --once` run took 17m42s where the internal notes promised
~7 minutes, and ~14 of those minutes sat between two jobs with no way to tell
where they went: every line looked alike and the only clock was the log file's.
The two phases that can take minutes - preparing the guest (download + baking a
4GB ext4 per job) and tuxrun itself - now report their own duration, so the next
report can attribute the time instead of guessing.  The worker keeps its own
`stamp()` for its non-bake lines, and a caller may re-bind
`kcilib.run.bake.stamp` just as it re-binds this module's `download`.

### Cache constants

* `DISK_SIZE = "4G"`: ext4 image size, unrelated to QEMU memory.
* `BAKE_CACHE_MAX_ENTRIES = 3`: each entry is a full `DISK_SIZE` image, so
  the cache is bounded by entry count.  Two or three entries cover the real
  input sets (kselftest-riscv bakes no modules, kselftest-kvm bakes
  modules.tar.xz, a different rootfs is a third).
* `BAKE_CACHE_TMP_AGE_S = 3600`: a killed bake's `.tmp` is ignored, then
  aged out.

### _safe_member() and _extract()

* Symlinks with absolute targets are ALLOWED - rootfs tarballs legitimately ship
  them (`./init -> /usr/lib/systemd/systemd`,
  `./dev/stdout -> /proc/self/fd/1`); extraction only stores the link text, the
  link is meaningful inside the guest image, and nothing on the host follows it.
  Absolute member paths and `..` components are rejected.
* Hardlink targets stay strict: tarfile resolves them with `os.link()` on the
  host at extraction time, so an absolute target would genuinely escape.
* Device/FIFO members are skipped: rootfs tarballs ship `/dev` nodes and
  `mknod` fails for an unprivileged lab user
  (`trixie-full.rootfs.tar.xz` reproduces this), while `mkfs.ext4 -d`
  populates them from the tree anyway.

### bake_rootfs_image()

* `boot_modules`: an `/etc/modules-load.d/kernelci.conf` is dropped into the
  tree before `mkfs.ext4`, so the guest modprobes those modules at boot.
* `modules_url` (kselftest-kvm): the `modules.tar.xz` is ALSO unpacked under
  `/lib/modules` before `mkfs.ext4` - the `--modules` LAVA overlay is
  delivered only after boot and never lands in `/lib/modules`, so without
  baking them in, `modprobe kvm` at boot finds nothing and every kvm test skips
  with "Cannot open '/dev/kvm'".  kselftest/modules are otherwise injected by
  tuxrun as LAVA overlays instead of being baked in.
* `modules.tar.xz` ships `lib/modules/<version>/`, so extracting at the tree
  root puts them exactly where `modprobe`/`uname -r` looks.
* Refusing to write through a symlink (tar-slip via symlink): the realpath must
  stay exactly where the lexical path is, inside the extracted tree -
  absolute-target symlinks in the tarball are fine as image content, but our own
  writes must never follow them.
* `image_path`: where the ext4 file is written (default
  `<workspace>/rootfs.ext4`).  Callers that publish the image somewhere else
  (the baked-image cache, whose temporary file must sit in the cache directory so
  the publish is a rename) pass it explicitly.  Everything else - tarball,
  extracted tree - still lives under *workspace* and is discarded with it.

### disk_size_bytes() / _human_size()

`disk_size_bytes()` turns `DISK_SIZE` into bytes for validating a cached
image's length; `_human_size()` renders bytes for the cache log lines.

### bake_cache_dir()

Default `work/env/baked/`: `work/` is gitignored and already the documented
home of the multi-GB guest testbed (`work/env/rootfs-kvm.ext4`), so the big
regenerable files stay in one place that no one commits.  A separate
*subdirectory* rather than that exact path, because
`work/env/rootfs-kvm.ext4` is a different artifact owned by
`./run.sh provision` and its `work/env/.manifest.json`: two writers on one
file would race, and one fixed filename cannot hold the several distinct input
sets a worker sees (kselftest-riscv bakes no modules, kselftest-kvm bakes
modules.tar.xz, a lab may point `--rootfs` elsewhere).

Override with `KCI_BAKE_CACHE_DIR`; disable with `KCI_BAKE_CACHE=0` (then
every job bakes into its own workspace, as before).  Returns "" when disabled.

The three `dirname()`s that used to be here counted from
`scripts/kcilib/run/bake.py`; after the package move this file sits one level
deeper, so the cache would have landed in `scripts/work/env/baked` - a
multi-GB directory nobody would ever clean.

### cache_dir_writable()

`os.makedirs(exist_ok=True)` succeeds on a directory that exists but is not
writable - a read-only mount, or `work/env/baked` left root-owned by a single
`sudo` run - and `os.access` is unreliable for root and ACLs, so probe by
writing.  Without this probe the bake was aimed into such a directory and
`mkfs.ext4` failed the whole job, making an optional optimisation able to
break jobs that worked before it existed.

### bake_cache_inputs() / bake_cache_key() / cached_rootfs_image()

* `bake_cache_inputs()` serialises everything `mkfs.ext4`'s result depends
  on: the rootfs tarball, the modules tarball, the modules-load.d list baked into
  the tree and the image size.  A key that omitted any of these would hand a job
  an image built from other inputs, so the test for "changed URL must not reuse"
  is exactly this serialisation.
* `bake_cache_key()` is a short stable filename: sha256 of the serialisation,
  first 16 hex digits.
* `cached_rootfs_image()`: a hit requires ALL of a regular file that is not a
  symlink and resolves inside the cache directory (a symlink could otherwise hand
  tuxrun an unrelated disk outside it), a sidecar recording byte-identical
  *inputs*, and an image whose size is both the recorded size and the size
  `mkfs.ext4` was asked to write.  The sidecar is published LAST, so an
  interrupted bake leaves an entry that is simply never trusted.

### _write_cache_sidecar() and publish_baked_image()

* The sidecar is written atomically (tmp + rename, like `save_manifest`) and
  only after the image is in place: a crash in between leaves an image nobody
  trusts rather than a sidecar promising a file that is not there.
* The bake wrote `<key>.ext4.tmp<pid>` inside the cache directory, so
  publishing is one rename on one filesystem: a reader sees either the previous
  entry or the complete new image, never a half-written one, and a bake that is
  killed mid-way (leaving only the `.tmp`) cannot poison the entry.  The size
  is checked before the rename - `mkfs.ext4` is handed `DISK_SIZE`, so
  anything else means the file in hand is not the image.

### prune_bake_cache()

Each entry is a full-size image (~4GB), so an unbounded cache fills a disk one
input change at a time.  Only files this module creates are touched:
`<key>.ext4` + `<key>.json` pairs and `<key>.<suffix>.tmp<pid>`.

It is enumerated from BOTH file kinds: a publish that wrote the image and then
failed to write its sidecar used to be invisible here (only `*.json` was
listed), so each occurrence parked another ~4GB forever.  Such an image is
unusable for reuse, so it is counted against the cap and removed once it is
older than the publish window - younger ones may belong to a publish that is
still running (image renamed, sidecar next).

Other rules: a sidecar without an image is an entry somebody removed by hand and
is dropped; symlinks are skipped; `keep_key` counts towards the cap (it is one
of the entries on disk) and is only exempt from *eviction* - skipping it while
counting could leave `max_entries + 1` entries behind after a long bake raced
another publisher; `.tmp` files are only removed once they are older than
`BAKE_CACHE_TMP_AGE_S`, because a fresh one may belong to a bake still running
(the age test is what protects it, not the key).

### baked_rootfs_image()

A real batch spent `kselftest-riscv: guest prepared in 144.4s` and
`kselftest-kvm: guest prepared in 180.9s` re-downloading the same ~144MB
nfsroot tarball and re-baking the same 4GB ext4 image per job, while
`boot: guest prepared in 0.0s` showed what a job costs without that step.  The
bake is a function of the inputs in `bake_cache_inputs()`, so the second job
with the same ones gets the image from disk.

The key is the *URL*, not the bytes: content that is replaced behind an
unchanged URL is not noticed (adversarial review demonstrated it).  The
production artifact URLs embed the build id (`/kbuild-gcc-14-riscv-<id>/`) or a
rootfs version directory, so they are immutable in practice; if you ever repoint
a URL at different content, run with `KCI_BAKE_CACHE=0` or
`rm -rf work/env/baked`.  Checking the bytes would mean downloading them,
which is exactly what the cache exists to avoid.

Cache failure handling, all of it deliberate:

* an unusable cache directory (`os.makedirs` fails, or the directory is not
  writable) must not fail the job: bake into the workspace exactly as before and
  report the reason once;
* the temporary target is created inside the cache directory, so
  `publish_baked_image()` is a same-filesystem rename even when the workspace
  sits on another mount (the worker's default workspace base is `/tmp`);
* every cache-specific failure (disk full, the directory turned read-only
  between the probe and mkfs, a publish that cannot rename) falls back to the
  pre-cache behaviour instead of failing the run.  The retry cannot loop: it is
  only reachable when a cache target was set, and the second bake writes into the
  workspace;
* a killed process cannot run the cleanup branch, which is why the reader
  ignores `.tmp` files and `prune_bake_cache()` ages them out;
* caching is an optimisation: if the image cannot be moved into the cache (a
  rename that fails, a full disk, a sidecar that cannot be written), it is
  reported and tuxrun gets the image that WAS baked.  A published image without
  its sidecar is unusable for reuse, so it counts against the cap and prune ages
  it out.

## scripts/kcilib/run/callback.py

### Why both halves live here

A finished pull-lab job has exactly one durable output - the callback POST - so
the two halves of it live here rather than in each entry point:

* `lava_body()` assembles the **LAVA-compatible callback body**, the only
  format the pipeline's callback endpoint (`lava_callback.py` +
  `kernelci.runtime.lava.Callback`) ingests; there is no server-side parser for
  the PULL_LABS protocol body, so any other format would silently lose the
  result;
* `post_result()` delivers it and, crucially, *says what happened*: the
  "result posted" line belongs to a real 2xx and nothing else.

Both were moved out of `scripts/riscv_pull_worker.py` unchanged: the bodies,
the comments and the printed lines are byte-for-byte the same, and nothing had
to be renamed to become module-level.  The worker keeps its own policy - the poll
loop, the job mapping, the baked guest cache, the console archive and the
re-post-from-state rule.  `lava_body()` takes the two callback-metadata names
off a `kcilib.core.config.RunConfig` instead of an argparse namespace (phase
4); the configuration it reads did not change, only where it comes from.

### The three load-bearing behaviours (not to be "improved")

* A job definition without a callback URL raises `CallbackMissingURLError` (a
  subclass of the *transient* error) instead of returning quietly, so the caller
  keeps the result pending rather than logging "result posted" while the result
  exists nowhere (#3).
* A 4xx is permanent, a 5xx/network error is retried (3 attempts, with
  `time.sleep(2 * (attempt + 1))` between them) and then transient; both
  raise, so "not posted" can never look like "posted".
* The callback token comes from the environment at post time.  It is never a
  parameter of `lava_body()`, never a field of the body, and never written to
  the state file - `pending_entry()`/`report_from_pending()` are the round
  trip that keeps it that way (see `kcilib.core.state.StateFile`).

The judged verdicts are *inputs*, never re-derived here: `tap` is
`(label, summary, per_test)` - the `summary` and `per_test` halves of the
5-tuple `kcilib.run.judge.judge_run()` returns, paired with the test label
exactly as the worker's `run_node()` builds it - and `error_msg` is the
`detail` that goes with them.  This module never runs tuxrun, never parses TAP
and never reads a job definition.

### Constants

* `REQUEST_TIMEOUT = 60`: the same value the worker polls its APIs with.
* `LOG_LIMIT = 2 << 20`: cap of log text embedded in a result body.
* `SUITE_CASE_PREFIX = "0_kselftest."`: the suite case `lava_body()` files a
  kselftest run under (`0_kselftest.<suite>`); the prefix is what marks a case
  as the selftest verdict rather than a boot case.
* `LAVA_STATUS_INCOMPLETE = 3` (a job whose result could not be produced) and
  `LAVA_STATUS_COMPLETE = 2`.
* `CALLBACK_TOKEN_ENV`: the report tuple a caller posts is
  `(callback_url, token, body)`.  The callback URL is the one recorded in the
  job definition (`job.get("callback", {})` /
  `callback.get("url")`); the token is a "remote token" name shared with the
  pipeline admins, read from the environment every time it is needed and never
  persisted.

### lava_body()

Required pieces, mirroring a real LAVA server callback:

* `status`: LAVA numeric job status (2=Complete, 3=Incomplete);
* `definition`: YAML whose metadata carries `api_config_name` /
  `storage_config_name` (what `get_meta()` reads);
* `results.lava`: case/stage list; `login-action` and `kernel-messages` are
  replayed from tuxrun's own LAVA lines so boot results get the usual 'setup'
  hierarchy;
* `results.<suite>`: per-test entries keyed `0_kselftest.<collection>`; the
  parser builds a suite node whose children are the tests and flips the job to
  'fail' when any failed (tuxrun exits 0 even then);
* `log`: LAVA `output.yaml` format (list of `{dt, lvl, msg}`); without it
  the endpoint forces 'incomplete'.

`tap` is `(label, summary, per_test)` from `tap_summary()`; `infra` marks
an infrastructure error via the 'job' stage metadata (what
`Callback.is_infra_error()` reads).  `run_config` is a
`kcilib.core.config.RunConfig` and only two of its fields are read here: the
`api_config_name` / `storage_config_name` the callback definition metadata
must carry.  The body itself is a pure function of the verdicts - no HTTP, no
tuxrun, no state.

Inline rules kept in the code:

* TAP available = the job DID complete (tuxrun exits 0/1/2 by LKFT result
  plumbing); the per-test hierarchy drives the final result, so the job stays
  Complete unless this is an infra error.
* rc 0 without any boot case lines means the log does not show a real boot -
  never report that as pass.

### Reading a body back

* `_lava_cases()`: the case list is a YAML string inside the body (that is the
  format the pipeline's callback parses), so it is read back the same way.  A
  body that cannot be read yields no cases rather than an exception: a caller
  reading a verdict must not be able to break a run that already finished.
* `verdict_from_body()`: read back OUT OF the body on purpose - a record must
  agree with what was actually reported upstream, and the body is what upstream
  received.  Computing the verdict a second time from the console
  (`judge_run()`, which is the one-shot path's route) would be a second opinion
  about the same run, and the two are free to disagree; "the ledger says pass and
  the pipeline says fail" is precisely the confusion a durable record exists to
  remove.  status 3 is LAVA's Incomplete (no usable result: infrastructure), 2 is
  Complete, and a Complete job is not automatically a pass: tuxrun exits 0 even
  when every selftest fails, so the suite case carries the verdict.
* `_job_case_metadata()` is where an infrastructure failure names itself
  (`error_type` Infrastructure and the message the callback's
  `is_infra_error()` reads).  `_lava_case_dicts()` is the shape
  `_lava_cases()` flattens.

### The round trip and the errors

* `pending_entry()` drops the token on purpose: the state file holds the
  callback URL and the body only, and the token is re-read from the environment
  when the body is posted again (`report_from_pending()`).
* `CallbackPermanentError`: the endpoint rejected the result (4xx), retrying is
  pointless.  `CallbackTransientError`: network/5xx trouble, retry later.
* `CallbackMissingURLError` is deliberately treated as transient rather than as
  a give-up.  The run has already happened and its result is the only copy, so
  the caller keeps it in the persisted pending set and does not mark the node
  seen; an operator who fixes the job definition (or the deployment's callback)
  then gets the result posted instead of losing it.  The old code printed a
  warning and returned normally, so the caller went on to log "result posted to
  the callback" while the job stayed available forever and the result existed
  nowhere (#3).
* `post_result()` retries a few times because a single network blip must not
  lose a result, and raises instead of returning quietly so a caller can never
  mistake "not posted" for "posted".

## scripts/kcilib/run/jobrun.py

### Provenance and the API boundary

The middle of the worker's job path, moved VERBATIM out of
`scripts/riscv_pull_worker.py`: `build_command()` maps a job definition onto
a tuxrun argv (baking a disk rootfs out of a tarball artifact when the job
carries one), `run_command()` runs it and captures the console into the
workspace, `run_node()` drives the two and turns the outcome into a LAVA
callback body.  The console archive (`archive_console_log()` and
`prune_console_logs()`) travels with them because `run_node()`'s
`finally` is what keeps a real run's evidence alive past the per-job workspace
that held it (#6).

THIS MODULE DOES NOT KNOW THE API EXISTS.  `run_node(node, run_config)` takes
the job definition the events API served plus a
`kcilib.core.config.RunConfig` and returns the report tuple; fetching nodes,
the cursor and the flock are `kcilib.run.poll`'s business, and the poll loop
hands this function its config rather than this module reaching for anything
global.  A caller that has never polled anything (a replay of a saved job
definition, an offline test) can run a node with a RunConfig it built by hand.

### What it delegates, and why each seam stays

* The judging is `kcilib.run.judge`'s, and specifically the three predicates
  (`tuxrun_invocation_error` / `tuxrun_job_error` / `tuxrun_infra_error`)
  plus `tap_summary` and `tuxrun_error_message`.  NOT `judge_run()`: its
  timeout wording differs, and swapping it in would change the `error_msg`
  that reaches the callback for a timed-out job.
* The command line is `kcilib.run.runner.build_tuxrun_argv` (flag order, the
  rw boot-args rationale and the `--rootfs`/`--modules`/`--tests` omission
  rules live there) and the execution is `kcilib.run.runner.run_tuxrun` - the
  worker's `timeout_s + 180` grace, the workspace as cwd, and
  `stream_separator="\n"` so the console keeps its blank line where stdout and
  stderr meet.
* The guest image is `kcilib.run.bake.baked_rootfs_image`: the same bake and
  the same cache the worker used to own, so "guest prepared in Ns" and the bake
  cache lines are unchanged.
* The progress printer is imported from `kcilib.run.bake.stamp` instead of
  being copied a third time.  Its `[HH:MM:SS] ` line is byte-identical to the
  worker's own `stamp()`, and a caller that re-binds
  `kcilib.run.bake.stamp` - or this module's `stamp` - moves every line of
  this module with it, exactly as the offline guard tests re-bind module
  attributes.
* `run_node()` does NOT post the result: it returns the
  `(callback_url, token, body)` tuple and the poll loop posts it.  The token
  is read from the environment here and is never persisted
  (`kcilib.run.callback`).

Nothing was "tidied": the archived consoles under `work/logs`, the printed
lines and the state file are test fixtures.  Every string, comment and f-string
below is the worker's, character for character.  The worker's CLI
(`kcilib/core/cli.py`) and the flag -> field mapping
(`kcilib/core/config.py`) are the only things above this module; nothing here
reads a command line, and no field is named after a flag.

### Timeouts and the console archive

* `DEFAULT_TIMEOUT = 1800` is used when the job definition carries no
  `timeout_s`.
* The clamp used to be a silent `max(60, min(timeout_s, config.max_timeout))`:
  a definition asking for 1800s was cut to the 1200s the shell entry points pass,
  the job was killed at 20 minutes and reported as Infrastructure, and nothing in
  the log said the timeout had been reduced - indistinguishable from a job that
  genuinely needs more time.  Both bounds now have a name, a CLI flag and a line
  of their own the moment they bite (see `clamp_timeout()`).
* `MIN_TIMEOUT = 60` is the floor: below this tuxrun cannot even boot a guest.
* `LOG_ARCHIVE_KEEP = 200` and the #6 history: the console is written inside
  the workspace and the workspace is deleted at the end of every job, so the only
  local copy of a real run used to disappear with it - all that survived was the
  callback's `LOG_LIMIT`-capped copy, and nothing at all when the callback
  failed.  It is anchored to the repository root rather than the CWD, so "the
  logs are in work/logs" holds whatever directory the worker was started from
  (`work/` is the gitignored tree this repo already treats as durable).

### build_command()

* `runtime_name()` picks a container runtime tuxrun can drive (podman
  preferred, docker second).
* An explicit `--rootfs` overrides whatever the job definition carries: the lab
  owns its guest images (e.g. point at a local mirror when
  storage.kernelci.org is throttled).
* A job definition carrying a cpio ramdisk gets a warning: the qemu device
  cannot boot it, so tuxrun's built-in disk is used unless `--rootfs` overrides.
* `boot_modules`/`modules_url` are only set for `kselftest-kvm`.  Once the
  rootfs tarball has been baked, `modules_url` is dropped again: the modules
  are already inside the baked image and the `--modules` LAVA overlay lands
  after boot and cannot load `kvm.ko` at boot time.
* The curated subset instead of the whole collection: the LKFT script hands
  `TST_CASENAME` to `run_kselftest.sh -t`, which matches each `kvm:name`
  entry exactly (allow-list).  `kvm.ko` is loaded at boot because
  `modules.tar.xz` is baked into `/lib/modules` and a modules-load.d conf
  modprobes it (see `bake_rootfs_image()`).  The LKFT "modules" test is a
  load/unload round-trip and must NOT be used here - verified: it unloads kvm
  again before kselftest runs.  `--kvm-full` means the whole collection: no
  allow-list, LKFT runs every kvm test.  The curated list itself is
  `kcilib.core.params`' business, which is why an unmodified subset goes
  through `kvm_allow_list()` and anything else is joined here.

### run_command(), prune_console_logs(), archive_console_log()

* `run_command()` prints the command line, runs tuxrun with
  `timeout_s + 180` (a little grace past the job timeout) and the workspace as
  cwd, and returns `(returncode, output)`; `returncode` is None on a
  timeout and the partial output is still written to the log.
* `prune_console_logs()`: archiving every job's console is a real disk cost
  (one 25-minute kselftest console is hundreds of KB, and a resident lab runs
  hundreds of jobs a month), so the archive is bounded by count and pruned
  oldest-first - the same shape as `prune_bake_cache()`.  Only
  `<node id>.log` files this module writes are considered, so a hand-placed
  file in the same directory is never removed.
* `archive_console_log()` returns the archived path or "" when the job
  produced no console, and raises `OSError` when the copy itself fails so the
  caller can keep the workspace instead of deleting the last copy of the
  evidence.  The node id comes from the API and ends up in a filename, so it is
  reduced to characters that cannot escape the log directory.

### clamp_timeout()

Returns `(effective_timeout, note)`; `note` is "" when nothing was clamped.
Clamping a job definition's timeout is intended (a definition must not be able
to run forever), but it used to be silent: a definition asking for 1800s, cut to
the 1200s the shell entry points pass, was killed at 20 minutes and reported as
Infrastructure with nothing in the log saying the timeout had been reduced.
Both bounds are now named, both are CLI flags (`--min-timeout` /
`--max-timeout`) and every clamp is announced (#15).

### The ledger record

* `SOURCE_WORKER`/`SOURCE_TABLE`: the ledger's `source` field is
  documented as "which writer produced this row", and it was hardcoded to
  "worker" here - so a run started by
  `./run.sh run --source table` (the local job table, which never touches the
  events API) was filed as if the resident worker had taken it.  The field is
  only worth having if it is true.
* `record_result()`: `kcilib.core.ledger` owns the layout
  (`work/results/<build-id>/<test>.json`) and the key set; this function is the
  worker's NAMING of the run, and it is written for every outcome - a failed run
  is exactly the one worth having a record of.  Until the worker wrote records,
  `work/results/` held only the one-shot runner's rows, so a resident lab that
  had taken a hundred dispatched jobs had no history of its own.  The build is
  taken from the job's artifact URLs (a pull-lab job definition carries no build
  id, only URLs - see `artifacts.build_id_from_artifacts`); when no URL names
  one, the job node id stands in, and the record says so by naming the node in
  `job` - a record filed under a made-up id would be worse than one filed under
  a real node id.  The verdict comes from the callback BODY that was just built,
  not from a second look at the console (`callback.verdict_from_body`): the
  record and the pipeline must not be able to disagree about the same run.
  Failure to write is reported and returned as "", never raised: the run already
  happened and its result still has to reach the callback.
* `_relative_to_repo()`: the one-shot runner stores repository-relative paths
  in the same field, and a reader lining the two writers' rows up must not have
  to guess which is which.  (A path on a different drive on Windows is kept as
  given.)

### run_node()

* *node* is a job definition exactly as the events API served it and
  *run_config* is a `kcilib.core.config.RunConfig` - the two things a run needs,
  and the API is not one of them.  *node_id* labels the progress lines and names
  the archived console log.
* The callback token is a "remote token" name shared with the pipeline admins;
  the worker holds the secret in an env var
  (`PULL_LABS_CALLBACK_TOKEN`).
* The clamp note is announced once per job, before anything runs: the effective
  timeout is the number to look at first when a job comes back Infrastructure
  after a kill (#15).
* An infra error is reported with its reason for, e.g., kselftest-riscv before
  the tuxlava class lands upstream, artifacts the dispatcher container cannot
  reach, or the serial connection dying mid-run.  The reason is built for the
  callback's 200-character window instead of being sliced out of the tail of a
  7KB argparse line.
* For `kselftest-*` the TAP decides: tuxrun returns 0 even when selftests
  fail.  It is computed even on infra failures, so a suite that died mid-run
  keeps the per-test results it produced.
* Every other failure inside becomes an infra-error report (the broad
  `except`), so a report is always produced unless the workspace itself cannot
  be created.
* The `finally` block archives the console and decides whether to keep the
  workspace; when archiving fails the workspace is kept, because it is now the
  only surviving copy of the run and deleting it is exactly the evidence loss
  this archiving exists to stop (#6).  Otherwise the workspace (or the whole
  temp base the worker created) is removed unless `--keep-workspace` was
  passed.
* The durable record is filed next to the one-shot runner's rows, before the
  caller posts, so a callback that never lands still leaves a record of what ran;
  a failure to write is reported inside and never stops the report.

## scripts/kcilib/run/judge.py

### The exit-code contract

`judge_run()`'s `exit_code` IS the process exit status of the local runner,
and the same verdict LAVA reports for the worker's callback:

    0   pass: TAP produced, no selftest failed (or the guest booted)
    1   test failure: at least one selftest failed
    3   infrastructure: tuxrun never started (argparse error, LAVA job error),
        the console self-reports error_type Infrastructure, the run timed out,
        the guest never booted, or no TAP lines were produced at all

`EXIT_INFRA = 3` mirrors LAVA's job status 3 (incomplete): "the tests ran and
failed" vs "nothing ran at all".  `VERDICT_ERROR` ("error") is no verdict at
all - a stale artifact server, a truncated download, ...  tuxrun exits 0 even
when every selftest fails, so the TAP - never tuxrun's exit code - carries the
verdict (this function used to reach in through `importlib`).

`TUXRUN_TIMEOUT = 1800` is the local runner's tuxrun subprocess timeout,
quoted by `judge_run()`'s timeout detail so the message cannot name a timeout
other than tuxrun's.

### Regexes and constants

* `ANSI_RE`: CSI (`ESC [ params letter`), OSC (`ESC ] ... BEL/ST`)
  sequences, and stray C0 control characters; tab, LF and CR are kept (console
  text structure).
* `strip_ansi()` returns *text* itself when there is nothing to strip: an
  unconditional copy of a multi-megabyte console is pure overhead for
  bounded-window callers.
* `LAVA_CASE_RE` reads LAVA's own `'case': '...' ... 'result': '...'` lines.
* `BOOT_EVIDENCE_RE` is the guest's own console output - boot evidence that
  does not come from LAVA's "Wait for prompt [...]" chatter; a `--test boot`
  run has no TAP.
* `ERROR_MSG_BUDGET = 190` exists because the callback keeps only the last 200
  characters of `error_msg` (see `lava_body()`), so an infra reason has to
  fit in that window with its most useful part last.
* `ERROR_MSG_WINDOW = JOB_CASE_GAP + 4096` and `ERROR_MSG_TAIL = 4096` are
  windows, never whole-console copies: joining 14 MB of trailing output to make a
  190-character answer cost millions of token strings (+205 MB peak RSS).

### tap_summary()

tuxrun/LAVA report "job pass" even when a selftest fails, so the TAP lines must
be read here: any top-level `not ok` (or a started test that never reported)
makes the job fail.  Lines carry ANSI codes and timestamps, and `label` builds
the TAP marker - without one nothing matches (no pass).

The patterns tolerate whitespace splits and glued variants ("notok", "NOT OK",
"not\x1b[31mok", "not  ok"): the ok lookbehind keeps glued "notok" out of
`ok_m`, and the not_ok loop overwrites any split "not ok" with fail.  With no
TAP at all the suite never ran (a tuxrun job-level failure), which is never
reported as pass - the suite is marked failed so it surfaces as fail.  Results
are one entry per test name, last result wins (no count inflation).

### The infra classifiers

* `tuxrun_invocation_error()`: argparse-level failures (unknown test class,
  bad flag) exit 2 and print usage - an infra problem, not a test result.
* `tuxrun_job_error()`: a tuxrun run that never reached the tests - LAVA's own
  infrastructure marker ("cannot terminate cleanly": unreachable artifacts,
  corrupt images, invalid job data).  Genuine boot/test failures do not print
  that line.
* `_quoted()` builds a dict key/value marker in either quote style: a log line
  can be a plain Python repr, a JSON object, or the repr of a repr (LAVA embeds
  its own repr inside the message, doubling the backslashes).
* `JOB_CASE_GAP`/`JOB_CASE_INFRA_RE`: LAVA's authoritative verdict is a job
  case dict carrying `error_type` Infrastructure.  The gap between the two
  fields is BOUNDED but spans newlines, so the pattern reads a repr, a JSON
  object and a multi-line dict without letting the search wander across a
  multi-megabyte console.
* `INFRA_MARKER_RE` is the fail-safe, deliberately NOT distance-bounded: a
  case dict whose own text exceeds the gap (a very long `error_msg`) would fail
  to match, reporting a real infrastructure failure as an ordinary job failure
  (status 2, `error_type` Job).  As a plain substring search it can only *add*
  infra classifications.
* `is_infra_error()` checks them in that order so the reason matches the
  classifier; a timeout (no returncode) is `judge_run()`'s job.

### Building the reason for the callback's window

Neither tuxrun's argparse errors (one line whose choices list runs to thousands
of characters) nor LAVA's dispatcher verdict (a case dict) has its useful text in
the console's tail: reporting `output[-2000:]` produced
"md-analyze', ..., 'zlib')" for a run whose real problem was a missing test
class.

* `missing_test_hint()` names the documented one-time patch when tuxrun
  rejects a test name because tuxlava does not provide it: tuxrun builds
  `--tests` choices from tuxlava's registry, so a tuxlava without the riscv
  kselftest class fails as `invalid choice: 'kselftest-riscv'` - an
  unexplained infra error.
* `_condense()` collapses every whitespace run (spaces, newlines, CRLF) into
  one space.  `_repr_unescape()` undoes the backslash escapes of a repr'd log
  line, on a bounded window only.
* `_clip_head()` keeps the HEAD: argparse names the problem in its first words,
  and the choices list after it is dropped separately.  `_clip_tail()` keeps
  the TAIL: an unrecognised failure's reason is printed last.
* `_clip_reason()` keeps BOTH ends of a reason that does not fit: the failure
  mode is the END of a reason ("...: Read timed out.") while the head names the
  artifact that failed, and the callback keeps only the last 200 characters sent
  - `message[:budget]` reported node `6aa387ecba3aeacda180ff12` as
  "HTTPSConnectionPool(host='files." alone.
* `_compose()` attaches the actionable *hint* LAST and intact, inside
  `ERROR_MSG_BUDGET`: the callback keeps the LAST 200 characters, so the hint
  - the one-time tuxlava patch - must never be truncated (capping it at half
  dropped the path).  With a hint the redundant " (invalid test name)" marker is
  dropped, because its 21 characters are what the intact hint needs.  A
  pathological class name leaves only the hint, and its own tail (the patch path)
  is the actionable part.
* `_verdict_reason()` reports the dict's own `error_msg` field, which is the
  authoritative reason: a 190-character prefix of the whole dict spends the
  budget on scaffolding instead of on the failure (a download timeout reported as
  a URL fragment).  The window reaches *before* the verdict as well as after it,
  because LAVA does not fix the field order - the candidate nearest the verdict
  wins (`_closest()`).  A doubly-escaped repr is re-tried in plain form.
* `tuxrun_error_message()` has three sources, in order of authority: the first
  `tuxrun: error:` line with the choices list dropped; the LAST job-case
  Infrastructure verdict (only the final attempt counts), whose own
  `error_msg` is reported rather than a prefix of the dict; and a bounded
  console tail.  `label` is kept for the callers' sake: the reason does not
  depend on it.

### judge_run()

TAP parsing is `tap_summary()`, not a second weaker copy (#23): tuxrun exits 0
even when every selftest fails, so it is authoritative (its `total=0` encoding
is the "suite never ran" case, #2).  `returncode` is None on timeout.  With no
TAP at all it is never a pass: a non-zero exit is reported as infrastructure
("the guest never booted or the suite never started") and exit 0 as a failure
("tuxrun exited 0 but produced no TAP lines at all").  boot has no TAP, and the
exit code alone is not a verdict (`lava_body()` also refuses a run with no boot
evidence a pass), so boot output is required - a failed boot case is a test
failure, and exit 0 with no boot evidence at all is infrastructure.

## scripts/kcilib/run/poll.py

### Provenance

Moved VERBATIM out of `scripts/riscv_pull_worker.py`: `poll_loop()` (the
flock, the per-event flush, the cursor rule and `--once`), `handle_event()`
(the node-state re-check, the dedup/re-post of a cached report and the callback
POST), `retrieve_job_definition()`, `fetch_nodes()`, `start_cursor()`,
`iso_ago()` and `_latest_base()`.  The bodies, the comments and every
printed line are the worker's; only the imports and three expressions that had
to become module-level names changed.

THIS IS THE ONLY LAYER ON THE RUN PATH THAT TALKS TO THE EVENTS API: where the
nodes come from (the events API, the node-status re-check before a run) is here;
RUNNING one is not, and it is not this module's to look up either.  It is no
longer the only module in the repository that knows an API exists:
`kcilib/api.py` is the one HTTP client, and the local job table's reads go
through it too (docs/ARCHITECTURE.md, "three lines").

    poll_loop(poll_config, run_node, run_config)

The loop is handed the run function and its config, so it can run a node without
importing the run path at all - the interval, the retries and the cursor are
`poll_config`'s fields, and `poll_config` is a value, not a module global.
That is also what makes the run path testable on its own: `handle_event()`
calls the `run_node` it was given, so a test injects a stub instead of
patching an import.

### What it delegates

* `kcilib.core.state.StateFile` owns the state file - the cursor, the seen set
  and the pending reports are one document written atomically after EVERY event
  (#9), and a corrupt file is refused loudly and replaced by an empty state.
* The run itself is the caller's *run_node* (`kcilib.run.jobrun.run_node`),
  called as `run_node(node, run_config, node_id)`; it returns the
  `(callback_url, token, body)` tuple and this module posts it.  Passing it in
  keeps this module from having to know how a job is executed - and keeps the run
  path from having to know that an events API exists.
* `kcilib.run.callback` owns the post (`post_result`) and the pending round
  trip.  The two expressions that changed: the startup rebuild of `reports` is
  now `report_from_pending(pending)` and the flush writes
  `pending_entry(report)` - the same `{"callback", "body"}` dict in the same
  key order, and the same environment read for the token.  The token is never
  persisted: the state file holds the callback URL and the body only, and the
  token is re-read from `PULL_LABS_CALLBACK_TOKEN` whenever a body is posted.
* The progress printer is `kcilib.run.bake.stamp` (the shared
  implementation), byte-identical to the worker's own `stamp()`; this module
  keeps no copy.

### The two load-bearing behaviours

"Result posted" is printed only after `post_result()` returned without raising,
i.e. after a real 2xx (a 4xx, a 5xx, a redirect or an unreachable endpoint
raises and the body stays pending), and the cursor only advances once a whole
batch succeeded - `--since` seeds a state file that has no cursor,
`--ignore-state-cursor` forces it.  `poll_config` is a
`kcilib.core.config.PollConfig`: `api_url`, `state_file`, `since`,
`once`, `poll_period`, `max_retries`, `ignore_state_cursor` and the
platform/runtime filters.  The defaults and the flag they come from live in
`kcilib/core/cli.py` and `kcilib/core/config.py`; nothing here reads a
command line.  `CURSOR_OVERLAP_S = 900` is the re-scan window, because the
events API is not sorted.

### Fetching

* `_latest_base()`: KernelCI serves its API under `/latest`; the local dev
  API accepts both forms, production only the `/latest` one, so always target
  the canonical base regardless of what the user passed.
* `fetch_nodes()` is the events API call and nothing else
  (`state=available&kind=job&limit=1000&recursive=true&from=<timestamp>`);
  a non-JSON body becomes a `RequestException`.
* `retrieve_job_definition()` refuses a redirect, and applies the same rule as
  the node API (#11): a non-JSON body (proxy error page) or a JSON body of the
  wrong shape is a transient fetch error, so the node is retried - not an
  unexpected exception that gives up on the node and marks it seen with its
  result never produced.

### handle_event()

A node whose execution already produced a report is retried by re-posting that
report only - tuxrun is never re-run for the same node.  It returns True when
the event is fully handled (or deliberately given up on) so the caller may mark
it seen.  The API layer knows the API, `run_node` knows tuxrun, and neither
imports the other.

* The events stream returns historical snapshots (state at event time); a node
  may have been taken/run since.  Only jobs that are still available NOW are
  acted on, so a fresh worker never replays yesterday's queue.
* The node-state re-check: a proxy's HTML error page is not JSON, and
  `.json()` used to be called straight on the response, so a 502 page from a
  reverse proxy raised `json.JSONDecodeError` (a ValueError) which nothing
  here, at the call site or in `poll_loop()` caught: one bad response killed
  the whole worker while the lab was running (#11).  Now it is an ordinary API
  error - log, do not handle this event, retry on the next poll.  A
  well-formed JSON body of the wrong shape (a list, a string) must not turn into
  an `AttributeError` that kills the poll loop either.
* A node with no HTTP `job_definition` artifact URL is not a pull_labs job:
  nothing to do.
* The platform/runtime filters skip a job whose `data.platform` /
  `data.runtime` differs.
* The cached-report path: a permanent callback failure deletes the cached report
  and gives up on the node; a transient one keeps it pending and returns False so
  the next poll retries the POST (never a re-run).
* The job-definition fetch and `run_node` call: a <500 status gives up on the
  node (it will not fix itself), anything else transient is retried next poll,
  and any other exception is logged with a traceback and given up on - since
  `run_node()` converts its own failures, the rest are unexpected.

### The cursor

`_parseable_iso()` guards `iso_ago()`: a state file hand-edited into
nonsense would otherwise reach `datetime.fromisoformat` and raise ValueError,
killing the worker at startup - far away from the file that caused it.

`start_cursor()` decides which timestamp the first poll scans from, and says
which one it is.  The persisted cursor is authoritative by default (#8).  Every
entry point passed `--since` (`run.sh`: the current day's 00:00) and the CLI
value used to win over the stored cursor, so a worker started the next day never
looked back at a job that arrived yesterday and is still `available`: it sat
in the queue forever with no error anywhere.  `--since` is now the bootstrap
cursor - used only when the state file has none - unless the operator asks for
the override deliberately with `--ignore-state-cursor`.

### poll_loop()

* *poll_config* is a `kcilib.core.config.PollConfig`; *run_node* is the run
  function and *run_config* its config, both passed through to
  `handle_event()` - the loop never runs a job itself.
* The flock: a second worker instance prints "Another worker instance holds the
  lock; exiting." and raises `SystemExit(1)`.
* Which cursor wins is `start_cursor()`'s decision, and it says so on stdout:
  the operator needs to know whether this run scans from the persisted position
  or from `--since` before reading anything else (#8).
* Unposted results left over from a previous run (e.g. `--once` exiting on a
  transient callback failure) are re-posted without re-running tuxrun; the token
  is re-read from the environment and never persisted - the document
  `StateFile` writes holds the callback URL and the body only.
* `flush()` writes the cursor and the unposted reports out now, after EVERY
  event, not once per batch (#9): a worker killed after a transient callback
  failure but before the batch ended used to lose the in-memory report, the
  pending entry and the seen update, so the next start re-ran tuxrun for a node
  whose result it already had.  `StateFile.save()` owns both guards that keep
  that honest rather than expensive (a re-entrancy flag and a comparison against
  the document on disk).
* `flush_and_exit()` is the SIGTERM/SIGINT handler: a signal must not cost the
  results already collected.
* The events API is not sorted and can deliver events out of order, so a
  trailing window is re-scanned and deduped via `seen` - a cursor that only
  ever advances would silently skip late events.
* The retry budget is `poll_config.max_retries`; when it is exhausted the
  worker exits 1.  An empty batch sleeps for `poll_config.poll_period`.
* Only nodes that were actually processed are marked seen: the first event for a
  node may arrive before its `job_definition` artifact is attached (e.g. create
  then update), and `handle_event()` skips such events silently - marking them
  seen would hide the later, complete event.
* One flush per event, in a `finally` so it also runs for an event that raised:
  whatever `handle_event()` already changed (a node marked seen, a result
  queued for re-posting) survives a crash or a kill from here on (#9).
* The cursor advances only when the whole batch succeeded, so a failed job is
  retried next poll; a failing batch also sleeps before the next poll, because
  the API needs a breather and the failure is usually environmental (a 404
  jobdef, the network).
* The final flush persists the advanced cursor; the per-event flushes above
  already persisted the seen/pending mutations.  `--once` prints where the
  cursor and any unposted result now live, then exits.

## scripts/kcilib/run/runner.py

### Why the single copy

Two entry points drive tuxrun: `scripts/riscv_pull_worker.py`
(`build_command` + `run_command`) and `scripts/fetch-and-run-latest.py`
(`run_once`).  Both assembled the same argv in the same order and both turned
tuxrun's two output streams into one console, so the assembly and the execution
live here instead of twice.

### Preserved verbatim from those callers - do not "tidy" any of it

* `argv[0]` is the tuxrun executable, followed by `--runtime`,
  `--device`, `--kernel`, `--boot-args`, `--rootfs`, `--modules`,
  `--tests`, `--parameters` in exactly that order.
* Each `--parameters` value is its own argv entry and is never joined into one
  string: a value may itself contain spaces
  (`TST_CASENAME=kvm:a kvm:b` is ONE entry), and `" ".join(argv)` is what
  both callers print and what the archived consoles in this repo show.
* `--modules` is only ever passed for the kvm case; the *caller* decides (the
  worker drops it again when the modules are baked into the image).
* stdout and stderr are captured separately and concatenated afterwards, never
  interleaved - see `run_tuxrun()`.

Nothing in this module prints.  The worker prints `Running: <cmd>` and
fetch-and-run-latest prints `running: <cmd>`; those two literals differ, so
they stay where they are.

### build_tuxrun_argv()

The keywords are explicit and keyword-only so both callers can pass their own
variables straight through with no reshaping.  The two call shapes:

    # the worker path (kcilib.run.jobrun.build_command): device is
    # run_config.platform, runtime is runtime_name(run_config), kernel is the
    # job's kernel artifact, tests is the collection list, and the kvm subset
    # travels as ONE "TST_CASENAME=kvm:a kvm:b" parameter entry
    build_tuxrun_argv(
        tuxrun_bin=run_config.tuxrun_bin, runtime=runtime_name(run_config),
        device=run_config.platform, kernel=kernel_url, boot_args="rw",
        rootfs=rootfs_arg, modules=modules_url, tests=tests,
        parameters=parameters)

    # scripts/fetch-and-run-latest.py (run_once): the executable is the module
    # constant TUXRUN, the device is fixed at qemu-riscv64, kernel and rootfs are
    # URLs served by its own artifact server, TST_CASENAME is again one
    # space-joined entry, and "args" is that script's OWN parsed command line
    # (phase 4 moved the worker onto kcilib.core.config.RunConfig and left the
    # one-shot fetch path on its own argparse namespace)
    build_tuxrun_argv(
        tuxrun_bin=TUXRUN, runtime=args.runtime, device="qemu-riscv64",
        kernel=f"{base}/Image", boot_args="rw",
        rootfs=f"file://{os.path.abspath(rootfs)}",
        modules=modules and f"{base}/modules.tar.xz",
        tests=TESTS[args.test], parameters=params)

Omission rules, exactly as in the callers: `boot_args` defaults to "rw" and
both callers pass "rw" literally; `--rootfs` is omitted when rootfs is falsy
(the boot job with no rootfs), `--modules` when modules is falsy, and
`--tests` when tests is falsy (the boot case: neither caller passes
`--tests` at all).  `--parameters` is omitted when `parameters is None`; a
list is passed through unchanged, empty list included, because both callers
append the flag unconditionally - so an empty list still reaches tuxrun, which
rejects it loudly, instead of the flag disappearing silently.

Inline rationales:

* `--boot-args rw`: Debian images (e.g. trixie-kselftest) ship an
  UNCONFIGURED fstab with no root entry, so the kernel mounts / read-only and
  systemd never remounts it; the LAVA test shell then dies with "Read-only file
  system" when writing results.  rw is harmless for images that remount
  themselves (buildroot).
* An explicit `--rootfs` overrides whatever the job definition carries: the lab
  owns its guest images (e.g. point at a local mirror when storage.kernelci.org
  is throttled).
* `modules.tar.xz` is only needed by kselftest-kvm (kvm.ko loaded at boot).
  For boot/kselftest-riscv it is a needless 100MB+ download that adds a flaky
  network dependency per job - skip it.
* A bare string would splat into one `--tests` entry per character: a silently
  wrong command line is worse than refusing, and the callers pass a list.

### run_tuxrun()

Same execution as both callers:
`subprocess.run(argv, capture_output=True, text=True, check=False)`, so tuxrun
is never run through a shell and a non-zero exit is a value, not an exception.

* `timeout`: passed straight to `subprocess.run`; None means no timeout.
  The worker passes `timeout_s + 180` (a little grace past the job timeout) and
  fetch-and-run-latest passes `TUXRUN_TIMEOUT` - the grace is the caller's
  business, not this function's.
* `cwd`: working directory for tuxrun; None inherits the caller's, which is
  what fetch-and-run-latest does.  The worker passes its per-job workspace.
* `stream_separator`: the text placed between captured stdout and stderr when
  the run COMPLETES.  Both callers concatenate the two streams instead of
  interleaving them, so a byte-for-byte identical console needs their exact
  separator: the worker writes `f"{proc.stdout}\n{proc.stderr}"` (the default
  here) and fetch-and-run-latest writes `proc.stdout + proc.stderr` (pass "").
  The difference is real and visible in this repo's own artifacts: the archived
  consoles under `work/logs/` carry one blank line where the streams meet, the
  fetch-and-run-latest consoles under `work/downloads/<build>/` carry none,
  because tuxrun's LAVA console goes to stdout and its urllib3 warnings
  ("403 Client Error: ...") go to stderr.  The timeout path needs no such knob:
  both callers spell it `f"{error.stdout or ''}\n{error.stderr or ''}"`, which
  is what happens here unconditionally.
* `log_path`: when given, the merged console is written there with
  `open(log_path, "w")` - the same file both callers write today, partial
  output included on a timeout.  Missing parent directories are not created,
  exactly as before: a caller that hands over an unusable path gets an OSError
  rather than a run whose console vanished.  Nothing is printed: the two callers
  log the command line themselves and with different wording.
* The returned CompletedProcess has `returncode` None on a timeout
  (`TimeoutExpired` is swallowed here because that is what both callers do, and
  a timed-out run is an infrastructure failure, not a test failure), `stdout`
  the merged console - the same bytes written to `log_path`, and what the
  callers hand to `tap_summary` / `judge_run` - and `stderr` empty, because
  the two streams were merged as they were captured.

### _write_console_log()

Shared by both exits of `run_tuxrun()`: a run that timed out still produced a
partial console worth keeping (#2), so neither path may skip the write.
