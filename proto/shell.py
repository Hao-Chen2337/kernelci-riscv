# SPDX-License-Identifier: LGPL-2.1-or-later
"""The page shell: the topbar, the nav, the live strip, and the document around a page.

`document()` is the only thing that writes `<html>`, so the head, the stylesheet
link and the script are in one place and a page module returns a fragment.  The
site is plain files under `proto/site/`, one per route, which is why a link here
is an ordinary `href` and there is no router: what a reader sees in the address
bar is what the eventual server will route on.

The strip is the console's own activity - what it started and whether it is still
going.  It is a `<details>` because on most visits the answer is "nothing", and a
reader who is not waiting for a job should not pay a panel for it.
"""

from .ui import esc
from .words import both

# route -> (file name, the word key of its own name).  The order here is the order
# of the nav, which is the order a reader walks the tool in: what upstream built,
# what has not run, what is running it, what did run, and how it is trending.
ROUTES = [
    ("/builds", "builds", "nav.builds"),
    ("/jobs", "jobs", "nav.jobs"),
    ("/runs", "runs", "nav.runs"),
    ("/worker", "worker", "nav.worker"),
    ("/analysis", "analysis", "nav.analysis"),
]

# The title of the page in the topbar is the route's own sub-line, which is the
# one sentence that answers "what question does this page ask".
BLURBS = {
    "/builds": "page.builds.blurb",
    "/jobs": "page.jobs.blurb",
    "/runs": "page.runs.blurb",
    "/worker": "page.worker.blurb",
    "/analysis": "page.analysis.blurb",
}


def nav(route: str) -> str:
    out = []
    for href, _slug, key in ROUTES:
        cur = ' aria-current="page"' if href == route else ""
        out.append(f'<a href="{href}"{cur}>{both(key)}</a>')
    return f'<nav class="nav" aria-label="pages">{"".join(out)}</nav>'


def live_strip(d: dict, open_: bool = False) -> str:
    """The activity list: what this console started, newest first.

    One row per process, and the row says the three things a reader waiting on a
    job asks: what it is, how long it has been going, and where its output is.
    """
    running = [a for a in d["activities"] if a["state"] == "running"]
    rows = []
    for a in d["activities"][:6]:
        if a["state"] == "running":
            left = '<span class="pulse"></span>'
            tail = btn("cancel", "sm", name=a["run_id"])
            age = f'<span class="age">{esc(a["age"])}</span>'
        else:
            left = f'<span class="flag {"on" if a["state"] == "done" else "no"}">' \
                   f'{"&#10003;" if a["state"] == "done" else "&#10007;"}</span>'
            if a["exit"] is None:
                tail = btn("cancel", "sm", name=a["run_id"])
            else:
                tail = f'<span class="age">{both("shell.exit", n=a["exit"])}</span>'
            age = f'<span class="age">{esc(a["age"])}</span>'
        rows.append(
            f'<li class="act">'
            f'{left}'
            f'<span class="who">{esc(a["run_id"])}</span>'
            f'<span class="what">{esc(a["what"])}'
            f'<span class="argv" title="{esc(a["argv"])}">{esc(a["argv"])}</span></span>'
            f'{age}'
            f'<span class="do">{tail}'
            f'<a class="btn sm" href="/runs#{esc(a["run_id"])}">{both("shell.log")}</a></span>'
            f'</li>'
        )
    body = (f'<ul class="acts">{"".join(rows)}</ul>' if rows
            else f'<p class="empty">{both("shell.live_empty")}</p>')
    count = both("shell.running", n=len(running)) if running else both("shell.live")
    sub = both("shell.live_sub")
    return (
        f'<details class="live"{" open" if open_ else ""}>'
        f'<summary><span class="{"pulse" if running else "muted"}"></span>'
        f'<b>{sub}</b><span class="count">{count}</span></summary>'
        f'<div class="body">{body}</div>'
        f'</details>'
    )


def btn(word_html: str, kind: str = "", name: str = "") -> str:
    cls = f'btn {kind}'.strip()
    attrs = f' name="{esc(name)}"' if name else ""
    return f'<button type="button" class="{cls}"{attrs}>{word_html}</button>'


def topbar(route: str, d: dict) -> str:
    """The one bar: who this is, which page, and the two switches.

    The theme and language switches are in the topbar and not in a page, because
    both are properties of the reader and not of the question the page asks.
    """
    running = [a for a in d["activities"] if a["state"] == "running"]
    chip = ""
    if running:
        chip = (f'<a class="live-chip" href="#live">'
                f'<span class="pulse"></span>{both("shell.running", n=len(running))}</a>')
    return (
        f'<header class="topbar">'
        f'<span class="brand"><span class="mark">kci</span>'
        f'<span class="name">{both("shell.brand")}</span>'
        f'<span class="sep">&rsaquo;</span>'
        f'<span class="where">{both(BLURBS[route])}</span></span>'
        f'{nav(route)}'
        f'<span class="tools">'
        f'{chip}'
        f'<span class="seg" role="group" aria-label="language">'
        f'<label><input type="radio" name="lang" value="en" checked><span>EN</span></label>'
        f'<label><input type="radio" name="lang" value="zh"><span>中文</span></label>'
        f'</span>'
        f'<button type="button" class="btn sm" id="theme" title="light / dark">'
        f'&#9680; <span id="theme-word">auto</span></button>'
        f'</span>'
        f'</header>'
    )


def document(route: str, d: dict, body: str, title_html: str = "") -> str:
    """The whole file: head, topbar, strip, the page, the script."""
    title = f"kernelci-riscv - {route.strip('/') or 'builds'}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='3' fill='%232f5bd0'/><text x='8' y='12' font-size='9' font-family='monospace' fill='white' text-anchor='middle'>k</text></svg>">
<link rel="stylesheet" href="/app.css">
</head>
<body>
{topbar(route, d)}
<main class="wrap">
{live_strip(d)}
{body}
</main>
<script src="/app.js"></script>
</body>
</html>
"""
