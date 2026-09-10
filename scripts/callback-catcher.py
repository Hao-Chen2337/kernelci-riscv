#!/usr/bin/env python3
"""Minimal callback catcher: logs every POST (headers + body) it receives."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

# Derived from this file's location: a hardcoded absolute path pointed every
# clone at one machine's checkout.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "work", "logs")
LOG = os.path.join(LOG_DIR, "callback-received.json")


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        # A first run has no work/logs yet; creating it beats crashing on the
        # very first callback.
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG, "ab") as f:
            f.write(body + b"\n")
        print(f"POST {self.path} auth={self.headers.get('Authorization')!r}")
        print(body.decode("utf-8", "replace")[:1500])
        self.send_response(202)
        self.end_headers()
        self.wfile.write(b'{"message":"OK"}')

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", 9999), H).serve_forever()
