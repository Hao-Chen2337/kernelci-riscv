# Group B code notes: long-form rationale moved out of the code

These notes hold the long-form explanation that used to live in the comments and
docstrings of the two files below. The code now carries a one-line summary of
each point (and points here where the detail matters); nothing from the original
text was dropped. Comments and docstrings are English-only and short by policy.

## scripts/kcilib/run/delivery.py

### Why there are two delivery modes

The same guest can be fed its artifacts from two places, and the choice changes
what a failed run means.

**in_container** (what kcilib/run/jobrun.build_command does today, and the
module default): the artifact URLs go straight into the tuxrun command line
(`--kernel <url>`, `--modules <url>`, `KSELFTEST=<url>`) and the container
tuxrun starts downloads them itself. It is stateless, uses no host disk and
needs no extra port. The price is a real network dependency on every single
run: if the CDN hiccups, this run becomes Infrastructure. It also gives up all
control over whether the artifact is complete - a kernel truncated halfway
through the download is handed straight to qemu, and the failure scene stays
inside the guest.

**local_server** (what scripts/fetch-and-run-latest.py has always done):
artifacts land locally first (work/downloads/<build>/, work/env/), their size is
verified, and a local HTTP server feeds them to the container. The container
cannot read host paths, so "a local file" has to appear as HTTP. What that buys:

* **Verification before boot.** ensure_artifact() / ensure_kernel_image() only
  treat a file as a cache hit when it has been proven complete: by the size
  recorded in the manifest, by the server's Content-Length, or by the original
  length recorded in the gzip trailer. Anything that does not match is
  re-downloaded instead of being used to boot. The "exists and is non-empty"
  Image left behind by an interrupted gunzip is exactly what this guard stops.
* **The served size must equal the size on disk.** start_artifact_server()
  reads Content-Length back through the very port tuxrun is about to be given
  and refuses to run on a mismatch - the wording is "refusing to boot a
  different or truncated kernel". Booting some other, or a truncated, kernel
  while reporting that this build ran is the hardest failure to diagnose on
  this path.
* **Offline and swappable kernels.** file:// sources and a hand-written
  --kernel-url take the same route, so artifacts do not have to come from the
  production CDN.

The cost is one extra copy on the host disk, one extra port, and the
download/verification code that has to be maintained.

### Capability, not choice

This module provides capabilities; it never makes the choice for a caller. Each
mode has a name, and the executor layer only asks one question - "which address
should the kernel come from" - through kernel_url():

```
in_container:   kernel_url(IN_CONTAINER, url) is url itself;
local_server:   ensure_artifact(...) -> verify on disk ->
                server = start_artifact_server(out, port, node, kernel) ->
                kernel_url(LOCAL_SERVER, url, f"{base}/Image") ->
                stop_artifact_server(server).
```

Today kcilib/run/jobrun.build_command() is still in_container and
scripts/fetch-and-run-latest.py is still local_server; wiring the two lines
together is a separate step and is not a decision this module makes for them.

### Provenance of the moved implementation

What moved into this module is the implementation
scripts/fetch-and-run-latest.py used to own (ensure_artifact /
ensure_kernel_image / the manifest and size records / the local HTTP server),
moved verbatim, with only the script's private names turned into public ones.
Every line it prints (`  downloading <name> (<url>)`, `kernel -> <path> (...)`,
`artifact server on <port> serves ...`) is that script's console contract and
must not change during the move. The English comments and function bodies that
came along are kept as they were rather than tidied up: those comments carry the
conclusions of real failures (#13, the truncated Image; #12, the stale artifact
server).

### Layout ownership

ROOT, the work/ layout and the definition of work/env/.manifest.json live here:
the artifact manifest is a delivery-layer concern, and
scripts/fetch-and-run-latest.py takes this layout from the module instead of
writing its own copy.

### Per-symbol detail that was cut

* `ROOT` is derived from this file's own location, never a hardcoded absolute
  path. The original script reached the repository root with one dirname();
  this file needs four. Counting dirname() levels is the trap: a stale count
  silently puts downloads - and the artifact server's document root - under
  scripts/ instead of the repository root. kcilib.repo_root() walks up to
  run.sh instead, so it can never be off by one. work/ is gitignored and holds
  regenerable runtime artifacts.
