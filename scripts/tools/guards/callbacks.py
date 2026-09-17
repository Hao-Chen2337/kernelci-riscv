"""Callback classification, and a result that must survive an unposted POST."""
import os
import tempfile

import kcilib
from kcilib.core import config, ledger
from kcilib.run import callback, jobrun, judge, poll

from .support import (
    _poll_config,
    _Response,
    _run_job_config,
    check,
    no_sleep,
    read_state,
    stub_requests,
)


def test_post_result_classification():
    """#3: a result that was not posted must never look posted."""
    check(issubclass(callback.CallbackMissingURLError,
                     callback.CallbackTransientError),
          "a missing callback URL must take the transient path (keep the "
          "result, retry) - the permanent path gives up and marks the node "
          "seen")
    with no_sleep(), stub_requests(callback):  # no HTTP call may happen at all
        try:
            callback.post_result("", "tok", {"status": 2})
            check(False, "post_result with no callback URL returned normally "
                         "(the caller then logs 'result posted')")
        except callback.CallbackMissingURLError as error:
            check("pending" in str(error), error)
        except Exception as error:  # noqa: BLE001 - the point of the test
            check(False, f"missing callback URL raised {error!r}")

    status = {"code": 200}
    with no_sleep(), stub_requests(
            callback, post=lambda url, **kw: _Response(status["code"])):
        callback.post_result("http://cb", "tok", {"status": 2})
        callback.post_result("http://cb", "tok", {"status": 2})
        status["code"] = 403
        try:
            callback.post_result("http://cb", "tok", {"status": 2})
            check(False, "a 4xx from the callback must raise (it used to be "
                         "reported as posted)")
        except callback.CallbackPermanentError:
            pass
        status["code"] = 503
        try:
            callback.post_result("http://cb", "tok", {"status": 2})
            check(False, "a 5xx from the callback must raise after the retries")
        except callback.CallbackTransientError:
            pass
    print("test_post_result_classification OK")


