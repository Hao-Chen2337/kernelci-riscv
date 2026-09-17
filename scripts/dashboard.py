#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Dashboard: render the local job table as one read-only page.

Reads our own build index, ledger and optional local API - no extra
dependencies, unlike the upstream frontend.  Binds 127.0.0.1, writes nothing.

    ./run.sh dashboard [--port 8079]

Notes: docs/code-notes/A-sink-source-dashboard.md
"""

import argparse
import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from kcilib import api
from kcilib.core import ledger
from kcilib.table import localrun
from kcilib.table.buildindex import BuildIndex
from kcilib.table.jobspec import DEFAULT_TESTS

LOCAL_API = os.environ.get("KCI_API_URL", "http://127.0.0.1:8001")
ROW_LIMIT = 25


def collect(db, api_url=None):
    """Everything the page shows, as plain data (also served as JSON)."""
    index = BuildIndex(db)
    builds = index.all()
    ran = localrun.ran_tests()

    runs = []
    for build_id, tests in ran.items():
        records = ledger.read_results(build_id)
        for test in tests:
            record = records.get(test) or {}
            runs.append({
                "build_id": build_id,
                "test": test,
                "verdict": record.get("verdict"),
                "exit_code": record.get("exit_code"),
                "source": record.get("source"),
                "timestamp": record.get("timestamp"),
                "detail": record.get("detail") or "",
                "log": record.get("log"),
            })
    runs.sort(key=lambda row: row["timestamp"] or "", reverse=True)

    specs, skipped, checked = localrun.todo(index, tests=DEFAULT_TESTS)

    trees = {}
    for build in builds:
        key = build.tree or "?"
        trees[key] = trees.get(key, 0) + 1
    verdicts = {}
    for row in runs:
        key = row["verdict"] or "-"
        verdicts[key] = verdicts.get(key, 0) + 1

    return {
        "index": {
            "count": index.count(),
            "path": os.path.relpath(index.path),
            "trees": sorted(trees.items(), key=lambda item: -item[1]),
            "builds": [{
                "build_id": b.build_id, "tree": b.tree, "describe": b.describe,
                "created": b.created, "commit": b.commit,
            } for b in builds[:ROW_LIMIT]],
        },
        "ledger": {"runs": runs[:ROW_LIMIT], "total": len(runs),
                   "verdicts": sorted(verdicts.items())},
        "pending": {
            "count": len(specs), "checked": checked,
            "skipped": len(skipped),
            "items": [{"build_id": s.build_id, "test": s.test,
                       "tree": getattr(s.build, "tree", None),
                       "describe": getattr(s.build, "describe", None)}
                      for s in specs[:ROW_LIMIT]],
        },
        "api": api.node_counts(api_url) if api_url else None,
    }


CSS = """body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#222}
header{background:#12304d;color:#fff;padding:14px 22px}
header h1{margin:0;font-size:17px;font-weight:600}
header .sub{opacity:.75;font-size:12px;margin-top:3px}
main{padding:18px 22px;display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:16px}
section{background:#fff;border:1px solid #e2e5ea;border-radius:8px;padding:12px 14px}
h2{margin:0 0 8px;font-size:14px;color:#12304d}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td,th{padding:3px 6px;border-bottom:1px solid #eef0f3;text-align:left;vertical-align:top}
th{color:#68727f;font-weight:600}
code{font-family:ui-monospace,monospace;font-size:12px}
.pass{color:#1a7f37;font-weight:600}.fail{color:#b42318;font-weight:600}
.infra,.error{color:#b54708;font-weight:600}
.count{font-size:22px;font-weight:700;color:#12304d}
.muted{color:#68727f;font-size:12px}"""


def _table(headers, rows):
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def render(data, api_url):
    index, led = data["index"], data["ledger"]
    verdict_cells = " ".join(
        f'<span class="{html.escape(name)}">{html.escape(name)}</span> {count}'
        for name, count in led["verdicts"])
    trees = " ".join(f"{html.escape(name)} {count}" for name, count in index["trees"])

    build_rows = [[
        f"<code>{html.escape(b['build_id'][:16])}</code>",
        html.escape(b["tree"] or "?"),
        html.escape((b["describe"] or "")[:44]),
        html.escape((b["created"] or "")[:16]),
    ] for b in index["builds"]]

    run_rows = [[
        f"<code>{html.escape(r['build_id'][:16])}</code>",
        html.escape(r["test"] or "?"),
        (f'<span class="{html.escape(r["verdict"] or "")}">'
         f"{html.escape(r['verdict'] or '-')}</span>"),
        html.escape(str(r["source"] or "-")),
        html.escape((r["timestamp"] or "")[:19]),
        html.escape((r["detail"] or "")[:52]),
    ] for r in led["runs"]]

    todo_rows = [[
        f"<code>{html.escape(t['build_id'][:16])}</code>",
        html.escape(t["test"] or "?"),
        html.escape(t["tree"] or "?"),
        html.escape((t["describe"] or "")[:40]),
    ] for t in data["pending"]["items"]]

    api_html = '<p class="muted">local API not reachable (./run.sh stack)</p>'
    if data["api"]:
        blocks = []
        for kind, counts in data["api"].items():
            total = sum(count for _name, count in counts)
            top = ", ".join(f"{html.escape(name)} {count}"
                            for name, count in counts[:5])
            blocks.append(f"<p><b>{html.escape(kind)}</b> {total}"
                          f'<br><span class="muted">{top}</span></p>')
        api_html = "".join(blocks)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>local job table</title><style>{CSS}</style></head><body>
<header><h1>RISC-V pull lab &mdash; local job table</h1>
<div class="sub">index {index['path']} &middot; ledger work/results/ &middot;
 local API {html.escape(api_url or '-')} &middot; read-only</div></header>
<main>
<section><h2>Build index</h2>
<div class="count">{index['count']}</div>
<div class="muted">builds &middot; {html.escape(trees)}</div>
{_table(["build", "tree", "describe", "created"], build_rows)}
</section>
<section><h2>Runs (ledger)</h2>
<div class="count">{led['total']}</div>
<div class="muted">{verdict_cells}</div>
{_table(["build", "test", "verdict", "source", "when", "detail"], run_rows)}
</section>
<section><h2>Pending</h2>
<div class="count">{data['pending']['count']}</div>
<div class="muted">over {data['pending']['checked']} indexed builds &middot;
 {data['pending']['skipped']} skipped for missing artifacts</div>
{_table(["build", "test", "tree", "describe"], todo_rows)}
</section>
<section><h2>Local API</h2>{api_html}</section>
</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    db = None
    api_url = None

    def do_GET(self):
        if self.path.startswith("/summary.json"):
            body = json.dumps(collect(self.db, self.api_url),
                              indent=1, sort_keys=True).encode()
            self._send("application/json", body)
            return
        if self.path not in ("/", "/index.html"):
            self._send("text/plain", b"not found\n", status=404)
            return
        page = render(collect(self.db, self.api_url), self.api_url).encode()
        self._send("text/html; charset=utf-8", page)

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


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dashboard.py",
        description="Serve the local job table as a read-only page.")
    parser.add_argument("--port", type=int, default=8079)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", default=None)
    parser.add_argument("--api-url", default=LOCAL_API)
    parser.add_argument("--no-api", action="store_true")
    args = parser.parse_args(argv)

    Handler.db = args.db
    Handler.api_url = None if args.no_api else args.api_url
    server = HTTPServer((args.host, args.port), Handler)
    print(f"local job table on http://{args.host}:{args.port}/ "
          f"(Ctrl-C to stop; /summary.json for machines)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
