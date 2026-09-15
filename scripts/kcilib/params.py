# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Test parameters shared by the pull-lab worker and the one-shot fetch path.

These two entry points run the same tuxrun invocations on the same build, so the
things that decide *what* is run - the curated KVM allow-list and the QEMU cpu
property string - live here rather than being copied into each script.  They were
moved out of riscv_pull_worker.py unchanged; the worker keeps its --kvm-tests and
--kvm-full flags as the overrides.
"""

# The KVM selftests that behave under TCG.  The perf/stress tests in the same
# collection (demand_paging, access_tracking_perf, dirty_log_perf and friends)
# measure throughput, which has no meaning on an emulator, and
# kvm_page_table_test hangs the job - all of them are deliberately excluded
# (verified in the real loop) - they stay available via --kvm-full/--kvm-tests.
# Passed to the LKFT script as a TST_CASENAME allow-list ("kvm:name ...").
# Override with --kvm-tests / --kvm-full.
KVM_TEST_SUBSET = [
    "set_memory_region_test",
    "kvm_create_max_vcpus",
    "kvm_binary_stats_test",
    "ebreak_test",
    "guest_print_test",
    "steal_time",
    "sbi_pmu_test",
    "irqfd_test",
]


def cpu_for(cpu, test_type):
    """CPU property string; KVM jobs need the H extension enabled.

    Takes the cpu string rather than an argparse namespace so both entry points
    can use it with their own --cpu default.
    """
    if test_type == "kselftest-kvm" and "h=" not in cpu:
        cpu += ",h=true"
    return cpu


def kvm_allow_list():
    """The allow-list in the form the LKFT script wants: "kvm:name kvm:name ..."."""
    return " ".join(f"kvm:{name}" for name in KVM_TEST_SUBSET)
