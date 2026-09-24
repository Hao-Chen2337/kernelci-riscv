# SPDX-License-Identifier: LGPL-2.1-or-later
"""The request lifecycle: the socket loop, the handler, and what one request has read.

`serve()` is the loop and `handler_for(gui)` is the `Handler` class - the route
dispatch, the status codes, the language negotiation and the one line every request
leaves behind.  The per-request state lives here because this is the one thing that
knows a request has begun: the scratch the local reads are cached in
(`_request_scratch`, cleared at the start of every request, because `protocol_version`
is `HTTP/1.1` and one keep-alive connection serves many requests on one thread) and the
digest of the local facts the 2s poll compares (`_state_digest`).

`_form_body` reads a POST in both encodings a browser can send: a page's own `<form>`
posts `application/x-www-form-urlencoded` and the script this page serves posts
`new FormData(form)`, which is `multipart/form-data` - the body that `parse_qs` was
handed and could not read, so every action silently fell back to its defaults."""

import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.parse
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .. import api as api_mod
from .. import errors, layout
from ..i18n import DEFAULT_LANG, pick_lang, t
from ..tests import DEFAULT_TESTS
from .forms import _clamp, _first, _numbers
from .models import Filter
from .schema import API_BUDGET, API_TTL_DEFAULT, REDIRECTS
from .urls import _url

# ---------------------------------------------------------------------------
# 19. Gui (view.hpp §19)
# ---------------------------------------------------------------------------

# What one request has already read off this machine, and nothing more.
#
# The local reads (`Builds.load()`, `Records.load()`, the download tree) are the
# page's own facts, and they change while it is running: a `run`/`pull`/`index`
# button writes them from a subprocess, and the next page load has to show it
# without a restart.  So they are read per *request* - and a page that asked for
# 200 local rows must not parse the ledger 200 times to do it, which is what makes
# this a cache at all.
#
# It lives in a `threading.local()`, and the handler *clears it at the start of
# every request*.  That second half is not decoration: `protocol_version` is
# `HTTP/1.1`, so one keep-alive connection carries many requests on the *same*
# thread - "one thread, one request" is not true here, and a cache that outlived a
# request would show the state from before the last write.  It is also why this is
# not a field on `Gui`: two threads, one field, whichever wrote last - the
# `self.note` race, and `_shell`'s docstring says what that cost.
_LOCAL = threading.local()


def _request_scratch() -> dict[str, Any]:
    """This request's own scratch space; created on first use, cleared per request.

    Only ever read through `Gui._state()`, `Gui.all_locals()`, `Gui.runs()` and
    `Gui.todo()`, which are the reads that are asked for many times in one render.
    """
    found = getattr(_LOCAL, "scratch", None)
    if found is None:
        found = {}
        _LOCAL.scratch = found
    return found


def _ttl_of(query: Mapping[str, list[str]]) -> float:
    """How long an API answer this request may reuse one: `?ttl=`, `?fresh=1`.

    `?fresh=1` is the manual refresh spelled as a URL: it asks the API again *now*.
    That is what makes the refresh control (`_refresh`) a real re-read and not a
    decoration - the local side was never cached, so a refresh has always re-read
    the files, and this is the API half of the same promise (`01-perf.md` §D2).
    `?fresh=0` is not fresh, so a link can carry the key and mean "no".

    A `?ttl=` nobody can read, or one past `api_mod.MAX_TTL`, falls back rather
    than refusing: this is a knob for a reader tuning one page, not a condition of
    the question, so it is not a `Filter` key and it never reaches a command line.

    **The default is `API_TTL_DEFAULT` and not `lib/api.py`'s 5 s.  Carry-over C2,
    decided here.**  An entry is stamped when its answer is *written*, so a cold page
    whose own `/count` took longer than the TTL left that answer already stale: the
    very next load re-read it (`/analysis` 4.44 s, `/worker` 1.81 s, where the load
    after that is 0.012 s).  Since the alternative - stamping an entry with its
    request's *start* - is a change to `lib/api.py`, the page's own default covers the
    read instead.  It is the page's decision to make because it is the page that knows
    what its loads cost, and it is *stated* rather than silent: `_refresh` prints the
    age of what was read (`read 3s ago`), `?fresh=1` bypasses the cache entirely, and
    every local file the page draws from is read fresh on every request whatever this
    number is - the operator's "我刷新一次界面起码我运行时候能够在外重新读文件".
    """
    if _first(query, "fresh") not in ("", "0"):
        return 0.0
    raw = _first(query, "ttl")
    if not raw:
        return float(API_TTL_DEFAULT)
    try:
        return float(_clamp(int(float(raw)), 0, api_mod.MAX_TTL))
    except ValueError:
        return float(API_TTL_DEFAULT)


