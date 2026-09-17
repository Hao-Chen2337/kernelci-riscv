#!/usr/bin/env python3
"""Fetch the newest production riscv kbuild and run it locally with tuxrun.

No KernelCI local stack, no node, no token needed: this queries the
public production API for the latest passing kbuild-gcc-14-riscv build,
downloads its artifacts (kernel / kselftest / modules / .config), serves
them locally and runs tuxrun against them - the same execution path the
pull-lab worker uses.

How the artifacts GET here is this script's choice and nobody else's:
kcilib/run/delivery.py names the two ways (local_server, which this script
uses, and in_container, which is what the worker's tuxrun command line does)
and owns the implementation of both - the download/size checks, the artifact
manifest and the local HTTP server used to live in this file.  This script now
picks the mode and hands out the addresses; see delivery.py for the trade-off.

Usage:
    fetch-and-run-latest.py                 # newest build, kselftest-riscv
    fetch-and-run-latest.py --test kselftest-kvm   # curated kvm subset
    fetch-and-run-latest.py --kvm-full      # whole kvm collection
                                            # (implies --test kselftest-kvm)
    fetch-and-run-latest.py --test boot            # boot only
    fetch-and-run-latest.py --api-url http://127.0.0.1:8001  # local DB
    fetch-and-run-latest.py --provision-only       # produce work/ artifacts

Exit status - this path is driven from cron/CI, so the verdict IS the exit
status (it used to be 0 for every outcome, including a guest that never booted):
    0   the run passed: TAP produced and no selftest failed, or the guest booted
    1   the run completed and at least one selftest failed
    3   infrastructure error: tuxrun never started, the guest never booted, no
        TAP lines at all, or the artifacts/artifact server could not be verified
Every outcome is also recorded in work/results/<build-id>/<test>.json.
"""

import argparse
import json
import os
import shlex
import shutil
import socket
import sys
import tempfile
import time
from urllib.parse import unquote, urlparse

API = "https://api.kernelci.org"
JOB = "kbuild-gcc-14-riscv"
TESTS = {"boot": [], "kselftest-riscv": ["kselftest-riscv"], "kselftest-kvm": ["kselftest-kvm"]}

# Everything this path and the pull-lab worker MUST agree on lives in
# scripts/kcilib/: the TAP parser and the verdict, the tuxrun command line, the
# artifact transfers, the KVM allow-list and the result ledger.  The library is
# resolved through this file's own directory, so the script works from any CWD
# and also when an offline test loads it by path.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from kcilib.api import KernelCI
from kcilib.core import config, ledger, params
from kcilib.run import artifacts, bake, delivery, judge, runner

TUXRUN = os.environ.get("TUXRUN_BIN", shutil.which("tuxrun")
                        or os.path.expanduser("~/.local/bin/tuxrun"))

# Repository layout: work/ is gitignored and holds regenerable runtime
# artifacts.  ROOT/WORK_ENV/WORK_SERVE are kcilib.run.delivery's (each resolved
# from that module's own location, never a hardcoded absolute path, exactly as
# this file used to do) because the delivery layer is what records which
# artifact was downloaded, from where and how big it was - the manifest and the
# serve directory are its business, so the layout is spelled once, there.
ROOT = delivery.ROOT
WORK_ENV = delivery.WORK_ENV
WORK_SERVE = delivery.WORK_SERVE
DEFAULT_ROOTFS = os.path.join(WORK_ENV, "rootfs-kvm.ext4")
DEFAULT_IMAGE = os.path.join(WORK_ENV, "Image")
DEFAULT_SERVE_IMAGE = os.path.join(WORK_SERVE, "Image")

# Rootfs for --provision-only (./run.sh provision).  Kernel and modules are NOT
# pinned here: they are discovered from the newest production kbuild node by
# default_build_artifacts() below, because storage prunes old builds (a pinned
# hash still served modules.tar.xz while its Image returned 404, which left a
# fresh deployment unable to provision a kernel at all).
DEFAULT_ROOTFS_URL = (
    "https://storage.kernelci.org/images/rootfs/debian/"
    "trixie-kselftest/20260606.0/riscv64/full.rootfs.tar.xz")

