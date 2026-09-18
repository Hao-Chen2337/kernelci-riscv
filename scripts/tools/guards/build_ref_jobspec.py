"""Node -> Build -> Job, and the sqlite index's idempotent writes.

The file and the function in it keep the names they had while the two classes
were called BuildRef and JobSpec: the runner registers both
(guards/runner.py: build_ref_jobspec.test_build_ref_and_jobspec), so renaming
them would edit the gate's own list rather than the thing it pins.  What is
pinned is the new single vocabulary - kcilib.table.build.Build is the one build
class (the table's row and the model's card at once) and
kcilib.model.jobs.jobs_for() the one "one build -> its jobs".
"""
import os
import tempfile

from .support import check


def test_build_ref_and_jobspec():
    """The local job table's two pure layers: node -> Build -> Job.

    Both are pure, so they need no network, API or run.  Pinned down: a node
    whose artifacts name no build falls back to the node id, a build lacking a
    collection's tarball SKIPs loudly instead of dying 20 minutes into a job,
    and the build's index column "source" is DERIVED from its origin (it was a
    stored field while BuildRef carried it, so the row could disagree with the
    object)."""
    from kcilib.model import ORIGIN_HANDMADE, Job
    from kcilib.model.jobs import jobs_for
    from kcilib.table.build import build_from_node

    node = {
        "id": "6aa822fcf84821b97339d2f9",
        "created": "2026-09-16T01:22:08Z",
        "data": {"kernel_revision": {"tree": "net-next", "commit": "348ea4642f56",
                                     "describe": "v7.3-rc2-758-g87b80c2f6b05c"}},
        "artifacts": {
            "kernel": "http://172.17.0.1:8999/Image",
            "kselftest_tar_xz": ("https://files.kernelci.org/"
                                 "kbuild-gcc-14-riscv-6aa3689720239ade90209d50/"
                                 "kselftest.tar.xz"),
            "modules": ("https://files.kernelci.org/"
                        "kbuild-gcc-14-riscv-6aa3689720239ade90209d50/"
                        "modules.tar.xz"),
        },
    }
    build = build_from_node(node)
    check(build.build_id == "6aa3689720239ade90209d50",
          f"the build id must come from the artifact URL, got {build.build_id}")
    check(build.node_id == "6aa822fcf84821b97339d2f9",
          f"the source node id is kept as a reference, got {build.node_id}")
    check(build.tree == "net-next" and build.commit == "348ea4642f56",
          f"tree/commit must come from the node: {build.tree}/{build.commit}")
    check(build.missing_for("kselftest-kvm") == [],
          "this node carries everything the kvm collection needs")

    # source is the index's coarse official|local column and is read-only: it is
    # derived from origin, so a row cannot claim a provenance its build denies.
    check(build.source == "official" and build.as_row()["source"] == "official",
          f"an ORIGIN_API build is the official column: {build.origin}")
    check(build_from_node(node, origin=ORIGIN_HANDMADE).source == "local",
          "only the two API origins are 'official'; everything else is 'local'")
    try:
        build.source = "local"
    except AttributeError:
        pass
    else:
        check(False, "Build.source must be read-only: it is derived from origin")

    local_only = dict(node, artifacts={"kernel": "http://172.17.0.1:8999/Image"})
    fallback = build_from_node(local_only)
    check(fallback.build_id == "6aa822fcf84821b97339d2f9",
          f"without a build id the node id stands in, got {fallback.build_id}")

    for broken in ({}, dict(node, artifacts={})):
        try:
            build_from_node(broken)
        except ValueError:
            pass
        else:
            check(False, f"a node without a kernel must be refused: {broken}")

    jobs, skipped = jobs_for(fallback, tests=("boot", "kselftest-kvm"))
    check([job.test for job in jobs] == ["boot"],
          f"only boot is runnable without the kselftest tarball: {jobs.jobs}")
    check(skipped and skipped[0][0] == "kselftest-kvm",
          f"the skipped test must be reported: {skipped}")
    check(all(job.timeout_s for job in jobs),
          "every job must carry a timeout (the runner needs one)")

    plain = jobs[0].definition()
    check("callback" not in plain,
          "without a callback URL the definition must carry no callback section")
    check(set(plain) == {"artifacts", "tests", "environment"},
          f"unexpected definition keys: {sorted(plain)}")
    check(plain["environment"]["platform"] == "qemu-riscv64",
          f"platform must be qemu-riscv64: {plain['environment']}")
    with_cb = Job(jobs[0].build_id, jobs[0].test,
                  artifacts=dict(fallback.artifacts),
                  callback={"url": "http://127.0.0.1:8003/n/1"},
                  build=fallback).definition()
    check(with_cb["callback"]["url"] == "http://127.0.0.1:8003/n/1",
          "a callback URL must reach the definition, or the result is never posted")

    from kcilib.table.buildindex import BuildIndex
    with tempfile.TemporaryDirectory() as tmp:
        index = BuildIndex(os.path.join(tmp, "builds.db"))
        check(index.add(build) is True, "the first add is new")
        check(index.add(build) is False, "the second add must be a no-op")
        check(index.count() == 1, f"one row expected, got {index.count()}")
        roundtrip = index.get(build.build_id)
        check(roundtrip and roundtrip.artifacts == build.artifacts,
              f"artifacts must survive the roundtrip: {roundtrip.artifacts}")
        check(roundtrip.commit == build.commit, "the commit column must roundtrip")
        check(roundtrip.source == build.source == "official",
              f"the source column must roundtrip: {roundtrip.source!r}")
    print("test_build_ref_and_jobspec OK")
