# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The worker's two config objects - and the ONE place CLI -> config.

Phase 4's last layer: the library used to read a 23-field argparse Namespace -
every module reached into the parsed command line for its own settings - which
meant every module knew that the worker is a command line, and the poll loop
knew the shape of the run configuration as well.  Two small dataclasses replace
that namespace:

* RunConfig is everything ONE RUN needs - the tuxrun executable, the device, the
  guest images, the workspace and console-archive directories, the timeout
  bounds, the KVM selection - and nothing about the API.  jobrun.run_node(node,
  run_config) can therefore be called by a caller that has never heard of the
  events API.
* PollConfig is the API side: where to poll, how often, how hard to retry, where
  the cursor lives, and which jobs this worker claims (platform / runtime).
  poll.poll_loop(poll_config, run_node, run_config) owns it.

from_args() is the only place an argparse Namespace is read, so "which flag
lands in which field" is one screen of code a reviewer (and the guard tests) can
check in one look.  Programmatic callers - a test, or the one-shot runner - build
the dataclasses directly: scripts/fetch-and-run-latest.py now builds a RunConfig
in its main() and reads the run-scoped fields (tuxrun_bin, cpu, kvm_full,
container_runtime, rootfs, output_dir) from it, instead of reaching into its own
argparse namespace at the point of use.  What it keeps in that namespace is its
deployment business (which build to fetch, which port to serve it on, whether to
provision only), which is not part of "one run".

