# Group W2d code notes: scripts/tools/*.py

Long-form rationale that used to live in the docstrings and comments of these
six files.  The code now carries short summaries plus a pointer here.

Files covered:

* scripts/tools/verify-worker-guards.py
* scripts/tools/config_drift.py
* scripts/tools/regression_tracker.py
* scripts/tools/callback-catcher.py
* scripts/tools/render-local-config.py
* scripts/tools/verify-lava-body.py

Line numbers quoted below are from the pre-compression files and are kept for
orientation only; they are deliberately NOT kept in the code.

## scripts/tools/verify-worker-guards.py

### What this suite is

Covers the review findings that are testable offline: ANSI stripping, TAP edge
cases, infra detection, log capping, test-type validation, and - since round 3 -
the state machine the worker runs on: the state file and the cursor it stores,
how a result is classified when the callback is missing, unreachable or
refusing, the resume/416 download path, the console-log archive and the timeout
clamp.  Those are the paths where a bug loses a result or wedges an artifact,
and none of them had a test before.

The behaviours are the worker's; the code implementing them now lives in
scripts/kcilib/ (the worker itself is only the flags, the config they map to and
the call into kcilib.run.poll.poll_loop).  Every check therefore drives the
module that OWNS the behaviour and patches THAT module's seam -
kcilib.run.poll.fetch_nodes/handle_event/retrieve_job_definition,
kcilib.run.jobrun.run_command/baked_rootfs_image/stamp,
kcilib.run.callback.requests, kcilib.run.artifacts.requests,
kcilib.run.poll.requests - instead of a re-export in the worker: a shim there
would only test the shim.  The state file is driven through
kcilib.core.state.StateFile directly, the same object the poll loop writes.

Since phase 4 the library takes two config objects instead of an argparse
namespace - kcilib.core.config.RunConfig for a run and
kcilib.core.config.PollConfig for the API side - so the fixtures
(_run_job_config, _poll_config) build those dataclasses directly, and
test_build_command_validation() also drives config.from_args() to check that the
command line really lands in them.

Round B's own abstractions get the same treatment:

* kcilib/api.py (the one API client every reader of the API now goes through) is
  driven with an injected session, so the /latest prefix, the
  {items,total,offset} paging walk, its two ways of stopping and its refusal to
  hand back something that is not JSON are all checked without a request leaving
  the machine.
* kcilib/source.py's TableSource (the index minus the ledger, and a skip that
  names the artifact it is missing) and NewestSource (the 3 -> 7 -> 30 -> 180
  day widening, and the reason it gives when it finds nothing) are driven
  offline by patching that module's own production-API seam.

Removed comment: kcilib sits next to this file; resolved through the file's own
directory, so the guards run from any CWD.

### check()

These checks used to be `assert` statements.  run.sh fails the `verify` gate on
a non-zero exit, but -O strips every assert, so a broken check printed
"ALL GUARD CHECKS PASSED" and exited 0: the gate reported success precisely when
it had verified nothing.

### stub_requests() and _RequestsStub

The module argument is the one whose code performs the request now -
kcilib.run.callback for the result POST, kcilib.run.artifacts for an artifact
transfer, kcilib.run.poll for the node-state GET - because that is the
module-level name the code actually resolves.  Stubbing the worker's would no
longer be seen by any of them, which is exactly why the worker keeps no
re-export for it.  _RequestsStub replaces a module's requests: get/post are
stubbed, the exception classes stay the real ones so the module's except clauses
still match.

### read_state() / write_state()

kcilib.core.state.StateFile owns the file (the worker's load_state()/save_state()
shims are gone); these are the guards' own view of the document it writes - the
same {timestamp, seen, pending} shape the worker has always persisted.  The
writer goes through StateFile, so the write is an atomic rename.

### test_missing_callback_keeps_result_pending

End-to-end form of #3: a job whose definition has no callback URL must not be
reported as posted and must not be marked seen - the result it just produced is
the only copy.

### test_state_flushed_before_a_crash

