"""Node -> BuildRef -> JobSpec, and the sqlite index's idempotent writes."""
import os
import tempfile

from .support import check


def test_build_ref_and_jobspec():
    """The local job table's two pure layers: node -> BuildRef -> JobSpec.

    Both are pure, so they need no network, API or run.  Pinned down: a node
    whose artifacts name no build falls back to the node id, and a build lacking
    a collection's tarball SKIPs loudly instead of dying 20 minutes into a job."""
    from kcilib.table import buildref, jobspec

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
    ref = buildref.build_ref_from_node(node)
    check(ref.build_id == "6aa3689720239ade90209d50",
          f"the build id must come from the artifact URL, got {ref.build_id}")
    check(ref.node_id == "6aa822fcf84821b97339d2f9",
          f"the source node id is kept as a reference, got {ref.node_id}")
    check(ref.tree == "net-next" and ref.commit == "348ea4642f56",
          f"tree/commit must come from the node: {ref.tree}/{ref.commit}")
    check(ref.missing_for("kselftest-kvm") == (),
          "this node carries everything the kvm collection needs")

    local_only = dict(node, artifacts={"kernel": "http://172.17.0.1:8999/Image"})
    fallback = buildref.build_ref_from_node(local_only)
    check(fallback.build_id == "6aa822fcf84821b97339d2f9",
          f"without a build id the node id stands in, got {fallback.build_id}")

    for broken in ({}, dict(node, artifacts={})):
        try:
            buildref.build_ref_from_node(broken)
        except ValueError:
            pass
        else:
            check(False, f"a node without a kernel must be refused: {broken}")

    specs, skipped = jobspec.jobs_from_build(fallback,
                                             tests=("boot", "kselftest-kvm"))
    check([spec.test for spec in specs] == ["boot"],
          f"only boot is runnable without the kselftest tarball: {specs}")
    check(skipped and skipped[0][0] == "kselftest-kvm",
          f"the skipped test must be reported: {skipped}")
    check(all(spec.timeout_s for spec in specs),
          "every spec must carry a timeout (the runner needs one)")

    plain = jobspec.job_definition(specs[0])
    check("callback" not in plain,
          "without a callback URL the definition must carry no callback section")
    check(set(plain) == {"artifacts", "tests", "environment"},
          f"unexpected definition keys: {sorted(plain)}")
    check(plain["environment"]["platform"] == "qemu-riscv64",
          f"platform must be qemu-riscv64: {plain['environment']}")
    with_cb = jobspec.job_definition(specs[0],
                                     callback_url="http://127.0.0.1:8003/n/1")
    check(with_cb["callback"]["url"] == "http://127.0.0.1:8003/n/1",
          "a callback URL must reach the definition, or the result is never posted")

    from kcilib.table.buildindex import BuildIndex
    with tempfile.TemporaryDirectory() as tmp:
        index = BuildIndex(os.path.join(tmp, "builds.db"))
        check(index.add(ref) is True, "the first add is new")
        check(index.add(ref) is False, "the second add must be a no-op")
        check(index.count() == 1, f"one row expected, got {index.count()}")
        roundtrip = index.get(ref.build_id)
        check(roundtrip and roundtrip.artifacts == ref.artifacts,
              f"artifacts must survive the roundtrip: {roundtrip.artifacts}")
        check(roundtrip.commit == ref.commit, "the commit column must roundtrip")
    print("test_build_ref_and_jobspec OK")
