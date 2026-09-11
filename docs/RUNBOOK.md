# Runbook

> All commands run from the repo root via `./run.sh`.

## Environment

- docker + the host-side Python packages. `pip install tuxrun` alone is not
  enough - it only brings the fetch/worker dependencies (requests, PyYAML,
  jinja2) - so install this repository's list as well:

```bash
python3 -m pip install tuxrun -r requirements.txt
# requests + PyYAML (fetch/worker), uvicorn + fastapi + PyJWT + toml (the
# callback service `./run.sh stack` starts on the HOST), ruff (`verify`)
```

  There is no virtualenv requirement - the scripts run under the system
  `python3`. Once `setup` has cloned the upstreams, the callback also imports
  `kernelci-core` from that clone, so its requirements are needed as well:

```bash
python3 -m pip install -r kernelci-core/requirements.txt   # after ./run.sh setup
```
- Tier B (local full stack) additionally needs `KCI_API_TOKEN` (local API
  admin JWT, **never committed**) in `kernelci-pipeline/.env`; `./run.sh setup`
  generates it (see below)
- One-time patch for an already-installed tuxlava (riscv kselftest support).
  The directory is derived, not hardcoded - `python3.10` in the path only ever
  matched one machine's Python:

```bash
patch -p1 -d "$(python3 -c 'import site;print(site.getusersitepackages())')" \
  < config/tuxlava-kselftest-riscv.patch
```

## Commands

| Command | What it does |
|---|---|
| `./run.sh setup` | Clone core/api/pipeline + apply PR1/bullseye/nginx patches (skipped if already applied) + generate runtime config (`.env`, SSH keys, API token) + validate_yaml |
| `./run.sh fetch [--job name] [--kvm] [--kvm-full]` | Tier A: re-run the newest production riscv build locally with tuxrun; artifacts in `work/downloads/` |
| `./run.sh stack [--seed]` | Tier B: start the local full stack (api/db/redis/storage/ssh + artifact server + real callback + official scheduler); `--seed` dispatches (overridable via `SEED_*` env vars) |
| `./run.sh worker [--once]` | Take jobs, execute, report back; `--once` exits after the existing queue; unposted results persist and are re-posted (never re-run) on the next start |
| `./run.sh report` | Recent baseline/kselftest node states |
| `./run.sh verify` | Full gate: validate_yaml + verify-lava-body + verify-worker-guards + ruff |
| `./run.sh drift` / `./run.sh trend` | Config drift / regression pass-rates |
| `./run.sh stop` | Stop the whole local stack (incl. the docker compose API stack; data stays in volumes) |

## Fresh deployment (one go, no manual steps)

```bash
git clone https://github.com/Hao-Chen2337/kernelci-riscv.git && cd kernelci-riscv
python3 -m pip install tuxrun -r requirements.txt   # host deps (see Environment)
# step 0, once per machine: riscv kselftest support in the installed tuxlava
# (`setup` only WARNS when it is missing - the failure shows up much later)
patch -p1 -d "$(python3 -c 'import site;print(site.getusersitepackages())')" \
  < config/tuxlava-kselftest-riscv.patch
./run.sh setup          # upstream clones + patches + runtime config (see below)
python3 -m pip install -r kernelci-core/requirements.txt   # deps of the cloned callback
./run.sh provision      # fetch + bake the artifacts a run needs
./run.sh stack --seed   # API/db/redis/storage/ssh + artifact server + callback + scheduler, then seed
./run.sh worker --once  # execute the queued jobs and report back
./run.sh report         # results
```

Two things to know before the first run on a new machine:

- **A stale or dead proxy** makes the `git clone` above hang with no output
  before any script of ours is running: fix the proxy settings, or bypass them
  for that one command (`env -u http_proxy -u https_proxy -u HTTP_PROXY -u
  HTTPS_PROXY git clone ...`). The scripts themselves probe the network and
  print the exact settings that are broken; `KCI_BYPASS_PROXY=1 ./run.sh setup`
  (or `fetch`/`stack`/`provision`) makes their downloads and clones ignore the
  proxy for that run.
- **Several GB of images** are pulled on first use: the API/db/redis/nginx
  images (~4 GB) at `stack`, then the tuxrun runtime images on the first job
  (`tuxrun-dispatcher` + `qemu-riscv64` + `gcc-14`/`clang-21`
  `riscv64-kselftest` ≈ 12.3 GB measured here). Docker Hub and ghcr.io both have
  to be reachable.

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
recorded in `work/env/build.env`, which `stack --seed` then seeds from, so the
kernel served to the guest and the modules baked into the rootfs cannot drift
apart.

The worker also uses that ext4 image: it keeps the baked images it produces in
`work/env/baked/`, keyed by the rootfs and modules URLs it baked them from, so
the second kselftest job in a batch reuses the image instead of downloading
144MB and re-baking 4GB again (measured: 180.9s → 0.0s for the second job). The
directory is gitignored and holds up to three entries, each ~4GB (sparse on
disk); `KCI_BAKE_CACHE=0` disables the cache and `rm -rf work/env/baked` clears
it. A changed URL always bakes a new entry, and an interrupted bake is never
published.

Both `.env` files and the keypair live in gitignored directories, so no secret
is ever committed. To force-refresh the keys or the `.env`:

```bash
bash scripts/local-instance-init.sh --force   # then restart the stack
```

### Known limitations of the upstream image

`kernelci/staging-kernelci:api` ships three upstream kernelci-api defects
(unfixed upstream as of the revision this deployment uses): `POST
/latest/user/login` — and logout/forgot-password/reset-password — return
**405**, `/latest/docs` and `/latest/openapi.json` return **404**, and a fresh
database gets no initial admin. So `./run.sh setup` mints the admin and the API
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
- Every node carries the kernel revision recorded by `./run.sh provision`
  (`work/env/build.env`); a deployment seeded without it says so loudly and
  labels its nodes with a placeholder revision instead.

### A second, isolated deployment on the same machine

The compose project decides which data volumes (and therefore which database)
a deployment owns, and the ports are all overridable:

```bash
export KCI_COMPOSE_PROJECT=kcirv-clean KCI_API_PORT=18001 KCI_STORAGE_PORT=18002 \
       KCI_CB_PORT=18003 KCI_SSH_PORT=18022 KCI_MONGO_PORT=18017 KCI_SERVE_PORT=18999 \
       KCI_API_URL=http://127.0.0.1:18001
# then run the same sequence as above
```

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
  works. The seed kernel (`work/serve/Image`) must be the **same build** as
  `SEED_MODULES_URL`. `--kvm-full` runs everything — timeouts report
  incomplete, never fail.
- **fetch** defaults to gcc-14 builds; clang riscv has no kselftest
  (upstream gap).
