"""The interface layer (kci), and the table line that runs through it.

Two things this suite did not cover before, both of which the 2026-09-18 wiring
made load-bearing:

* kci's Outcome is read by older callers through the dict protocol the run
  result used to be (local-jobs.py's loop, kcilib.sink's ledger sink), so that
  contract is pinned here - including that the key set is EXACTLY the old one,
  because a reader testing ``"log" in outcome`` would otherwise enter a branch
  that never existed.
* the run of a table row goes through kci.Job.run, which must send the very
  definition kcilib.table.jobspec renders for that row - the object layer is
  not allowed to grow a second idea of what a row is.

Added for the one-shot fetch line's move onto the same call: run()'s two
deliveries (kcilib.run.delivery's in_container and local_server) and the ledger
"source" every entry point files its records under.  The local_server cases are
driven with that module's own functions recorded, never with a copy of it, so a
future divergence in delivery.py is a failure here and not a silently different
run.
"""
import json
import os
import tempfile

import kci.jobs as kci_jobs
from kci import (
    DELIVERY_IN_CONTAINER,
    DELIVERY_LOCAL_SERVER,
    ORIGIN_API,
    SOURCE_FETCH,
    Job,
    Jobs,
    Kbuild,
    Kbuilds,
    Outcome,
)
from kcilib.core import ledger
from kcilib.table import buildref, jobspec

from .support import check

# The keys kcilib.table.localrun.run_job returned before the object layer.
OLD_KEYS = ("verdict", "exit_code", "detail", "status", "record", "report",
            "callback_url")


def _row():
    """A table row: one BuildRef plus the one test it can support."""
    ref = buildref.BuildRef(
        build_id="6aa3689720239ade90209d50",
        artifacts={"kernel": "https://files.kernelci.org/x/Image.gz",
                   "kselftest_tar_xz": "https://files.kernelci.org/x/ks.tar.xz",
                   "modules": "https://files.kernelci.org/x/modules.tar.xz"},
        tree="net-next", branch="main", commit="348ea4642f56ab3d" * 2,
        describe="v7.3-rc2-655-g348ea4642f56a",
        created="2026-09-11T02:33:59.007000", node_id="6aa3689720239ade90209d50",
        source="official")
    specs, _skipped = jobspec.jobs_from_build(ref, tests=["boot"])
    return specs[0]


def _container(ref):
    """One BuildRef from the table -> a Kbuilds holding one card."""
    card = Kbuilds()
    card.add(Kbuild(ref.build_id, ref.artifacts, tree=ref.tree,
                   branch=ref.branch, commit=ref.commit, describe=ref.describe,
                   created=ref.created, node_id=ref.node_id,
                   origin=ORIGIN_API))
    return card


def _card(ref):
    """The single Kbuild card for one table row."""
    return _container(ref).builds[0]


def test_outcome_is_dict_shaped_for_old_readers():
    """Outcome answers the reads the old run-result dict answered, and no more.

    The wiring replaced a 7-key dict with this object, so the two readers that
    never changed - local-jobs.py's loop and sink.LedgerSink.deliver - must keep
    working: ``outcome["verdict"]``, ``outcome.get("record")`` and ``or {}``
    fallbacks.  The key set is asserted EXACTLY: a key the old dict did not have
    (``log``) would make ``"log" in outcome`` true and send a reader down a
    branch that never existed.
    """
    outcome = Outcome("pass", 0, detail="", status=2, log="/tmp/x.log",
                      record="/tmp/record.json",
                      report=("http://cb", "tok", {"status": 2}))
    for key in OLD_KEYS:
        check(key in outcome, f"{key} is not in the outcome's key set")
    check(set(outcome._fields()) == set(OLD_KEYS),
          f"the key set changed: {sorted(outcome._fields())} != "
          f"{sorted(OLD_KEYS)}")
    check("log" not in outcome,
          "log is not a key of the old dict and must not be one now")
    check(outcome["verdict"] == "pass" and outcome["callback_url"] == "http://cb",
          (outcome["verdict"], outcome["callback_url"]))
    check(outcome.get("record") == "/tmp/record.json"
          and outcome.get("nope", "D") == "D",
          "get() no longer reads like the dict's")
    check(outcome["status"] == 2 and outcome["report"][1] == "tok",
          "status/report did not survive the dict-shaped read")
    try:
        outcome["nope"]
        check(False, "an unknown key must raise KeyError, as a dict does")
    except KeyError:
        pass
    # The two reads the wiring actually depends on.
    check((outcome or {}).get("record") == "/tmp/record.json",
          "sink.LedgerSink.deliver's (outcome or {}).get('record') broke")
    check((None or {}).get("record") is None, "the or-{} fallback broke")
    check(outcome.is_pass() and not outcome.logs(),
          "is_pass()/logs() regressed on an outcome with no readable log")
    print("test_outcome_is_dict_shaped_for_old_readers OK")


