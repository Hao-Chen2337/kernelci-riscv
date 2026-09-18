# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The middle job layer: one test on one build, and the outcome it produced.

Job is the intent (build, test, timeout) plus the definition its executor gets;
Outcome is what one run produced; Jobs is the collection that runs them one
after another.  Job renders its own definition (definition()), shaped like
kernelci-pipeline's pull_labs.jinja2, and the run is kcilib.run.jobrun's - so
this layer owns the definition and re-implements no execution.

It used to be two names: JobSpec was the table's row and Job was this card, and
every caller converted one into the other (and a card into a BuildRef and back)
before anything could run.  JobSpec and jobs_from_build() are gone; jobs_for()
is the one "one build -> its jobs".

How a run's artifacts reach the guest is kcilib.run.delivery's two modes:
in_container (the default - run_node hands tuxrun the URLs and the container
downloads them) and local_server (this layer downloads and proves them first,
then serves them to the container over HTTP).  Which mode a run used, and
which ledger source its record is filed under, are run() arguments, so the
worker's line, the table's and the one-shot fetch line are one call with three
answers.

local_server is the one-shot line's mode, and it carries that line's own
conventions with it: tuxrun is announced as "running:", run from the caller's
directory, and judged by kcilib.run.judge - a one-shot run posts no callback,
so its console is the evidence and its verdict is what its process status and
its ledger record report.  A caller whose line names its records its own way
passes record_fields, and the record on disk is then that line's record.
"""

from __future__ import annotations

import os
import shutil
import socket
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace as _replace

from kcilib.core import config as _config
from kcilib.core import ledger as _ledger
from kcilib.core import params as _params
from kcilib.core import policy as _policy
from kcilib.run import artifacts as _artifacts
from kcilib.run import callback as _callback
from kcilib.run import delivery as _delivery
from kcilib.run import jobrun as _jobrun
from kcilib.run import judge as _judge
from kcilib.run import runner as _runner
from kcilib.table.build import ORIGIN_API, ORIGIN_API_LOCAL, Build

from .builds import Builds
from .nodes import (
    JobPuller,
    KernelCINode,
    origin_for,
)

# The RunConfig fields run() accepts as overrides.  Anything else is a typo and
# raises TypeError naming this tuple, instead of being dropped silently.
RUN_OVERRIDES = (
    "container_runtime", "tuxrun_bin", "platform", "cpu", "rootfs",
    "max_timeout", "min_timeout", "max_download_size",
    "log_dir", "output_dir", "keep_workspace",
)

# The run-level arguments run() takes beside those overrides: they say HOW the
# run is made (which delivery, whose ledger record, where its artifacts are
# served from), not what the run is.  Jobs.run() forwards them to every job.
RUN_ARGUMENTS = (
    "config", "delivery", "source", "node_id", "serve_port", "gateway",
    "out_dir", "record_fields",
)

# The two ways artifacts reach the guest, as kcilib.run.delivery names them.
DELIVERY_IN_CONTAINER = "in_container"
DELIVERY_LOCAL_SERVER = "local_server"
DELIVERIES = (DELIVERY_IN_CONTAINER, DELIVERY_LOCAL_SERVER)

# Who filed a ledger record.  The worker's and the table's names are
# kcilib.run.jobrun's (one vocabulary, not two); the fetch line's is the
# one-shot runner's own.
SOURCE_FETCH = "fetch"
SOURCE_TABLE = _jobrun.SOURCE_TABLE
SOURCE_WORKER = _jobrun.SOURCE_WORKER

# local_server defaults: the port the one-shot line has always served on, and
# the address a container reaches this host on when host.docker.internal does
# not resolve (docker's own bridge address).
DEFAULT_SERVE_PORT = 8998
DEFAULT_GATEWAY = "172.17.0.1"

# The artifacts tuxrun fetches, and the name each is served under.  A
# definition's URLs are rewritten to the local server for these keys and only
# these: a rootfs is tuxrun's own bind mount, and no other artifact is read by
# the run layer.
SERVED_ARTIFACTS = (
    ("kernel", "Image"),
    ("kselftest", "kselftest.tar.xz"),
    ("kselftest_tar_xz", "kselftest.tar.xz"),
    ("modules", "modules.tar.xz"),
)

# The console a local_server run keeps beside the artifacts it downloaded.
# kcilib.run.jobrun archives a console as <log_dir>/<node id>.log, while the
# one-shot fetch line's has always been
# work/downloads/<node id>/tuxrun.log (docs/ARCHITECTURE.md): _keep_console
# makes both names the same file rather than one of them pointing at nothing.
CONSOLE_NAME = "tuxrun.log"

# The verdict vocabulary of an Outcome (kcilib.run.judge's), plus the exit code
# a failure OUTSIDE run_node is filed under.
VERDICT_PASS = "pass"
VERDICT_ERROR = "error"
EXIT_ERROR = 3

# Timeout for a test policy.POLICY.seconds_test_timeouts does not name.
DEFAULT_TIMEOUT = 600

# Origins whose builds came from a KernelCI API, i.e. the table layer's
# "official" source; every other origin is a local one.
_OFFICIAL_ORIGINS = (ORIGIN_API, ORIGIN_API_LOCAL)


def _run_config(overrides: dict[str, object]) -> _config.RunConfig:
    """A RunConfig from run()'s overrides, rejecting any unknown name.

    The defaults are kcilib.core.config's own - the CLI's - so a Job run
    without overrides behaves exactly like a worker run.
    """
    unknown = sorted(set(overrides) - set(RUN_OVERRIDES))
    if unknown:
        raise TypeError(
            f"unknown run override(s): {', '.join(unknown)}; run() accepts "
            f"{', '.join(RUN_OVERRIDES)}")
    return _config.RunConfig(**overrides)


def _source_for(origin: str) -> str:
    """The index's coarse *source* column for a Job's origin."""
    return "official" if origin in _OFFICIAL_ORIGINS else "local"


def _delivery_of(name: str) -> str:
    """*name* when it is a delivery this layer knows, else a ValueError.

    Spelling the two out in the message rather than leaving a KeyError lookup:
    a mangled name ("in-container", "local-server") is the common mistake, and
    the right spelling is what the reader then has in front of them.
    """
    if name not in DELIVERIES:
        raise ValueError(f"unknown delivery {name!r}; delivery accepts "
                         f"{', '.join(DELIVERIES)}")
    return name


def _run_config_for(config: _config.RunConfig | None,
                    overrides: dict[str, object]) -> _config.RunConfig:
    """The RunConfig this run uses: the caller's, or one from the overrides.

    Both at once is refused rather than silently half-honoured: the caller
    asked for two runs, and only one of them can happen.
    """
    if config is None:
        return _run_config(overrides)
    if overrides:
        raise TypeError("run() takes config or run overrides, not both: "
                        + ", ".join(sorted(overrides)))
    return config


def _artifacts_of(definition: Mapping[str, object]) -> dict[str, str]:
    """A definition's artifact URLs, read the way the run layer reads them.

    An absent, non-mapping or empty URL drops out here, so a malformed
    definition costs a missing artifact and not an exception.
    """
    artifacts = definition.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return {str(key): str(value) for key, value in artifacts.items() if value}


def _served(definition: dict, base: str) -> dict:
    """*definition* with every artifact tuxrun fetches pointing at *base*.

    Only the served keys move.  The kernel config is downloaded as this run's
    evidence but is read by nobody in the run layer, so it keeps naming the
    build it came from - which is also where a ledger record's build id comes
    from when the caller named no node.
    """
    artifacts = _artifacts_of(definition)
    served = dict(definition)
    for key, name in SERVED_ARTIFACTS:
        if artifacts.get(key):
            artifacts[key] = f"{base}/{name}"
    served["artifacts"] = artifacts
    return served


def _gateway(requested: str | None) -> str:
    """The address the container reaches this host's artifact server on.

    The default is the one the one-shot line has always used: docker's own
    name for the host when it resolves, and the bridge address when it does
    not (a --gateway override beats both).
    """
    if requested:
        return requested
    try:
        return socket.gethostbyname("host.docker.internal")
    except OSError:
        return DEFAULT_GATEWAY


def _fetch_console(argv, timeout=None, log_path=None, *, cwd=None,
                   stream_separator="\n"):
    """kcilib.run.runner.run_tuxrun with the one-shot line's separator.

    The two lines' archived consoles differ by exactly this one thing: the
    worker joins the captured stdout and stderr with a newline (the rule
    kcilib.run.jobrun.run_command spells itself), the one-shot fetch line
    concatenates them with nothing between, and that console is what the
    operator reads at work/downloads/<node id>/tuxrun.log.  run_command reaches
    the runner through the module attribute kcilib.run.jobrun.run_tuxrun, which
    a caller may re-bind - the same seam kcilib.run.bake documents for its
    download() and stamp() - so local_server re-binds it for the length of one
    run instead of asking the run layer to carry a flag the table line does not
    have.  Every other argument is the caller's, unchanged.
    """
    return _runner.run_tuxrun(argv, timeout=timeout, log_path=log_path,
                              cwd=cwd, stream_separator="")


def _oneshot_run_command(captured: list):
    """kcilib.run.jobrun.run_command as the one-shot line has always run it.

    A replacement for the run layer's own command step, which prints
    "Running:", works from the job's workspace and gives tuxrun the job's
    timeout plus a grace.  The one-shot line has always printed "running:",
    run tuxrun from the caller's directory and bounded it by
    kcilib.run.judge.TUXRUN_TIMEOUT, because its console is read by people and
    two runs of the same job must look the same (the definition's timeout is
    the queue's, and this line has no queue).  The separator is not repeated
    here: the runner it calls is the _fetch_console seam, which owns it.

    *captured* receives the CompletedProcess, so this layer can judge the very
    console the run archived (see _judged): what run_tuxrun returned is exactly
    what it wrote to work/downloads/<node id>/tuxrun.log.
    """
    def run_command(cmd, timeout_s, workspace):
        log_path = os.path.join(workspace, "tuxrun.log")
        print("running:", " ".join(cmd))
        proc = _jobrun.run_tuxrun(cmd, timeout=_judge.TUXRUN_TIMEOUT,
                                  log_path=log_path, cwd=None)
        captured.append(proc)
        return proc.returncode, proc.stdout
    return run_command


def _judged(captured: list, test: str) -> tuple:
    """The one-shot line's (verdict tuple, console), or (None, None).

    kcilib.run.judge.judge_run over the console this run just captured: that
    function is the one-shot line's judgement (its exit statuses, its detail
    wording and its TAP), and a served run posts no report for the caller to
    read instead.  Nothing to judge when no console was captured - a caller
    that replaced the executor, a run that never reached it - and then the
    report body is what is left to read.
    """
    if not captured:
        return None, None
    proc = captured[-1]
    return _judge.judge_run(proc.returncode, proc.stdout, test), proc.stdout


def _quiet(_message: str) -> None:
    """The one-shot line's progress printer: it prints none.

    kcilib.run.bake.stamp announces every stage as "[HH:MM:SS] <what>" - the
    worker's and the table's console.  The one-shot line has never had those
    lines (its own are the "running:", "log kept at:" and "result record:"
    ones), and jobrun's docstring names the printer as re-bindable, so
    local_server re-binds it for the length of its own run.
    """


def _repo_relative(path: str) -> str:
    """*path* relative to the repository root, the way ledger rows spell paths.

    The one-shot line has always filed "work/downloads/<id>" rather than an
    absolute path, and kcilib.core.ledger's rows are relative to the same root.
    """
    return os.path.relpath(path, _ledger.ROOT)


def _keep_console(archived: str | None, console: str) -> str | None:
    """Keep a run's console under both names, and return the one to report.

    kcilib.run.jobrun archives the console as <log_dir>/<node id>.log - the
    path the ledger record it wrote names - while the one-shot line's console
    has always been <out>/tuxrun.log (docs/ARCHITECTURE.md, and what
    ./run.sh prune and the operator read).  One hard link makes both names the
    same file, so neither reader is handed a path that is not there; copying
    is the fallback for a link that crosses filesystems.  None when this run
    kept no console at all - pointing at an older run's file would be worse
    than pointing at nothing.
    """
    kept = _existing(archived)
    if not kept:
        return None
    if os.path.abspath(kept) != os.path.abspath(console):
        if os.path.lexists(console):
            os.unlink(console)
        try:
            os.link(kept, console)
        except OSError:
            shutil.copyfile(kept, console)
    return console


def _existing(path: str | None) -> str | None:
    """*path* when it is on disk, else None: no file, no evidence to point
    at."""
    return path if path and os.path.exists(path) else None


def _is_definition(definition: object) -> bool:
    """True when *definition* has the shape run_node reads from it."""
    if not isinstance(definition, dict):
        return False
    tests = definition.get("tests")
    if not isinstance(tests, (list, tuple)) or not tests:
        return False
    return isinstance(tests[0], dict)


def _definition_timeout(definition: dict) -> int | None:
    """tests[0].timeout_s, or None when the definition carries none.

    None means "take TEST_TIMEOUTS for the test", the same default a locally
    listed job gets from JobSpec.
    """
    first = (definition.get("tests") or [{}])[0]
    timeout = first.get("timeout_s")
    return timeout if isinstance(timeout, int) and timeout > 0 else None


class Job:
    """One test to run on one build."""

    def __init__(self, build_id: str, test: str, *,
                 timeout_s: int | None = None,
                 artifacts: Mapping[str, str] | None = None,
                 callback: Mapping[str, str] | None = None,
                 origin: str = ORIGIN_API, notes: str = "",
                 build: Build | None = None) -> None:
        # Mapping, not dict: this layer's public signatures name no bare dict.
        self.build_id: str = build_id
        self.test: str = test
        self.timeout_s: int = (
            timeout_s or _policy.POLICY.seconds_test_timeouts.get(
                test, DEFAULT_TIMEOUT))
        self.artifacts: dict[str, str] = dict(artifacts or {})
        self.callback: dict[str, str] | None = (
            dict(callback) if callback else None)
        self.origin: str = origin
        self.notes: str = notes
        self.build: Build | None = build
        # A pulled job keeps the definition the API served: run() passes it
        # through untouched (the resident worker does the same), instead of
        # re-rendering through jobspec - that would drop keys (integrity),
        # rewrites tests[0].id and injects our own rootfs, i.e. runs something
        # the pipeline did not ask for.
        self._served: dict | None = None

    def missing(self) -> list[str]:
        """Artifacts this test needs and this job does not have.

        With a Build the answer is the build's (kcilib.table.build owns the
        per-test requirement); without one it is read off the artifacts the job
        itself carries.
        """
        if self.build is not None:
            return list(self.build.missing_for(self.test))
        missing: list[str] = []
        if not self.artifacts.get("kernel"):
            missing.append("kernel")
        if self.test.startswith("kselftest"):
            if not (self.artifacts.get("kselftest")
                    or self.artifacts.get("kselftest_tar_xz")):
                missing.append("kselftest_tar_xz")
            if (self.test == "kselftest-kvm"
                    and not self.artifacts.get("modules")):
                missing.append("modules")
        return missing

    def run(self, *, config: _config.RunConfig | None = None,
            delivery: str = DELIVERY_IN_CONTAINER,
            source: str = SOURCE_TABLE,
            node_id: str | None = None,
            serve_port: int | None = None,
            gateway: str | None = None,
            out_dir: str | None = None,
            record_fields: Mapping[str, object] | None = None,
            **overrides: object) -> Outcome:
        """Run this job once and report what came back.

        The run itself is kcilib.run.jobrun.run_node: this assembles the
        RunConfig (from *config*, or from the overrides), hands it the
        definition and reads the verdict back out of the report body.  Posting
        the result is the sink's job, not this layer's.

        *delivery* is how the artifacts reach the guest - in_container (the
        default: the URLs go to tuxrun and its container downloads them) or
        local_server (they are downloaded and proved here first, then served
        to the container over HTTP; see _run_served).  *source* is the ledger
        "source" column, written verbatim, and *node_id* the name this run's
        console is archived under and the id run_node labels its lines with
        (the build id unless the caller names another one).  serve_port,
        gateway, out_dir and record_fields belong to local_server; in_container
        ignores them.

        Nothing here decides a process status: an Outcome is what the entry
        point turns into one.
        """
        mode = _delivery_of(delivery)
        run_config = _run_config_for(config, overrides)
        named = node_id or self.build_id
        definition = self.definition()
        if mode == DELIVERY_LOCAL_SERVER:
            return self._run_served(definition, run_config, source, named,
                                    serve_port, gateway, out_dir,
                                    record_fields)
        url, token, body = _jobrun.run_node(
            definition, run_config, named, source=source)
        return self._outcome(
            body, url, token, log=_existing(self._log_path(run_config, named)),
            record=self._record_path(definition, named))

    def _run_served(self, definition: dict, run_config: _config.RunConfig,
                    source: str, node_id: str, serve_port: int | None,
                    gateway: str | None, out_dir: str | None,
                    record_fields: Mapping[str, object] | None = None,
                    ) -> Outcome:
        """Run once with the artifacts served from this host (local_server).

        Everything but the run is kcilib.run.delivery's: the downloads and the
        size each one is proven against, the server that is shown to serve
        THIS build before tuxrun starts, and stopping it again.  The
        definition's URLs are the only thing rewritten - the run and the record
        run_node files for it stay its own, exactly as in in_container, so the
        two modes differ in one place.

        This is the one-shot line's mode, so it also carries that line's
        console and its judgement: the runner is reached through _fetch_console
        (nothing between tuxrun's stdout and stderr) and the command step is
        _oneshot_run_command ("running:", the caller's directory, the line's
        own timeout), while kcilib.run.judge judges the console the run
        archived - a one-shot run has no callback to post a body to, so its
        console is the evidence its verdict comes from.

        A server that cannot start is an "error" Outcome and not a traceback:
        kcilib.run.delivery raises ArtifactServerError because a resident
        caller exists, and turning a failure into a process status is an entry
        point's job, not this layer's (docs/REFACTOR-C-BRIEF.md §1.3).
        """
        out = self._out_dir(out_dir)
        os.makedirs(out, exist_ok=True)
        if not _artifacts_of(definition).get("kernel"):
            # No kernel URL means nothing to serve and no server worth
            # starting: run_node files the missing artifact itself, as an
            # infra report with a record.
            url, token, body = _jobrun.run_node(
                definition, run_config, node_id, source=source)
            return self._outcome(
                body, url, token,
                log=_existing(self._log_path(run_config, node_id)),
                record=self._record_path(definition, node_id),
                out_dir=out, source=source, record_fields=record_fields)
        port = serve_port or DEFAULT_SERVE_PORT
        base = f"http://{_gateway(gateway)}:{port}"
        # A one-shot run keeps its console beside what it downloaded, never in
        # the worker's archive (work/logs): the two lines keep different files
        # on purpose, and this is the path the ledger record names.
        run_config = _replace(run_config, log_dir=out)
        try:
            kernel = self._download(definition, out)
            server = _delivery.start_artifact_server(
                out, port,
                self._server_node(definition, node_id, record_fields), kernel)
        except _delivery.ArtifactServerError as error:
            return Outcome(VERDICT_ERROR, EXIT_ERROR, detail=str(error),
                           job=self)
        # Which kvm tests to run is read off the tarball this run already
        # downloaded, before run_node builds the argv (see _kvm_tests).
        run_config = self._kvm_tests(definition, run_config, out)
        served = _served(definition, base)
        captured: list = []
        try:
            # The console this line archives is the concatenation it always
            # was, run by the command step it always ran: both seams are put
            # back after the run, whatever the run did.
            real_runner = _jobrun.run_tuxrun
            real_command = _jobrun.run_command
            real_stamp = _jobrun.stamp
            _jobrun.run_tuxrun = _fetch_console
            _jobrun.run_command = _oneshot_run_command(captured)
            _jobrun.stamp = _quiet
            try:
                url, token, body = _jobrun.run_node(
                    served, run_config, node_id, source=source)
            finally:
                _jobrun.run_tuxrun = real_runner
                _jobrun.run_command = real_command
                _jobrun.stamp = real_stamp
        finally:
            _delivery.stop_artifact_server(server)
        console = _keep_console(self._log_path(run_config, node_id),
                                os.path.join(out, CONSOLE_NAME))
        judged, output = _judged(captured, self.test)
        return self._outcome(body, url, token, log=console,
                             record=self._record_path(served, node_id),
                             judged=judged, output=output, source=source,
                             out_dir=out, record_fields=record_fields)

    def _kvm_tests(self, definition: Mapping[str, object],
                   run_config: _config.RunConfig,
                   out: str) -> _config.RunConfig:
        """*run_config* with the kvm tests this build has, read off its tarball.

        A kselftest-kvm run excludes the tests the kernel never built by listing
        the kvm/ entries of the build's kselftest tarball (kcilib.run.artifacts
        and kcilib.core.params own both halves).  The one-shot line lists the
        tarball it already downloaded for this run; the run layer would
        otherwise download a second, cached copy of it
        (work/env/kselftest/<key>.tar.xz) and announce that transfer on a
        console that has never carried it.  --kvm-full is the whole collection
        and an explicit kvm_tests is the caller's own list: both are left
        alone, as is a run whose tarball is not on disk.
        """
        artifacts = _artifacts_of(definition)
        if (self.test != "kselftest-kvm" or run_config.kvm_full
                or run_config.kvm_tests or not artifacts.get("modules")):
            return run_config
        tarball = os.path.join(out, "kselftest.tar.xz")
        if not os.path.isfile(tarball):
            return run_config
        names = _params.kvm_tests_to_run(
            _artifacts.tarball_executables(tarball, subdir="kvm"))
        return _replace(run_config, kvm_tests=names) if names else run_config

    def _out_dir(self, out_dir: str | None) -> str:
        """Where a one-shot run keeps its artifacts, console and server log.

        The caller's directory when it named one (the one-shot line always
        does: it prints that path), else this build's own download directory.
        """
        return out_dir or os.path.join(_delivery.ROOT, "work", "downloads",
                                       self.build_id)

    def record(self, out_dir: str | None = None, *, verdict: str,
               exit_code: int, detail: str,
               results: Mapping[str, object] | None = None,
               source: str = SOURCE_TABLE,
               fields: Mapping[str, object] | None = None) -> str:
        """File this job's ledger record and return the path written.

        kcilib.core.ledger owns the record's key set and its layout; this fills
        the columns the run itself owns - the build and test identity, the
        source, the verdict, the console kept beside the artifacts
        (out_dir/tuxrun.log, the one-shot line's own console name) and the
        directory the artifacts were downloaded into - and takes the rest from
        *fields*, the columns only the caller's line can know: the kbuild it
        pulled, when that build was made, the revision it built.

        run_node files its own record for every run it makes, and that record
        stays (the table's and the worker's readers rely on it); a caller whose
        line names its records its own way re-files the run under those names,
        so the file on disk is that line's record.  An OSError from the write
        is the caller's to report, as it always was.
        """
        out = self._out_dir(out_dir)
        payload = dict(fields or {})
        payload.update({
            "source": source,
            "verdict": verdict,
            "exit_code": exit_code,
            "detail": detail,
            "results": results,
            "log": _repo_relative(os.path.join(out, CONSOLE_NAME)),
            "artifacts_dir": _repo_relative(out),
        })
        return _ledger.write_result(self.build_id, self.test, payload)

    def record_path(self) -> str:
        """Where this job's ledger record goes (kcilib.core.ledger's rule).

        The path is the one a record is written to and read back from whether
        or not the write succeeded, so a caller can name the record it could
        not file.
        """
        return _ledger.result_path(self.build_id, self.test)

    def _download(self, definition: Mapping[str, object], out: str) -> str:
        """Download this run's artifacts into *out*; returns the kernel path.

        The transfers are kcilib.run.delivery's, record kept included: the
        size a previous run recorded is what proves a cached file complete,
        and anything unproven is downloaded again, because a truncated Image
        boots as garbage while the stage "succeeds" (#13).  The names are the
        ones the definition is rewritten to and the server hands out.
        """
        artifacts = _artifacts_of(definition)
        record = _delivery.load_artifact_record(out)
        kernel = os.path.join(out, "Image")
        _delivery.ensure_kernel_image(artifacts["kernel"], kernel + ".gz",
                                      kernel, record)
        kselftest = (artifacts.get("kselftest")
                     or artifacts.get("kselftest_tar_xz"))
        if kselftest:
            _delivery.ensure_artifact(
                kselftest, os.path.join(out, "kselftest.tar.xz"), record,
                "kselftest.tar.xz", "kselftest")
        # Only the kvm collection needs modules.tar.xz - kcilib.run.jobrun
        # passes --modules for that test alone.
        if self.test == "kselftest-kvm" and artifacts.get("modules"):
            _delivery.ensure_artifact(
                artifacts["modules"], os.path.join(out, "modules.tar.xz"),
                record, "modules.tar.xz", "modules")
        if artifacts.get("_config"):
            _delivery.ensure_artifact(
                artifacts["_config"], os.path.join(out, ".config"), record,
                ".config", "kernel config")
        _delivery.save_artifact_record(out, record)
        return kernel

    def _server_node(self, definition: Mapping[str, object],
                     node_id: str,
                     record_fields: Mapping[str, object] | None = None) -> dict:
        """The node the artifact server records in its build-id.json.

        kcilib.run.delivery verifies one field of it - the id it serves
        against the one it was asked for; the name and the creation time are
        the operator's evidence.  A pulled definition carries a name of its
        own; a caller that names its records passes the same two facts there
        (the kbuild it pulled and when that build was made), and its
        build-id.json has always recorded those.
        """
        build = self.build
        fields = record_fields or {}
        name = fields.get("job") or definition.get("name")
        created = fields.get("build_created")
        return {
            "id": node_id,
            "name": name if isinstance(name, str) else "",
            "created": created if created is not None else (
                build.created if build is not None else None),
        }

    def _outcome(self, body: dict, url: str | None, token: str | None, *,
                 log: str | None, record: str | None,
                 judged: tuple | None = None, output: str | None = None,
                 source: str = SOURCE_TABLE, out_dir: str | None = None,
                 record_fields: Mapping[str, object] | None = None) -> Outcome:
        """The Outcome for one run_node report body.

        The verdict is read out of the body kcilib.run.jobrun built, never
        recomputed from the console here: the record, the pipeline and this
        object are then one verdict instead of three opinions.  *judged* is
        the one-shot line's exception to that, and its reason: a served run
        posts no report, so verdict, detail and TAP come from
        kcilib.run.judge over the console the run archived (see _judged).

        *record_fields* re-files the record under the caller's line's own
        names, when it has any (see record()).
        """
        summary = per_test = None
        if judged is None:
            verdict, exit_code, detail = _callback.verdict_from_body(body)
        else:
            verdict, exit_code, detail, summary, per_test = judged
        if record_fields is not None:
            record = self.record(out_dir, verdict=verdict, exit_code=exit_code,
                                 detail=detail, results=summary,
                                 source=source, fields=record_fields)
        status = body.get("status")
        return Outcome(
            verdict, exit_code,
            detail=detail,
            status=status if isinstance(status, int) else None,
            log=log,
            record=record,
            report=(url, token, body),
            job=self,
            summary=summary,
            per_test=per_test,
            output=output,
        )

    def _record_path(self, definition: Mapping[str, object],
                     node_id: str) -> str | None:
        """The ledger record run_node filed for this run, when there is one.

        The build is kcilib.run.jobrun.record_result's own rule - the build the
        artifacts name, else the node id it was handed, else this job's build -
        so the Outcome points at the record that was written rather than at the
        one this layer would have named.
        """
        build_id = (_artifacts.build_id_from_artifacts(_artifacts_of(definition))
                    or node_id or self.build_id)
        return _existing(_ledger.result_path(build_id, self.test))

    def definition(self) -> dict:
        """The definition handed to run_node, shaped exactly like upstream's.

        Field names are the ones kernelci-pipeline's pull_labs.jinja2 renders, so
        run_node cannot tell (and must not care) whether a definition came from
        the API or was built here; the only difference is whether it carries a
        callback URL, and that is what makes "run one of my own jobs" and "run
        one the pipeline dispatched" the same thing at the execution layer.

        A pulled job returns the definition the API served, verbatim: it is what
        the pipeline asked this lab to run, and re-rendering it would drop keys
        and inject our own rootfs.
        """
        if self._served is not None:
            return self._served
        callback = self.callback or {}
        artifacts = dict(self.artifacts, rootfs=_policy.POLICY.rootfs_url)
        # The executor reads "kselftest", but the index stores the API's raw key
        # "kselftest_tar_xz" - the same rename the production template does.
        artifacts["kselftest"] = (
            artifacts.get("kselftest") or artifacts.get("kselftest_tar_xz") or "")
        definition = {
            "artifacts": artifacts,
            "tests": [{
                "id": self.test,
                "type": self.test,
                "depends": [],
                "timeout_s": self.timeout_s,
                "pre-commands": [],
                "post-commands": [],
            }],
            "environment": {
                "platform": _policy.POLICY.platform,
                "arch": _policy.POLICY.arch,
                "console": {"method": "serial", "baud": 115200},
            },
        }
        if callback.get("url"):
            definition["callback"] = {
                "url": callback["url"],
                "token_name": callback.get("token_name")
                or "kernelci-pipeline-callback",
            }
        return definition

    def _log_path(self, run_config: _config.RunConfig,
                  node_id: str | None = None) -> str | None:
        """Where run_node archives this job's console, when it archives one.

        The name is run_node's own rule (jobrun.archive_console_log): the node
        id it was handed - the build id unless the caller named another one -
        and never this layer's build id regardless, or the path would name a
        file nobody wrote.
        """
        if not run_config.log_dir:
            return None
        return os.path.join(run_config.log_dir,
                            f"{node_id or self.build_id}.log")

    def __str__(self) -> str:
        return f"{self.build_id} {self.test}"

    def __repr__(self) -> str:
        return f"<Job {self}>"


def jobs_for(build: Build, tests=None, timeout_s=None):
    """One build -> (its jobs, the tests it cannot support).

    The one implementation of "which tests does this build run": it used to
    exist twice, as table.jobspec.jobs_from_build (returning JobSpecs) and as
    Kbuild.to_jobs (returning Jobs), and callers of the first had to convert its
    rows into the second's cards before anything could run.  A test whose
    artifacts are missing is reported with its reason, never dropped silently.
    """
    names = tuple(tests) if tests else _policy.DEFAULT_TESTS
    jobs, skipped = [], []
    for test in names:
        missing = build.missing_for(test)
        if missing:
            skipped.append((test, f"missing artifact(s): {', '.join(missing)}"))
            continue
        jobs.append(Job(build.build_id, test, timeout_s=timeout_s,
                        artifacts=dict(build.artifacts),
                        origin=build.origin, notes=build.notes, build=build))
    return Jobs(jobs), skipped


class Jobs:
    """The middle job layer: a collection of Job."""

    def __init__(
            self, source: Builds | Build | JobPuller | Sequence[Job] | None
            = None,
            *, tests: Sequence[str] | None = None) -> None:
        self.jobs: list[Job] = []
        if source is None:
            return
        if isinstance(source, Builds):
            self._from_builds(source, tests)
        elif isinstance(source, Build):
            # One card is a collection of one: Jobs(card, tests=[...]) is the
            # common case and reads better than wrapping it first.
            one = Builds()
            one.add(source)
            self._from_builds(one, tests)
        elif isinstance(source, JobPuller):
            self._from_puller(source)
        else:
            self.jobs.extend(source)

    def run(self, **overrides: object) -> list[Outcome]:
        """Run every job, one at a time, and collect the outcomes.

        One job failing does not stop the batch: a run that blows up outside
        run_node becomes an "error" Outcome, so the rest still get to run.

        The run-level arguments (RUN_ARGUMENTS: config, delivery, source,
        node_id, serve_port, gateway, out_dir) reach every job unchanged; every
        other name is a RunConfig override, and one that is neither is refused
        before the first job starts.
        """
        arguments = {name: value for name, value in overrides.items()
                     if name in RUN_ARGUMENTS}
        configured = {name: value for name, value in overrides.items()
                      if name not in RUN_ARGUMENTS}
        _run_config(configured)  # refuse a typo before the first job starts
        outcomes: list[Outcome] = []
        for job in self.jobs:
            try:
                outcomes.append(job.run(**arguments, **configured))
            except Exception as error:  # noqa: BLE001 - the batch continues
                print(f"Warning: {job} could not be run ({error})")
                outcomes.append(Outcome(VERDICT_ERROR, EXIT_ERROR,
                                        detail=str(error), job=job))
        return outcomes

    def _from_builds(self, builds: Builds,
                     tests: Sequence[str] | None) -> None:
        """Every card x every test that card has the artifacts for."""
        wanted = tuple(tests) if tests else _policy.DEFAULT_TESTS
        for build in builds:
            for test in wanted:
                missing = build.missing_for(test)
                if missing:
                    print(f"Warning: skipping {build.build_id} {test}: "
                          f"missing artifact(s): {', '.join(missing)}")
                    continue
                self.jobs.append(Job(
                    build.build_id, test,
                    artifacts=dict(build.artifacts),
                    origin=build.origin,
                    build=build,
                ))

    def _from_puller(self, puller: JobPuller) -> None:
        """Every job node of *puller*, read through its own definition."""
        for node in puller:
            job = self._job_from_node(puller, node, origin_for(puller.api_url))
            if job is not None:
                self.jobs.append(job)

    def _job_from_node(self, puller: JobPuller, node: KernelCINode,
                       origin: str) -> Job | None:
        """One job node -> a Job, or None when its definition is malformed.

        A malformed definition is skipped with a line saying so: it cannot be
        run, and the rest of the batch must not be lost to it.  Fetching the
        definition itself is not guarded - a transfer failure there is
        transient and belongs to the caller's retry.
        """
        definition = puller.definition(node)
        if not _is_definition(definition):
            print(f"Warning: skipping job node {node.node_id}: malformed job "
                  "definition")
            return None
        artifacts = definition.get("artifacts")
        artifacts = dict(artifacts) if isinstance(artifacts, dict) else {}
        callback = definition.get("callback")
        callback = dict(callback) if isinstance(callback, dict) else None
        build_id = _artifacts.build_id_from_artifacts(artifacts)
        job = Job(
            build_id, _ledger.test_of(definition),
            timeout_s=_definition_timeout(definition),
            artifacts=artifacts,
            callback=callback,
            origin=origin,
            build=Build(build_id, artifacts, origin=origin) if build_id
            else None,
        )
        # Keep the served definition: run() must run what the API asked for,
        # not a re-render of it (see Job._served).
        job._served = definition
        return job

    def __iter__(self) -> Iterator[Job]:
        return iter(self.jobs)

    def __len__(self) -> int:
        return len(self.jobs)

    def __getitem__(self, index: int) -> Job:
        return self.jobs[index]

    def __repr__(self) -> str:
        return f"<Jobs {len(self.jobs)} job(s)>"


class Outcome:
    """What one run produced: a verdict and where its evidence is."""

    def __init__(self, verdict: str, exit_code: int, *, detail: str = "",
                 status: int | None = None, log: str | None = None,
                 record: str | None = None, report: tuple | None = None,
                 job: Job | None = None,
                 summary: Mapping[str, object] | None = None,
                 per_test: Mapping[str, object] | None = None,
                 output: str | None = None) -> None:
        # verdict: pass/fail/infra/error; exit_code: 0/1/3; report is the
        # (callback_url, token, body) tuple run_node returned.  summary,
        # per_test and output are kcilib.run.judge's reading of the console a
        # served run judged, and None for a run that was read from its body.
        self._verdict: str = verdict
        self._exit_code: int = exit_code
        self._detail: str = detail
        self._status: int | None = status
        self._log: str | None = log
        self._record: str | None = record
        self._report: tuple | None = report
        self._job: Job | None = job
        self._summary: Mapping[str, object] | None = summary
        self._per_test: Mapping[str, object] | None = per_test
        self._output: str | None = output

    @property
    def verdict(self) -> str:
        return self._verdict

    @property
    def exit_code(self) -> int:
        return self._exit_code

    @property
    def detail(self) -> str:
        return self._detail

    @property
    def status(self) -> int | None:
        return self._status

    @property
    def log(self) -> str | None:
        return self._log

    @property
    def record(self) -> str | None:
        return self._record

    @property
    def report(self) -> tuple | None:
        return self._report

    @property
    def job(self) -> Job | None:
        return self._job

    @property
    def summary(self) -> Mapping[str, object] | None:
        """The TAP counts of this run's console (None: no TAP, or no console).

        A served run judges its own console, so the counts, the per-test
        results and the console text are all kcilib.run.judge's - the one-shot
        line prints its TAP summary from these instead of reading the console a
        second time.
        """
        return self._summary

    @property
    def per_test(self) -> Mapping[str, object] | None:
        """The per-test TAP results ({} when the console carried no TAP)."""
        return self._per_test

    @property
    def output(self) -> str | None:
        """The merged console this run produced, or None when it left none."""
        return self._output

    @property
    def started(self) -> bool:
        """True when the run reached the executor and produced a report.

        A local_server run whose artifact server refused to start is the one
        Outcome that is a failure OF the run instead of a result from it:
        there is no report, so no verdict can be read out of one.
        """
        return self._report is not None

    def is_pass(self) -> bool:
        """True only for a passing run; an infra error is not a failure."""
        return self._verdict == VERDICT_PASS

    def logs(self, lines: int = 20) -> list[str]:
        """The last *lines* lines of the archived console ([] when none)."""
        if not self._log or lines <= 0:
            return []
        try:
            with open(self._log, encoding="utf-8",
                      errors="replace") as handle:
                return [line.rstrip("\n")
                        for line in handle.readlines()[-lines:]]
        except OSError:
            return []

    def _fields(self) -> dict[str, object]:
        """The fields the dict-shaped readers see, by their old key names.

        The table line's run result was a dict with exactly these keys before
        this layer existed (that shell, kcilib.table.localrun.run_job, is gone
        now), so the callers that still read a run that way (local-jobs.py's
        loop, kcilib.sink's ledger sink) keep working.
        ``log`` is deliberately NOT one of them: the old dict had no such key,
        and a reader testing ``"log" in outcome`` must not enter a branch that
        never existed.  ``.log`` is still an attribute.
        """
        return {
            "verdict": self._verdict,
            "exit_code": self._exit_code,
            "detail": self._detail,
            "status": self._status,
            "record": self._record,
            "report": self._report,
            "callback_url": self._report[0] if self._report else None,
        }

    def __getitem__(self, key: str) -> object:
        """Dict-style read of a report field, for the older callers."""
        return self._fields()[key]

    def get(self, key: str, default: object = None) -> object:
        """Dict-style get(): outcome.get("record") reads as it always did."""
        return self._fields().get(key, default)

    def __contains__(self, key: object) -> bool:
        """True for the keys the old dict carried (never for anything else)."""
        return key in self._fields()

    def __repr__(self) -> str:
        """Names no report: the tuple carries the callback token."""
        return f"<Outcome verdict={self._verdict} exit_code={self._exit_code}>"
