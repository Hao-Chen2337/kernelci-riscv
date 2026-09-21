# SPDX-License-Identifier: LGPL-2.1-or-later
"""The activities page (`/runs`): what ran, what it ran, and the two things you can do to it.

One table (`_runs_table`), folded by kind in `KIND_ORDER` (`_by_kind`: bookkeeping
first-class and one click away, never filtered out) with a log link and a cancel button
per row.  The cells a refresh writes are the same cells this module prints - the script
in `templates` writes them a second time, in JavaScript, and `04-actions.md` §P8a is why."""

import html
from collections.abc import Iterable
from typing import Any

from ... import layout
from ... import run as run_mod
from ...i18n import DEFAULT_LANG, t
from ..models import Filter
from ..schema import FOLDED_KINDS, KIND_ORDER, _labels
from ..urls import _url
from ..widgets import (
    _cell,
    _end_word,
    _filter_bar,
    _pill,
    _row,
    _select,
    _table,
    _tally_word,
)


class RunsMixin:
    # --- /runs --------------------------------------------------------------

    def _runs(self, kind: str = "", state: str = "", lang: str = DEFAULT_LANG,
              api: str = "") -> str:
        """What is happening right now: every Run on disk, its log, and the cancel button.

        `/runs` reads two keys that are not filter fields at all, so its bar is
        the whole page state: no window is carried here, because an activity is
        not a build and a window would be a condition nothing reads.

        **This bar is deliberately not `_build_axes`, and the reason is the same one
        that keeps the window off it.**  The fourteen kbuild axes are questions about
        an API *node* - its tree, its arch, its defconfig, how many days back it was
        created - and a `Run` is a directory in `var/runs/` with a `run.json` in it.
        None of the fourteen filters an activity: there is no `arch` on a `table.py
        pull`, no `days` on a `rundrv` cancel, and `Filter.accepts` - the predicate
        that decides what an axis *means* - is never called on this page.  Drawing
        them here would put thirteen controls on the bar that change nothing, and a
        control that changes nothing is the failure this console's whole filter round
        was about.  What the two pages do share is `_filter_bar` itself: the axes
        strip, the hidden fields, the noscript note, the apply/clear pair and the
        `data-auto` script are one implementation, and this page's own two boxes
        (`kind`, `state`) are the only thing that differs.

        `api` is the one key this page carries without reading it.  An activity is
        not a build either - but the commands an operator runs *from* here are, and
        walking `/remote` (production) -> `/runs` -> `/remote` used to land back on
        the startup base with nothing said.  So the key rides as page state through
        the navigation and the language switch, and through this page's own form as
        a hidden field (`_form` writes any `ROUTE_KEYS` entry the page has no control
        for), and it is shown as a chip - a page that carries a condition says so.
        """
        # `api_base` is filled even when the URL carries no `api` key: this page hands
        # the key on without reading the API, and the strip's `api` axis has to name the
        # stack that key *means* - "any" beside a page that is carrying `api=local` into
        # every link would be the same under-reporting the F3 complaint is about.
        carried = Filter(api=api, api_base=self.apis.base(api))
        runs = self.run_rows()
        kinds = sorted({one["kind"] for one in runs})
        # **The bookkeeping is folded, and the fold is this page's filter state.**
        # 37 of the 50 activities here are `table.py index`, and they were interleaved
        # with the run the reader was watching - the operator's "为什么拉取或者这里就
        # run 也会显示".  `kind` arrives empty from a plain `/runs` and is filled with
        # the kinds the page shows, so everything downstream - the select box, the axes
        # strip, `rows_of`, and the 2 s poll's own guard - sees one answer to one
        # question.  A fold applied inside the renderer would be undone by the poll two
        # seconds later, which is the failure this whole file is about
        # (`docs/gui-rework/04-actions.md` §P8a).
        every = ",".join(kinds)
        asked = kind                       # what the URL said, before the fold fills it in
        folded = kind == "" and bool(FOLDED_KINDS)
        if folded:
            kind = ",".join(one for one in kinds if one not in FOLDED_KINDS)
        shown = self.run_rows(kind, state)
        body = [
            _filter_bar("/runs", [_select("kind", ("", *kinds), kind, t(lang, "word.kind"),
                                          lang=lang),
                                  _select("state", ("", run_mod.RUNNING, run_mod.DONE,
                                                    run_mod.FAILED, run_mod.CANCELLED),
                                          state, t(lang, "word.state"),
                                          labels=_labels("run_state", lang), lang=lang)],
                        carried, rendered=("kind", "state"),
                        keep=[("kind", kind), ("state", state)], lang=lang),
            # No intro sentence: it was four facts with no number, column or link in
            # them ("every activity is a directory with run.json and run.log; the argv
            # column is the exact command an operator would type; drift exits 1 when the
            # configs differ"), and accept.py's W1 found it after the first prose pass.
            # Each one is a `title=` now - the directory on the id cell, the full argv
            # on the argv cell (which always had it), the drift exit code on a drift
            # row's exit cell (`_runs_table`) - which is where `05-i18n-prose.md` §B.1
            # puts a fact a reader wants once, and never a paragraph over the table.
            # `rows_of="all"` only while the rows on screen are the whole list.  This is
            # the one activity table the 2 s poll may re-render, and the poll fetches
            # `/api/runs` with no filter at all: re-rendering a folded table would put
            # the 37 `table` rows back two seconds after the page said they were folded
            # - the "silently undone filter" `04-actions.md` §d.1 warns about, one level
            # up, and the same bug as `/pull` drawing one row and showing fifty.
            _runs_table(_by_kind(shown), empty=t(lang, "empty.no_activity"), lang=lang,
                        group=True,
                        rows_of="all" if (kind == every and not state) else ""),
            # A default that hides rows has to be *stated*, and undone in one click: the
            # count is in the group captions below and the box above, so this is the
            # link and nothing else (`05-i18n-prose.md` §B.1's four allowed classes).
            # The link spells **every** kind out.  Dropping `kind` instead would land on
            # a URL with no `kind` key, which is the *folded* page - a "show everything"
            # that shows the same rows is worse than no link at all.
            ('<p class="note">' + t(lang, "runs.folded_note",
                                    link=f'<a href="{html.escape(_url("/runs", carried, kind=every, lang=lang))}">'
                                         f'{html.escape(t(lang, "runs.show_all"))}</a>')
             + "</p>" if folded and kind else ""),
        ]
        return self._shell("runs", "".join(body), carried, (), lang, route="/runs",
                           # `asked`, not the folded `kind`: the language switch, the
                           # refresh control and the nav links are the same URL this
                           # page was reached by, so a bare `/runs` stays a bare
                           # `/runs` (folded, with its note) instead of turning into an
                           # explicit six-kind filter the reader never chose.
                           lang_keep=(("kind", asked), ("state", state)))


