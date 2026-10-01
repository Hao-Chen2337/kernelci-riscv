# Command reference

Every flag of every command. For the command sequence alone, read [`RUNBOOK.md`](RUNBOOK.md).
Every entry point also documents itself: `python3 <entry>.py --help`.

Build ids below are written as `<id>` — they are addresses into a moving stream and age within
days.

---

## Three verbs that look alike and are not

| verb | what actually happens | where it lands |
|---|---|---|
| **index** | record that a build *exists*, as a card | `var/state/builds.json` |
| **pull** | download its bytes (kernel, modules, kselftest) | `var/downloads/<id>/` |
| **run** | boot + test it under QEMU, write a verdict | `var/results/<id>/` |

A card is not a download, and a download is not a run. Three separate facts, three separate files.

`index` cannot tell you "here is what I just added" — it folds new cards in and reprints *the whole
table*, newest first. So "what did I actually pull or run" is answered by `results.py` (ran),
`table.py summary` (pulled), and `table.py todo` (owes) — never by `index`.

---

## The shared run flags

Defined once in `lib/config.py`. Three entry points take the whole set — `table.py run`,
`run_latest.py`, `runday.py`. Two take less: `pull_worker.py` has its own parser and takes six of
the eight (`--rootfs` and `--callback-url` would be accepted and change nothing, so it does not
offer them), and `provision.py` declares its own three instead (`--tree`, `--branch`, `--api-url`).

| flag | what it does | default |
|---|---|---|
| `--api-url URL` | which API to talk to | `$KCI_API_URL`, else `127.0.0.1:8001` (`run_latest.py`/`provision.py` default to production) |
| `--device D` | the tuxrun device | `qemu-riscv64` |
| `--container-runtime R` | what tuxrun runs the dispatcher image in | `docker` |
| `--tuxrun-bin P` | the tuxrun binary | `$TUXRUN_BIN`, else `tuxrun` |
| `--timeout S` | per-job timeout, seconds (must be ≥ 1) | `1800` |
| `--parameter K=V` | an extra tuxrun parameter, repeatable | none |
| `--rootfs P` | **no reader** — parsed, then dropped | `""` |
| `--callback-url U` | post the result here too (`""` = ledger only) | `""` |

`--parameter` refuses anything that is not `K=V` (exit 3). `--callback-url` is how a one-shot
`table.py run` reports; the worker's sinks come from the job definition instead. `--rootfs` is the
one flag here that goes nowhere: the guest disk comes from the job definition's own artifact, so
setting this changes nothing.

---

## `table.py` — the local build table, offline

```bash
python3 table.py {index|index-pull|jobs|todo|summary|pull|run}
```

| subcommand | what it does |
|---|---|
| `index` | ask the API which builds exist and record the window in `var/state/builds.json` |
| `index-pull` | `index` that window, then `pull` the builds named with `--build` |
| `jobs` | one build's three tests, with the reason for each that cannot run |
| `todo` | the table minus the ledger: what has not run yet, and why |
| `summary` | counts by tree and verdict, plus what is on disk |
| `pull` | fetch the named builds' artifacts (`--build`, repeatable; none = every build) |
| `run` | run the pairs, here, with no queue and no callback — the same `Job.run()` as the worker |

| flag | what it does | default |
|---|---|---|
| `command` | the positional above | (required) |
| `--build ID` | one build id; repeat for several (`todo`/`pull`/`run`/`index-pull` — `jobs` reads only the first) | none |
| `--test T` | one of `boot`/`kselftest-riscv`/`kselftest-kvm`; repeat (`jobs`/`todo`/`run`) | all three |
| `--pair ID:T` | one `<build_id>:<test>`, repeatable; names the pairs themselves and **wins over** `--build`/`--test` | none |
| `--days N` | how many days back `index` asks for | `7` |
| `--tree T` | one tree name, repeatable; `index` registers each (none = any) | any |
| `--limit N` | the window size `index` asks for | `200` |
| `--no-api` | `index` without talking to the API (offline) | off |
| `--redo` | run even what the ledger already has a record for (`run`) | off |
| *(run flags)* | the shared set | see above |

Three things worth knowing before you type them:

- **`pull` with no `--build` acts on every build in the table**, and at least one of them has no
  `modules` URL — so that call always ends in exit 3. Name the builds you want.
- **`run --build <id>` needs a build whose artifacts are already on disk** for the test you ask
  for; `Job.make()` fetches them, but the build must declare them. One unfetchable build does not
  cancel the other forty-nine: each is its own attempt, the failure is recorded with its error,
  and the ledger skips it next time.
- **`--pair` names the pairs, `--build`/`--test` multiply them.** `--build A --build B --test boot`
  is the cross product (every build × every test); `--pair A:boot` is exactly one run. A `--pair`
  with no colon is refused.