def test_job_run_matches_the_table_line():
    """A row's run must be the table line's own run, down to the definition.

    This guard used to compare two ways to run one row: kci.Job.run and
    kcilib.table.localrun.run_job, the old shell over run_node that no
    production caller used any more (removed 2026-09-18, with the move of the
    object layer to kci/).  What it was comparing for is what is pinned here,
    and it is pinned harder: Job.run() must reach
    kcilib.run.jobrun.run_node with the byte-identical definition
    kcilib.table.jobspec renders for that same row, with the row's build id as
    the node id and with the table's ledger source - so ./run.sh run cannot
    drift from the table line.  run_node itself is not called: the run is
    checked at the call boundary.
    """
    spec = _row()
    ref = spec.build
    build = _card(ref)
    job = Job(build.build_id, spec.test, timeout_s=spec.timeout_s,
              artifacts=dict(build.artifacts), build=build)

    rendered = json.dumps(jobspec.job_definition(spec), sort_keys=True)
    check(json.dumps(job._definition(), sort_keys=True) == rendered,
          "Job._definition() drifted from the table line's job_definition()")

    seen = []

    def fake_run_node(definition, run_config, node_id=None, source=None):
        seen.append((json.dumps(definition, sort_keys=True), node_id, source))
        return "http://cb", "tok", {"status": 2, "results": {}}

    import kci.jobs as kci_jobs
    real_run_node = kci_jobs._jobrun.run_node
    kci_jobs._jobrun.run_node = fake_run_node
    try:
        outcome = job.run()
    finally:
        kci_jobs._jobrun.run_node = real_run_node
    check(len(seen) == 1, f"one row is one run_node call: {seen}")
    check(seen[0][0] == rendered,
          "Job.run() sent a definition the table line's renderer did not "
          "produce")
    check(seen[0][1] == build.build_id,
          f"the node id is not the row's build id: {seen[0][1]}")
    check(seen[0][2] == "table",
          f"the ledger source is not the table's: {seen[0][2]}")
    check(outcome["verdict"] == "pass" and outcome.is_pass(),
          f"the run did not come back as a pass: {outcome['verdict']}")
    check(outcome["callback_url"] == "http://cb"
          and outcome["report"][1] == "tok",
          "the report triple did not survive the run")
    print("test_job_run_matches_the_table_line OK")


def test_jobs_runs_a_row_and_records_it():
    """Jobs runs what a row asks for, once, and files the run in the ledger.

    Driven through the object layer with run_node replaced: the point is the
    wiring (one job, the row's test, the table ledger source) and the outcome
    the entry point prints, not tuxrun.
    """
    spec = _row()
    jobs = Jobs(_container(spec.build), tests=["boot"])
    check(len(jobs) == 1 and jobs[0].test == "boot", list(jobs))
    check(jobs[0].missing() == [], jobs[0].missing())

    with tempfile.TemporaryDirectory() as tmp:
        real_env = os.environ.get(ledger.RESULTS_DIR_ENV)
        os.environ[ledger.RESULTS_DIR_ENV] = os.path.join(tmp, "results")
        import kci.jobs as kci_jobs
        real_run = kci_jobs._jobrun.run_node
        calls = []

        def fake_run_node(definition, run_config, node_id=None, source=None):
            calls.append((node_id, source))
            ledger.write_result(
                node_id, jobspec.test_of(definition),
                {"verdict": "pass", "exit_code": 0, "source": source})
            return None, None, {"status": 2, "results": {}}

        kci_jobs._jobrun.run_node = fake_run_node
        try:
            outcomes = jobs.run()
        finally:
            kci_jobs._jobrun.run_node = real_run
            if real_env is None:
                os.environ.pop(ledger.RESULTS_DIR_ENV, None)
            else:
                os.environ[ledger.RESULTS_DIR_ENV] = real_env
        check(len(calls) == 1 and calls[0][1] == "table",
              f"Jobs.run did not run one table row: {calls}")
        check(len(outcomes) == 1 and outcomes[0].is_pass(),
              [o.verdict for o in outcomes])
        check(outcomes[0].record is not None,
              "the outcome lost the ledger record path")
        check(not outcomes[0].report[:1][0],
              "a row without a callback must carry no callback URL")
    print("test_jobs_runs_a_row_and_records_it OK")


