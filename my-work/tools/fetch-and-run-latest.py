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
"""

import argparse
import gzip
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

API = "https://api.kernelci.org"
JOB = "kbuild-gcc-14-riscv"
TESTS = {"boot": [], "kselftest-riscv": ["kselftest-riscv"], "kselftest-kvm": ["kselftest-kvm"]}
KVM_SUBSET = ("kvm:set_memory_region_test kvm:kvm_create_max_vcpus "
              "kvm:kvm_binary_stats_test kvm:kvm_page_table_test kvm:ebreak_test "
              "kvm:guest_print_test kvm:steal_time kvm:sbi_pmu_test kvm:irqfd_test")
TUXRUN = os.environ.get("TUXRUN_BIN", shutil.which("tuxrun")
                        or os.path.expanduser("~/.local/bin/tuxrun"))
DEFAULT_ROOTFS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "worker-out", "kvm-run", "rootfs-kvm.ext4")


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


def download(url, dest):
    print(f"  downloading {os.path.basename(dest)} ({url})")
    with urllib.request.urlopen(url, timeout=300) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


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
    ap.add_argument("--api-url", default=API)
    ap.add_argument("--rootfs", default=DEFAULT_ROOTFS)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--serve-port", type=int, default=8998)
    ap.add_argument("--gateway", default=None)
    ap.add_argument("--cpu", default="rv64,v=true,ssnpm=true")
    ap.add_argument("--runtime", default="docker")
    args = ap.parse_args()
    api = args.api_url

    node = pick_newest(args.job, api)
    kr = (node.get("data") or {}).get("kernel_revision") or {}
    arts = node.get("artifacts") or {}
    print(f"newest {args.job}: {kr.get('describe', '?')} "
          f"({kr.get('commit', '')[:12]}) {node.get('created')} id={node['id']}")

    out = args.out_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "evidence", "latest-runs", node["id"])
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
           "--rootfs", f"file://{os.path.abspath(args.rootfs)}"]
    params = [f"cpu={args.cpu}"]
    if args.test != "boot":
        params.append(f"KSELFTEST={base}/kselftest.tar.xz")
        if args.test == "kselftest-kvm" and modules:
            cmd += ["--modules", f"{base}/modules.tar.xz"]
            params.append(f"TST_CASENAME={KVM_SUBSET}")
        cmd += ["--tests", TESTS[args.test][0]]
    cmd += ["--parameters", *params]
    print("running:", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
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
