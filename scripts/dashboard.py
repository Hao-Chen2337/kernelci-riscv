#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Dashboard: render the local job table as one read-only page.

Reads our own build index, ledger and optional local API - no extra
dependencies, unlike the upstream frontend.  Binds 127.0.0.1, writes nothing.

    ./run.sh dashboard [--port 8079] [--rows N] [--refresh SECONDS]

--port is a preference: if it is taken (WSL mirrors the Windows side's
listeners), the next free port is used and the substitution is printed.

Notes: docs/code-notes/A-sink-source-dashboard.md
"""

import argparse
import errno
import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar
from urllib.parse import parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from kcilib import api, repo_root
from kcilib.core import ledger
from kcilib.table import localrun
from kcilib.table.buildindex import BuildIndex
from kcilib.table.jobspec import DEFAULT_TESTS
from tools import config_drift, regression_tracker

# One owner for "where is the local API": kcilib.api.local_api_url().
LOCAL_API = api.local_api_url()
ROW_LIMIT = 25
NODE_LIMIT = 1000
RECENT_NODES = 12
PORT_TRIES = 20
DRIFT_CAP = 60
ACTION_LIMIT = 20

# The run.sh actions this page can launch: (name, label, run.sh argv, optional
# arg flag, confirm message or "").  One action runs at a time; each writes a
# log under work/logs/actions/ that the page links to.  Only local, read-mostly
# or dry-run-safe commands are here - `setup` and a real `prune` stay terminal.
ACTIONS = (
    ("build-index", "Pull build index",  ("build", "index"),  "days",  ""),
    ("fetch",       "Fetch & run latest", ("fetch",),         None,    ""),
    ("run",         "Run pending jobs",   ("run",),           "build", ""),
    ("worker",      "Worker (once)",      ("worker", "--once"), None,  ""),
    ("trend",       "Regression trend",   ("trend",),         None,    ""),
    ("drift",       "Config drift",       ("drift",),         None,    ""),
    ("verify",      "Run verify",         ("verify",),        None,    ""),
    ("prune",       "Prune (dry-run)",    ("prune", "--dry-run"), "keep",
     "Prune old downloads? This frees disk under work/downloads/."),
    ("stack",       "Start stack",        ("stack",),         None,
     "Start the local Docker stack?"),
    ("stop",        "Stop stack",         ("stop",),          None,
     "Stop the local Docker stack?"),
)
_ACTIONS = {action[0]: action for action in ACTIONS}


def _counts(values):
    """{value: n}, biggest first - one shape for every breakdown on the page."""
    out = {}
    for value in values:
        key = value or "-"
        out[key] = out.get(key, 0) + 1
    return sorted(out.items(), key=lambda item: (-item[1], item[0]))


def _age(stamp):
    """A timestamp as "3h ago": a build's age is how you read a stale table."""
    if not stamp:
        return ""
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - then).total_seconds()
    if seconds < 1:
        return "just now"
    for limit, unit in ((60, "s"), (3600, "m"), (86400, "h")):
        if seconds < limit:
            return f"{max(int(seconds // (limit / 60)), 1)}{unit} ago"
    return f"{int(seconds // 86400)}d ago"


def _api_state(api_url, kinds=api.COUNTED_KINDS):
    """Per kind: totals, breakdowns, and the newest nodes.

    None - not a raise - means the API is not answering, the same contract
    kcilib.api.node_counts keeps: a page must render without a stack.
    """
    if not api_url:
        return None
    client = api.client(api_url, timeout=10, retries=1)
    state = {}
    for kind in kinds:
        try:
            nodes = client.all_nodes(kind=kind, limit=NODE_LIMIT)
        except Exception:  # noqa: BLE001 - see the docstring
            return None
        nodes.sort(key=lambda node: node.get("created") or "", reverse=True)
        state[kind] = {
            "total": len(nodes),
            "by_state": _counts(node.get("state") for node in nodes),
            "by_result": _counts(node.get("result") for node in nodes),
            "by_name": _counts(node.get("name") for node in nodes),
            "recent": [{
                "id": node.get("id") or "",
                "name": node.get("name") or "?",
                "state": node.get("state") or "-",
                "result": node.get("result") or "-",
                "created": node.get("created") or "",
                "owner": node.get("owner") or "-",
                "retries": node.get("retry_counter") or 0,
            } for node in nodes[:RECENT_NODES]],
        }
    return state