**Output.**

`index` / `index-pull` print the whole table, newest first. A card is `id  label  …`, and the
label reads `tree-branch-arch-defconfig`:

```text
<id>  mainline-master-riscv-defconfig   ...
```

`summary` adds a `pulled-artifacts` column — `kernel modules kselftest` when all three are on
disk, `-` when nothing is — then the ledger at the end:

```text
--- <id> (3 record(s), 3 pass)
  kselftest-kvm            pass   exit=0   table   2026-09-29T16:54:43Z  12 selftests: 9 pass, 0 fail, 3 skip
  kselftest-riscv          pass   exit=0   table   2026-09-29T16:01:42Z  10 selftests: 10 pass, 0 fail, 0 skip
  boot                     pass   exit=0   table   2026-09-29T16:01:29Z  guest booted
```

`todo` is one `(build, test)` pair per line with the exact file it is missing; a build already run
prints nothing:

```text
<id>  boot             kernel: not downloaded yet (.../Image)
<id>  kselftest-riscv  kernel: not downloaded yet (...); kselftest: not downloaded yet (...)
```

`pull` prints `pulled <id>` per build and ends in exit 0 or 3.

`run` prints the `tuxrun` line it is about to execute, then one verdict line per pair — and its
exit status **is** the verdict:

```bash
$ python3 table.py run --build <id> --test boot
running: boot: tuxrun --runtime docker --device qemu-riscv64 --kernel file:///.../var/downloads/<id>/Image --boot-args rw --parameters cpu=rv64,v=true,ssnpm=true
pass       boot             <id>  guest booted      # exit 0, ~10 s
```

Note `--kernel file:///...`: a command-line run starts a **local file**; a dispatched job starts the
one the local stack serves.

`pull` needs the card to already exist — that is the only reason `index-pull` exists, as the one
command that does `index` and `pull` for the same build in one go.

---

## `results.py` — read the ledger back

```bash
python3 results.py [--build ID] [--test NAME] [--list] [--json]
```

| flag | what it does | default |
|---|---|---|
| `--build ID` | only records for this build | all builds |
| `--test NAME` | only this test (one of the three) | all tests |
| `--list` | the build ids the ledger has | — |
| `--json` | machine-readable output | off |

**Effect.** One record per line: build, test, verdict, exit, **writer** (`table` / `worker` /
`fetch` / `runday`), timestamp, reason — newest first. Needs no API, no container, no stack. Exit 0 even
when there is nothing to show; an empty ledger is an answer, not a failure. There is **no
`--limit`** — `python3 results.py --test boot --limit 5` is refused by argparse (exit 2).

---

## `drift.py` — configuration drift

```bash
python3 drift.py [--older ID --newer ID] [--older-config F --newer-config F] \
                 [--job JOB] [--max-lines N] [--json] [--api-url URL]
```

| flag | what it does | default |
|---|---|---|
| `--job NAME` | the job whose builds to compare | `kbuild-gcc-14-riscv` |
| `--older ID` / `--newer ID` | the two builds to compare | the two newest *passing* builds of the job |
| `--older-config F` / `--newer-config F` | two local `.config` files — fully offline, no API | — |
| `--max-lines N` | how many diff rows to print (0 = all; negative refused) | `0` |
| `--json` | machine-readable output | off |
| `--api-url URL` | which API resolves the ids | local |

**Effect.** Two builds' `.config` compared: `--- added`, `--- removed`, `--- changed`.

```text
older: <id>
newer: <id>
no drift: the two configs hold the same options
```

**Exit 1 is the answer itself** ("there is drift"), so it works directly as a script gate: 0 =
identical, 1 = drift, 3 = infrastructure. Two costs: the ids must be **API-resolvable** (it scans
the recent nodes via `--api-url`; cards in `var/state/builds.json` do not help), and it
re-downloads both `.config` files (~194 KB each) every time. Passing
`--older-config`/`--newer-config` makes it fully offline — but give *both* or *neither*: one file
alone is refused (exit 3), not silently treated as "no files".

Without `--older`/`--newer` it uses the two newest passing builds — the comparison that matters
after a toolchain bump.

---

## `trend.py` — regression analysis

```bash
python3 trend.py [--job NAME] [--api-url URL]
```

| flag | what it does | default |
|---|---|---|
| `--job NAME` | a job node name to read, repeatable | the three pull-lab jobs |
| `--api-url URL` | which API's history | local |

**Effect.** Reads history **by job node name** (not by test), oldest to newest, each node with the
commit it ran:

```text
== baseline-riscv-pull-labs ==
  <timestamp>  <commit>  pass  <id>
  <timestamp>  <commit>  pass  <id>
  -> 4 pass / 0 fail, 0 regression(s)
```