# The verdict vocabulary is kcilib.run.judge's - the exit statuses (0 pass, 1 test
# failure, 3 infrastructure), the TAP parser, the "timed out after Ns" detail
# and the boot evidence a --test boot run is judged by (kcilib.run.judge reads the
# guest's own console output).  The result record below and the worker's
# callback are therefore the same verdict, not two copies of it.
#
# BUILD_ID_FILE, the per-build ARTIFACT_RECORD and SERVE_READY_TIMEOUT went
# with the delivery implementation: writing the build-id file the server proves
# itself with, recording what was downloaded, and waiting for that proof are
# kcilib.run.delivery's, not this script's.


def api_get(path, api):
    """One GET through the shared client (kcilib/api.py).

    This script used to open its own urllib request here - a third variant of
    the same call, next to config_drift.py's and regression_tracker.py's.  The
    client keeps this script's promise of needing no stack and no token: it is
    plain HTTP against whatever --api-url says.
    """
    return KernelCI(api).get(path)


def pick_newest(job, api):
    """Newest done/pass kbuild node; the API defaults to old-first pages,
    so ask for a rolling window and widen it if empty."""
    for days in (3, 7, 30, 180):
        since = (time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400)))
        items = [node for node in KernelCI(api).nodes(
            kind="kbuild", name=job, created__gte=since, limit=200)
            if node.get("state") == "done" and node.get("result") == "pass"]
        if items:
            items.sort(key=lambda i: i.get("created") or "", reverse=True)
            return items[0]
    sys.exit(f"no passing kbuild nodes for {job}")


def default_build_artifacts(job, api):
    """Kernel + modules URLs from the newest passing production kbuild node.

    Both come from the SAME node on purpose: the worker bakes modules.tar.xz
    into /lib/modules of the rootfs and modprobe matches them by kernel
    release, so mixing builds makes every kvm test skip with "Cannot open
    /dev/kvm".

    Discovered, not pinned: storage prunes old builds, and a pinned hash that
    still served modules.tar.xz returned 404 for its Image - a fresh
    deployment could not provision a kernel from it.
    """
    node = pick_newest(job, api)
    artifacts = node.get("artifacts") or {}
    kernel_url = artifacts.get("kernel")
    if not kernel_url:
        sys.exit(f"newest {job} node {node.get('id')} carries no kernel artifact")
    revision = (node.get("data") or {}).get("kernel_revision") or {}
    print(f"newest {job}: {revision.get('describe', '?')} "
          f"({(revision.get('commit') or '')[:12]}) id={node.get('id')}")
    # The revision travels with the URLs: provision records it in
    # work/env/build.env and the seed labels its nodes from it.  Returning the
    # URLs alone is what let the seed keep its own hardcoded revision while
    # serving a completely different kernel, so every node - and every
    # `./run.sh report` line - named a build nothing had booted.
    return kernel_url, artifacts.get("modules"), revision


# The nfsroot tarball -> ext4 bake machinery (DISK_SIZE, the path-traversal
# and device-member guards, _extract and bake_rootfs_image) used to be an
# inlined copy of the pull-lab worker's, kept here only because kcilib had no
# bake module when this path was rewritten.  It is kcilib.run.bake now: the same
# code, imported, so the guards and the mkfs.ext4 command line cannot drift
# from the worker's a second time.  The manifest cache it uses
# (work/env/.manifest.json, by URL, shared with the kernel artifact entries) is
# NOT kcilib.run.bake's sidecar cache: its implementation is
# kcilib.run.delivery's (load_manifest/save_manifest/cache_hit/record_entry),
# because recording WHAT was downloaded, from where and how big it was is the
# delivery layer's job.  Rootfs BAKING stays here - delivery is about getting
# artifacts to tuxrun, baking is kcilib.run.bake's.


