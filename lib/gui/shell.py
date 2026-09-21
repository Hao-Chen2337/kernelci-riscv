# SPDX-License-Identifier: LGPL-2.1-or-later
"""The page's chrome: the one template, its navigation and its live panel.

`render` is the route dispatch (`GUI.REDIRECTS`' three old addresses are answered in
`server.py`, before a page is ever drawn) and `_shell` is the template every page is
drawn in: the language links, the refresh control with the age of what was last read,
and the values a hand-edited URL asked for and did not get.

The live panel (`_live_panel`, `_live_row`, `_live_chip`) is here rather than on a page
of its own for the same reason: what is running now is the one fact a reader needs
wherever they are, and it is rendered by the server so it is there before any fetch.
`log_body` is the log as `text/plain`, opened like a file rather than shown as JSON,
and it is what every 日志 link on this page points at - there is no longer a box on the
page that a click fills instead."""

import html
import time
import urllib.parse
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .. import api as api_mod
from .. import errors
from .. import run as run_mod
from ..i18n import DEFAULT_LANG, LANGS, t
from .forms import _clamp, _first, _numbers, _token
from .models import Filter
from .schema import DEFAULT_DELTA, LIVE_KEPT, MAX_DELTA, NAV_KEYS, PAGES
from .server import _state_digest
from .templates import _CSS, _PAGE, _js
from .urls import _link, _url
from .values import _ago
from .widgets import _end_word, _pill

if TYPE_CHECKING:
    from collections.abc import Mapping

