#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Config-drift detector for the KernelCI riscv pipeline.
#
# Compares the effective kernel `.config` of two kbuild nodes of the same
# job and reports option-level drift: CONFIG_* options that were added,
# removed, or had their value changed between the two builds.  A kconfig
# change (upstream default change, fragment change, defconfig change) can
# silently alter which selftests are built and run, so drift is reported
# next to the test results.
#
# Where the .config comes from, in order of preference:
#   1. node artifact `_config` / `.config` (a URL in the node's artifacts)
#   2. the local storage convention used by the docker-compose deployment:
#      {storage_base}/{job}-{node_id}/.config
#   3. --older-config / --newer-config: explicit URLs or local file paths
#
# Read-only command: it talks to the API with GET requests only, so it works
# against the public production API (https://api.kernelci.org) without a
# token, as well as against the local API.  No KCI_API_TOKEN is required.
#
# Examples:
#   # newest two passing builds of the default job, drift summary only
#   python3 scripts/config_drift.py
#
#   # two specific builds, full listing capped at 20 lines per category
#   python3 scripts/config_drift.py --older 6a96... --newer 6a9d... --max-lines 20
#
#   # machine-readable report (and CI gate: exit 1 when drift > 0)
#   python3 scripts/config_drift.py --json
#
# Exit code: 0 = no drift, 1 = drift found (usable as a CI gate).

import argparse
import json
import os
import sys
import time

import requests

API_URL = os.environ.get("KCI_API_URL", "http://localhost:8001").rstrip("/")
# KernelCI exposes its API under the /latest prefix on api.kernelci.org; the
# local API accepts both, so always target the canonical /latest base.
API_LATEST = API_URL if API_URL.endswith("/latest") else f"{API_URL}/latest"
# Storage convention of the docker-compose deployment:
# {STORAGE_BASE}/{job}-{node_id}/.config
STORAGE_BASE = os.environ.get("KCI_STORAGE_URL", "http://localhost:8002")


def api_headers():
    """Optional Authorization header.

    Every request this tool makes is a GET, and the KernelCI API serves
    those publicly, so a token is only attached when one is configured.
    """
    token = os.environ.get("KCI_API_TOKEN")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def api_get(path, params=None, retries=3):
    """GET with a few retries for the local API's idle-connection resets."""
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.get(
                f"{API_LATEST}{path}",
                params=params,
                headers=api_headers(),
                timeout=60,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(attempt + 1)
    raise last_error


def fetch_all_nodes(params):
    """Page through /nodes until every matching node has been fetched.

    /nodes returns its results in creation order and truncates each
    response to the page limit, so a single request would silently miss the
    newest nodes of a large job.  The response carries {items,total,offset},
    which lets us walk every page before sorting client-side.
    """
    items = []
    offset = 0
    while True:
        page = api_get("/nodes", dict(params, offset=offset))
        batch = page.get("items") or []
        items.extend(batch)
        total = page.get("total")
        offset += len(batch)
        if not batch:
            return items
        if total is not None and offset >= total:
            return items
        if total is None and len(batch) < params.get("limit", 200):
            return items


def list_nodes(name, kind="kbuild", limit=200, **filters):
    params = {"name": name, "kind": kind, "limit": limit}
    for key, value in filters.items():
        if value is not None:
            params[key] = value
    return fetch_all_nodes(params)


def get_node(node_id):
    return api_get(f"/node/{node_id}")


def parse_config(text):
    """Parse a kernel .config into {CONFIG_OPT: value}.

    `CONFIG_X=y` / `CONFIG_X=123` / `CONFIG_X="str"` map to the value after
    '='; `# CONFIG_X is not set` maps to 'n'.  Comments and blanks are
    ignored; inline comments after a value are stripped.
    """
    config = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            value = value.split("#", 1)[0].strip()  # drop inline comments
            config[key] = value
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            key = line[2:].rsplit(" is not set", 1)[0].strip()
            config[key] = "n"
    return config


def fetch_text(url):
    if os.path.exists(url):
        with open(url) as f:
            return f.read()
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.text


def config_url_of(node, job):
    """Return the .config URL for a kbuild node, or None.

    Prefers the node's own artifacts; falls back to the storage layout the
    docker-compose deployment uses ({STORAGE_BASE}/{job}-{node_id}/.config).
    """
    artifacts = node.get("artifacts") or {}
    url = artifacts.get("_config") or artifacts.get(".config")
    if url:
        return url
    return f"{STORAGE_BASE}/{job}-{node['id']}/.config"


def pick_nodes(job, older_id, newer_id):
    """Resolve the two kbuild nodes to compare.

    Explicit ids take precedence; otherwise the newest two done/pass nodes
    of the job are used, in chronological order: (older, newer).  The API
    filters (state=done, result=pass) are pushed down so pagination stays
    cheap even on the busy production job.
    """
    if older_id and newer_id:
        return get_node(older_id), get_node(newer_id)

    nodes = list_nodes(job, kind="kbuild", state="done", result="pass")
    if len(nodes) < 2:
        sys.exit(
            f"Need at least 2 passing kbuild nodes for '{job}', "
            f"found {len(nodes)}"
        )
    nodes.sort(key=lambda n: n.get("created") or "")
    return nodes[-2], nodes[-1]


def diff_config(prev, curr):
    """Return (added, removed, changed) going from prev -> curr."""
    added, removed, changed = [], [], []
    for key in sorted(set(prev) | set(curr)):
        if key not in prev:
            added.append((key, curr[key]))
        elif key not in curr:
            removed.append((key, prev[key]))
        elif prev[key] != curr[key]:
            changed.append((key, prev[key], curr[key]))
    return added, removed, changed


def commit_of(node):
    revision = (node.get("data") or {}).get("kernel_revision") or {}
    return revision.get("commit", "?")[:12]


def build_report(job, older, newer, prev_cfg, prev_url, curr_cfg, curr_url):
    added, removed, changed = diff_config(prev_cfg, curr_cfg)
    return {
        "job": job,
        "older": {
            "id": older["id"],
            "commit": commit_of(older),
            "created": older.get("created"),
            "config": prev_url,
        },
        "newer": {
            "id": newer["id"],
            "commit": commit_of(newer),
            "created": newer.get("created"),
            "config": curr_url,
        },
        "total_options": {"older": len(prev_cfg), "newer": len(curr_cfg)},
        "drift": {
            "added": [{"option": k, "value": v} for k, v in added],
            "removed": [{"option": k, "value": v} for k, v in removed],
            "changed": [
                {"option": k, "old": o, "new": n} for k, o, n in changed
            ],
        },
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "total": len(added) + len(removed) + len(changed),
        },
    }


