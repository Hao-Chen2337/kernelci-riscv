# Runbook

RISC-V KernelCI automation for [riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49):
continuous regression testing of the Linux riscv Vector/Hypervisor extensions under QEMU.

**One run is four things: pick a build, pull it local, run one test on it, get one verdict.**
Every command below is one of those four, or the deployment that makes them possible.

Run everything from the repository root. Every command is an entry point there, run as
`python3 <entry>.py`; the deployment half lives in `deploy/*.sh`. `python3 verify.py` is the gate.

---

## 1. Install

```bash
python3 -m pip install tuxrun -r requirements.txt

sudo apt-get install -y docker.io docker-compose-v2 docker-buildx git curl patch \
                        openssh-client e2fsprogs nodejs python3 python3-pip

sudo usermod -aG docker "$USER"    # then log out and back in, or `newgrp docker`
```

On Ubuntu 24.04 (python3.12) pip refuses that first line — PEP 668. Add
`--break-system-packages` there. 22.04 ships pip 22.0.2, which does not know the flag, so it is
not a portable line.

No virtualenv: the entries run under the `python3` on `PATH`.

**One directory rule.** `kernelci-api/docker/storage/data` and
`kernelci-api/docker/ssh/user-data` must be writable by **uid 1000**, or the scheduler's upload
fails silently. `stack.sh` checks this and prints the `chown`.

---

## 2. First-time setup

```bash
deploy/setup.sh                        # clone upstreams, apply patches, render config; idempotent
bash deploy/instance-init.sh           # .env, SSH keys, API token
python3 -m pip install -r kernelci-core/requirements.txt
```

`instance-init.sh` writes three things that must not live in git: `kernelci-api/.env`, the SSH
key pair, and `KCI_API_TOKEN` in `kernelci-pipeline/.env`.

---

## 3. Start the stack

```bash
python3 provision.py                   # pin the newest passing production build -> var/serve/Image
deploy/stack.sh --seed                 # API + artifact server + callback + scheduler, then seed one build
```

`deploy/stack.sh` with no flags starts the services only; `--worker` seeds and runs the pull
worker in the foreground.

Allow several GB on first use: ~4 GB at `stack`, then ~12.3 GB of tuxrun runtime images on the
first job.

---

## 4. Check the tree

```bash
python3 verify.py                # everything; exit 3 when any check failed
python3 verify.py --quick        # leaves out the slow page renders
python3 verify.py --base URL     # also sweep a running page over HTTP
```

Most checks' scripts are in `tools/gate/`, published with the tree; the exceptions are `ruff` (an
external tool), `i18n` (`python3 -m lib.i18n`), and `pipeline yaml` (upstream's
`kernelci-pipeline/tests/validate_yaml.py`). `verify.py` runs every
check and reports all of them — read its own last line for the count.

---

## 5. Run tests

```bash
python3 verify.py --quick                        # is this tree healthy?
python3 table.py index --api-url https://api.kernelci.org --tree mainline --days 3
python3 table.py summary                         # what is on disk, and what ran
python3 table.py todo --build <id>               # what has no record yet, and why
python3 table.py pull --build <id>               # fetch that build's artifacts
python3 table.py run --build <id> --test boot    # run it - the exit status IS the verdict
python3 results.py                               # read the ledger back
python3 drift.py --older <id> --newer <id> --api-url https://api.kernelci.org
python3 trend.py --api-url https://api.kernelci.org
python3 gui.py                                   # the same thing as a page: http://127.0.0.1:8079
```

The three tests are `boot`, `kselftest-riscv`, and `kselftest-kvm`; a run with no `--test` covers
all three, in that order.

Unattended, without a person watching:

```bash
python3 run_latest.py         # the newest production build, fetched and run once
python3 runday.py             # a rotation: a day's builds, skipping what the ledger has
python3 pull_worker.py        # the resident worker: poll the events API, claim, run, report back
python3 report.py             # the newest nodes of each pull-lab job name
python3 prune.py --dry-run    # retention for var/downloads/
```

---

## 6. Stop

```bash
deploy/stop.sh
```

Compose data stays in the volumes, so a later `stack.sh` resumes from the same database.

---

## Exit codes

| verdict | exit | meaning |
|---|---|---|
| `pass` | **0** | the thing happened (test passed, no drift, all green) |
| `fail` | **1** | the test ran and **failed**; for `drift.py`, the two configs differ |
| — | **2** | argparse refused the command line (a bad flag) |
| `incomplete` | **3** | **infrastructure**: an artifact never arrived, the API is unreachable, a gate check failed |

`table.py run`'s exit status *is* the verdict of the test, and "the artifact was never
downloaded" is not a test result — so it is 3, never 1.

---

## Where things land

`var/`, and only `var/`. `lib/layout.py` owns every path in it.

| path | what it holds |
|---|---|
| `var/downloads/<build_id>/` | pulled artifacts (`Image`, `modules.tar.xz`, `kselftest.tar.xz`, `provenance.json`) |
| `var/results/<build_id>/<test>.json` | **the ledger** — what ran, never pruned, the only record |
| `var/baked/<key>.ext4` | 4 GB guest images baked from the rootfs |
| `var/configs/` | archived `.config`, for drift comparison |
| `var/cache/` | raw fetched bytes reused across bakes (the rootfs tarball, and `.part` resumes) |
| `var/serve/Image` | the kernel this deployment serves out |
| `var/state/` | `builds.json`, `served.json`, `worker-state.json`, `seed.env` |
| `var/runs/<run-id>/` | one activity's log and `run.json` |
| `var/workspaces/<name>/` | one task's scratch |
| `var/logs/` | archived serial output and action logs |

Everything above can be regenerated except `var/results/` — that one is the record.

Three environment variables move things: `KCI_WORK_DIR` (the whole workspace), `KCI_RESULTS_DIR`
(the ledger directory alone — for tests, or a second deployment), and `KCI_WORKER_STATE` (the
worker's cursor file).

---

## Ports

Every port is overridable, and the stack probes each one before starting a service on it — with
one exception: `gui.py --port` is overridable but nothing checks it, so a busy 8079 fails at bind.

| service | variable | default |
|---|---|---|
| API | `KCI_API_PORT` | 8001 |
| storage | `KCI_STORAGE_PORT` | 8002 |
| callback | `KCI_CB_PORT` | 8003 |
| ssh | `KCI_SSH_PORT` | 8022 |
| mongo | `KCI_MONGO_PORT` | 8017 |
| artifact server | `KCI_SERVE_PORT` | 8999 |
| console | `gui.py --port` | 8079 |

A second deployment sets `KCI_COMPOSE_PROJECT` and the `KCI_*_PORT` variables **plus**
`KCI_RESULTS_DIR`, then runs the same order as above.