def test_job_run_refuses_an_unknown_delivery_and_files_its_source():
    """run() takes kcilib.run.delivery's two modes, and the ledger is told who
    filed the record.

    Two claims, both of which the fetch line's move onto Job.run rests on:

    * an unknown delivery is refused, with BOTH legal names in the message.  A
      mangled spelling ("in-container") is the mistake this catches, and the
      reader has the right one in front of them when it fires.
    * *source* travels verbatim into the record, including "fetch", which
      kcilib.run.jobrun does not name.  The ledger's "source" column is how a
      reader tells a re-run from a table row from a worker job
      (docs/ARCHITECTURE.md), so it may not be defaulted or rewritten on the
      way.  Pinned through the REAL writer (jobrun.record_result), because
      "we passed the string to run_node" is not the same claim as "the record
      on disk says fetch".

    The card this runs carries NO artifacts on purpose: the refusal has to
    happen before anything is done, and if it ever stops happening (this guard
    exists to fail then) a run of this job dies in kcilib.run.jobrun's own
    "no kernel artifact" check - no container, no download, no network.  The
    ledger root and the console directory are temporary for the same reason:
    a broken refusal must not file a fixture build in this repository's work/.
    """
    spec = _row()
    build = _card(spec.build)
    job = Job(build.build_id, spec.test, timeout_s=spec.timeout_s,
              artifacts={}, build=Kbuild(build.build_id, {}))

    with tempfile.TemporaryDirectory() as tmp:
        real_env = os.environ.get(ledger.RESULTS_DIR_ENV)
        os.environ[ledger.RESULTS_DIR_ENV] = os.path.join(tmp, "results")
        real_run = kci_jobs._jobrun.run_node
        kept = {"log_dir": os.path.join(tmp, "logs")}
        seen = []
        recorded = {}

        def fake_run_node(definition, run_config, node_id=None, source=None):
            seen.append(source)
            # The writer run_node itself calls: the record is the evidence.
            recorded["path"] = kci_jobs._jobrun.record_result(
                definition, node_id, {"status": 2, "results": {}}, None, None,
                source=source)
            return None, None, {"status": 2, "results": {}}

        try:
            for wrong in ("in-container", "local-server", ""):
                try:
                    job.run(delivery=wrong, **kept)
                    check(False, f"run() accepted the delivery {wrong!r}")
                except ValueError as error:
                    for name in (DELIVERY_IN_CONTAINER, DELIVERY_LOCAL_SERVER):
                        check(name in str(error),
                              f"the refusal of {wrong!r} does not name "
                              f"{name}: {error}")
            check(kci_jobs._delivery_of(DELIVERY_LOCAL_SERVER)
                  == DELIVERY_LOCAL_SERVER,
                  "a legal delivery name was not accepted")
            kci_jobs._jobrun.run_node = fake_run_node
            outcome = job.run(source=SOURCE_FETCH)
            record = ledger.read_results(build.build_id).get(spec.test) or {}
        finally:
            kci_jobs._jobrun.run_node = real_run
            if real_env is None:
                os.environ.pop(ledger.RESULTS_DIR_ENV, None)
            else:
                os.environ[ledger.RESULTS_DIR_ENV] = real_env
        check(seen == [SOURCE_FETCH],
              f"the source did not reach the run layer verbatim: {seen}")
        check(outcome.is_pass(), f"the run did not pass: {outcome.verdict}")
        check(record.get("source") == SOURCE_FETCH,
              f"the ledger record does not say {SOURCE_FETCH!r}: "
              f"{record.get('source')!r}")
        check(record.get("build_id") == build.build_id,
              f"the record was filed under another build: {record}")
        check((recorded.get("path") or "").startswith(tmp),
              f"the record went outside the temporary ledger: "
              f"{recorded.get('path')}")
    print("test_job_run_refuses_an_unknown_delivery_and_files_its_source OK")


class _Server:
    """A stand-in for the artifact server process (nothing is started here)."""


