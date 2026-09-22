# Runbook

Operate this tree from the repository root. Every command is an entry point there, run as
`python3 <entry>.py`, and `python3 verify.py` is the gate. `run.sh` and `scripts/` are gone.

## What you need

```bash
python3 -m pip install tuxrun -r requirements.txt
# requests + PyYAML (fetch/worker), uvicorn + fastapi + PyJWT + toml (the callback runs on
# the host), ruff (verify)

sudo apt-get install -y docker.io docker-compose-v2 git curl patch openssh-client \
                        e2fsprogs python3 python3-pip
```

No virtualenv: the entries run under the `python3` on `PATH`. `patch` is for the step below,
`e2fsprogs` is for the worker (it bakes a 4GB ext4 image with `mkfs.ext4`), and
`openssh-client` is for `setup` (it runs `ssh-keygen` for the key pair the scheduler uploads
job definitions with).

**One-time patch, for riscv kselftest support in tuxlava.** Apply it where the package
actually is, and check that the test appears:

```bash
patch -p1 -d "$(python3 -c 'import tuxlava,os;print(os.path.dirname(os.path.dirname(tuxlava.__file__)))')" \
  < config/tuxlava-kselftest-riscv.patch

tuxrun --list-tests | grep -w kselftest-riscv    # must print it
```

`deploy/setup.sh` only **warns** when this is missing and still exits 0. Without it, tuxrun
derives its `--tests` choices from tuxlava and exits 2 much later.

**One directory rule.** `kernelci-api/docker/storage/data` and `kernelci-api/docker/ssh/user-data`
must be writable by **uid 1000** - the `kernelci` user inside the ssh container that stores job
definitions and result logs. Another owner makes the scheduler's upload fail *silently*: job
nodes stay `available` and `deploy/stack.sh --seed` reports "no job node appeared within 90s".
`stack.sh` checks this and prints the `chown` to run.

## Five minutes

```bash
python3 verify.py --quick                        # is this tree healthy?
python3 table.py index --days 1                  # ask the API which builds exist
python3 table.py summary                         # what the local table now holds
python3 table.py todo                            # what has no record yet, and what it is missing
python3 table.py pull --build <id>               # fetch that build's artifacts
python3 table.py run --build <id> --test boot    # run it - the exit status IS the verdict
python3 results.py --test boot                   # read the ledger back
python3 gui.py                                   # the same thing as a page: http://127.0.0.1:8079
```

## Exit codes

Every entry point keeps the same convention:

| code | meaning |
|---|---|
| **0** | the thing happened (test passed, no drift, everything green) |
| **1** | the test ran and **failed**; for `drift.py`, the two configs differ |
| **2** | argparse refused the command line |
| **3** | **infrastructure**: an artifact never arrived, the API is unreachable, a gate check failed |

This is deliberate. `table.py run`'s exit status *is* the verdict of the test, and "the artifact
was never downloaded" is not a test result - so it is 3, never 1.

## The twelve commands

Each one documents itself: `python3 <entry>.py --help`.

| command | what it is for |
|---|---|
| `table.py index` | ask the API which builds exist, and record the window in the local table |
| `table.py pull` | fetch one build's artifacts (`--build`, repeatable) |
| `table.py run` | run a test on a build (`--test`, `--redo`) |
| `table.py jobs` / `todo` / `summary` | one build's tests and why each cannot run / the pairs with no record / what the table holds |
| `results.py` | the ledger, read back (`--build`, `--test`, `--json`) |
| `drift.py` | two builds' `.config` compared - **the configuration drift**. exit 0 none, 1 drift, 3 infrastructure |
| `trend.py` | pass/fail and regressions (pass -> fail) over time, **by job name** - **the regression analysis** |
| `run_latest.py` | the newest production riscv build, fetched and run once here |
| `runday.py` | a day's builds, skipping whatever the ledger already has |
| `pull_worker.py` | the resident worker: claim jobs from the events API, run them, report back |
| `provision.py` | pin the newest passing production build and publish the `Image` the local stack seeds from |
| `report.py` | the newest node of each pull-lab job name, as the stack sees it |
| `prune.py` | retention for `var/downloads/` - the newest N plus the one this deployment serves |
| `gui.py` | the page over HTTP (default port 8079) |
| `verify.py` | the gate: everything that must be true before this tree is deployed |

Three things worth knowing before you type them:

- **`pull` with no `--build` acts on every build in the table**, and at least one of them has no
  `modules` URL - so that call always ends in exit 3. Name the builds you want.
- **`table.py run --build <id>` needs a build whose artifacts are already on disk** for the test
  you ask for (see the table below). `Job.make()` fetches them, but the build must declare them.