def _config_drift(builds):
    """Config drift between the two newest local .config files, oldest -> newest.

    Reads work/downloads/<id>/.config (written by fetch); the build index adds
    each side's commit.  None when there are not two files to compare.  Pure and
    read-only: the dashboard never downloads a config itself.
    """
    root = os.path.join(repo_root(), "work", "downloads")
    if not os.path.isdir(root):
        return None
    commit_of = {b.build_id: (b.commit or "")[:12] for b in builds}
    found = []
    for node_id in os.listdir(root):
        cfg_path = os.path.join(root, node_id, ".config")
        if not os.path.isfile(cfg_path):
            continue
        try:
            with open(cfg_path, encoding="utf-8") as handle:
                config = config_drift.parse_config(handle.read())
        except OSError:
            continue
        found.append((os.path.getmtime(cfg_path), node_id, config))
    if len(found) < 2:
        return None
    found.sort()  # oldest first by mtime
    _, old_id, old_cfg = found[-2]
    _, new_id, new_cfg = found[-1]
    added, removed, changed = config_drift.diff_config(old_cfg, new_cfg)
    return {
        "older": {"id": old_id, "commit": commit_of.get(old_id, "")},
        "newer": {"id": new_id, "commit": commit_of.get(new_id, "")},
        "total_options": {"older": len(old_cfg), "newer": len(new_cfg)},
        "added": added, "removed": removed, "changed": changed,
        "summary": {"added": len(added), "removed": len(removed),
                    "changed": len(changed),
                    "total": len(added) + len(removed) + len(changed)},
    }


def _regressions(runs):
    """Pass->fail transitions per test, with the two commits on each side.

    Consecutive failures are one regression (transitions_in's rule), so the list
    length is the regression count and each entry names the failing build and the
    last build that passed.  Newest-first.
    """
    by_test = {}
    for row in sorted(runs, key=lambda r: r["timestamp"] or ""):
        by_test.setdefault(row["test"], []).append({
            "result": row["verdict"],
            "build_id": row["build_id"],
            "commit": row["commit"],
            "created": row["timestamp"],
        })
    out = []
    for test, seq in by_test.items():
        for fail, prev in regression_tracker.transitions_in(seq):
            out.append({
                "test": test,
                "fail": {"build_id": fail["build_id"], "commit": fail["commit"],
                         "created": fail["created"]},
                "pass": {"build_id": prev["build_id"], "commit": prev["commit"],
                         "created": prev["created"]},
            })
    out.sort(key=lambda r: r["fail"]["created"] or "", reverse=True)
    return out


def collect(db, api_url=None, limit=ROW_LIMIT):
    """Everything the page shows, as plain data (also served as JSON)."""
    index = BuildIndex(db)
    builds = index.all()
    ran = localrun.ran_tests()

    runs = []
    for build_id, tests in ran.items():
        records = ledger.read_results(build_id)
        for test in tests:
            record = records.get(test) or {}
            revision = record.get("revision") or {}
            subject = (revision.get("commit_message") or "").splitlines()
            runs.append({
                "build_id": build_id,
                "test": test,
                "verdict": record.get("verdict"),
                "exit_code": record.get("exit_code"),
                "source": record.get("source"),
                "job": record.get("job"),
                "timestamp": record.get("timestamp"),
                "detail": record.get("detail") or "",
                "log": record.get("log"),
                "artifacts_dir": record.get("artifacts_dir"),
                "results": record.get("results"),
                "commit": (revision.get("commit") or "")[:12],
                "branch": revision.get("branch") or "",
                "subject": (subject[0] if subject else "")[:80],
            })
    runs.sort(key=lambda row: row["timestamp"] or "", reverse=True)

    # The runs grouped by the build they came from: one build, its tests, its commit.
    build_of = {build.build_id: build for build in builds}
    groups = {}
    for row in runs:
        groups.setdefault(row["build_id"], []).append(row)
    run_groups = []
    for build_id, rows in groups.items():
        build = build_of.get(build_id)
        run_groups.append({
            "build_id": build_id,
            "tree": getattr(build, "tree", None),
            "describe": getattr(build, "describe", None),
            # The commit is the build's, not the test's: the index is the
            # authority, and only fetch writes a revision into its records.
            "commit": (getattr(build, "commit", None)
                       or next((r["commit"] for r in rows if r["commit"]), "")),
            "indexed": build is not None,
            "created": getattr(build, "created", None) or rows[0].get("timestamp"),
            "verdicts": _counts(row["verdict"] for row in rows),
            "rows": rows,
        })
    run_groups.sort(key=lambda g: max(r["timestamp"] or "" for r in g["rows"]),
                    reverse=True)

    # Per test: is this test holding, or getting worse.
    per_test = {}
    for row in runs:
        entry = per_test.setdefault(row["test"], {
            "test": row["test"], "runs": 0, "pass": 0, "fail": 0, "other": 0,
            "last": None, "last_when": ""})
        entry["runs"] += 1
        if row["verdict"] == "pass":
            entry["pass"] += 1
        elif row["verdict"] == "fail":
            entry["fail"] += 1
        else:
            entry["other"] += 1
        if (row["timestamp"] or "") > entry["last_when"]:
            entry["last"], entry["last_when"] = row["verdict"], row["timestamp"]

    # Pass->fail transitions (the regression analysis) and the trend strip.
    regressions = _regressions(runs)
    regr_by_test = {}
    for reg in regressions:
        regr_by_test[reg["test"]] = regr_by_test.get(reg["test"], 0) + 1
    series = {}
    for row in sorted(runs, key=lambda r: r["timestamp"] or ""):
        series.setdefault(row["test"], []).append(row["verdict"])
    for entry in per_test.values():
        entry["series"] = series.get(entry["test"], [])
        entry["regressions"] = regr_by_test.get(entry["test"], 0)

    specs, skipped, checked = localrun.todo(index, tests=DEFAULT_TESTS)

    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "index": {
            "count": index.count(),
            "path": os.path.relpath(index.path),
            "trees": _counts(build.tree or "?" for build in builds),
            "builds": [{
                "build_id": b.build_id, "tree": b.tree, "describe": b.describe,
                "created": b.created, "commit": b.commit,
                "ran": len(ran.get(b.build_id, ())),
                "tests": len(DEFAULT_TESTS),
            } for b in builds[:limit]],
        },
        "ledger": {
            "runs": runs,
            "total": len(runs),
            "builds": len(run_groups),
            "groups": run_groups,
            "verdicts": _counts(row["verdict"] for row in runs),
            "sources": _counts(row["source"] for row in runs),
            "regressions": len(regressions),
            "tests": sorted(per_test.values(),
                            key=lambda e: (-e["runs"], e["test"])),
        },
        "pending": {
            "count": len(specs), "checked": checked, "skipped": len(skipped),
            "by_test": _counts(spec.test for spec in specs),
            "by_tree": _counts(getattr(spec.build, "tree", None) for spec in specs),
            "skip_reasons": _counts(reason for _b, _t, reason in skipped),
            "items": [{"build_id": s.build_id, "test": s.test,
                       "tree": getattr(s.build, "tree", None),
                       "describe": getattr(s.build, "describe", None)}
                      for s in specs[:limit]],
        },
        "config_drift": _config_drift(builds),
        "regressions": regressions,
        "api": _api_state(api_url),
    }


