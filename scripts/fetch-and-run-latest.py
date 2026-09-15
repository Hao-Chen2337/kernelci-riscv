#!/usr/bin/env python3
"""Fetch the newest production riscv kbuild and run it locally with tuxrun.

No KernelCI local stack, no node, no token needed: this queries the
public production API for the latest passing kbuild-gcc-14-riscv build,
downloads its artifacts (kernel / kselftest / modules / .config), serves
them locally and runs tuxrun against them - the same execution path the
pull-lab worker uses.

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
import gzip
import importlib.util
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import unquote, urlparse

API = "https://api.kernelci.org"
JOB = "kbuild-gcc-14-riscv"
TESTS = {"boot": [], "kselftest-riscv": ["kselftest-riscv"], "kselftest-kvm": ["kselftest-kvm"]}

# KVM whitelist, single source: imported from the worker so the two can
# never drift apart.
_worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "riscv_pull_worker.py")
_worker_spec = importlib.util.spec_from_file_location("riscv_pull_worker", _worker_path)
_worker = importlib.util.module_from_spec(_worker_spec)
_worker_spec.loader.exec_module(_worker)
KVM_SUBSET = " ".join(f"kvm:{name}" for name in _worker.KVM_TEST_SUBSET)

TUXRUN = os.environ.get("TUXRUN_BIN", shutil.which("tuxrun")
                        or os.path.expanduser("~/.local/bin/tuxrun"))

# Repository layout derived from this file's own location (never a hardcoded
# absolute path): work/ is gitignored and holds regenerable runtime artifacts.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_SCRIPT_DIR)
WORK_ENV = os.path.join(ROOT, "work", "env")
WORK_SERVE = os.path.join(ROOT, "work", "serve")
MANIFEST_PATH = os.path.join(WORK_ENV, ".manifest.json")
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

# One verdict vocabulary for the script and for the record it writes.  Exit 3
# for "infrastructure" mirrors LAVA's job status 3 (incomplete), so a caller
# can tell "the tests ran and failed" from "nothing ran at all".
EXIT_PASS = 0
EXIT_TEST_FAIL = 1
EXIT_INFRA = 3
VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_INFRA = "infra"
# The run never produced a verdict at all (stale artifact server, truncated
# download, ...): still a non-zero outcome worth recording.
VERDICT_ERROR = "error"

RESULTS_DIR = os.path.join(ROOT, "work", "results")
BUILD_ID_FILE = "build-id.json"
ARTIFACT_RECORD = "artifacts.json"
TUXRUN_TIMEOUT = 1800
# How long the freshly started artifact server gets to serve its build-id file
# back before the run is refused (see start_artifact_server).
SERVE_READY_TIMEOUT = 15.0

# The guest's own console output: the only boot evidence that does not come
# from LAVA's own "Wait for prompt [...]" chatter.  Used to judge a --test boot
# run, which has no TAP to read (see judge_run).
BOOT_EVIDENCE_RE = re.compile(r"\[\s*0\.000000\]|Booting Linux")


def api_get(path, api):
    req = urllib.request.Request(f"{api}/latest{path}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def pick_newest(job, api):
    """Newest done/pass kbuild node; the API defaults to old-first pages,
    so ask for a rolling window and widen it if empty."""
    for days in (3, 7, 30, 180):
        since = (time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400)))
        data = api_get(
            f"/nodes?kind=kbuild&name={job}&created__gte={since}&limit=200",
            api)
        items = [i for i in data.get("items", [])
                 if i.get("state") == "done" and i.get("result") == "pass"]
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


def download(url, dest):
    """Download *url* to *dest*, verifying size against Content-Length
    (a truncated 144MB rootfs must fail loudly, not boot half an image)."""
    print(f"  downloading {os.path.basename(dest)} ({url})")
    with urllib.request.urlopen(url, timeout=300) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)
        size = f.tell()
    length = resp.headers.get("Content-Length")
    if length:
        try:
            length = int(length)
        except ValueError:
            length = None
        if length is not None and size != length:
            os.unlink(dest)
            raise OSError(f"Truncated download {url}: {size}/{length} bytes")


def _human(n):
    """Compact byte size for log lines."""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(n)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024.0
    return f"{n}B"


def load_manifest(path=MANIFEST_PATH):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        print(f"Warning: manifest {path} unreadable; starting fresh")
        return {}


def save_manifest(manifest, path=MANIFEST_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _record(manifest, key, dest):
    manifest[key] = {
        "size": os.path.getsize(dest),
        "mtime": os.path.getmtime(dest),
        "dest": os.path.relpath(dest, ROOT),
    }


def _gzip_isize(path):
    """Uncompressed size from a gzip member's 4-byte trailer, or None.

    A complete *download* is not proof of a complete *gunzip*: the kernel is
    decompressed into its final name, so a run killed mid-gunzip leaves a
    truncated Image that still exists and is still non-empty.  The trailer is
    the only size a finished .gz carries, and reading 4 bytes costs nothing."""
    try:
        with open(path, "rb") as handle:
            handle.seek(-4, os.SEEK_END)
            return int.from_bytes(handle.read(4), "little")
    except (OSError, ValueError):
        return None


def _looks_complete(dest):
    """True when *dest* can be a complete decompression of dest + ".gz".

    Only consulted for a file with NO manifest record, i.e. the one case where
    _cache_hit() would otherwise adopt a file on trust (#13)."""
    gz = dest + ".gz"
    if not os.path.exists(gz):
        return True
    isize = _gzip_isize(gz)
    if not isize:
        return True
    return os.path.getsize(dest) == isize


def _cache_hit(manifest, key, dest):
    """True when *dest* is usable for *key*: non-empty, size matches the
    record (if any).  An existing file with no record at all is adopted
    (fresh clone / pre-seeded work/), but a file recorded under a different
    key (another build's kernel/modules) must be regenerated - and a
    record-less file still has to look complete, because a truncated Image
    boots as garbage while the stage "succeeds" (#13)."""
    if not os.path.exists(dest):
        return False
    size = os.path.getsize(dest)
    if size <= 0:
        return False
    entry = manifest.get(key)
    if entry is not None:
        return entry.get("size") == size
    rel = os.path.relpath(dest, ROOT)
    if any(e.get("dest") == rel for e in manifest.values()):
        return False
    if not _looks_complete(dest):
        print(f"  {os.path.basename(dest)} has no manifest record and does not "
              "match its .gz trailer; regenerating")
        return False
    return True


_ORIGINAL_DOWNLOAD = _worker.download


def _fetch(url, dest, max_size=_worker.MAX_DOWNLOAD_SIZE):
    """Download *url* to *dest*.  file:// sources are copied locally (offline
    tests); http(s) reuses worker.download (retry + size/truncation checks)."""
    if url.startswith("file://"):
        src = unquote(urlparse(url).path)
        if not os.path.exists(src):
            raise OSError(f"file:// source missing: {src}")
        size = os.path.getsize(src)
        if size > max_size:
            raise OSError(f"source too large {src}: {size} > {max_size}")
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copyfile(src, dest)
        print(f"  copied {src} -> {dest} ({_human(size)})")
        return
    _ORIGINAL_DOWNLOAD(url, dest, max_size=max_size)


def _ensure_symlink(target, link):
    """Point *link* at *target*; work/serve/Image is a symlink to
    ../env/Image so the artifact server serves the canonical kernel file."""
    if os.path.lexists(link):
        if os.path.exists(link) and os.path.getsize(link) > 0:
            return
        os.unlink(link)
    os.makedirs(os.path.dirname(link) or ".", exist_ok=True)
    rel = os.path.relpath(target, os.path.dirname(link))
    os.symlink(rel, link)
    print(f"  linked {link} -> {rel}")


_BUILD_RE = re.compile(r"kbuild-gcc-14-riscv-([0-9a-fA-F]+)")


def _build_of(url):
    m = _BUILD_RE.search(url or "")
    return m.group(1) if m else None


def _check_consistency(kernel_url, modules_url):
    """The kernel Image and the modules baked into the rootfs must come from
    the same kbuild node; a mismatch makes every kvm test skip."""
    kbuild = _build_of(kernel_url)
    mbuild = _build_of(modules_url)
    if kbuild and mbuild and kbuild != mbuild:
        print("WARNING: kernel and modules are from different kbuild builds "
              f"({kbuild} vs {mbuild}); kvm tests will skip "
              '("Cannot open /dev/kvm")')
        return False
    return True


def provision_kernel(kernel_url, image_path, serve_image_path, manifest):
    """Ensure the raw kernel Image exists at *image_path* and is linked from
    *serve_image_path*; downloads + gunzips only on a manifest miss.

    The compressed artifact is kept next to the Image (recorded in the
    manifest under its own key) instead of being deleted after gunzip: this
    CDN truncates downloads often enough that re-provisioning a correct
    artifact should not depend on the network at all."""
    key = f"kernel|{kernel_url}"
    if _cache_hit(manifest, key, image_path):
        _record(manifest, key, image_path)
        print(f"cache hit: {os.path.basename(image_path)} "
              f"({_human(os.path.getsize(image_path))})")
        _ensure_symlink(image_path, serve_image_path)
        return image_path

    gz_path = image_path + ".gz"
    gz_key = f"kernel-gz|{kernel_url}"
    started = time.time()
    if _cache_hit(manifest, gz_key, gz_path):
        print(f"cache hit: {os.path.basename(gz_path)} "
              f"({_human(os.path.getsize(gz_path))})")
    else:
        print(f"downloading kernel {kernel_url}")
        _fetch(kernel_url, gz_path)
        _record(manifest, gz_key, gz_path)

    with open(gz_path, "rb") as f:
        is_gzip = f.read(2) == b"\x1f\x8b"
    if is_gzip:
        tmp = image_path + ".part"
        with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, image_path)
    else:
        shutil.copyfile(gz_path, image_path)
    _record(manifest, key, image_path)
    _ensure_symlink(image_path, serve_image_path)
    print(f"kernel -> {image_path} "
          f"({_human(os.path.getsize(image_path))}, "
          f"{time.time() - started:.1f}s)")
    return image_path