def test_missing_callback_keeps_result_pending():
    """#3 end to end: no callback URL -> not posted and not marked seen, because
    the result it just produced is the only copy."""
    node_id = "6aa387ecba3aeacda180ff12"
    job_def = {"callback": {}, "environment": {"platform": "qemu-riscv64"},
               "artifacts": {"kernel": "http://x/Image"},
               "tests": [{"type": "boot"}]}
    event = {"node": {"id": node_id,
                      "artifacts": {"job_definition": "http://x/job.yaml"}},
             "data": {"data": {"platform": "qemu-riscv64",
                               "runtime": "pull-labs-riscv"}}}

    def fake_run_command(cmd, timeout_s, workspace):
        with open(os.path.join(workspace, "tuxrun.log"), "w") as handle:
            handle.write("2026-09-08T00:00:00 console\n")
        return 0, "2026-09-08T00:00:00 console\n"

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "out"))
        run_config = _run_job_config(tmp)
        poll_config = _poll_config("unused-state.json")
        reports = {}
        # The ledger root is redirected for the duration: this test drives a
        # REAL run_node(), and the record it files must not land in the
        # repository's work/results/ - `./run.sh verify` would dirty the tree it
        # is verifying.
        results_dir = os.path.join(tmp, "results")
        real_results_env = os.environ.get(ledger.RESULTS_DIR_ENV)
        os.environ[ledger.RESULTS_DIR_ENV] = results_dir
        baked, stamped = [], []
        real_retrieve = poll.retrieve_job_definition
        real_run_command = jobrun.run_command
        real_bake = jobrun.baked_rootfs_image
        real_stamp = jobrun.stamp
        poll.retrieve_job_definition = lambda url: job_def
        jobrun.run_command = fake_run_command

        def no_bake(*bake_args, **bake_kwargs):
            baked.append((bake_args, bake_kwargs))
            return "/tmp/not-baked.ext4"

        # run_node() resolves both as kcilib.run.jobrun module globals, which is
        # where the seam is: a boot job must never bake.
        jobrun.baked_rootfs_image = no_bake
        jobrun.stamp = stamped.append
        try:
            with no_sleep(), stub_requests(
                poll,
                get=lambda url, **kw: _Response(
                    200, json_body={"state": "available"})
            ):
                handled = poll.handle_event(event, poll_config, run_config,
                                            reports, jobrun.run_node)
        finally:
            poll.retrieve_job_definition = real_retrieve
            jobrun.run_command = real_run_command
            jobrun.baked_rootfs_image = real_bake
            jobrun.stamp = real_stamp
        check(baked == [], f"a boot job must not bake a guest image: {baked}")
        check(stamped, "the job's progress lines must still be stamped")
        check(handled is False,
              "a job with no callback URL must not be treated as handled "
              "(that marks the node seen and drops the result)")
        check(node_id in reports,
              "the produced result must stay queued for re-posting")
        check(not reports[node_id][0],
              f"the queued report must keep the (empty) callback: {reports}")
        check(reports[node_id][2].get("status") == 3,
              f"the report must be the run's real body: {reports}")

        # The same run must also be in the ledger: the worker used to file
        # nothing, so work/results/ held only the one-shot runner's rows.  The
        # build id falls back to the job node id, as this job names no build.
        record_path = ledger.result_path(node_id, "boot")
        check(os.path.isfile(record_path),
              f"the run must be recorded at {record_path}")
        record = ledger.read_results(node_id)["boot"]
        check(record["verdict"] == judge.VERDICT_INFRA,
              f"the record must carry the body's verdict: {record['verdict']}")
        check(record["source"] == "worker",
              f"the record must name its writer: {record['source']}")
        check(record["exit_code"] == judge.EXIT_INFRA,
              f"the record must carry the body's exit code: {record['exit_code']}")
        check(record["log"] and record["log"].endswith(".log"),
              f"the record must point at the archived console: {record['log']}")
        # The guards live in scripts/tools/guards/, so the root is walked up to.
        repo_results = os.path.join(kcilib.repo_root(), "work", "results")
        check(not os.path.isdir(repo_results)
              or node_id not in os.listdir(repo_results),
              "the record must not land in the repository's work/results/")
    if real_results_env is None:
        os.environ.pop(ledger.RESULTS_DIR_ENV, None)
    else:
        os.environ[ledger.RESULTS_DIR_ENV] = real_results_env
    print("test_missing_callback_keeps_result_pending OK")


def test_state_flushed_before_a_crash():
    """#9: a kill mid-batch must not lose a collected result.

    handle_event() queues a report and then raises, which is what a crash looks
    like from poll_loop's side: the state file must already hold the report, so
    the next start re-posts it instead of re-running tuxrun."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        poll_config = _poll_config(state_file)
        events = [{"node": {"id": "node-1"},
                   "timestamp": "2026-09-08T00:00:00.000000"}]

        def fake_handle(_event, _poll_config, _run_config, reports, _run_node):
            reports["node-1"] = ("http://cb", "tok", {"status": 2})
            raise RuntimeError("worker killed mid-batch")

        real_fetch, real_handle = poll.fetch_nodes, poll.handle_event
        poll.fetch_nodes = lambda *_a, **_k: events
        poll.handle_event = fake_handle
        try:
            try:
                poll.poll_loop(poll_config, jobrun.run_node, config.RunConfig())
                check(False, "the simulated crash did not propagate")
            except RuntimeError:
                pass
        finally:
            poll.fetch_nodes, poll.handle_event = real_fetch, real_handle
        state = read_state(state_file)
        check(state["pending"].get("node-1", {}).get("body") == {"status": 2},
              f"the unposted result did not survive the crash: {state}")
        check("node-1" not in state["seen"],
              f"a node whose result is still pending must not be seen: {state}")
    print("test_state_flushed_before_a_crash OK")
