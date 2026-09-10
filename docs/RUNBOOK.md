# Runbook

> All commands run from the repo root via `./run.sh`.

## Environment

- docker + `pip install tuxrun` (see `requirements.txt` for the Python packages
  the scripts themselves import; there is no virtualenv requirement, but the
  versions are what `requirements.txt` pins)
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
./run.sh setup          # upstream clones + patches + runtime config (see below)
./run.sh provision      # fetch + bake the artifacts a run needs
./run.sh stack --seed   # API/db/redis/storage/ssh + artifact server + callback + scheduler, then seed
./run.sh worker --once  # execute the queued jobs and report back
./run.sh report         # results
```

`setup` generates everything the runtime needs that must not live in git, so
nothing has to be filled in by hand:

- `kernelci-api/.env` — generated from `kernelci-api/env.sample`
  (`SECRET_KEY`, `MONGO_SERVICE`, `PUBLIC_BASE_URL`, initial admin
  user/password/email). Re-running keeps an existing file; `--force`
  regenerates it (a new `SECRET_KEY` invalidates every JWT).
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

Both `.env` files and the keypair live in gitignored directories, so no secret
is ever committed. To force-refresh the keys or the `.env`:

```bash
bash scripts/local-instance-init.sh --force   # then restart the stack
```

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
