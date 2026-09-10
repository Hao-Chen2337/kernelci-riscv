#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Regression trend recorder for the KernelCI riscv pipeline.
#
# The pipeline already records every test run as a node in the API, so the
# result history (the "trend") is inherently persisted.  This tool layers two
# things on top of that history:
#
#   * `trend`  - render the pass/fail history of the tracked test jobs as a
#                time series (commit -> result), so drift over builds is
#                visible at a glance.
#   * `track`  - scan that history for pass -> fail transitions and create
#                `kind=regression` nodes in the API, turning a one-off failure
#                into a persistent, queryable regression record (with the
#                first-failing and last-passing nodes linked).
#   * `watch`  - loop `track` so regressions are recorded automatically.
#
# Read/write split:
#   * `trend` is read-only: GET requests only, no KCI_API_TOKEN required, and
#     it works against both the local API and the public production API
#     (https://api.kernelci.org).
#   * `track` / `watch` create nodes (POST).  They require KCI_API_TOKEN and
#     must run against the local API: the production API is read-only from
#     this tooling's point of view, and local JWTs are not accepted there.
#
# Idempotent: re-running `track` never creates a duplicate regression node
# for the same failing run.
#
# Examples:
#   python3 scripts/regression_tracker.py trend --jobs kselftest-riscv-pull-labs
#   python3 scripts/regression_tracker.py track --dry-run
#   python3 scripts/regression_tracker.py watch --interval 60

import argparse
import os
import sys
import time

import requests

API_URL = os.environ.get("KCI_API_URL", "http://localhost:8001").rstrip("/")
# KernelCI exposes its API under the /latest prefix on api.kernelci.org; the
# local API accepts both, so always target the canonical /latest base.
API_LATEST = API_URL if API_URL.endswith("/latest") else f"{API_URL}/latest"
PRODUCTION_API_URLS = {
    "https://api.kernelci.org",
    "https://api.kernelci.org/latest",
}
PROD_READ_ONLY = (
    "production mode is read-only; writes only against the local API "
    "(KCI_API_URL=http://127.0.0.1:8001)"
)

# Test nodes whose pass/fail transitions are tracked.  These names must
# match the node `name` field in the API exactly; run `trend` with an empty
# --jobs list to see what names exist (it will show "(no runs)" per job).
# These are the PR1 pull-labs job names; the locally created demo nodes use
# a numeric suffix (-2/-3/...) and can be tracked via --jobs.
DEFAULT_JOBS = [
    "baseline-riscv-pull-labs",
    "kselftest-riscv-pull-labs",
    "kselftest-kvm-riscv-pull-labs",
]


def is_production():
    return API_URL in PRODUCTION_API_URLS


def api_headers():
    """Optional Authorization header.

    GET endpoints of the KernelCI API are public.  A local admin JWT is
    only meaningful against the local API, so it is never attached when
    KCI_API_URL points at the production API.
    """
    token = os.environ.get("KCI_API_TOKEN")
    if not token or is_production():
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
    newest runs of a busy production job.  The response carries
    {items,total,offset}, which lets us walk every page before sorting
    client-side.
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


def list_nodes(name=None, kind=None, limit=200, **filters):
    """Return *all* matching nodes, walking /nodes pages as needed."""
    params = {"limit": limit}
    if name is not None:
        params["name"] = name
    if kind is not None:
        params["kind"] = kind
    for key, value in filters.items():
        if value is not None:
            params[key] = value
    return fetch_all_nodes(params)


def require_write_access(action):
    """Guard for every command that POSTs nodes.

    POSTing is only supported against the local API: production
    (https://api.kernelci.org) is read-only from this tooling, and without
    KCI_API_TOKEN there is no identity to create nodes with at all.
    """
    if is_production():
        sys.exit(
            f"refusing to {action}: {PROD_READ_ONLY}. "
            f"Run with KCI_API_URL=http://127.0.0.1:8001 instead."
        )
    token = os.environ.get("KCI_API_TOKEN")
    if not token:
        sys.exit(
            f"KCI_API_TOKEN is not set; cannot {action} nodes. "
            f"{PROD_READ_ONLY}. Set KCI_API_TOKEN from kernelci-pipeline/.env "
            f"(local API admin JWT) to write locally."
        )


def post_node(node):
    require_write_access("create regression nodes via POST /node")
    response = requests.post(
        f"{API_LATEST}/node", json=node, headers=api_headers(), timeout=60
    )
    response.raise_for_status()
    return response.json()


def commit_of(node):
    revision = (node.get("data") or {}).get("kernel_revision") or {}
    return revision.get("commit", "?")[:12]


def existing_regressions():
    """Return the set of fail_node ids already covered by a regression node."""
    covered = set()
    for node in list_nodes(kind="regression"):
        fail_node = (node.get("data") or {}).get("fail_node")
        if fail_node:
            covered.add(str(fail_node))
    return covered


def done_runs(job):
    """Chronological list of done runs of a job."""
    runs = list_nodes(name=job, state="done")
    runs.sort(key=lambda n: (n.get("created") or "", n.get("id", "")))
    return runs


