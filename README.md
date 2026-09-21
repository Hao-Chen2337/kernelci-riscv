# kernelci-riscv

RISC-V KernelCI automation for the SOW in
[riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49):
continuous regression testing of the Linux riscv Vector/Hypervisor
extensions on QEMU, with the test profile submitted upstream to kernelci-pipeline.

One run is four things: **pick a build, make it local, run a test on it, get an
outcome.**  Everything in this repository is either that, a selector that decides
*which* build, or a viewer that shows what came back.

## One tree

This repository used to hold two implementations of the same thing - the shipping
tree under `scripts/` with `run.sh` as its dispatcher, and the rewrite under `lib/`
with a file per command.  **The rewrite won, and the old tree is deleted**
(2026-09-20): the last of it went in one commit-sized step, and what replaced each
piece is listed under [Adopting the new tree](#adopting-the-new-tree-what-replaced-what)
below.  A short history, because the names still turn up in the docs:

| Was | Is now |
|---|---|
| `run.sh <subcommand>` (the one command surface, 504 lines) | `python3 <entry>.py` for the runtime, `deploy/*.sh` for the deployment, `python3 verify.py` for the gate |
| `scripts/{local-jobs,results,riscv_pull_worker,fetch-and-run-latest}.py`, `supervise-run.sh`, `dashboard.py` | `table.py`, `results.py`, `pull_worker.py`, `run_latest.py` + `provision.py`, `runday.py`, `gui.py` |
| `scripts/run-local-stack.sh`, `stack-seed.sh`, `local-instance-init.sh`, `net-preflight.sh` | `deploy/stack.sh`, `deploy/seed.sh`, `deploy/instance-init.sh`, `deploy/net-preflight.sh` |
| `kcilib/` (36 modules, ~8.1k lines) | `lib/` (the same ideas, one vocabulary) |
| `work/` (the old workspace) | `var/` |
| `./run.sh verify` (validate_yaml + the kcilib guard suite) | `python3 verify.py` |

The workspace is `var/` and only `var/`: `lib/layout.py` owns every path in it, and
`$KCI_WORK_DIR` moves it anywhere.  Its ledger (`var/results/`) is history and is
never pruned; everything else there can be regenerated.

## How to run it

All commands run from the repository root.

```bash
# one test on the newest production riscv build (exit status IS the verdict:
# 0 pass, 1 test failure, 3 infrastructure)
python3 run_latest.py --test boot
python3 run_latest.py --test kselftest-riscv
python3 run_latest.py --test kselftest-kvm

# the resident worker: claim jobs from a KernelCI events API, run them, report
python3 pull_worker.py --api-url http://127.0.0.1:8001 --once
python3 pull_worker.py --api-url http://127.0.0.1:8001        # keep polling

# a day's builds, skipping whatever the ledger already has
python3 runday.py --days 1

# the local table, offline
python3 table.py index                 # ask the API which builds exist
python3 table.py pull --build <id>     # materialize one (repeatable)
python3 table.py jobs | todo | summary | run

# the ledger, read back; config drift between two builds
python3 results.py [--build ID] [--json]
python3 drift.py [--older ID] [--newer ID]

# the page
python3 gui.py --port 8080             # http://127.0.0.1:8080
python3 gui.py --port 8080 --api-url http://127.0.0.1:8001   # $KCI_API_URL works too
#   ... and it does not have to be restarted to ask a different API: the `api` box in
#       its filter bar switches to `production` (https://api.kernelci.org) or to any
#       http(s) address you type, one page load at a time

# the gate: everything that must be true before this tree is deployed
python3 verify.py                      # --quick skips the page renders; --base URL adds the HTTP sweep

# deployment: the local full stack (its own directory - see README's deploy/ row)
deploy/setup.sh                        # clones + patches + this deployment's local configuration
deploy/stack.sh --seed                 # api/db/redis/storage/ssh + artifact server + callback + scheduler, then seed
deploy/stop.sh                         # stop the host services it recorded, then the compose stack
```

The page is bilingual: `?lang=zh` (or the switch in its header, which remembers your
choice in a `kci_lang` cookie) draws the same page in Chinese.  Which API it asks is
the `api` box in the filter bar, and it is a URL key rather than a setting: `?api=production`
is the public API (`https://api.kernelci.org`), `?api=local` the local stack, and
`?api=http://127.0.0.1:8001` spells the same thing out - any `http(s)` address works, and a
value that is neither a known name nor one is ignored (the page says so and reads the base
`--api-url` / `$KCI_API_URL` gave it).  `api` rides on every link, so a page you bookmark or
copy answers the question its URL states, and the address it really read is printed in its
own query line (`asked the API: https://api.kernelci.org: kind=kbuild …`) - which is worth
reading before believing a small row count.  Every sentence it prints lives in
`lib/i18n/`; `python3 -m lib.i18n --check lib/gui` is that package's test (missing keys,
keys nothing uses, rows left untranslated), and `--map` says which line of `lib/gui/` reads
each one.

