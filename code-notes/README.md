# Code notes: the rationale that left the code

These files hold the long-form "why" that used to live as essays in the comments
and docstrings of `scripts/`. On 2026-09-17 the code side was cut back to short
English one-liners (a comment block is 1 line whenever possible, 3 at most), and
every explanation worth keeping moved here.

**Rule for future edits**: the code says *what* in one line and, when it matters,
points here ("Rationale: code-notes/<file>.md"). The *why*, the history, the
measurements and the traps live in these notes. Do not grow the comments back -
grow the notes instead.

**What these are**: per-file engineering notes for `scripts/`. They are committed
with the repository (unlike `docs/`, which is internal and gitignored except
`RUNBOOK.md`), so a fresh clone keeps the reasoning that no longer fits in the code.
They are the counterpart of the internal `docs/ARCHITECTURE.md` (structure,
invariants, data flow) and `docs/DATA-MODEL-AND-FLOW.md` (data structures): those two
describe the system, these hold the per-file detail - and some notes cite them by
name, so a citation to `docs/...` may point at a document that is not shipped here.

| File | Covers |
|---|---|
| `A-sink-source-dashboard.md` | `kcilib/sink.py`, `kcilib/source.py`, `dashboard.py` - why "where results go" is one place, the events worker is not a source, and why the dashboard is not kernelci-frontend |
| `B-delivery-buildref.md` | `kcilib/run/delivery.py`, `kcilib/table/buildref.py` - the two delivery modes and their trade-offs, `kernel_url()`'s contract, provenance rules, node-id instability |
| `C-table-localjobs.md` | `kcilib/table/{localrun,jobspec,buildindex}.py`, `local-jobs.py` - the local job table: JobSpec vs JobDefinition, the ledger-vs-API split, index vs database |
| `W2a-shell.md` | `run-local-stack.sh`, `net-preflight.sh`, `local-instance-init.sh` - the uid-1000 upload trap, port probing, seed rules, `KCI_SETTINGS` import-time trap |
| `W2b-entrypoints.md` | `run.sh`, `fetch-and-run-latest.py` - command surface, the one-shot path, proxy handling, artifact delivery history |
| `W2c-kcilib.md` | `kcilib/api.py`, `kcilib/core/*`, `kcilib/run/*` - API client history, path derivation, bake cache and 416, verdict windows, timeout clamps |
| `W2d-tools.md` | `scripts/tools/*` - guard-by-guard rationale, port-probe contract, /latest paging, drift sources, the lava_body TAP/infra cases |

Line numbers cited inside these notes refer to the tree at the time of writing and
were already shifted by the trim itself: use the symbol names.