def _remote_size(url, timeout=60):
    """Content-Length of *url* without downloading it, or None."""
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
        return int(length) if length else None
    except (OSError, ValueError):
        return None


def provision_rootfs(rootfs_url, modules_url, ext4_path, manifest):
    """Ensure the baked ext4 rootfs exists at *ext4_path* (manifest cache).
    Reuses worker.bake_rootfs_image: nfsroot tar.xz -> tuxrun-bootable ext4,
    with kvm modules baked into /lib/modules."""
    key = f"rootfs-kvm.ext4|{rootfs_url}|{modules_url or ''}"
    if _cache_hit(manifest, key, ext4_path):
        _record(manifest, key, ext4_path)
        print(f"cache hit: {os.path.basename(ext4_path)} "
              f"({_human(os.path.getsize(ext4_path))})")
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
        expected = _remote_size(rootfs_url)
        have = os.path.getsize(cached) if os.path.exists(cached) else 0
        if expected is not None and have == expected:
            print(f"  reusing cached tarball {cached} ({_human(have)})")
        else:
            if have:
                print(f"  tarball on disk is incomplete ({_human(have)} of "
                      f"{_human(expected) if expected else 'an unknown size'}); "
                      "resuming")
            _worker.download(rootfs_url, cached)
        source = "file://" + os.path.abspath(cached)
    workspace = tempfile.mkdtemp(prefix="kci-bake-", dir=WORK_ENV)
    try:
        # bake_rootfs_image calls the module-global download; swap in _fetch so
        # file:// URLs work too, then restore the original.
        _worker.download = _fetch
        try:
            image = _worker.bake_rootfs_image(
                workspace, source,
                boot_modules=["kvm"],
                modules_url=modules_url)
        finally:
            _worker.download = _ORIGINAL_DOWNLOAD
        os.replace(image, ext4_path)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    _record(manifest, key, ext4_path)
    print(f"rootfs -> {ext4_path} "
          f"({_human(os.path.getsize(ext4_path))}, "
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
    _check_consistency(kernel_url, modules_url)
    manifest = load_manifest()
    provision_kernel(kernel_url, DEFAULT_IMAGE, DEFAULT_SERVE_IMAGE, manifest)
    provision_rootfs(rootfs_url, modules_url, DEFAULT_ROOTFS, manifest)
    save_manifest(manifest)
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
# riscv_pull_worker.tap_summary() from the import above, exactly as the worker
# uses it - one parser, no drift.


def _load_artifact_record(out):
    """Per-build record of what was downloaded and how big it was."""
    try:
        with open(os.path.join(out, ARTIFACT_RECORD)) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_artifact_record(out, record):
    path = os.path.join(out, ARTIFACT_RECORD)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as handle:
        json.dump(record, handle, indent=1, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _recorded_size(record, name, url):
    """The size this script recorded when it wrote *name* from *url*, or None."""
    entry = record.get(name)
    if entry and entry.get("url") == url:
        size = entry.get("size")
        if isinstance(size, int) and size > 0:
            return size
    return None


def ensure_artifact(url, dest, record, name, what):
    """Make sure *dest* holds the complete artifact at *url*.

    A bare os.path.exists() adopted an Image that an interrupted run had left
    truncated, and handed it to tuxrun as a kernel (#13).  Reuse therefore has
    to be proven: by the size recorded when this script wrote the file, or -
    for a file it did not write (a pre-seeded work/downloads/) - by the
    server's Content-Length.  A recorded size that does not match is proof of
    truncation and is said so; anything that cannot be shown complete is
    fetched again."""
    expected = _recorded_size(record, name, url)
    if os.path.exists(dest):
        size = os.path.getsize(dest)
        if expected is not None and size == expected:
            print(f"  cache hit: {os.path.basename(dest)} ({_human(size)})")
            return dest
        if expected is not None:
            print(f"  cached {what} {os.path.basename(dest)} is truncated "
                  f"({_human(size)} of {_human(expected)}); re-downloading")
        elif size == 0:
            print(f"  cached {what} {os.path.basename(dest)} is empty; "
                  "re-downloading")
        else:
            remote = _remote_size(url)
            if remote is not None and remote == size:
                print(f"  cache hit: {os.path.basename(dest)} ({_human(size)}, "
                      "size confirmed by the server)")
                record[name] = {"url": url, "size": size}
                return dest
            detail = (_human(remote) if remote is not None
                      else "no Content-Length from the server")
            print(f"  cached {what} {os.path.basename(dest)} cannot be verified "
                  f"({_human(size)} vs {detail}); re-downloading")
        os.unlink(dest)
    download(url, dest)
    record[name] = {"url": url, "size": os.path.getsize(dest)}
    return dest


def ensure_kernel_image(url, gz_path, image_path, record):
    """Ensure the gunzipped kernel at *image_path* is complete.

    The Image is written through a .part file + rename, so a partial kernel can
    never appear under the final name, and it is only reused when its recorded
    size still matches the compressed artifact it came from: an interrupted
    *gunzip* leaves both files present and non-empty, which is exactly the case
    a plain existence check cannot see (#13)."""
    ensure_artifact(url, gz_path, record, "Image.gz", "kernel")
    gz_size = os.path.getsize(gz_path)
    entry = record.get("Image") or {}
    have = os.path.getsize(image_path) if os.path.exists(image_path) else 0
    if have > 0 and entry.get("gz_size") == gz_size and entry.get("size") == have:
        print(f"  cache hit: {os.path.basename(image_path)} ({_human(have)})")
        return image_path
    if have:
        recorded = entry.get("size")
        print(f"  cached Image does not match its Image.gz ("
              f"{_human(have)} vs "
              f"{_human(recorded) if isinstance(recorded, int) else 'no record'}"
              "); re-gunzipping")
    tmp = image_path + ".part"
    try:
        with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
    except (OSError, EOFError) as error:
        # A truncated .gz fails here (EOFError / BadGzipFile) instead of
        # leaving a half-written Image in place.
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise OSError(f"gunzip {gz_path} failed: {error}") from error
    os.replace(tmp, image_path)
    record["Image"] = {"url": url, "size": os.path.getsize(image_path),
                       "gz_size": gz_size}
    print(f"kernel -> {image_path} ({_human(os.path.getsize(image_path))})")
    return image_path


def _port_error(port):
    """The bind error for *port*, or None when the port is free.

    Binding is the only honest test: a stale artifact server that answers
    nothing (or answers with an OLDER build) still owns the port, and the
    failure mode that matters is tuxrun downloading the previous build's
    artifacts while the console names the new one (#12)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("0.0.0.0", port))
    except OSError as error:
        return str(error)
    finally:
        probe.close()
    return None


def _served_body(port, name, timeout=5):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/{name}",
                                timeout=timeout) as response:
        return response.read()


def _served_size(port, name, timeout=5):
    """Content-Length the artifact server reports for *name*, or None."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}/{name}",
                                     method="HEAD")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        length = response.headers.get("Content-Length")
    return int(length) if length else None


def _log_tail(path, lines=8):
    try:
        with open(path) as handle:
            tail = handle.read().strip().splitlines()[-lines:]
    except OSError:
        return "      (no server log)"
    return "\n".join("      " + line for line in tail)


def stop_artifact_server(server):
    server.terminate()
    try:
        server.wait(timeout=15)
    except subprocess.TimeoutExpired:
        server.kill()


def start_artifact_server(out, port, node, kernel_path):
    """Start the artifact server and prove what it serves before tuxrun runs.

    The old code started http.server with stdout/stderr on DEVNULL and slept a
    fixed 1.5s: a server left on the port by a killed earlier run kept serving
    an older work/downloads/<node>/, so the run tested one kernel while the
    console - and the log - named another (#12).  Now the port is probed first
    (busy = a loud refusal, never a silent swap), the server logs into the
    build directory instead of DEVNULL, and its build-id file plus the served
    Image size are read back through the very port tuxrun is handed."""
    busy = _port_error(port)
    if busy:
        sys.exit(
            f"artifact server port {port} is already in use ({busy}).\n"
            "    A stale server from an earlier run would serve an OLDER build "
            f"to tuxrun while this run reports {node.get('id')} - refusing to "
            "run against a build it cannot verify.\n"
            f"    Stop it (e.g. pkill -f 'http.server {port}') or pass "
            "--serve-port <other port>.")
    build_id = {
        "node_id": node.get("id"),
        "name": node.get("name"),
        "created": node.get("created"),
        "kernel": os.path.basename(kernel_path),
    }
    with open(os.path.join(out, BUILD_ID_FILE), "w") as handle:
        json.dump(build_id, handle, indent=1, sort_keys=True)
    log_path = os.path.join(out, "serve.log")
    pybin = sys.executable or shutil.which("python3") or "python3"
    with open(log_path, "w") as log:
        server = subprocess.Popen(
            [pybin, "-m", "http.server", str(port),
             "--bind", "0.0.0.0", "--directory", out],
            stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + SERVE_READY_TIMEOUT
    served = None
    while time.time() < deadline:
        if server.poll() is not None:
            break
        try:
            served = json.loads(_served_body(port, BUILD_ID_FILE))
            break
        except (OSError, ValueError):
            time.sleep(0.25)
    if served is None or served.get("node_id") != node.get("id"):
        stop_artifact_server(server)
        got = served.get("node_id") if isinstance(served, dict) else "no answer"
        sys.exit(
            f"artifact server on port {port} did not serve build "
            f"{node.get('id')} (got {got}); refusing to run tuxrun against an "
            "unknown build.\n"
            f"    its log ({log_path}):\n{_log_tail(log_path)}")
    name = os.path.basename(kernel_path)
    try:
        served_size = _served_size(port, name)
    except OSError as error:
        # A 404 for the kernel we just verified is itself the failure this
        # guard exists for, so report it instead of tracing back.
        served_size = f"unreadable ({error})"
    local_size = os.path.getsize(kernel_path)
    if served_size != local_size:
        stop_artifact_server(server)
        sys.exit(
            f"artifact server serves {name} as {served_size} but the verified "
            f"file on disk is {local_size} bytes; refusing to boot a different "
            "or truncated kernel.")
    print(f"artifact server on {port} serves {os.path.relpath(out, ROOT)} "
          f"(build {node.get('id')}, {os.path.basename(kernel_path)} "
          f"{_human(local_size)})")
    return server


def judge_run(test, returncode, output):
    """The verdict for one tuxrun run:
    (verdict, exit_code, detail, summary, per_test).

    TAP parsing is the worker's, not a second weaker copy (#23): tuxrun exits 0
    even when every selftest fails, so riscv_pull_worker.tap_summary() is
    authoritative for a kselftest collection, and its total=0 encoding is the
    "the suite never ran" case that used to be printed as a harmless summary
    (#2).  returncode is None after a timeout."""
    if returncode is None:
        return (VERDICT_INFRA, EXIT_INFRA,
                f"tuxrun timed out after {TUXRUN_TIMEOUT}s", None, {})
    if (_worker.tuxrun_invocation_error(returncode, output)
            or _worker.tuxrun_job_error(returncode, output)
            or _worker.tuxrun_infra_error(returncode, output)):
        return (VERDICT_INFRA, EXIT_INFRA,
                _worker.tuxrun_error_message(output, test), None, {})
    if test != "boot":
        summary, _status, per_test = _worker.tap_summary(output, test)
        if summary["total"] == 0:
            # No TAP at all: the suite never ran.  Never a pass - this is
            # exactly the false green the worker's tap_summary() guards against.
            if returncode != 0:
                return (VERDICT_INFRA, EXIT_INFRA,
                        (f"no TAP lines and tuxrun exited {returncode}: the "
                         "guest never booted or the suite never started"),
                        summary, per_test)
            return (VERDICT_FAIL, EXIT_TEST_FAIL,
                    "tuxrun exited 0 but produced no TAP lines at all",
                    summary, per_test)
        detail = (f"{summary['total']} selftest(s): "
                  f"{summary['total'] - summary['failed'] - summary['skipped']} "
                  f"pass, {summary['failed']} fail, "
                  f"{summary['skipped']} skip")
        if summary["failed"]:
            return VERDICT_FAIL, EXIT_TEST_FAIL, detail, summary, per_test
        if returncode != 0:
            detail += (f" (tuxrun exited {returncode}; the TAP, not tuxrun's "
                       "exit code, carries the selftest verdict)")
        return VERDICT_PASS, EXIT_PASS, detail, summary, per_test
    # boot: there is no TAP, and the exit code alone is not a verdict - the
    # worker's lava_body() also refuses to call a run with no boot evidence a
    # pass - so require output that only a booted guest can have produced.
    if returncode != 0:
        return (VERDICT_FAIL, EXIT_TEST_FAIL,
                f"tuxrun exited {returncode}; see the log", None, {})
    cleaned = _worker.strip_ansi(output)
    job_result = None
    boot_cases = []
    for raw in cleaned.splitlines():
        match = _worker.LAVA_CASE_RE.search(raw)
        if not match:
            continue
        if match.group(1) in ("login-action", "kernel-messages"):
            boot_cases.append(match.group(2))
        elif match.group(1) == "job":
            job_result = match.group(2)
    if job_result == "fail" or "fail" in boot_cases:
        return (VERDICT_FAIL, EXIT_TEST_FAIL,
                "tuxrun reported the boot as failed", None, {})
    if boot_cases or job_result == "pass" or BOOT_EVIDENCE_RE.search(cleaned):
        return (VERDICT_PASS, EXIT_PASS, "guest booted", None, {})
    return (VERDICT_INFRA, EXIT_INFRA,
            ("tuxrun exited 0 but the log shows no boot at all (no kernel "
             "console output, no login prompt, no boot case)"), None, {})


def write_result(path, node, test, verdict, exit_code, detail, out, summary):
    """Write the durable (build, test, verdict) record under work/results/.

    Mode (A) kept nothing but a console log inside work/downloads/<build>/, so
    "which build was this test run against, when, and how did it end" could
    only be reconstructed by hand.  The record is written for EVERY outcome -
    a failed run is exactly the one worth having a record of."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "build_id": node.get("id"),
        "build_created": node.get("created"),
        "job": node.get("name") or "",
        "test": test,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "verdict": verdict,
        "exit_code": exit_code,
        "detail": detail,
        "revision": (node.get("data") or {}).get("kernel_revision") or {},
        "artifacts_dir": os.path.relpath(out, ROOT),
        "log": os.path.relpath(os.path.join(out, "tuxrun.log"), ROOT),
        "results": summary,
    }
    tmp = f"{path}.tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return path


def run_once(args, node, out, record, rootfs):
    """Download/verify this build's artifacts, serve them and run tuxrun once.

    Returns the outcome dict (verdict, exit_code, detail, summary, per_test,
    log, output).  Anything that prevents a verdict raises, and the caller
    records it: a run that dies before tuxrun is still a run that happened."""
    arts = node.get("artifacts") or {}
    kernel_gz = os.path.join(out, "Image.gz")
    kernel = os.path.join(out, "Image")
    ensure_kernel_image(arts["kernel"], kernel_gz, kernel, record)
    ensure_artifact(arts["kselftest_tar_xz"],
                    os.path.join(out, "kselftest.tar.xz"), record,
                    "kselftest.tar.xz", "kselftest")
    modules = None
    if args.test == "kselftest-kvm":
        modules = os.path.join(out, "modules.tar.xz")
        ensure_artifact(arts["modules"], modules, record, "modules.tar.xz",
                        "modules")
    ensure_artifact(arts["_config"], os.path.join(out, ".config"), record,
                    ".config", "kernel config")
    _save_artifact_record(out, record)
    with open(os.path.join(out, "node.json"), "w") as f:
        json.dump({k: node[k] for k in ("id", "name", "created", "data")}, f,
                  indent=1)

    # The default rootfs used to be a hand-made 4GB file nothing generated:
    # bake it on first use so a fresh clone works.  An explicit --rootfs is
    # used verbatim (never auto-generated).
    if args.rootfs is None and not os.path.exists(rootfs):
        rootfs_url = (args.rootfs_url or os.environ.get("KCI_ROOTFS_URL")
                      or DEFAULT_ROOTFS_URL)
        manifest = load_manifest()
        provision_rootfs(rootfs_url, arts.get("modules"), rootfs, manifest)
        save_manifest(manifest)

    gateway = args.gateway
    if not gateway:
        try:
            gateway = socket.gethostbyname("host.docker.internal")
        except OSError:
            gateway = "172.17.0.1"
    base = f"http://{gateway}:{args.serve_port}"
    server = start_artifact_server(out, args.serve_port, node, kernel)
    try:
        cmd = [TUXRUN, "--runtime", args.runtime, "--device", "qemu-riscv64",
               "--kernel", f"{base}/Image", "--boot-args", "rw",
               "--rootfs", f"file://{os.path.abspath(rootfs)}"]
        params = [f"cpu={args.cpu}"]
        if args.test != "boot":
            params.append(f"KSELFTEST={base}/kselftest.tar.xz")
            if args.test == "kselftest-kvm" and modules:
                cmd += ["--modules", f"{base}/modules.tar.xz"]
                if not args.kvm_full:
                    params.append(f"TST_CASENAME={KVM_SUBSET}")
            cmd += ["--tests", TESTS[args.test][0]]
        cmd += ["--parameters", *params]
        print("running:", " ".join(cmd))
        output = ""
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=TUXRUN_TIMEOUT, check=False)
            returncode = proc.returncode
            output = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as error:
            # A timed-out run still has a partial console log worth keeping,
            # and it is an infrastructure failure, not a test failure (#2).
            returncode = None
            output = f"{error.stdout or ''}\n{error.stderr or ''}"
    finally:
        stop_artifact_server(server)
    log_path = os.path.join(out, "tuxrun.log")
    with open(log_path, "w") as handle:
        handle.write(output)
    verdict, exit_code, detail, summary, per_test = judge_run(
        args.test, returncode, output)
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
    ap.add_argument("--cpu", default="rv64,v=true,ssnpm=true")
    ap.add_argument("--runtime", default="docker")
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

    node = pick_newest(args.job, args.api_url)
    kr = (node.get("data") or {}).get("kernel_revision") or {}
    print(f"newest {args.job}: {kr.get('describe', '?')} "
          f"({kr.get('commit', '')[:12]}) {node.get('created')} id={node['id']}")

    out = args.out_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "work", "downloads", node["id"])
    os.makedirs(out, exist_ok=True)
    record = _load_artifact_record(out)
    result_path = os.path.join(RESULTS_DIR, node["id"], f"{args.test}.json")

    try:
        outcome = run_once(args, node, out, record, rootfs)
    except BaseException as error:
        # Anything that stops the run before it produced a verdict (a stale
        # artifact server, a truncated download, Ctrl-C) is recorded too: the
        # record only has value if a failed run leaves one.
        try:
            write_result(result_path, node, args.test, VERDICT_ERROR,
                         EXIT_INFRA, f"{type(error).__name__}: {error}", out,
                         None)
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

    write_result(result_path, node, args.test, outcome["verdict"],
                 outcome["exit_code"], outcome["detail"], out,
                 outcome["summary"])
    print(f"\nverdict: {outcome['verdict'].upper()} - {outcome['detail']}")
    print(f"log kept at: {out}")
    print(f"result record: {result_path}")
    return outcome["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