handle_event() is replaced by a stub that queues a report and then raises, which
is what a crash (or a SIGKILL) after a transient callback failure looks like
from poll_loop's side: the state file must already contain the report, so the
next start re-posts it instead of re-running tuxrun.

### test_port_probe

The port check the stack makes is kcilib.core.ports', not a second copy.
scripts/run-local-stack.sh carried its own bind test, holder lookup and refusal
text (~49 lines) next to the library's, and the two copies already disagreed
about the address to probe: the shell bound 0.0.0.0 because the stack binds
0.0.0.0, while kcilib.core.ports defaults to 127.0.0.1.  The shell now calls
`python3 -m kcilib.core.ports --host 0.0.0.0`, so what has to hold is the
contract that call depends on: a free port passes, a foreign listener raises
SystemExit(1) with the refusal naming the port, the holder and the KCI_*_PORT
variable, our own compose project is not a conflict, an EMPTY owner never counts
as ours, and the host really is forwarded instead of silently taking the
127.0.0.1 default.

Explicit ports are used, NOT port 0: asking the kernel for an ephemeral port
makes this test depend on the machine's ephemeral pool, and a box whose pool is
exhausted (4096 ports in range 56905-61000 here, and 4113 sockets open at the
time) fails bind(0) with EADDRINUSE - which reads as "the port probe is broken"
when nothing is wrong with it.  The stack's own ports are all 8001-8999,
comfortably outside the ephemeral range, so probing outside it is also the more
faithful test.

Other notes kept in the code as one-liners: our own compose project is not a
conflict; an empty owner is NOT ours (one deployment with no project name must
not wave a foreign listener through in silence); the host is forwarded, not
defaulted away (probing 127.0.0.1 for a service that binds 0.0.0.0 is the weaker
check the shell never made); PYTHONPATH is scripts/ where kcilib lives, not this
file's own directory, because this tool moved one level down into scripts/tools/.

SystemExit detail: the refusal is a message SystemExit, so python prints it to
stderr and exits 1 - which is the status the shell's own `exit 1` produced.
`refusal.code` is therefore the MESSAGE, not 1; the real exit status is checked
through the command line run-local-stack.sh calls.

### test_build_ref_and_jobspec

These are the functions 'build index / jobs / todo' stand on, and they are pure -
so they are testable without a network, an API or a run.  The two things worth
pinning down are the ones that bit us while designing: a node whose artifacts
name no build must fall back to the node id (never to something invented), and a
build that lacks a collection's tarball must SKIP that test loudly instead of
producing a job that dies 20 minutes in.

### test_worker_lock

Two workers on one state file would each see half the queue and fight over the
same workspaces and ports; the flock is what prevents that.

### test_seen_eviction

The oldest id is evicted, so the state file cannot grow without limit.

### _FakeSession

kcilib/api.py opens its own session in __init__ and resolves self.session at call
time (kcilib/api.py:85), so replacing that one attribute is the seam: no request
leaves the machine, and the kwargs the client passes - allow_redirects above all,
which is what makes the redirect refusal reachable at all - stay observable.

### test_api_latest_prefix

The /latest prefix is the thing the five hand-written clients this module
replaced disagreed about, so both accepted forms must address the SAME
endpoint - not merely both "work".

### test_api_all_nodes_pages

A missing page used to look exactly like "no such build", so the loop is worth a
test rather than a comment.  The two ways it must end: the total is reached, or
a page comes back short when there is no total.  The stale-total case (10**6
with 250 nodes) is the third: an empty page is the only thing that can stop it,
and a walk that never ends must fail here rather than hang the suite.

### test_api_non_json_is_api_error

A proxy in front of the API answers an HTML page; response.json() raises
ValueError, which used to escape the client and kill callers that only catch API
errors.  The stub raises the exception a real requests response raises
(requests.exceptions.JSONDecodeError on 2.27+, plain json.JSONDecodeError
before), not a bare ValueError, so _json()'s except clause is exercised for the
type it really sees - both are ValueError, which is what _json() catches, so
neither can escape as a bare ValueError.