def print_text_report(report, cap):
    s = report["summary"]
    print(f"Config drift: {report['job']}")
    print(
        f"  older: {report['older']['id']}  commit={report['older']['commit']}"
    )
    print(
        f"  newer: {report['newer']['id']}  commit={report['newer']['commit']}"
    )
    print(
        f"  options: {report['total_options']['older']} -> "
        f"{report['total_options']['newer']}"
    )
    print(
        f"  drift: +{s['added']} added, -{s['removed']} removed, "
        f"~{s['changed']} changed  ({s['total']} total)"
    )

    rows = [
        ("added", [(f"+ {k}={v}",) for k, v in report["drift"]["added"]]),
        (
            "removed",
            [(f"- {k} (was {v})",) for k, v in report["drift"]["removed"]],
        ),
        (
            "changed",
            [(f"~ {k}: {o} -> {n}",) for k, o, n in report["drift"]["changed"]],
        ),
    ]
    for label, lines in rows:
        if not lines:
            continue
        shown = lines[:cap] if cap else lines
        print(f"  {label}:")
        for (line,) in shown:
            print(f"    {line}")
        if cap and len(lines) > cap:
            print(f"    ... and {len(lines) - cap} more")


def main():
    p = argparse.ArgumentParser(
        description="Detect kernel config drift between two kbuild nodes",
        epilog="examples:\n"
        "  %(prog)s                     # newest two passing builds\n"
        "  %(prog)s --older ID --newer ID\n"
        "  %(prog)s --json --max-lines 20",
    )
    p.add_argument(
        "--job",
        default="kbuild-gcc-14-riscv",
        help="kbuild job name (default: %(default)s)",
    )
    p.add_argument("--older", help="older kbuild node id")
    p.add_argument("--newer", help="newer kbuild node id")
    p.add_argument(
        "--older-config", help="override .config URL/path for the older node"
    )
    p.add_argument(
        "--newer-config", help="override .config URL/path for the newer node"
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit a JSON report instead of human-readable text",
    )
    p.add_argument(
        "--max-lines",
        type=int,
        default=0,
        help="cap per-category listing at N lines (0 = unlimited)",
    )
    args = p.parse_args()

    older, newer = pick_nodes(args.job, args.older, args.newer)

    prev_url = args.older_config or config_url_of(older, args.job)
    curr_url = args.newer_config or config_url_of(newer, args.job)
    try:
        prev_cfg = parse_config(fetch_text(prev_url))
        curr_cfg = parse_config(fetch_text(curr_url))
    except requests.exceptions.RequestException as error:
        sys.exit(f"Could not fetch .config: {error}")
    except (OSError, UnicodeDecodeError) as error:
        sys.exit(f"Could not read .config: {error}")

    # A 200 response that is not a .config (HTML index/auth page, truncated
    # download) parses to {}: reporting drift on that would be nonsense.
    if not prev_cfg or not curr_cfg:
        sys.exit(
            f"Empty .config parsed (older: {len(prev_cfg)} options, "
            f"newer: {len(curr_cfg)} options) - check "
            f"{prev_url} and {curr_url}"
        )

    report = build_report(
        args.job, older, newer, prev_cfg, prev_url, curr_cfg, curr_url
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text_report(report, args.max_lines)

    # Non-zero exit signals drift, so this can gate CI / alerting.
    return 1 if report["summary"]["total"] else 0


if __name__ == "__main__":
    sys.exit(main())