- **`pull_worker.py --once` is not "claim one job"**: it works the **current queue** and returns.
  The worker asks the events feed and only from its own cursor onwards, so a first run can
  correctly find nothing.

## Which artifacts a test needs

Nothing on the command line names an artifact. A test does, in one table:

| `--test` | `needs` (`lib/tests.py`) | artifacts pulled | files on disk |
|---|---|---|---|
| `boot` | `("kernel",)` | kernel | `Image` |
| `kselftest-riscv` | `("kernel", "kselftest")` | kernel, kselftest | `Image`, `kselftest.tar.xz` |
| `kselftest-kvm` | `("kernel", "modules", "kselftest")` | kernel, modules, kselftest | `Image`, `modules.tar.xz`, `kselftest.tar.xz` |

A run with no `--test` covers all three (`DEFAULT_TESTS`). No entry point has an
`--artifact`/`--want` flag. `ARTIFACTS` also defines a fourth, `config` -> local `.config`, and
**no test needs it**: it is read only by `drift.py`.

## The workspace

`var/`, and only `var/`. `lib/layout.py` owns every path in it, and `$KCI_WORK_DIR` moves it
anywhere. Its ledger (`var/results/`, one file per (build, test)) is history and is never pruned;
everything else there can be regenerated. `$KCI_RESULTS_DIR` replaces the ledger directory
alone, which is how a test or a second deployment runs without touching real history.

## The local stack

```bash
deploy/setup.sh                # upstream clones + the PR1/bullseye/nginx patches + runtime config
python3 -m pip install -r kernelci-core/requirements.txt   # deps of the cloned callback
python3 provision.py           # fetch + bake what a run needs
deploy/stack.sh --seed         # api/db/redis/storage/ssh + artifact server + real callback + scheduler, then seed
python3 pull_worker.py --once  # execute the queued jobs and report back
python3 report.py              # what the API did with them
deploy/stop.sh                 # stop the stack (compose data stays in volumes)
```

`setup.sh` applies its patches only when they are not already applied, and generates what must
not live in git, so nothing is filled in by hand: `kernelci-api/.env`, the SSH key pair, and
`KCI_API_TOKEN` in `kernelci-pipeline/.env` (**never committed**).

Four things stop a first run:

