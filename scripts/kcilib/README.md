# scripts/kcilib/

The library of the RISC-V pull-lab scripts. The split follows the three lines
this repository actually runs (two run paths and one local table):

    core/       what all three lines stand on: the CLI, the config objects, state
                file, the result ledger, the host-port probes, the test params
    run/        ONE job: definition -> tuxrun argv -> artifact delivery -> run
                -> verdict -> callback body / ledger row
    sink.py     where a result goes: the ledger (always) and the callback (only
                when the job definition carries a URL)
    api.py      the one KernelCI API client - every reader goes through it
    table/      the local job table: which builds exist, which tests each one
    source.py   still needs, and how a row becomes a job definition

`core/` and `run/` are what the **two run paths** share
(`scripts/riscv_pull_worker.py`, `scripts/fetch-and-run-latest.py`).
`api.py` + `table/` + `source.py` serve the **local job-table line** instead
(`./run.sh build|jobs|todo|summary|run`, `./run.sh dashboard`): they are not part
of either run path, and the worker never imports them. An earlier version of this
file called the whole package "the library the two run paths share"; that stopped
being true when this cluster moved in, so the three lines are named separately
here (and `sink.py` belongs to all of them: the ledger is the one exit that
always exists).

Import it with `scripts/` on `sys.path` (each entry point inserts it from its own
directory, e.g. `scripts/riscv_pull_worker.py:74-78`):

    from kcilib.core import config
    from kcilib.run import judge, runner
    from kcilib.run.jobrun import run_node
    from kcilib.run.poll import poll_loop

The pre-layering spellings (`from kcilib import judge`, `from kcilib.jobrun import
run_node`, `kcilib.poll`) no longer import: the modules moved into the
subpackages and nothing re-exports them.

Five programs use the library: `scripts/riscv_pull_worker.py` (a resident
poller), `scripts/fetch-and-run-latest.py` (a one-shot runner),
`scripts/local-jobs.py` (the local job table), `scripts/dashboard.py` (its web
view) and `scripts/results.py` (the reader of the result ledger). The offline
tools use it too: `scripts/tools/verify-worker-guards.py`,
`scripts/tools/verify-lava-body.py`, `scripts/tools/config_drift.py` (the API
client only) and `scripts/tools/regression_tracker.py`.

The full picture - layer diagram, data flow, invariants, where state lives, the
rebinding seams and a "how do I ..." section - is `docs/ARCHITECTURE.md`.

## Module index

One line per module: what it owns, its public API, and the contract it enforces.
The module names are relative to `scripts/kcilib/`.

### The API client and the sources (the local job-table line)

| Module | Public API | Owns | The contract it enforces |
|---|---|---|---|
| `api.py` | `KernelCI`, `client()`, `APIError`, `node_counts()`; `PRODUCTION_API`/`LOCAL_API`, `PAGE_LIMIT` | The ONE KernelCI client: the `/latest` prefix, `{items,total,offset}` pagination, JSON-or-error, and the redirect-refusing job-definition fetch.  `node_counts()` is what `local-jobs summary` and `dashboard` both read (it returns None when the API is down, which is the contract those callers need) | It exists because the same three functions had been written out five times, each with its own pagination and retry story - and a missing page is indistinguishable from "no such build". It borrows upstream's *conventions*, not its client: these scripts stay standalone (`./run.sh fetch` needs "no stack, no node, no token"). `get()` retries a connection error and otherwise raises requests' own exceptions, so `run.poll`'s existing handlers keep working |
| `source.py` | `JobSource`, `TableSource`, `NewestSource`, `SOURCES`, `get_source()` | "What should run right now", as an object: `TableSource` = local index − ledger, `NewestSource` = the newest usable production build | A source may only say *what* to run: it must not run anything and must not import the execution layer, which is what keeps "where a job comes from" and "how a job is run" independently replaceable. events (the worker) is deliberately **not** a source - polling, the cursor, dedup, the flock and re-posting are a resident state machine, not a `jobs()` iterator |
| `table/buildref.py` | `BuildRef`, `build_ref_from_node()`, `BuildQuery`, `build_refs_from_nodes()`, `fetch_nodes()`, `builds_from_production_api()`; `ARTIFACT_KEYS`, `REQUIRED_FOR` | A build's stable identity (the id parsed out of its artifact URLs, plus tree/commit/describe) and the artifact addresses the run layer needs | The node id is **not** an identity (the local and the production API mint unrelated ones for the same build), so the key is the build id from the artifact URLs. `BuildRef` carries only what it takes to run, because it is stored in the index: the index is an index, not a second copy of the node. `source` is the one field this layer owns |
| `table/jobspec.py` | `JobSpec`, `jobs_from_build()`, `job_definition()`, `test_of()`; `DEFAULT_TESTS`, `TEST_TIMEOUTS` | The row (build × test × timeout) and the job definition the run layer is handed | `JobSpec` has three fields on purpose - it is the intent, not "how to run". `job_definition()` renders the same field names as the upstream `pull_labs.jinja2`, so `run_node` cannot tell (and must not care) whether a definition came from the API or was built here; the only difference is whether it carries a callback URL, and that is what makes "run one of my own jobs" and "run one the pipeline dispatched" the same thing at the execution layer |
| `table/buildindex.py` | `BuildIndex` (`add`/`add_all`/`get`/`all`/`newest`/`count`) | The local sqlite index of runnable builds (`work/builds.db`, keyed by build id) | It stores only the columns that answer "can this be run", plus the one field it owns (`source`: official or local); every write is idempotent (`add()` returns `False` for a known build id) so a re-index is not a duplicate. `work/` is gitignored: deleting the file loses no upstream data |
| `table/localrun.py` | `ran_tests()`, `todo()` | The views over the table ("what have I not run yet") | `ran_tests()`/`todo()` are pure reads - the ledger answers "did this machine run it", the API answers "what does upstream think", and only the ledger answers it offline. The execution shell that used to live here (`run_job()`/`outcome_from()`, wrapping `kcilib.run.jobrun.run_node`) was deleted on 2026-09-18: the interface layer (`scripts/kci/`, `Jobs`/`Job.run()`) had taken it over and what remained had no caller but a guard - and keeping it would now mean this package importing upward into `kci` |

