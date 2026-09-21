# SPDX-License-Identifier: LGPL-2.1-or-later
"""The fixture: the rows the prototype draws, in the shape the real readers return.

**This module is the seam.**  Every page in `pages.py` reads its rows out of the
dict `data()` returns and knows nothing else about where they came from, so
replacing this file with the real thing is the whole of "wire it up":

    lib/kci_results.py   ->  "records"   (the ledger, `var/results/*.json`)
    lib/kci_table.py     ->  "builds"    (the local table, `var/state/builds.json`)
    lib/api.py           ->  "api_rows"  (what the API says about a build)
    lib/kci_runs.py      ->  "runs"      (the console's own background processes)
    lib/kci_poller.py    ->  "worker"    (the poller's state file)

The values are copied from what the running 8082 console printed on
2026-09-21 - real build ids, real tree/branch pairs, real byte counts, real
verdict details - so that a layout decision made here is a decision about the
data that will actually arrive.  Nothing here is invented to make a column look
full; where the real page had a dash, this has a dash.
"""

import time

# ---------------------------------------------------------------- the builds
# `checks` is the three artifacts a card is made of, in the order the page shows
# them.  A build that has bytes on disk but no card is the case the left column
# exists for, so one row here is exactly that.
BUILDS = [
    dict(build_id="6aaf3175d96a8203de710e5c", tree="net-next", branch="main",
         created="2026-09-20T01:05", checks=dict(kernel=True, kselftest=True, modules=True),
         here="whole", bytes_mib=38.9, acts=5, acts_host="files.kernelci.org",
         acts_when="2026-09-20T09:20", api=("done", "pass", "6aaf3175d96a"),
         ran=[("boot", "pass"), ("kselftest-riscv", "pass"), ("kselftest-kvm", "pass")]),
    dict(build_id="6aaf2335d96a8203de70924d", tree="net-next", branch="main",
         created="2026-09-20T00:05", checks=dict(kernel=True, kselftest=True, modules=True),
         here="whole", bytes_mib=38.7, acts=4, acts_host="files.kernelci.org",
         acts_when="2026-09-20T08:14", api=("done", "pass", "6aaf2335d96a"),
         ran=[("boot", "pass"), ("kselftest-riscv", "pass"), ("kselftest-kvm", "fail")]),
    dict(build_id="6aaf1468d96a8203de70924d", tree="net-next", branch="main",
         created="2026-09-19T23:02", checks=dict(kernel=True, kselftest=True, modules=True),
         here="whole", bytes_mib=38.6, acts=3, acts_host="files.kernelci.org",
         acts_when="2026-09-20T07:02", api=("done", "pass", "6aaf1468d96a"),
         ran=[("boot", "pass"), ("kselftest-riscv", "pass"), ("kselftest-kvm", "pass")]),
    dict(build_id="6aa3689720239ade1f0b3c7a", tree="mainline", branch="master",
         created="2026-09-19T14:58", checks=dict(kernel=True, kselftest=True, modules=False),
         here="partial", bytes_mib=27.4, acts=2, acts_host="files.kernelci.org",
         acts_when="2026-09-19T18:31", api=("done", "pass", "6aa3689720239ade"),
         ran=[("boot", "pass"), ("kselftest-riscv", "pass"), ("kselftest-kvm", "incomplete")]),
    dict(build_id="6aade015d96a8203de40918b", tree="riscv", branch="for-next",
         created="2026-09-19T08:20", checks=dict(kernel=True, kselftest=True, modules=True),
         here="whole", bytes_mib=40.2, acts=6, acts_host="files.kernelci.org",
         acts_when="2026-09-19T12:40", api=("done", "pass", "6aade015d96a"),
         ran=[("boot", "pass"), ("kselftest-riscv", "fail"), ("kselftest-kvm", "pass")]),
    dict(build_id="6aacc1f2d96a8203de1177aa", tree="riscv", branch="fixes",
         created="2026-09-18T22:47", checks=dict(kernel=True, kselftest=False, modules=False),
         here="card only", bytes_mib=None, acts=0, acts_host="", acts_when="",
         api=None, ran=[("boot", None), ("kselftest-riscv", None), ("kselftest-kvm", None)]),
    dict(build_id="6aab88c0d96a8203de5512ee", tree="stable-rc", branch="linux-6.12.y",
         created="2026-09-18T14:02", checks=dict(kernel=True, kselftest=True, modules=True),
         here="whole", bytes_mib=37.1, acts=3, acts_host="files.kernelci.org",
         acts_when="2026-09-18T19:22", api=None,
         ran=[("boot", "pass"), ("kselftest-riscv", "incomplete"), ("kselftest-kvm", None)]),
]

