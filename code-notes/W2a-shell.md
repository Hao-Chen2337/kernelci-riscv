# Code notes: shell entry points (group W2a)

Long-form explanation that was cut out of the comments of the three shell files
below. The code now carries only the short version; this file keeps the
reasoning, the history behind each gotcha, and the contracts that used to be
spelled out inline.

Scope of the pass: **comment text only**. No code line, no string literal, no
whitespace and no ordering was touched; `echo "# ..."` lines that end up inside
generated files (`work/env/seed.env`, `work/env/images.env`) are output and were
left alone, as were the `# shellcheck` directives.

## scripts/run-local-stack.sh

### Header and usage

The old header spelled out all three modes; the code keeps one line:

* no argument - start the services only, then print the status and the next step;
* `--seed` - start the services and POST a kbuild seed node, which is what makes
  the scheduler dispatch;
* `--worker` - services + seed + the worker in the foreground.

### Deployment identity (`PROJECT`, the ports)

Everything that identifies one deployment is overridable: the compose project
(which fixes the data volumes) and the host ports. The full example that used to
sit in the comment:

    KCI_COMPOSE_PROJECT=kcirv-clean KCI_API_PORT=18001 KCI_CB_PORT=18003 \
    KCI_SERVE_PORT=18999 KCI_STORAGE_PORT=18002 KCI_SSH_PORT=18022 ./run.sh stack

Two deployments can therefore be exercised on the same machine, each against its
own empty database instead of the accumulated one. They cannot run
*simultaneously*: kernelci-api's compose file hardcodes `container_name`
(`kernelci-api`, `kernelci-api-db`, ...), so the first stack has to be stopped.
It is the volume - and therefore the database - that decides whether this is a
fresh deployment or the old one.