CSS = """body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#222}
header{background:#12304d;color:#fff;padding:14px 22px}
header h1{margin:0;font-size:17px;font-weight:600}
header .sub{opacity:.75;font-size:12px;margin-top:3px}
.stats{display:flex;gap:28px;padding:12px 22px;background:#1b4266;color:#fff;flex-wrap:wrap}
.stat b{display:block;font-size:22px;font-weight:700;line-height:1.2}
.stat span{font-size:11.5px;opacity:.75;text-transform:uppercase;letter-spacing:.04em}
main{padding:18px 22px;display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:16px;align-items:start}
section{background:#fff;border:1px solid #e2e5ea;border-radius:8px;padding:12px 14px}
section.wide{grid-column:1/-1}
h2{margin:0 0 8px;font-size:14px;color:#12304d}
h2 .muted{font-weight:400}
h3{margin:14px 0 4px;font-size:12.5px;color:#12304d}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td,th{padding:3px 6px;border-bottom:1px solid #eef0f3;text-align:left;vertical-align:top}
th{color:#68727f;font-weight:600;background:#fbfcfd}
tbody tr:hover{background:#f8fafc}
code{font-family:ui-monospace,monospace;font-size:12px}
.pass{color:#1a7f37;font-weight:600}.fail{color:#b42318;font-weight:600}
.infra,.error{color:#b54708;font-weight:600}.skip,.available{color:#68727f}
.count{font-size:22px;font-weight:700;color:#12304d}
.muted{color:#68727f;font-size:12px}
.flt{width:100%;box-sizing:border-box;margin:6px 0 8px;padding:4px 8px;
 border:1px solid #d7dbe0;border-radius:5px;font-size:12.5px}
.chip{font-size:11.5px;color:#68727f;user-select:none;display:inline-block;margin:0 0 6px}
.grp td{background:#f2f5f8;border-left:3px solid #12304d;padding:6px 8px}
.grp .id{font-family:ui-monospace,monospace;font-weight:600}
.grp .r{margin-left:9px}
.bar{display:flex;height:9px;width:84px;border-radius:5px;overflow:hidden;background:#e7eaee}
.bar i{display:block}
.bar .b-pass{background:#1a7f37}.bar .b-fail{background:#b42318}
.bar .b-skip{background:#c9ced6}
details{margin-top:6px}summary{cursor:pointer;font-size:12px;color:#12304d}
.foot{padding:10px 22px 22px;color:#68727f;font-size:11.5px}
.spark{display:inline-flex;gap:1px;align-items:flex-end;height:16px}
.spark i{width:6px;height:13px;border-radius:1px;background:#c9ced6}
.spark .s-pass{background:#1a7f37}.spark .s-fail{background:#b42318}
.tbar{display:flex;height:10px;border-radius:5px;overflow:hidden;background:#e7eaee;min-width:200px;max-width:360px}
.tbar i{display:block}
.acts{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
.act{display:inline-flex;gap:6px;align-items:center;margin:0}
.act button{background:#12304d;color:#fff;border:0;border-radius:5px;padding:5px 12px;
 font-size:12.5px;cursor:pointer}
.act button:hover{background:#1b4266}
.act input.arg{border:1px solid #d7dbe0;border-radius:5px;padding:4px 7px;
 font-size:12px;width:150px}"""