def provision_rootfs(rootfs_url, modules_url, ext4_path, manifest):
    """Ensure the baked ext4 rootfs exists at *ext4_path* (manifest cache).
    Uses kcilib.run.bake.bake_rootfs_image(): nfsroot tar.xz -> tuxrun-bootable
    ext4, with kvm modules baked into /lib/modules."""
    key = f"rootfs-kvm.ext4|{rootfs_url}|{modules_url or ''}"
    if delivery.cache_hit(manifest, key, ext4_path):
        delivery.record_entry(manifest, key, ext4_path)
        print(f"cache hit: {os.path.basename(ext4_path)} "
              f"({delivery.human(os.path.getsize(ext4_path))})")
        return ext4_path

    print(f"baking rootfs ext4 from {rootfs_url}")
    started = time.time()
    os.makedirs(WORK_ENV, exist_ok=True)
    # Download the tarball to a stable path rather than into the temporary bake
    # directory: the worker's download() resumes an interrupted transfer with a
    # Range request, so a fetch that this CDN cut short is continued by the
    # next run instead of restarting from zero - which is the difference
    # between a fresh clone provisioning successfully and never finishing.
    source = rootfs_url
    if not rootfs_url.startswith("file://"):
        cached = os.path.join(
            WORK_ENV, os.path.basename(unquote(urlparse(rootfs_url).path)))
        expected = delivery.remote_size(rootfs_url)
        have = os.path.getsize(cached) if os.path.exists(cached) else 0
        if expected is not None and have == expected:
            print(f"  reusing cached tarball {cached} "
                  f"({delivery.human(have)})")
        else:
            if have:
                known = (delivery.human(expected) if expected
                         else "an unknown size")
                print("  tarball on disk is incomplete "
                      f"({delivery.human(have)} of {known}); resuming")
            artifacts.download(rootfs_url, cached)
        source = "file://" + os.path.abspath(cached)
    workspace = tempfile.mkdtemp(prefix="kci-bake-", dir=WORK_ENV)
    try:
        # kcilib.run.bake transfers through this rebindable seam:
        # delivery.fetch() takes file:// sources (the offline tests) and its
        # printed "copied ..." lines were this script's before the move, so it
        # is still bound before the bake - the bake's console is unchanged.
        bake.download = delivery.fetch
        image = bake.bake_rootfs_image(
            workspace, source,
            boot_modules=["kvm"],
            modules_url=modules_url)
        os.replace(image, ext4_path)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    delivery.record_entry(manifest, key, ext4_path)
    print(f"rootfs -> {ext4_path} "
          f"({delivery.human(os.path.getsize(ext4_path))}, "
          f"{time.time() - started:.1f}s)")
    return ext4_path