DELIBERATELY NOT A FIELD: RunConfig.runtime.  --runtime is the *lab* filter (the
events API's data.runtime, "pull-labs-riscv"), which is the poll layer's
business and lives in PollConfig; the runtime tuxrun is told to use
(podman/docker) is RunConfig.container_runtime.  One name for two meanings would
be worse than the missing field, so the container runtime keeps its own name
(and jobrun.runtime_name() still auto-detects podman, then docker, when it is
empty - exactly as before).

The defaults below ARE the CLI defaults: kcilib/core/cli.py builds its parser from
them, so the flags, their help text and their values cannot drift away from the
config a programmatic caller gets.  The environment-derived ones (QEMU_CPU,
KCI_API_CONFIG_NAME, KCI_STORAGE_CONFIG_NAME) are default_factory functions,
read when a config is built - the same moment the old argparse defaults were
evaluated.
"""
import os
from dataclasses import dataclass, field
from typing import NamedTuple

from kcilib import repo_root
from kcilib.core.params import KVM_TEST_SUBSET
from kcilib.run.jobrun import LOG_ARCHIVE_KEEP, MIN_TIMEOUT

__all__ = [
    "BASE_URI", "DEFAULT_MAX_TIMEOUT", "DEFAULT_PLATFORM", "DEFAULT_RUNTIME",
    "DEFAULT_STATE_FILE", "LOG_ARCHIVE_KEEP", "LOG_DIR", "MAX_DOWNLOAD_MB",
    "MIN_TIMEOUT", "Configs", "PollConfig", "RunConfig", "from_args",
]

# The repository root, not the CWD: work/ is the durable tree this repo already
# has, and "the logs are in work/logs" must hold whatever directory the worker
# was started from.  kcilib.repo_root() walks up to run.sh; counting dirname()
# levels pointed at scripts/ as soon as this module moved into core/.
REPO_ROOT = repo_root()
LOG_DIR = os.path.join(REPO_ROOT, "work", "logs")

BASE_URI = "https://api.kernelci.org"
DEFAULT_PLATFORM = "qemu-riscv64"
DEFAULT_RUNTIME = "pull-labs-riscv"
DEFAULT_TUXRUN = "tuxrun"
DEFAULT_STATE_FILE = "riscv-pull-worker-state.json"
# Ceiling for a job definition's timeout_s, matching the pull-labs runtime's own
# timeout; its floor is kcilib.run.jobrun.MIN_TIMEOUT, which below cannot even boot
# a guest.  The CLI refuses --min-timeout above --max-timeout
# (cli.parse_args), so both bounds keep meaning something.
DEFAULT_MAX_TIMEOUT = 7200
DEFAULT_MIN_TIMEOUT = MIN_TIMEOUT
MAX_DOWNLOAD_MB = 4096
DEFAULT_POLL_PERIOD = 30
DEFAULT_MAX_RETRIES = 5
DEFAULT_CONTAINER_RUNTIME = ""
DEFAULT_ROOTFS = ""
DEFAULT_CPU = "rv64,v=true,ssnpm=true"
DEFAULT_API_CONFIG_NAME = "docker-host"
DEFAULT_STORAGE_CONFIG_NAME = "docker-host"


def default_cpu():
    """QEMU cpu properties, overridable from the environment (--cpu)."""
    return os.environ.get("QEMU_CPU", DEFAULT_CPU)


def default_api_config_name():
    """api_config_name for the callback definition metadata (--api-config-name)."""
    return os.environ.get("KCI_API_CONFIG_NAME", DEFAULT_API_CONFIG_NAME)


def default_storage_config_name():
    """storage_config_name for the callback metadata (--storage-config-name)."""
    return os.environ.get("KCI_STORAGE_CONFIG_NAME",
                          DEFAULT_STORAGE_CONFIG_NAME)


@dataclass
class RunConfig:
    """Everything one run of a node needs; nothing about the API.

    max_download_size is in BYTES (the unit kcilib.run.artifacts and kcilib.run.bake
    take); the CLI flag is --max-download-mb and from_args() does the shift.
    """

    tuxrun_bin: str = DEFAULT_TUXRUN
    platform: str = DEFAULT_PLATFORM
    cpu: str = field(default_factory=default_cpu)
    container_runtime: str = DEFAULT_CONTAINER_RUNTIME
    rootfs: str = DEFAULT_ROOTFS
    output_dir: str | None = None
    log_dir: str | None = LOG_DIR
    max_timeout: int = DEFAULT_MAX_TIMEOUT
    min_timeout: int = DEFAULT_MIN_TIMEOUT
    max_download_size: int = MAX_DOWNLOAD_MB << 20
    # The same list object argparse's --kvm-tests defaults to; build_command()
    # copies it and nobody mutates it.
    kvm_tests: list = field(default_factory=lambda: KVM_TEST_SUBSET)
    kvm_full: bool = False
    keep_workspace: bool = False
    api_config_name: str = field(default_factory=default_api_config_name)
    storage_config_name: str = field(
        default_factory=default_storage_config_name)


@dataclass
class PollConfig:
    """The API side of the worker: what to poll, how often, and which jobs.

    platform/runtime are the event filters (a job whose data.platform /
    data.runtime differs is skipped); None or "" means "claim everything".
    """
    api_url: str = BASE_URI
    state_file: str = DEFAULT_STATE_FILE
    since: str | None = None
    once: bool = False
    poll_period: int = DEFAULT_POLL_PERIOD
    max_retries: int = DEFAULT_MAX_RETRIES
    ignore_state_cursor: bool = False
    platform: str | None = DEFAULT_PLATFORM
    runtime: str | None = DEFAULT_RUNTIME


class Configs(NamedTuple):
    """The pair the worker entry point drives: run and poll."""
    run: RunConfig
    poll: PollConfig


def from_args(args):
    """Map a parsed argparse Namespace onto (RunConfig, PollConfig).

    THE one place CLI -> config.  Every field is listed explicitly, so a flag
    that quietly stops reaching the library is visible here instead of being
    swallowed by a namespace; scripts/tools/verify-worker-guards.py drives this
    function too, so the mapping is a tested thing and not a claim.

    The --max-download-mb -> bytes shift lives here (it used to be the worker's
    main()), and the --min-timeout/--max-timeout sanity check stays in
    kcilib.core.cli.parse_args() so it keeps printing argparse's usage and exiting 2.
    """
    return Configs(
        run=RunConfig(
            tuxrun_bin=args.tuxrun_bin,
            platform=args.platform,
            cpu=args.cpu,
            container_runtime=args.container_runtime,
            rootfs=args.rootfs,
            output_dir=args.output_dir,
            log_dir=args.log_dir,
            max_timeout=args.max_timeout,
            min_timeout=args.min_timeout,
            max_download_size=args.max_download_size << 20,
            kvm_tests=args.kvm_tests,
            kvm_full=args.kvm_full,
            keep_workspace=args.keep_workspace,
            api_config_name=args.api_config_name,
            storage_config_name=args.storage_config_name,
        ),
        poll=PollConfig(
            api_url=args.api_url,
            state_file=args.state_file,
            since=args.since,
            once=args.once,
            poll_period=args.poll_period,
            max_retries=args.max_retries,
            ignore_state_cursor=args.ignore_state_cursor,
            platform=args.platform,
            runtime=args.runtime,
        ),
    )
