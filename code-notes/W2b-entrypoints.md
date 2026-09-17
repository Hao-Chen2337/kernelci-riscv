# Group W2b code notes: long-form rationale moved out of the entry points

These notes hold the long-form explanation that used to live in the comments and
docstrings of the two files below. The code keeps one short line per fact (and
points here where the detail matters); nothing from the original text was
dropped. Comment text and docstrings are English-only and short by policy.

Comments that are *output* rather than explanation were deliberately left alone:
the `cmd_help` heredoc in run.sh, the `kernelci-pipeline/.env` heredoc it
writes, and the `# Written by ./run.sh provision ...` header that
scripts/fetch-and-run-latest.py writes into `work/env/build.env` (those five
lines are string literals - they are the file's content, not comments about it).

## run.sh

### What the entry point is

`run.sh` is the one-command entry for the whole lab: deploy -> run -> inspect.
`./run.sh help` prints the subcommand list; `docs/RUNBOOK.md` is the
operator-facing how-to and `docs/INTERNAL-NOTES.md` the deeper dive. The old
header said "Usage: ./run.sh <subcommand> [args]; ./run.sh help for the full
list" and pointed at those two documents; the pointer to this file was added.

### Network: proxy policy and the per-endpoint preflight

**Proxy handling lives in `scripts/net-preflight.sh`, not here.** It probes the
network with the configuration exactly as the user set it and bypasses a proxy
only when explicitly asked (`KCI_BYPASS_PROXY=1`) or when the proxy is
demonstrably broken. It never silently unsets a working proxy configuration the
way the old `no_proxy_setup()` did - that function hardcoded one machine's dead
proxy into the repository.

**`KCI_PROBE_URL` is captured BEFORE sourcing.** `net-preflight.sh` defaults
that variable to `files.kernelci.org`; the per-endpoint preflight below has to
honour a user-supplied probe target *and* name the URL it really probed.

**Why the preflight is per endpoint.** `kci_preflight()` probes the endpoint(s)
the NEXT command actually talks to, one line each, and prints the URL it probed.
The shared preflight probes a single endpoint, but its message used to read
"kernelci API" while it was probing `files.kernelci.org`: an OK verdict then
looked like a general "the network is fine" verdict, and the next command could
still time out through the same proxy. Measured at the time:
`api.kernelci.org` answered 000 / exit 28 while `files.kernelci.org` answered
200 (docs/RUN-MODES-AND-BUGS.md #17). Hence: probe per endpoint, say which one,
and keep the verdict as narrow as the check. It returns 1 when at least one
endpoint failed; callers that can still make progress `continue anyway` and say
so, because the exit status that follows belongs to the real command.

### `setup`

* The network is demanded **only when something actually has to be cloned**:
  re-running setup on a machine that already has the upstream checkouts must not
  fail just because the network is down.
* **PR1 config patch** (`config/pr1-config.patch`): applied only when
  `kernelci-pipeline/config/platforms.yaml` has no `qemu-riscv64` platform, so
  the same command works before and after the upstream PR merges. The landing is
  **verified afterwards**, because a `git apply` that failed quietly used to
  leave a stack with no riscv platform at all - a state `validate_yaml` cannot
  detect.
* **bullseye archive-source patch** (`config/kernelci-api-bullseye-archive.patch`):
  the official Debian archive issue; without it the local ssh container cannot
  be built.
* **storage nginx uid patch**
  (`config/kernelci-api-storage-nginx-user.patch`): job definitions are uploaded
  with scp and must be readable by nginx **as uid 1000** (`user: '1000:1000'` in
  kernelci-api's docker-compose.yaml), otherwise the upload fails silently and
  jobdef fetches 404.
* **tuxlava patch**: it lives in site-packages, so it cannot be applied from here
  - setup only reports it. It has to be applied **where tuxlava IS**, not in this
  interpreter's user site-packages: a virtualenv or a system-wide install put the
  two in different trees, and the command that was printed then either patched
  nothing or reported "Reversed (or previously applied) patch detected" (N8).
  `tuxlava` not being importable at all is a *different* problem with a
  different fix, and the banner below would otherwise have blamed the patch for
  it (the guest setup needs tuxlava; `pip install tuxrun` pulls it in).
* **Why the tuxlava warning is printed at the END of setup** instead of where it
  is detected: it is a hard prerequisite for the riscv kselftest jobs (tuxrun
  builds its `--tests` choices from tuxlava, so without the class the job dies
  with exit 2 and the node is filed as an *infrastructure* error), and as a
  single `!!` line in the middle of ~145 lines of setup output nobody noticed it
  until the worker failed ~20 minutes later. It is still **non-fatal**: a
  deployment that only runs `baseline` does not need it, so setup exits 0 and
  the banner says so.
* `kernelci-pipeline/.env` is created if missing with a placeholder
  `KCI_API_TOKEN`, `NO_DOCKER_PULL=1` and `KCI_TREES=riscv`.
* The "SOW Phase 1 acceptance clause" comment ("first validation script
  successfully parsed locally") is kept verbatim in the code - it is the
  requirement that `validate_yaml.py` is run at all.
* `scripts/local-instance-init.sh` generates everything the runtime needs that
  is **not in git**: the API's `.env` (with its own `SECRET_KEY`), the SSH key
  pair used to publish job definitions, and a real API token. It runs per
  deployment - no secret is ever committed.

### `provision`, `fetch`, `worker`

* `provision` picks the newest passing kbuild from the production API and then
  downloads that build's artifacts: **two different hosts, two probes**. It runs
  `fetch-and-run-latest.py --provision-only` with `TUXRUN_BIN` passed through.
* `fetch`: `--kvm` is run.sh's own shortcut (translated to
  `--test kselftest-kvm`); `--kvm-full`, `--job`, `--test` are passed through
  untouched. It discovers the build on the production API and downloads the
  kernel, modules and kselftest from `files.kernelci.org` - both hosts are probed
  separately. A failed preflight does not stop it: the message says the exit
  status below is fetch's, not the preflight's.
* `worker`: **every argument passes through.** This used to keep only `"$2"`, so
  `--kvm-full` or `--kvm-tests ...` were dropped without a word. The worker polls
  *this* deployment's API (`KCI_API_URL`) and then downloads the artifacts of
  every job it takes, which are production URLs (`files.kernelci.org`) - probed
  and named separately.
* `PATH` must include `/usr/sbin`: `mkfs.ext4` lives there on Debian/Ubuntu.
  `run-local-stack.sh`'s worker invocation already added it while this one did
  not - two entry points, two behaviours for the same job.
* The worker's state file and workspace carry the **compose project name** in
  their names. Two deployments on one machine do not share node ids, and a shared
  "already seen" set would silently make one of them skip its own queue.

### `report`

* The three node names are job names, and the node name is the job name. The kvm
  entry is the shared `kselftest-kvm-pull-labs` job definition that
  kernelci-pipeline#1600 added for sasha-lab and #1599 reuses, so it is no longer
  riscv-specific.
* The inline python is robust against an unreachable API, an empty result and a
  node without an id: this used to traceback (`json.load` on an empty body,
  `n["id"][:16]` on None) exactly when the stack was down and the answer
  mattered.
* `limit` stays generous (100): the API returns nodes in its own order, so a
  small page can miss the newest ones entirely.
* The **full 24-character id** is printed: the previous `[:16]` truncation made
  two different nodes of the same name print identically in one report.
* **The error type is printed because docs/RUNBOOK.md tells the reader to look at
  it FIRST.** `Infrastructure` means the run produced no usable data (a boot or
  infra failure), not that the kernel regressed; without that column the two were
  only distinguishable by querying the API by hand.
* **Both spellings are read on purpose.** The runbook names the field
  `data.error_type`, while kernelci-core's lava runtime writes the job error
  type as `data.error_code` (`runtime/lava.py`: "error_code" = job_meta
  error_type) and `docs/UPSTREAM-BUILD-AND-DISPATCH.md` documents
  `error_code`. Printing only one of the two shows `-` for real infrastructure
  failures.
* **No apostrophes in that python block**: it is one single-quoted shell string.
  (This is not theoretical - a first attempt at shortening that comment
  introduced "kernelci-core's" and broke `bash -n` at the assignment below it.
  Both the warning and the apostrophe-free wording are still in the code.)
* `|| true` after the pipeline: curl fails when the API is down, and under
  `set -o pipefail` that failure became the report's exit status (7) even
  though the message printed above is exactly what the reader needs
  (adversarial review, N6).

### `dashboard`, `build|jobs|todo|summary|run`, `results`, `prune`

* `dashboard` is a read-only page over the local job table (build index + ledger
  + local API). It is **not** the upstream kernelci-frontend: that one is a 2024
  Flask app whose config lives in another repo and which opens its own MongoDB
  connection, so it shows its data, not this lab's table. The page serves what
  `./run.sh summary` prints.
* The local job table (`scripts/local-jobs.py`) is deliberately separate from
  `worker`: the worker is the resident claimer, this is the table you look at.
  Everything there works without the local stack and without the upstream config
  being merged.
* `results` reads back the durable record this machine produced:
  `work/results/<build>/<test>.json`, written by `./run.sh fetch` and - since
  the worker was given the same ledger - by the resident worker too. It is
  deliberately NOT the API report above: it answers "what did this repo actually
  run and how did it end" from local files, so it still works with the stack
  stopped, and it is the reader the ledger never had (the ledger was write-only
  until then).
* `prune` is the retention policy the entry point owns: `work/downloads/<node_id>/`
  is one directory per fetched build (~45 MB each: Image + modules + kselftest +
  .config) and nothing ever removed them - a daily fetch loop is ~16 GB/year,
  before the bounded rootfs bake cache. Explicit and bounded rules:
  the newest `--keep` builds (default 5) are kept; a build whose commit is the
  one `work/env/build.env` records is kept (that is the build
  `./run.sh stack --seed` and `work/serve/Image` serve, so the deployment never
  loses what it is serving); `--dry-run` prints the same list without deleting
  anything. `--keep` is validated as a whole number and must be >= 1, because
  the newest build is the one `./run.sh stack --seed` serves.
* The embedded python of `prune` reads `work/env/build.env` for the served
  build's **commit** (what every node names) and, when the directory happens to
  be the artifact directory itself, its **build id**. `recorded_commit()`'s
  docstring ("Commit of the kbuild the directory was downloaded from
  (node.json).") is kept verbatim.

### `verify`

* **Every gate must be able to fail the command.** Piping a check into
  `tail -1` (or trailing it with `|| true`) throws its exit status away, so the
  "full gate" used to print a traceback and still exit 0 - it reported success
  precisely when it should have reported a crash.
* The tools the gates themselves need are checked **first**: `ruff: command not
  found` from the last gate, after three others had already run, told a new user
  nothing about what to install (ruff was in no requirements file); the message
  now names the missing pieces and points at `requirements.txt`.
* `compileall` is a gate because the guards import the library only: before it
  existed, a syntax error in `riscv_pull_worker.py` (or in a kcilib module
  nobody exercises yet) reached the user as a runtime traceback.
* `ruff check .` runs from the repository root: it checks our own scripts/
  (upstream clones and `work/` are gitignored). That one-line comment is kept
  verbatim.

### `drift`, `trend`

* `drift` probes and then calls the *same* URL, so the preflight's verdict is
  about the endpoint the command really uses (the old "kernelci API" verdict was
  produced by probing `files.kernelci.org`).
* `KCI_STORAGE_URL` exists because config_drift's fallback for a node without a
  `_config` artifact must point at THIS deployment's storage, not at that tool's
  built-in 8002. The code keeps this as a two-line comment.
* `trend` and `drift` both continue on a failed preflight and report their own
  API errors.

### `stop`

* `stop_recorded_services()` stops the host services of ONE deployment from the
  records `scripts/run-local-stack.sh` wrote when it started them
  (`role|pid|start|pattern`). **The pid's start time is re-read before killing**:
  a record from an old run whose pid was meanwhile reused by an unrelated process
  must not kill that process (field 22 of `/proc/<pid>/stat` is the comparison).
* One machine can host more than one isolated deployment, each with its own
  compose project, volumes and ports, so `stop` uses the same overridable
  identity (`KCI_COMPOSE_PROJECT`, default `kcirv`) as the stack - stopping one
  deployment must not stop another.
* The pkill fallback (used only when there is no pid record: the stack was started
  before pids were recorded, or by another checkout) used to be machine-global,
  so stopping one deployment killed another deployment's scheduler, callback and
  artifact server - while the compose teardown right below was already
  project-scoped (#18). It now announces that it cannot prove ownership, prints
  exactly what the pattern matching is about to hit, and then does it: a stop
  that quietly stops nothing would be worse.
* The API stack (api/db/redis/storage/ssh) runs under docker compose; its data
  stays in volumes, so a later `stack` brings it back as-is. The teardown branch
  used to have no `else`: a failed `docker compose down` printed nothing at all
  and the reader believed the stack was down while its containers kept running
  (#14). It now prints the failure, the output, and how to inspect the project.

## scripts/fetch-and-run-latest.py

### Purpose and contract

Fetches the newest production riscv kbuild and runs it locally with tuxrun: no
KernelCI local stack, no node and no token are needed. It queries the public
production API for the latest passing `kbuild-gcc-14-riscv` build, downloads its
artifacts (kernel / kselftest / modules / .config), serves them locally and runs
tuxrun against them - the same execution path the pull-lab worker uses.

**How the artifacts GET here is this script's choice and nobody else's.**
`kcilib/run/delivery.py` names the two ways - `local_server` (what this script
uses) and `in_container` (what the worker's tuxrun command line does) - and owns
the implementation of both: the download/size checks, the artifact manifest and
the local HTTP server all used to live in this file. The script now picks the
mode and hands out the addresses; the trade-off between the two modes is
documented in `code-notes/B-delivery-buildref.md`.

**Usage** (removed from the module docstring; `--help` carries the flag list):

    fetch-and-run-latest.py                        # newest build, kselftest-riscv
    fetch-and-run-latest.py --test kselftest-kvm   # curated kvm subset
    fetch-and-run-latest.py --kvm-full             # whole kvm collection
                                                   # (implies --test kselftest-kvm)
    fetch-and-run-latest.py --test boot            # boot only
    fetch-and-run-latest.py --api-url http://127.0.0.1:8001  # local DB
    fetch-and-run-latest.py --provision-only       # produce work/ artifacts

**Exit status - this path is driven from cron/CI, so the verdict IS the exit
status** (it used to be 0 for every outcome, including a guest that never booted):

    0   the run passed: TAP produced and no selftest failed, or the guest booted
    1   the run completed and at least one selftest failed
    3   infrastructure error: tuxrun never started, the guest never booted, no
        TAP lines at all, or the artifacts/artifact server could not be verified

### Import contract and paths

* **Everything this path and the pull-lab worker MUST agree on lives in
  `scripts/kcilib/`**: the TAP parser and the verdict, the tuxrun command line,
  the artifact transfers, the KVM allow-list and the result ledger. The library is
  resolved through this file's own directory, so the script works from any CWD
  and also when an offline test loads it by path.
* `work/` is gitignored and holds regenerable runtime artifacts.
  `ROOT`/`WORK_ENV`/`WORK_SERVE` are `kcilib.run.delivery`'s, each resolved
  from that module's own location and never a hardcoded absolute path (exactly as
  this file used to do) - because the delivery layer is what records *which*
  artifact was downloaded, from where and how big it was, so the manifest and the
  serve directory are its business and the layout is spelled once, there.
* `DEFAULT_ROOTFS_URL` is the rootfs used by `--provision-only`
  (`./run.sh provision`). **Kernel and modules are NOT pinned here**: they are
  discovered from the newest production kbuild node by
  `default_build_artifacts()`, because storage prunes old builds - a pinned hash
  still served `modules.tar.xz` while its `Image` returned 404, which left a
  fresh deployment unable to provision a kernel at all.
* The **verdict vocabulary is `kcilib.run.judge`'s**: the exit statuses (0 pass,
  1 test failure, 3 infrastructure), the TAP parser, the "timed out after Ns"
  detail and the boot evidence a `--test boot` run is judged by
  (`kcilib.run.judge` reads the guest's own console output). The result record
  below and the worker's callback are therefore the same verdict, not two copies
  of it. `BUILD_ID_FILE`, the per-build `ARTIFACT_RECORD` and
  `SERVE_READY_TIMEOUT` went with the delivery implementation: writing the
  build-id file the server proves itself with, recording what was downloaded, and
  waiting for that proof are `kcilib.run.delivery`'s, not this script's.

### API access and build discovery

* `api_get()` goes through the shared client (`kcilib/api.py`). This script
  used to open its own urllib request here - a third variant of the same call,
  next to config_drift.py's and regression_tracker.py's. The client keeps this
  script's promise of needing no stack and no token: it is plain HTTP against
  whatever `--api-url` says.
* `pick_newest()` looks for a `done`/`pass` kbuild node and widens the window
  (3 -> 7 -> 30 -> 180 days) because the API defaults to old-first pages: asking
  for a rolling window and widening it if empty is the only way to be sure the
  newest build is really the newest.
* `default_build_artifacts()` takes kernel **and** modules from the SAME node on
  purpose: the worker bakes `modules.tar.xz` into `/lib/modules` of the rootfs
  and modprobe matches them by kernel release, so mixing builds makes every kvm
  test skip with "Cannot open /dev/kvm".

### Rootfs baking

The nfsroot-tarball -> ext4 bake machinery (`DISK_SIZE`, the path-traversal and
device-member guards, `_extract` and `bake_rootfs_image`) used to be an inlined
copy of the pull-lab worker's, kept here only because kcilib had no bake module
when this path was rewritten. It is `kcilib.run.bake` now - the same code,
imported, so the guards and the `mkfs.ext4` command line cannot drift from the
worker's a second time.

The manifest cache it uses (`work/env/.manifest.json`, keyed by URL, shared with
the kernel artifact entries) is **not** `kcilib.run.bake`'s sidecar cache: its
implementation is `kcilib.run.delivery`'s
(`load_manifest`/`save_manifest`/`cache_hit`/`record_entry`), because
recording WHAT was downloaded, from where and how big it was is the delivery
layer's job. Rootfs **baking** stays here - delivery is about getting artifacts
to tuxrun, baking is `kcilib.run.bake`'s.

`provision_rootfs()` ensures the baked ext4 exists at `ext4_path` (manifest
cache) and otherwise calls `bake.bake_rootfs_image()`: nfsroot tar.xz ->
tuxrun-bootable ext4 with the kvm modules baked into `/lib/modules`.

The tarball is downloaded to a **stable path** rather than into the temporary
bake directory: the worker's `download()` resumes an interrupted transfer with a
Range request, so a fetch that a CDN cut short is continued by the next run
instead of restarting from zero - which is the difference between a fresh clone
provisioning successfully and never finishing.

`bake.download` is rebound to `delivery.fetch` before the bake, because that is
the seam `kcilib.run.bake` transfers through: `delivery.fetch()` takes
`file://` sources (the offline tests) and its printed "copied ..." lines were this
script's before the move, so binding it keeps the bake's console unchanged.

### Provisioning and `work/env/build.env`

* With no pinned build hash, production is asked for the newest passing kbuild and
  kernel + modules come from that one node.
* A **hand-pinned kernel URL** has no node to read a revision from, so the caller
  has to state it (`KCI_BUILD_COMMIT`/`KCI_BUILD_DESCRIBE`/...). Without one
  the seed has nothing to label its nodes with, and it says so instead of quietly
  using its old default.
* `build.env` is the **one source of truth for "which kbuild these artifacts came
  from"**: `run-local-stack.sh` seeds jobs from this file, so the kernel served
  at :8999, the modules baked into the rootfs and the job definition cannot drift
  apart. A mismatch makes every kvm test skip ("Cannot open /dev/kvm"), which is
  exactly the failure this whole path exists to avoid.
* **The kernel *revision* is part of that.** The seed used to keep its own
  hardcoded commit/describe, so a deployment serving 7.3-rc2 labelled every node
  (and every `./run.sh report` line) `7.3-rc1-516-gf217004a40c49`. The results
  were right, the attribution was wrong, and `config_drift.py` /
  `regression_tracker.py` group by that field.
* Production nodes carry either `{"version": 7, "patchlevel": 3}` or a bare
  int; `.get()` on the int raised `AttributeError` and lost the whole file
  (adversarial review, N10).
* `env_line()` writes `KEY=<shell-quoted value>` because `build.env` is
  ***sourced*** by `run-local-stack.sh`, so a raw value breaks the deployment: a
  space-joined tag list ran `v7.0: command not found` and silently dropped every
  tag to the placeholder, and a quote or backslash in a describe string corrupted
  the shell state (adversarial review, N2).
* The five `# ...` lines at the top of `build.env` are written by the script as
  string literals ("Written by ./run.sh provision - do not edit by hand", "The
  kbuild every work/ artifact below comes from", "run-local-stack.sh seeds jobs
  from these URLs and labels the nodes it creates with this revision", "Values are
  shell-quoted: this file is sourced, not parsed") - they are output, not
  comments, and were left untouched.

### Verdict, record and run

* There is **deliberately no local `strip_ansi()`/`parse_tap()`** any more: the
  fetch path used a second, weaker copy that missed "not  ok", "NOT OK",
  ANSI-glued failures and tests that started but never finished, so it could print
  a summary that looked green when nothing had run (#23). TAP parsing is
  `kcilib.run.judge.tap_summary()`, reached through `judge_run()`, exactly as
  the worker's callback reaches it: one parser, no drift.
* `write_result()`: mode (A) kept nothing but a console log inside
  `work/downloads/<build>/`, so "which build was this test run against, when, and
  how did it end" could only be reconstructed by hand. The record is written for
  **every** outcome - a failed run is exactly the one worth having a record of.
  The file itself (path layout, tmp file + rename, fsync, the key set) is
  `kcilib.core.ledger`'s, so the regression tracker and the worker write the same
  records; the payload is this script's naming of the run.
* `run_once()` returns the outcome dict (verdict, exit_code, detail, summary,
  per_test, log, output). Anything that prevents a verdict raises, and the caller
  records it: a run that dies before tuxrun is still a run that happened.
* The default rootfs used to be a hand-made 4 GB file that nothing generated:
  it is baked on first use so a fresh clone works. An explicit `--rootfs` is
  used verbatim and never auto-generated.

### The tuxrun command line and the console it writes

* The cpu property string is `kcilib.core.params.cpu_for()`: the KVM jobs need
  the H extension, everything else takes `--cpu` as it was given.
* `kcilib.core.params.kvm_allow_list()` is the curated functional subset in the
  `"kvm:name kvm:name ..."` form the LKFT script wants, passed as **ONE**
  `--parameters` entry. `--kvm-full` asks for the whole collection, which is
  exactly no allow-list at all.
* `cwd` and `stream_separator` are explicit because they are part of the console
  this writes: tuxrun is run from the caller's directory, and its stdout and
  stderr are concatenated with **nothing** between them - these `tuxrun.log`
  files carry no blank line at the junction, unlike the worker's archived
  consoles. `log_path` is written by `run_tuxrun` (partial console included on a
  timeout), and its `proc.stdout` IS the merged console the verdict is read from.
* One verdict comes from `kcilib.run.judge`: the same TAP parser and the same
  exit statuses the worker's callback reports. `summary` and `per_test` are what
  the TAP summary and the result record print.

### Arguments

* `--cpu`'s default comes from `kcilib.core.config`, not from a literal here:
  this flag and the worker's `--cpu` must mean the same string, and two copies of
  a default are two chances to drift apart.
* `--runtime` was this script's **container** runtime (docker/podman) while the
  worker's `--runtime` is the **lab filter** (`pull-labs-riscv`,
  `PollConfig.runtime`): one name, two meanings, in two entry points that are
  supposed to describe the same run. The unambiguous `--container-runtime` is now
  primary, `--runtime` stays as an alias so nothing that already calls it breaks,
  and the value lands in `RunConfig.container_runtime` either way.
* `--kvm-full` without the kvm collection used to be a silent no-op: the flag is
  read only inside the kselftest-kvm branch, so `./run.sh fetch --kvm-full` ran
  the whole *riscv* collection - a different and much larger suite than the help
  promised (#5). It now implies `--test kselftest-kvm` and errors out if an
  incompatible `--test` was given too.
* `run_config` carries the run-scoped half of the command line in the SAME object
  the worker passes around (`kcilib.core.config.RunConfig`). Everything a run
  needs is named there once; what stays in `args` is this script's deployment
  business (which build to fetch, which port to serve it on, whether to provision
  only). The two entry points therefore cannot describe the same run differently
  field by field - which is how they drifted before.
* Anything that stops the run before it produced a verdict (a stale artifact
  server, a truncated download, Ctrl-C) is recorded too: the record only has value
  if a failed run leaves one.