JS = """var BAD = ['fail', 'infra', 'error'];
function dashApply(id){
 var t = document.getElementById(id); if(!t) return;
 var box = document.querySelector('input.flt[data-target="' + id + '"]');
 var q = box ? box.value.toLowerCase() : '';
 var fo = document.getElementById('failonly');
 var failsOnly = !!(fo && fo.checked && id === 'runs');
 var groups = t.querySelectorAll('tbody tr.grp');
 if(groups.length){
  groups.forEach(function(g){
   var any = false, r = g.nextElementSibling;
   while(r && !r.classList.contains('grp')){
    var bad = BAD.indexOf(r.dataset.verdict) >= 0;
    r.hidden = (q && r.textContent.toLowerCase().indexOf(q) < 0)
               || (failsOnly && !bad);
    if(!r.hidden) any = true;
    r = r.nextElementSibling;
   }
   g.hidden = !any;
  });
  return;
 }
 t.querySelectorAll('tbody tr').forEach(function(r){
  r.hidden = !!q && r.textContent.toLowerCase().indexOf(q) < 0;
 });
}
function dashWire(){
 document.querySelectorAll('input.flt').forEach(function(box){
  box.addEventListener('input', function(){ dashApply(box.dataset.target); });
 });
 var fo = document.getElementById('failonly');
 if(fo) fo.addEventListener('change', function(){ dashApply('runs'); });
}
function dashPoll(){
 var el = document.getElementById('actions-status');
 if(!el) return;
 fetch('/actions').then(function(r){return r.text()}).then(function(h){el.innerHTML=h;});
}
function dashAction(form){
 if(form.dataset.confirm && !confirm(form.dataset.confirm)) return false;
 fetch(form.getAttribute('action'), {
  method: 'POST',
  headers: {'Content-Type': 'application/x-www-form-urlencoded'},
  body: new URLSearchParams(new FormData(form)).toString()
 }).then(function(r){return r.json()})
  .then(function(j){ if(j && !j.ok){ alert(j.error || 'failed to start'); } dashPoll(); })
  .catch(function(){ dashPoll(); });
 return false;
}"""


def _table(headers, rows, table_id=None):
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows)
    ident = f' id="{table_id}"' if table_id else ""
    return f"<table{ident}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _link(path):
    """A record's file: the console log is a real link; other paths are hoverable."""
    if not path:
        return '<span class="muted">-</span>'
    text = str(path)
    shown = text if len(text) <= 38 else "..." + text[-35:]
    if text.startswith("work/logs/"):
        name = os.path.basename(text)
        return (f'<a href="/logs/{html.escape(name)}">'
                f'<code>{html.escape(shown)}</code></a>')
    return f'<code title="{html.escape(text)}">{html.escape(shown)}</code>'


def _bar_width(count, total):
    return f"{count * 100 / total:.1f}%"


def _result_bar(results):
    """One run's pass/fail/skip split, as text plus a small stacked bar."""
    if not isinstance(results, dict) or not results.get("total"):
        return '<span class="muted">-</span>'
    total = results["total"]
    failed = results.get("failed") or 0
    skipped = results.get("skipped") or 0
    passed = max(total - failed - skipped, 0)
    return (
        f'<span class="pass">{passed}</span>/<span class="fail">{failed}</span>'
        f'/<span class="skip">{skipped}</span>'
        f'<div class="bar" title="{passed} pass, {failed} fail, {skipped} skip">'
        f'<i class="b-pass" style="width:{_bar_width(passed, total)}"></i>'
        f'<i class="b-fail" style="width:{_bar_width(failed, total)}"></i>'
        f'<i class="b-skip" style="width:{_bar_width(skipped, total)}"></i></div>')


def _breakdown(pairs):
    if not pairs:
        return '<span class="muted">-</span>'
    return " ".join(f'<span class="muted">{html.escape(str(name))} {count}</span>'
                    for name, count in pairs)


def _sparkline(series):
    """A test's verdict history, oldest first, as a strip of coloured cells."""
    cells = []
    for i, verdict in enumerate(series or []):
        cls = f"s-{verdict}" if verdict in ("pass", "fail") else ""
        cells.append(f'<i class="{cls}" title="#{i + 1} '
                     f'{html.escape(str(verdict))}"></i>')
    return f'<span class="spark">{"".join(cells)}</span>'


_TREE_COLORS = ("#12304d", "#1a7f37", "#b42318", "#b54708", "#68727f",
                "#1b4266", "#8a5a2b")


