# SPDX-License-Identifier: LGPL-2.1-or-later
"""The test catalogue: what can be run, what it needs, what it is called on the command line.

Not a test suite - this is the list of tests *this project runs*, which both
`Build` (to answer "is this build missing something") and `Job` (to render a
definition) need.  It lives here so those two do not have to import each other.

接口形状（C++，只有声明）：include/kci/local.hpp §8 测试目录。
"""

# A test is a name, the artifacts it needs, whether the guest needs a baked
# disk, and what tuxrun is asked for:
#
#   boot            --kernel only; the kselftest tarball is not even downloaded
#   kselftest-riscv --kernel + kselftest tarball, and NO --modules (modules are
#                   a kvm-only need; passing them changes the guest's /lib/modules)
#   kselftest-kvm   --kernel + modules + kselftest, with the curated test list
#                   from the tarball minus KVM_SKIP_TESTS
TESTS = {
    "boot": {"needs": ("kernel",), "rootfs": False, "tests": (), "modules": False},
    "kselftest-riscv": {"needs": ("kernel", "kselftest"), "rootfs": True,
                        "tests": ("kselftest-riscv",), "modules": False},
    "kselftest-kvm": {"needs": ("kernel", "modules", "kselftest"), "rootfs": True,
                      "tests": ("kselftest-kvm",), "modules": True},
}

# What a run without --test covers.  All three, in this order: boot is the
# cheapest and its console is what tells a kernel problem from a test problem.
DEFAULT_TESTS = ("boot", "kselftest-riscv", "kselftest-kvm")

# The KVM tests: an EXCLUSION list, not an allow list.  The build's kselftest
# tarball decides what exists (a test an older kernel did not build simply is
# not there), and these seven are the ones that cannot pass under TCG - three
# perf, two stress, plus the two that hang or burn their whole budget.
KVM_SKIP_TESTS = (
    # perf: benchmark throughput an emulator has none of
    "access_tracking_perf_test",
    "dirty_log_perf_test",
    "memslot_perf_test",
    # stress: hammer the guest and take forever under TCG
    "memslot_modification_stress_test",
    "mmu_stress_test",
    # too slow under TCG: dirty_log_test burns its 120s per-test budget across
    # its many guest/log modes, and kvm_page_table_test hangs the job outright
    "dirty_log_test",
    "kvm_page_table_test",
    # measured 2026-09-19 on build 6aade015d96a8203de6dff37: the tarball this
    # kernel ships grew past what the list above was calibrated for.
    #   arch_timer           an aarch64 test; exits 254 here, immediately
    #   demand_paging_test   another throughput benchmark; TIMEOUT after 120s
    # A test that cannot apply to this architecture or cannot finish under
    # emulation is not a regression - but it must be named here, not discovered
    # as a red run every night.
    "arch_timer",
    "demand_paging_test",
)

# The environment these tests are run in.  It lives with the catalogue - and in
# this module rather than in `config.py` - because the catalogue imports nothing,
# so both the config and the callback body can read it without a cycle.
#
# Three names that are easy to confuse, and were confused once:
#   device             what tuxrun boots                        (qemu-riscv64)
#   lab                the pipeline runtime that dispatches to us (pull-labs-riscv):
#                      what a job node's `data.runtime` says, and what `claimable()`
#                      compares - NOT the container runtime
#   container_runtime  what tuxrun runs the dispatcher image in  (docker/podman)
DEFAULT_DEVICE = "qemu-riscv64"
DEFAULT_LAB = "pull-labs-riscv"
DEFAULT_CONTAINER_RUNTIME = "docker"

# The lab's own guest image, used when nothing else names a rootfs: the same
# pinned nfsroot tarball the production pull_labs template injects, baked to
# ext4 by `bake_rootfs()`.  A dated path, not `latest`: `latest` is a 404.
ROOTFS_URL = ("https://storage.kernelci.org/images/rootfs/debian/"
              "trixie-kselftest/20260606.0/riscv64/full.rootfs.tar.xz")


def needs(test):
    """The artifacts a test needs; an unknown name is a ConfigError, never a KeyError."""
    from . import errors
    try:
        return TESTS[test]["needs"]
    except KeyError:
        raise errors.ConfigError(
            f"unknown test {test!r}; known: {', '.join(sorted(TESTS))}") from None