# what `Build.make()` recorded, one row per act, newest first
PULLS = [
    dict(when="2026-09-20T09:20:48Z", build_id="6aaf3175d96a8203de710e5c", artifacts=3,
         bytes_raw=40764928, mib="38.9 MiB", transferred=0, hosts="files.kernelci.org", error=None),
    dict(when="2026-09-20T09:19:06Z", build_id="6aaf3175d96a8203de710e5c", artifacts=2,
         bytes_raw=36431464, mib="34.7 MiB", transferred=0, hosts="files.kernelci.org", error=None),
    dict(when="2026-09-20T08:14:02Z", build_id="6aaf2335d96a8203de70924d", artifacts=3,
         bytes_raw=40579072, mib="38.7 MiB", transferred=1, hosts="files.kernelci.org", error=None),
    dict(when="2026-09-20T07:02:41Z", build_id="6aaf1468d96a8203de70924d", artifacts=3,
         bytes_raw=40468480, mib="38.6 MiB", transferred=0, hosts="files.kernelci.org", error=None),
    dict(when="2026-09-19T18:31:19Z", build_id="6aa3689720239ade1f0b3c7a", artifacts=2,
         bytes_raw=28729344, mib="27.4 MiB", transferred=0, hosts="files.kernelci.org",
         error="kselftest.tar.xz: 404 from files.kernelci.org"),
]

# ---------------------------------------------------------------- the jobs
# The pairs the ledger has nothing for.  `runs` is how many records exist, so a
# row with runs=0 is the gap this page exists to show.
GAP = [
    dict(build_id="6aaf3175d96a8203de710e5c", tree="net-next", test="boot",
         needs="kernel", ready=True, runs=0, last=None, when=None, gap=True),
    dict(build_id="6aaf3175d96a8203de710e5c", tree="net-next", test="kselftest-kvm",
         needs="kernel, modules, kselftest", ready=False, runs=0, last=None, when=None, gap=True),
    dict(build_id="6aaf2335d96a8203de70924d", tree="net-next", test="boot",
         needs="kernel", ready=True, runs=0, last=None, when=None, gap=True),
    dict(build_id="6aa3689720239ade1f0b3c7a", tree="mainline", test="kselftest-riscv",
         needs="kernel, kselftest", ready=True, runs=1, last="pass", when="2026-09-20T07:20",
         gap=False),
    dict(build_id="6aa3689720239ade1f0b3c7a", tree="mainline", test="kselftest-kvm",
         needs="kernel, modules, kselftest", ready=False, runs=1, last="pass",
         when="2026-09-20T07:23", gap=False),
    dict(build_id="6aacc1f2d96a8203de1177aa", tree="riscv", test="boot",
         needs="kernel", ready=False, runs=0, last=None, when=None, gap=True),
]

# the ledger in full: every record, whoever wrote it.  `source` is the column the
# worker panel below filters on.
LEDGER = [
    dict(build_id="6aade015d96a8203de40918b", test="boot", verdict="pass", exit=0,
         source="worker", when="2026-09-21T05:15:30Z", detail="guest booted"),
    dict(build_id="6aaf3175d96a8203de710e5c", test="kselftest-kvm", verdict="pass", exit=0,
         source="worker", when="2026-09-21T04:58:02Z", detail="12 selftests: 9 pass, 0 fail, 3 skip"),
    dict(build_id="6aade015d96a8203de40918b", test="kselftest-riscv", verdict="fail", exit=1,
         source="worker", when="2026-09-20T16:54:22Z", detail="12 selftests: 10 pass, 2 fail"),
    dict(build_id="6aade015d96a8203de40918b", test="kselftest-kvm", verdict="pass", exit=0,
         source="worker", when="2026-09-20T16:57:31Z", detail="12 selftests: 9 pass, 0 fail, 3 skip"),
    dict(build_id="6aaf3175d96a8203de710e5c", test="boot", verdict="pass", exit=0,
         source="worker", when="2026-09-20T15:03:11Z", detail="guest booted"),
    dict(build_id="6aaf2335d96a8203de70924d", test="kselftest-kvm", verdict="incomplete", exit=3,
         source="runday", when="2026-09-20T09:14:00Z", detail="tuxrun timed out after 900s"),
    dict(build_id="6aaf2335d96a8203de70924d", test="boot", verdict="pass", exit=0,
         source="runday", when="2026-09-20T08:51:12Z", detail="guest booted"),
    dict(build_id="6aaf1468d96a8203de70924d", test="boot", verdict="pass", exit=0,
         source="table", when="2026-09-19T23:44:08Z", detail="guest booted"),
    dict(build_id="6aa3689720239ade1f0b3c7a", test="boot", verdict="pass", exit=0,
         source="index", when="2026-09-19T14:58:20Z", detail="guest booted"),
    dict(build_id="6aab88c0d96a8203de5512ee", test="kselftest-riscv", verdict="incomplete", exit=3,
         source="worker", when="2026-09-18T19:31:47Z", detail="log truncated: no summary line"),
]