class ShellMixin:
    # --- the pages ---------------------------------------------------------

    def render(self, page: str = "/", query: "Mapping[str, list[str]] | None" = None,
               lang: str = DEFAULT_LANG) -> str:
        """One page as HTML: the route decides which, the query string is its state.

        `lang` is the language this answer is drawn in, negotiated by the handler
        (`Handler._lang`) and carried by every link the page writes.  The pages
        themselves, and every machine endpoint (`/summary.json`, `/api/*`), read it:
        those two are contracts and stay English whatever the reader asked for.

        `?api=` is read here, once per request, through `self.apis`: it may name a
        base or spell one out, and every page draws from the filter that comes back.
        Nothing about it is kept on `Gui` - the request's URL is the whole of its
        state, which is what lets two requests in two threads read two APIs.
        """
        query = query or {}
        check = Filter.from_query(query, lang, self.apis)
        if page in ("", "/", "/index.html"):
            return self._builds(check, lang)
        if page.startswith("/local/"):
            # The one route that is not in `PAGES`, and deliberately so: it is a
            # *detail* page for one build, not a station.  It stays where it was
            # (`03-structure.md` §d.6): it is where the operator reads a build's
            # whole record, and `_lang_links`'s `route=` argument is what keeps its
            # build id through a language switch.
            return self._correspondence(urllib.parse.unquote(page[len("/local/"):]), lang,
                                        check.api)
        if page == "/jobs":
            return self._jobs(check, lang)
        if page == "/runs":
            # `/runs` reads no API of its own, but it still carries the key: see
            # `_runs`, which hands `check.api` on as the page's own state.
            return self._runs(_first(query, "kind"), _first(query, "state"), lang, check.api)
        if page == "/worker":
            # The worker's own arguments are read from the URL, so the command
            # line under its button is the one the URL states - nothing else can
            # change between the page being drawn and the button being pressed.
            # **The queue's own state, when the URL names none.**  A worker page is about
            # what a worker can claim, so its default question is `state=available` -
            # spelled here rather than only in `_worker`, because the filter bar, the
            # table and the "现在可领取 N 个" badge all read the same query and must agree
            # about it (`_worker`'s own comment says why the *boxes* come from the rows).
            # `since` is the window the worker starts from (`--since`): read raw here,
            # because `_worker` has to be able to tell a stamp it honoured from one it
            # refused (`error.not_a_stamp`), and normalising it away in the caller would
            # turn a refusal into a silently dropped key.
            return self._worker(check, lang, state=_first(query, "state", "available"),
                                mode=_first(query, "mode"),
                                platform=_first(query, "platform"),
                                runtime=_first(query, "runtime"),
                                since=_first(query, "since"))
        if page.startswith("/analysis/"):
            # The single-build view the operator asked for (「单个那种也可能还要专门开发
            # 一个」), and the place the whole comparison is printed: `/analysis` names a
            # pair and shows its arithmetic, this route shows the pair.
            return self._one_build(urllib.parse.unquote(page[len("/analysis/"):]), check,
                                   _token(_first(query, "vs")), lang)
        if page == "/analysis":
            picks = [one for one in check.pick if one][:2]
            older = _token(_first(query, "older")) or (picks[0] if len(picks) == 2 else "")
            newer = _token(_first(query, "newer")) or (picks[1] if len(picks) == 2 else "")
            # Two page keys, read like `older`/`newer` so the state stays in the URL:
            #   `point` - the run a timeline cell selected (A6: the cells were inert
            #             `<span>`s, so `这个不能选` was literal);
            #   `delta` - how many rows of the order may spend a config read on their
            #             neighbours, clamped here because a URL is hand-editable and
            #             `?delta=600` would be a two-hour request (D3).
            point = _token(_first(query, "point"))
            delta = _clamp(_numbers(query, "delta", DEFAULT_DELTA), 0, MAX_DELTA)
            return self._analysis(check, older, newer, lang, point=point, delta=delta)
        raise errors.ConfigError(t(lang, "error.no_page", page=repr(page),
                                   routes=", ".join(route for route, _ in PAGES)))

    def _shell(self, name: str, body: str, check: "Filter | None" = None,
               notes: Iterable[str] = (), lang: str = DEFAULT_LANG, route: str = "",
               lang_keep: Iterable[tuple[str, str]] = ()) -> str:
        """The one template every page is drawn in: navigation, the numbers, the banners.

        **The counts line is gone.**  It said `27 build(s) in /home/…/builds.json, 7
        record(s) in /home/…/var/results, 50 activit(ies) in /home/…/var/runs` - three
        absolute paths, two machine plurals, and the three numbers the operator called
        "多余" - and `_numbers_strip` replaces it with the seven numbers the console
        actually has, each one a link to the rows it counts and each one read uncapped.
        Nothing about the paths is lost: each is now the `title=` of the number that
        counts it.  What stays on this line is the two things that are about *this*
        request and nothing else: the values a hand-edited URL asked for and did not
        get (a clamped number, an `?api=` nobody here knows), and the refresh control
        with the age of what was last read.

        It no longer names the API either: which API a page reads is set in its filter
        bar and stated in its own query line (`remote_query`), and a third place saying
        it again would be one more thing to keep in step with the two that decide it.

        `notes` are the failures *this* request ran into, and only those: the
        banner is about this page load, so it is built from what the page's own
        reads returned (the server answers requests in threads).

        `name` is the route's *name* (`builds`, `jobs`, ...) and stays English: it
        picks the navigation word (`nav.builds`) and marks the current page in the
        bar, and a bar that compared translated titles would stop marking anything
        the day a translation changed.  `route` is the path to come back to for the
        language switch (`/local/<id>` is not in `PAGES`), and `lang_keep` is the
        page's own state that is not a filter field (the /runs and /worker keys) -
        the same two things the refresh control needs, because it is the same URL.

        The digest is taken last, once the page's own reads are done, and it is what
        the poll compares (`state_poll`): a page drawn from one set of files that
        then re-reads itself the moment one of them changes.

        **The live panel is here and not on `/runs`.**  What is running now is the one
        fact a reader needs on *every* page, and a side panel that only exists on the
        page you are not looking at answers nothing: the operator's "有个任务运行最好
        把它放在动态的侧栏".  It is rendered by the server, so it is there with
        JavaScript off, before any fetch, and on an API that is answering slowly -
        which is also why the poll script does not build it, only updates it.

        The activities are read **once** for the three readers that want them (the
        panel, `busy`'s writer banner, the numbers strip's count), and the moment this
        answer was drawn rides to the page as `data-drawn`: the finish notice compares
        a run's own `ended` against it, so a reload cannot re-announce an old finish
        (`run_rows`, `_PAGE`, `07-shell.md` §C1).
        """
        rows = self.run_rows()
        running = [one for one in rows if one["state"] == run_mod.RUNNING]
        banners = ['<p class="banner bad">' + t(lang, "header.api_down", note=html.escape(one))
                   + "</p>" for one in notes if one]
        busy = self.busy(rows)
        if busy:
            banners.append('<p class="banner busy">'
                           + t(lang, "header.busy", writers=html.escape(", ".join(busy)))
                           + "</p>")
        capped = "".join(f' <span class="capped">{html.escape(one)}</span>'
                         for one in (check.clamps(lang) if check is not None else []))
        return _PAGE.format(
            lang=lang, title=t(lang, "nav." + name), nav=_nav(check, name, lang),
            langs=_lang_links(check, name, lang, route, lang_keep),
            live_chip=_live_chip(len(running), lang),
            drawn=f"{time.time():.3f}",
            live=_live_panel(rows, lang, kept=LIVE_KEPT),
            meta=(self._numbers_strip(check, lang) + capped + " "
                  + _refresh(_route_of(name, route), check, lang_keep, lang)),
            banners="".join(banners), body=body, css=_CSS,
            js=_js(lang, _state_digest()),
            tagline=t(lang, "header.tagline"))


