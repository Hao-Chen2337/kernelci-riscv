#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Artifact delivery: the same guest, two ways to feed it artifacts.

in_container hands artifact URLs straight to tuxrun, which downloads them
in the container; local_server downloads and verifies them locally first,
then serves them to the container over a local HTTP server. This module
offers the capabilities and never picks a mode for the caller.
Long-form rationale: docs/code-notes/B-delivery-buildref.md.
"""

import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import unquote, urlparse

from kcilib import repo_root
from kcilib.core import ports
from kcilib.run import artifacts

# Repo layout from this file's own location: walk up to run.sh
# (kcilib.repo_root), never count dirname() levels - a stale count puts
# downloads and the artifact server's document root under scripts/.
ROOT = repo_root()
WORK_ENV = os.path.join(ROOT, "work", "env")
WORK_SERVE = os.path.join(ROOT, "work", "serve")
MANIFEST_PATH = os.path.join(WORK_ENV, ".manifest.json")

BUILD_ID_FILE = "build-id.json"
ARTIFACT_RECORD = "artifacts.json"
# Seconds the freshly started artifact server gets to serve build-id.json back.
SERVE_READY_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# local_server: artifacts on disk (transfer + manifest + size record)
# ---------------------------------------------------------------------------

def download(url, dest):
    """Download *url* to *dest*, checking the size against Content-Length.

    A truncated 144MB rootfs must fail loudly, not boot half an image. Kept
    as its own single-shot transfer on purpose: artifacts.download() resumes
    .part files and prints different lines, changing the console contract.
    """
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


def human(n):
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


def record_entry(manifest, key, dest):
    manifest[key] = {
        "size": os.path.getsize(dest),
        "mtime": os.path.getmtime(dest),
        "dest": os.path.relpath(dest, ROOT),
    }


def cache_hit(manifest, key, dest):
    """True when *dest* is non-empty and matches *key*'s recorded size.

    A file with no record is adopted (fresh clone / pre-seeded work/) unless
    another key claims it, and it must still look complete: a truncated
    Image boots as garbage while the stage "succeeds" (#13).
    """
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
    if not artifacts.looks_complete(dest):
        print(f"  {os.path.basename(dest)} has no manifest record and does not "
              "match its .gz trailer; regenerating")
        return False
    return True


def fetch(url, dest, max_size=artifacts.MAX_DOWNLOAD_SIZE):
    """Download *url* to *dest*: file:// is copied, http(s) via
    artifacts.download (resume + size/truncation checks).

    The printed "copied <src> -> <dest> (...)" line is a console contract: the
    script that used to own this function re-binds kcilib.run.bake.download to
    it.
    """
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
        print(f"  copied {src} -> {dest} ({human(size)})")
        return
    artifacts.download(url, dest, max_size=max_size)


def _ensure_symlink(target, link):
    """Point *link* at *target* (work/serve/Image -> ../env/Image)."""
    if os.path.lexists(link):
        if os.path.exists(link) and os.path.getsize(link) > 0:
            return
        os.unlink(link)
    os.makedirs(os.path.dirname(link) or ".", exist_ok=True)
    rel = os.path.relpath(target, os.path.dirname(link))
    os.symlink(rel, link)
    print(f"  linked {link} -> {rel}")


BUILD_RE = re.compile(r"kbuild-gcc-14-riscv-([0-9a-fA-F]+)")


def build_of(url):
    m = BUILD_RE.search(url or "")
    return m.group(1) if m else None


def check_consistency(kernel_url, modules_url):
    """The kernel Image and the modules baked into the rootfs must come from
    the same kbuild node; a mismatch makes every kvm test skip."""
    kbuild = build_of(kernel_url)
    mbuild = build_of(modules_url)
    if kbuild and mbuild and kbuild != mbuild:
        print("WARNING: kernel and modules are from different kbuild builds "
              f"({kbuild} vs {mbuild}); kvm tests will skip "
              '("Cannot open /dev/kvm")')
        return False
    return True


def provision_kernel(kernel_url, image_path, serve_image_path, manifest):
    """Ensure the raw Image exists at *image_path* and is linked from
    *serve_image_path*; downloads and gunzips only on a manifest miss.

    The compressed artifact is kept next to the Image so re-provisioning
    does not depend on a CDN that truncates downloads often enough to matter.
    """
    key = f"kernel|{kernel_url}"
    if cache_hit(manifest, key, image_path):
        record_entry(manifest, key, image_path)
        print(f"cache hit: {os.path.basename(image_path)} "
              f"({human(os.path.getsize(image_path))})")
        _ensure_symlink(image_path, serve_image_path)
        return image_path

    gz_path = image_path + ".gz"
    gz_key = f"kernel-gz|{kernel_url}"
    started = time.time()
    if cache_hit(manifest, gz_key, gz_path):
        print(f"cache hit: {os.path.basename(gz_path)} "
              f"({human(os.path.getsize(gz_path))})")
    else:
        print(f"downloading kernel {kernel_url}")
        fetch(kernel_url, gz_path)
        record_entry(manifest, gz_key, gz_path)

    with open(gz_path, "rb") as f:
        is_gzip = f.read(2) == b"\x1f\x8b"
    if is_gzip:
        tmp = image_path + ".part"
        with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, image_path)
    else:
        shutil.copyfile(gz_path, image_path)
    record_entry(manifest, key, image_path)
    _ensure_symlink(image_path, serve_image_path)
    print(f"kernel -> {image_path} "
          f"({human(os.path.getsize(image_path))}, "
          f"{time.time() - started:.1f}s)")
    return image_path


def remote_size(url, timeout=60):
    """Content-Length of *url* without downloading it, or None."""
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
        return int(length) if length else None
    except (OSError, ValueError):
        return None


def load_artifact_record(out):
    """Per-build record of what was downloaded and how big it was."""
    try:
        with open(os.path.join(out, ARTIFACT_RECORD)) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_artifact_record(out, record):
    path = os.path.join(out, ARTIFACT_RECORD)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as handle:
        json.dump(record, handle, indent=1, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def recorded_size(record, name, url):
    """The size this script recorded when it wrote *name* from *url*, or None."""
    entry = record.get(name)
    if entry and entry.get("url") == url:
        size = entry.get("size")
        if isinstance(size, int) and size > 0:
            return size
    return None


def ensure_artifact(url, dest, record, name, what):
    """Make sure *dest* holds the complete artifact at *url*.

    Reuse has to be proven - by the recorded size, or by the server's
    Content-Length for a file this script did not write - because a bare
    os.path.exists() once adopted a truncated Image and booted it (#13).
    """
    expected = recorded_size(record, name, url)
    if os.path.exists(dest):
        size = os.path.getsize(dest)
        if expected is not None and size == expected:
            print(f"  cache hit: {os.path.basename(dest)} ({human(size)})")
            return dest
        if expected is not None:
            print(f"  cached {what} {os.path.basename(dest)} is truncated "
                  f"({human(size)} of {human(expected)}); re-downloading")
        elif size == 0:
            print(f"  cached {what} {os.path.basename(dest)} is empty; "
                  "re-downloading")
        else:
            remote = remote_size(url)
            if remote is not None and remote == size:
                print(f"  cache hit: {os.path.basename(dest)} ({human(size)}, "
                      "size confirmed by the server)")
                record[name] = {"url": url, "size": size}
                return dest
            detail = (human(remote) if remote is not None
                      else "no Content-Length from the server")
            print(f"  cached {what} {os.path.basename(dest)} cannot be verified "
                  f"({human(size)} vs {detail}); re-downloading")
        os.unlink(dest)
    download(url, dest)
    record[name] = {"url": url, "size": os.path.getsize(dest)}
    return dest


def ensure_kernel_image(url, gz_path, image_path, record):
    """Ensure the gunzipped kernel at *image_path* is complete.

    The Image goes through a .part file + rename and is reused only when its
    recorded size still matches its .gz: an interrupted *gunzip* leaves both
    files non-empty, which an existence check cannot see (#13).
    """
    ensure_artifact(url, gz_path, record, "Image.gz", "kernel")
    gz_size = os.path.getsize(gz_path)
    entry = record.get("Image") or {}
    have = os.path.getsize(image_path) if os.path.exists(image_path) else 0
    if have > 0 and entry.get("gz_size") == gz_size and entry.get("size") == have:
        print(f"  cache hit: {os.path.basename(image_path)} ({human(have)})")
        return image_path
    if have:
        recorded = entry.get("size")
        print(f"  cached Image does not match its Image.gz ("
              f"{human(have)} vs "
              f"{human(recorded) if isinstance(recorded, int) else 'no record'}"
              "); re-gunzipping")
    tmp = image_path + ".part"
    try:
        with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
    except (OSError, EOFError) as error:
        # A truncated .gz fails here instead of leaving a half-written Image.
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise OSError(f"gunzip {gz_path} failed: {error}") from error
    os.replace(tmp, image_path)
    record["Image"] = {"url": url, "size": os.path.getsize(image_path),
                       "gz_size": gz_size}
    print(f"kernel -> {image_path} ({human(os.path.getsize(image_path))})")
    return image_path


# ---------------------------------------------------------------------------
# local_server: the local HTTP server and what it actually serves
# ---------------------------------------------------------------------------

def _served_body(port, name, timeout=5):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/{name}",
                                timeout=timeout) as response:
        return response.read()


def served_size(port, name, timeout=5):
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


class ArtifactServerError(RuntimeError):
    """The artifact server cannot be trusted to serve this run's kernel.

    Raised instead of exiting the process: this library is also called by a
    resident worker, where one busy port must cost a job, not the daemon.  An
    entry point that wants a process exit status catches this and uses sys.exit()
    itself (scripts/fetch-and-run-latest.py does exactly that, keeping the stderr
    text, the infra record and status 1 it produced when these were sys.exit()).
    """


def start_artifact_server(out, port, node, kernel_path):
    """Start the artifact server and prove what it serves before tuxrun runs.

    The port is probed first (busy = a loud refusal, never the stale server
    that once served an older build - #12), and the served build-id plus
    Image size are read back through the very port tuxrun is handed. The
    probe binds 0.0.0.0, as the stack serves. Refusals raise
    ArtifactServerError, never SystemExit (a resident caller exists).
    """
    if not ports.port_is_free(port, host="0.0.0.0"):
        holder = ports.port_holder(port)
        raise ArtifactServerError(
            f"artifact server port {port} is already in use ({holder}).\n"
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
        raise ArtifactServerError(
            f"artifact server on port {port} did not serve build "
            f"{node.get('id')} (got {got}); refusing to run tuxrun against an "
            "unknown build.\n"
            f"    its log ({log_path}):\n{_log_tail(log_path)}")
    name = os.path.basename(kernel_path)
    try:
        served_bytes = served_size(port, name)
    except OSError as error:
        # A 404 here is itself the failure this guard exists for, so report it.
        served_bytes = f"unreadable ({error})"
    local_size = os.path.getsize(kernel_path)
    if served_bytes != local_size:
        stop_artifact_server(server)
        raise ArtifactServerError(
            f"artifact server serves {name} as {served_bytes} but the verified "
            f"file on disk is {local_size} bytes; refusing to boot a different "
            "or truncated kernel.")
    print(f"artifact server on {port} serves {os.path.relpath(out, ROOT)} "
          f"(build {node.get('id')}, {os.path.basename(kernel_path)} "
          f"{human(local_size)})")
    return server
