# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Test parameters shared by the pull-lab worker and the one-shot fetch path.

Both entry points run the same tuxrun invocations on the same build, so what
decides *what* is run - the KVM exclusion list and the QEMU cpu property
string - lives here instead of in each script; --kvm-tests / --kvm-full are the
overrides.  Rationale: docs/code-notes/W2c-kcilib.md.
"""

# KVM selftests the local stack excludes; everything else the build shipped runs
# (exclusion, matching production's whole-collection-minus-skipfile shape in
# PR #1599).  The perf/stress tests benchmark throughput an emulator has none of,
# and a few functional tests are too slow or hang under TCG - all stay behind
# --kvm-full.  The "run everything else" set is derived from the build's own
# kselftest tarball
# (kcilib.run.artifacts.kselftest_kvm_tests), so a name an older kernel never
# built is simply absent - no "No such test" failure, unlike a fixed allow-list.
KVM_SKIP_TESTS = frozenset({
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
})


def cpu_for(cpu, test_type):
    """CPU property string; KVM jobs need the H extension enabled.

    Takes the cpu string, not a namespace, so both entry points pass their own.
    """
    if test_type == "kselftest-kvm" and "h=" not in cpu:
        cpu += ",h=true"
    return cpu


def kvm_tests_to_run(present):
    """The kvm tests to run: everything *present* (the build's own kselftest
    tarball names) minus the exclusion list, sorted so the argv is stable."""
    return sorted(set(present) - KVM_SKIP_TESTS)