def _begin_request(query: Mapping[str, list[str]]) -> None:
    """Start this request's API scope: an empty memo, this freshness, this deadline.

    Called from the handler, because the handler is the one thing that knows a new
    request has begun - and it has to be called for every request the console
    serves, not only the pages: one keep-alive connection carries many requests on
    one thread (`_request_scratch` above), so a memo that outlived its request would
    answer the next one with what the last one read.

    The budget is the page's, and it is shared by every read of this request
    (`API_BUDGET`), so no page can spend it once per call the way `/worker` did.
    """
    api_mod.begin_request(ttl=_ttl_of(query), budget=API_BUDGET)


def _mark(path: str) -> str:
    """One file as `path:mtime:size`, or `path:-` when it is not there yet."""
    try:
        info = os.stat(path)
    except OSError:
        return f"{path}:-"                 # absent is a fact as well: it may appear
    return f"{path}:{info.st_mtime_ns}:{info.st_size}"


def _dir_marks(directory: str, suffix: str) -> list[str]:
    """`path:mtime:size` for every `<directory>/*/<suffix>` - one level, never recursive.

    `suffix` and not a file name: `var/results/<build>/` holds one `<test>.json` per
    recorded verdict and the page does not know their names in advance, while
    `var/runs/<id>/` holds exactly one `run.json`.  A name still matches itself, so
    one spelling covers both; a half-written `.tmp` beside its file matches neither,
    which is what a reader wants.

    A directory that is not there is not a failure: each of these is made by the
    first thing that writes it, and a page that refused to draw on a fresh machine
    would be a page nobody could use.  The same is true of a directory removed
    while it is being walked, which is what a cancelled activity leaves behind.
    """
    found = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_dir():
                    continue
                try:
                    with os.scandir(entry.path) as inner:
                        found += [_mark(one.path) for one in inner
                                  if one.name.endswith(suffix)]
                except OSError:
                    continue
    except OSError:
        return found
    return found


def _state_digest() -> str:
    """A hash of the local facts a page reads, from mtime and size, never content.

    This is what the 2s poll compares (`Gui.state_poll`, `_JS`'s `dashPoll`): when
    an activity finishes, its `run.json` is settled, the record it wrote appears
    under `var/results`, its `provenance.json` under `var/downloads` - and this
    number moves, so the page re-reads them with nobody pressing anything.  That is
    the operator's 我这个东西运行完了，他可能是要改某些东西 wired to the poll that
    already existed (`docs/gui-rework/01-perf.md` §D3).

    `(mtime, size)` and not the bytes: these are the cards, the ledger and the pull
    records, some of them megabytes, and a page may not read them twice to decide
    whether it has to read them once.  One `scandir` per directory, which is the
    same walk `all_locals()` already makes for the downloads, so this is not a new
    cost class - and it is the *page's own inputs*, not a guess about them: nothing
    an activity writes is outside this list.

    `worker-state.json` is in it although the worker rewrites it after every event
    it handles: each of those rewrites is a real change to what `/worker` shows.
    """
    marks = [_mark(layout.index()), _mark(layout.worker_state())]
    marks += _dir_marks(layout.results(), ".json")
    marks += _dir_marks(layout.downloads(), "provenance.json")
    marks += _dir_marks(layout.runs(), "run.json")
    return hashlib.sha256("\n".join(sorted(marks)).encode("utf-8")).hexdigest()[:16]


