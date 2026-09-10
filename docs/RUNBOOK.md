# Runbook

> All commands run from the repo root via `./run.sh`. Tool deep dives,
> evidence and drafts are internal (gitignored) — see
> `docs/INTERNAL-NOTES.md` locally.

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
| `./run.sh setup` | Clone core/api/pipeline + apply PR1/bullseye/nginx patches (skipped if already applied) + run validate_yaml |
| `./run.sh fetch [--job name] [--kvm] [--kvm-full]` | Tier A: re-run the newest production riscv build locally with tuxrun; artifacts in `work/downloads/` |
| `./run.sh stack [--seed]` | Tier B: start the local full stack (api/db/redis/storage/ssh + artifact server + real callback + official scheduler); `--seed` dispatches a kbuild node (overridable via `SEED_*` env vars) |
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
  into `/lib/modules` of the rootfs image so kvm.ko loads at boot and
  `/dev/kvm` exists. The seed kernel (`work/serve/Image`) must be the
  **same build** as `SEED_MODULES_URL`. `--kvm-full` runs everything —
  timeouts report incomplete, never fail.
- **fetch** defaults to gcc-14 builds; clang riscv has no kselftest
  (upstream gap).

## Known pitfalls

- `api.kernelci.org` is intermittently reachable (direct works; the local
  7890 proxy is dead — run.sh drops it by default).
- `storage.kernelci.org` sometimes streams the 144MB rootfs at KB/s;
  workaround: run the worker with
  `--rootfs http://127.0.0.1:8999/trixie-full.rootfs.tar.xz` (local mirror).
- Truncated downloads → Infrastructure reported honestly, re-run.
- The tuxlava patch must be re-applied after reinstalling tuxrun.
- The worker's default `--since` takes only today's new jobs — no history
  replay.
- Local `drift` needs ≥2 done/pass kbuild nodes in the local DB; compare
  offline files via `--older-config/--newer-config` instead.