A **regression is a pass → fail transition**, so a first-ever `fail` is not one. The summary line
counts `incomplete` too (as a third number) when it is non-zero. There is no `--test` (exit 2 if
you try).

A red trend is a *result*, not an error: `trend.py` exits `0` either way, and `3` only when the
API or the flags are impossible.

---

## `run_latest.py` — re-run the newest production build here

```bash
python3 run_latest.py [--test T] [--kvm] [--tree T] [--branch B] [--out-dir D] [--provision-only]
```

| flag | what it does | default |
|---|---|---|
| `--test T` | which test(s), repeatable | all three |
| `--kvm` | the curated `kselftest-kvm` subset (one run, not all three) | off |
| `--tree T` | which tree | `riscv` |
| `--branch B` | which branch | (none) |
| `--out-dir D` | **no reader** — declared, never read | — |
| `--provision-only` | publish this deployment's own kernel and record it, run nothing | off |
| *(run flags)* | the shared set, and **the API defaults to production** | see above |

**Effect.** The whole one-shot line in one command: ask the API for the newest usable build, make
it local, pick the tests, run them, exit with the verdict (0 pass / 1 fail / 3 infra). It points
tuxrun at `file://` URLs.

---

## `runday.py` — a day's builds

```bash
python3 runday.py [--day ISO] [--days N] [--test T] [--redo] [--limit N] [--tree T] [--branch B]
```

| flag | what it does | default |
|---|---|---|
| `--tree T` | which tree | `riscv` |
| `--branch B` | which branch | (none) |
| `--day ISO` | one calendar day (`YYYY-MM-DD`, UTC); **replaces** `--days` | — |
| `--days N` | how many days back to look | `1` |
| `--test T` | which test(s), repeatable | all three |
| `--redo` | run even what the ledger already has | off |
| `--limit N` | how many builds (must be ≥ 1) | `20` |
| *(run flags)* | the shared set | see above |

**Effect.** A **rotation, not a queue**: by default yesterday's builds, skipping every pair the
ledger already has a record for. `--redo` is the only way back to re-running. Exit 0/1/3.

---

## `pull_worker.py` — the resident worker

```bash
python3 pull_worker.py [--platform qemu-riscv64] [--runtime pull-labs-riscv] \
                       [--container-runtime docker] [--state-file F] \
                       [--poll-period 5] [--max-retries 5] [--once] [--since ISO] \
                       [--api-url URL] [--device D] [--tuxrun-bin P] [--timeout S] [--parameter K=V]
```

| flag | what it does | default |
|---|---|---|
| `--platform P` | only claim jobs for this platform (`data.platform`) | `qemu-riscv64` |
| `--runtime R` | only claim jobs of this pipeline runtime (`data.runtime`) — **the lab name, not the container runtime** | `pull-labs-riscv` |
| `--container-runtime R` | what tuxrun runs the dispatcher image in | `docker` |
| `--state-file F` | the cursor file | `var/state/worker-state.json` |
| `--poll-period S` | seconds between polls (≥ 1) | `5` |
| `--max-retries N` | event-fetch retries (≥ 1) | `5` |
| `--once` | work the current queue and return (do not loop) | off |
| `--since ISO` | move the cursor back to this time, then claim from there | — |
| `--api-url U` | which API | local |
| `--device D` | the tuxrun device a job definition that names none runs on | `qemu-riscv64` |
| `--tuxrun-bin P` | the tuxrun binary | `$TUXRUN_BIN`, else `tuxrun` |
| `--timeout S` | per-job timeout, seconds | `1800` |
| `--parameter K=V` | an extra tuxrun parameter, repeatable | none |

**Effect.** Polls the events feed, **only from its own cursor onwards**, claims the nodes that
match the platform/runtime filters, runs each with the same `Job.run()` as everything else, and
posts a LAVA-compatible callback body. `--once` is not "claim one job": it works the **current
queue** and returns. `--runtime` is the pipeline's lab, `--container-runtime` is the container
engine — collapsing them is how a worker ends up rejecting every node.

**Not usable end to end yet.** The pipeline is dispatching this lab's jobs and they are visible
on the production API, but nothing claims them, so they end in timeout — the worker has no
callback token yet. It has only been exercised against the local stack's API. Everything above
describes what the code does, not yet what production does.

---

## `report.py` — what the pipeline did with the jobs

```bash
python3 report.py [--name NAME] [--limit N] [--api-url URL]
```

| flag | what it does | default |
|---|---|---|
| `--name NAME` | a job node name, repeatable | the three pull-lab jobs |
| `--limit N` | how many nodes per name (≥ 1) | `3` |
| `--api-url U` | which API | local |