def test_job_run_local_server_delivery():
    """delivery="local_server" downloads, serves, runs and stops - in order.

    kcilib.run.delivery's functions are replaced by recorders and run_node by a
    stub, so what is pinned is the wiring the one-shot fetch line depends on,
    and nothing that needs a container or a port:

    * every artifact tuxrun fetches is rewritten to
      ``http://<gateway>:<port>/<served name>`` and nothing else is touched
      (the rootfs is tuxrun's own bind mount, and the kernel config is read by
      nobody in the run layer);
    * the server starts only after the downloads were handed to
      kcilib.run.delivery, and it is stopped even when the run raises;
    * a server that refuses to start is an "error" Outcome carrying
      ArtifactServerError's own text - no traceback, and no fake stop of a
      server that never ran (delivery stops the ones it started itself);
    * the console is left under the fetch line's own name (tuxrun.log) as well
      as under the archive name run_node wrote, and the record says which
      entry point ran it.
    """
    spec = _row()
    card = _card(spec.build)
    artifacts = dict(card.artifacts, _config="https://files.kernelci.org/x/.cfg")
    job = Job(card.build_id, "kselftest-kvm", artifacts=artifacts, build=card)
    check(job.missing() == [], job.missing())

    calls = []
    definitions = []
    seams = []
    state = {"refuse": False}

    def fake_ensure_kernel(url, gz_path, image_path, record):
        calls.append(("kernel", url))
        return image_path

    def fake_ensure_artifact(url, dest, record, name, what):
        calls.append((name, url))
        return dest

    def fake_start(out, port, node, kernel):
        calls.append(("start", port, node.get("id")))
        if state["refuse"]:
            raise kci_jobs._delivery.ArtifactServerError(
                "artifact server port 8998 is already in use (guard)")
        return _Server()

    def fake_run_node(definition, run_config, node_id=None, source=None):
        definitions.append(definition)
        calls.append(("run", os.path.basename(definition["artifacts"]["kernel"])))
        # The runner seam the console's stream separator comes from is in
        # place for the run, and only for the run.
        seams.append(kci_jobs._jobrun.run_tuxrun is kci_jobs._fetch_console)
        # run_node archives the console it just wrote and names it in the
        # record, which is what the caller has to keep pointing at.
        os.makedirs(run_config.log_dir, exist_ok=True)
        archived = os.path.join(run_config.log_dir, f"{node_id}.log")
        with open(archived, "w") as handle:
            handle.write("console")
        kci_jobs._jobrun.record_result(
            definition, node_id, {"status": 2, "results": {}}, None, archived,
            source=source)
        return None, None, {"status": 2, "results": {}}

    patched = {
        "load_artifact_record": lambda out: (calls.append(("load", out)), {})[1],
        "save_artifact_record": lambda out, record: calls.append(("record",)),
        "ensure_kernel_image": fake_ensure_kernel,
        "ensure_artifact": fake_ensure_artifact,
        "start_artifact_server": fake_start,
        "stop_artifact_server": lambda server: calls.append(("stop",)),
    }
    real = {name: getattr(kci_jobs._delivery, name) for name in patched}
    real_run = kci_jobs._jobrun.run_node
    real_runner = kci_jobs._jobrun.run_tuxrun
    real_env = os.environ.get(ledger.RESULTS_DIR_ENV)

    with tempfile.TemporaryDirectory() as tmp:
        os.environ[ledger.RESULTS_DIR_ENV] = os.path.join(tmp, "results")
        out = os.path.join(tmp, "downloads", card.build_id)
        try:
            for name, function in patched.items():
                setattr(kci_jobs._delivery, name, function)
            kci_jobs._jobrun.run_node = fake_run_node
            outcome = job.run(delivery=DELIVERY_LOCAL_SERVER,
                              source=SOURCE_FETCH, serve_port=8998,
                              gateway="10.1.2.3", out_dir=out)
            first_calls = list(calls)
            # A named node id: the console is archived under it (that is
            # run_node's own naming rule), the fetch line's own console name
            # stays, and the record follows the id the run layer was handed.
            named = job.run(delivery=DELIVERY_LOCAL_SERVER,
                            source=SOURCE_FETCH, node_id="fetch-node",
                            serve_port=8998, gateway="10.1.2.3", out_dir=out)
            # A busy port: an Outcome, not a traceback, and no invented stop.
            state["refuse"] = True
            before = list(calls)
            refused = job.run(delivery=DELIVERY_LOCAL_SERVER,
                              source=SOURCE_FETCH, serve_port=8998,
                              gateway="10.1.2.3", out_dir=out)
            record = ledger.read_results(card.build_id).get("kselftest-kvm")
            named_record = ledger.read_results("fetch-node").get(
                "kselftest-kvm")
        finally:
            state["refuse"] = False
            for name, function in real.items():
                setattr(kci_jobs._delivery, name, function)
            kci_jobs._jobrun.run_node = real_run
            if real_env is None:
                os.environ.pop(ledger.RESULTS_DIR_ENV, None)
            else:
                os.environ[ledger.RESULTS_DIR_ENV] = real_env

        check(outcome.is_pass(), f"the served run did not pass: {outcome.detail}")
        check(len(definitions) == 2,
              f"run_node was called {len(definitions)}x for two served runs")
        check(definitions[0] == definitions[1],
              "the two served runs were handed different definitions")
        served = definitions[0]["artifacts"]
        base = "http://10.1.2.3:8998"
        for key, name in (("kernel", "Image"),
                          ("kselftest", "kselftest.tar.xz"),
                          ("kselftest_tar_xz", "kselftest.tar.xz"),
                          ("modules", "modules.tar.xz")):
            check(served.get(key) == f"{base}/{name}",
                  f"{key} is not served from {base}/{name}: {served.get(key)}")
        check(served.get("_config") == "https://files.kernelci.org/x/.cfg",
              "an artifact the run layer never fetches was rewritten")
        check(served.get("rootfs") == jobspec.ROOTFS_URL,
              "the rootfs must stay tuxrun's own (a local path is a bind mount)")
        check(definitions[0]["tests"] == job._definition()["tests"],
              "the served definition rewrote something other than URLs")

        order = [call[0] for call in first_calls]
        check(order == ["load", "kernel", "kselftest.tar.xz", "modules.tar.xz",
                        ".config", "record", "start", "run", "stop"],
              f"the local_server order changed: {order}")
        check(first_calls[2][1] == artifacts["kselftest_tar_xz"]
              and first_calls[3][1] == artifacts["modules"],
              f"the downloads did not come from the definition: {first_calls}")

        console = os.path.join(out, "tuxrun.log")
        archived = os.path.join(out, f"{card.build_id}.log")
        check(outcome.log == console,
              f"the outcome does not name the fetch line's console: "
              f"{outcome.log}")
        with open(console, encoding="utf-8") as handle:
            check(handle.read() == "console",
                  "the console did not survive under the fetch line's name")
        check(os.path.isfile(archived),
              "the archive run_node wrote is gone: the record names it")
        check(outcome.record is not None, "the outcome lost the ledger record")
        check((record or {}).get("source") == SOURCE_FETCH,
              f"the served run's record lost its source: {record}")
        check((record or {}).get("log", "").endswith(f"{card.build_id}.log"),
              f"the record does not name the console it archived: {record}")

        # The node id the caller names is the console's archive name and the
        # node id run_node labels the run with; the console the operator reads
        # is still tuxrun.log, and the record follows the id that was handed.
        check(named.log == console and named.is_pass(),
              f"a named node id moved the console: {named.log}")
        check(os.path.isfile(os.path.join(out, "fetch-node.log"))
              and os.path.samefile(os.path.join(out, "fetch-node.log"), console),
              "the console was not archived under the node id it was handed")
        check(named.record is not None
              and named.record.endswith(os.path.join("fetch-node",
                                                     "kselftest-kvm.json")),
              f"the record does not follow the node id it was handed: "
              f"{named.record}")
        check((named_record or {}).get("source") == SOURCE_FETCH,
              f"the named run's record lost its source: {named_record}")

        check(isinstance(refused, Outcome) and refused.verdict == "error"
              and refused.exit_code == kci_jobs.EXIT_ERROR,
              f"a refused server is not an infra Outcome: {refused!r}")
        check("already in use" in refused.detail,
              f"the refusal lost its reason: {refused.detail!r}")
        check(("stop",) not in calls[len(before):],
              "a server that never started was stopped")
        check(seams == [True, True],
              f"the fetch line's console rule was not in place for the run: "
              f"{seams}")
        check(kci_jobs._jobrun.run_tuxrun is real_runner,
              "the runner seam was not put back after the run")

    # And the separator itself: the fetch line concatenates tuxrun's stdout
    # and stderr with NOTHING between them, while the worker joins them with a
    # newline (docs/ARCHITECTURE.md).  Two real, byte-different consoles.
    real_runner = kci_jobs._runner.run_tuxrun
    seen_runner = []

    def fake_runner(argv, timeout=None, log_path=None, *, cwd=None,
                    stream_separator="\n"):
        seen_runner.append((argv, timeout, log_path, cwd, stream_separator))

    kci_jobs._runner.run_tuxrun = fake_runner
    try:
        kci_jobs._fetch_console(["tuxrun"], timeout=7, log_path="log",
                                cwd="/tmp", stream_separator="\n")
    finally:
        kci_jobs._runner.run_tuxrun = real_runner
    check(seen_runner == [(["tuxrun"], 7, "log", "/tmp", "")],
          f"the one-shot console separator changed: {seen_runner}")
    print("test_job_run_local_server_delivery OK")
