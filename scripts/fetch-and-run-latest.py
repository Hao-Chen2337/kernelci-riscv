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
    fetch-and-run-latest.py --test boot            # boot only
    fetch-and-run-latest.py --api-url http://127.0.0.1:8001  # local DB
    fetch-and-run-latest.py --provision-only       # produce work/ artifacts
"""

import argparse
import gzip
import importlib.util
import json
import os
import re
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
    return kernel_url, artifacts.get("modules")


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


def _cache_hit(manifest, key, dest):
    """True when *dest* is usable for *key*: non-empty, size matches the
    record (if any).  An existing file with no record at all is adopted
    (fresh clone / pre-seeded work/), but a file recorded under a different
    key (another build's kernel/modules) must be regenerated."""
    if not os.path.exists(dest):
        return False
    size = os.path.getsize(dest)
    if size <= 0:
        return False
    entry = manifest.get(key)
    if entry is not None:
        return entry.get("size") == size
    rel = os.path.relpath(dest, ROOT)
    return not any(e.get("dest") == rel for e in manifest.values())


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
    if not kernel_url:
        # No pinned build hash: ask production for the newest passing kbuild
        # and take kernel + modules from that one node.
        kernel_url, discovered_modules = default_build_artifacts(
            args.job, args.api_url)
        modules_url = modules_url or discovered_modules
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
    build_dir = kernel_url.rsplit("/", 1)[0]
    build_env = os.path.join(WORK_ENV, "build.env")
    with open(build_env, "w") as handle:
        handle.write("# Written by ./run.sh provision - do not edit by hand.\n")
        handle.write("# The kbuild every work/ artifact below comes from;\n")
        handle.write("# run-local-stack.sh seeds jobs from these URLs.\n")
        handle.write(f"KCI_BUILD_DIR={build_dir}\n")
        handle.write(f"KCI_KERNEL_URL={kernel_url}\n")
        if modules_url:
            handle.write(f"KCI_MODULES_URL={modules_url}\n")
        handle.write(f"KCI_ROOTFS_URL={rootfs_url}\n")
    print(f"build pinned at {build_env}: {build_dir}")
    print("provision complete")
    return 0


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def parse_tap(output):
    rows = []
    for line in output.splitlines():
        line = strip_ansi(line)
        m = re.search(r"(?<![a-z])(not ok|ok)\s+(\d+)\s+selftests:\s+(.*)", line)
        if m:
            name = m.group(3).strip()
            if ":" in name:
                name = name.split(":", 1)[1].strip()
            rows.append((m.group(1), m.group(2), name))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default=JOB)
    ap.add_argument("--test", choices=sorted(TESTS), default="kselftest-riscv")
    ap.add_argument("--kvm-full", action="store_true",
                    help="kvm: run whole collection (no TST_CASENAME "
                         "allow-list); timeouts are TCG limitation, not fails")
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
    if args.provision_only:
        sys.exit(provision_only(args))
    rootfs = args.rootfs or DEFAULT_ROOTFS
    api = args.api_url

    node = pick_newest(args.job, api)
    kr = (node.get("data") or {}).get("kernel_revision") or {}
    arts = node.get("artifacts") or {}
    print(f"newest {args.job}: {kr.get('describe', '?')} "
          f"({kr.get('commit', '')[:12]}) {node.get('created')} id={node['id']}")

    out = args.out_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "work", "downloads", node["id"])
    os.makedirs(out, exist_ok=True)

    kernel_gz = os.path.join(out, "Image.gz")
    kernel = os.path.join(out, "Image")
    if not os.path.exists(kernel):
        download(arts["kernel"], kernel_gz)
        with gzip.open(kernel_gz, "rb") as src, open(kernel, "wb") as dst:
            shutil.copyfileobj(src, dst)
    kselftest = os.path.join(out, "kselftest.tar.xz")
    if not os.path.exists(kselftest):
        download(arts["kselftest_tar_xz"], kselftest)
    modules = None
    if args.test == "kselftest-kvm":
        modules = os.path.join(out, "modules.tar.xz")
        if not os.path.exists(modules):
            download(arts["modules"], modules)
    cfg = os.path.join(out, ".config")
    if not os.path.exists(cfg):
        download(arts["_config"], cfg)
    with open(os.path.join(out, "node.json"), "w") as f:
        json.dump({k: node[k] for k in ("id", "name", "created", "data")}, f, indent=1)

    # The default rootfs used to be a hand-made 4GB file nothing generated:
    # bake it on first use so a fresh clone works.  An explicit --rootfs is
    # used verbatim (never auto-generated).
    if args.rootfs is None and not os.path.exists(rootfs):
        rootfs_url = (args.rootfs_url or os.environ.get("KCI_ROOTFS_URL")
                      or DEFAULT_ROOTFS_URL)
        manifest = load_manifest()
        provision_rootfs(rootfs_url, arts.get("modules"), rootfs, manifest)
        save_manifest(manifest)

    # serve artifacts for the dispatcher container / guest
    gateway = args.gateway
    if not gateway:
        try:
            gateway = socket.gethostbyname("host.docker.internal")
        except OSError:
            gateway = "172.17.0.1"
    base = f"http://{gateway}:{args.serve_port}"
    pybin = sys.executable or shutil.which("python3") or "python3"
    server = subprocess.Popen(
        [pybin, "-m", "http.server", str(args.serve_port),
         "--bind", "0.0.0.0", "--directory", out],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)

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
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                              check=False)
        output = proc.stdout + proc.stderr
    finally:
        server.terminate()
    with open(os.path.join(out, "tuxrun.log"), "w") as f:
        f.write(output)
    rows = parse_tap(output)
    print("\n=== TAP summary ===")
    for status, num, name in rows:
        print(f"  {status:6s} {num:>3s}  {name}")
    if not rows:
        tail = "\n".join(output.strip().splitlines()[-12:])
        print("no selftest TAP lines found; log tail:\n", tail)
    print(f"\nlog kept at: {out}")


if __name__ == "__main__":
    main()