- **A stale or dead proxy** hangs the upstream `git clone` with no output. Fix the proxy, or
  bypass it for one command with `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY …`
  (`KCI_BYPASS_PROXY=1` for the scripts' own downloads).
- **Several GB of images** on first use: ~4 GB at `stack`, then the tuxrun runtime images on the
  first job.
- **The seed tree is checked before anything starts.** `stack --seed` asks the scheduler's own
  rule engine whether the runtime would accept it, and stops *before* starting the services if
  it would not. Relabel the seed (`SEED_TREE=<allowed tree> deploy/stack.sh --seed`) or add the
  tree to `runtimes.pull-labs-riscv.rules.tree` in `kernelci-pipeline/config/pipeline-pull-labs.yaml`.
- **The upstream image has three defects** in the revision this deployment uses:
  `POST /latest/user/login` (and logout/forgot-password/reset-password) return **405**,
  `/latest/docs` and `/latest/openapi.json` return **404**, and a fresh database gets no initial
  admin. That is why `setup` mints the admin and the API token itself, and why **password reset
  is unavailable**.

Seeding is a shortcut **around** the build, not a build: the `checkout` and `kbuild-gcc-14-riscv`
nodes are declarations carrying pre-existing artifacts (`artifacts.kernel` is this deployment's
own artifact server), so a seeded kernel URL names the deployment that seeded it. The three job
nodes come from the official scheduler reading `jobs-pull-labs.yaml` and are the real thing.

**A second, isolated deployment on one machine.** The compose project decides which volumes (and
therefore which database) a deployment owns; every port is overridable:

```bash
export KCI_COMPOSE_PROJECT=kcirv-clean KCI_API_PORT=18001 KCI_STORAGE_PORT=18002 \
       KCI_CB_PORT=18003 KCI_SSH_PORT=18022 KCI_MONGO_PORT=18017 KCI_SERVE_PORT=18999 \
       KCI_API_URL=http://127.0.0.1:18001 KCI_RESULTS_DIR=var/results-kcirv-clean
```

Defaults are 8001 api, 8002 storage, 8003 callback, 8022 ssh, 8017 mongo, 8999 artifact server.
Every port is probed before a service starts on it, and a conflict is refused by name - the port,
the holder and the `KCI_*_PORT` variable that moves this deployment. The two cannot run *at the
same time* (kernelci-api's compose file hardcodes `container_name`), so stop the first stack
before starting the second.

`$KCI_RESULTS_DIR` is what keeps the two ledgers apart; without it the second deployment writes
its history into the first one's `var/results/`. It moves that directory alone - `var/state/`,
`var/serve/` and `var/downloads/` stay shared by both.

Two things the second deployment cannot inherit, and neither of them is a port:

- **The ssh image.** The `ssh` service carries `build:` and no `image:`, so compose names its
  image after the project (`<project>-ssh`) and builds it - which on a dockerd with no registry
  route dies on `debian:bullseye-slim`. Tag what is already on the machine instead
  (`docker tag kcirv-ssh:latest kcirv-clean-ssh:latest`) and compose reuses that.
- **An admin, and a token, in the new database.** The initial admin and `KCI_API_TOKEN` are made
  by `deploy/instance-init.sh` against the database that existed *when it ran*, so the second
  deployment starts with an empty one and its scheduler dies on `401 Unauthorized` at
  `/latest/subscribe/node` - which is what makes `stack.sh --seed` exit 1 while every container
  is up and healthy. With this `KCI_*` environment still exported, run `deploy/instance-init.sh`
  and then `deploy/stack.sh --seed` **again**: the first mints the admin and the token, the second
  is what starts the scheduler that needed it. Both `.env` files are shared, so the way back to
  the first deployment is the same two commands with the first deployment's ports - its
  `stack.sh --seed` keeps failing on `401` at port 8001 until they are run.

## The gate

```bash
python3 verify.py            # everything
python3 verify.py --quick    # leaves out the slow page renders
```

It runs every check and reports all of them - a gate that stops at the first failure hides the
other nine. Exit status is 3 when any of them failed.

| check | what it covers |
|---|---|
| `ruff` | style, imports, syntax |
| `i18n` | every string the page prints exists in both languages |
| `structure` | one owner per decision, one exit path |
| `callback body` | the LAVA body, read back by the **real upstream parser** |
| `dom` / `notice` | the page's script, driven in node against a DOM stub |
| `config cache` | one request parses the workspace once |
| `form body` | a POST carries the form's own body |
| `pages` | every page renders, in both languages (the slow one) |
| `pipeline yaml` | the PR1 test profile still parses (**the deliverable**) |
| `accept` | the page over HTTP, only with `--base URL` |

`callback body` and `pipeline yaml` need the upstream clones and report themselves as skipped
until `deploy/setup.sh` has made them. The checks' own scripts ship with this tree
(`tools/gate/`), so a fresh clone can run the gate immediately: 8 passed, 2 skipped, exit 0.

## When something goes wrong

**`pull` dies on a proxy TLS drop, and the retry resumes it.** One artifact, three attempts,
giving up with exit 3. The failed run leaves a `.part` file, and **the same command again**
prints `resuming <name> at <n> bytes` and exits 0 - bytes already on disk are proven against
this copy's own pull record and skipped. Re-running is the fix.

**An artifact that 404s, or one the build never declared.** Both fail *before* the network, and
the act **is** recorded with its error. `pull` catches it per build, prints `! <id>: <error>` and
carries on with the rest, ending in exit 3. A real 4xx is permanent: it leaves on the first
attempt instead of going through the three-attempt loop that transport errors get.

**`drift.py` refuses ids the API cannot resolve.** Each id is resolved through the API the
`--api-url` names, by a scan capped at 1000 nodes; cards in `var/state/builds.json` do not help.
Use `--older-config`/`--newer-config` with local files to compare without the API.

**The worker's poll.** The events endpoint can time out; the line to look for in
`var/runs/<stamp>-worker/run.log` is `! events fetch failed (n/5): <url> did not answer: …`.
Read it as transient: the failure is retried five times, and the line names the URL, the attempt
and the exception.

**A ledger record that will not parse.** `Ledger.read()` raises on purpose ("a ledger that
quietly loses rows is worse than none"), and every entry point turns that into exit 3 with a
message rather than a traceback.

## Where the rest is

- `python3 <entry>.py --help` - the flags, from the entry itself. The deployment scripts do
  **not** take one, so `deploy/stop.sh --help` stops the stack and `deploy/setup.sh --help` runs
  the setup - both ignore the argument rather than refusing it. Their usage is the header comment
  at the top of each script; `deploy/stack.sh` is the one with a `# Usage:` line.
- **The test profile** the scheduler reads is YAML in the cloned upstream, applied by
  `config/pr1-config.patch`: the three `*-riscv-pull-labs` jobs in
  `kernelci-pipeline/config/jobs-pull-labs.yaml`, the `pull-labs-riscv` runtime in
  `pipeline-pull-labs.yaml`, and the scheduler entries in `scheduler-pull-labs.yaml`. What a test
  needs is in `lib/tests.py`.