**Five pages, one filter bar, one live panel.**  `builds | jobs | runs | worker | analysis`.
`/` is the merged builds page - one row per build id, with the three facts kept apart as
three adjacent columns (`card | bytes | act`, each of which may be `-`) - and `/remote`,
`/local` and `/pull` are **302 redirects** that carry the whole query, so an old bookmark
still asks the question it always asked.  Every axis in force is printed, **including its
default**, as `key: value`; `rows` and `days` are sliders you may also type into; and the
page prints how many rows it read, how many the API had, and how many its own filter
dropped.  A running activity appears in a side panel with a spinner, and a finish is
announced once - a reload never replays an old one.

**It is reworked, and the record is in `docs/gui-rework/`.**  Start at
[`docs/gui-rework/README.md`](docs/gui-rework/README.md) for the index,
[`REQUIREMENTS.md`](docs/gui-rework/REQUIREMENTS.md) for every point the operator raised
and what became of it, and [`CHANGELOG.md`](docs/gui-rework/CHANGELOG.md) for what changed
with the measurement behind each claim.  The acceptance harness is
`docs/gui-rework/tools/accept.py` - sixteen checks
that are the operator's own requirements, each printing the evidence that decided it;
run it against a live instance with `--base`.

`--help` on any entry lists its flags.  The worker's `--runtime` is the *lab*
name (`pull-labs-riscv`, what a job node's `data.runtime` says); `--container-runtime`
is what tuxrun runs the dispatcher image in (`docker`).

This is the quickstart.  The full manual - environment, the local stack, the worker,
prune, verify, and everything that goes wrong - is [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## What is verified, and how

Every claim below is from a real run, not from reading code.

| Claim | Evidence |
|---|---|
| the one-shot line boots a real kernel | `var/results/<build>/boot.json` - `pass`, console archived under `var/logs/` |
| the two kselftest suites run | `kselftest-kvm`: 9 pass / 3 skip - the 3 want ISA extensions the emulated CPU does not expose (`sbi-pmu`, `aia`, `h`), not missing hardware.  `kselftest-riscv`: 10 TAP tests, and the verdict is per build - of six builds on 2026-09-20, four had `pointer_masking` fail its `constraint` assertion (PMLEN>=1) and one passed 10/10 |
| the worker line reports into a real pipeline | local stack seeded with 3 job nodes, `pull_worker.py --once` ran them, and the pipeline's own node states read `done/pass` with our `callback_data`, `lava_log`, `lava_logs` |
| the callback body is accepted upstream | generated bodies replayed through the real `kernelci.runtime.lava.Callback`; its `get_job_status()`, per-test hierarchy and infra flag all read back correctly - four cases, 23 checks, `docs/gui-rework/tools/verify_callback_body.py` |
| the tree keeps its shape | `docs/gui-rework/tools/check_structure.py`: every entry turns a `KciError` into its own exit code, one module writes the ledger, one names the tuxrun binary, only `lib/layout.py` spells a workspace path, one `lava_body`, and every entry prints its usage |
| all of it at once | `python3 verify.py` - the command an operator runs, whose exit status is the answer |
| exit codes mean what they say | 0 pass, 1 test failure, 3 infrastructure - all three observed in real runs; an unreachable artifact or API becomes `incomplete` and **still writes the ledger** |
| the page works | driven over HTTP: filters, actions as subprocesses, live log tail, cancel, the one-writer rule, drift and trend |
| the page can ask the public API without a restart | on an instance started on the local stack, `?api=production` answers the same query with `showing 10 of …` where the local stack answers 2, its query line names `https://api.kernelci.org`, and `?api=https://api.kernelci.org` renders the identical bytes (34113) with every link writing `api=production` |
| the page keeps up with what the buttons do | another process writes one ledger record, and the same URL - no restart - goes from `0 record(s)` to `1 record(s)`, its `/jobs` row from `0 / - / -` to `1 / pass / <time>`; with 300 cards a request parses the table and the ledger **once** (0.035s) instead of 207 times |
| an action button reports in place, and never dumps JSON | the *rendered* page script run in node against a hand-written DOM stub: submit is intercepted (`preventDefault`), the POST goes to the form's own action, a 2xx writes `started <id>: <argv>` into **that form's** status line, a 409 writes the server's own refusal there, and a GET filter form is left to the browser - 5/5 |
| "register this window" really registers it | isolated workspace: `table.py index --api-url https://api.kernelci.org --days 1 --limit 5` takes the local table from 3 cards to 7 (`net-next`, `mainline/master`, `riscv/fixes`); before the fix the button ran `index` without `--api-url` and read the local stack instead |
| the page does not hang on a production-sized queue | `/worker` against `api.kernelci.org` (`kind=job` answers **4.78 million** nodes) is **2 requests** - a count and the head of the queue - 12-18s; the old read paged to `total` and never drew |

## 文档地图：想干什么，读哪一份

| 我想… | 读 | 它在说什么 |
|---|---|---|
| 把新树跑起来 | 本文件的「How to run it」 | 17 条命令行，每条都真跑过 |
| 知道哪些话是被验证过的、哪些还没有 | 本文件的「What is verified, and how」+「Not done yet, and the gaps worth knowing」 | 证据与缺口，分开写 |
| 看懂接口的形状 | [`include/kci.hpp`](include/kci.hpp)（总览）→ `include/kci/*.hpp`（按层） | 只有声明和注释，`g++ -std=c++17` 能过 |
| **操作这个部署**（部署、起栈、worker、prune、verify） | [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | 部署与运行手册：环境、setup、stack、worker、prune、verify |
| 知道上游卡在哪、项目边界在哪 | [`docs/UPSTREAM-BLOCKERS.md`](docs/UPSTREAM-BLOCKERS.md) | 上游进展快照（§0）+ 未解问题 U1–U5；关于外部世界的事实，日期是测量日期 |
| 看旧树（已删除）曾经怎么分的层 | [`docs/archive/`](docs/archive/)（冻结的早期深挖） | 旧树的地图已随旧树删除：历史材料在 `archive/` |
| 翻历史 | `docs/archive/`（冻结） | 别当现状读 |

**两份文档集的分界**：`docs/` 是**这个部署**的运行手册加上关于上游与旧树的事实
（旧树 `scripts/` + `run.sh` 已于 2026-09-20 删除）；`include/` 讲的是
**这棵树的设计**（`lib/` + 根目录入口）。`docs/INDEX.md` 顶部有同样的路标。

## What is implemented

One run is four things - **pick a build, make it local, run a test on it, get an
outcome** - and the tree is one file per thing: a root entry that chooses, a `lib/`
module that does the work, a viewer that shows what came back.  Every module, path and
count below was read off the tree.  The layout rule (`lib/__init__.py`) is that the
selectors and the viewers sit above `lib/`, the outside world (KernelCI HTTP,
tuxrun/QEMU, the filesystem) below it, and **nothing in `lib/` imports an entry point
or a tool**.

### The root entries: twelve files, twelve commands

Every root `*.py` is a thin `argparse` shell: parse argv, hand the work to `lib/`, turn
a `KciError` into an exit code.  `docs/gui-rework/tools/check_structure.py` pins that
shape - one entry, one exit path, one usage line.

| Entry | The command | Reads from `lib/` |
|---|---|---|
| `gui.py` | the page over HTTP: `gui.Gui(...).serve()`, default port **8079** (`--port`, `--rows`, `--refresh`, `--api-url`) | `config`, `errors`, `gui` |
| `run_latest.py` | the newest production riscv build, run once here (fetch → build → job → verdict), then exit | `api`, `build`, `config`, `errors`, `kbuild`, `job` |
| `pull_worker.py` | the resident worker: claim jobs from an events API, run them, call back; `--once` is one round | `config`, `errors`, `poller` |
| `runday.py` | a day's builds, skipping whatever the ledger already has (`--day`, `--days`, `--redo`) | `build`, `config`, `errors`, `kbuild`, `job`, `re` |
| `table.py` | the local build table, offline: `index` (ask the API) / `pull` (fetch the bytes) / `jobs` / `todo` / `summary` / `run` | `build`, `config`, `errors`, `job`, `re` |
| `results.py` | the ledger (`var/results/`) read back; `--build`, `--test`, `--list`, `--json` | `errors`, `re` |
| `drift.py` | two builds' `.config` compared; exit 0 no drift, **1 drift**, 3 infrastructure | `config`, `drift`, `errors` |
| `trend.py` | pass/fail, and regressions (pass → fail), from the production API's `done` job history | `config`, `errors`, `re`, `kjob`, `out` |
| `provision.py` | pin the newest **passing** production riscv build: fetch its kernel, publish `var/serve/Image`, record `var/state/served.json` | `api`, `build`, `config`, `errors` |
| `prune.py` | retention for `var/downloads/`: the newest N plus the one this deployment serves; `--dry-run` | `errors`, `layout`, `retention` |
| `report.py` | the newest node of each pull-lab job name (state / result / created / full id) | `config`, `errors` |
| `verify.py` | the gate: ruff, i18n, structure, the callback body through the real upstream parser, four page-script and unit checks, every page rendered in both languages, the PR1 YAML, and `accept.py` over HTTP with `--base` | `errors`; each check is its own subprocess, under `docs/gui-rework/tools/` |

### The middle layer, lib/

**The foundation**, which knows nothing or only `errors` and `layout`:

| Module | What it is | Key names |
|---|---|---|
| `errors.py` | one exception root and three exit codes (0 pass / 1 test fail / **3 infrastructure**) | `KciError`, `ConfigError`, `ApiError`, `ArtifactError`, `InfraError`, `LedgerError` |
| `out.py` | one `(build, test)` outcome | `Outcome`, `RECORD_FIELDS` - the on-disk key set, a contract |
| `tests.py` | the test directory (**not** a test suite): which tests can be run | `TESTS`, `DEFAULT_TESTS`, `KVM_SKIP_TESTS`, `ROOTFS_URL`, `DEFAULT_DEVICE`, `DEFAULT_LAB`, `device()` - one definition's own device, which `runner` spells as `--device` and `sink` reports as `actual_device_id` |
| `layout.py` | **every path this project writes is spelled here and nowhere else** | `work()` (`var/` or `$KCI_WORK_DIR`), `downloads/baked/configs/logs/serve/results/runs/state/workspaces`, `worker_state()`, `index()` |
| `atomic.py` | one atomic write: the file written beside itself, then renamed over itself - seven call sites used to write those two steps by hand | `write_json()`, `write_text()` |
| `__init__.py` | the repository root | `repo_root()` - walks up for `lib/layout.py` + `README.md`, never counts `dirname()` levels |
| `ports.py` | host port probing, used by `deploy/stack.sh` | `port_is_free`, `port_holder`, `require_port_free` |

**The remote half**, read-only - what the API has:

| Module | What it is | Key names |
|---|---|---|
| `api.py` | **the only KernelCI HTTP in the tree**: a per-request memo, a process-wide TTL cache, a per-request time budget, retries on `ConnectionError` only, and redirects refused rather than followed | `Api` (`get/post/text/nodes/count/node/events/counts`), `PRODUCTION`, `LOCAL` |
| `kbuild.py` | remote **build** nodes | `Kbuild`, `Kbuilds` (`getnew/getdays/get`), `build_id_of`, `KBUILD_JOB` |
| `kjob.py` | remote **job** nodes - one node kind, whether it is a queue entry or a finished run | `Kjob`, `Kjobs` (`getjob/available/done`), `claimable()`, `definition()` |

**The local half**, which has the side effects - what we do to it:

| Module | What it is | Key names |
|---|---|---|
| `build/` (a package, 6 modules) | the local half of a build: the bytes, the guest disk, the local table | `Build`, `Builds` (`var/state/builds.json`), `download`, `bake_rootfs`, `publish_local`, `served`, `provision` |
| `job.py` | **the only executor** - the worker, the one-shots, `table.py` and the page's buttons all arrive here | `Job`, `Jobs`, `Job.run()` |
| `runner.py` | tuxrun's argv, and running it (**no shell anywhere**; a timeout kills the process group) | `argv()`, `execute()` |
| `judge.py` | console → verdict (**the evidence is the TAP**, never tuxrun's exit code) | `tap_summary`, `verdict`, `infra_reason`, `strip_ansi` |
| `sink.py` | where one outcome goes | `Sink` (the ABC), `Ledger`, `Callback`, `lava_body`, `deliver` |

**The flow and the views**, which run once something is running:

| Module | What it is | Key names |
|---|---|---|
| `poller.py` | **the rotation**: watch the API, claim, run, call back - the most involved class in the tree | `Poller` |
| `run.py` | one background activity: `run.json` + `run.log` under `var/runs/<id>/` | `Run`, `start/load/load_all/reap/cancel/log_since`, `WRITERS`, `KINDS` |
| `config.py` | argv/env → objects | `RunConfig`, `PollConfig`, `client()`, `run_from`, `parse_poll` |
| `re.py` | the ledger, read back | `Records` (`load/for_build/for_test/last/series/tally`), `todo()`, `transitions()`, `render` |
| `drift.py` | config drift: fetch the `.config`, parse it, compare; kept on disk under `var/configs/` | `Drift` (`between/series/from_files`), `parse`, `diff` |
| `retention.py` | the retention rule; **the plan (who stays) and the prune (who goes) are separate** | `plan()`, `prune()`, `DEFAULT_KEEP` |
| `gui/` (a package, 28 modules) | **the whole page**; its `__init__.py` docstring carries the per-module layout table, so enter there.  Coarsely: `schema.py` is the vocabulary every page shares (routes, actions, filters, sorting), `models.py` is `Apis/Filter/Local/Remote`, `server.py` the socket loop and routing, `app.py` `Gui` itself, `pages/` one module per page, `templates.py` the inlined CSS/JS/HTML | `Gui`, `Filter`, `Local`, `Remote`, `Apis` |
| `i18n/` (a package, 10 modules) | the page's own words, **one catalogue in EN and ZH**, read by `lib/gui/` and nothing else.  `catalogue/` carries six data parts (`shell`/`local`/`work`/`analysis`/`record`/`words`, 112-340 lines each), `__init__.py` is the lookup, `check.py` is `--check`/`--map` | `t(lang, key, **fmt)`, `pick_lang`, `key_for` |

A new sentence has to reach `lib/i18n/catalogue/` in the same change, or
`python3 -m lib.i18n --check lib/gui` reports the missing key.  (`-m` runs the package's
own `lib/i18n/__main__.py`; this is a package now, not a `lib/i18n.py`.)

**Three entry lines, one executor.**  The lines differ only in where a job comes from,
and all of them arrive at the same `Job.run()`, which cannot tell a job it invented from
one the API dispatched - that is the design, not a coincidence.  Where a result goes is
the sink's decision, never the caller's, and the ledger is always first.

| Line | Entry | Where the job comes from |
|---|---|---|
| the resident worker | `pull_worker.py` → `poller.Poller` | the API dispatches it (`Kjobs.available()`) |
| one-shot | `run_latest.py`, `runday.py` | it picks one itself: newest, or a given day |
| the local table | `table.py` | the table itself (`index − ledger = todo`) |

```
Kbuilds.getnew() ──▶ Build.make() ──▶ Job.run() ──▶ sink.deliver()
Kjobs.available()    download()        argv()         Ledger.write() → var/results/
                     bake_rootfs()     execute()      Callback.post() → lava_body
                                       judge.verdict()
```

### What is not Python

| Path | What it is | The rule that matters |
|---|---|---|
| `include/kci.hpp` + `include/kci/*.hpp` | **the interface as C++ declarations - a drawing, not a program** (declarations and comments, `g++ -std=c++17` passes) | by layer: `base` (exit codes/paths/config) → `remote` (Api/Kbuild/Kjob) → `local` (Build/Job/Outcome) → `engine` (Runner/Judge/Sink) → `flow` (Run/Poller) → `view` (Filter/ledger/Drift/GUI).  **The drawing may lead the implementation; the implementation may not lead the drawing** - change `include/` first |
| `deploy/` | **the deployment half**: `setup.sh` (clones + patches + this deployment's local configuration + the YAML check), `stack.sh [--seed]` (the local full stack: compose, artifact server, real callback, official scheduler), `stop.sh`, `instance-init.sh`, `seed.sh`, `net-preflight.sh`, `render-local-config.py`, `repro-api-bugs.sh` | it owns no runtime decision - the root entries do - and it reads and writes `var/` like the rest of this tree |
| `config/` | patches and templates | `pr1-config.patch` (the PR1 test profile), `tuxlava-kselftest-riscv.patch` (tuxlava 0.25.0 from PyPI has no riscv class, so this machine still needs it), `local-callback.toml` (the `@KCI_ROOT@` template), `cb-config/pipeline.yaml`, and the two kernelci-api patches |
| `docs/RUNBOOK.md` | how to operate this deployment: environment, `setup`, `stack`, the worker, prune, verify | the full manual; the deploy/setup/stack/stop lines above are the quickstart |
| `docs/` | the runbook, plus the facts about upstream and about the old tree | **the whole tree is gitignored and only `docs/RUNBOOK.md` is let through**, so what is put here does not enter the repository.  `docs/INDEX.md` is the signpost for "which document answers this" |
| `kernelci-*/` | upstream clones (**gitignored**, created by `deploy/setup.sh`) | to judge upstream's behaviour read `git show origin/<branch>:<path>`, never a working-tree file |
| `var/` | **the workspace**, owned by `lib/layout.py` and nothing else | `$KCI_WORK_DIR` moves it anywhere; the ledger `var/results/` is history and is **never pruned**, everything else there is regenerable.  The old tree's `work/` is deleted; its data is archived in `/home/hao/kci-work-backup-*.tar.gz` |

## Not done yet, and the gaps worth knowing

* **The adoption is finished; these are the gaps that were there all along.**
  The three bullets that used to open this list (the dispatcher not being
  repointed, the deployment half, the old ledger) are done or decided: the old
  tree is deleted, `deploy/` is the deployment, and the 378 records of
  `work/results/` are archived rather than migrated (the operator did not want
  them - `/home/hao/kci-work-backup-*.tar.gz`).
* **`runday.py` has never been run end to end** - its code path (a day's builds
  minus the ledger) was exercised through `table.py` and the poller, not through
  the entry itself.
* **The KVM skip list is a measurement, not a law.**  `lib/tests.py` names the
  tests that cannot pass under TCG; a newer kernel's kselftest tarball can ship
  new ones, and they show up as failures until the list is updated from the
  evidence.  That is deliberate - a test that cannot run here should be *named*,
  not silently skipped - but it needs a human when it happens.
* **`gui.py --refresh` is not wired**; the page polls every 2 seconds.
* **Nothing in the new tree has been run against the production API's write
  path.**  Reads (`getnew`, `getdays`) are exercised; the only write is the
  callback, and it has only been posted to a local pipeline.

## Two contracts the rewrite keeps byte for byte

Everything else was allowed to change; these were not, because breaking them
fails silently:

* **the LAVA callback body** - the pipeline's endpoint has no parser for any
  other shape, so a wrong format loses the result without an error.  Both trees'
  builders are read back through the real upstream parser
  (`kernelci.runtime.lava.Callback`): kcilib's by `scripts/tools/verify-lava-body.py`,
  the new tree's by `docs/gui-rework/tools/verify_callback_body.py` - four cases
  each (a passing and a failing boot, a failing TAP row with tuxrun exiting 0, a
  no-TAP JobError, tuxrun refusing the flags).  `python3 verify.py` runs the new
  tree's; kcilib's copy went with the old tree.
* **the exit codes** - 0 pass, 1 test failure, 3 infrastructure.  `3` is LAVA's
  *incomplete*: "we never got a verdict", which must stay distinguishable from
  "the tests failed".

## Status

The rewrite is complete, verified and adopted: the old tree (`scripts/`,
`run.sh` and `kcilib/`) is deleted, every command is a root entry point, the
deployment half lives in `deploy/`, and `python3 verify.py` is the gate.  The
tables below record what replaced what.

The upstream state (the PR1 test profile, its review thread, the blockers, and
the honest limits of what has been tested) lives in `docs/` -
`UPSTREAM-BLOCKERS.md` describes the *shipping* tree, and its numbers are
measurements from the dates it names, not standing claims.  Two of those facts
are worth repeating here because they are the deliverable rather than the
tooling: the test profile (`config/pr1-config.patch`,
4 YAMLs) is ready and the official scheduler renders 3 job definitions from it,
and the config-drift / regression-trend tooling reads the production history
back correctly.

## Adopting the new tree: what replaced what

| shipping | new | done? |
|---|---|---|
| `./run.sh fetch [--kvm]` | `python3 run_latest.py --test <name>` | **yes** |
| `./run.sh worker [--once]` | `python3 pull_worker.py [--once]` | **yes** |
| `./run.sh build index\|jobs\|todo\|summary` | `python3 table.py index\|jobs\|todo\|summary` | **yes** |
| `./run.sh run` | `python3 table.py run` | **yes** |
| `./run.sh results` | `python3 results.py` | **yes** |
| `./run.sh drift` | `python3 drift.py` | **yes** |
| `./run.sh dashboard` | `python3 gui.py` | **yes** |
| `./run.sh prune [--keep N] [--dry-run]` | `python3 prune.py [--keep N] [--dry-run]` | **yes** |
| `./run.sh provision` | `python3 provision.py` | **yes** |
| `./run.sh report` | `python3 report.py` | **yes** |
| `./run.sh trend` | `python3 trend.py` | **yes** |
| `./run.sh verify` | `python3 verify.py` | **yes** - the old gate went with `kcilib`; the new one is `verify.py` |
| `deploy/setup.sh` \| `deploy/stack.sh [--seed]` \| `deploy/stop.sh` | `deploy/` - the deployment half has its own directory now |

**Two of these rows looked like one-line swaps and were not**, and what they needed
is worth knowing before repointing anything else:

* `drift`: the new reader is the same reader the page uses, but its CLI with no
  `--older`/`--newer` passed `--job` to `getdays()` as a *tree* (`lib/drift.py`), so
  `--job kbuild-gcc-14-riscv` asked production for a tree of that name, was told
  `total=0`, and ended in a `ConfigError` traceback.  It now asks for the job's whole
  history with `state=done`/`result=pass` - the old tool's selection.  And `drift.py`
  read the method `drifted` as an attribute, so it exited **1 whatever the answer
  was**; the one thing that command promises is that exit status.  Verified on
  production: both readers pick older `6aaf2335…` / newer `6aaf3175…`, both find 0
  differences, both exit 0.
* `prune`: the old rule read the served build out of `work/env/build.env` and each
  directory's `node.json`.  Neither exists in the new tree, so
  `publish_local()` now records the act - `var/state/served.json` names the build
  `var/serve/Image` is - and `lib/retention.py` protects it by that id.  An image
  with no record is reported (`! … nothing is protected by provenance`), never
  guessed at.

Where a flag set differs, the new entry's own flags win: the worker has no
`--tuxrun-bin` (it resolves `tuxrun` from PATH), no `--output-dir` (consoles go
to `var/logs/`) and no `--max-timeout` (`lib/config.py` carries the run timeout
and `lib/runner.py` the tuxrun ceiling); the page
has no `--host`, `--db` or `--no-api`; `fetch` has no `--job` or `--kvm-full`.