# One archived console's file name, and nothing else: what the `/logs/` route admits.
# `lib/job.py`'s `_log_path` writes `<build>.<test>.<stamp>.log` - a hex id, a test
# name, a UTC stamp - so this is that shape and not a general file name.  It is a
# whitelist rather than a blacklist of `..` because the two failures are not the same
# size: a name outside this pattern is refused here, and `layout.logs()` is only ever
# joined with a name that cannot leave its directory.
#
# `:` is in the set and it is not decoration: the stamp is `%Y-%m-%dT%H:%M:%SZ`, so
# every real name has two of them.  A pattern that dropped it refused every console
# this tree has ever written - measured against
# `6aade015d96a8203de6dff37.boot.2026-09-22T16:25:49Z.log`, which answered 404 while
# the file was on disk.  What the set excludes is what matters: no `/`, no backslash,
# no whitespace, so the join cannot leave `var/logs/`.
_CONSOLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]*\.log$")


def _part_name(head: str) -> str:
    """The `name="…"` of one multipart part's `Content-Disposition`, or `""`."""
    for line in head.splitlines():
        if not line.lower().startswith("content-disposition:"):
            continue
        match = re.search(r'name="([^"]*)"', line)
        if match:
            return match.group(1)
    return ""


def _multipart(body: bytes, boundary: str) -> dict[str, list[str]]:
    """A `multipart/form-data` body as the same shape `parse_qs` returns.

    Repeated names accumulate in order, which is what a bar of tick boxes sends and
    what `_ticks()` reads.
    """
    found: dict[str, list[str]] = {}
    marker = b"--" + boundary.encode("utf-8")
    for part in body.split(marker):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue                       # the preamble and the closing marker
        head, separator, value = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        name = _part_name(head.decode("utf-8", "replace"))
        if name:
            found.setdefault(name, []).append(value.decode("utf-8", "replace"))
    return found


def _form_body(content_type: str, body: bytes, lang: str = DEFAULT_LANG) -> dict[str, list[str]]:
    """One POST body as form fields, in both encodings a browser can send.

    A page's own `<form>` posts `application/x-www-form-urlencoded`, and
    `parse_qs` reads exactly that.  The script this page serves did not: it took the
    form over and posted `new FormData(form)`, which is `multipart/form-data` - so
    `parse_qs` was handed a body it could not read and returned *no fields at all*.

    That was not a missing value but a silent one.  Every action fell back to its
    defaults, and the ones that need a ticked row - `run` and `pull` - were refused
    with "needs at least one ticked build" however many rows the operator ticked,
    which is the report this function exists to answer.  Worse, an action that needs
    nothing ticked still ran, but on the *default* tree and window rather than the
    ones in the filter bar, because `_first(form, "tree")` was reading an empty
    form.

    So the body is read for what it says it is, and a body that is neither encoding
    is refused loudly instead of being parsed into silence.
    """
    kind = content_type.split(";", 1)[0].strip().lower()
    if kind == "multipart/form-data":
        match = re.search(r'boundary="?([^";]+)"?', content_type)
        if not match:
            raise errors.ConfigError(t(lang, "error.body_no_boundary"))
        return _multipart(body, match.group(1).strip())
    if kind in ("", "application/x-www-form-urlencoded"):
        return urllib.parse.parse_qs(body.decode("utf-8"))
    raise errors.ConfigError(t(lang, "error.body_not_a_form", kind=kind))


def _back_link(back: str, lang: str) -> str:
    """`?back=` as a link, or nothing at all.

    Only a path *on this console* is obeyed: a value that does not start with `/`, or
    that starts with `//` (which a browser reads as another host), is dropped rather
    than reflected.  The value arrives in a URL, so anyone can put anything in it; the
    one thing this page does with it is write it into an `href`, and an `href` that can
    be made to point anywhere is how a console becomes a redirector.  Dropping it is
    not a complaint - a log opened by typing its own address has no list to go back to,
    and that is the whole of it.
    """
    if not back.startswith("/") or back.startswith("//"):
        return ""
    return (f'<a class="log-back" href="{html.escape(back, quote=True)}">'
            f'{html.escape(t(lang, "log.back"))}</a>')