def provision_only(args):
    kernel_url = args.kernel_url or os.environ.get("KCI_KERNEL_URL")
    modules_url = args.modules_url or os.environ.get("KCI_MODULES_URL")
    rootfs_url = (args.rootfs_url or os.environ.get("KCI_ROOTFS_URL")
                  or DEFAULT_ROOTFS_URL)
    revision = {}
    if not kernel_url:
        # No pinned build hash: ask production for the newest passing kbuild
        # and take kernel + modules from that one node.
        kernel_url, discovered_modules, revision = default_build_artifacts(
            args.job, args.api_url)
        modules_url = modules_url or discovered_modules
    else:
        # A hand-pinned kernel URL has no node to read a revision from, so let
        # the caller state it.  Without one the seed has nothing to label its
        # nodes with, and says so instead of quietly using its old default.
        revision = {
            "commit": os.environ.get("KCI_BUILD_COMMIT", ""),
            "describe": os.environ.get("KCI_BUILD_DESCRIBE", ""),
            "tree": os.environ.get("KCI_BUILD_TREE", ""),
            "branch": os.environ.get("KCI_BUILD_BRANCH", ""),
            "url": os.environ.get("KCI_BUILD_URL", ""),
        }
    delivery.check_consistency(kernel_url, modules_url)
    manifest = delivery.load_manifest()
    delivery.provision_kernel(kernel_url, DEFAULT_IMAGE, DEFAULT_SERVE_IMAGE,
                              manifest)
    provision_rootfs(rootfs_url, modules_url, DEFAULT_ROOTFS, manifest)
    delivery.save_manifest(manifest)
    # One source of truth for "which kbuild these artifacts came from":
    # run-local-stack.sh seeds jobs from this file, so the kernel served at
    # :8999, the modules baked into the rootfs and the job definition cannot
    # drift apart.  A mismatch makes every kvm test skip ("Cannot open
    # /dev/kvm"), which is exactly the failure this whole path exists to avoid.
    #
    # The kernel *revision* is part of that: the seed used to keep its own
    # hardcoded commit/describe, so a deployment serving 7.3-rc2 labelled every
    # node (and every ./run.sh report line) 7.3-rc1-516-gf217004a40c49.  The
    # results were right, the attribution was wrong, and config_drift.py /
    # regression_tracker.py group by that field.
    build_dir = kernel_url.rsplit("/", 1)[0]
    build_env = os.path.join(WORK_ENV, "build.env")
    version = revision.get("version")
    if not isinstance(version, dict):
        # Production nodes carry either {"version": 7, "patchlevel": 3} or a
        # bare int; .get() on the int raised AttributeError and lost the whole
        # file (adversarial review, N10).
        version = {"version": version} if isinstance(version, int) else {}
    tags = " ".join(revision.get("commit_tags") or [])

    def env_line(key, value):
        """KEY=<shell-quoted value>.

        build.env is *sourced* by run-local-stack.sh, so a raw value breaks the
        deployment: a space-joined tag list ran `v7.0: command not found` and
        silently dropped every tag to the placeholder, and a quote or backslash
        in a describe string corrupted the shell state (adversarial review, N2).
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


# There is deliberately no local strip_ansi()/parse_tap() any more: the fetch
# path used a second, weaker copy that missed "not  ok", "NOT OK", ANSI-glued
# failures and tests that started but never finished, so it could print a
# summary that looked green when nothing had run (#23).  TAP parsing is
# kcilib.run.judge.tap_summary() - reached through judge_run() below - exactly as
# the worker's callback reaches it: one parser, no drift.




def write_result(node, test, verdict, exit_code, detail, out, summary):
    """Record one (build, test, verdict) under work/results/<build>/<test>.json.

    Mode (A) kept nothing but a console log inside work/downloads/<build>/, so
    "which build was this test run against, when, and how did it end" could
    only be reconstructed by hand.  The record is written for EVERY outcome -
    a failed run is exactly the one worth having a record of.  The file itself
    (path layout, tmp file + rename, fsync, the key set) is kcilib.core.ledger's,
    so the regression tracker and the worker write the same records; the
    payload below is this script's naming of the run."""
    return ledger.write_result(node["id"], test, {
        "build_created": node.get("created"),
        "job": node.get("name") or "",
        "source": "fetch",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "verdict": verdict,
        "exit_code": exit_code,
        "detail": detail,
        "revision": (node.get("data") or {}).get("kernel_revision") or {},
        "artifacts_dir": os.path.relpath(out, ROOT),
        "log": os.path.relpath(os.path.join(out, "tuxrun.log"), ROOT),
        "results": summary,
    })