# ---------------------------------------------------------------- the worker
WORKER = dict(
    running=True,
    run_id="20260921T133948-worker",
    pid=338070,
    started="2026-09-21T13:39:48",
    uptime="80m36s",
    argv=("python3 pull_worker.py --platform qemu-riscv64 "
          "--runtime pull-labs-riscv --api-url http://127.0.0.1:8001"),
    state_file="var/state/worker-state.json",
    cursor="2026-09-21T05:33:08.834000",
    seen=20,
    pending=0,
)

# the job nodes the runtime can see, newest first
QUEUE = [
    dict(node_id="6ab0c1940c05", name="boot", state="done", result="pass",
         platform="qemu-riscv64", runtime="pull-labs-riscv", created="2026-09-20T08:20",
         claimed=True),
    dict(node_id="6ab0bd560c05", name="kselftest-riscv", state="done", result="fail",
         platform="qemu-riscv64", runtime="pull-labs-riscv", created="2026-09-20T08:42",
         claimed=True),
    dict(node_id="6ab0a1f20c05", name="kselftest-kvm", state="available", result=None,
         platform="qemu-riscv64", runtime="pull-labs-riscv", created="2026-09-20T09:10",
         claimed=False),
    dict(node_id="6ab08c440c05", name="boot", state="available", result=None,
         platform="qemu-riscv64", runtime="pull-labs-riscv", created="2026-09-21T04:55",
         claimed=False),
]

