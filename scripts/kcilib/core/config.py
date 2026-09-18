# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The worker's two config objects - and the ONE place CLI -> config.

RunConfig is everything ONE RUN needs and nothing about the API; PollConfig is
the API side - where to poll, how often, where the cursor lives and which jobs
this worker claims.  from_args() is the only place an argparse Namespace is
read, so "which flag lands in which field" is one screen a reviewer and the
guard tests can check.  The defaults below ARE the CLI defaults; the
environment-derived ones are default_factory functions.
Rationale: docs/code-notes/W2c-kcilib.md.
"""
import os
from dataclasses import dataclass, field
from typing import NamedTuple

from kcilib import repo_root
from kcilib.core import layout
from kcilib.core.policy import POLICY

__all__ = [
    "BASE_URI", "DEFAULT_MAX_TIMEOUT", "DEFAULT_PLATFORM", "DEFAULT_RUNTIME",
    "DEFAULT_STATE_FILE", "LOG_ARCHIVE_KEEP", "LOG_DIR", "MAX_DOWNLOAD_MB",
    "MIN_TIMEOUT", "Configs", "PollConfig", "RunConfig", "from_args",
]

# The floor a job's timeout_s is raised to, and the console-archive cap.  They
# live next to the defaults and the flags that carry them because core/ is what
# every line stands on: they used to be defined in kcilib.run.jobrun, so this
# module imported the run layer - the one inverted edge (core -> run) of the
# dependency table, and the reason "does core depend on the execution layer?" had
# a yes answer.  kcilib.run.jobrun imports them from here and keeps re-exporting
# the same names, so jobrun.MIN_TIMEOUT / jobrun.LOG_ARCHIVE_KEEP still resolve.
# The numbers themselves are NOT decided here any more: they are read from
# core.policy, the one owner of "how many / how big / how long" (the values are
# unchanged; only their source is).  Re-exporting the same names is what keeps
# jobrun's re-export and the guards that read them working.
MIN_TIMEOUT = POLICY.seconds_min_job_timeout  # floor: below this tuxrun cannot even boot a guest
LOG_ARCHIVE_KEEP = POLICY.console_logs_keep  # newest archived consoles kept in LOG_DIR

# The repository root, not the CWD, so "the logs are in work/logs" holds
# whatever directory the worker was started from.
REPO_ROOT = repo_root()
LOG_DIR = os.fspath(layout.logs())

BASE_URI = "https://api.kernelci.org"
DEFAULT_PLATFORM = POLICY.platform
DEFAULT_RUNTIME = POLICY.runtime
DEFAULT_TUXRUN = POLICY.tuxrun_bin
DEFAULT_STATE_FILE = "riscv-pull-worker-state.json"
# Ceiling for a job definition's timeout_s, matching the pull-labs runtime's own
# timeout; the floor is MIN_TIMEOUT above.
DEFAULT_MAX_TIMEOUT = POLICY.seconds_max_job_timeout
DEFAULT_MIN_TIMEOUT = MIN_TIMEOUT
MAX_DOWNLOAD_MB = POLICY.bytes_max_download >> 20
DEFAULT_POLL_PERIOD = POLICY.seconds_poll_period
DEFAULT_MAX_RETRIES = POLICY.poll_retries_max
DEFAULT_CONTAINER_RUNTIME = POLICY.container_runtime
DEFAULT_ROOTFS = POLICY.rootfs_override
DEFAULT_CPU = POLICY.cpu
DEFAULT_API_CONFIG_NAME = POLICY.api_config_name
DEFAULT_STORAGE_CONFIG_NAME = POLICY.storage_config_name


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

    max_download_size is in BYTES; --max-download-mb is shifted in from_args().
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
    # argparse's --kvm-tests override; None means "everything the build shipped
    # minus the exclusion list" (kcilib.core.params.kvm_tests_to_run).
    kvm_tests: list | None = None
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

    THE one place CLI -> config: every field is listed explicitly, so a flag
    that stops reaching the library is visible here.  The --max-download-mb ->
    bytes shift lives here; the timeout sanity check stays in
    kcilib.core.cli.parse_args().
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