def log_body(payload: Mapping[str, Any], lang: str = DEFAULT_LANG, back: str = "") -> str:
    """One activity's log as the page a browser shows at `/runs/<id>/log`.

    The payload is `Gui.log(id, 0)`'s - the whole file from the start, so the page the
    reader lands on and the address they could have typed cannot show different logs.
    Two lines of header carry what the activity *is* (its id, its state, its exit code)
    because a log with no name on it is a wall of text in a tab the reader then cannot
    identify; an activity with an empty log gets a sentence instead of a blank page,
    which is the same complaint ("打开不了") arriving a second way.

    `back` is where the reader came from (the `?back=` the 日志 link carried), and it is
    what makes the page a page rather than a dead end: this opens in a tab of its own,
    so Back does not lead to the table the click was made in, and a reader who has to
    retype the filter they were looking at loses it.  The bytes are HTML now, not
    `text/plain`, because that link has to be markup; the file itself is inside one
    `<pre>`, escaped, so the log still reads as the log - same lines, same characters,
    selectable and searchable.  What a machine reads is unchanged and still one branch
    down: `/api/runs/<id>/log` answers the same text as JSON, which is what the script
    polled then and what a caller wanting the bytes should ask for.
    """
    text = str(payload.get("text") or "")
    head = t(lang, "log.head", run=str(payload.get("id") or ""),
             state=str(payload.get("state") or ""),
             exit_code="-" if payload.get("exit_code") is None else str(payload["exit_code"]))
    file_text = text or t(lang, "log.empty")
    return (
        "<!doctype html>\n"
        f'<html lang="{html.escape(lang, quote=True)}"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(head)}</title>"
        "<style>"
        "body{margin:0;background:#fff;color:#111;"
        "font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}"
        ".log-back{display:inline-block;margin:12px 16px 0;color:#0366d6}"
        "pre{margin:12px 16px 32px;white-space:pre-wrap;word-break:break-word}"
        "</style></head><body>"
        + _back_link(back, lang)
        + f"<pre>{html.escape(file_text)}</pre>"
        "</body></html>\n"
    )


