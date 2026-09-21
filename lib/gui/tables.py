# SPDX-License-Identifier: LGPL-2.1-or-later
"""The small tables a page prints about the record: the ledger's rows, one copy's acts.

`_records_table` is what the ledger holds for one build (test, verdict, exit, source,
when and the detail), `_acts_table` and `_pulls_table` are the pull record's acts,
newest first, and `_remote_detail` is the remote side of one local copy - the row
this page's own query returned for it, or the fact that it returned none.

All four are read by the two pages that show a single build, `/jobs` and
`/local/<id>`, and by nothing else."""

import html
import re
import urllib.parse
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ..i18n import DEFAULT_LANG, t
from .models import Filter
from .urls import _url
from .values import _host, _human, _short
from .widgets import _cell, _pill, _row, _table

if TYPE_CHECKING:
    from ..kbuild import Kbuild
    from .models import Local

def _records_table(rows: Iterable[Any], empty: str = "", lang: str = DEFAULT_LANG,
                   title: bool = False, api: str = "") -> str:
    """The ledger's own rows: test, verdict, exit, source, when and the detail.

    One shape for the two pages that show records - a build's whole history on
    `/local/<id>` (`Records.for_build`) and the ledger itself on `/jobs`
    (`Records.load`).  Written once because the two were about to be two spellings of
    one table, which is how the `cards`/`records` columns of the two pages drifted
    apart in the first place (`03-structure.md` §A3).

    `title` adds the build id the record belongs to, which the per-build page has no
    use for (its whole page is one id) and the ledger page cannot do without: the
    `/jobs` table is the only place a reader can see a record for a build the local
    table no longer holds.  With `api` the id is a **link** to that build's own page,
    which is where the full record lives - one click, and the reader does not have to
    copy a hex id into the address bar.

    `detail` is printed **verbatim, and that is the decision**.  It is free text a
    child process wrote into the record (`lib/judge.py` produces `12 selftest(s): 9
    pass, 0 fail, 3 skip`), so a ledger written before that phrasing changed keeps the
    old words for ever; the value on screen is the value on disk, and a page that
    rewrote it would be claiming something about a run nobody can re-observe.
    `docs/gui-rework/tools/accept.py`'s W3 draws the line in the same place: a machine
    plural is the page's fault only when the *page* invented it.
    """
    head = ([t(lang, "word.build_id")] if title else []) + [
        t(lang, "word.test"), t(lang, "col.verdict"), t(lang, "col.exit"),
        t(lang, "col.source"), t(lang, "col.when"), t(lang, "col.detail")]
    built = []
    for one in rows:
        first = []
        if title:
            shown = (f'<code title="{html.escape(one.build_id)}">'
                     f'{html.escape(_short(one.build_id, 16))}</code>')
            href = _url("/local/" + urllib.parse.quote(one.build_id), Filter(api=api),
                        lang=lang)
            shown = f'<a href="{html.escape(href)}">{shown}</a>'
            first = [_cell(shown, "id")]
        built.append(_row(first
                          + [_cell(html.escape(one.test)),
                             _cell(_pill(one.verdict, "verdict")),
                             _cell(str(one.exit_code if one.exit_code is not None else "-"),
                                   "num"),
                             _cell(html.escape(one.source or "-"), "wrap"),
                             _cell(html.escape(one.timestamp or "-")),
                             _cell(html.escape(one.detail or ""), "wrap")]))
    return _table(head, built, empty=empty, cls="ledger")


def _pulls_table(acts: list[dict[str, Any]], empty: str = "",
                 lang: str = DEFAULT_LANG, api: str = "") -> str:
    """Every recorded pull act: what was pulled, from where, and when.

    `api` is the page's API key, and it is carried onto the `/local/<build_id>`
    links because that page reads an API of its own (the build's remote
    counterpart): leading the reader from a production pull act to a page that
    quietly queries the local stack would be the whole failure this key fixes.
    """
    return _table((t(lang, "col.when"), t(lang, "word.build_id"), t(lang, "col.artifacts"),
                   t(lang, "col.bytes"), t(lang, "col.transferred"), t(lang, "col.hosts"),
                   t(lang, "col.error")),
                  [_row((_cell(html.escape(one["at"]), "wrap"),
                         _cell(f'<a href="{html.escape(_url("/local/" + urllib.parse.quote(one["build_id"]), Filter(api=api), lang=lang))}">'
                               f'<code>{html.escape(one["build_id"][:16])}</code></a>', "id"),
                         _cell(str(one["entries_count"]), "num"),
                         _cell(f'{one["bytes"]} ({_human(one["bytes"])})', "num"),
                         _cell(str(sum(1 for entry in one["entries"]
                                       if isinstance(entry, dict)
                                       and entry.get("transferred"))), "num"),
                         _cell(html.escape(", ".join(sorted({
                             _host(str(entry.get("url") or "")) for entry in one["entries"]
                             if isinstance(entry, dict)}))), "wrap"),
                         _cell(html.escape(one["error"] or "-"), "wrap")))
                        for one in acts], empty=empty, cls="pulls")