def _route_of(name: str, route: str = "") -> str:
    """The path a page is served at: its own route, else its name's.

    `/local/<build_id>` is the one page that is not in `PAGES`, so it hands its path
    in (`_shell`'s `route`); everything else is looked up by the name that picks its
    navigation word.
    """
    return route or {title: path for path, title in PAGES}.get(name, "/")


def _lang_links(check: "Filter | None", current: str, lang: str,
                route: str = "", keep: Iterable[tuple[str, str]] = ()) -> str:
    """The header's language slot: one link per language, the current one marked.

    Each link is a URL, so it carries what this page reads - including the keys
    that are not filter fields (`/runs`'s kind and state, the worker's mode), which
    is what `keep` is for.  `route` overrides the path for the one page that is not
    in `PAGES` (`/local/<id>`), whose build id would otherwise be lost on a switch.

    Every href spells its own language out (`spell_lang=True`), the default one
    included.  Leaving the default out is what made this slot dead in one direction:
    the click into Chinese set `kci_lang=zh`, the English href then carried no
    `?lang=`, and `pick_lang` preferred the cookie - so `English` on a Chinese page
    answered in Chinese and the reader had no way back but to clear the cookie
    (`accept.py`'s N3).
    """
    here = _route_of(current, route)
    parts = []
    for one in LANGS:
        text = t(lang, f"lang.{one}")
        attrs = f'hreflang="{html.escape(one)}" lang="{html.escape(one)}"'
        if one == lang:
            attrs += ' aria-current="true"'
        href = _url(here, check, keep=keep, lang=one, spell_lang=True)
        parts.append(f'<a href="{html.escape(href)}" {attrs}>{html.escape(text)}</a>')
    return "".join(parts)


def _refresh(route: str, check: "Filter | None", keep: Iterable[tuple[str, str]] = (),
             lang: str = DEFAULT_LANG) -> str:
    """The one control that re-reads this page, and the age of what it last read.

    A link and not a button: every page here is a GET whose URL *is* its state, so
    "ask again" is the same URL with `fresh=1` in it - which is the one thing that
    turns the API cache off for that read (`_ttl_of`).  `keep` carries the page's
    own keys through it exactly as the language links do, so a refresh of `/worker`
    is a refresh of the worker page's question and not of a default one.

    The age beside it is not decoration.  An answer served from the cache and shown
    without its age is a page pretending it just asked, which is the one thing a
    cache here may not do (`docs/gui-rework/01-perf.md` §D2) - so the number is
    printed, and `?ttl=` is named in the `title=` for a reader who wants to know how
    long "cached" means.
    """
    age = api_mod.read_age()
    when = (t(lang, "refresh.now") if age is None or age < 1
            else t(lang, "refresh.age", age=_ago(age)))
    return (f'<a class="btn" href="'
            f'{html.escape(_url(route, check, keep=keep, lang=lang, fresh="1"))}" '
            f'title="{html.escape(t(lang, "refresh.title", ttl=_ago(api_mod.request_ttl())))}">'
            f'{html.escape(t(lang, "btn.refresh"))}</a> '
            f'<span class="pill idle">{html.escape(when)}</span>')


