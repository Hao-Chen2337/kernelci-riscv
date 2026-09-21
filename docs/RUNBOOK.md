# Runbook

> All commands run from the repository root.  **`run.sh` is deleted** (2026-09-20):
> the command is the one named in each row, and `python3 verify.py` is the gate.

## Environment

- **system packages**: `docker` with the compose plugin, `git`, `curl`, `patch`
  (the tuxlava patch), `openssh-client` (`setup` runs `ssh-keygen` for the key
  pair the scheduler uploads job definitions with) and `e2fsprogs` (the worker
  bakes a 4GB ext4 image with `mkfs.ext4`). A bare Ubuntu has none of `patch`,
  `ssh-keygen` or `mkfs.ext4`, and each missing one stops a documented stage.
  On Debian/Ubuntu:
  `sudo apt-get install -y docker.io docker-compose-v2 git curl patch openssh-client e2fsprogs python3 python3-pip`
- **Python host packages**: `pip install tuxrun` alone is not enough - it only
  brings the fetch/worker dependencies (requests, PyYAML, jinja2) - so install
  this repository's list as well:

```bash
python3 -m pip install tuxrun -r requirements.txt
# requests + PyYAML (fetch/worker), uvicorn + fastapi + PyJWT + toml (the
# callback service `deploy/stack.sh` starts on the HOST), ruff (`verify`)
```

  There is no virtualenv requirement - the scripts run under the system
  `python3`. Once `setup` has cloned the upstreams, the callback also imports
  `kernelci-core` from that clone, so its requirements are needed as well:

```bash
python3 -m pip install -r kernelci-core/requirements.txt   # after deploy/setup.sh
```

- **one directory rule**: `kernelci-api/docker/storage/data` and
  `kernelci-api/docker/ssh/user-data` must be writable by **uid 1000** - that is
  the `kernelci` user inside the ssh container, which stores every job
  definition and result log through those bind mounts. A clone owned by root (or
  by any other uid) makes the scheduler's upload fail *silently*: job nodes stay
  `available` and `stack --seed` prints "no job node appeared within 90s".
  `stack` checks this and prints the `chown` to run; running `stack` as root
  fixes it automatically.
- Tier B (local full stack) additionally needs `KCI_API_TOKEN` (local API
  admin JWT, **never committed**) in `kernelci-pipeline/.env`; `deploy/setup.sh`
  generates it (see below)
- One-time patch for an already-installed tuxlava (riscv kselftest support).
  The directory is derived from tuxlava itself, never hardcoded: the old
  `site.getusersitepackages()` pointed at a directory that does not exist when
  tuxrun was installed system-wide (`patch: Can't change to directory`), so
  apply it where the package actually is, and check that the test class appears:

```bash
patch -p1 -d "$(python3 -c 'import tuxlava,os;print(os.path.dirname(os.path.dirname(tuxlava.__file__)))')" \
  < config/tuxlava-kselftest-riscv.patch
tuxrun --list-tests | grep -w kselftest-riscv    # must print it
```

## Commands