def _tree_bar(pairs):
    """The tree split as a stacked bar (one colour per tree)."""
    total = sum(count for _name, count in pairs) or 1
    segs = []
    for i, (name, count) in enumerate(pairs):
        colour = _TREE_COLORS[i % len(_TREE_COLORS)]
        segs.append(f'<i title="{html.escape(str(name))}: {count}" '
                    f'style="width:{count * 100 / total:.1f}%;'
                    f'background:{colour}"></i>')
    return f'<div class="tbar">{"".join(segs)}</div>'


def _drift_section(drift):
    """The config-drift comparison, or a note when there is nothing to compare."""
    if not drift:
        return ('<p class="muted">No two local .config files to diff yet - '
                './run.sh fetch downloads work/downloads/&lt;id&gt;/.config.</p>')

    def side(b):
        commit = (f' <span class="muted">{html.escape(b["commit"])}</span>'
                  if b["commit"] else "")
        return f'<code>{html.escape(b["id"][:16])}</code>{commit}'

    opts = drift["total_options"]
    head = (f'<p>{side(drift["older"])} &rarr; {side(drift["newer"])} &middot; '
            f'{opts["older"]} &rarr; {opts["newer"]} options</p>')
    summary = drift["summary"]
    if summary["total"] == 0:
        return head + '<p class="muted">No drift: the two configs are identical.</p>'
    parts = [head]
    for label, pairs, cell in (
            ("added", drift["added"],
             lambda k, v: f'<li><code>{html.escape(k)}</code> = '
                          f'<span class="pass">{html.escape(v)}</span></li>'),
            ("removed", drift["removed"],
             lambda k, v: f'<li><code>{html.escape(k)}</code> = '
                          f'<span class="fail">{html.escape(v)}</span></li>')):
        if not pairs:
            continue
        shown = pairs[:DRIFT_CAP]
        tail = (f'<li class="muted">&hellip;and {len(pairs) - len(shown)} more</li>'
                if len(pairs) > len(shown) else "")
        parts.append(f'<h3>{label} ({summary[label]})</h3><ul>'
                     + "".join(cell(k, v) for k, v in shown) + tail + "</ul>")
    if drift["changed"]:
        shown = drift["changed"][:DRIFT_CAP]
        tail = (f'<li class="muted">&hellip;and '
                f'{len(drift["changed"]) - len(shown)} more</li>'
                if len(drift["changed"]) > len(shown) else "")
        parts.append(f'<h3>changed ({summary["changed"]})</h3><ul>' + "".join(
            f'<li><code>{html.escape(k)}</code>: '
            f'<span class="fail">{html.escape(o)}</span> &rarr; '
            f'<span class="pass">{html.escape(n)}</span></li>'
            for k, o, n in shown) + tail + "</ul>")
    return "".join(parts)


def _regression_section(regressions):
    """Each pass->fail transition as a row: which build broke, from which pass."""
    if not regressions:
        return ('<p class="muted">No pass &rarr; fail transitions in the ledger '
                'yet - a regression appears once a test that passed starts '
                'failing.</p>')
    rows = []
    for reg in regressions:
        def cell(side):
            commit = (f' <span class="muted">{html.escape(side["commit"])}</span>'
                      if side["commit"] else "")
            return f'<code>{html.escape(side["build_id"][:16])}</code>{commit}'
        rows.append([
            html.escape(reg["test"] or "?"),
            cell(reg["fail"]),
            cell(reg["pass"]),
            html.escape(_age(reg["fail"]["created"])),
        ])
    return _table(["test", "failing build", "last passing build", "when"], rows)


def _spawn_action(name, arg):
    """Start one run.sh action in the background; returns (ok, error, entry).

    One action runs at a time - starting a second is refused, not queued, so two
    long jobs never write builds.db / the ledger / downloads at once.  The child
    inherits nothing except stdout into its own log; the page links to it.
    """
    definition = _ACTIONS.get(name)
    if not definition:
        return False, f"unknown action {name!r}", None
    _, label, argv, flag, _confirm = definition
    for entry in Handler.actions.values():
        if entry["running"]:
            return False, f"already running: {entry['label']}", None
    command = [os.path.join(repo_root(), "run.sh"), *argv]
    if arg and flag:
        command += [f"--{flag}", arg]
    Handler._action_seq += 1
    ident = f"{name}-{int(time.time())}-{Handler._action_seq}"
    log_dir = os.path.join(repo_root(), "work", "logs", "actions")
    os.makedirs(log_dir, exist_ok=True)
    rel_log = os.path.join("work", "logs", "actions", f"{ident}.log")
    with open(os.path.join(repo_root(), rel_log), "wb") as handle:
        proc = subprocess.Popen(command, stdout=handle,
                                stderr=subprocess.STDOUT, cwd=repo_root(),
                                close_fds=True)
    entry = {
        "name": name, "label": label, "id": ident, "arg": arg,
        "command": " ".join(command), "start": time.time(), "log": rel_log,
        "proc": proc, "running": True, "exit": None, "end": None,
    }
    Handler.actions[ident] = entry
    return True, "", entry


