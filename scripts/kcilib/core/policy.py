# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The one owner of every "how many / how big / how long" decision here.

Why: one table, because these numbers sat in three files in three units (5
builds, 3 baked images, 200 consoles), the ledger's retention had no owner at
all, and the 4 GiB download ceiling had two spellings that could drift.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

__all__ = ["POLICY", "Policy"]


@dataclass(frozen=True)
class Policy:
    """One field per decision, unit in the name, value copied from its owner."""

    # --- how many of each thing is kept: the four retention policies ---
    # builds: newest 5 of work/downloads plus the one build.env records and
    # work/serve/Image serves (retention.DEFAULT_KEEP); ~45 MB each and a daily
    # fetch loop is ~16 GB a year, so the count is what bounds the directory.
    downloads_keep: int = 5
    # files: newest 200 archived consoles in work/logs (config.LOG_ARCHIVE_KEEP);
    # consoles are hundreds of KB and a resident lab runs hundreds of jobs a month.
    console_logs_keep: int = 200
    # entries: baked guest images in the bake cache (bake.BAKE_CACHE_MAX_ENTRIES);
    # each entry is a whole 4 GiB image, and three cover the real input sets
    # (no modules, modules, another rootfs).
    baked_images_keep: int = 3
    # records: NOT kept at all, on purpose and not by omission - work/results is
    # the lab's history, not a cache, ./run.sh prune never touches it, and this
    # field exists so that "never prune the ledger" is a stated policy rather
    # than an unowned absence. None means unbounded; 0 would mean delete all.
    ledger_keep: None = None

    # --- sizes ---
    # bytes: the ext4 guest image mkfs.ext4 -d writes (bake.DISK_SIZE "4G", via
    # bake.disk_size_bytes()); unrelated to QEMU memory.
    bytes_baked_image: int = 4 << 30
    # bytes: ONE download ceiling. config.MAX_DOWNLOAD_MB (4096 MiB) and
    # artifacts.MAX_DOWNLOAD_SIZE (4 << 30) are this same number in two units -
    # the bake path defaults to one and the worker passes the other, so a drift
    # between them would silently give the two paths different limits.
    bytes_max_download: int = 4 << 30
    # bytes: log text embedded in a callback body (callback.LOG_LIMIT); the
    # console is millions of bytes and the body is POSTed.
    bytes_max_callback_log: int = 2 << 20

    # --- durations ---
    # seconds: floor a job's timeout_s is raised to (config.MIN_TIMEOUT, ==
    # DEFAULT_MIN_TIMEOUT); below 60 tuxrun cannot even boot a guest.
    seconds_min_job_timeout: int = 60
    # seconds: ceiling a job's timeout_s is clamped to (config.DEFAULT_MAX_TIMEOUT),
    # the pull-labs runtime's own timeout.  run.sh's 1200 is a caller override.
    seconds_max_job_timeout: int = 7200
    # seconds: the timeout a test gets when seconds_test_timeouts has no entry for
    # it (jobspec.JobSpec.__post_init__'s inline fallback).
    seconds_test_timeout_default: int = 1800
    # seconds per test: boot only starts the kernel, the two kselftest sets are
    # long runs (jobspec.TEST_TIMEOUTS, where the inline 1800 also appears).
    seconds_test_timeouts: Mapping[str, int] = MappingProxyType({
        "boot": 600,
        "kselftest-riscv": 1800,
        "kselftest-kvm": 1800,
    })
    # seconds: how long one tuxrun run may take (judge.TUXRUN_TIMEOUT, the value
    # fetch-and-run-latest.py passes and the verdict message quotes, so the
    # message cannot name a second timeout).
    seconds_tuxrun_timeout: int = 1800
    # seconds: the gap between two reads of ONE artifact, not a total budget
    # (artifacts.DOWNLOAD_TIMEOUT) - a slow-but-moving download is not killed.
    seconds_artifact_read_timeout: int = 60
    # seconds: one HTTP request to the KernelCI API (callback.REQUEST_TIMEOUT;
    # kcilib.run.poll and kcilib/api.py hold their own copies of the same 60 for
    # the same purpose - one quantity, so one field here).
    seconds_http_request_timeout: int = 60
    # seconds: how long a killed bake's .tmp is ignored before the cache ages it
    # out (bake.BAKE_CACHE_TMP_AGE_S).
    seconds_bake_tmp_age: int = 3600
    # seconds between event polls of the worker's own loop (config.DEFAULT_POLL_PERIOD).
    seconds_poll_period: int = 30
    # retries: consecutive API failures tolerated before a poll gives up
    # (config.DEFAULT_MAX_RETRIES).
    poll_retries_max: int = 5

    # --- what this deployment runs as: the CLI flag defaults ---
    # the platform name: config.DEFAULT_PLATFORM (--platform, and the poll filter)
    # and jobspec.PLATFORM (environment.platform of every definition) are one
    # platform, so the table spells it once.
    platform: str = "qemu-riscv64"
    # the guest architecture in every definition's environment (jobspec.ARCH).
    arch: str = "riscv"
    # the lab filter: config.DEFAULT_RUNTIME, the runtime the claimed jobs carry.
    runtime: str = "pull-labs-riscv"
    # QEMU cpu properties (config.DEFAULT_CPU, --cpu, overridable by $QEMU_CPU);
    # KVM jobs append ,h=true.
    cpu: str = "rv64,v=true,ssnpm=true"
    # the tuxrun executable the runner invokes (config.DEFAULT_TUXRUN, --tuxrun-bin).
    tuxrun_bin: str = "tuxrun"
    # podman or docker for the dispatcher image; "" = detect
    # (config.DEFAULT_CONTAINER_RUNTIME, --container-runtime).
    container_runtime: str = ""
    # --rootfs: "" = use the definition's rootfs, and tuxrun's built-in buildroot
    # disk for a boot job that has none (config.DEFAULT_ROOTFS).
    rootfs_override: str = ""
    # the guest rootfs the offline table boots from: the pinned nfsroot tar.xz the
    # production pull_labs template injects as "rootfs" (jobspec.ROOTFS_URL).
    rootfs_url: str = (
        "https://storage.kernelci.org/images/rootfs/debian/"
        "trixie-kselftest/20260606.0/riscv64/full.rootfs.tar.xz"
    )
    # callback definition metadata: MUST match the pipeline deployment's config
    # names (config.DEFAULT_API_CONFIG_NAME / DEFAULT_STORAGE_CONFIG_NAME).
    api_config_name: str = "docker-host"
    storage_config_name: str = "docker-host"
    # the address a host-port probe binds by default (ports.DEFAULT_HOST); the
    # local stack passes "0.0.0.0" because that is what it binds.
    host: str = "127.0.0.1"
    # the compose project this deployment owns, exempt from its own port check
    # (ports.DEFAULT_COMPOSE_PROJECT).
    compose_project: str = "kcirv"
    # Deliberately absent, because they are not policy: endpoints (config.BASE_URI,
    # $KCI_API_URL) and paths (config.LOG_DIR, DEFAULT_STATE_FILE, --output-dir,
    # $KCI_RESULTS_DIR, $KCI_BAKE_CACHE_DIR) belong to config and layout;
    # the remaining flags default to None/False (--since, --kvm-tests, --once),
    # and "ask for nothing" is not a number this table can own.
    # See docs/REFACTOR-D-BRIEF.md 1.4 and 2.2.


# The defaults as a frozen singleton: environment overrides still live with the
# module that reads the variable (bake_cache_dir, default_cpu, ...), because
# baking them in here would freeze them at import and two readers would then
# disagree.  Phase 1 moves those readers onto this table.
POLICY = Policy()