### The exit (`sink.py`)

| Module | Public API | Owns | The contract it enforces |
|---|---|---|---|
| `sink.py` | `sinks_for(definition)`, `deliver(sinks, definition, outcome=None, report=None)`, `Sink`, `LedgerSink`, `CallbackSink`, `SINKS`, `has_callback()`; `LEDGER`/`CALLBACK` | "Where a result goes", as an explicit pluggable thing: the one decision point (`sinks_for()`), the ledger sink that is always present, and the callback sink that exists only when the job definition carries a callback URL | The decision is made from the **job definition** (what the run layer actually sees), never from an argparse value or the caller's wish; the ledger is unconditional because it is the only exit that needs no service, no token and no URL - and a failed run is the one worth recording. A sink re-implements no failure policy (the callback's 4xx/5xx rules stay in `run/callback.py`) and never writes the ledger a second time: the ledger sink *fetches back* the record the execution layer wrote, because that record is the complete one |

### `core/` - what both lines stand on

| Module | Public API | Owns | The contract it enforces |
|---|---|---|---|
| `core/cli.py` | `build_parser()`, `parse_args(argv=None)` | The worker's flags, defaults-by-reference, and the `--min-timeout`/`--max-timeout` cross-check | Argparse's own bytes: `--help` and every argparse error are what they always were, and the check reports itself with usage + exit 2 |
| `core/config.py` | `RunConfig`, `PollConfig`, `Configs`, `from_args()`, the `DEFAULT_*`/`LOG_DIR`/`MIN_TIMEOUT`/`LOG_ARCHIVE_KEEP` constants | The two config objects and the ONLY CLI -> config mapping (the one-shot runner builds the same `RunConfig` itself, from the flags it keeps for its own deployment); `LOG_DIR` anchored to the repository, not the CWD | No module below reads a command line; the dataclass defaults ARE the CLI defaults, so the two readers cannot drift. `runtime` is deliberately NOT a field - that is the *lab* filter and lives in `PollConfig`; the container runtime is `RunConfig.container_runtime`. `MIN_TIMEOUT`/`LOG_ARCHIVE_KEEP` live here (with the flags that carry them) rather than in `kcilib.run.jobrun`, which used to make this module import the run layer; `jobrun` imports them from here and keeps re-exporting the names |
| `core/state.py` | `StateFile` (`load`/`save`/`mark_seen`/`has_seen`/`add_pending`/`pop_pending`), `SEEN_LIMIT` | The persisted `{timestamp, seen, pending}` document and its atomic write | The document shape is a contract (operators hand-edit it); a corrupt file is refused loudly and never trusted; the save is atomic, re-entrancy-safe and skipped when nothing changed |
| `core/ledger.py` | `write_result()`, `read_results()`, `list_builds()`, `result_path()`, `test_of()`, `results_dir()`, `RESULT_FIELDS` | The durable `work/results/<build-id>/<test>.json` record, written by both run paths; and, since the test name is a component of that path, the ONE owner of "what is this job called" | Every outcome is recorded (a failed run is the one worth having), the key set is closed - an unknown field raises rather than being dropped - and a record is written by temp file + rename. `test_of()` never raises: a malformed `tests[0]` is `"boot"`, because the run path calls it outside `run_node`'s error handling, where a raise marked the node seen with its callback never posted. `source` names the writer (`fetch` / `worker`); the root is `work/results` or `$KCI_RESULTS_DIR` (the guard suite redirects it rather than dirtying the repo); `scripts/results.py` is the reader |
| `core/retention.py` | `plan()`, `prune()`, `served_build()`, `recorded_commit()`, `download_entries()`, `main()` (`python3 -m kcilib.core.retention`) | Which fetched builds `./run.sh prune` keeps: the newest `--keep`, plus the one `work/env/build.env` records and `work/serve/Image` serves | `plan()` returns the table it prints AND the removals it performs, so a `--dry-run` and a real run cannot disagree about which build is which; it is the only path that deletes a user's retained data (`work/downloads/`; `jobrun`/`fetch` only `rmtree` a per-job temp workspace they made themselves), which is why it is not a heredoc in `run.sh` any more (the guards import `kcilib` and nothing else). `run.sh` keeps the flags and their validation |
| `core/ports.py` | `port_is_free()`, `port_holder()`, `require_port_free()`, `main()` (`python3 -m kcilib.ports`) | Host-port probes: the bind test, the best-effort holder, the refusal text | Binding is the only honest test; a port published by our own compose project is not a conflict; a refusal names the port, the holder and the `KCI_*` variable that moves the deployment. `scripts/run-local-stack.sh` probes through the command line (with `--host 0.0.0.0`, because the stack binds 0.0.0.0), so the stack and the one-shot runner share one implementation instead of two that already disagreed |
| `core/params.py` | `KVM_SKIP_TESTS`, `cpu_for()`, `kvm_tests_to_run()` | The curated KVM exclusion list and the cpu property string | Both entry points run the same thing: one list, one spelling (`"kvm:name kvm:name ..."` as ONE `--parameters` entry). It is an EXCLUSION list - everything the build's own kselftest tarball ships minus `KVM_SKIP_TESTS` - so a test an older kernel never built is absent instead of failing the suite with "No such test" |

