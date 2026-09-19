# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The one-shot line: fetch the newest production riscv kbuild and run it locally.

Not a second run path.  This module owns the command line, the choice of build,
the console this line has always printed and the exit status it has always
returned - and nothing else: the run itself is one Job.run() call
(kcilib.model.jobs), which is the same executor the worker and the local table
use.  The entry point scripts/fetch-and-run-latest.py is a shell over main().

Rationale: docs/ARCHITECTURE.md, docs/code-notes in docs/archive/code-notes/.
"""

import argparse
import json
import os
import shlex
import shutil
import sys
import time

from kcilib import repo_root
from kcilib.core import config, layout, policy
from kcilib.model import (
    DELIVERY_LOCAL_SERVER,
    SOURCE_FETCH,
    Builds,
    Job,
    KbuildPuller,
    KernelCINode,
)
from kcilib.run import delivery, judge

API = "https://api.kernelci.org"
JOB = "kbuild-gcc-14-riscv"
# The --test choices, in the order --help lists them (sorted).
TESTS = ("boot", "kselftest-kvm", "kselftest-riscv")

TUXRUN = os.environ.get("TUXRUN_BIN", shutil.which("tuxrun")
                        or os.path.expanduser("~/.local/bin/tuxrun"))

# Repository layout; work/ is gitignored.  ROOT/WORK_ENV/WORK_SERVE are
# kcilib.run.delivery's: the manifest of what was downloaded and the serve
# directory are its business, so the layout is spelled once, there.
ROOT = delivery.ROOT
WORK_ENV = delivery.WORK_ENV
WORK_SERVE = delivery.WORK_SERVE
DEFAULT_IMAGE = os.path.join(WORK_ENV, "Image")
DEFAULT_SERVE_IMAGE = os.path.join(WORK_SERVE, "Image")

# Rootfs for --provision-only (./run.sh provision).  Kernel and modules are NOT
# pinned here but discovered from the newest production kbuild node: storage
# prunes old builds (a pinned hash served modules.tar.xz but 404'd on its Image).
# The URL has one owner - the artifact the job definitions carry themselves.

# The verdict vocabulary is kcilib.run.judge's - exit statuses (0 pass, 1 test
# failure, 3 infrastructure), the TAP parser, the timeout detail and the boot
# evidence - so this record and the worker's callback are one verdict.



def newest_node(job: str, api: str) -> KernelCINode:
    """The newest done/pass kbuild node of *job*, or exit 1 when there is none.

    The API pages old-first, so the window widens 3 -> 7 -> 30 -> 180 days: an
    empty page is not "no build".  kci.KbuildPuller asks the API (the same
    filters this line has always sent); the done/pass filter --job has to keep
    and the newest-by-created pick are this line's.
    """
    puller = KbuildPuller(api)
    for days in (3, 7, 30, 180):
        since = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.gmtime(time.time() - days * 86400))
        found = [node for node in puller.find(kind="kbuild", name=job,
                                              created__gte=since, limit=200)
                 if node.state == "done" and node.result == "pass"]
        if found:
            return max(found, key=lambda node: node.created)
    sys.exit(f"no passing kbuild nodes for {job}")


def revision_of(node: KernelCINode) -> dict:
    """The node's data.kernel_revision as the API served it ({} when it has none).

    build.env needs version, patchlevel and commit_tags and the ledger records
    the whole revision (dashboard.py reads commit and branch out of it); a
    build card keeps only what running a test needs of a build, so this reads
    the node the way this line always has.
    """
    return (node.raw().get("data") or {}).get("kernel_revision") or {}


# The nfsroot -> ext4 bake machinery is kcilib.run.bake (imported, so its
# guards and mkfs.ext4 command line cannot drift from the worker's); the manifest
# cache shared with the kernel artifact entries is kcilib.run.delivery's.



def provision_only(args):
    kernel_url = args.kernel_url or os.environ.get("KCI_KERNEL_URL")
    modules_url = args.modules_url or os.environ.get("KCI_MODULES_URL")
    revision = {}
    if not kernel_url:
        # No pinned build hash: take kernel + modules from the newest passing
        # build.  Both come from the SAME node on purpose: modprobe matches
        # /lib/modules by kernel release, so mixing builds makes every kvm test
        # skip with "Cannot open /dev/kvm".
        node = newest_node(args.job, args.api_url)
        if not node.artifact("kernel"):
            sys.exit(f"newest {args.job} node {node.node_id} carries no "
                     f"kernel artifact")
        card = Builds().add(node)
        kernel_url = card.kernel
        modules_url = modules_url or card.modules
        revision = revision_of(node)
        print(f"newest {args.job}: {revision.get('describe', '?')} "
              f"({(revision.get('commit') or '')[:12]}) id={node.node_id}")
    else:
        # A pinned kernel URL has no node to read a revision from: the caller
        # states it, or the seed has nothing to label its nodes with.
        revision = {
            "commit": os.environ.get("KCI_BUILD_COMMIT", ""),
            "describe": os.environ.get("KCI_BUILD_DESCRIBE", ""),
            "tree": os.environ.get("KCI_BUILD_TREE", ""),
            "branch": os.environ.get("KCI_BUILD_BRANCH", ""),
            "url": os.environ.get("KCI_BUILD_URL", ""),
        }
    delivery.check_consistency(kernel_url, modules_url)
    # The rootfs this lab boots its guests from is the lab's own image, not a
    # build artifact: the one URL policy owns.  Recorded in build.env because
    # that file is this deployment's description of what it serves; nothing
    # prunes or bakes it any more - a run bakes its rootfs from this URL on
    # demand and keeps the result in the bake cache.
    rootfs_url = policy.POLICY.rootfs_url
    manifest = delivery.load_manifest()
    delivery.provision_kernel(kernel_url, DEFAULT_IMAGE, DEFAULT_SERVE_IMAGE,
                              manifest)
    delivery.save_manifest(manifest)
    # One source of truth for "which kbuild these artifacts came from" -
    # including the revision: run-local-stack.sh seeds jobs from this file, so the
    # served kernel, the baked modules and the job definition cannot drift apart.
    build_dir = kernel_url.rsplit("/", 1)[0]
    # The path is kcilib.core.layout's (it owns what lives in work/env).
    build_env = os.fspath(layout.deployment_env())
    version = revision.get("version")
    if not isinstance(version, dict):
        # Either {"version": N, "patchlevel": N} or a bare int (N10): .get() on
        # the int raised AttributeError and lost the whole file.
        version = {"version": version} if isinstance(version, int) else {}
    tags = " ".join(revision.get("commit_tags") or [])

    def env_line(key, value):
        """KEY=<shell-quoted value>.

        build.env is *sourced* by run-local-stack.sh, so a raw value breaks the
        deployment: a space-joined tag list ran `v7.0: command not found`, and a
        quote or backslash corrupted the shell state (N2).
        """
        return f"{key}={shlex.quote('' if value is None else str(value))}\n"

    with open(build_env, "w") as handle:
        handle.write("# Written by ./run.sh provision - do not edit by hand.\n")
        handle.write("# The kbuild every work/ artifact below comes from;\n")
        handle.write("# run-local-stack.sh seeds jobs from these URLs and\n")
        handle.write("# labels the nodes it creates with this revision.\n")
        handle.write("# Values are shell-quoted: this file is sourced, not parsed.\n")
        handle.write(env_line("KCI_BUILD_DIR", build_dir))
        handle.write(env_line("KCI_KERNEL_URL", kernel_url))
        if modules_url:
            handle.write(env_line("KCI_MODULES_URL", modules_url))
        handle.write(env_line("KCI_ROOTFS_URL", rootfs_url))
        handle.write(env_line("KCI_BUILD_COMMIT", revision.get("commit") or ""))
        handle.write(env_line("KCI_BUILD_DESCRIBE", revision.get("describe") or ""))
        handle.write(env_line("KCI_BUILD_TREE", revision.get("tree") or ""))
        handle.write(env_line("KCI_BUILD_BRANCH", revision.get("branch") or ""))
        handle.write(env_line("KCI_BUILD_URL", revision.get("url") or ""))
        handle.write(env_line("KCI_BUILD_VERSION", version.get("version") or ""))
        handle.write(env_line("KCI_BUILD_PATCHLEVEL", version.get("patchlevel") or ""))
        handle.write(env_line("KCI_BUILD_TAGS", tags))
    print(f"build pinned at {build_env}: {build_dir}")
    if revision.get("commit"):
        print(f"build revision: {revision.get('describe') or '?'} "
              f"({revision['commit'][:12]})")
    else:
        print("  !! build revision unknown (the kernel URL came from outside "
              "production): the seed will fall back to its pinned placeholder "
              "unless KCI_BUILD_COMMIT/KCI_BUILD_DESCRIBE are set")
    print("provision complete")
    return 0


# The judgement itself is kcilib.run.judge's, reached through the run this entry
# point hands to kci: judge_run() over the console the run archived, so the
# printed verdict, the record and the process status are one verdict.


def print_tap(outcome, test):
    """The TAP summary this line has always printed, off the run's own verdict.

    The counts and the per-test results are kcilib.run.judge's reading of the
    console this run archived (kci's local_server delivery judges it), so
    nothing here reads the console a second time; this only lays them out.
    """
    print(f"\n=== TAP summary ({test}) ===")
    if outcome.per_test:
        for name, result in outcome.per_test.items():
            print(f"  {result:4s}  {name}")
        summary = outcome.summary
        print(f"  {summary['total']} test(s): "
              f"{summary['total'] - summary['failed'] - summary['skipped']} pass, "
              f"{summary['failed']} fail, {summary['skipped']} skip")
    else:
        tail = "\n".join((outcome.output or "").strip().splitlines()[-12:])
        print("no TAP results; log tail:\n", tail)


def record_error(job, out, fields, detail):
    """File the "error" record of a run that produced no verdict.

    The key set, the layout and the write are kcilib.core.ledger's and the file
    is written for every outcome - a failed run is exactly the one worth having
    a record of.  A write that fails is reported and costs only the record.
    """
    try:
        job.record(out, verdict=judge.VERDICT_ERROR, exit_code=judge.EXIT_INFRA,
                   detail=detail, source=SOURCE_FETCH, fields=fields)
    except OSError as write_error:
        print(f"Warning: could not write {job.record_path()}: {write_error}")


def main():
    ap = argparse.ArgumentParser(
        epilog="exit status: 0 pass, 1 test failure, 3 infrastructure error")
    ap.add_argument("--job", default=JOB)
    ap.add_argument("--test", choices=sorted(TESTS), default=None,
                    help="test collection to run (default: kselftest-riscv)")
    ap.add_argument("--kvm-full", action="store_true",
                    help="kvm: run whole collection (no TST_CASENAME "
                         "allow-list); implies --test kselftest-kvm. "
                         "Timeouts are a TCG limitation, not fails")
    ap.add_argument("--api-url", default=API)
    ap.add_argument("--rootfs", default=None,
                    help="rootfs ext4 path to use instead of the one the job "
                         "definition names (default: the definition's, baked "
                         "on demand and cached under work/env/baked/)")
    ap.add_argument("--provision-only", action="store_true",
                    help="produce/reuse work/serve/Image and record the build "
                         "in work/env/build.env, then exit 0 (no tuxrun)")
    ap.add_argument("--kernel-url", default=None,
                    help="kernel Image URL for work/serve/Image")
    ap.add_argument("--modules-url", default=None,
                    help="modules.tar.xz URL baked into the rootfs; must be "
                         "the SAME build as --kernel-url")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--serve-port", type=int, default=8998)
    ap.add_argument("--gateway", default=None)
    # From kcilib.core.config: this flag and the worker's --cpu must not drift.
    ap.add_argument("--cpu", default=config.DEFAULT_CPU)
    # One name, two meanings before: here the CONTAINER runtime (docker/podman),
    # in the worker the LAB filter.  --container-runtime is primary, --runtime stays
    # as an alias, and either lands in RunConfig.container_runtime.
    ap.add_argument("--container-runtime", "--runtime",
                    dest="container_runtime", default="docker",
                    help="container runtime tuxrun runs the guest in "
                         "(docker/podman); --runtime is the old spelling")
    args = ap.parse_args()
    # --kvm-full without the kvm collection used to be a silent no-op that ran the
    # whole riscv suite instead (#5); it now means what it says.
    if args.kvm_full:
        if args.test is None:
            print("--kvm-full implies --test kselftest-kvm")
            args.test = "kselftest-kvm"
        elif args.test != "kselftest-kvm":
            ap.error("--kvm-full runs the whole kvm collection, but --test "
                     f"{args.test} was also given; pass --test kselftest-kvm "
                     "(or --kvm-full alone)")
    if args.test is None:
        args.test = "kselftest-riscv"
    if args.provision_only:
        sys.exit(provision_only(args))
    # The run-scoped half of this command line, in the SAME object the worker
    # passes around (kcilib.core.config.RunConfig): the two entry points cannot
    # describe the same run differently field by field.
    #
    # rootfs is empty unless --rootfs named one: the job definition carries the
    # lab's nfsroot URL (Job.definition), so run_node bakes it on demand and
    # keeps the result in the bake cache - the same route the worker and the
    # local table take.  This line used to pre-bake a fixed work/env/
    # rootfs-kvm.ext4 of its own, with its own manifest, which is why it was the
    # only one of the three that needed provisioning logic at all.
    run_config = config.RunConfig(
        tuxrun_bin=TUXRUN,
        cpu=args.cpu,
        kvm_full=args.kvm_full,
        container_runtime=args.container_runtime,
        rootfs=f"file://{os.path.abspath(args.rootfs)}" if args.rootfs else "",
        output_dir=args.out_dir,
    )

    node = newest_node(args.job, args.api_url)
    revision = revision_of(node)
    print(f"newest {args.job}: {revision.get('describe', '?')} "
          f"({revision.get('commit', '')[:12]}) {node.created} id={node.node_id}")

    # The per-build download/serve directory.  Spelled the way this line has
    # always printed it ("<repo>/scripts/../work/downloads/<id>", the same
    # directory kcilib.core.layout names as work/downloads): people read that
    # line and compare it, so the root comes from kcilib.repo_root() and the
    # rest is unchanged.
    out = args.out_dir or os.path.join(repo_root(), "scripts", "..", "work",
                                       "downloads", node.node_id)
    os.makedirs(out, exist_ok=True)
    # The node as the API served it: kcilib.core.retention reads this file to
    # tell which build a download directory holds, and no card carries the whole
    # node.
    raw = node.raw()
    with open(os.path.join(out, "node.json"), "w") as handle:
        json.dump({key: raw[key] for key in ("id", "name", "created", "data")},
                  handle, indent=1)

    card = Builds().add(node)

    # One test on one build: kcilib.run.jobrun runs it, kcilib.run.delivery
    # serves its artifacts and kcilib.run.judge decides it - this line only says
    # which build, which test and whose record it is.
    job = Job(card.build_id, args.test, artifacts=dict(card.artifacts),
              build=card)
    fields = {
        "job": node.name,
        "build_created": node.created,
        "revision": revision,
    }
    try:
        outcome = job.run(config=run_config, delivery=DELIVERY_LOCAL_SERVER,
                          source=SOURCE_FETCH, node_id=node.node_id,
                          serve_port=args.serve_port, gateway=args.gateway,
                          out_dir=out, record_fields=fields)
    except BaseException as error:
        # Anything that stops the run before a verdict (a truncated download, a
        # bake that failed, Ctrl-C) is recorded too: a failed run needs its
        # record.
        record_error(job, out, fields, f"{type(error).__name__}: {error}")
        raise
    if not outcome.started:
        # The artifact server refused to start, so no run happened: that is not
        # a verdict.  This line has always put that text on stderr with status
        # 1, and filed it as an infra "error" under the SystemExit that carried
        # it - the wording below is that record's.
        record_error(job, out, fields, f"SystemExit: {outcome.detail}")
        sys.exit(outcome.detail)

    print_tap(outcome, args.test)
    print(f"\nverdict: {outcome.verdict.upper()} - {outcome.detail}")
    print(f"log kept at: {out}")
    print(f"result record: {outcome.record}")
    return outcome.exit_code