def _end_cell(row: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """The state cell: the pill, worded by the **exit code**, and the ledger's tally.

    The pill's word and its colour are two different answers and both are wanted
    (`_end_word`): `failed` is what `Run._settle` wrote about the process, and
    "tests failed" / "incomplete (infra)" is what the code says happened - a run whose
    tests failed is not the same event as a run whose command crashed, and the one
    state word for both is the operator's "a run with mixed results displays as
    failed".  The tally beside it is the number he was missing: 39 pass / 9 fail / 1
    incomplete is a run that did its work, and it is drawn only where the activity's
    argv names builds (`activities._add_tallies`) - a `table.py index` row has no
    builds and gets no number rather than a misleading zero.

    The script writes this same cell a second time (`drawTable`), so both halves come
    from the catalogue on both sides: the pill's words ride in `I18N.end_word` and the
    tally's format in `I18N.tally_one`, out of the same keys this line reads.
    """
    word = _end_word(row["state"], row["exit_code"], lang)
    tally = _tally_word(row.get("tally") or {}, lang)
    chip = f'<span class="tally">{html.escape(tally)}</span>' if tally else ""
    return _pill(row["state"], "run", label=word) + chip


def _by_kind(rows: list[dict[str, Any]], order: Iterable[str] = KIND_ORDER
             ) -> list[dict[str, Any]]:
    """The activity rows in the group order, each kind's rows kept in the page's own order.

    `sorted` on a key that is *not* in the order puts an unknown kind last rather than
    dropping it: a kind this page has never heard of (a `stack`, a `verify`) is a fact
    about the deployment, not something to hide.  `sorted` is stable, so within a kind
    the newest-first order `Run.load_all()` produced survives untouched.
    """
    wanted = list(order)
    return sorted(rows, key=lambda one: wanted.index(one["kind"])
                  if one["kind"] in wanted else len(wanted))


def _runs_table(rows: list[dict[str, Any]], empty: str = "",
                lang: str = DEFAULT_LANG, rows_of: str = "",
                group: bool = False, kinds: Iterable[str] = ()) -> str:
    """The activity table: what ran, what it ran, and the two things you can do to it.

    The markup here and the re-render in `_JS` are the same cells in the same
    order with the same classes: a table that changes shape when it refreshes is a
    table nobody can read while something runs.  They also read the same three
    words from the same keys - `link.log` and `js.cancel` are looked up here and
    injected into the script (`_js`), so a refreshed row cannot change language.
    That now includes the **group captions**: `group=True` emits one caption row per
    kind and hands the order to the script in `data-kinds`, because a poll that
    dropped the captions would re-shape the table two seconds after it was drawn.

    `rows_of` is passed straight through to `_table`: the caller that drew the *whole*
    activity list says so (`rows_of="all"`), and every caller that drew a subset -
    `/runs` with a kind or state filter, `/local/<id>` with one build's argv - leaves
    it out, which is what tells the 2 s poll to leave those rows alone.

    `group` is the classification the operator asked for in as many words: 37 of the
    50 activities on this deployment are `table.py index`, and they were interleaved
    with the run he was watching ("为什么拉取或者这里就 run 也会显示").  The caption
    is the kind - code vocabulary, translated by `runs.group` only for its brackets -
    and its count, so a reader can see at a glance which group is the noise.
    """
    head = (t(lang, "word.id"), t(lang, "word.kind"), t(lang, "word.state"),
            t(lang, "col.age"), t(lang, "col.exit"), t(lang, "col.what_run"),
            t(lang, "word.argv"), "")
    order = list(kinds) or list(KIND_ORDER)
    body: list[str] = []
    last = ""
    for row in rows:
        # The group caption rides in the **first cell of its group's first row** and
        # is not a row of its own.  A caption `<tr>` was the plan's shape
        # (`04-actions.md` §P8) and it is wrong here for a reason worth stating: a row
        # count is how this page is checked, the numbers strip counts *activities*
        # (every row of `var/runs`), and `accept.py`'s S6 finds that number by counting
        # `<tr>`s on this page - so a caption row per kind would make `activities 64`
        # unreproducible (70 `<tr>`s for 64 activities) and the label would be the lie
        # instead of the number.  `display: block` on the span gives it the caption's
        # own line; the count of what a row *is* stays exact.
        first = group and row["kind"] != last
        caption = ""
        if first:
            last = row["kind"]
            many = sum(1 for one in rows if one["kind"] == last)
            caption = (f'<span class="kind-group">'
                       f'{html.escape(t(lang, "runs.group", kind=last, n=many))}</span>')
        code = "-" if row["exit_code"] is None else row["exit_code"]
        argv = " ".join(row["argv"])
        # A `drift` activity's exit code is its *answer* (0 no drift, 1 drift), not a
        # failure - said where it applies, as a tooltip on that row's own cell, instead
        # of as a paragraph about every row above the table (`runs.intro`, deleted).
        exit_cell = (f'<span title="{html.escape(t(lang, "analysis.drift_hint"))}">{code}</span>'
                     if row["kind"] == "drift" else str(code))
        home = layout.runs(row["id"])
        body.append(_row((
            _cell(f'{caption}<code title="{html.escape(t(lang, "runs.dir_title", dir=home))}">'
                  f'{html.escape(row["id"])}</code>',
                  "id" + (" group-first" if first else "")),
            _cell(html.escape(row["kind"])),
            _cell(_end_cell(row, lang)),
            _cell(html.escape(row["age"]), "num"),
            _cell(exit_cell, "num"),
            _cell(html.escape(row["what"][:60]), "wrap"),
            _cell(f'<code title="{html.escape(argv)}">{html.escape(argv[:60])}</code>', "wrap"),
            _cell('<span class="cell-actions">'
                  # `href` is `/runs/<id>/log`, which serves the **whole** log as
                  # `text/plain` (`lib/gui/server.py`, `log_body`) - so the link is the
                  # log, not a promise of one.  It used to point at the JSON endpoint
                  # and carry `onclick="showLog(...);return false"`, which drew the tail
                  # into a box on this page and did **nothing at all** with JavaScript
                  # off (the operator's "某些日志点不开").  The box is gone and the link
                  # is a real one: a middle-click, a copy of the address and a click all
                  # give the same thing.  `target`/`rel` open it in a new tab without
                  # handing that tab a handle back into this page.
                  f'<a href="/runs/{html.escape(row["id"])}/log" '
                  f'target="_blank" rel="noopener">'
                  f'{html.escape(t(lang, "link.log"))}</a>'
                  f'<form method="post" action="/api/runs/{html.escape(row["id"])}/cancel">'
                  f'<button class="btn">{html.escape(t(lang, "js.cancel"))}</button>'
                  "</form></span>", "act"))))
    if not body:
        return f'<p class="empty">{empty}</p>' if empty else ""
    return _table(head, body, cls="runs", id="runs", rows_of=rows_of,
                  kinds=order if group else ())