def run_once(args, run_config, node, out, record, rootfs):
    """Download/verify this build's artifacts, serve them and run tuxrun once.

    Returns the outcome dict (verdict, exit_code, detail, summary, per_test,
    log, output).  Anything that prevents a verdict raises, and the caller
    records it: a run that dies before tuxrun is still a run that happened."""
    arts = node.get("artifacts") or {}
    kernel_gz = os.path.join(out, "Image.gz")
    kernel = os.path.join(out, "Image")
    delivery.ensure_kernel_image(arts["kernel"], kernel_gz, kernel, record)
    delivery.ensure_artifact(arts["kselftest_tar_xz"],
                             os.path.join(out, "kselftest.tar.xz"), record,
                             "kselftest.tar.xz", "kselftest")
    modules = None
    if args.test == "kselftest-kvm":
        modules = os.path.join(out, "modules.tar.xz")
        delivery.ensure_artifact(arts["modules"], modules, record,
                                 "modules.tar.xz", "modules")
    delivery.ensure_artifact(arts["_config"], os.path.join(out, ".config"),
                             record, ".config", "kernel config")
    delivery.save_artifact_record(out, record)
    with open(os.path.join(out, "node.json"), "w") as f:
        json.dump({k: node[k] for k in ("id", "name", "created", "data")}, f,
                  indent=1)

    # The default rootfs used to be a hand-made 4GB file nothing generated:
    # bake it on first use so a fresh clone works.  An explicit --rootfs is
    # used verbatim (never auto-generated).
    if args.rootfs is None and not os.path.exists(rootfs):
        rootfs_url = (args.rootfs_url or os.environ.get("KCI_ROOTFS_URL")
                      or DEFAULT_ROOTFS_URL)
        manifest = delivery.load_manifest()
        provision_rootfs(rootfs_url, arts.get("modules"), rootfs, manifest)
        delivery.save_manifest(manifest)

    gateway = args.gateway
    if not gateway:
        try:
            gateway = socket.gethostbyname("host.docker.internal")
        except OSError:
            gateway = "172.17.0.1"
    base = f"http://{gateway}:{args.serve_port}"
    server = delivery.start_artifact_server(out, args.serve_port, node, kernel)
    log_path = os.path.join(out, "tuxrun.log")
    try:
        # The cpu property string is kcilib.core.params.cpu_for(): the KVM jobs
        # need the H extension, everything else takes --cpu as it was given.
        parameters = [f"cpu={params.cpu_for(run_config.cpu, args.test)}"]
        if args.test != "boot":
            parameters.append(f"KSELFTEST={base}/kselftest.tar.xz")
            # kcilib.core.params.kvm_allow_list(): the curated functional subset
            # in the "kvm:name kvm:name ..." form the LKFT script wants, as
            # ONE --parameters entry.  --kvm-full asks for the whole
            # collection, which is exactly no allow-list at all.
            if (args.test == "kselftest-kvm" and modules
                    and not run_config.kvm_full):
                parameters.append(
                    f"TST_CASENAME={params.kvm_allow_list()}")
        argv = runner.build_tuxrun_argv(
            tuxrun_bin=run_config.tuxrun_bin,
            runtime=run_config.container_runtime, device="qemu-riscv64",
            kernel=f"{base}/Image", boot_args="rw",
            rootfs=f"file://{os.path.abspath(rootfs)}",
            modules=modules and f"{base}/modules.tar.xz",
            tests=TESTS[args.test], parameters=parameters)
        print("running:", " ".join(argv))
        # cwd and stream_separator are explicit because they are part of the
        # console this writes: tuxrun is run from the caller's directory, and
        # its stdout and stderr are concatenated with NOTHING between them -
        # these tuxrun.log files carry no blank line at the junction, unlike
        # the worker's archived consoles.  log_path is written by run_tuxrun
        # (partial console included on a timeout), and its proc.stdout IS the
        # merged console the verdict is read from.
        proc = runner.run_tuxrun(argv, timeout=judge.TUXRUN_TIMEOUT,
                                 log_path=log_path, cwd=None,
                                 stream_separator="")
        returncode = proc.returncode
        output = proc.stdout
    finally:
        delivery.stop_artifact_server(server)
    # One verdict, from kcilib.run.judge: the same TAP parser and the same exit
    # statuses the worker's callback reports.  summary and per_test are what
    # the TAP summary below and the result record print.
    verdict, exit_code, detail, summary, per_test = judge.judge_run(
        returncode, output, args.test)
    return {
        "verdict": verdict,
        "exit_code": exit_code,
        "detail": detail,
        "summary": summary,
        "per_test": per_test,
        "log": log_path,
        "output": output,
    }


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
                    help="rootfs ext4 path (default: work/env/rootfs-kvm.ext4)")
    ap.add_argument("--provision-only", action="store_true",
                    help="produce/reuse work/serve/Image and "
                         "work/env/rootfs-kvm.ext4 (+ manifest), then exit 0 "
                         "(no tuxrun)")
    ap.add_argument("--rootfs-url", default=None,
                    help="nfsroot tar.xz URL to bake the ext4 rootfs from")
    ap.add_argument("--kernel-url", default=None,
                    help="kernel Image URL for work/serve/Image")
    ap.add_argument("--modules-url", default=None,
                    help="modules.tar.xz URL baked into the rootfs; must be "
                         "the SAME build as --kernel-url")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--serve-port", type=int, default=8998)
    ap.add_argument("--gateway", default=None)
    # The default comes from kcilib.core.config, not from a literal here: this flag
    # and the worker's --cpu must mean the same string, and two copies of a
    # default are two chances to drift apart.
    ap.add_argument("--cpu", default=config.DEFAULT_CPU)
    # --runtime was this script's CONTAINER runtime (docker/podman) while the
    # worker's --runtime is the LAB filter (pull-labs-riscv, PollConfig.runtime):
    # one name, two meanings, in two entry points that are supposed to describe
    # the same run.  The unambiguous name is now primary, the old one stays as an
    # alias so nothing that already calls it breaks, and the value lands in
    # RunConfig.container_runtime either way.
    ap.add_argument("--container-runtime", "--runtime",
                    dest="container_runtime", default="docker",
                    help="container runtime tuxrun runs the guest in "
                         "(docker/podman); --runtime is the old spelling")
    args = ap.parse_args()
    # --kvm-full without the kvm collection used to be a silent no-op: the flag
    # is read only inside the kselftest-kvm branch, so "./run.sh fetch
    # --kvm-full" ran the whole *riscv* collection - a different and much
    # larger suite than the help promised (#5).  It now means what it says.
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
    rootfs = args.rootfs or DEFAULT_ROOTFS
    # The run-scoped half of this command line, in the SAME object the worker
    # passes around (kcilib.core.config.RunConfig).  Everything a run needs is named
    # here once; what stays in `args` is this script's deployment business (which
    # build to fetch, which port to serve it on, whether to provision only).
    # The two entry points therefore cannot describe the same run differently
    # field by field - which is how they drifted before.
    run_config = config.RunConfig(
        tuxrun_bin=TUXRUN,
        cpu=args.cpu,
        kvm_full=args.kvm_full,
        container_runtime=args.container_runtime,
        rootfs=args.rootfs or "",
        output_dir=args.out_dir,
    )

    node = pick_newest(args.job, args.api_url)
    kr = (node.get("data") or {}).get("kernel_revision") or {}
    print(f"newest {args.job}: {kr.get('describe', '?')} "
          f"({kr.get('commit', '')[:12]}) {node.get('created')} id={node['id']}")

    out = args.out_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "work", "downloads", node["id"])
    os.makedirs(out, exist_ok=True)
    record = delivery.load_artifact_record(out)
    result_path = ledger.result_path(node["id"], args.test)

    try:
        outcome = run_once(args, run_config, node, out, record, rootfs)
    except BaseException as error:
        # Anything that stops the run before it produced a verdict (a stale
        # artifact server, a truncated download, Ctrl-C) is recorded too: the
        # record only has value if a failed run leaves one.
        try:
            write_result(node, args.test, judge.VERDICT_ERROR,
                         judge.EXIT_INFRA,
                         f"{type(error).__name__}: {error}", out, None)
        except OSError as write_error:
            print(f"Warning: could not write {result_path}: {write_error}")
        raise

    print(f"\n=== TAP summary ({args.test}) ===")
    if outcome["per_test"]:
        for name, result in outcome["per_test"].items():
            print(f"  {result:4s}  {name}")
        summary = outcome["summary"]
        print(f"  {summary['total']} test(s): "
              f"{summary['total'] - summary['failed'] - summary['skipped']} pass, "
              f"{summary['failed']} fail, {summary['skipped']} skip")
    else:
        tail = "\n".join(outcome["output"].strip().splitlines()[-12:])
        print("no TAP results; log tail:\n", tail)

    write_result(node, args.test, outcome["verdict"],
                 outcome["exit_code"], outcome["detail"], out,
                 outcome["summary"])
    print(f"\nverdict: {outcome['verdict'].upper()} - {outcome['detail']}")
    print(f"log kept at: {out}")
    print(f"result record: {result_path}")
    return outcome["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
