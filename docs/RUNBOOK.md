# Runbook

> All commands run from the repo root via `./run.sh`.

## Environment

- docker + `pip install tuxrun`
- Tier B (local full stack) additionally needs `KCI_API_TOKEN` (local API
  admin JWT, **never committed**) in `kernelci-pipeline/.env`
- One-time patch for an already-installed tuxlava (riscv kselftest support):

```bash
cd ~/.local/lib/python3.10/site-packages && patch -p1 < /home/hao/kernelci-riscv/config/tuxlava-kselftest-riscv.patch
```

## Commands

| Command | What it does |
|---|---|
| `./run.sh setup` | Clone core/api/pipeline + apply PR1/bullseye/nginx patches (skipped if already applied) + validate_yaml |
| `./run.sh fetch [--job name] [--kvm] [--kvm-full]` | Tier A: re-run the newest production riscv build locally with tuxrun; artifacts in `work/downloads/` |
| `./run.sh stack [--seed]` | Tier B: start the local full stack (api/db/redis/storage/ssh + artifact server + real callback + official scheduler); `--seed` dispatches (overridable via `SEED_*` env vars) |
| `./run.sh worker [--once]` | Take jobs, execute, report back; `--once` exits after the existing queue; unposted results persist and are re-posted (never re-run) on the next start |
| `./run.sh report` | Recent baseline/kselftest node states |
| `./run.sh verify` | Full gate: validate_yaml + verify-lava-body + verify-worker-guards + ruff |
| `./run.sh drift` / `./run.sh trend` | Config drift / regression pass-rates |
| `./run.sh stop` | Stop the whole local stack (incl. the docker compose API stack; data stays in volumes) |

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