* `SERVE_READY_TIMEOUT` is how long a freshly started artifact server gets to
  serve its build-id file back before the run is refused (see
  start_artifact_server).
* `validate()`: a misspelled mode field must not silently fall back to the
  default, because that makes "I chose local_server" and "I chose nothing" look
  identical on the console - and those two choices fail in completely different
  ways.
* `kernel_url()`: it deliberately does not build the served URL for the caller.
  The gateway part of that URL is deployment knowledge about how a container
  reaches the host, and the entire point of local_server is that the production
  URL is replaced by a local one, so it has to be passed in explicitly. Not
  passing it is a programming error, not a default that can be guessed.
* `download()` is ensure_artifact()'s own single-shot transfer and was left
  exactly as it was. kcilib.run.artifacts.download() - which fetch() below uses
  for the same job - prints different lines ("Downloading <url>", then
  "           -> <dest> (N bytes)") and resumes partial transfers through .part
  files. Swapping it in here would change the console of every run and the
  contents of work/downloads/<build>/ (which is reported).
* `cache_hit()`: an existing file with no manifest record at all is adopted
  (fresh clone, or a pre-seeded work/), but a file recorded under a different
  key - another build's kernel or modules - must be regenerated. A record-less
  file still has to look complete, because a truncated Image boots as garbage
  while the stage reports success (#13).
* `fetch()`: file:// sources are copied locally, which is what the offline
  tests rely on; http(s) goes through kcilib.run.artifacts.download (resume plus
  size/truncation checks - the same transfer implementation the worker uses).
  The printed `copied <src> -> <dest> (...)` line is the console contract of the
  script that used to own this function, and that script still re-binds
  kcilib.run.bake.download to THIS function so the bake's tarball transfer
  prints the same line.
* `_ensure_symlink()`: work/serve/Image is a symlink to ../env/Image, so the
  artifact server serves the canonical kernel file.
* `check_consistency()`: the kernel Image and the modules baked into the rootfs
  must come from the same kbuild node; a mismatch makes every kvm test skip with
  "Cannot open /dev/kvm".
* `provision_kernel()`: the compressed artifact is kept next to the Image
  (recorded in the manifest under its own key) instead of being deleted after
  gunzip. This CDN truncates downloads often enough that re-provisioning a
  correct artifact should not depend on the network at all.
* `ensure_artifact()`: a bare os.path.exists() once adopted an Image that an
  interrupted run had left truncated and handed it to tuxrun as a kernel (#13).
  Reuse therefore has to be proven: by the size recorded when this script wrote
  the file, or - for a file it did not write, e.g. a pre-seeded
  work/downloads/ - by the server's Content-Length. A recorded size that does
  not match is proof of truncation and is reported as such; anything that cannot
  be shown complete is fetched again.
* `ensure_kernel_image()`: the Image is written through a .part file plus a
  rename, so a partial kernel can never appear under the final name. It is only
  reused when its recorded size still matches the compressed artifact it came
  from: an interrupted *gunzip* leaves both files present and non-empty, which
  is exactly the case a plain existence check cannot see (#13). A truncated .gz
  fails inside the copy (EOFError / BadGzipFile) instead of leaving a
  half-written Image in place.
* `start_artifact_server()`: the old code started http.server with
  stdout/stderr on DEVNULL and slept a fixed 1.5s. A server left on the port by
  a killed earlier run kept serving an older work/downloads/<node>/, so the run
  tested one kernel while the console - and the log - named another (#12). Now
  the port is probed first (busy means a loud refusal, never a silent swap), the
  server logs into the build directory instead of DEVNULL, and its build-id file
  plus the served Image size are read back through the very port tuxrun is
  handed. The probe is kcilib.core.ports.port_is_free(): binding is the only
  honest test, and it binds 0.0.0.0 because that is how the stack serves - a
  probe against any other address would test a different thing and could report
  a busy port as free. The refusal names the holder through
  kcilib.core.ports.port_holder(). The refusal wording still names
  --serve-port, the flag of the script that calls this: that wording is part of
  the script's console contract, and the reader is the one who has to be told
  how to move the port. Those refusals are sys.exit() because this function's
  only caller today is a command-line script whose exit status IS the verdict; a
  resident caller (the worker, if local_server is ever wired into jobrun) must
  NOT get a SystemExit out of a library call, since it would take the daemon
  down with it - that step needs a raised exception instead, and a per-job port
  rather than one fixed --serve-port.

## scripts/kcilib/table/buildref.py

### Why this layer exists

Everything downstream - generating jobs, running tests, computing config drift -
needs a **stable build identity**, and a KernelCI node id is not it. A node id
says which database allocated it: the local and production instances each hand
out their own, and the same build has unrelated ids on the two sides. Measured
example: the local job node 6aa822fcf84821b97339d2f9 carries the production
build 6aa3689720239ade90209d50.

What is stable is the id inside the artifact URLs, plus tree/commit. So:

```
node (a complete node from any source)  --build_ref_from_node()-->  BuildRef (one row)
a batch of nodes from the production API --builds_from_production_api()-->  [BuildRef]
```

BuildRef carries only the fields the executor actually uses (kernel / kselftest
/ modules / _config) and nothing more: it is stored in the local index table,
which records "is this enough to run", not a node snapshot.

### Per-symbol detail that was cut

* `ARTIFACT_KEYS` are the artifact keys the executor understands, with the same
  names the upstream template renders. `_config` is only useful for config
  drift, but it is still copied down because it is the sole source of "the
  compile configuration of this build".
* `REQUIRED_FOR`: for a build to be runnable it needs at least a kernel, and
  the kselftest suites additionally need the collection tarball
  (kselftest-kvm also needs modules).
* `BuildRef`: *build_id* is half the primary key (the other half is the test
  name). *source* is the only field this layer owns; everything else is copied
  from the node, so that the local index is an index and not a second source of
  truth.
* `missing_for()`: missing artifacts are not an error but the normal case - a
  failed build produces nothing. Measured: of 58 kbuild-gcc-14-riscv nodes in
  the local database, 15 have result=incomplete and empty artifacts. No job
  under those builds can run at all, and finding that out up front beats finding
  it out halfway through.
* `build_ref_from_node()`: pure - no network, no disk. *node* is any
  KernelCI-shaped dict, whether it came from the official API, was copied, or
  was hand-made; all are treated the same, which is why this layer takes nodes
  and not ids (a hand-made node has no id to look up). build_id is parsed from
  the artifact URLs with artifacts.build_id_from_artifacts(); when that fails it
  falls back to the node's own id while keeping *source* unchanged, so the
  caller can tell how solid this row's identity is. A node with no kernel
  artifact raises ValueError: a build that cannot run does not belong in the
  table.
* `BuildQuery`: which builds to look for on production, as explicit fields
  rather than a guessed "last N days". Every field corresponds to one API filter
  parameter (or to one local filter), so "what was found is what was wanted" is
  readable at the call site instead of hiding behind a day-count magic number.
* `accepts()`: this is where the conditions the API does not support are
  applied. It returns (ok, reason), and reason is only non-empty when ok is
  False, so a caller can report "200 nodes came back, here is why each was
  dropped" - silent filtering is a common source of "why is there no build for
  this" questions.
* `fetch_nodes()`: goes through kcilib.api, the single API client in the whole
  repository. This function used to build URLs and open urllib itself; now only
  constructing the filter parameters is local knowledge, and fetching plus error
  classification live in kcilib/api.py in one place (there used to be five
  copies).
* `builds_from_production_api()`: read-only and needs no token. It returns the
  BuildRef list sorted by query.order plus the dropped (id, reason) pairs, so a
  caller that wants to print "why no build was found" does not have to query
  again. `result` is not an API filter parameter, so it is applied locally: the
  API also returns nodes whose build failed (incomplete), and their artifacts
  are either missing or incomplete.