def console_log(name: str, lang: str = DEFAULT_LANG) -> str:
    """One archived console, as the plain text it is: what `/logs/<name>` serves.

    This is the *other* log.  `/runs/<run_id>/log` above is one **activity**'s output -
    a process this console started and can still show the state of - and this is the
    console `lib/job.py` archived for one run of one (build, test) pair, at
    `var/logs/<build>.<test>.<stamp>.log` (`Job._log_path`).  The run-history panel is
    the one page that links here, one link per run.

    **`text/plain` with nothing added**, where `/runs/<id>/log` draws two header lines:
    an activity's id says nothing about what it ran, so that page has to say it, while
    the row a reader clicked here already prints the build, the test and the stamp - a
    header would be a second copy of what is on the screen behind the tab.  The file
    itself, in the browser's own plain-text view.

    The name is **one file name and never a path**: the pattern below admits no `/`, no
    backslash and no `.` segment but the ones inside a real name, so `layout.logs()` can
    only ever be joined with something that names a file in that one directory.  A name
    that does not match, and a file that is not there, are the same 404 - the caller
    turns `ConfigError` into it - because "you mistyped it" and "it was pruned" are not
    two different answers to a request for bytes.
    """
    if not _CONSOLE_NAME.match(name):
        raise errors.ConfigError(t(lang, "error.no_such_log", name=repr(name)))
    try:
        with open(layout.logs(name), encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as exc:
        raise errors.ConfigError(t(lang, "error.no_such_log", name=repr(name))) from exc


def handler_for(gui: Any) -> type[BaseHTTPRequestHandler]:
    """The request handler one `Gui` answers with: a class per `serve`, as before.

    A factory and not a class with a `gui` attribute: the routes below close over the
    one `Gui` this server was started for, which is what the nested class did when it
    was written inside `Gui.serve` - the class a `serve` binds is still its own, so two
    servers in one process cannot see each other's pages.
    """
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        # The language a URL asked for and the page will remember: `""` until a
        # request really carried `?lang=`, so `_send` can decide the header.
        _remember = ""

        def do_GET(self) -> None:
            try:
                self._route_get()
            except errors.ConfigError as exc:
                self._send(404, "text/plain; charset=utf-8", f"{exc}\n")
            except Exception as exc:  # noqa: BLE001 - a page that dies silently is worse
                self._fail(exc)

        def do_HEAD(self) -> None:
            """The same answers, headers only.

            `BaseHTTPRequestHandler` answers 501 to a HEAD, and a link a reader
            opens by hand is preceded by a HEAD in several clients (and in every
            link checker).  Routing it through the GET path and suppressing the body
            is what `http.server`'s own contract asks for, and it is cheaper than a
            reader concluding that the log address is dead.
            """
            self._head = True
            try:
                self._route_get()
            except errors.ConfigError as exc:
                self._send(404, "text/plain; charset=utf-8", f"{exc}\n")
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)

        def _route_get(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            # This request's API scope: what it has already asked, how fresh a
            # repeated answer may be (`?ttl=`, `?fresh=1`) and the one deadline
            # its reads share.  Before any read, and on every route: the memo
            # must not survive into the next request on this connection.
            _begin_request(query)
            lang = self._lang(query)
            if parsed.path == "/summary.json":
                self._json(gui.summary(_first(query, "api")))
            elif parsed.path == "/api/runs":
                self._json(gui.status(_first(query, "kind"), _first(query, "state")))
            elif parsed.path == "/api/state":
                # What the page's own 2s poll asks: the activities it draws, and
                # the digest of the local facts it was drawn from.
                self._json(gui.state_poll(_first(query, "kind"), _first(query, "state")))
            elif parsed.path == "/api/analysis/drift":
                self._json(gui.drift(_first(query, "older"), _first(query, "newer"),
                                     api=_first(query, "api")))
            elif parsed.path == "/api/analysis/trend":
                self._json(gui.trend(_first(query, "test", DEFAULT_TESTS[0]),
                                     _numbers(query, "scope", 20)))
            elif parsed.path.startswith("/runs/") and parsed.path.endswith("/log"):
                # The log as a *page*, not as this program's own polling endpoint.
                # The activity table's 日志 link used to point at
                # `/api/runs/<id>/log`, which answers JSON - so a reader who clicked
                # it, or copied the address into a new tab, got something that did
                # not look like a log and would not open like one ("日志点击之后拉到
                # 下面给个地址也打开不了我要的是类似自己打开那种").  This is where
                # the 日志 link goes now, in a tab of its own: the page's inline log
                # box is gone, so the script that used to poll the JSON endpoint below
                # polls nothing here any more - the endpoint stays as what it always
                # also was, the machine interface.
                #
                # It is HTML and not `text/plain` because of the one thing a tab of
                # its own costs: 点进日志之后回不去 - the browser's Back button leads
                # to whatever was open before the tab, not to the table the click was
                # made in.  So the log page carries a `?back=`, which is this page's
                # own URL as the *link that wrote it* sees it (a filter, an api key,
                # a window), and `log_body` draws it as one link.  The file is still
                # the file, inside a `<pre>`, escaped - and `curl` has the JSON
                # endpoint one branch down.
                run_id = urllib.parse.unquote(parsed.path[len("/runs/"):-len("/log")])
                self._send(200, "text/html; charset=utf-8",
                           log_body(gui.log(run_id, 0, lang), lang,
                                    _first(query, "back")))
            elif parsed.path.startswith("/api/runs/") and parsed.path.endswith("/log"):
                run_id = parsed.path[len("/api/runs/"):-len("/log")]
                self._json(gui.log(run_id, _first(query, "offset", "0")))
            elif parsed.path.startswith("/logs/"):
                # An **archived console**: `lib/job.py` keeps one per run of one
                # (build, test) pair, and this is the other log route - the one above
                # serves an activity's, out of `var/runs/`, and this serves the
                # archived file out of `var/logs/` (`builds._console_cell` links here).
                # It is the file and nothing else, so it is served as the bytes it is
                # rather than as a page: no header, no prose, no language - see
                # `console_log`.  It is not a `?lang=` page and it writes no cookie.
                self._send(200, "text/plain; charset=utf-8",
                           console_log(urllib.parse.unquote(parsed.path[len("/logs/"):]),
                                       lang))
            elif parsed.path in REDIRECTS:
                # Merging three pages must not break a link somebody wrote down.
                # The condition rides along as a key `/` already reads (`origin`,
                # `missing`) and it is only added when the URL did not carry that
                # key already: `/remote?origin=local` was a filter the reader set,
                # and a redirect that overwrote it would answer a question nobody
                # asked - the one thing `Filter.from_query` refuses to do.
                #
                # The `Location` is built by `_url`, the one function every link
                # on every page goes through, so the `api` key is canonicalised by
                # `Apis.key` and not by hand: `?api=production` is the startup
                # base here and must come back as no key at all, while the same
                # URL on a machine started on the local stack must keep it.  A
                # hand-built query string could not know that.
                to, over = REDIRECTS[parsed.path]
                check = Filter.from_query(query, lang, gui.apis)
                where = _url(to, check, lang=lang,
                             **{key: value for key, value in over.items()
                                if not _first(query, key)})
                self._send(302, "text/html; charset=utf-8", where + "\n")
            else:
                self._send(200, "text/html; charset=utf-8",
                           gui.render(parsed.path, query, lang))

        def do_POST(self) -> None:
            try:
                self._route_post()
            except errors.KciError as exc:
                # A refused writer, an unknown action, a bad value: an answer,
                # not a page that half worked.
                self._send(409, "text/plain; charset=utf-8", f"{exc}\n")
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                self._fail(exc)

        def _route_post(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            _begin_request(query)
            # A refused action answers in the language the reader is reading; the
            # cookie is not written from here, because this is the machine
            # interface (`/api/actions/...`), not a page.  Read before the body,
            # because a body this cannot read is refused in that language too.
            lang = self._lang(query, remember=False)
            form = _form_body(self.headers.get("Content-Type") or "",
                              self.rfile.read(length), lang)
            if parsed.path.startswith("/api/actions/"):
                self._json(gui.start(parsed.path[len("/api/actions/"):], form, lang))
            elif parsed.path.startswith("/api/runs/") and parsed.path.endswith("/cancel"):
                run_id = parsed.path[len("/api/runs/"):-len("/cancel")]
                self._json(gui.cancel(run_id, lang))
            elif parsed.path.startswith("/api/worker/forget/"):
                # One of the two endpoints here that writes a file rather than starting a
                # program, and it is a POST for that reason: a link that edits state
                # is a link a crawler, a prefetch or a middle-click can fire.
                self._json(gui.forget(parsed.path[len("/api/worker/forget/"):], lang))
            elif parsed.path == "/api/worker/callback":
                # The other one, and the same reason for being a POST: this decides where
                # the *token* is POSTed, so it is not a thing a prefetch may do.  The URL
                # is the body's `url` field and the whole of the change: an empty one
                # means "back to the definition's".
                self._json(gui.set_callback(_first(form, "url"), lang))
            else:
                self._send(404, "text/plain; charset=utf-8",
                           f"{t(lang, 'error.no_such_action')}\n")

        def _fail(self, exc: Exception) -> None:
            print(f"! {self.path}: {type(exc).__name__}: {exc}", flush=True)
            self._send(500, "text/plain; charset=utf-8", f"{type(exc).__name__}: {exc}\n")

        def _json(self, payload: Any) -> None:
            self._send(200, "application/json", json.dumps(payload, indent=1))

        def _lang(self, query: Mapping[str, list[str]], remember: bool = True) -> str:
            """Which language this answer is drawn in, and whether to remember it.

            The order is `i18n.pick_lang`'s: `?lang=` -> the `kci_lang` cookie ->
            `Accept-Language` (`zh-CN` and `zh-TW` are both `zh`) -> the default.
            A `?lang=` nobody knows is skipped rather than refused, so
            `?lang=fr` draws a page instead of a 500.
            """
            lang = pick_lang(_first(query, "lang"), self._cookie("kci_lang"),
                             self.headers.get("Accept-Language") or "")
            self._remember = lang if remember and "lang" in query else ""
            return lang

        def _cookie(self, name: str) -> str:
            """One cookie of the request, or `""` when it is not there."""
            for item in (self.headers.get("Cookie") or "").split(";"):
                key, _, value = item.partition("=")
                if key.strip() == name:
                    return value.strip()
            return ""

        # Set by `do_HEAD` for the length of one request: the headers are the
        # answer and the body is dropped (`_send`).  A class attribute so `_send`
        # never has to guess whether it was set.
        _head = False

        def _send(self, code: int, kind: str, text: str) -> None:
            blob = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(blob)))
            if code in (301, 302, 303, 307, 308):
                # A 302 and not a 301: this mapping is a decision of *this*
                # version of the page, and a permanent redirect is cached in the
                # browser for as long as the reader keeps it - a merge that later
                # changes its mind could not be undone in a tab that remembered.
                self.send_header("Location", text.strip())
            if self._remember:
                # Only a URL that really carried `?lang=` writes this, and there is
                # no `Secure`: the page listens on 127.0.0.1 over http.  It is the
                # one piece of client state this GUI keeps.
                self.send_header("Set-Cookie", f"kci_lang={self._remember}; Path=/; "
                                               "Max-Age=31536000; SameSite=Lax; HttpOnly")
            self.end_headers()
            if not self._head:
                self.wfile.write(blob)

        def log_message(self, *args: Any) -> None:
            pass                                            # one person is reading this

        def log_request(self, code: Any = "-", size: Any = "-") -> None:
            """Every request leaves one line: a slow page must be visible, not felt."""
            took = time.time() - getattr(self, "_started", time.time())
            note = "  <-- slow" if took > 2 else ""
            print(f"  {self.command} {self.path} -> {code}  {took:.2f}s{note}", flush=True)

        def handle_one_request(self) -> None:
            # A request starts having read nothing: whatever the last writer
            # wrote is what this page must show, and a keep-alive connection
            # serves several requests from this same thread.
            _request_scratch().clear()
            self._started = time.time()
            super().handle_one_request()

    return Handler


