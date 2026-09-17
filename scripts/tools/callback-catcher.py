#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Debug callback catcher: logs every POST (headers + body) it receives.

DEBUG TOOL, not the stack's callback: a running stack delivers its results to
`lava_callback` on KCI_CB_PORT (8003 by default), and nothing is wired here.
One JSON Lines record per request, rotated to <log>.1 above --max-bytes.

Rationale: docs/code-notes/W2d-tools.md.

    python3 scripts/tools/callback-catcher.py --port 9998 --log /tmp/cb.jsonl
"""

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# WALKED UP to run.sh (kcilib.repo_root), never counted: this file lives in
# scripts/tools/, and a counted root quietly defaulted the log to
# scripts/work/logs/ instead of work/logs/.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # scripts/ holds kcilib

from kcilib import repo_root

ROOT = repo_root()
DEFAULT_LOG = os.path.join(ROOT, "work", "logs", "callback-received.jsonl")
DEFAULT_PORT = 9999
DEFAULT_MAX_BYTES = 8 * 1024 * 1024

# Set from the command line in main(); the handler reads them as globals.
LOG = DEFAULT_LOG
MAX_BYTES = DEFAULT_MAX_BYTES


def record(path, auth, body, size):
    """Append one JSON-lines record, rotating the log when it got too big."""
    entry = {
        "received": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path": path,
        "auth": auth,
        "bytes": size,
        "body": body,
    }
    try:
        if os.path.getsize(LOG) >= MAX_BYTES:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass  # no log yet
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError as error:
        # Never swallow this: a catcher that drops requests silently is worse
        # than not starting it at all.
        print(f"!! could not write {LOG}: {error}", file=sys.stderr)


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            # Not JSON: keep the text, do not reject the request.
            body = raw.decode("utf-8", "replace")
        auth = self.headers.get("Authorization")
        record(self.path, auth, body, length)
        print(f"POST {self.path} auth={auth!r} ({length} B) -> {LOG}")
        print(raw.decode("utf-8", "replace")[:1500])
        self.send_response(202)
        self.end_headers()
        self.wfile.write(b'{"message":"OK"}')

    def do_GET(self):
        # Liveness/identity answer, so a port check can tell catcher from
        # whatever else holds the port.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"service": "callback-catcher", "log": LOG}).encode()
        )

    def log_message(self, *a):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Debug callback catcher (POST logger); not the stack's callback",
        epilog="The local stack delivers callbacks to lava_callback on KCI_CB_PORT "
        "(8003 by default); nothing is wired to this script.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KCI_CB_CATCH_PORT", DEFAULT_PORT)),
        help="TCP port to listen on (default: %(default)s, or KCI_CB_CATCH_PORT)",
    )
    parser.add_argument(
        "--bind",
        default=os.environ.get("KCI_CB_CATCH_BIND", "127.0.0.1"),
        help="address to bind (default: %(default)s)",
    )
    parser.add_argument(
        "--log",
        default=os.environ.get("KCI_CB_CATCH_LOG", DEFAULT_LOG),
        help="JSON Lines output file (default: %(default)s)",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help="rotate the log to <log>.1 above this size (default: %(default)s)",
    )
    args = parser.parse_args()

    global LOG, MAX_BYTES
    LOG = os.path.abspath(args.log)
    MAX_BYTES = args.max_bytes

    try:
        server = HTTPServer((args.bind, args.port), H)
    except OSError as error:
        # Name the port and the way out instead of a bare traceback.
        sys.exit(
            f"cannot listen on {args.bind}:{args.port}: {error}\n"
            f"pick a free port with --port (or KCI_CB_CATCH_PORT); the stack's "
            f"own callback port is KCI_CB_PORT (default 8003)"
        )
    print(f"callback catcher on http://{args.bind}:{args.port} -> {LOG}")
    print(
        "debug tool: a running ./run.sh stack delivers its callbacks to "
        "lava_callback on KCI_CB_PORT, not here"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
