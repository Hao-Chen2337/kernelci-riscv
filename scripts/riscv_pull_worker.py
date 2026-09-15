#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""RISC-V QEMU pull-lab worker for KernelCI (tuxrun engine).

Polls the events API for ``available`` pull_labs job nodes on qemu-riscv64,
executes each with tuxrun inside the linaro/tuxrun-dispatcher container, and
posts the result back as a **LAVA-compatible callback body** - the only format
the pipeline's callback endpoint (lava_callback.py + kernelci.runtime.lava.Callback)
ingests; there is no server-side parser for the PULL_LABS protocol body, so any
other format would silently lose the result.

Judging rule: tuxrun exits 0 even when selftests fail, so results come from
parsing the TAP lines (tap_summary); infra failures (bad flags, unreachable
artifacts, timeouts) are reported as incomplete + Infrastructure, never as a
test result.  Protocol robustness: state cursor, seen-node dedup, flock,
callback retries, and unposted results persisted across runs (re-posted,
never re-run).

The persisted cursor is authoritative: --since only seeds a state file that has
no cursor yet (--ignore-state-cursor forces it).  Every event's seen/pending
change is flushed to the state file immediately, a SIGTERM flushes before
exiting, and each job's tuxrun console is archived to work/logs/<node_id>.log
before its workspace is deleted, so a real run's evidence outlives the job.