NB: raise_for_status() runs first, so the not-JSON path is a 2xx whose body is
HTML (a captive proxy, an SSO page); a 502 never gets that far.

Also asserted here: get() is the raw read and hands back whatever parsed; the
typed readers are the ones that owe the caller a shape, and they are the ones
that must refuse a page that is not an object - instead of handing a list to code
about to index it as a page.  A 5xx stays requests' own HTTPError (callers catch
RequestException) and must never be turned into an empty page.

### test_api_refuses_redirect

The definition URL is handed out by the scheduler, so a redirect means something
in between is answering.  A 3xx that carries a perfectly good JSON body is the
case a "does the body parse?" check would wave through: the refusal has to come
first, and it can only come at all because allow_redirects=False reaches the
session.  The response is bound as a lambda default so it does not close over the
loop variable (ruff B023: every call would then see the last redirect built).
The same flag is asserted on the successful path, so an endpoint that STARTS
redirecting is never silently followed.

### test_api_retries_a_dropped_connection

The local API closes idle keep-alive connections, so one dropped connection used
to lose a page; retrying a 5xx instead would turn a refusal into a slow refusal.
A retry that succeeds returns the page - that is what the sleep between the
attempts is for.

### ledger_at() / no_api_calls() / stub_newest_api()

ledger_at uses the same seam as test_missing_callback_keeps_result_pending, for
the same reason: a guard must not write into the repository's work/results/.

no_api_calls: kcilib/source.py:8 documents the table source as local-only (index
minus ledger), so a request on this path means the "offline" source grew a
network dependency without anyone saying so.

stub_newest_api patches NewestSource.build()'s two globals,
builds_from_production_api and _days_ago, ON kcilib.source (kcilib/source.py:83-84),
because that is what the code actually reads.  It also makes the window the
source asked for observable instead of something to infer from the clock.
*builds* is called with the attempt number and returns the refs that attempt
found; *windows* and *queries* collect what was asked for.

### test_table_source_subtracts_the_ledger

Two separate decisions are pinned down: a (build, test) the ledger already holds
a record for is not offered again (otherwise every run re-runs the whole table),
and a test the build cannot support is skipped WITH the artifact it is missing -
never silently dropped.  The build pairing also shows that the ledger now holds a
record for boot, which must be subtracted; with both recorded the list is empty
while the skip is still reported, because "0 to do" and "2 tests were skipped"
are different answers.  A narrowed test list still reports the skip it asked
about.

### test_newest_source_widens_the_window

The production API pages old-first and a quiet tree can be days behind, so a hit
on the first window must stop the walk, a hit on a later one must still be used,
and the query that is finally asked has to be the one the caller described.  A
custom first window leads the widening, and the walk still ends at the last one
when nothing is found.

### test_newest_source_reports_no_build

"0 to do" is the answer an operator cannot act on; the source has to say which
job it looked for and how far back it looked - and it must have looked all the
way back before it says so.

### test_get_source_unknown_name

The events source is the trap this guards: ./run.sh worker is the way to it, and
a user who typed --source events must be told that instead of getting a KeyError
traceback.  The base class refuses to be a source: a subclass that forgets jobs()
must fail loudly rather than answer "nothing to do".

### test_no_repo_root_is_counted_with_dirname

Three tools moved into scripts/tools/ and kept a counted root, each of them
silently one level too deep: render-local-config.py rendered @KCI_ROOT@ as
.../scripts, so the stack's settings named
scripts/kernelci-pipeline/data/ssh/id_rsa_tarball and EVERY job node came back
submit_error; callback-catcher.py defaulted its log to scripts/work/logs/;
verify-lava-body.py pre-empted the same trap.  All of them still "worked" one
directory up, which is why nothing failed loudly - so the rule is checked here
instead: a module-level ROOT-ish name may not be built from os.path.dirname().

### test_shell_scripts_reference_live_modules

