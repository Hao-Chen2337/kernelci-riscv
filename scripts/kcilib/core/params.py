# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Test parameters shared by the pull-lab worker and the one-shot fetch path.

Both entry points run the same tuxrun invocations on the same build, so what
decides *what* is run - the curated KVM allow-list and the QEMU cpu property
string - lives here instead of in each script; --kvm-tests / --kvm-full are the
overrides.  Rationale: code-notes/W2c-kcilib.md.
"""

# The KVM selftests that behave under TCG; passed to LKFT as a TST_CASENAME
# allow-list.  The perf/stress tests measure throughput an emulator has none of
# and kvm_page_table_test hangs the job - both stay behind --kvm-full.
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

    Takes the cpu string, not a namespace, so both entry points pass their own.
    """
    if test_type == "kselftest-kvm" and "h=" not in cpu:
        cpu += ",h=true"
    return cpu


def kvm_allow_list():
    """The allow-list in the form the LKFT script wants: "kvm:name kvm:name ..."."""
    return " ".join(f"kvm:{name}" for name in KVM_TEST_SUBSET)