def transitions_in(runs):
    """Return (fail_node, pass_node) pairs, one per pass->fail transition.

    Consecutive failures belong to the same regression: only the first
    failing run after a pass starts a new transition, and the counter only
    re-arms after a fresh pass.
    """
    transitions = []
    last_pass = None
    for run in runs:
        result = run.get("result")
        if result == "pass":
            last_pass = run
        elif result == "fail" and last_pass is not None:
            transitions.append((run, last_pass))
            last_pass = None  # re-arm only after the next pass
    return transitions


def find_transitions(job):
    """Return transitions for a job; convenience over transitions_in()."""
    return transitions_in(done_runs(job))


def build_regression(fail_node, pass_node):
    """Construct a kind=regression node linking a first failure to its last
    pass.  Supports cross-commit regressions (the normal case), so unlike
    Regression.create_regression it does not require identical revisions."""
    data = fail_node.get("data") or {}
    return {
        "kind": "regression",
        "name": fail_node.get("name"),
        "group": fail_node.get("group"),
        "path": fail_node.get("path"),
        "state": "done",
        "result": "fail",
        "data": {
            "arch": data.get("arch"),
            "defconfig": data.get("defconfig"),
            "config_full": data.get("config_full"),
            "compiler": data.get("compiler"),
            "platform": data.get("platform"),
            "failed_kernel_revision": data.get("kernel_revision"),
            "fail_node": fail_node.get("id"),
            "pass_node": pass_node.get("id"),
        },
    }


def track_once(jobs, dry_run=False, quiet=False):
    """Create regression nodes for untracked transitions; return the count."""
    covered = existing_regressions()
    created = 0
    for job in jobs:
        for fail_node, pass_node in find_transitions(job):
            if str(fail_node.get("id")) in covered:
                if not quiet:
                    print(
                        f"skip (already tracked): {job} {fail_node.get('id')}"
                    )
                continue
            if dry_run:
                print(
                    f"[dry-run] would create regression for {job}: "
                    f"fail={fail_node.get('id')} "
                    f"pass={pass_node.get('id')}"
                )
                continue
            node = post_node(build_regression(fail_node, pass_node))
            if not node.get("id"):
                raise RuntimeError(
                    f"regression node creation for {job} returned no id: {node}"
                )
            print(
                f"created regression {node.get('id')} for {job}: "
                f"fail={fail_node.get('id')} "
                f"(commit {commit_of(fail_node)}) "
                f"pass={pass_node.get('id')} "
                f"(commit {commit_of(pass_node)})"
            )
            covered.add(str(fail_node.get("id")))
            created += 1
    if not quiet:
        print(f"track complete: {created} new regression node(s)")
    return created


def cmd_trend(args):
    for job in args.jobs:
        runs = done_runs(job)
        print(f"== {job} ==")
        if not runs:
            print("  (no runs)")
            continue
        for node in runs:
            result = node.get("result") or "?"
            print(
                f"  {node.get('created')}  {commit_of(node)}  "
                f"{result:10s}  {node.get('id')}"
            )
        transitions = transitions_in(runs)
        n_pass = sum(1 for n in runs if n.get("result") == "pass")
        n_fail = sum(1 for n in runs if n.get("result") == "fail")
        print(
            f"  -> {n_pass} pass / {n_fail} fail, "
            f"{len(transitions)} regression(s)"
        )
    return 0


def cmd_track(args):
    if not args.dry_run:
        require_write_access("track")
    track_once(args.jobs, dry_run=args.dry_run)
    return 0


def cmd_watch(args):
    require_write_access("watch")
    print(
        f"watching for regressions every {args.interval}s "
        f"(jobs: {', '.join(args.jobs)}); Ctrl-C to stop"
    )
    while True:
        try:
            created = track_once(args.jobs, quiet=True)
            if created:
                print(
                    f"{time.strftime('%H:%M:%S')} recorded "
                    f"{created} regression(s)"
                )
        except Exception as error:  # noqa: BLE001 - watch must survive any error and keep polling
            print(f"{time.strftime('%H:%M:%S')} watch error: {error}")
        time.sleep(args.interval)


def add_jobs_arg(parser):
    parser.add_argument(
        "--jobs",
        nargs="*",
        default=DEFAULT_JOBS,
        help="job node names to track (default: %(default)s)",
    )


def main():
    p = argparse.ArgumentParser(
        description="Record and report riscv selftest regression trends",
        epilog="examples:\n"
        "  %(prog)s trend --jobs kselftest-riscv-pull-labs\n"
        "  %(prog)s track --dry-run\n"
        "  %(prog)s watch --interval 60",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trend", help="render result history as a time series")
    add_jobs_arg(t)
    t.set_defaults(func=cmd_trend)

    k = sub.add_parser(
        "track", help="create regression nodes for pass->fail transitions"
    )
    add_jobs_arg(k)
    k.add_argument(
        "--dry-run",
        action="store_true",
        help="only report, do not create nodes",
    )
    k.set_defaults(func=cmd_track)

    w = sub.add_parser(
        "watch", help="loop `track` so regressions are recorded automatically"
    )
    add_jobs_arg(w)
    w.add_argument(
        "--interval",
        type=int,
        default=60,
        help="poll interval in seconds (default: %(default)s)",
    )
    w.set_defaults(func=cmd_watch)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