def _duration(seconds: float) -> str:
    """A run's own seconds as the panel prints them: `1m06s`, `28s`.

    A unit, not a sentence (`05-i18n-prose.md` §B.1 class 2): `1m06s` needs no
    translation and no plural rule, where "1 minute and 6 seconds" would need both.
    """
    whole = max(0, round(seconds or 0))
    return f"{whole // 60}m{whole % 60:02d}s" if whole >= 60 else f"{whole}s"


def _live_chip(count: int, lang: str = DEFAULT_LANG) -> str:
    """The header's one live fact: how many activities are running, and a link to them.

    A link and not a second list, because the header answers *is anything running*
    while the panel answers *what* - and it is the one live fact that has to be
    visible on every page and while scrolling, which is why it sits in the header's
    existing flex row rather than on a row of its own (`--head-h` is the sticky
    `thead`'s offset, and a wrap here would hide the header row under it).

    It carries the same two elements the panel's tab does (`.spin`, `.live-word`), so
    the poll script keeps both in step with one rule and one number.  The count comes
    from the same `run_rows()` the panel was drawn from, so chip and panel cannot
    disagree at render time.

    `header.busy` stays where it is: it is about *writes being refused*, and a running
    `results` shuts no gate (`07-shell.md` §A4).
    """
    word = (t(lang, "live.tab_running", n=count) if count else t(lang, "live.tab_idle"))
    spin = ('<span class="spin" aria-hidden="true"'
            + ("" if count else " hidden") + "></span>")
    return (f'<a class="live-chip{" idle" if not count else ""}" href="#live">'
            f'{spin}<span class="live-word">{html.escape(word)}</span></a>')


