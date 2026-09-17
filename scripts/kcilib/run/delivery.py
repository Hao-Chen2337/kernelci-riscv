#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""构件投送:同一个 guest,构件可以从两个地方来。

**in_container**(kcilib/run/jobrun.build_command 的现状,也是本模块的默认)
    构件 URL 直接写进 tuxrun 的命令行(--kernel <url>、--modules <url>、
    KSELFTEST=<url>),tuxrun 起的容器自己去下载。无状态、不占宿主机磁盘、
    不需要额外端口;代价是每次运行都是一次真实的网络依赖:CDN 抖一下,这次
    运行就变成 Infrastructure,而且"这个构件完整吗"不归我们管——下到一半被
    截断的内核会被直接交给 qemu,失败现场留在 guest 里。

**local_server**(scripts/fetch-and-run-latest.py 一直以来的做法)
    构件先落到本地(work/downloads/<build>/、work/env/)、校验大小,再用一个
    本机 HTTP 服务喂给容器——容器读不到宿主机的路径,所以"本地文件"必须以
    HTTP 的形式出现。换来的能力:

    * **启动前校验**:ensure_artifact() / ensure_kernel_image() 只把"证明过
      完整"的文件当成缓存命中(记录过的大小、服务器给的 Content-Length、
      或 gzip 尾部记的原始长度),对不上的重新下载,而不是拿去启动;被中断的
      gunzip 留下的那个"存在且非空"的 Image 正是这条守卫要拦的东西;
    * **服务出去的大小必须等于磁盘上的大小**:start_artifact_server() 在
      tuxrun 之前,用 tuxrun 将要拿到的那个端口把 Content-Length 读回来比对,
      不一致就拒绝运行——原话是 "refusing to boot a different or truncated
      kernel"。起了一个别的、或被截断的内核却报告说跑了这个构建,是这条路上
      最难查的故障;
    * **可离线、可换内核**:file:// 源与手写的 --kernel-url 走同一条路,构件
      不必来自生产 CDN。

    代价是宿主机多一份磁盘、多一个端口,以及一段要自己维护的下载/校验代码。

本模块只提供**能力**,不替调用方做**选择**。两种方式各有名字,执行层只问一个
问题——"内核该从哪个地址取"——也就是 kernel_url():

    in_container:   kernel_url(IN_CONTAINER, url) 就是 url 本身;
    local_server:   ensure_artifact(...) 落盘校验 ->
                    server = start_artifact_server(out, port, node, kernel) ->
                    kernel_url(LOCAL_SERVER, url, f"{base}/Image") ->
                    stop_artifact_server(server)。

今天 kcilib/run/jobrun.build_command() 仍然是 in_container、
scripts/fetch-and-run-latest.py 仍然是 local_server;把两条线接起来是另一步,
不是这个模块替它们做的决定。