def serve(gui: Any) -> int:
    """Serve `gui` until interrupted; an impossible or taken port is reported, never swapped."""
    # A port outside the 16 bits a socket address has is refused here, before the
    # bind: `socket.bind()` answers it with `OverflowError`, which is an
    # `ArithmeticError` and **not** an `OSError`, so the `except` below never saw it
    # and `gui.py --port 99999` left as a traceback with exit 1 - the one way this
    # function could still fail.  0 is refused along with them, because `bind()` reads
    # it as "any free port": the page comes up on a port nobody chose while the line
    # below prints `http://127.0.0.1:0`, a URL that opens nothing.  Checking the range
    # here rather than in `gui.py` is what every caller of the server inherits.
    if not 1 <= gui.port <= 65535:
        raise errors.ConfigError(f"--port must be 1-65535, got {gui.port}")
    try:
        server = ThreadingHTTPServer((gui.host, gui.port), handler_for(gui))
    except OSError as exc:
        # No request, so no language: this one is drawn in the default one.  The
        # sentence still comes from the catalogue, so the day a `--lang` flag
        # exists, this line needs no change.
        raise errors.ConfigError(t(DEFAULT_LANG, "error.port_taken", host=gui.host,
                                   port=gui.port, why=exc)) from exc
    print(f"kernelci-riscv pages on http://{gui.host}:{gui.port}  (Ctrl-C stops it)",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        server.server_close()
    return errors.EXIT_PASS