def _live_row(one: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """One activity in the panel: state, elapsed, what it is, its argv, and its two acts.

    The ended rows say the exit code **or say that none was seen**.  `Run._settle`
    (`lib/run.py`) turns a code it never learned into `failed`, so an activity whose
    process the GUI lost settles as `failed` with `exit_code: null` whatever the child
    really exited with - the live tree holds two such rows.  A panel that printed
    "failed" beside an invented code would repeat a claim nobody can check, so it
    prints `exit code not seen` and lets the pill carry the stored state
    (`07-shell.md` §A3, `live.exit_unknown`).

    `log` is a **real href**, not `href="#"`: it is the whole log, served as `text/plain`
    at `/runs/<id>/log` (`log_body`), and it opens in a tab of its own - so it works with
    JavaScript off, and a click is a navigation rather than a script that fills a box on
    this page (the operator's "某些日志点不开").  `_JS`'s `liveRow` writes the same link
    for the same row, because this panel is drawn here and only *updated* by the poll.
    """
    ended = one["state"] != run_mod.RUNNING
    code = one["exit_code"]
    exit_text = (t(lang, "live.exit", code=code) if code is not None
                 else t(lang, "live.exit_unknown"))
    argv = " ".join(str(part) for part in one["argv"])
    home = html.escape(str(one["id"]))
    acts = (f'<a href="/runs/{home}/log" target="_blank" rel="noopener">'
            f'{html.escape(t(lang, "link.log"))}</a>')
    if not ended:
        acts += (f'<form method="post" action="/api/runs/{home}/cancel">'
                 f'<button class="btn">{html.escape(t(lang, "js.cancel"))}</button></form>')
    return ('<li class="live-row ' + ("ended" if ended else "running") + '"'
            f' data-id="{home}" data-started="{float(one["started"] or 0):.3f}"'
            f' data-state="{html.escape(str(one["state"]))}">'
            '<div class="live-line">'
            + ("" if ended else '<span class="spin" aria-hidden="true"></span>')
            + _pill(one["state"], "run",
                    label=_end_word(one["state"], code, lang))
            + f'<code class="live-id">{home}</code>'
            + f'<span class="live-time num">{_duration(one["seconds"])}</span></div>'
            + f'<div class="live-what">{html.escape(str(one["what"])[:80])}</div>'
            + f'<code class="live-argv" title="{html.escape(argv)}">'
              f'{html.escape(argv)}</code>'
            + '<div class="live-act">'
            + (f'<span class="live-exit">{exit_text}</span>' if ended else "")
            + acts + "</div></li>")


def _live_panel(rows: list[dict[str, Any]], lang: str = DEFAULT_LANG,
                kept: int = LIVE_KEPT) -> str:
    """What is running now, and what just ended - the shell's own side panel.

    **Rendered by the server, not built by the script**, and that is the point: a page
    whose side panel exists only after a successful `fetch` shows nothing when
    JavaScript is off or the API answers slowly, and the running activity is exactly
    when the page is being read.  The script's job is to *update* this list, never to
    create it (`livePoll`).

    `open` follows the facts: something running means the panel is already out, so the
    reader sees it with no click; nothing running means it is a tab they can pull, and
    a quiet page does not lose 380px of width to an empty column.  That is also what
    "the sidebar must work without JavaScript" costs - one attribute, decided here.

    Nothing is computed.  A row is an activity on disk, and "recently ended" is the
    first `kept` rows of this same list that are not running - no verdict, no
    re-derivation of what `lib/judge.py` or the record says (ground rule 2).
    """
    running = [one for one in rows if one["state"] == run_mod.RUNNING]
    ended = [one for one in rows if one["state"] != run_mod.RUNNING][:kept]
    body = "".join(_live_row(one, lang) for one in (*running, *ended))
    head = t(lang, "live.head_running") if running else t(lang, "live.head_recent")
    word = (t(lang, "live.tab_running", n=len(running)) if running
            else t(lang, "live.tab_idle"))
    # The ring is drawn whether or not anything is running and hidden when nothing is,
    # so the poll script only ever toggles `hidden` on it - it never has to build the
    # element, and a page that has never run anything still has the shape.
    spin = ('<span class="spin" aria-hidden="true"'
            + ("" if running else " hidden") + "></span>")
    return ('<details class="live" id="live"' + (" open" if running else "") + ">"
            + f'<summary class="live-tab">{spin}'
              f'<span class="live-word">{html.escape(word)}</span></summary>'
            + '<div class="live-body"><div class="live-head">'
            + spin + f'<b class="live-headword">{html.escape(head)}</b>'
            + f'<span class="live-count">{len(running)}</span>'
            # Rendered `hidden` and unhidden by the script only where the browser
            # really has the Notification API: a button that does nothing because the
            # origin is not a secure context (a LAN address, not 127.0.0.1) is a worse
            # lie than no button.  It never prompts on its own - the click is the
            # gesture, which is the only form of this every browser accepts.
            + f'<button class="btn live-notify" type="button" data-notify="1" hidden>'
              f'{html.escape(t(lang, "live.notify_off"))}</button></div>'
            + f'<ul class="live-list">{body}</ul>'
            + f'<p class="live-empty"{" hidden" if body else ""}>'
              f'{html.escape(t(lang, "live.none"))}</p>'
            + '<noscript><p class="note">' + html.escape(t(lang, "live.noscript"))
            + "</p></noscript>"
            + "</div></details>")


def _nav(check: "Filter | None", current: str, lang: str = DEFAULT_LANG) -> str:
    """The navigation bar, with the current page spelled out and its conditions carried.

    Moving between pages keeps what the target reads and nothing more: the carry
    whitelist is the whole rule, so no link can quietly add a condition.  The pages
    are listed once - this bar *is* the list of them, which is why the footer no
    longer repeats it.

    `current` is a route *name*, and the comparison is made on it and never on the
    printed word: the day a translation changes, a bar that compared titles would
    stop marking the page the reader is on.
    """
    route_of = {title: route for route, title in PAGES}
    source = NAV_KEYS.get(route_of.get(current, ""), ())
    parts = []
    for route, title in PAGES:
        text = html.escape(t(lang, f"nav.{title}"))
        if title == current:
            parts.append(f"<b>{text}</b>")
            continue
        parts.append(_link(route, check, source, t(lang, f"nav.{title}"), lang))
    return " ".join(parts)