def _acts_table(local: "Local", empty: str = "", lang: str = DEFAULT_LANG) -> str:
    """One copy's recorded acts, one block each: the newest first."""
    if not local.acts:
        return f'<p class="empty">{empty}</p>'
    parts = []
    for act in local.acts:
        entries = [one for one in act.get("entries") or [] if isinstance(one, dict)]
        parts.append(
            f'<p class="query"><b>{html.escape(str(act.get("at") or "?"))}</b> &mdash; '
            + t(lang, "count.artifacts_act", n=len(entries)) + ", "
            + (t(lang, "label.error_prefix", what=html.escape(str(act["error"])))
               if act.get("error") else t(lang, "state.no_error"))
            + "</p>")
        parts.append(_table((t(lang, "col.artifact"), t(lang, "word.url"), t(lang, "col.bytes"),
                             t(lang, "col.that_pull")), [
            _row((html.escape(str(one.get("artifact") or "")),
                  f'<code>{html.escape(str(one.get("url") or ""))}</code>',
                  f'{one.get("bytes")} ({_human(int(one.get("bytes") or 0))})',
                  t(lang, "col.transferred") if one.get("transferred")
                  else t(lang, "state.already_whole_proven")))
            for one in entries]))
    return "".join(parts)


def _remote_detail(local: "Local", remote: "Kbuild | None", query: str, note: str = "",
                   lang: str = DEFAULT_LANG) -> str:
    """The remote side of one local copy: the row this page's query returned, or none.

    Three different facts again: the API answered and has this row, the API
    answered without it, and the API did not answer at all - only the second of
    those is "not in that answer", and only the third says nothing either way.
    """
    if remote is None:
        if note:
            return ('<p class="query">'
                    + t(lang, "remote_detail.no_answer", note=html.escape(note)) + "</p>")
        # The visible words are the **same two words the list page uses**
        # (`state.no_remote_counterpart`) - the detail page and the row that led here now
        # name the same fact the same way - and the doctrine that used to be printed here
        # ("the window is the API's only way of being asked…") is the tooltip, because it
        # is a definition of the vocabulary and not data (`02-dedupe.md` §C.4).
        why = t(lang, "remote_detail.none", query=html.escape(query))
        return ('<p class="query" title="' + html.escape(re.sub(r"<[^>]+>", "", why)) + '">'
                + t(lang, "state.no_remote_counterpart") + "</p>")
    record_node = local.node_id
    warning = ""
    if record_node and remote.node_id and record_node != remote.node_id:
        warning = ('<p class="bad">'
                   + t(lang, "remote_detail.node_mismatch",
                       record=html.escape(record_node), api=html.escape(remote.node_id))
                   + "</p>")
    return warning + _table((t(lang, "word.build_id"), t(lang, "word.node_id"),
                             t(lang, "word.tree_branch"), t(lang, "word.created"),
                             t(lang, "word.state_result"), t(lang, "col.artifact_urls")), [
        _row((_cell(f'<code>{html.escape(remote.build_id)}</code>', "id"),
              _cell(f'<code>{html.escape(remote.node_id or "-")}</code>', "id"),
              _cell(html.escape(f"{remote.tree} / {remote.branch}")),
              _cell(html.escape((remote.created or "-")[:16])),
              _cell(f'{_pill(remote.state, "job")}{_pill(remote.result, "idle")}'),
              _cell("<br>".join(f"<code>{html.escape(name)}: {html.escape(url)}</code>"
                                for name, url in sorted(remote.artifacts.items())), "wrap")))],
        cls="remote-detail")
