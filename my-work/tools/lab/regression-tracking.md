# Regression tracking & config-drift detection (riscv SOW)

Two self-contained tools (no `kernelci` library dependency; plain `requests`)
speak directly to the KernelCI HTTP API:

| Tool | Sub-command | API access | Works against |
|---|---|---|---|
| `config_drift.py` | drift (default action) | GET only | local API **and** production `https://api.kernelci.org` — **no token needed** |
| `regression_tracker.py` | `trend` | GET only | local API **and** production `https://api.kernelci.org` — **no token needed** |
| `regression_tracker.py` | `track` / `watch` | POST | **local API only** — needs `KCI_API_TOKEN` (admin JWT from `kernelci-pipeline/.env`) |
| `regression_tracker.py` | `track --dry-run` | GET only (scan) | local API or production; no POST happens |

Read-only vs write mode:

```sh
# Reads (drift, trend): works everywhere, token optional and normally unset.
export KCI_API_URL=http://127.0.0.1:8001        # local API
export KCI_API_URL=https://api.kernelci.org      # production API (public GET)

# Writes (track, watch): local API + local admin token only.
export KCI_API_URL=http://127.0.0.1:8001
export KCI_API_TOKEN=<admin JWT from kernelci-pipeline/.env>
```

The tools always target the canonical `/latest` API prefix (the local API
accepts both spellings; `api.kernelci.org` only serves the `/latest`
prefix). GET requests carry no token; `track`/`watch` refuse to run against
`https://api.kernelci.org` and print:

> production mode is read-only; writes only against the local API
> (KCI_API_URL=http://127.0.0.1:8001)

Without a token locally, `track`/`watch` exit with a clear
`KCI_API_TOKEN is not set` error before touching the API.

## `my-work/tools/lab/regression_tracker.py`

The pipeline records every test run as a node, so the pass/fail history (the
"trend") is inherently persistent. This tool layers on top of it:

```sh
# Render the result time-series for the tracked riscv test jobs (read-only).
python3 my-work/tools/lab/regression_tracker.py trend
# Same, but pick the jobs explicitly (works against production too):
KCI_API_URL=https://api.kernelci.org python3 my-work/tools/lab/regression_tracker.py trend --jobs kselftest-arm64-pull-labs

# Convert pass->fail transitions into persistent kind=regression nodes.
# Local API + token only:
python3 my-work/tools/lab/regression_tracker.py track            # create
python3 my-work/tools/lab/regression_tracker.py track --dry-run  # report only, no POST

# Loop `track` so regressions are recorded automatically (long-running,
# local API + token only):
python3 my-work/tools/lab/regression_tracker.py watch --interval 60
```

`track`/`watch` are idempotent: a failing run is never recorded twice. A
regression node links `data.fail_node` (first failure) to `data.pass_node`
(last pass) and carries `failed_kernel_revision`, so it stays queryable even
after the original test nodes age out. It supports cross-commit regressions
(the normal case).

The default job list (`--jobs` with no value) is the PR1 riscv pull-labs
set. Production currently has no `*-riscv-pull-labs` data, so against
`https://api.kernelci.org` pass an explicit job name that does exist, e.g.
`--jobs kselftest-arm64-pull-labs`.

## `my-work/tools/lab/config_drift.py`

Compares the effective kernel `.config` between two kbuild builds of the
same job (the kbuild job uploads `.config` as the `_config` artifact).
Read-only, so it runs against local **or** production without a token:

```sh
# last two passing builds of the default riscv job
python3 my-work/tools/lab/config_drift.py --job kbuild-gcc-14-riscv

# production API, no token:
KCI_API_URL=https://api.kernelci.org python3 my-work/tools/lab/config_drift.py --job kbuild-gcc-14-riscv

python3 my-work/tools/lab/config_drift.py --older <id> --newer <id>  # explicit pair
python3 my-work/tools/lab/config_drift.py --json                     # machine-readable
```

Exits 1 on drift, 0 on no drift, so it can gate CI/alerting. Option-level
diff is reported as added / removed / changed `CONFIG_*`.

Both tools page through `/nodes` until every matching node is fetched
instead of trusting a single page limit, so "newest two builds" and long
production trends are correct even when a job has thousands of runs.
`commit_of()` tolerates missing/`null` `data.kernel_revision`.

## Wiring for production monitoring

Run `watch` as a long-lived process next to the local pipeline services
(e.g. a systemd unit, or a compose service using the pipeline image with the
`my-work/tools/lab/` scripts mounted and `KCI_API_TOKEN` from
`kernelci-pipeline/.env`). `config_drift.py` is cheapest run on each new
kbuild `available` event, or on a cron. Do **not** point `track`/`watch`
at `https://api.kernelci.org`: writes are local-API only.