**这里搬进来的是 scripts/fetch-and-run-latest.py 原本自己持有的那份实现**
(ensure_artifact / ensure_kernel_image / 清单与大小记录 / 本地 HTTP 服务),
逐字搬、只把脚本私有的名字改成公开的名字。它打印的每一行
(  downloading <name> (<url>)、kernel -> <path> (...)、
artifact server on <port> serves ...)都是那个脚本的控制台契约,搬家过程中
不许改;同理,搬过来的英文注释与函数体保持原样,不"顺手整理"——那些注释里
带着真实故障的结论(#13 截断的 Image、#12 陈旧的 artifact server)。本模块
新写的说明用中文。

ROOT、work/ 布局与 work/env/.manifest.json 的定义在这里:构件清单是投送层的
东西,scripts/fetch-and-run-latest.py 从本模块取这套拼法,不再自己写一份。
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

# Repository layout derived from this file's own location (never a hardcoded
# absolute path): work/ is gitignored and holds regenerable runtime artifacts.
# Walked up to run.sh (kcilib.repo_root), never counted: fetch-and-run-latest.py
# reached the root with one dirname() and this file needs four, and a stale count
# silently puts downloads and the artifact server's document root under scripts/.
ROOT = repo_root()
WORK_ENV = os.path.join(ROOT, "work", "env")
WORK_SERVE = os.path.join(ROOT, "work", "serve")
MANIFEST_PATH = os.path.join(WORK_ENV, ".manifest.json")

BUILD_ID_FILE = "build-id.json"
ARTIFACT_RECORD = "artifacts.json"
# How long the freshly started artifact server gets to serve its build-id file
# back before the run is refused (see start_artifact_server).
SERVE_READY_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# 方式的名字:执行层按一个字段选,拼错不静默退回默认值
# ---------------------------------------------------------------------------

IN_CONTAINER = "in_container"
LOCAL_SERVER = "local_server"
MODES = (IN_CONTAINER, LOCAL_SERVER)
# 默认仍是执行层今天的行为:URL 直接给 tuxrun,容器自己下。
DEFAULT_MODE = IN_CONTAINER


def validate(mode):
    """*mode* 必须是已知的投送方式,否则 ValueError。

    拼错的字段名不能静默地退回默认值:那会让"我选了 local_server"和"我什么都
    没选"在控制台上长得一模一样,而这两种选择的失败方式完全不同。
    """
    if mode not in MODES:
        raise ValueError(
            f"unknown delivery mode {mode!r}; expected one of "
            f"{', '.join(MODES)}")
    return mode


def describe(mode):
    """一种投送方式的一句话说明(给 --help、日志和报告用)。"""
    validate(mode)
    if mode == IN_CONTAINER:
        return ("in_container: 构件 URL 直接交给 tuxrun,容器自己下载 "
                "(不占本地磁盘,校验在 tuxrun 手里)")
    return ("local_server: 构件先下载并校验到本地,再由本机 HTTP 服务喂给容器 "
            "(占磁盘和一个端口,换启动前校验)")


def kernel_url(mode, url, served_url=None):
    """执行层唯一要问的问题:内核该从这个地址取?

    in_container: *url* 本身——tuxrun 的 --kernel 拿到 URL,容器自己下。
    local_server: *served_url*——start_artifact_server() 服务出来的本机地址
    (通常 http://<gateway>:<port>/Image)。这里不替调用方拼它:地址里的
    gateway 是"容器怎么回到宿主机"的部署知识,而 local_server 的全部意义就是
    "生产 URL 被本机地址换掉",所以它必须显式传进来——不传是编程错误,不是
    可以猜的默认值。
    """
    validate(mode)
    if mode == IN_CONTAINER:
        return url
    if not served_url:
        raise ValueError(
            "local_server delivery needs the address its artifact server "
            "serves (see start_artifact_server); got no served_url")
    return served_url


# ---------------------------------------------------------------------------
# local_server:构件落盘(单发传输 + 清单 + 大小记录)
# ---------------------------------------------------------------------------

def download(url, dest):
    """Download *url* to *dest*, verifying size against Content-Length
    (a truncated 144MB rootfs must fail loudly, not boot half an image).

    This is ensure_artifact()'s own single-shot transfer, and it is left
    exactly as it was: kcilib.run.artifacts.download() - which fetch() below
    uses for the same job - prints different lines ("Downloading <url>", then
    "           -> <dest> (N bytes)") and resumes partial transfers through
    .part files, so swapping it here would change the console of every run and
    the contents of work/downloads/<build>/ (reported)."""
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
    if not artifacts.looks_complete(dest):
        print(f"  {os.path.basename(dest)} has no manifest record and does not "
              "match its .gz trailer; regenerating")
        return False
    return True


def fetch(url, dest, max_size=artifacts.MAX_DOWNLOAD_SIZE):
    """Download *url* to *dest*.  file:// sources are copied locally (offline
    tests); http(s) is kcilib.run.artifacts.download (resume + size/truncation
    checks, the one transfer implementation the worker uses too).

    The printed "copied <src> -> <dest> (...)" line is the console contract of
    the script that used to own this function, and that script still re-binds
    kcilib.run.bake.download to THIS function so the bake's tarball transfer
    prints the same line."""
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
    """Ensure the raw kernel Image exists at *image_path* and is linked from
    *serve_image_path*; downloads + gunzips only on a manifest miss.

    The compressed artifact is kept next to the Image (recorded in the
    manifest under its own key) instead of being deleted after gunzip: this
    CDN truncates downloads often enough that re-provisioning a correct
    artifact should not depend on the network at all."""
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

    A bare os.path.exists() adopted an Image that an interrupted run had left
    truncated, and handed it to tuxrun as a kernel (#13).  Reuse therefore has
    to be proven: by the size recorded when this script wrote the file, or -
    for a file it did not write (a pre-seeded work/downloads/) - by the
    server's Content-Length.  A recorded size that does not match is proof of
    truncation and is said so; anything that cannot be shown complete is
    fetched again."""
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
        # A truncated .gz fails here (EOFError / BadGzipFile) instead of
        # leaving a half-written Image in place.
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise OSError(f"gunzip {gz_path} failed: {error}") from error
    os.replace(tmp, image_path)
    record["Image"] = {"url": url, "size": os.path.getsize(image_path),
                       "gz_size": gz_size}
    print(f"kernel -> {image_path} ({human(os.path.getsize(image_path))})")
    return image_path


# ---------------------------------------------------------------------------
# local_server:本机 HTTP 服务(以及"服务出去的确实是这个文件"的守卫)
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


def start_artifact_server(out, port, node, kernel_path):
    """Start the artifact server and prove what it serves before tuxrun runs.

    The old code started http.server with stdout/stderr on DEVNULL and slept a
    fixed 1.5s: a server left on the port by a killed earlier run kept serving
    an older work/downloads/<node>/, so the run tested one kernel while the
    console - and the log - named another (#12).  Now the port is probed first
    (busy = a loud refusal, never a silent swap), the server logs into the
    build directory instead of DEVNULL, and its build-id file plus the served
    Image size are read back through the very port tuxrun is handed.  The probe
    is kcilib.core.ports.port_is_free() - binding is the only honest test, and it
    binds 0.0.0.0 because that is how the stack serves - while the refusal names
    the holder through kcilib.core.ports.port_holder().

    The refusals still name --serve-port, which is the flag of the script that
    calls this: the wording is part of that script's console contract and it is
    the reader who has to be told how to move the port.

    Those refusals are sys.exit(), because this function's only caller today is
    a command-line script whose exit status IS the verdict.  A resident caller
    (the worker, if local_server is ever wired into jobrun) must NOT get a
    SystemExit out of a library call - it would take the daemon down with it -
    so that step needs a raised exception instead, and a per-job port rather
    than one fixed --serve-port."""
    if not ports.port_is_free(port, host="0.0.0.0"):
        holder = ports.port_holder(port)
        sys.exit(
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
        sys.exit(
            f"artifact server on port {port} did not serve build "
            f"{node.get('id')} (got {got}); refusing to run tuxrun against an "
            "unknown build.\n"
            f"    its log ({log_path}):\n{_log_tail(log_path)}")
    name = os.path.basename(kernel_path)
    try:
        served_bytes = served_size(port, name)
    except OSError as error:
        # A 404 for the kernel we just verified is itself the failure this
        # guard exists for, so report it instead of tracing back.
        served_bytes = f"unreadable ({error})"
    local_size = os.path.getsize(kernel_path)
    if served_bytes != local_size:
        stop_artifact_server(server)
        sys.exit(
            f"artifact server serves {name} as {served_bytes} but the verified "
            f"file on disk is {local_size} bytes; refusing to boot a different "
            "or truncated kernel.")
    print(f"artifact server on {port} serves {os.path.relpath(out, ROOT)} "
          f"(build {node.get('id')}, {os.path.basename(kernel_path)} "
          f"{human(local_size)})")
    return server
