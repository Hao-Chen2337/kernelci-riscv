# scripts/kcilib/

The shared library of the RISC-V pull-lab scripts. Import it with `scripts/` on
`sys.path` (each entry point inserts it from its own directory, e.g.
`scripts/riscv_pull_worker.py:77-78`):

    from kcilib import judge, runner
    from kcilib.jobrun import run_node
    from kcilib.poll import poll_loop

Two entry points use it: `scripts/riscv_pull_worker.py` (a resident poller) and
`scripts/fetch-and-run-latest.py` (a one-shot runner). Both offline gates use
it too: `scripts/verify-worker-guards.py` and `scripts/verify-lava-body.py`.

The full picture - layer diagram, data flow, invariants, where state lives, the
rebinding seams and a "how do I ..." section - is `docs/ARCHITECTURE.md`.

## Module index

One line per module: what it owns, its public API, and the contract it enforces.

| Module | Public API | Owns | The contract it enforces |
|---|---|---|---|
| `cli.py` | `build_parser()`, `parse_args(argv=None)` | The worker's flags, defaults-by-reference, and the `--min-timeout`/`--max-timeout` cross-check | Argparse's own bytes: `--help` and every argparse error are what they always were, and the check reports itself with usage + exit 2 |
| `config.py` | `RunConfig`, `PollConfig`, `Configs`, `from_args()`, the `DEFAULT_*`/`LOG_DIR` constants | The two config objects and the ONLY CLI -> config mapping; `LOG_DIR` anchored to the repository, not the CWD | No module below reads a command line; the dataclass defaults ARE the CLI defaults, so the two readers cannot drift |
| `poll.py` | `poll_loop(poll_config, run_node, run_config)`, `handle_event()`, `fetch_nodes()`, `retrieve_job_definition()`, `start_cursor()`, `iso_ago()` | The events API, the node-state re-check, the job-definition fetch, dedup and re-post, the cursor rule, the flock, the batch loop, and the result POST | The only layer that knows the API exists (it never imports `jobrun`); the persisted cursor is authoritative; every event flushes state; "result posted" is printed only after a real 2xx |
| `jobrun.py` | `run_node(node, run_config, node_id=None)`, `build_command()`, `run_command()`, `clamp_timeout()`, `archive_console_log()`, `prune_console_logs()`, `runtime_name()` | Job definition -> tuxrun argv -> run -> verdict -> callback body, the per-job workspace, and the console archive | The only layer that runs a job, and it knows nothing about the API; the console is archived before the workspace is deleted (and the workspace is kept if archiving fails); a timeout clamp is always announced |
| `judge.py` | `judge_run()`, `tap_summary()`, `strip_ansi()`, `is_infra_error()`, `tuxrun_invocation_error()`, `tuxrun_job_error()`, `tuxrun_infra_error()`, `tuxrun_error_message()`, `missing_test_hint()`, `EXIT_*`/`VERDICT_*` | The verdict vocabulary and exit codes (0 pass / 1 test failure / 3 infrastructure), the TAP parser and the infra predicates | tuxrun's exit code is never the verdict; no TAP is never a pass; an infra `error_msg` is built to fit the callback's 200-character window with its actionable tail intact |
| `runner.py` | `build_tuxrun_argv(...)`, `run_tuxrun(...)` | The tuxrun argv layout and omission rules, and the single execution wrapper | argv order and one-entry-per-`--parameters` value are fixed (a joined string is what both callers print); a timeout is a return value, not an exception; the partial console survives a timeout; stdout and stderr are concatenated, never interleaved |
| `callback.py` | `lava_body()`, `post_result()`, `pending_entry()`, `report_from_pending()`, `callback_url()`, `callback_token()`, `callback_target()`, `Callback{Permanent,Transient,MissingURL}Error` | The LAVA-compatible body and its delivery | The callback token is read from `PULL_LABS_CALLBACK_TOKEN` at post time and is never persisted (pending entries carry URL + body only); a 4xx is permanent, a 5xx is retried then transient, and "not posted" can never look like "posted" |
| `state.py` | `StateFile` (`load`/`save`/`mark_seen`/`has_seen`/`add_pending`/`pop_pending`), `SEEN_LIMIT` | The persisted `{timestamp, seen, pending}` document and its atomic write | The document shape is a contract (operators hand-edit it); a corrupt file is refused loudly and never trusted; the save is atomic, re-entrancy-safe and skipped when nothing changed |
| `ledger.py` | `write_result()`, `read_results()`, `result_path()`, `RESULT_FIELDS` | The durable `work/results/<build-id>/<test>.json` record | Every outcome is recorded (a failed run is the one worth having), the key set is closed - an unknown field raises rather than being dropped - and a record is written by temp file + rename |
| `ports.py` | `port_is_free()`, `port_holder()`, `require_port_free()` | Host-port probes: the bind test, the best-effort holder, the refusal text | Binding is the only honest test; a port published by our own compose project is not a conflict; a refusal names the port, the holder and the `KCI_*_PORT` variable that moves the deployment |
| `params.py` | `KVM_TEST_SUBSET`, `cpu_for()`, `kvm_allow_list()` | The curated KVM subset, the cpu property string and the LKFT allow-list spelling | Both entry points run the same thing: one list, one spelling (`"kvm:name kvm:name ..."` as ONE `--parameters` entry) |
| `artifacts.py` | `download()`, `publish_complete_part()`, `gzip_isize()`, `looks_complete()`, `MAX_DOWNLOAD_SIZE`, `DOWNLOAD_TIMEOUT` | Resumable, size-checked artifact transfer | A partial transfer is never lost (it stays as `<dest>.part` with a sidecar naming its URL) and never trusted blindly: a file is reused only once it is proven complete |
| `bake.py` | `baked_rootfs_image()`, `bake_rootfs_image()`, `cached_rootfs_image()`, `publish_baked_image()`, `prune_bake_cache()`, `bake_cache_dir()`, `cache_dir_writable()`, `bake_cache_inputs()`, `bake_cache_key()`, `disk_size_bytes()`, `stamp()` | The nfsroot tar.xz -> bootable ext4 bake (with `modules-load.d` for kvm), the bounded baked-image cache, and the shared progress printer | The cache key covers every bake input (a changed URL never reuses an entry); a published entry is one rename plus a sidecar written last; caching is an optimisation and never fails a job |

## Testing seams

The guard tests patch the module that OWNS a behaviour, never a re-export
(`scripts/verify-worker-guards.py:12-21`). Module attributes that exist to be
re-bound: `bake.stamp`, `bake.download`, the `requests` of `poll`,
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