`KCFG` (the scheduler's YAML config directory) is `/tmp/kcisched-$PROJECT`
precisely so the scheduler's command line is unique per deployment. Without that,
"is a scheduler already running?" matched - and `./run.sh stop` killed - every
pull-labs-riscv scheduler on the machine, including another deployment's (#18).

`PID_FILE` is the ownership record of the host services this deployment starts
(written by `record_service`, read by `./run.sh stop`).

`API_HOST_PORT`/... are exported because the compose file already reads them
(`${API_HOST_PORT:-8001}` ...), so no patching is needed to move a stack off the
default ports.

### Rendering the settings templates

Runtime settings are rendered from the *tracked* `@NAME@` templates into
gitignored files under `work/` (`work/local-callback.toml`,
`work/cb-config/pipeline.yaml`). The reason is that kernelci's `toml.load()`
does not expand environment variables: a tracked file cannot refer to the
checkout next to it or to this deployment's ports, and hardcoding one machine's
values made every clone read another deployment's paths and endpoints.

### The port check

Nothing used to check whether a port was free before a service was started on it.
A port held by an unrelated listener then surfaced three layers down as
"X artifact server failed" - with the real EADDRINUSE only inside
`/tmp/fs8999.log` - or as a compose bind failure that blamed the API.
`docs/HANDOVER.md` used to tell people to move the artifact server off 8999
"because the port is reserved"; that note is stale (8999 binds here), and the
check is what answers the question where it matters instead of by folklore.

The probe itself lives in `kcilib/core/ports.py` and is reached through its
command line: the bind test, the holder lookup and the refusal text are ONE
implementation, shared with `scripts/fetch-and-run-latest.py` (which imports it).
They used to exist twice - here and there - and the two copies already disagreed
about the address to bind: this one probed `0.0.0.0` because the stack binds
`0.0.0.0`, while the library's default is `127.0.0.1`, so "the same check"
answered two different questions. `--host 0.0.0.0` keeps the meaning this script
had; `--project` keeps the "our own compose project is not a conflict" rule, and
`kcilib.core.ports` states it more strictly than the shell did (an empty owner
never counts as ours).

### Service ownership (`record_service`, `PID_FILE`)

`./run.sh stop` used machine-global pkill patterns
(`"scheduler.py.*pull-labs-riscv"`, `"uvicorn lava_callback"`), so stopping one
deployment killed another deployment's services, while the compose teardown next
to it was already project-scoped (#18). Everything started here is recorded as
`role|pid|start-time|pattern`; stop kills exactly those pids after re-reading the
start time, so a recycled pid is never killed.

The `[ -n "$start" ] || continue` line covers a pid that vanished between the
`pgrep` and the `/proc/$pid/stat` read.

### The token sanity check

A non-empty check is not enough: setup's placeholder text ("fill in the local
kernelci-api admin JWT ...") is non-empty, so it used to pass, start the whole
stack, and then 401 on every single API call. The script therefore demands
something that at least looks like the JWT the API hands out - and only warns
(does not fail) when the prefix is missing.

### Seed resolution (`resolve_seed_inputs`)

Resolved BEFORE any service is started. The seed used to be resolved after the
whole stack was up, which is how "work/env/build.env's tree is not one this
runtime accepts" turned into a full start plus a 90 s wait ending in "no job node
appeared" - the node's tree label silently disagreeing with the artifacts being
booted (#1). A seed that cannot work must cost a second.

CONSISTENCY RULE: `work/serve/Image`, the modules baked into
`work/env/rootfs-kvm.ext4` and the URLs in this seed must all be the SAME kbuild.
The worker bakes `modules.tar.xz` into `/lib/modules` and modprobe matches them
by kernel release, so a mismatch makes every kvm test skip ("Cannot open
/dev/kvm"). `./run.sh provision` records the build it provisioned in
`work/env/build.env`; seeding from it is what keeps the three places from
drifting apart. The `SEED_*` defaults are only a fallback for a deployment that
never ran provision - their pinned hash is old, because production storage prunes
builds, which is why provision discovers the newest one instead of pinning.

The revision fields (`SEED_COMMIT`, `SEED_DESCRIBE`, ...) exist so the nodes
created below name the kernel that actually boots. They used to be hardcoded
defaults, which meant a deployment serving 7.3-rc2 created nodes labelled
`v7.3-rc1-516-gf217004a40c49`: the runs were real, the attribution was not. An
explicit `SEED_*` in the environment still wins over all of it.

The whole seed is env-overridable: when production storage prunes the original
build, point `SEED_*_URL` at a newer build and replay.

No tag placeholder: a build whose node carries no `commit_tags` reports none.
Defaulting to `["v7.3-rc1"]` (the previous behaviour) put a tag on a node whose
describe said `v7.3-rc2-655-...` - a self-contradicting record nobody would
notice, since only the describe is displayed.

Seeding with the placeholder is allowed (a hand-made Image has no build
metadata), but it must not happen quietly: every node this creates, and every
line `./run.sh report` prints for them, will name a kernel that was never booted.

`seed_json()`: every value is spliced into a JSON heredoc, so each one is escaped
for JSON rather than interpolated raw - a quote or backslash in a branch name or
a describe string produced an invalid body, and the API answered with a parse
error instead of a node.

### The pre-seed tree guard (`seed_tree_guard`)

The runtime that owns the riscv jobs declares `rules.tree` as an ALLOW-LIST
(`kernelci-pipeline/config/pipeline-pull-labs.yaml`) and the scheduler enforces
it (`kernelci-core/kernelci/api/helper.py:358`, `APIHelper.should_create_node`).
`work/env/build.env` records the tree of the build this deployment actually
serves, so the two can disagree - and when they did, `./run.sh stack --seed`
started everything, printed "seeded; scheduler will auto-create the 3 job nodes",
waited the full 90 s and ended with "no job node appeared", while the only cause
was one scheduler line:

    rules[tree]: Tree net-next not allowed due ['mainline', 'next', 'riscv'].

The check asks the scheduler's OWN code (`should_create_node`) with the
scheduler's OWN config, so it cannot drift from what the scheduler decides.

Inside the embedded python: rules are pure data, so evaluating them needs no API
connection, and a real `APIHelper` would need one - which is why the check can run
before the stack is up.

When the check itself cannot run (kernelci-core not importable, config
unreadable) it says so and carries on: the wait below prints the scheduler's own
rejection reason, so a refusal is still visible instead of silent.

The refusal message lists the two honest ways out: keep the artifacts and label
the seed with an accepted tree (the node's tree then disagrees with the kernel
that boots - recorded in `work/env/seed.env`), or add the build's tree to
`runtimes.pull-labs-riscv.rules.tree` in the scheduler's own config.

### Seed provenance (`write_seed_provenance`)

Written even when the run dies later: the nodes say `tree=$SEED_TREE` while
`work/serve/Image` and the artifact URLs come from the `tree=$KCI_BUILD_TREE`
build, and that difference is invisible in the API.
`KCI_SEED_TREE_MISMATCH=1` triggers the loud message - the run is real, the
attribution is not.

### uid 1000 directories (`check_uid1000_dir`)

The ssh container stores job definitions and result logs through bind mounts into
`kernelci-api/docker/storage/data` and `kernelci-api/docker/ssh/user-data`, as
its own user `kernelci` - uid 1000, see `kernelci-api/docker/ssh/Dockerfile`. A
host directory owned by anybody else makes that upload fail, and it fails
SILENTLY: kernelci-core's `StorageSSH._upload` runs `mkdir -p` fire-and-forget, so
the scheduler sees only "submit error: Failed to store job definition", every job
node is parked as incomplete and `stack --seed` reports "no job node appeared
within 90s" - with nothing pointing at permissions. It is checked here so nobody
has to find that out from a hang; root simply fixes it, any other uid is told
exactly what to run.

### The callback token (`CALLBACK_TOKEN`)

Environment first (the precedence run.sh uses), then this deployment's rendered
settings. The callback validates the Authorization header against
`[runtime].pull-labs-riscv.callback_token`, so reading the configured token is
what keeps a per-deployment token working in this entry point as well. It used to
be the literal `"labtoken-callback"` on the worker launch line: a deployment with
its own token got 401/403, which the worker classifies as a PERMANENT callback
failure, so the job was abandoned behind a one-line message (#10).

The embedded python reads the rendered file with `re` rather than a TOML parser
because python3 here is 3.10 (no `tomllib`) and the renderer emits one line per
runtime; `config/local-callback.toml`'s commented example lines cannot match
because the runtime name is part of the pattern.

If the configured token does not start with `"Token "` the script warns: the
worker sends `Token <PULL_LABS_CALLBACK_TOKEN>`, so the two cannot match and every
result would come back 401.

### Starting the services

* **1) KernelCI API stack.** `docker compose up -d` runs even when the API
  already answers, because only compose knows whether the running containers still
  match the requested port mappings: skipping it left containers on the default
  ports while the rendered cb-config pointed at this deployment's ports, and the
  scheduler then failed to store any job definition ("unable to connect to port
  18022"). With nothing to change this is a no-op that costs about a second.
* Bindability is checked first, and the conflict is named: a compose that cannot
  publish 8001 reports it in its own words, and the reader would otherwise hunt
  through the API's logs for a problem that is an unrelated listener on the port.
* After a machine/docker restart, stale Exited containers cause compose name
  conflicts; the data lives in volumes, so removing
  `kernelci-api`, `kernelci-api-db`, `kernelci-api-redis`,
  `kernelci-api-storage` and `kernelci-api-ssh` is safe.
* **images.env.** Which artifact is actually running is *recorded*, not inferred
  afterwards: `kernelci-api/docker-compose.yaml` pulls a *mutable* tag
  (`${KERNELCI_API_IMAGE:-kernelci/staging-kernelci}:${KERNELCI_API_TAG:-api}`), so
  the image this deployment tested can change under it overnight, and without this
  record no report can name the artifact it verified. It is read back from the
  running container rather than from the tag that was requested. When the read
  fails the script says so instead of silently writing nothing: a renamed
  container (`KCI_COMPOSE_PROJECT`, an override) would otherwise vanish without a
  trace.
* **`rotate_log`.** `stop` + `stack` used to truncate the previous round's
  service logs, because every service logs to a fixed `/tmp` path - so after a
  restart the round that produced a result was no longer auditable. One generation
  is rotated instead, and ONLY when the service is about to be started below:
  rotating unconditionally moved the log file of an ALREADY RUNNING service to
  `.prev`, leaving the live round with no log path at all while the service kept
  writing to the moved inode (caught by an adversarial review, then observed live).
* **Subshell redirection.** Each service launch redirects the SUBSHELL's own
  stdout/stderr as well as the service's. Redirecting only the service left the
  subshell holding the caller's stdout, so `./run.sh stack | tee log` never saw
  EOF and appeared to hang long after the stack was up.
* **2) artifact server.** A listener on the port that does not answer `/Image` is
  exactly the case the old message hid ("X artifact server failed", with the real
  EADDRINUSE only inside `/tmp/fs8999.log`); `require_port_free` names the port and
  the holder. When it fails to start, the service's own log tail is printed - the
  log is the evidence, not just the file name.
* **3) lava_callback.** It runs on the HOST (not in a container) and imports the
  cloned kernelci-core, so its imports have to be installed here. Importing the
  module is the honest check: listing four packages missed what the callback
  actually needs transitively (kernelci-core wants `elftools`, and a machine with
  only PyJWT/toml/uvicorn/fastapi still died here with a bare "callback failed (see
  /tmp/cb8003.log)"). `KCI_SETTINGS` must be set for the check to mean anything:
  `lava_callback.py` reads it AT IMPORT TIME (`toml.load`), and it is otherwise only
  set inline on the launch line - so an import check without it fails with
  `FileNotFoundError: 'config/kernelci.toml'` on a perfectly healthy machine and
  blames dependencies that are installed (caught by adversarial review of this very
  check, N11).
* **4) scheduler.** A second scheduler on the same API dispatches every job a
  second time (both subscribe to the same node events), so a scheduler that is not
  ours is a conflict to report, not something to duplicate. Before this deployment
  got its own config directory it could not tell.

### Seeding (the `--seed`/`--worker` branch)

* The seed itself was resolved, and its tree label checked against the runtime
  rules, BEFORE any service was started (`resolve_seed_inputs` /
  `seed_tree_guard`). What is left here is the local preflight, the checkout parent
  and the POST.
* Preflight: the local Image is a hard requirement; broken production URLs only
  warn (that job will report Infrastructure honestly; override and retry).
* The artifact probes use the user's proxy configuration as-is. This used to unset
  `http_proxy`/`https_proxy` unconditionally, with a comment about "the dead local
  proxy" - one machine's temporary state. Someone whose proxy works would have it
  silently removed; `KCI_BYPASS_PROXY=1` is the explicit opt-in for a broken one.
  Note what this does and does not cover: these three URLs are the ARTIFACT host,
  while the API calls below are a different endpoint, so a green line here is not a
  verdict on them (and vice versa).
* The probe is a HEAD, not a Range request: files.kernelci.org ignores Range and
  streams the whole file, so a range check on a big artifact always times out.
* A kbuild node hangs off a checkout node, so the seed needs one to exist. On a
  fresh database there is none - and the old lookup crashed (`IndexError` from
  `items[0]` on an empty list) and carried on with an empty parent, so the very
  first `./run.sh stack --seed` of a new deployment died. The checkout node is
  created when the database has none.
* The checkout body goes through a `mktemp` file rather than piping a heredoc into
  python: a pipe after a heredoc terminator inside a command substitution is a
  syntax error bash only reports when it reaches the line.
* `-m 30` on the seed POST: the first POST after an API restart can stall
  mid-response, and curl must not wait forever. The node may already exist
  server-side; re-running only adds one more seed node, which is harmless in the
  dev DB.
* Inside the seed JSON, `artifacts.kernel` is
  `http://172.17.0.1:$SERVE_PORT/Image` - the container's view of the host.
* The wait exists because seeding and then immediately running
  `./run.sh worker --once` used to hit an empty queue: the worker printed "batch
  processed, exiting" having run nothing at all, which looks like success and is
  deeply confusing.
* On timeout the scheduler's own reason is printed first: a rule rejection is a
  plain stdout line in a log full of paramiko debug, so "check
  /tmp/sched-local.log" left the reader without the one sentence that explains it
  (#4). The grep looks for `rules\[`, `not allowed` or `Not creating node`;
  otherwise the reader is pointed at "submit error", "unable to connect" or a
  traceback near the end of the log.
* The tree-label mismatch is pointed at (`work/env/seed.env`) rather than letting
  the node's label and the booted artifacts drift apart silently (#1).

### The worker launch

The callback token comes from the environment or this deployment's rendered
settings (see `CALLBACK_TOKEN`), not from the literal that used to sit on this
launch line: the callback validates the header it receives against the configured
`callback_token`, and a hardcoded value 401s every per-deployment token (#10). The
worker's state file and output directory are also project-scoped
(`/tmp/kci-worker-$PROJECT-*`), so two deployments cannot share a queue.

### Kept verbatim

* `# Loud on purpose: the run is real, the attribution is not.` - the one-line
  summary of the tree-label hazard; shortening it would lose the meaning.
* `# shellcheck source=net-preflight.sh`, `# shellcheck disable=SC1091` and the
  `--- section ---` separators - directives and navigation, not prose.
* The `echo "# ..."` lines that are written INTO `work/env/seed.env` and
  `work/env/images.env`: those are generated file content (behaviour), and the note
  inside `images.env` ("kernelci-api's compose file pulls a mutable tag, so this is
  the only durable record of what was tested; re-read on every stack start") is
  read by humans later, from the file, not from the script.

## scripts/net-preflight.sh

Why the file exists: the previous code unconditionally unset
`http_proxy`/`https_proxy` with a comment saying "the local proxy is dead; direct
access works". That is one machine's temporary state baked into a public
repository. Someone behind a working proxy (a lab, a corporate egress proxy, a
mirror-only network) would have it silently removed, and their downloads would
break instead of the author's.

The contract that replaced it:

    (default)            honour the environment and git proxy configuration
    KCI_BYPASS_PROXY=1   ignore the proxy configuration for this run

Probe with the configuration exactly as the user set it, and only fall back to a
direct connection when the proxy is demonstrably broken - saying so out loud, and
letting the user force either mode.

Nothing here changes the environment of the caller's shell: bypassing is applied
per command (`env -u ...`), so a run cannot leak a modified environment into the
next one.

Per function:

* `kci_curl` - curl honouring the user's proxy configuration, or `--noproxy '*'`
  when a bypass is requested.
* `kci_curl_direct` - curl over a direct connection, whatever the environment
  says (the proxy variables are removed from the child environment).
* `kci_run` - needed for helpers that read the proxy variables themselves
  (python-requests, tuxrun, git).
* `kci_git` - git honouring the bypass switch. `lowSpeedLimit`/`lowSpeedTime` turn
  "hangs forever behind a dead proxy" into "fails after 20 s of no progress",
  which is what makes the retry loops useful.
* `kci_proxy_works` - probes one proxy URL with the probe endpoint and returns 0
  when it can carry the request. It is used to name the *failing* entries instead
  of listing every setting a user has: the list used to imply a working proxy was
  broken and never tested git's own proxy - which is the one that actually kills
  `git clone`, because that is what git uses regardless of what the `http_proxy`
  environment says.
* `kci_proxy_report` - where the proxy configuration currently comes from, for
  error messages. Only settings that FAILED the probe are printed as broken; the
  rest are listed as working, because "these are your proxy settings" was read as
  "these are the problem" even when the proxy in question answered fine. SOCKS
  proxies are reported as not probed; git's own `http.proxy`/`https.proxy` are
  included.
* `kci_net_preflight` - returns 0 when the network is usable and 1 with actionable
  advice when it is not; callers decide whether that is fatal. The "reachable
  directly but not through your proxy" branch prints the per-setting report and
  suggests either fixing the settings or `KCI_BYPASS_PROXY=1`.
* `kci_git_clone` - clones with retries and falls back to a direct connection when
  the configured proxy is dead. This is the single most common failure on a fresh
  machine: a stale proxy entry makes `git clone` hang with no output at all. On the
  first failure it retries directly (`KCI_BYPASS_PROXY=1`), then two more times
  with a 3 s pause, removing a partial destination before each attempt.

`KCI_PROBE_URL` (default `https://files.kernelci.org/`) and
`KCI_PROBE_TIMEOUT` (default 10 s) are the knobs the two probes above share.

## scripts/local-instance-init.sh

### The header is frozen on purpose

`usage()` runs `sed -n '2,21p' "$0"`, so lines 2-21 of this file ARE the `--help`
output. They were left byte-for-byte unchanged: shortening them would change
user-visible behaviour, not just a comment. The same reasoning applies to the
final `next step` line.

The header documents: the three steps (each reporting "using existing" vs
"generated") - `kernelci-api/.env` from `env.sample`; the SSH keypair
(`kernelci-pipeline/data/ssh/id_rsa_tarball` private +
`kernelci-api/docker/ssh/user-data/authorized_keys` public); `KCI_API_TOKEN` in
`kernelci-pipeline/.env` via HTTP login (`POST /latest/user/login`), falling back
to in-container minting when the login route is absent, then verifying it - and
the flags: `--force` (regenerate the SSH keys AND overwrite `kernelci-api/.env`;
a new SECRET_KEY invalidates every existing JWT), `--quiet`, `--skip-token`.

Secrets never land in git-tracked files: `kernelci-api/` and
`kernelci-pipeline/` are gitignored in this repo.

### Deployment identity

Matching `scripts/run-local-stack.sh`: the compose project decides which
containers and data volumes this deployment owns, so a second isolated stack on
the same machine keeps its own database.

The port exports must stay in sync with `scripts/run-local-stack.sh`: the compose
file publishes `${API_HOST_PORT:-8001}` and friends, so starting the containers
here without all of them leaves this deployment on the default ports while the
rendered cb-config points at the custom ones - which surfaces later as the
scheduler failing to store a job definition ("unable to connect to port
<ssh port>").

### Helpers

* `set_env <file> <key> <value>` replaces an existing `KEY=` line or appends one.
  The values used here are restricted to `[A-Za-z0-9@._/:+-]` so the `sed`
  substitution is safe.
* `api_up` is true (exit 0) when the API answers on `/latest/` - any HTTP status
  means the server is up, matching `scripts/run-local-stack.sh`'s readiness probe.
* `whoami_code <token>` prints the HTTP status of `/latest/whoami` with the bearer
  token: 200 means the token authenticates, anything else means
  invalid/expired/missing.

### `mint_token_in_container`

Prints a fresh JWT for the admin by running the API's own code INSIDE the api
container: the JWT strategy (so the token is signed with the SECRET_KEY the API
itself loaded) and, on a database with no user at all, the same first-admin
bootstrap that `api/main.py`'s `ensure_initial_admin_user()` performs.

That bootstrap has to happen here because the app actually served is
`versioned_app`, whose `on_startup` list does not include
`ensure_initial_admin_user` - so a genuinely fresh database never gets an admin,
and with no admin no token can be minted at all. Credentials come from the
container's own environment (`KCI_INITIAL_*`), the same place the API would have
read them. The token goes to stdout; a non-zero exit with a message on stderr
means the container is unreachable or the bootstrap is impossible.

Inside the embedded python, the password is hashed with `bcrypt` directly and NOT
with `Authentication.get_password_hash()`: the api image ships passlib 1.7.4
together with bcrypt 5.0.0, and passlib 1.7.4 reads
`bcrypt.__about__.__version__`, which bcrypt 4.1 removed. passlib traps that
failure, falls back to a stub backend and then raises the thoroughly misleading
"password cannot be longer than 72 bytes". bcrypt itself works, so hashing with it
directly is the call passlib would have made anyway, and it keeps the flow
independent of that mismatch.

### The API token step

* An already-valid token is reused: a re-run must not churn a working token. A
  placeholder or expired token fails `whoami` and is replaced.
* The official login endpoint is tried first; when this kernelci-api build has no
  registered login route (upstream versioned-app regression -> 404/405), the
  script falls back to minting the token inside the api container with its own JWT
  strategy. Other failing codes are reported with their HTTP status before the
  same fallback.
* After minting, only the JWT-shaped line is kept: docker compose is free to print
  warnings on stdout, and a polluted token would only surface as a confusing
  `whoami` failure further down. If nothing JWT-shaped comes back, the first 200
  characters of the compose output are shown.
* The token is verified on an authenticated endpoint (`/latest/whoami` must return
  200) before it is written to `kernelci-pipeline/.env`.
* Before the step, the API stack is started if needed (compose `up -d` for
  `api db redis storage ssh`) and waited for up to 80 s.

### Unchanged, and why

The three `--- N) ... ---` separators, the shebang, and every `echo`/`die`
message (user-visible output) were left alone. The `KCI_INITIAL_*` values written
by this script are what `mint_token_in_container` reads back later, which is why
the admin username/password defaults stay in step with the `grep` above them.