scripts/run-local-stack.sh kept calling `python3 -m kcilib.ports` after ports.py
had moved into kcilib/core/, so `./run.sh stack` died at its first port check
with "No module named kcilib.ports" - and no gate noticed, because nothing here
read the shell entry points.  The same class of mistake had already bitten once
when the six offline tools moved into scripts/tools/.  Two kinds of reference are
therefore checked: every `python3 -m kcilib.<x>` must import, and every flat
`scripts/<name>.py` must exist.  Both patterns must match something, or this
guard would pass by finding nothing at all the day the call sites are rewritten.

### Small comments that stayed one-liners in the code

* CRLF + ANSI + timestamp prefixes (ANSI-stripping fixture).
* "not ok" must not be double-counted as ok (the old bug).
* started but never finished -> fail.
* all-skip: still has results (visible skips), suite passes.
* malformed/glued/uppercase failures must still be detected (round 2: these used
  to be false greens).
* garbage: no TAP -> fail, never pass.
* a test whose NAME mentions JobError must not be misclassified.
* authoritative: LAVA self-reported Infrastructure on the job case.
* rc 0 without any boot case -> incomplete, not a fake pass.
* The defaults are the CLI's own: one home (kcilib.core.config), two readers.
* (a) full-size .part + matching sidecar: publish, no HTTP request.
* (b) a 416 whose Content-Range total equals the offset: the server itself
  confirms the partial file was the whole artifact.
* (c) a 416 that does not match: the partial is dropped and the transfer
  restarts from zero instead of wedging the artifact.
* a sidecar for another URL must never be used to publish.
* a workspace without a console archives nothing and does not fail.
* an id that tries to escape the log directory is neutralised.
* pruning keeps only the newest entries.
* a file the worker did not write is never pruned.
* This file lives in scripts/tools/, so the repository root is two up.
* The file must stay open for the flock to be held (SIM115 is deliberate,
  exactly as in poll_loop).
* An absolute URL is used as given: a job definition URL is external and must
  never be re-based under /latest.
* kernel + kselftest tarball, no modules: kselftest-kvm cannot run.
* The real widening clock, before it is patched: an ISO8601 second stamp that
  really is N days back (the module builds it with time.gmtime).
* (d) an empty first page: one request, no nodes, no spin.
* The ledger root is redirected for the duration: this test drives a REAL
  run_node(), so without it the record the worker now files would land in the
  repository's work/results/ and `./run.sh verify` would dirty the tree it is
  verifying.  The redirection is the seam; the assertions read the same root back
  through kcilib.core.ledger.
* run_node() resolves baked_rootfs_image and stamp as kcilib.run.jobrun module
  globals, so that is where the seam is: a boot job must never bake, and the
  progress lines must still be emitted.
* The same run must also be in the ledger: the worker used to file nothing, so
  work/results/ held only the one-shot runner's rows and a resident lab had no
  history of its own.  The build id falls back to the job node id here because
  the only artifact URL of this job names no build.

## scripts/tools/config_drift.py

### What the module header said

Config-drift detector for the KernelCI riscv pipeline.  It compares the
effective kernel .config of two kbuild nodes of the same job and reports
option-level drift: CONFIG_* options that were added, removed, or had their
value changed between the two builds.  A kconfig change (upstream default
change, fragment change, defconfig change) can silently alter which selftests
are built and run, so drift is reported next to the test results.

Where the .config comes from, in order of preference:

