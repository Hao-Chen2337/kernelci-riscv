#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The prototype's server: five routes, two files, one fixture.

    python3 -m proto.serve [--port 8084] [--host 127.0.0.1]

It is `http.server` and nothing else - no template library, no build step, no
dependency outside the standard library - because the thing being reviewed is the
markup and the stylesheet, and a toolchain in the middle of that is a second thing
to debug.  `--render DIR` writes the five pages as files instead of serving them,
which is what makes them openable without a running process.

Every request calls `data.data()` again, for the same reason the real page reads
its files per request: the numbers on the screen must be the numbers on disk, and a
fixture held at startup is a fixture that goes stale in a way nobody can see.  The
`Cache-Control: no-store` pair is that decision applied to the browser.
"""

import argparse
import html
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proto import data, pages, shell, theme

DEFAULT_PORT = 8084
DEFAULT_HOST = "127.0.0.1"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# The routes, and the file each one is written to by `--render`.  `/` is the
# builds page: the question a reader arrives with is "what is there".
ROUTES = {"/": "/builds", "/builds": "/builds", "/jobs": "/jobs", "/runs": "/runs",
          "/worker": "/worker", "/analysis": "/analysis"}
FILES = {"/builds": "index.html", "/jobs": "jobs.html", "/runs": "runs.html",
         "/worker": "worker.html", "/analysis": "analysis.html"}

# The two static files, and the type each is served as.  Written out rather than
# guessed from the extension: a `mimetypes` table that changes with the platform
# is a stylesheet that stops loading on one machine and not another.
STATIC_TYPES = {"app.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}


def render(route: str, d: dict) -> str:
    """One page, whole: the shell around the fragment the route's function returns."""
    page = pages.PAGES[route]
    return shell.document(route, d, page(d))


def page_for(path: str) -> str:
    """The route a request path names, or `""` when it names no page.

    A trailing slash is the same page (`/jobs/` is `/jobs`), which is what a
    reader gets from a hand-typed address, and a `?limit=50` never reaches here
    because `urlsplit` took it off first.
    """
    key = path.rstrip("/") or "/"
    return ROUTES.get(key, "")


class Handler(BaseHTTPRequestHandler):
    server_version = "kci-proto"
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parts.path)

        if path in ("/app.css", "/app.js"):
            return self._static(path.lstrip("/"))

        route = page_for(path)
        if not route:
            return self._send(404, "text/html; charset=utf-8",
                              shell.document(route or "/builds", data.data(),
                                             f'<p class="empty">no such page: '
                                             f'{html.escape(path)}</p>'))
        try:
            body = render(route, data.data())
        except Exception as exc:                       # a page that dies says so, on the page
            body = shell.document(route, data.data(),
                                  f'<pre class="note warn">{html.escape(repr(exc))}</pre>')
            return self._send(500, "text/html; charset=utf-8", body)
        return self._send(200, "text/html; charset=utf-8", body)

    def do_HEAD(self):
        parts = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parts.path)
        route = page_for(path)
        if path in ("/app.css", "/app.js") or route:
            return self._send(200, "text/html; charset=utf-8", b"", head=True)
        return self._send(404, "text/plain; charset=utf-8", b"", head=True)

    def _static(self, name: str):
        kind = STATIC_TYPES.get(name)
        if kind is None:
            return self._send(404, "text/plain; charset=utf-8", "not found")
        if name == "app.css":
            # the tokens come first: `app.css` names no colour of its own, so a
            # stylesheet served without `theme.css_vars()` is a page with no theme
            # at all - every `var(--ink)` resolves to nothing and the page renders
            # in the browser's defaults
            try:
                with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
                    body = theme.css_vars() + "\n" + fh.read()
            except OSError:
                return self._send(404, "text/plain; charset=utf-8", f"{name} is missing")
            return self._send(200, kind, body)
        try:
            with open(os.path.join(STATIC, name), "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send(404, "text/plain; charset=utf-8", f"{name} is missing")
        return self._send(200, kind, body)

    def _send(self, code: int, kind: str, body, head: bool = False):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Prototype", "no command is run by this server")
        self.end_headers()
        if not head and raw:
            self.wfile.write(raw)

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def write_files(out_dir: str) -> list:
    """The five pages and their two assets, as files: `--render DIR`.

    Written with the stylesheet inlined so that one file opened from the desktop
    is the whole page - which is what makes the prototype sendable to somebody who
    is not going to start a server to look at a design.
    """
    os.makedirs(out_dir, exist_ok=True)
    d = data.data()
    with open(os.path.join(STATIC, "app.css"), encoding="utf-8") as fh:
        css = theme.css_vars() + "\n" + fh.read()
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as fh:
        js = fh.read()
    written = []
    for route, name in FILES.items():
        body = shell.document(route, d, pages.PAGES[route](d))
        body = body.replace('<link rel="stylesheet" href="/app.css">', f"<style>\n{css}\n</style>")
        body = body.replace('<script src="/app.js"></script>', f"<script>\n{js}\n</script>")
        # a file opened from disk has no server, so every route becomes a file
        for r, n in FILES.items():
            body = body.replace(f'href="{r}"', f'href="{n}"')
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        written.append(path)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--render", metavar="DIR", default=None,
                        help="write the pages as standalone files instead of serving")
    args = parser.parse_args(argv)

    if args.render:
        for path in write_files(args.render):
            print(f"wrote {path}")
        return 0

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"kernelci-riscv frontend prototype on {url}")
    print("  /builds  /jobs  /runs  /worker  /analysis")
    print("  nothing here runs a command; ctrl-c to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
