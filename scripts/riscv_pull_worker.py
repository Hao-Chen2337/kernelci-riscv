#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""RISC-V QEMU pull-lab worker for KernelCI (tuxrun engine).

Polls the events API for "available" pull_labs job nodes on qemu-riscv64,
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
  boot             -> tuxrun --device qemu-riscv64 --kernel <url> (a cpio
                      ramdisk in the job def is not bootable by the qemu
                      device; override with --rootfs).
  kselftest-<coll> -> --tests kselftest-<coll> + a rootfs disk (nfsroot
                      tar.xz baked to ext4) + --parameters KSELFTEST=<url>.

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
"rm -rf work/env/baked" clears them.

WHAT THIS FILE OWNS.  Nothing but the entry point.  Starting this file IS
starting the worker (run.sh worker, the local stack and a human all do it), and
what is left here is the four lines that read the command line and hand it to
the library:

    flags + defaults + the --min-timeout/--max-timeout check -> kcilib/cli.py
    flag -> field mapping (one place)                       -> kcilib/config.py
    run one node (no API knowledge)                         -> kcilib/jobrun.run_node
    fetch nodes from the API + the cursor + the flock       -> kcilib/poll.poll_loop

Everything a job DOES lives in scripts/kcilib/, shared with
scripts/fetch-and-run-latest.py - the judging vocabulary and the TAP/infra
verdict (judge), the tuxrun argv and its execution (runner), artifact transfer
(artifacts), the bake and its cache (bake), the LAVA callback body and its
delivery (callback), the state file (state), the test parameters (params), the
job mapping, the console archive and the run itself (jobrun), and the poll loop,
the event handling and the cursor (poll).

That split is why the flags, the printed lines, the state file bytes and the
archived consoles are what they always were: the code that produces them did
not change, only how it is configured and where it is imported from.

Full parameter and behavior reference: docs/INTERNAL-NOTES.md (internal).
"""

import os
import sys

# scripts/kcilib/ is resolved through THIS file's own directory: the worker
# runs from any CWD, and an offline test that loads it by path (as
# scripts/verify-worker-guards.py used to) still finds the library.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from kcilib import cli, config
from kcilib.jobrun import run_node
from kcilib.poll import poll_loop


def main():
    """Parse the CLI, build the two configs, and drive the poll loop.

    The loop is handed the run function and its config instead of reaching for
    them, so kcilib.poll is the only layer that knows the events API exists and
    kcilib.jobrun.run_node never learns that it was called by a poller.
    """
    args = cli.parse_args()
    configs = config.from_args(args)
    poll_loop(configs.poll, run_node, configs.run)


if __name__ == "__main__":
    main()
