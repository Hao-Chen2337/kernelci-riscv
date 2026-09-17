# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The worker's command line: the flags, their defaults, and nothing else.

Defaults come from kcilib/core/config.py, so the parser cannot drift from the
config a programmatic caller gets.  Flag order, help strings and the fact that
--min-timeout/--max-timeout is refused by parser.error() (usage on stderr, exit
2) are frozen.  Rationale: docs/code-notes/W2c-kcilib.md.
"""
import argparse

from kcilib.core import config
from kcilib.core.params import KVM_TEST_SUBSET


def build_parser():
    """The worker's ArgumentParser, defaults included."""
    parser = argparse.ArgumentParser(
        description="Run KernelCI pull_labs qemu-riscv64 jobs with tuxrun."
    )
    parser.add_argument(
        "--api-url",
        default=config.BASE_URI,
        help="KernelCI API base URL to poll for events.",
    )
    parser.add_argument(
        "--platform",
        default=config.DEFAULT_PLATFORM,
        help="tuxrun device / platform filter (default: qemu-riscv64).",
    )
    parser.add_argument(
        "--runtime",
        default=config.DEFAULT_RUNTIME,
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
        default=config.LOG_DIR,
        help=f"Where each job's tuxrun console is archived as "
        f"<node_id>.log before its workspace is removed (default: "
        f"{config.LOG_DIR}; the newest {config.LOG_ARCHIVE_KEEP} are kept).",
    )
    parser.add_argument(
        "--state-file",
        default=config.DEFAULT_STATE_FILE,
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
        default=config.DEFAULT_MAX_RETRIES,
        help="Max consecutive API retries (default: 5).",
    )
    parser.add_argument(
        "--poll-period",
        type=int,
        default=config.DEFAULT_POLL_PERIOD,
        help="Seconds between event polls (default: 30).",
    )
    parser.add_argument(
        "--tuxrun-bin",
        default=config.DEFAULT_TUXRUN,
        help="tuxrun executable (default: tuxrun).",
    )
    parser.add_argument(
        "--container-runtime",
        default=config.DEFAULT_CONTAINER_RUNTIME,
        help="podman or docker for the dispatcher image "
        "(default: podman, falling back to docker).",
    )
    parser.add_argument(
        "--cpu",
        default=config.default_cpu(),
        help="QEMU cpu properties (default: rv64,v=true,ssnpm=true; "
        "KVM jobs add ,h=true).",
    )
    parser.add_argument(
        "--rootfs",
        default=config.DEFAULT_ROOTFS,
        help="Rootfs disk URL overriding the job definition's rootfs "
        "(default: use the job definition's rootfs; tuxrun's built-in "
        "buildroot disk for boot jobs without one).",
    )
    parser.add_argument(
        "--max-timeout",
        type=int,
        default=config.DEFAULT_MAX_TIMEOUT,
        help=f"Upper bound for a job's timeout_s (default: "
        f"{config.DEFAULT_MAX_TIMEOUT}, the pull-labs runtime's own timeout).  "
        "A definition asking for more is clamped and the clamp is logged; the "
        "shell entry points pass 1200, which cuts the 1800s the kselftest "
        "template asks for.",
    )
    parser.add_argument(
        "--min-timeout",
        type=int,
        default=config.MIN_TIMEOUT,
        help=f"Lower bound for a job's timeout_s (default: "
        f"{config.MIN_TIMEOUT}).  "
        "Raising it is not enough to help: check --max-timeout too.",
    )
    parser.add_argument(
        "--max-download-mb",
        type=int,
        default=config.MAX_DOWNLOAD_MB,
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
        default=config.default_api_config_name(),
        help="api_config_name embedded in the LAVA callback "
        "definition metadata; MUST match the pipeline "
        "deployment's api config name (docker-host is "
        "the local dev compose).",
    )
    parser.add_argument(
        "--storage-config-name",
        default=config.default_storage_config_name(),
        help="storage_config_name embedded in the LAVA "
        "callback definition metadata; MUST match the "
        "pipeline deployment's storage config name.",
    )
    return parser


def parse_args(argv=None):
    """Parse the worker's command line and apply its one cross-flag check.

    A --min-timeout above --max-timeout is refused here, or clamp_timeout()
    would quietly return the floor and the "upper bound" would mean nothing.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.min_timeout > args.max_timeout:
        parser.error(
            f"--min-timeout {args.min_timeout} is above --max-timeout "
            f"{args.max_timeout}"
        )
    return args