1. node artifact `_config` / `.config` (a URL in the node's artifacts)
2. the local storage convention used by the docker-compose deployment:
   {storage_base}/{job}-{node_id}/.config
3. --older-config / --newer-config: explicit URLs or local file paths

Read-only command: it talks to the API with GET requests only, so it works
against the public production API (https://api.kernelci.org) without a token, as
well as against the local API.  No KCI_API_TOKEN is required.

Examples that used to sit in the header (all still valid):

    # newest two passing builds of the default job, drift summary only
    python3 scripts/tools/config_drift.py

    # two specific builds, full listing capped at 20 lines per category
    python3 scripts/tools/config_drift.py --older 6a96... --newer 6a9d... --max-lines 20

    # machine-readable report (and CI gate: exit 1 when drift > 0)
    python3 scripts/tools/config_drift.py --json

Exit code: 0 = no drift, 1 = drift found (usable as a CI gate).  The argparse
epilog carries the short form of these examples.

### Imports and paths

requests is imported for its exception types: kcilib.api re-raises
requests.exceptions.RequestException, and this tool's error handling catches
exactly that.  The HTTP itself goes through the shared client now.
scripts/kcilib/ is resolved through this file's own directory (the tool runs from
any CWD), and the API client lives in exactly one place.

### API_LATEST

KernelCI exposes its API under the /latest prefix on api.kernelci.org; the local
API accepts both, so always target the canonical /latest base.

### STORAGE_BASE

Storage convention of the docker-compose deployment:
{STORAGE_BASE}/{job}-{node_id}/.config

KCI_STORAGE_URL wins; otherwise the port comes from the deployment, which moves
the stack off the defaults with KCI_STORAGE_PORT (run-local-stack.sh exports it
for the compose file, and ./run.sh drift forwards it).  Hardcoding 8002 here
meant a deployment on e.g. 18002 fetched from the wrong host - and only in the
one case this fallback exists for, a node without a _config artifact in its own
artifacts.

### api_headers() / _client() / fetch_all_nodes()

api_headers: every request this tool makes is a GET, and the KernelCI API serves
those publicly, so a token is only attached when one is configured.

_client: this module used to carry its own api_get/fetch_all_nodes - near enough
byte-for-byte what regression_tracker.py had, plus a third variant in
fetch-and-run-latest.py.  There is one client now (kcilib/api.py), so an API
change is made once instead of five times.

fetch_all_nodes: /nodes returns its results in creation order and truncates each
response to the page limit, so a single request would silently miss the newest
nodes of a large job.  The response carries {items,total,offset}, which lets us
walk every page before sorting client-side.

### parse_config() / config_url_of() / pick_nodes()

parse_config: `CONFIG_X=y` / `CONFIG_X=123` / `CONFIG_X="str"` map to the value
after '='; `# CONFIG_X is not set` maps to 'n'.  Comments and blanks are ignored;
inline comments after a value are stripped.

config_url_of: prefers the node's own artifacts; falls back to the storage layout
the docker-compose deployment uses ({STORAGE_BASE}/{job}-{node_id}/.config).

pick_nodes: explicit ids take precedence; otherwise the newest two done/pass
nodes of the job are used, in chronological order: (older, newer).  The API
filters (state=done, result=pass) are pushed down so pagination stays cheap even
on the busy production job.

### Empty-config guard

A 200 response that is not a .config (HTML index/auth page, truncated download)
parses to {}: reporting drift on that would be nonsense.

## scripts/tools/regression_tracker.py

### What the module header said

Regression trend recorder for the KernelCI riscv pipeline.  The pipeline already
records every test run as a node in the API, so the result history (the "trend")
is inherently persisted.  This tool layers three things on top of that history:

* trend - render the pass/fail history of the tracked test jobs as a time series
  (commit -> result), so drift over builds is visible at a glance.
* track - scan that history for pass -> fail transitions and create
  kind=regression nodes in the API, turning a one-off failure into a persistent,
  queryable regression record (with the first-failing and last-passing nodes
  linked).
* watch - loop track so regressions are recorded automatically.

Read/write split:

* trend is read-only: GET requests only, no KCI_API_TOKEN required, and it works
  against both the local API and the public production API
  (https://api.kernelci.org).
* track / watch create nodes (POST).  They require KCI_API_TOKEN and must run
  against the local API: the production API is read-only from this tooling's
  point of view, and local JWTs are not accepted there.

Idempotent: re-running track never creates a duplicate regression node for the
same failing run.

Examples that used to sit in the header (all still valid, and in the argparse
epilog):

    python3 scripts/tools/regression_tracker.py trend --jobs kselftest-riscv-pull-labs
    python3 scripts/tools/regression_tracker.py track --dry-run
    python3 scripts/tools/regression_tracker.py watch --interval 60

### Imports, API_LATEST, DEFAULT_JOBS

scripts/kcilib/ is resolved through this file's own directory, so the tool runs
from any CWD and the API client lives in exactly one place.

KernelCI exposes its API under the /latest prefix on api.kernelci.org; the local
API accepts both, so always target the canonical /latest base.

DEFAULT_JOBS are the test nodes whose pass/fail transitions are tracked.  These
names must match the node `name` field in the API exactly; run `trend` with an
empty --jobs list to see what names exist (it will show "(no runs)" per job).
These are the PR1 pull-labs job names; the locally created demo nodes use a
numeric suffix (-2/-3/...) and can be tracked via --jobs.

### api_headers() / _client() / fetch_all_nodes() / require_write_access()

api_headers: GET endpoints of the KernelCI API are public.  A local admin JWT is
only meaningful against the local API, so it is never attached when KCI_API_URL
points at the production API.

_client: this module had its own api_get/fetch_all_nodes - the same code as
config_drift.py and a third variant in fetch-and-run-latest.py.  Reads go through
the one client now; writes below still use requests directly, because creating
nodes is this tool's own decision.

fetch_all_nodes: /nodes returns its results in creation order and truncates each
response to the page limit, so a single request would silently miss the newest
runs of a busy production job.  The response carries {items,total,offset}, which
lets us walk every page before sorting client-side.

require_write_access: POSTing is only supported against the local API; production
(https://api.kernelci.org) is read-only from this tooling, and without
KCI_API_TOKEN there is no identity to create nodes with at all.

### done_runs()

kind="job" is not decoration: `track` creates kind=regression nodes that copy the
job's own name/group/path (build_regression below), so without the filter this
function also returned the regression records describing those very runs.
`trend` then printed one extra row per regression - with commit "?" (a
regression node carries failed_kernel_revision, not kernel_revision) - counted it
in the "N pass / M fail" line, and `track` rescanned its own output as if it
were history.

### transitions_in() / build_regression()

Consecutive failures belong to the same regression: only the first failing run
after a pass starts a new transition, and the counter only re-arms after a fresh
pass (hence the @# re-arm only after the next pass@ comment on the assignment).

build_regression supports cross-commit regressions (the normal case), so unlike
Regression.create_regression it does not require identical revisions.

## scripts/tools/callback-catcher.py

### What the module docstring said

This is a DEBUG TOOL, not the stack's callback.  A running local stack delivers
its job results to the real lava_callback service on KCI_CB_PORT (8003 by
default, see ./run.sh stack), and nothing wires callbacks to this script - so
someone who starts it expecting the stack's results to appear sees nothing.
Point a job definition's callback URL (or a plain curl) here when you want to see
the exact body and headers a callback carries.  The startup banner prints the
same warning.

Each request is appended as ONE JSON object per line (JSON Lines), so the file
can be read directly with jq / `tail -f ... | jq .`; it used to be named
callback-received.json while its content was JSON Lines.

Both invocation examples:

    python3 scripts/tools/callback-catcher.py                     # 127.0.0.1:9999
    python3 scripts/tools/callback-catcher.py --port 9998 --log /tmp/cb.jsonl

The port is a flag (and KCI_CB_CATCH_PORT) instead of a hardcoded 9999: 9999 was
not overridable, and a port that is somebody else's on this machine failed with
a bare traceback.  The log is capped - once it exceeds --max-bytes it is rotated
to <log>.1 (one generation kept) instead of growing without bound.

### ROOT / DEFAULT_LOG

Derived from this file's location: a hardcoded absolute path pointed every clone
at one machine's checkout.  WALKED UP to run.sh (kcilib.repo_root), not counted:
this file moved into scripts/tools/, and the old two-dirname version quietly
defaulted the log to scripts/work/logs/ instead of work/logs/.

### Globals LOG / MAX_BYTES

Set from the command line in main(); the handler reads them as globals so a
single HTTP server instance can serve every request with them.

### record() and the handler

The write error is never swallowed: a catcher that drops requests silently is
worse than not starting it at all.

do_GET answers a cheap liveness/identity response, so a port check can tell this
catcher apart from whatever else may hold the port.

A body that is not JSON is kept as text (decoded with "replace"), because the
request must not be rejected just for that.

The bind failure names the port and the way out instead of a bare traceback: the
default 9999 is somebody else's port on many machines.

## scripts/tools/render-local-config.py

### What the module docstring said

Why the script exists: kernelci loads its settings with a plain toml.load() that
does not expand environment variables, so a tracked file cannot say "the config
next to me" or "whatever API port this deployment picked" - it has to carry
absolute values.  Carrying them meant every clone silently read another
deployment's paths, and a second isolated stack could not even be told apart from
the first.

Placeholders are written @NAME@ and are replaced from --var NAME=VALUE plus
KCI_ROOT (this checkout).  Values are NOT taken from the ambient environment on
purpose: an inherited variable of the same name would silently satisfy a
placeholder, and a template comment mentioning @SOMETHING@ got substituted from
the environment during testing - which is exactly the kind of invisible wrong
value this script exists to prevent.  A name with no value is an error, never
something left in place.

Full usage form:

    python3 scripts/tools/render-local-config.py \
        --template config/local-callback.toml \
        --output work/local-callback.toml \
        --var KCI_ROOT=/srv/kernelci-riscv

(The rendered output is the file a deployment actually reads; the tracked
template stays placeholder-only.)

### ROOT

Walked up to run.sh, never counted: this file moved into scripts/tools/, and
`ROOT = os.path.dirname(HERE)` then rendered every @KCI_ROOT@ as .../scripts - so
the stack's settings pointed at scripts/kernelci-pipeline/data/ssh/... and every
job node came back submit_error.  See kcilib.repo_root().

## scripts/tools/verify-lava-body.py

### The root and the imports

This tool lives in scripts/tools/, so the repository root is WALKED UP to
(kcilib.repo_root finds run.sh) instead of counted: three tools kept a counted
root when they moved here and silently pointed one level too deep.

kernelci-core is imported from THIS checkout, never from some other deployment
that happened to be hardcoded here: a hardcoded path made a fresh clone's verify
results silently depend on the machine it was run from.

The body under test is kcilib.run.callback.lava_body and the verdicts it is fed
are kcilib.run.judge's: the worker imports them from the library instead of
defining them (they used to live in riscv_pull_worker.py, which this script
loaded by path).  Same body, same parser, same expectations - and scripts/ is on
the path here, so kcilib resolves from any CWD.

The recorded consoles stay in scripts/fixtures/, next to kcilib.

### check()

These checks used to be `assert` statements.  run.sh fails the `verify` gate on a
non-zero exit, but -O strips every assert, so a broken check printed
"ALL PARSER CHECKS PASSED" and exited 0: the gate reported success precisely when
it had verified nothing.

### fake_config()

lava_body() takes a kcilib.core.config.RunConfig since phase 4 instead of an
argparse namespace; the values - and therefore every body checked here - are
exactly the ones the namespace carried.

### run_kselftest_tap_cases()

The bug this guards: tuxrun exits 0 even when selftests fail, so a LAVA body
built from the exit code alone would report a PASS node and drop every per-test
result.  With the TAP wired in, the same run must produce per-test child results
and a job-level 'fail'; the all-pass TAP variant must keep the job node pass.

### run_no_tap_case()

A kselftest job whose tuxrun run failed before any test ran (no TAP lines, e.g.
artifacts the dispatcher cannot reach) must NOT become a pass node: no TAP ->
suite fail, JobError -> infrastructure.

### run_infra_case()

An infrastructure failure (tuxrun exit 2, e.g. unknown test class) must surface
as error_type=Infrastructure on the job node.