### `run/` - one job, from a definition to a body

| Module | Public API | Owns | The contract it enforces |
|---|---|---|---|
| `run/poll.py` | `poll_loop(poll_config, run_node, run_config)`, `handle_event()`, `fetch_nodes()`, `retrieve_job_definition()`, `start_cursor()`, `iso_ago()` | The events API, the node-state re-check, the job-definition fetch, dedup and re-post, the cursor rule, the flock, the batch loop, and the result POST | The only layer of the run path that knows the events API exists; it never imports `run.jobrun` - the run function is injected. Its three HTTP calls go through this module's own module-level `requests` (a registered rebinding seam), NOT through `kcilib.api.KernelCI` - that client serves the table line, the interface layer and the tools (since 2026-09-18 `node()`/`job_definition()` are `scripts/kci/nodes.py`'s `JobPuller` readers; only `events()` still has no production caller). Anything this path raises for a fetch must stay a `requests.exceptions.RequestException`: `handle_event` converts exactly that into "retry next poll", and everything else falls through to its last `except`, which marks the node seen with its result never posted (guarded by `test_job_definition_failure_is_transient`). The persisted cursor is authoritative; every event flushes state; "result posted" is printed only after a real 2xx |
| `run/jobrun.py` | `run_node(node, run_config, node_id=None)`, `record_result(node, node_id, body, tap, log_path)`, `build_command()`, `run_command()`, `clamp_timeout()`, `archive_console_log()`, `prune_console_logs()`, `runtime_name()` | Job definition -> tuxrun argv -> run -> verdict -> callback body, the per-job workspace, the console archive, and the run's record in the ledger | The only layer that runs a job, and it knows nothing about the API; the console is archived before the workspace is deleted (and the workspace is kept if archiving fails); a timeout clamp is always announced; the record is read back out of the callback body this layer just built - not out of a second look at the console - and a record that cannot be written warns, never fails the job. Where a result goes is read through `kcilib.run.callback`'s `callback_url()`/`callback_token()` (the same helpers `sink.CallbackSink.wants()` uses), never re-derived here; the test name a record is filed under is `kcilib.core.ledger.test_of()` |
| `run/judge.py` | `judge_run()`, `tap_summary()`, `strip_ansi()`, `is_infra_error()`, `tuxrun_invocation_error()`, `tuxrun_job_error()`, `tuxrun_infra_error()`, `tuxrun_error_message()`, `missing_test_hint()`, `EXIT_*`/`VERDICT_*` | The verdict vocabulary and exit codes (0 pass / 1 test failure / 3 infrastructure), the TAP parser and the infra predicates | tuxrun's exit code is never the verdict; no TAP is never a pass; an infra `error_msg` is built to fit the callback's 200-character window with its actionable tail intact |
| `run/runner.py` | `build_tuxrun_argv(...)`, `run_tuxrun(...)` | The tuxrun argv layout and omission rules, and the single execution wrapper | argv order and one-entry-per-`--parameters` value are fixed (a joined string is what both callers print); a timeout is a return value, not an exception; the partial console survives a timeout; stdout and stderr are concatenated, never interleaved |
| `run/callback.py` | `lava_body()`, `verdict_from_body()`, `post_result()`, `pending_entry()`, `report_from_pending()`, `callback_url()`, `callback_token()`, `Callback{Permanent,Transient,MissingURL}Error` | The LAVA-compatible body, the verdict read back out of that body, and its delivery | The callback token is read from `PULL_LABS_CALLBACK_TOKEN` at post time and is never persisted (pending entries carry URL + body only); a 4xx is permanent, a 5xx is retried then transient, and "not posted" can never look like "posted" |
| `run/artifacts.py` | `download()`, `build_id_from_artifacts()`, `publish_complete_part()`, `gzip_isize()`, `looks_complete()`, `MAX_DOWNLOAD_SIZE`, `DOWNLOAD_TIMEOUT` | Resumable, size-checked artifact transfer, and the build id recovered from a job's artifact URLs | A partial transfer is never lost (it stays as `<dest>.part` with a sidecar naming its URL) and never trusted blindly: a file is reused only once it is proven complete |
| `run/delivery.py` | `fetch()`, `download()`, `provision_kernel()`, `ensure_artifact()`, `ensure_kernel_image()`, `check_consistency()`, `served_size()`, `start_artifact_server()`, `stop_artifact_server()`, the manifest helpers; `ArtifactServerError`, `MANIFEST_PATH` | The artifact transfers the `local_server` way needs (download, prove the size, serve it over HTTP on the host) and the record that says a cached file is complete | The two ways artifacts reach the guest live in two modules, not behind a mode switch here: `in_container` is `kcilib.run.jobrun.build_command` handing tuxrun the URLs, `local_server` is these helpers, and it is the caller that names which one it wants. A cached file counts as complete only when a recorded size, a `Content-Length` or the gzip trailer proves it; a downloaded file that does not match is downloaded again rather than booted; and the size the server actually hands out must equal the size on disk, checked through the very port tuxrun will read - booting a truncated or different kernel while reporting the build that was asked for is the hardest failure on this path to notice. `start_artifact_server()` raises `ArtifactServerError`, never `SystemExit`: a resident worker must lose a job to a busy port, not the daemon; `scripts/fetch-and-run-latest.py` is the entry point that turns it back into the process exit status it always had |
| `run/bake.py` | `baked_rootfs_image()`, `bake_rootfs_image()`, `cached_rootfs_image()`, `publish_baked_image()`, `prune_bake_cache()`, `bake_cache_dir()`, `cache_dir_writable()`, `bake_cache_inputs()`, `bake_cache_key()`, `disk_size_bytes()`, `stamp()` | The nfsroot tar.xz -> bootable ext4 bake (with `modules-load.d` for kvm), the bounded baked-image cache, and the shared progress printer | The cache key covers every bake input (a changed URL never reuses an entry); a published entry is one rename plus a sidecar written last; caching is an optimisation and never fails a job |

## Testing seams

The guard tests patch the module that OWNS a behaviour, never a re-export
(`scripts/tools/guards/runner.py`, the ordered list of all checks). Module attributes that exist to
be re-bound: `bake.stamp`, `bake.download`, the `requests` of `poll`,
`callback` and `artifacts`, `jobrun.run_command`, `jobrun.baked_rootfs_image`,
`jobrun.stamp`, `poll.fetch_nodes`/`handle_event`/`retrieve_job_definition`.
Keep them module-level names; do not import them directly into a caller that
tests need to intercept.

## Where to read more

* `docs/ARCHITECTURE.md` - the maintainer's document (layer diagram, module
  ownership table, data flow, invariants, "how do I ...").
* `docs/RUNBOOK.md` - the public operator guide (tracked in git).
* `docs/INTERNAL-DEEP-DIVE.md` - the older per-command deep dive. It predates
  this library: its `riscv_pull_worker.py:<line>` citations point at the
  pre-refactor file, and the code now lives here.
* `work/phase4-report.md` - the report of the refactor that created this
  package, including the before/after equivalence result.

Tracking note: `.gitignore` ignores `docs/*` except `docs/RUNBOOK.md`, so
ARCHITECTURE.md is local-only by design. This README is not ignored and travels
with the code.