def _reap_actions():
    """Move any finished subprocess from running to done (exit code + end)."""
    for entry in Handler.actions.values():
        if not entry["running"]:
            continue
        code = entry["proc"].poll()
        if code is not None:
            entry["running"] = False
            entry["exit"] = code
            entry["end"] = time.time()


def _action_forms():
    """The action buttons: one form each, with an arg box where the flag asks."""
    forms = []
    for name, label, _argv, flag, confirm in ACTIONS:
        arg_box = (f'<input type="text" name="arg" placeholder="{flag}" '
                   f'class="arg">' if flag else "")
        confirm_attr = (f' data-confirm="{html.escape(confirm, quote=True)}"'
                        if confirm else "")
        forms.append(
            f'<form class="act" action="/action/{name}" method="post" '
            f'onsubmit="return dashAction(this)"{confirm_attr}>'
            f'<button type="submit">{html.escape(label)}</button>{arg_box}</form>')
    return '<div class="acts">' + "".join(forms) + "</div>"


def _actions_status():
    """The running + recent action list, as an HTML fragment (also /actions)."""
    _reap_actions()
    items = sorted(Handler.actions.values(),
                   key=lambda e: e["start"], reverse=True)[:ACTION_LIMIT]
    if not items:
        return '<p class="muted">No actions run yet - pick one above.</p>'
    rows = []
    for entry in items:
        link = (f'<a href="/logs/actions/{html.escape(os.path.basename(entry["log"]))}">'
                f'<code>{html.escape(entry["label"])}</code></a>')
        if entry["running"]:
            state = '<span class="infra">running</span>'
        elif entry["exit"] == 0:
            state = '<span class="pass">done</span>'
        else:
            state = f'<span class="fail">exit {entry["exit"]}</span>'
        took = int((entry["end"] or time.time()) - entry["start"])
        rows.append([
            link,
            html.escape(entry["arg"] or "-"),
            state,
            html.escape(_age(entry["start"])),
            f"{took}s",
        ])
    return _table(["action", "arg", "state", "started", "took"], rows)