**Effect.** The newest `N` nodes of each name, newest first: `created`, `state`, `result`, `id`.

---

## `prune.py` — retention

```bash
python3 prune.py [--keep N] [--dry-run] [--downloads DIR]
```

| flag | what it does | default |
|---|---|---|
| `--keep N` | newest builds to keep (must be ≥ 1) | `5` |
| `--dry-run` | print the decision, delete nothing | off |
| `--downloads DIR` | the directory to prune | `var/downloads/` |

**Effect.** Keeps the newest `N` builds by mtime **plus the one `var/state/served.json` names**.
`--keep 0` is refused (exit 3). Always run `--dry-run` first; it only touches `var/downloads/`,
never `var/results/`.

---

## `gui.py` — the page

```bash
python3 gui.py [--port 8079] [--rows 25] [--refresh 0] [--api-url URL]
```

| flag | what it does | default |
|---|---|---|
| `--port N` | the port to serve on | `8079` |
| `--rows N` | rows per table page | `25` |
| `--refresh S` | auto-refresh seconds | `0` (off) |
| `--api-url U` | which API the page reads | local |

**Effect.** Serves the console over HTTP. Read-only apart from its buttons, and **every button is
one command of this tree**. Routes: `/`, `/builds`, `/jobs`, `/worker`, `/runs`, `/analysis`,
`/trend`, `/local/<build_id>`, and the machine endpoints `/summary.json`, `/api/analysis/drift`,
`/api/analysis/trend`.

---

## `provision.py` — pin the newest passing build

```bash
python3 provision.py [--tree riscv] [--branch B] [--api-url URL]
```

| flag | what it does | default |
|---|---|---|
| `--tree T` | which tree's builds to choose from | `riscv` |
| `--branch B` | which branch | (none) |
| `--api-url U` | which API to read | production |

**Effect.** Takes the newest *passing* production build, pulls only the kernel, republishes
`var/serve/Image`, and rewrites `var/state/served.json`. It changes deployment state; it is not a
downloader.

---

## `deploy/stack.sh` — start the stack

```bash
deploy/stack.sh [--seed] [--worker]
```

| flag | what it does |
|---|---|
| *(none)* | start the API stack + artifact server + callback + scheduler |
| `--seed` | also POST a kbuild seed node (from `var/state/served.json`, or the `SEED_*` variables) |
| `--worker` | seed + run the pull worker in the foreground |

---

## `deploy/instance-init.sh` — generate secrets and config

```bash
bash deploy/instance-init.sh [--force] [--quiet] [--skip-token]
```

| flag | what it does |
|---|---|
| *(none)* | generate the runtime config, idempotently |
| `--force` | regenerate the SSH key pair **and** overwrite `kernelci-api/.env` (invalidates every existing JWT) |
| `--quiet` | suppress the per-step narration, keep errors |
| `--skip-token` | skip the API-token step (offline / test runs) |

---

## `verify.py` — the gate

```bash
python3 verify.py            # everything
python3 verify.py --quick    # leaves out the slow page renders
python3 verify.py --base URL # also sweep a running page over HTTP (accept.py)
```

| flag | what it does | default |
|---|---|---|
| `--quick` | skip the slow checks (the `pages` renders) | off |
| `--base URL` | add the `accept` check, sweeping a live page at `URL` | off |

**Effect.** One command, exit status is the answer. It runs *every* check and reports all of them.
Exit 3 when any failed. The checks: `ruff`, `i18n`, `structure`, `callback body`, `dom`/`notice`,
`config cache`, `form body`, `ledger history`, `callback override`, `pages`, `pipeline yaml`, and
`accept` (only with `--base URL`). Most checks' scripts are in `tools/gate/`; the `pipeline yaml`
one is upstream's — `kernelci-pipeline/tests/validate_yaml.py`.

---

## The cheat sheet

```bash
# query production, register cards (filtered by tree, window)
python3 table.py index --api-url https://api.kernelci.org --tree mainline --tree next --days 3

# what's on disk + what ran
python3 table.py summary

# what still owes work, and why
python3 table.py todo --build <id>

# download + run, one command (card must exist)
python3 table.py index-pull --api-url https://api.kernelci.org --tree mainline --days 3 --build <id>

# download, then run (separately)
python3 table.py pull --build <id>
python3 table.py run --build <id> --test boot

# what this machine ran
python3 results.py

# did the build drift? did the jobs turn red?
python3 drift.py --older <id> --newer <id> --api-url https://api.kernelci.org
python3 trend.py --api-url https://api.kernelci.org
```

Exit codes throughout: `0` pass (or "nothing owed"), `1` a test actually failed, `3`
infrastructure — a bad flag, a dead API, an artifact that never arrived. A `3` is never a test
result; it is the machine telling you the machine broke, not the kernel.
