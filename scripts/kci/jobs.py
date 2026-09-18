# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The middle job layer: one test on one build, and the outcome it produced.

Job is the intent (build, test, timeout) plus the definition its executor gets;
Outcome is what one run produced; Jobs is the collection that runs them one
after another.  The definition shape comes from kcilib.table.jobspec and the
run from kcilib.run.jobrun, so this layer adds no definition of its own.

How a run's artifacts reach the guest is kcilib.run.delivery's two modes:
in_container (the default - run_node hands tuxrun the URLs and the container
downloads them) and local_server (this layer downloads and proves them first,
then serves them to the container over HTTP).  Which mode a run used, and
which ledger source its record is filed under, are run() arguments, so the
worker's line, the table's and the one-shot fetch line are one call with three
answers.
"""

from __future__ import annotations

import os
import shutil
import socket
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace as _replace

from kcilib.core import config as _config
from kcilib.core import ledger as _ledger
from kcilib.run import artifacts as _artifacts
from kcilib.run import callback as _callback
from kcilib.run import delivery as _delivery
from kcilib.run import jobrun as _jobrun
from kcilib.run import runner as _runner
from kcilib.table import buildref as _buildref
from kcilib.table import jobspec as _jobspec

from .builds import Kbuild, Kbuilds
from .nodes import (
    ORIGIN_API,
    ORIGIN_API_LOCAL,
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
    "out_dir",
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

# Timeout for a test kcilib.table.jobspec.TEST_TIMEOUTS does not name.
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
    """The BuildRef *source* column for a Job's origin."""
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
                 build: Kbuild | None = None) -> None:
        # Mapping, not dict: this layer's public signatures name no bare dict.
        self.build_id: str = build_id
        self.test: str = test
        self.timeout_s: int = (
            timeout_s or _jobspec.TEST_TIMEOUTS.get(test, DEFAULT_TIMEOUT))
        self.artifacts: dict[str, str] = dict(artifacts or {})
        self.callback: dict[str, str] | None = (
            dict(callback) if callback else None)
        self.origin: str = origin
        self.notes: str = notes
        self.build: Kbuild | None = build
        # A pulled job keeps the definition the API served: run() passes it
        # through untouched (the resident worker does the same), instead of
        # re-rendering through jobspec - that would drop keys (integrity),
        # rewrites tests[0].id and injects our own rootfs, i.e. runs something
        # the pipeline did not ask for.
        self._served: dict | None = None

    def missing(self) -> list[str]:
        """Artifacts this test needs and this job does not have.

        With a Kbuild card the answer is the card's (kcilib.table.buildref owns
        the per-test requirement); without one it is read off the artifacts the
        job itself carries.
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
        gateway and out_dir belong to local_server; in_container ignores them.

        Nothing here decides a process status: an Outcome is what the entry
        point turns into one.
        """
        mode = _delivery_of(delivery)
        run_config = _run_config_for(config, overrides)
        named = node_id or self.build_id
        definition = self._definition()
        if mode == DELIVERY_LOCAL_SERVER:
            return self._run_served(definition, run_config, source, named,
                                    serve_port, gateway, out_dir)
        url, token, body = _jobrun.run_node(
            definition, run_config, named, source=source)
        return self._outcome(
            body, url, token, log=_existing(self._log_path(run_config, named)),
            record=self._record_path(definition, named))

    def _run_served(self, definition: dict, run_config: _config.RunConfig,
                    source: str, node_id: str, serve_port: int | None,
                    gateway: str | None, out_dir: str | None) -> Outcome:
        """Run once with the artifacts served from this host (local_server).

        Everything but the run is kcilib.run.delivery's: the downloads and the
        size each one is proven against, the server that is shown to serve
        THIS build before tuxrun starts, and stopping it again.  The
        definition's URLs are the only thing rewritten - the run, the verdict
        and the ledger record stay run_node's, exactly as in in_container, so
        the two modes differ in one place.

        A server that cannot start is an "error" Outcome and not a traceback:
        kcilib.run.delivery raises ArtifactServerError because a resident
        caller exists, and turning a failure into a process status is an entry
        point's job, not this layer's (docs/REFACTOR-C-BRIEF.md §1.3).
        """
        out = out_dir or os.path.join(_delivery.ROOT, "work", "downloads",
                                      self.build_id)
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
                record=self._record_path(definition, node_id))
        port = serve_port or DEFAULT_SERVE_PORT
        base = f"http://{_gateway(gateway)}:{port}"
        # A one-shot run keeps its console beside what it downloaded, never in
        # the worker's archive (work/logs): the two lines keep different files
        # on purpose, and this is the path the ledger record names.
        run_config = _replace(run_config, log_dir=out)
        try:
            kernel = self._download(definition, out)
            server = _delivery.start_artifact_server(
                out, port, self._server_node(definition, node_id), kernel)
        except _delivery.ArtifactServerError as error:
            return Outcome(VERDICT_ERROR, EXIT_ERROR, detail=str(error),
                           job=self)
        served = _served(definition, base)
        try:
            # The console this line archives is the concatenation it always
            # was, not the worker's newline-joined one (see _fetch_console).
            real_runner = _jobrun.run_tuxrun
            _jobrun.run_tuxrun = _fetch_console
            try:
                url, token, body = _jobrun.run_node(
                    served, run_config, node_id, source=source)
            finally:
                _jobrun.run_tuxrun = real_runner
        finally:
            _delivery.stop_artifact_server(server)
        console = _keep_console(self._log_path(run_config, node_id),
                                os.path.join(out, CONSOLE_NAME))
        return self._outcome(body, url, token, log=console,
                             record=self._record_path(served, node_id))

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
                     node_id: str) -> dict:
        """The node the artifact server records in its build-id.json.

        kcilib.run.delivery verifies one field of it - the id it serves
        against the one it was asked for; the name and the creation time are
        the operator's evidence, and this layer's build card is where they
        live (a definition carries a name only when the pipeline rendered
        one).
        """
        build = self.build
        name = definition.get("name")
        return {
            "id": node_id,
            "name": name if isinstance(name, str) else "",
            "created": build.created if build is not None else None,
        }

    def _outcome(self, body: dict, url: str | None, token: str | None, *,
                 log: str | None, record: str | None) -> Outcome:
        """The Outcome for one run_node report body.

        The verdict is read out of the body kcilib.run.jobrun built, never
        recomputed from the console here: the record, the pipeline and this
        object are then one verdict instead of three opinions.
        """
        verdict, exit_code, detail = _callback.verdict_from_body(body)
        status = body.get("status")
        return Outcome(
            verdict, exit_code,
            detail=detail,
            status=status if isinstance(status, int) else None,
            log=log,
            record=record,
            report=(url, token, body),
            job=self,
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

    def _definition(self) -> dict:
        """The definition handed to run_node, shaped exactly like the table's.

        A locally listed job is built through kcilib.table.jobspec so this
        layer cannot drift from the definition the local job table renders for
        the same input.  A pulled job returns the definition the API served,
        verbatim: it is what the pipeline asked this lab to run.
        """
        if self._served is not None:
            return self._served
        build = self.build
        ref = _buildref.BuildRef(
            build_id=self.build_id,
            artifacts=self.artifacts,
            tree=build.tree if build is not None else None,
            branch=build.branch if build is not None else None,
            commit=build.commit if build is not None else None,
            describe=build.describe if build is not None else None,
            created=build.created if build is not None else None,
            node_id=build.node_id if build is not None else None,
            source=_source_for(self.origin),
        )
        spec = _jobspec.JobSpec(self.build_id, self.test, self.timeout_s,
                                build=ref)
        callback = self.callback or {}
        return _jobspec.job_definition(
            spec,
            callback_url=callback.get("url"),
            token_name=callback.get("token_name"),
        )

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


class Jobs:
    """The middle job layer: a collection of Job."""

    def __init__(
            self, source: Kbuilds | Kbuild | JobPuller | Sequence[Job] | None
            = None,
            *, tests: Sequence[str] | None = None) -> None:
        self.jobs: list[Job] = []
        if source is None:
            return
        if isinstance(source, Kbuilds):
            self._from_kbuild(source, tests)
        elif isinstance(source, Kbuild):
            # One card is a collection of one: Jobs(card, tests=[...]) is the
            # common case and reads better than wrapping it first.
            one = Kbuilds()
            one.add(source)
            self._from_kbuild(one, tests)
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

    def _from_kbuild(self, kbuild: Kbuilds,
                     tests: Sequence[str] | None) -> None:
        """Every card x every test that card has the artifacts for."""
        wanted = tuple(tests) if tests else _jobspec.DEFAULT_TESTS
        for build in kbuild:
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
            build_id, _jobspec.test_of(definition),
            timeout_s=_definition_timeout(definition),
            artifacts=artifacts,
            callback=callback,
            origin=origin,
            build=Kbuild(build_id, artifacts, origin=origin) if build_id
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
                 job: Job | None = None) -> None:
        # verdict: pass/fail/infra/error; exit_code: 0/1/3; report is the
        # (callback_url, token, body) tuple run_node returned.
        self._verdict: str = verdict
        self._exit_code: int = exit_code
        self._detail: str = detail
        self._status: int | None = status
        self._log: str | None = log
        self._record: str | None = record
        self._report: tuple | None = report
        self._job: Job | None = job

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