def _runs_table(groups):
    """The ledger as one table: a header row per build, its tests underneath."""
    headers = ["test", "verdict", "exit", "pass/fail/skip", "source", "when",
               "detail", "log / artifacts"]
    out = []
    for group in groups:
        # A seeded local-stack build is in the ledger but not in the index.
        tree = group["tree"] or ("not indexed" if not group["indexed"] else "?")
        bits = [f'<span class="r muted">{html.escape(tree)}</span>']
        if group["describe"]:
            bits.append(f'<span class="r">{html.escape(group["describe"][:54])}</span>')
        if group["commit"]:
            bits.append(f'<span class="r"><code>{html.escape(group["commit"][:12])}'
                        f'</code></span>')
        bits.append(f'<span class="r muted">{html.escape(_age(group["created"]))}</span>')
        bits.append(f'<span class="r muted">{len(group["rows"])} run(s) &middot; '
                    f'{_breakdown(group["verdicts"])}</span>')
        out.append(
            f'<tr class="grp"><td colspan="{len(headers)}">'
            f'<span class="id">{html.escape(group["build_id"])}</span>'
            + "".join(bits) + "</td></tr>")
        for row in group["rows"]:
            cells = [
                html.escape(row["test"] or "?"),
                (f'<span class="{html.escape(row["verdict"] or "")}">'
                 f'{html.escape(row["verdict"] or "-")}</span>'),
                html.escape("-" if row["exit_code"] is None
                            else str(row["exit_code"])),
                _result_bar(row["results"]),
                html.escape(str(row["source"] or "-")),
                (f'<span title="{html.escape(str(row["timestamp"] or ""))}">'
                 f'{html.escape(_age(row["timestamp"]))}</span>'),
                html.escape((row["detail"] or "")[:60]),
                _link(row["log"] or row["artifacts_dir"]),
            ]
            out.append(f'<tr data-verdict="{html.escape(row["verdict"] or "-")}">'
                       + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    return (f'<table id="runs"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(out)}</tbody></table>')


def render(data, api_url, refresh=0):
    index, led, pend = data["index"], data["ledger"], data["pending"]

    build_rows = [[
        f"<code>{html.escape(b['build_id'][:16])}</code>",
        html.escape(b["tree"] or "?"),
        html.escape((b["describe"] or "")[:46]),
        (f'<span title="{html.escape(str(b["created"] or ""))}">'
         f'{html.escape(_age(b["created"]))}</span>'),
        f"<code>{html.escape((b['commit'] or '')[:12])}</code>",
        f'{b["ran"]}/{b["tests"]}',
    ] for b in index["builds"]]

    test_rows = [[
        html.escape(entry["test"] or "?"),
        str(entry["runs"]),
        f'<span class="pass">{entry["pass"]}</span>',
        f'<span class="fail">{entry["fail"]}</span>',
        str(entry["other"]),
        (f'<span class="{html.escape(entry["last"] or "")}">'
         f'{html.escape(entry["last"] or "-")}</span>'),
        html.escape(_age(entry["last_when"])),
        str(entry["regressions"]),
        _sparkline(entry["series"]),
    ] for entry in led["tests"]]

    todo_rows = [[
        f"<code>{html.escape(t['build_id'][:16])}</code>",
        html.escape(t["test"] or "?"),
        html.escape(t["tree"] or "?"),
        html.escape((t["describe"] or "")[:40]),
    ] for t in pend["items"]]

    api_html = '<p class="muted">not reachable - start it with ./run.sh stack</p>'
    api_total = "-"
    if data["api"]:
        api_total = sum(info["total"] for info in data["api"].values())
        blocks = []
        for kind, info in data["api"].items():
            recent = [[
                f"<code>{html.escape(n['id'][:12])}</code>",
                html.escape(n["name"]),
                f'<span class="{html.escape(n["state"])}">{html.escape(n["state"])}</span>',
                f'<span class="{html.escape(n["result"])}">{html.escape(n["result"])}</span>',
                html.escape(_age(n["created"])),
                html.escape(n["owner"]),
                str(n["retries"]),
            ] for n in info["recent"]]
            blocks.append(
                f'<h3>{html.escape(kind)} <span class="muted">{info["total"]}</span></h3>'
                f'<div class="muted">state: {_breakdown(info["by_state"])}</div>'
                f'<div class="muted">result: {_breakdown(info["by_result"])}</div>'
                f'<div class="muted">name: {_breakdown(info["by_name"])}</div>'
                + (_table(["id", "name", "state", "result", "created",
                           "owner", "retries"], recent) if recent else ""))
        api_html = "".join(blocks)

    pending_detail = (
        f'<div class="muted">by test: {_breakdown(pend["by_test"])}</div>'
        f'<div class="muted">by tree: {_breakdown(pend["by_tree"])}</div>'
        + (f'<div class="muted">skipped: {_breakdown(pend["skip_reasons"])}</div>'
           if pend["skip_reasons"] else ""))
    meta = (f'<meta http-equiv="refresh" content="{int(refresh)}">'
            if refresh > 0 else "")
    every = f" (auto-refresh {int(refresh)}s)" if refresh > 0 else ""

    return f"""<!doctype html><html><head><meta charset="utf-8">{meta}
<title>local job table</title><style>{CSS}</style></head><body>
<header><h1>RISC-V pull lab &mdash; local job table</h1>
<div class="sub">index {html.escape(index['path'])} &middot;
 ledger {html.escape(os.path.relpath(ledger.results_dir()))} &middot;
 local API {html.escape(api_url or 'off')} &middot; read-only &middot;
 rendered {time.strftime('%H:%M:%S', time.localtime())}{every}</div>
</header>
<div class="stats">
 <div class="stat"><b>{index['count']}</b><span>indexed builds</span></div>
 <div class="stat"><b>{led['total']}</b><span>recorded runs</span></div>
 <div class="stat"><b>{led['builds']}</b><span>builds tested</span></div>
 <div class="stat"><b class="pass">{dict(led['verdicts']).get('pass', 0)}</b><span>pass</span></div>
 <div class="stat"><b class="fail">{dict(led['verdicts']).get('fail', 0)}</b><span>fail</span></div>
 <div class="stat"><b>{pend['count']}</b><span>pending runs</span></div>
 <div class="stat"><b>{led['regressions']}</b><span>regressions</span></div>
 <div class="stat"><b>{api_total}</b><span>API nodes</span></div>
</div>
<main>
<section class="wide"><h2>Run
 <span class="muted">start a command - it runs in the background, one at a time</span></h2>
{_action_forms()}
<div id="actions-status">
{_actions_status()}
</div>
</section>
<section class="wide"><h2>Runs (ledger)
 <span class="muted">{led['total']} run(s) over {led['builds']} build(s) &middot;
 verdicts: {_breakdown(led['verdicts'])} &middot; writers: {_breakdown(led['sources'])}</span></h2>
<input class="flt" type="search" placeholder="filter runs: build, test, tree, commit, detail, source..."
 data-target="runs">
<label class="chip"><input type="checkbox" id="failonly"> problems only (verdict fail / infra / error)</label>
{_runs_table(led['groups'])}
</section>
<section><h2>Build index <span class="muted">{index['count']} build(s)</span></h2>
{_tree_bar(index['trees'])}
<div class="muted">{_breakdown(index['trees'])}</div>
<input class="flt" type="search" placeholder="filter builds" data-target="builds">
{_table(["build", "tree", "describe", "age", "commit", "ran"], build_rows, "builds")}
</section>
<section><h2>By test <span class="muted">over {led['total']} run(s)</span></h2>
{_table(["test", "runs", "pass", "fail", "other", "last", "when", "regr", "trend"],
         test_rows)}
</section>
<section><h2>Config drift
 <span class="muted">between the two newest local .config</span></h2>
{_drift_section(data["config_drift"])}
</section>
<section><h2>Regressions <span class="muted">{led['regressions']} transition(s)</span></h2>
{_regression_section(data["regressions"])}
</section>
<section><h2>Pending <span class="muted">{pend['count']} over
 {pend['checked']} indexed build(s) &middot; {pend['skipped']} skipped</span></h2>
{pending_detail}
<details><summary>show the first {len(pend['items'])} pending run(s)</summary>
<input class="flt" type="search" placeholder="filter pending" data-target="pending">
{_table(["build", "test", "tree", "describe"], todo_rows, "pending")}
</details>
</section>
<section class="wide"><h2>Local API <span class="muted">{html.escape(api_url or 'off')}
 &middot; newest {RECENT_NODES} per kind</span></h2>
{api_html}
</section>
</main>
<div class="foot">Generated by scripts/dashboard.py from the build index and
 work/results/ - no writes, no upstream calls.  ./run.sh results prints the same
 ledger as text; ./run.sh summary adds the index and the API counts.</div>
<script>{JS}
dashWire();
setInterval(dashPoll, 3000);</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    db = None
    api_url = None
    rows = ROW_LIMIT
    refresh = 0
    actions: ClassVar[dict] = {}   # id -> the action dict _spawn_action builds
    _action_seq: ClassVar[int] = 0

    def do_GET(self):
        if self.path.startswith("/summary.json"):
            body = json.dumps(collect(self.db, self.api_url, self.rows),
                              indent=1, sort_keys=True).encode()
            self._send("application/json", body)
            return
        if self.path.startswith("/actions"):
            self._send("text/html; charset=utf-8", _actions_status().encode())
            return
        if self.path.startswith("/logs/"):
            self._serve_file(self.path[len("/logs/"):], "work/logs")
            return
        if self.path not in ("/", "/index.html"):
            self._send("text/plain", b"not found\n", status=404)
            return
        page = render(collect(self.db, self.api_url, self.rows), self.api_url,
                      self.refresh).encode()
        self._send("text/html; charset=utf-8", page)

    def do_POST(self):
        if not self.path.startswith("/action/"):
            self._send("text/plain", b"not found\n", status=404)
            return
        name = self.path[len("/action/"):].split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        arg = ""
        try:
            fields = parse_qs(body.decode("utf-8") or "")
            arg = (fields.get("arg") or [""])[0].strip()
        except (ValueError, UnicodeDecodeError):
            pass
        ok, error, _entry = _spawn_action(name, arg)
        self._send("application/json",
                   json.dumps({"ok": ok, "error": error}).encode(),
                   status=200 if ok else 409)

    def _serve_file(self, rel, base):
        """Serve one file under `base` (e.g. work/logs), path-traversal guarded."""
        root = os.path.realpath(os.path.join(repo_root(), base))
        path = os.path.realpath(os.path.join(root, rel))
        if not (path.startswith(root + os.sep) and os.path.isfile(path)):
            self._send("text/plain", b"not found\n", status=404)
            return
        try:
            with open(path, "rb") as f:
                self._send("text/plain; charset=utf-8", f.read())
        except OSError:
            self._send("text/plain", b"not found\n", status=404)

    def _send(self, content_type, body, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *fmt_args):
        # One line per request is noise for a page a human refreshes by hand.
        print(f"  {self.address_string()} {fmt % fmt_args}")


def _bind(host, port):
    """(server, port) for the first free port at or after `port`, else (None, 0)."""
    for candidate in range(port, port + PORT_TRIES):
        try:
            return HTTPServer((host, candidate), Handler), candidate
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise            # a bad --host is not a busy port; don't hide it
    return None, 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dashboard.py",
        description="Serve the local job table as a read-only page.")
    parser.add_argument("--port", type=int, default=8079)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", default=None)
    parser.add_argument("--api-url", default=LOCAL_API)
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--rows", type=int, default=ROW_LIMIT,
                        help="rows per table (default %(default)s)")
    parser.add_argument("--refresh", type=int, default=0,
                        help="reload the page every N seconds (0 = never)")
    args = parser.parse_args(argv)

    Handler.db = args.db
    Handler.api_url = None if args.no_api else args.api_url
    Handler.rows = args.rows
    Handler.refresh = args.refresh
    server, port = _bind(args.host, args.port)
    if server is None:
        print(f"port {args.port} is taken and the next "
              f"{PORT_TRIES - 1} after it are too; "
              f"pick one with: ./run.sh dashboard --port N", file=sys.stderr)
        return 1
    if port != args.port:
        # WSL mirrors the Windows side's listeners, so a port that `ss` does not
        # show can still refuse bind().  Say so rather than dying on a traceback.
        print(f"port {args.port} is in use (often a Windows-side listener "
              f"mirrored into WSL); using {port} instead")
    print(f"local job table on http://{args.host}:{port}/ "
          f"(Ctrl-C to stop; /summary.json for machines)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