Job mapping (rendered by config/runtime/*-pull-labs.jinja2):
  boot             -> ``tuxrun --device qemu-riscv64 --kernel <url>`` (a cpio
                      ramdisk in the job def is not bootable by the qemu
                      device; override with --rootfs).
  kselftest-<coll> -> ``--tests kselftest-<coll>`` + a rootfs disk (nfsroot
                      tar.xz baked to ext4) + ``--parameters KSELFTEST=<url>``.

Known gaps: kselftest-riscv needs the tuxlava class from
config/tuxlava-kselftest-riscv.patch (without it tuxrun exits 2 -> infra);
kselftest-kvm runs the curated KVM_TEST_SUBSET with kvm.ko loaded at boot
(modules.tar.xz baked into the ext4 image + modules-load.d conf);
--api-config-name / --storage-config-name must match the deployment or the
callback cannot find the node.

Baked guest images are cached in work/env/baked/ keyed on the bake inputs
(rootfs URL + modules URL + modules-load.d list + DISK_SIZE), so the second
job with the same inputs skips a ~144MB download and a 4GB mkfs.ext4; each
entry is ~4GB (sparse), at most BAKE_CACHE_MAX_ENTRIES are kept, and
`rm -rf work/env/baked` clears them.

WHAT THIS FILE OWNS.  What is left here is the worker's interface: the flags,
their defaults and the environment-derived config (--cpu, --api-config-name,
--storage-config-name).  Everything a job DOES lives in scripts/kcilib/,
shared with scripts/fetch-and-run-latest.py - the judging vocabulary and the
TAP/infra verdict (judge), the tuxrun argv and its execution (runner),
artifact transfer (artifacts), the bake and its cache (bake), the LAVA
callback body and its delivery (callback), the state file (state), the test
parameters (params), the job mapping and the console archive (jobrun), and the
poll loop, the event handling and the cursor (poll).  That split is why the
flags, the printed lines, the state file bytes and the archived consoles are
what they always were: the code that produces them did not change, only where
it is imported from.

Full parameter and behavior reference: docs/INTERNAL-NOTES.md (internal).
"""

import argparse
import os
import sys

# scripts/kcilib/ is resolved through THIS file's own directory: the worker
# runs from any CWD, and an offline test that loads it by path (as
# scripts/verify-worker-guards.py used to) still finds the library.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from kcilib.jobrun import LOG_ARCHIVE_KEEP, MIN_TIMEOUT
from kcilib.params import KVM_TEST_SUBSET
from kcilib.poll import poll_loop

BASE_URI = "https://api.kernelci.org"
# Ceiling for a job definition's timeout_s, matching the pull-labs runtime's
# own timeout.  Its floor is kcilib.jobrun.MIN_TIMEOUT (below it tuxrun cannot
# even boot a guest); kcilib.jobrun.clamp_timeout() applies both and announces
# every clamp, and --min-timeout above --max-timeout is refused by main()
# below - otherwise clamp_timeout() would quietly return the floor and the
# "upper bound" would mean nothing.  The clamp used to be a silent max(60,
# min(timeout_s, args.max_timeout)): a definition asking for 1800s was cut to
# the 1200s the shell entry points pass, the job was killed at 20 minutes and
# reported as Infrastructure with nothing in the log saying the timeout had
# been reduced.
DEFAULT_MAX_TIMEOUT = 7200
# Where the per-job tuxrun console is archived before its workspace is removed
# (#6): the console is written inside the workspace and the workspace is
# deleted at the end of every job, so the only local copy of a real run used to
# disappear with it - all that survived was the callback's LOG_LIMIT-capped
# copy, and nothing at all when the callback failed.  Anchored to the
# repository root rather than the CWD, so "the logs are in work/logs" holds
# whatever directory the worker was started from (work/ is the gitignored tree
# this repo already treats as durable).
LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "logs"
)


def main():
    parser = argparse.ArgumentParser(
        description="Run KernelCI pull_labs qemu-riscv64 jobs with tuxrun."
    )
    parser.add_argument(
        "--api-url",
        default=BASE_URI,
        help="KernelCI API base URL to poll for events.",
    )
    parser.add_argument(
        "--platform",
        default="qemu-riscv64",
        help="tuxrun device / platform filter (default: qemu-riscv64).",
    )
    parser.add_argument(
        "--runtime",
        default="pull-labs-riscv",
        help="Filter jobs by runtime/lab name (default: pull-labs-riscv).",
    )
    parser.add_argument(
        "--output-dir",
        help="Place per-job workspaces under this directory "
        "(cleaned unless --keep-workspace is given).",
    )
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Do not remove per-job workspaces.  The tuxrun console is "
        "archived to --log-dir either way.",
    )
    parser.add_argument(
        "--log-dir",
        default=LOG_DIR,
        help=f"Where each job's tuxrun console is archived as "
        f"<node_id>.log before its workspace is removed (default: "
        f"{LOG_DIR}; the newest {LOG_ARCHIVE_KEEP} are kept).",
    )
    parser.add_argument(
        "--state-file",
        default="riscv-pull-worker-state.json",
        help="Persist cursor + processed node ids + unposted result "
        "bodies here (unposted results are re-posted on the next run "
        "without re-running tuxrun).",
    )
    parser.add_argument(
        "--since",
        help="Bootstrap poll cursor (ISO-8601).  Used only when the state "
        "file has no cursor yet: the persisted cursor is authoritative, "
        "so a restart does not silently skip jobs that arrived while the "
        "worker was down.  Pass --ignore-state-cursor to force this value.",
    )
    parser.add_argument(
        "--ignore-state-cursor",
        action="store_true",
        help="Use --since instead of the cursor stored in --state-file "
        "(re-scans from that timestamp and may re-poll seen events).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Max consecutive API retries (default: 5).",
    )
    parser.add_argument(
        "--poll-period",
        type=int,
        default=30,
        help="Seconds between event polls (default: 30).",
    )
    parser.add_argument(
        "--tuxrun-bin",
        default="tuxrun",
        help="tuxrun executable (default: tuxrun).",
    )
    parser.add_argument(
        "--container-runtime",
        default="",
        help="podman or docker for the dispatcher image "
        "(default: podman, falling back to docker).",
    )
    parser.add_argument(
        "--cpu",
        default=os.environ.get("QEMU_CPU", "rv64,v=true,ssnpm=true"),
        help="QEMU cpu properties (default: rv64,v=true,ssnpm=true; "
        "KVM jobs add ,h=true).",
    )
    parser.add_argument(
        "--rootfs",
        default="",
        help="Rootfs disk URL overriding the job definition's rootfs "
        "(default: use the job definition's rootfs; tuxrun's built-in "
        "buildroot disk for boot jobs without one).",
    )
    parser.add_argument(
        "--max-timeout",
        type=int,
        default=DEFAULT_MAX_TIMEOUT,
        help=f"Upper bound for a job's timeout_s (default: "
        f"{DEFAULT_MAX_TIMEOUT}, the pull-labs runtime's own timeout).  A "
        "definition asking for more is clamped and the clamp is logged; the "
        "shell entry points pass 1200, which cuts the 1800s the kselftest "
        "template asks for.",
    )
    parser.add_argument(
        "--min-timeout",
        type=int,
        default=MIN_TIMEOUT,
        help=f"Lower bound for a job's timeout_s (default: {MIN_TIMEOUT}).  "
        "Raising it is not enough to help: check --max-timeout too.",
    )
    parser.add_argument(
        "--max-download-mb",
        type=int,
        default=4096,
        dest="max_download_size",
        help="Max download size in MiB (default: 4096).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process the currently available jobs once and exit "
        "(one-shot local loop test), instead of polling forever.",
    )
    parser.add_argument(
        "--kvm-full",
        action="store_true",
        help="Run the whole kvm collection (no TST_CASENAME allow-list). "
        "perf/stress time out under TCG; timeouts are reported as "
        "incomplete, never fail. Default: curated 8-test subset.",
    )
    parser.add_argument(
        "--kvm-tests",
        nargs="+",
        default=KVM_TEST_SUBSET,
        metavar="NAME",
        help="Curated kvm selftest names run via the LKFT "
        "TST_CASENAME allow-list (default: the 8 tests "
        "in KVM_TEST_SUBSET).  kvm.ko is loaded at boot "
        "through the modules-load.d conf baked into "
        "tar.xz rootfs; with a pre-built ext4 rootfs "
        "the image must load kvm itself.",
    )
    parser.add_argument(
        "--api-config-name",
        default=os.environ.get("KCI_API_CONFIG_NAME", "docker-host"),
        help="api_config_name embedded in the LAVA callback "
        "definition metadata; MUST match the pipeline "
        "deployment's api config name (docker-host is "
        "the local dev compose).",
    )
    parser.add_argument(
        "--storage-config-name",
        default=os.environ.get("KCI_STORAGE_CONFIG_NAME", "docker-host"),
        help="storage_config_name embedded in the LAVA "
        "callback definition metadata; MUST match the "
        "pipeline deployment's storage config name.",
    )
    args = parser.parse_args()
    if args.min_timeout > args.max_timeout:
        # Otherwise clamp_timeout() would quietly return the floor and the
        # "upper bound" would mean nothing.
        parser.error(
            f"--min-timeout {args.min_timeout} is above --max-timeout "
            f"{args.max_timeout}"
        )
    args.max_download_size = args.max_download_size << 20
    poll_loop(args)


if __name__ == "__main__":
    main()