# ---------------------------------------------------------------- the runs
RUNS = [
    dict(id="20260921T133948-worker", kind="worker", state="running", pid=338070,
         started="13:39:48", ended=None, exit=None, age="80m36s",
         what="worker: --platform qemu-riscv64 --runtime pull-labs-riscv",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/pull_worker.py --platform qemu-riscv64 --runtime pull-labs-riscv --api-url http://127.0.0.1:8001"),
    dict(id="20260921T133941-worker", kind="worker", state="done", pid=338059,
         started="13:39:41", ended="13:39:41", exit=0, age="0s",
         what="worker: --once --platform qemu-riscv64 --runtime pull-labs-riscv",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/pull_worker.py --once --platform qemu-riscv64 --runtime pull-labs-riscv --api-url http://127.0.0.1:8001"),
    dict(id="20260921T130919-worker", kind="worker", state="done", pid=337914,
         started="13:09:19", ended="13:25:04", exit=0, age="15m45s",
         what="worker: --platform qemu-riscv64 --runtime pull-labs-riscv",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/pull_worker.py --platform qemu-riscv64 --runtime pull-labs-riscv --api-url http://127.0.0.1:8001"),
    dict(id="20260920T224036-table", kind="table", state="failed", pid=331077,
         started="22:40:36", ended="22:41:17", exit=None, age="41s",
         what="index: --days 0 --limit 5",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/table.py index --api-url http://127.0.0.1:8001 --days 0 --limit 5"),
    dict(id="20260920T152050-run", kind="run", state="incomplete", pid=328811,
         started="15:20:50", ended="15:44:02", exit=3, age="23m12s",
         what="run: --build 17 --test kselftest-kvm",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/run_latest.py --build 17 --test kselftest-kvm"),
    dict(id="20260920T145110-run", kind="run", state="incomplete", pid=328204,
         started="14:51:10", ended="15:11:33", exit=3, age="20m23s",
         what="run: --build 50 --test kselftest-riscv",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/run_latest.py --build 50 --test kselftest-riscv"),
    dict(id="20260920T104402-runday", kind="runday", state="done", pid=326640,
         started="10:44:02", ended="11:02:18", exit=0, age="18m16s",
         what="runday: --days 1",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/runday.py --days 1"),
    dict(id="20260919T221508-fetch", kind="fetch", state="done", pid=325190,
         started="22:15:08", ended="22:15:54", exit=0, age="46s",
         what="fetch: --tree riscv --branch for-next",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/table.py fetch --tree riscv --branch for-next"),
]

# ---------------------------------------------------------------- analysis
# One row per position in the order the reader chose.  `delta_up` / `delta_down`
# are the config comparison with the neighbour: (added, removed, changed) or None
# when the pair was not read - which is the honest state of every row past the
# `delta` cap and of both ends.
PICKS = [
    dict(rank=1, build_id="6aaf3175d96a8203de710e5c", tree="net-next", branch="main",
         describe="asoc-fix-v7.3-rc3-1234-gabc1234", verdict="pass", total=12, failed=0,
         skipped=0, delta_up=None, delta_down=(3, 1, 2)),
    dict(rank=2, build_id="6aaf2335d96a8203de70924d", tree="net-next", branch="main",
         describe="asoc-fix-v7.3-rc3-1230-gdef5678", verdict="pass", total=12, failed=0,
         skipped=0, delta_up=(3, 1, 2), delta_down=(0, 0, 0)),
    dict(rank=3, build_id="6aaf1468d96a8203de70924d", tree="net-next", branch="main",
         describe="asoc-fix-v7.3-rc3-1218-gaaa9012", verdict="pass", total=12, failed=0,
         skipped=0, delta_up=(0, 0, 0), delta_down=(0, 0, 0)),
    dict(rank=4, build_id="6aa3689720239ade1f0b3c7a", tree="mainline", branch="master",
         describe="v6.12-rc5-118-g3f2e91a", verdict="pass", total=12, failed=0, skipped=0,
         delta_up=(0, 0, 0), delta_down=None),
    dict(rank=5, build_id="6aade015d96a8203de40918b", tree="riscv", branch="for-next",
         describe="v6.12-rc5-204-g9c4b7d1", verdict="fail", total=12, failed=2, skipped=0,
         delta_up=None, delta_down=None),
    dict(rank=6, build_id="6aacc1f2d96a8203de1177aa", tree="riscv", branch="fixes",
         describe="v6.12-rc4-88-g1a7f3c9", verdict=None, total=None, failed=None,
         skipped=None, delta_up=None, delta_down=None),
    dict(rank=7, build_id="6aab88c0d96a8203de5512ee", tree="stable-rc", branch="linux-6.12.y",
         describe="v6.12.51-12-g4d8a2f0", verdict="incomplete", total=12, failed=0, skipped=0,
         delta_up=None, delta_down=None),
]

# One bar per build for the chosen test: what answered and how it answered.  The
# three numbers are the run's own counts, not a running total - which is the
# distinction the mockup note asked to have drawn.
BARS = [
    dict(build_id="6aaf3175d96a8203de710e5c", ok=12, bad=0, warn=0),
    dict(build_id="6aaf2335d96a8203de70924d", ok=12, bad=0, warn=0),
    dict(build_id="6aaf1468d96a8203de70924d", ok=11, bad=0, warn=1),
    dict(build_id="6aa3689720239ade1f0b3c7a", ok=12, bad=0, warn=0),
    dict(build_id="6aade015d96a8203de40918b", ok=10, bad=2, warn=0),
    dict(build_id="6aacc1f2d96a8203de1177aa", ok=0, bad=0, warn=0),
    dict(build_id="6aab88c0d96a8203de5512ee", ok=9, bad=0, warn=3),
]

# One line per test: how many records, the newest verdict, and the run of records
# newest-last.  `None` in the timeline is a position the ledger has nothing for.
TIMELINES = [
    dict(test="boot", runs=22, last="pass", regressions=0,
         marks=["pass"] * 8 + [None] + ["pass"] * 13),
    dict(test="kselftest-riscv", runs=19, last="incomplete", regressions=3,
         marks=["pass", "pass", "fail", "pass", None, "pass", "pass", "fail",
                "pass", "incomplete", "pass", "pass", "pass", "pass", "pass",
                "pass", "pass", "pass", "pass"]),
    dict(test="kselftest-kvm", runs=16, last="pass", regressions=0,
         marks=["pass"] * 6 + [None, None] + ["pass"] * 8),
]

# the drift view: how much a config changed, as the command that answers it
DRIFT = [
    dict(left="6aaf3175d96a8203de710e5c", right="6aaf2335d96a8203de70924d",
         added=3, removed=1, changed=2),
    dict(left="6aaf2335d96a8203de70924d", right="6aaf1468d96a8203de70924d",
         added=0, removed=0, changed=0),
]

# ------------------------------------------------------- the activity strip
# What the console started.  A running row carries a pid and no exit; an ended one
# carries both.  `worker` shows the case the /runs note is about: one row however
# many jobs the loop claimed.
ACTIVITIES = [
    dict(run_id="20260921T133948-worker", kind="worker", state="running", age="80m36s",
         what="worker: --platform qemu-riscv64 --runtime pull-labs-riscv",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/pull_worker.py --platform qemu-riscv64 --runtime pull-labs-riscv --api-url http://127.0.0.1:8001",
         exit=None),
    dict(run_id="20260921T133941-worker", kind="worker", state="done", age="0s",
         what="worker: --once --platform qemu-riscv64 --runtime pull-labs-riscv",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/pull_worker.py --once --platform qemu-riscv64 --runtime pull-labs-riscv --api-url http://127.0.0.1:8001",
         exit=0),
    dict(run_id="20260921T130919-worker", kind="worker", state="done", age="15m45s",
         what="worker: --platform qemu-riscv64 --runtime pull-labs-riscv",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/pull_worker.py --platform qemu-riscv64 --runtime pull-labs-riscv --api-url http://127.0.0.1:8001",
         exit=0),
    dict(run_id="20260920T224036-table", kind="failed", state="failed", age="41s",
         what="index: --days 0 --limit 5",
         argv="/usr/bin/python3 /home/hao/kernelci-riscv/table.py index --api-url http://127.0.0.1:8001 --days 0 --limit 5",
         exit=None),
]

# the wording under the chips, and the paths behind them
COUNTS = [
    ("cards", "53", "/home/hao/kernelci-riscv/var/state/builds.json"),
    ("here", "54", "/home/hao/kernelci-riscv/var/downloads"),
    ("bytes", "53", "an artifact is on disk here (Build.present())"),
    ("acts", "145", "every act Build.make() recorded, in var/downloads/<id>/provenance.json"),
    ("records", "60", "60 records in /home/hao/kernelci-riscv/var/results"),
    ("gap", "99", "the gap: (build, test) with no record - re.todo()"),
    ("activities", "80", "/home/hao/kernelci-riscv/var/runs"),
]

# The two APIs the switcher offers.  `datalist` in the real page lets an operator
# type a third; the prototype keeps the two named ones and says so.
APIS = [("local", "http://127.0.0.1:8001"), ("production", "https://api.kernelci.org")]

# what the filter controls offer, taken from the real page's datalists
TREES = ["mainline", "net-next", "next", "riscv", "stable", "stable-rc", "soc", "tip"]
BRANCHES = ["main", "master", "for-next", "fixes", "linux-6.12.y", "linux-6.6.y"]
ARCHES = ["riscv", "arm64", "x86_64"]
DEFCONFIGS = ["defconfig", "rv32_defconfig", "nommu_k210_defconfig", "allnoconfig"]
COMPILERS = ["gcc-14", "gcc-13", "clang-19", "clang-20"]
TESTS = ["boot", "kselftest-riscv", "kselftest-kvm"]
KINDS = ["worker", "run", "runday", "table", "fetch", "drift", "pull", "results"]
RUN_STATES = ["pass", "fail", "incomplete", "unrun"]
ORIGINS = ["any", "remote", "local"]
EVIDENCES = ["any", "bytes", "card", "absent"]
SORTS = [("date", "newest first"), ("date-asc", "oldest first"),
         ("same-branch", "same branch together"), ("verdict", "by verdict"),
         ("build", "by build id")]


def data() -> dict:
    """Every fixture in one dict: the one argument a page function takes."""
    return dict(
        builds=BUILDS, pulls=PULLS, gap=GAP, ledger=LEDGER, worker=WORKER,
        queue=QUEUE, runs=RUNS, picks=PICKS, bars=BARS, timelines=TIMELINES,
        drift=DRIFT, activities=ACTIVITIES, counts=COUNTS, apis=APIS,
        trees=TREES, branches=BRANCHES, arches=ARCHES, defconfigs=DEFCONFIGS,
        compilers=COMPILERS, tests=TESTS, kinds=KINDS, run_states=RUN_STATES,
        origins=ORIGINS, evidences=EVIDENCES, sorts=SORTS,
        drawn=time.strftime("%Y-%m-%d %H:%M:%S"), drawn_from=[
            "var/state/builds.json", "var/downloads/", "var/results/", "var/runs/",
        ],
    )
