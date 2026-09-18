#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Config-drift detector for the KernelCI riscv pipeline.
#
# Diffs the effective kernel `.config` of two kbuild nodes and reports the
# CONFIG_* options added, removed or changed (a kconfig change silently alters
# which selftests get built). Read-only, no token; exit 1 means "drift", so it
# can gate CI. Rationale: docs/code-notes/W2d-tools.md.

import argparse
import json
import os
import sys

# For its exception types: kcilib.api re-raises RequestException, and that is
# what this tool catches.  The HTTP itself goes through the shared client.
import requests

# scripts/kcilib/ resolved through this file's own directory (any CWD).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kcilib.api import KernelCI, local_api_url

# One owner for "where is the local API": KCI_API_URL first, else kcilib.api's
# LOCAL_API.  This file used to default to "localhost", which resolves to ::1 on
# a dual-stack host while the local stack publishes IPv4 only.
API_URL = local_api_url().rstrip("/")
# api.kernelci.org serves under /latest and the local API accepts both, so
# always target the canonical /latest base.
API_LATEST = API_URL if API_URL.endswith("/latest") else f"{API_URL}/latest"
# Storage convention of the docker-compose deployment:
# {STORAGE_BASE}/{job}-{node_id}/.config.  KCI_STORAGE_URL wins, else the port
# KCI_STORAGE_PORT names (run-local-stack.sh exports it): hardcoding 8002
# fetched from the wrong host on a deployment that moved off the default.
STORAGE_BASE = os.environ.get("KCI_STORAGE_URL") or (
    "http://localhost:{}".format(os.environ.get("KCI_STORAGE_PORT", "8002"))
)


PRODUCTION_API_URLS = {
    "https://api.kernelci.org",
    "https://api.kernelci.org/latest",
}


def is_production():
    """True when this run targets the production API."""
    return API_URL in PRODUCTION_API_URLS


def _non_negative(value):
    """argparse type for a count: a negative cap used to be accepted and then
    silently dropped the last row (lines[:-1]) while still counting it."""
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return number




def _client():
    """The shared API client (kcilib/api.py) for this deployment.

    This module used to carry its own api_get/fetch_all_nodes, near enough a
    copy of regression_tracker.py's; there is one client now.
    """
    token = None if is_production() else os.environ.get("KCI_API_TOKEN")
    return KernelCI(API_URL, token=token)


def api_get(path, params=None, retries=3):
    """GET with a few retries for the local API's idle-connection resets."""
    return _client().get(path, params, retries=retries)


def fetch_all_nodes(params):
    """Page through /nodes until every matching node has been fetched.

    /nodes truncates each response to the page limit, so one request would
    silently miss the newest nodes of a large job; the {items,total,offset}
    response lets us walk every page before sorting client-side.
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


def _drop_inline_comment(value):
    """Cut a .config value at the first '#' that is outside double quotes, so a
    quoted path or cmdline keeps its '#'; escaped quotes stay inside the string."""
    kept = []
    quoted = False
    escaped = False
    for char in value:
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "#" and not quoted:
            break
        kept.append(char)
    return "".join(kept).strip()


def parse_config(text):
    """Parse a kernel .config into {CONFIG_OPT: value}.

    `CONFIG_X=y` maps to the value after '=', `# CONFIG_X is not set` to 'n'
    even with trailing text; comments and blanks are ignored, inline comments are
    dropped unless '#' sits inside quotes.
    """
    config = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            config[key] = _drop_inline_comment(value)
        elif line.startswith("# CONFIG_") and " is not set" in line:
            key = line[2:].split(" is not set", 1)[0].strip()
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
    """Return the .config URL for a kbuild node (never None).

    The node's own artifacts win, the deployment's storage layout is the
    fallback.
    """
    artifacts = node.get("artifacts") or {}
    url = artifacts.get("_config") or artifacts.get(".config")
    if url:
        return url
    return f"{STORAGE_BASE}/{job}-{node['id']}/.config"


def pick_nodes(job, older_id, newer_id):
    """Resolve the two kbuild nodes to compare.

    Explicit ids win; otherwise the newest two done/pass nodes, in
    chronological order, as (older, newer).
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
        type=_non_negative,
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

    # A 200 that is not a .config (HTML index/auth page) parses to {}; drift
    # reported from that would be nonsense.
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
