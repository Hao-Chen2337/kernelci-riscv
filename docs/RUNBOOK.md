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

## Fresh deployment (one command)

`./run.sh setup` runs `scripts/local-instance-init.sh` at the end, so a fresh
clone gets its runtime config generated automatically — no manual steps:

- `kernelci-api/.env` — generated from `kernelci-api/env.sample`
  (`SECRET_KEY`, `MONGO_SERVICE`, `PUBLIC_BASE_URL`, initial admin
  user/password/email). Re-running keeps an existing file; `--force`
  regenerates it (a new `SECRET_KEY` invalidates every JWT).
- SSH keypair — `kernelci-pipeline/data/ssh/id_rsa_tarball` (private, `0600`)
  and `kernelci-api/docker/ssh/user-data/authorized_keys` (public, `0644`);
  lets the scheduler upload jobdefs to storage via scp.
- `KCI_API_TOKEN` in `kernelci-pipeline/.env` — tries `POST /latest/user/login`
  first; in this kernelci-api revision that route is **not registered**
  (upstream versioned-app regression, returns 405), so the script falls back to
  minting the token with the API's own JWT strategy inside the `api` container.
  Either way it is verified against `/latest/whoami` before being written.

Both `.env` files and the keypair live in gitignored directories, so no secret
is ever committed. The old manual flow (hand-editing `.env`, generating keys by
hand, pasting a token) is no longer needed. To force-refresh the keys or the
`.env`:

```bash
bash scripts/local-instance-init.sh --force   # then restart the stack
```

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