| Command | What it does |
|---|---|
| `deploy/setup.sh` (was `./run.sh setup`) | Clone core/api/pipeline + apply PR1/bullseye/nginx patches (skipped if already applied) + generate runtime config (`.env`, SSH keys, API token) + validate_yaml |
| `python3 run_latest.py [--kvm] [--test name]` | Tier A: re-run the newest production riscv build locally with tuxrun. The exit status **is** the verdict (0 pass / 1 test failure / 3 infrastructure error), and every run - including one that never reached tuxrun - is recorded in `var/results/<build-id>/<test>.json`. **This now runs the new tree** (`run_latest.py`): artifacts go to `var/downloads/`, and the old `--job`/`--kvm-full` flags are gone with it |
| `deploy/stack.sh [--seed]` (was `./run.sh stack`) | Tier B: start the local full stack (api/db/redis/storage/ssh + artifact server + real callback + official scheduler); `--seed` dispatches (overridable via `SEED_*` env vars).  It reads the new tree's workspace now: the artifact server serves `var/serve/`, the callback's config is rendered into `var/state/`, services are recorded in `var/state/stack-<project>.pids` (which `deploy/stop.sh` reads), and `--seed` takes the build from `var/state/served.json` - what `python3 provision.py` recorded - so the seeded nodes name the kernel that actually boots. `--seed` refuses up front when the runtime's rules would drop the seed's tree, naming the allowed trees and the `SEED_TREE` override (see Fresh deployment) |
| `python3 pull_worker.py [--once]` | Take jobs, execute, report back; `--once` exits after the existing queue; unposted results persist and are re-posted (never re-run) on the next start. **Now the new tree** (`pull_worker.py`): `tuxrun` comes from PATH, consoles are archived under `var/logs/`, and per-test ceilings are `lib/config.py`'s run timeout and `lib/runner.py`'s tuxrun ceiling |
| `python3 runday.py [--days N] [--day DATE]` | A day's builds: fetch → build → job for every build of that day, **skipping whatever the ledger already has** (`--redo` runs them anyway). `--day` is an ISO date (default: yesterday) and `--days` counts back from it; `--tree`/`--branch`/`--test`/`--limit` narrow the set. This is the rotation rather than the queue - it asks the API which builds exist, so it needs no stack running. **It has not been run end to end yet**: its code path (a day's builds minus the ledger) was exercised through `table.py` and the poller, not through this entry |
| `python3 report.py` | Recent baseline/kselftest node states |
| `python3 results.py [--build ID] [--json] [--list]` | Read the local result ledger, written by both `fetch` and the worker. Needs no API, so it still answers "what did this machine run" with the stack stopped. **Now the new tree** (`results.py`) over `var/results/<build-id>/<test>.json`; `$KCI_RESULTS_DIR` moves the ledger for a test or a second deployment |
| `python3 table.py {index\|jobs\|todo\|summary\|pull\|run}` | The local build table, **offline**: `index` asks the API which builds exist and registers them, `pull --build <id>` (repeatable) fetches one build's bytes, `jobs`/`todo`/`summary` print the table, what the ledger still owes and the tally, and `run` runs the `todo`. The table is `var/state/builds.json` and the bytes land under `var/downloads/`; `--no-api` keeps it from asking anything, `--redo` ignores an existing record. The page's buttons run these same subcommands |
| `python3 provision.py` | Pin the kernel this deployment serves: the newest production build of the tree that **finished and passed** is chosen, its kernel fetched, `var/serve/Image` published as a symlink to it, and the act recorded in `var/state/served.json` (build id, revision, artifact URLs, rootfs). **Now the new tree** (`provision.py` + `lib/build/`). An image already at `var/serve/Image` that the deployment never recorded is kept aside (`Image.kept-<stamp>`) rather than deleted, with a line saying so; identical bytes are simply replaced |
| `python3 prune.py [--keep N] [--dry-run]` | Retention for `var/downloads/` (one directory per fetched build): keep the newest N (default 5) plus the build this deployment serves. **Now the new tree** (`prune.py` + `lib/retention.py`); the served build is the one `var/state/served.json` names, which `publish_local()` writes when it publishes `var/serve/Image`. An unrecorded `var/serve/Image` is reported rather than guessed at; `--dry-run` prints the list and deletes nothing |
| `python3 verify.py` | The new tree's gate: ruff + i18n + structure + callback body (real upstream parser) + DOM + notice + two unit tests + every page rendered + the PR1 YAML, and `accept.py` with `--base`. `--quick` leaves out the page renders. `./run.sh verify` is gone with the old tree |
| `python3 drift.py` | Config drift between two builds. **Now the new tree** (`drift.py`): without `--older/--newer` it takes the newest two builds that finished and passed (the old tool's selection), exit 1 means drift, 0 no drift, 3 infrastructure |
| `python3 trend.py` | Regression pass-rates read from the **production API's history** - not this machine's ledger; the local view of what ran here is the page's `/analysis` |
| `python3 gui.py [--port 8079] [--rows 25] [--api-url URL]` | The page, at `http://127.0.0.1:8079` unless `--port` moves it: five pages (`builds`/`jobs`/`runs`/`worker`/`analysis`) behind one filter bar and one live panel. It is a viewer **and** a launcher - every button runs the command an operator would type, as an activity under `var/runs/`, one writer at a time. `/analysis` is where this deployment reads drift and trend (the two entries above are the same readers from a terminal), and the `api` box in its filter bar answers from `production`, `local` or any `http(s)` address **without a restart**. `--refresh` is accepted but not wired: the page polls every 2 seconds |
| `deploy/stop.sh` (was `./run.sh stop`) | Stop the whole local stack (incl. the docker compose API stack; data stays in volumes) |

## Fresh deployment (one go, no manual steps)

```bash
git clone https://github.com/Hao-Chen2337/kernelci-riscv.git && cd kernelci-riscv
python3 -m pip install tuxrun -r requirements.txt   # host deps (see Environment)
# step 0, once per machine: riscv kselftest support in the installed tuxlava
# (`setup` only WARNS when it is missing - the failure shows up much later)
patch -p1 -d "$(python3 -c 'import tuxlava,os;print(os.path.dirname(os.path.dirname(tuxlava.__file__)))')" \
  < config/tuxlava-kselftest-riscv.patch
deploy/setup.sh         # upstream clones + patches + runtime config (see below)
python3 -m pip install -r kernelci-core/requirements.txt   # deps of the cloned callback
python3 provision.py      # fetch + bake the artifacts a run needs
deploy/stack.sh --seed  # API/db/redis/storage/ssh + artifact server + callback + scheduler, then seed
python3 pull_worker.py --once  # execute the queued jobs and report back
python3 report.py         # results
```

Three things to know before the first run on a new machine:

- **A stale or dead proxy** makes the `git clone` above hang with no output
  before any script of ours is running: fix the proxy settings, or bypass them
  for that one command (`env -u http_proxy -u https_proxy -u HTTP_PROXY -u
  HTTPS_PROXY git clone ...`). The scripts themselves probe the network and
  print the exact settings that are broken; `KCI_BYPASS_PROXY=1 deploy/setup.sh`
  (or `fetch`/`stack`/`provision`) makes their downloads and clones ignore the
  proxy for that run.
- **Several GB of images** are pulled on first use: the API/db/redis/nginx
  images (~4 GB) at `stack`, then the tuxrun runtime images on the first job
  (`tuxrun-dispatcher` + `qemu-riscv64` + `gcc-14`/`clang-21`
  `riscv64-kselftest` ≈ 12.3 GB measured here). Docker Hub and ghcr.io both have
  to be reachable.
- **The seed is checked before anything starts.** `stack --seed` asks the
  scheduler's own rule engine whether the runtime would accept the seed's tree.
  If it would refuse it, the command stops *before* starting the services
  instead of waiting 90 s and ending with "no job node appeared", since the only
  trace of the refusal is one scheduler log line. The message names the allowed
  trees and the two ways out: relabel the seed
  (`SEED_TREE=<allowed tree> deploy/stack.sh --seed` - recorded in
  `var/state/seed.env` when the label disagrees with the build that boots), or
  add the build's tree to `runtimes.pull-labs-riscv.rules.tree` in
  `kernelci-pipeline/config/pipeline-pull-labs.yaml`. If the rule engine itself
  cannot be read (no `kernelci-core` checkout), the check says so and carries on;
  the wait then reports the scheduler's own rejection reason.

`setup` generates everything the runtime needs that must not live in git, so
nothing has to be filled in by hand:

- `kernelci-api/.env` — a fresh one is generated from `kernelci-api/env.sample`
  with `SECRET_KEY`, `MONGO_SERVICE`, `PUBLIC_BASE_URL` and the initial admin
  (`KCI_INITIAL_ADMIN_USERNAME=admin`, a random `KCI_INITIAL_PASSWORD`,
  `KCI_INITIAL_ADMIN_EMAIL` defaulting to `admin@kernelci.org` and used only
  when that account is created). An existing file is kept **as-is, not
  backfilled**: one left by an earlier deployment can still hold only the four
  keys the API itself reads (`SECRET_KEY`, `MONGO_SERVICE`,
  `KCI_INITIAL_PASSWORD`, `KCI_INITIAL_ADMIN_USERNAME`) and no
  `PUBLIC_BASE_URL`. `--force` regenerates it (a new `SECRET_KEY` invalidates
  every JWT).
- SSH keypair — `kernelci-pipeline/data/ssh/id_rsa_tarball` (private, `0600`)
  and `kernelci-api/docker/ssh/user-data/authorized_keys` (public, `0644`);
  lets the scheduler upload jobdefs to storage via scp.
- `KCI_API_TOKEN` in `kernelci-pipeline/.env` — verified against
  `/latest/whoami` before it is written. Two things in this kernelci-api
  revision make that non-obvious, and both are handled automatically:
  `POST /latest/user/login` is **not registered** (the versioned-app refactor
  drops the auth router), and the app never bootstraps the first admin either
  (`versioned_app`'s startup list omits `ensure_initial_admin_user`). So the
  token is minted with the API's own JWT strategy inside the `api` container,
  creating the admin first when the database is empty.
- It also works on an **empty database**: `stack --seed` creates the checkout
  node a kbuild node hangs off when the database has none.

`provision` downloads the kernel (`~/9MB`) and the rootfs (`~144MB`) and bakes
a 4GB ext4 image from it — a few minutes on first use, instant afterwards.
Interrupted transfers are resumed, not restarted: this CDN truncates large
downloads routinely. Kernel and modules come from the same production build,
recorded in `var/state/served.json` (`python3 provision.py` writes it), which
`stack --seed` then seeds from, so the
kernel served to the guest and the modules baked into the rootfs cannot drift
apart.

The worker also uses that ext4 image: it keeps the baked images it produces in
`var/baked/`, keyed by the rootfs and modules URLs it baked them from, so
the second kselftest job in a batch reuses the image instead of downloading
144MB and re-baking 4GB again (measured: 180.9s → 0.0s for the second job). The
directory is gitignored; it holds one entry per distinct (rootfs, modules) pair,
each 4GB sparse (~800MB on disk), and nothing ages them out - a build whose
`var/downloads/` copy `prune.py` removed will never be re-run from its cached
image, so those entries are safe to delete. An interrupted bake is never
published under a reusable name.

Both `.env` files and the keypair live in gitignored directories, so no secret
is ever committed. To force-refresh the keys or the `.env`:

```bash
bash deploy/instance-init.sh --force   # then restart the stack
```

### Known limitations of the upstream image

`kernelci/staging-kernelci:api` ships three upstream kernelci-api defects
(unfixed upstream as of the revision this deployment uses): `POST
/latest/user/login` — and logout/forgot-password/reset-password — return
**405**, `/latest/docs` and `/latest/openapi.json` return **404**, and a fresh
database gets no initial admin. So `deploy/setup.sh` mints the admin and the API
token itself, and `KCI_API_TOKEN` in `kernelci-pipeline/.env` is the supported
way to authenticate; **password reset is unavailable**. `setup` still tries the
official login endpoint first, so it reverts to the documented path by itself
if upstream fixes the route.

### Reading the results

- A job whose run produced **no TAP output at all** is recorded two ways: the
  job node is `done` / `incomplete` with `data.error_type: Infrastructure`,
  while its suite child (e.g. `kselftest.riscv`) is `fail` — a suite that emits
  nothing is never reported as `pass`. When you group results, read the job's
  `error_type` first: `Infrastructure` means "no usable data", not "the kernel
  regressed".
- The `baseline` job boots **tuxrun's own rootfs**, not the artifact the job
  definition declares: the definition carries a cpio ramdisk, which the
  `qemu-riscv64` device cannot boot, and the worker says so in its log
  (`Warning: job definition carries a cpio ramdisk … using tuxrun's built-in
  disk`). Its `pass` therefore describes the boot path, not the declared
  artifact. The kselftest jobs do use the provisioned rootfs.
- Every run leaves a machine-readable record at
  `var/results/<build-id>/<test>.json` (verdict, exit code, detail, kernel
  revision, artifacts directory, log path, TAP counts, and which writer filed
  it), written for every outcome - including a run that stopped before tuxrun.
  Both writers share the layout: `python3 run_latest.py` (`source: fetch`, one
  production build re-run locally) and the worker taking dispatched jobs
  (`source: worker`). Read them with `python3 results.py` (add `--build <id>`,
  `--json` or `--list`); it needs no API, so it also answers "what did this
  machine run" with the stack stopped. `python3 prune.py` covers
  `var/downloads/`, not `var/results/`.
- Every node carries the kernel revision recorded by `python3 provision.py`
  (`var/state/served.json`); a deployment seeded without it says so loudly and
  labels its nodes with a placeholder revision instead.

### What `stack --seed` actually creates (and what it does not)

Seeding is a **shortcut around the build**, not a build. Three nodes appear, and
only the last row is produced by something that really ran:

| Node | Who creates it | Where its bytes come from | What it does NOT mean |
|---|---|---|---|
| `checkout` | `deploy/stack.sh --seed` POSTs it (`state=done`, `result=pass`) when the database has none | `data.kernel_revision` is taken from `var/state/served.json` (or the `SEED_*` variables) | no repository was cloned and no checkout ran - the `pass` says "the seed declared one", nothing more |
| `kbuild-gcc-14-riscv` | `deploy/stack.sh --seed` POSTs it as `state=available` | `artifacts.kernel` = `http://172.17.0.1:<KCI_SERVE_PORT>/Image`, i.e. the file this deployment serves from `var/serve/Image`; `modules`/`kselftest`/`_config` are the production build recorded in `var/state/served.json` | nothing was compiled. The node is a declaration carrying pre-existing artifacts, so the tree it claims (`SEED_TREE`, the served build's tree unless overridden) can disagree with the build the artifacts came from - `var/state/seed.env` records both |
| `baseline-riscv-pull-labs`, `kselftest-riscv-pull-labs`, `kselftest-kvm-pull-labs` | the **official scheduler**, from `kernelci-pipeline/config/jobs-pull-labs.yaml` | real job definitions, rendered per node | nothing: these are the real thing. The worker fetches each definition and runs tuxrun. `kselftest-kvm-pull-labs` is the **shared** kvm job: `kernelci-pipeline#1600` added it for sasha-lab, and this lab reuses it instead of carrying its own copy (the scheduler entry is what restricts it to `qemu-riscv64`) |

Two consequences worth knowing before reading a result:

- **The seeded kernel URL names the deployment that seeded it**
  (`http://172.17.0.1:<port>/Image`, the docker gateway address of that port).
  If that deployment is gone, the job cannot download its kernel and comes back
  `Incomplete` / `Infrastructure` for that reason alone - the node is not
  wrong, the server behind its URL is. Re-seed from the running deployment
  (`deploy/stack.sh --seed`) instead of running an old queue.
- **`python3 drift.py` needs two real kbuild `.config` files.** On a database
  that only ever saw one seed there is exactly one kbuild node, so drift has
  nothing to compare and says so. It compares whatever done/pass kbuild nodes
  the database holds, which on a long-lived deployment includes builds from
  earlier sessions.

### A second, isolated deployment on the same machine

The compose project decides which data volumes (and therefore which database)
a deployment owns, and the ports are all overridable:

```bash
export KCI_COMPOSE_PROJECT=kcirv-clean KCI_API_PORT=18001 KCI_STORAGE_PORT=18002 \
       KCI_CB_PORT=18003 KCI_SSH_PORT=18022 KCI_MONGO_PORT=18017 KCI_SERVE_PORT=18999 \
       KCI_API_URL=http://127.0.0.1:18001
# then run the same sequence as above
```

Every port in that list is probed **before** a service is started on it, and a
conflict is refused by name - the port, the holder and the `KCI_*_PORT` variable
that moves this deployment - instead of surfacing later as "artifact server
failed" or as a compose bind error blamed on the API. A port published by this
deployment's own compose project counts as ours, not as a conflict. No port is
reserved here: the defaults all bind on a machine where nothing else holds them,
including the artifact server's 8999.

Useful for testing a deployment the way a new user meets it — a fresh clone and
a genuinely empty database — without touching the first one's history. The two
cannot run *at the same time*: kernelci-api's compose file hardcodes
`container_name`, so stop the first stack before starting the second.

## Notes

- **Three worker modes = one file** (differences are parameters only):
  one-shot loop (`stack --seed` + `worker --once`), resident worker
  (accumulate history), remote official (`--api-url` + token).
- **KVM**: default = curated 8-test subset; the worker bakes modules.tar.xz
  into `/lib/modules` of the rootfs so kvm.ko loads at boot and `/dev/kvm`
  works. The seed kernel (`var/serve/Image`) must be the **same build** as
  `SEED_MODULES_URL`. A job definition naming its own test list (the
  `kvm_tests`/`kvm_full` parameters) runs more than the curated set - timeouts
  report incomplete, never fail.
- **fetch** defaults to gcc-14 builds; clang riscv has no kselftest
  (upstream gap).
