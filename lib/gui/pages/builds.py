# SPDX-License-Identifier: LGPL-2.1-or-later
"""The merged builds page (`/`) and the single-build view (`/local/<id>`).

One row per build id over the API's window and this machine's disk, with three facts
to a row that are never derived from one another: what the API says, what we hold, and
what the pull record claims.  `build_rows`/`build_row` are those rows, `_ledger_numbers`
and `_numbers_strip` are the seven numbers above them (each one a link to the rows it
counts, each one read uncapped), and `_coverage`/`ROW_BYTES` say what the row cap costs
and hides.

`_correspondence` is `/local/<id>`: a *detail* page for one build and deliberately not
a station in `PAGES`, which is where the operator reads a build's whole record - the
cards, the bytes, the pull record and the ledger's rows for it."""

import html
import os
import urllib.parse
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ... import errors, layout
from ... import re as re_mod
from ...i18n import DEFAULT_LANG, t
from ...re import Records
from ...tests import DEFAULT_TESTS
from ..cells import (
    _act_cell,
    _bytes_cell,
    _created_cell,
    _empty_builds,
    _ran_cell,
    _registered_cell,
    _remote_cell,
    _tick_all,
    _tick_failed,
    _tick_missing,
    _tree_branch,
)
from ..forms import _token
from ..models import Filter, Remote
from ..schema import MAX_LIMIT
from ..tables import _acts_table, _pulls_table, _records_table, _remote_detail
from ..urls import _url
from ..values import _human
from ..widgets import (
    _action_bar,
    _badge,
    _cell,
    _filter_bar,
    _h2,
    _number_chip,
    _number_row,
    _row,
    _table,
)
from .runs import _runs_table

if TYPE_CHECKING:
    from ...build import Builds
    from ...kbuild import Kbuild
    from ..models import Local

class BuildsMixin:
    # --- / : the merged builds page ----------------------------------------

    def _builds(self, check: Filter, lang: str = DEFAULT_LANG) -> str:
        """Every build id this machine and this API know, one row each, three facts to a row.

        `/`, `/remote`, `/local` and `/pull` were four renderings of one question -
        *for each build id, what does the API say, what do I hold, and what does the
        record claim?* - and each page made one of the three facts its subject, which
        is why the four of them disagreed.  The merge needs no new query key: `origin`
        was always the union's three sides (`ORIGINS`), so `/?origin=local` is the page
        `/local` was, and the three old routes are 302s onto here (`REDIRECTS`).

        **The three adjacent cells are the design.**  `card`, `bytes` and `act` state
        the three facts separately and each of them may be `-`, because none of the
        three is derived from the others: a row that reads `card - / bytes 30.4 MiB /
        acts 1` is the operator's bug ("拉了运行了还是显示卡片没拉取") told as data
        instead of as the paragraph (`page.overview.sub`) and the six-sentence glossary
        that used to explain it.  A row's *shape* is the diagnosis.

        **Two action bars, and none per row.**  `/jobs`' 51 `run` buttons are one bar
        over that page's own ticks; here the table's ticks feed one `pull`.  A form
        cannot submit another page's checkboxes, so the boxes are associated with a
        form of this page (`form="pull-now"`, `_pull_form`'s proven shape) - which is
        what keeps the bar working with JavaScript off, and why it lives above the
        table rather than under it (one id, one owner).

        **The tick column is the command's condition, not this page's.**  `table.py
        pull --build` reads the local table (`Builds.get`, build.py:676), so a row
        without a card is not tickable and says why: the box that used to be drawn
        there fed a command that refused with `no build '…' in builds.json`
        (`03-structure.md` §A3).  How many such rows there are is a number under the
        bar, not a paragraph.

        The activity table is not printed here.  It was 32,407 of the landing page's
        65,311 characters and it is the same fifty rows `/runs` already prints, so
        this page links to it (`counts.activities`).  No log is inlined here either:
        a run's whole log is a page of its own (`/runs/<id>/log`, `shell.py:290`).
        """
        table, records = self._state()
        held = self.all_locals()
        answer = self.remote_rows(check, held, lang)
        rows = self.build_rows(check, held, answer, lang)
        window = (("tree", check.tree), ("days", str(check.days)), ("limit", str(check.limit)))
        serve_image = layout.serve("Image")
        record = _action_bar("index", window, t(lang, "btn.record_window"),
                            argv=self._argv_of("index", dict(window), lang, api=check.api),
                            note="", hint=t(lang, "remote.index_hint"), lang=lang,
                            # `table.py index --tree` is one name, and the tree axis may
                            # now name several (`MULTI_FIELDS`): the button says which
                            # case this is rather than starting a command whose argv
                            # would refuse it (`_one_tree`).
                            blocked=self._one_tree(check, lang),
                            api=check.api)
        parts = [
            _remote_line(t(lang, "remote.asked"), answer, check, lang=lang),
            _filter_bar("/", [*self._build_axes("/", check, answer, lang=lang),
                              # What the cap costs and what it hides, in the form and
                              # beside the two fields it is about (§B5).  It replaces
                              # `filter.rows_note`, the 45-word sentence that used to
                              # sit under four tables.
                              _coverage(answer, check, lang)],
                        check, rendered=("api", "tree", "branch", "arch", "defconfig",
                                         "compiler", "state", "result", "days", "limit",
                                         "origin", "evidence", "missing"),
                        lang=lang, counts=self._axis_counts(check, answer.total)),
            # The view this page is showing, named and switchable, and no caption.  The
            # sub-line used to say what the page *is* ("the API's window and this disk,
            # one row per build id") - which is a sentence about the section, and a
            # sub-line is data or it is absent.  What a reader needs instead is which of
            # the three sets is in front of them and how big each one is, so the numbers
            # are the control: one press switches the view and keeps the filter.
            _h2(t(lang, "page.builds.title"),
                _view_presets("/", check, table, answer, lang)),
            record,
            _action_bar("pull", (), t(lang, "btn.pull_selected"), form_id="pull-now",
                        note=self._no_card_badge(rows, lang) + _tick_missing(rows, check, lang),
                        hint=t(lang, "pull.pull_hint"), lang=lang),
            _table((_tick_all("pull-now", len(rows), lang)
                    + _action_bar("pull", (), "", form_id="pull-one", lang=lang),
                    t(lang, "word.build_id"), t(lang, "word.tree_branch"),
                    t(lang, "word.created"), t(lang, "col.card"), t(lang, "col.bytes"),
                    t(lang, "col.act"), t(lang, "col.api_says"), t(lang, "filter.ran")),
                   [_row((_cell(self._tick_box(one, check, lang)),
                          # This one cell keeps the bare `<td><code title=…>` shape: the
                          # row probe an operator's own acceptance script counts this
                          # table by that prefix.
                          _cell(f'<code title="{html.escape(one["build_id"])}">'
                                f'{html.escape(one["build_id"][:16])}</code>'),
                          _cell(html.escape(_tree_branch(one)), "wrap"),
                          _cell(_created_cell(one, lang)),
                          _cell(_registered_cell(one, lang), "wrap"),
                          _cell(_bytes_cell(one)),
                          _cell(_act_cell(one, lang), "wrap"),
                          # Not escaped here: `_remote_cell` returns markup the same way
                          # `_registered_cell` and `_act_cell` do, and it escapes every
                          # value it interpolates itself.  Escaping its output printed the
                          # tags as text - `&lt;span title=…&gt;窗口外（上限 50）&lt;/span&gt;`.
                          _cell(_remote_cell(one, one["remote"], answer, lang), "wrap"),
                          _cell(_ran_cell(one), "act")))
                         for one in rows],
                   empty=_empty_builds(answer, held, lang),
                   cls="builds remote local"),
            _h2(t(lang, "page.builds.ledger_title")),
            self._ledger_numbers(table, records, lang),
            _h2(t(lang, "page.builds.acts_title"),
                # The retry, where the failure is reported: this page's own filter plus
                # the failed rows pre-ticked, so the reader lands on the same view with
                # the boxes already on and presses pull once.  `tick` is page state and
                # never leaves this URL (`Filter.to_query` excludes it), so the link
                # cannot smuggle a tick into another page.
                (_tick_failed(rows, check, lang) or t(lang, "page.builds.acts_sub")),
                id="acts"),
            _pulls_table(self.pull_acts(), api=check.api,
                         empty=t(lang, "empty.nothing_pulled",
                                 provenance=html.escape(
                                     os.path.basename(layout.provenance("x"))),
                                 downloads=html.escape(layout.downloads())), lang=lang),
            _h2(t(lang, "page.builds.image_title"),
                hint=t(lang, "page.builds.image_sub")),
            _action_bar("provision", [("tree", check.tree or "riscv")],
                        t(lang, "btn.publish_image"),
                        argv=self._argv_of("provision", {"tree": check.tree or "riscv"}, lang,
                                           api=check.api),
                        note=(t(lang, "local.image_state",
                                path=f'<code>{html.escape(serve_image)}</code>')
                              if os.path.isfile(serve_image)
                              else t(lang, "local.image_state_missing",
                                     path=f'<code>{html.escape(serve_image)}</code>')),
                        blocked=self._one_tree(check, lang),
                        lang=lang, api=check.api),
        ]
        return self._shell("builds", "".join(parts), check, [answer.note], lang, route="/")

    def build_rows(self, check: Filter, held: dict[str, "Local"], answer: Remote,
                   lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
        """One row per build id over the API's window and this disk, newest first, capped once.

        The union is the honest page: a build the API answered and we hold is one row
        carrying both halves, a build only the API knows shows `card -`, and a copy
        only this machine knows (a directory no card names) is the row the operator
        could not see anywhere before the merge.  Both halves arrive already filtered
        (`remote_rows` judges every API row against the real `{build_id: Local}`, and
        `filtered_locals` judges every copy), so this is a set union and not a second
        pass of the same question.

        The cap is applied **after** the merge, once: a page that capped both halves
        and then merged would print twice the rows it promised.

        The order is `created`, with two fallbacks that matter.  A card-less copy has
        no `created`, and its newest pull act is the newest thing anybody knows about
        it - without that fallback every such copy sorted to the bottom and fell off
        the end of the row cap, which is exactly how the build the operator pulled and
        ran became invisible on the page that lists local copies (`accept.py`'s S7
        read "not on the local listing page at all").
        """
        remote = {one.build_id: one for one in answer}
        # The API can answer one build id more than once, and the list built straight
        # from the answer printed it once per node: this deployment's own stack holds
        # three kbuild nodes for `6aade015d96a8203de6dff37`, so `/` printed that build
        # three times - on the page whose docstring promises one row per build id, and
        # whose row count the operator is asked to trust.  A build is one row; which
        # node answered is in the row's own `node_id`, and the answer's order (newest
        # first, which is how `remote_rows` read it) decides which of them it keeps.
        found = list(dict.fromkeys(one.build_id for one in answer))
        for local in self.filtered_locals(check):
            if local.build_id not in remote:
                found.append(local.build_id)
        rows = [self.build_row(remote.get(build_id), held.get(build_id), lang)
                for build_id in found]
        rows.sort(key=lambda one: (one["created"], one["build_id"]), reverse=True)
        # **In card mode the cap is not the page's to apply.**  `accepts()` lets
        # nothing but a carded row through when `origin=card`, so the row count *is* the
        # local table - and capping it meant the operator's own view of his cards hid
        # the oldest ones (`?origin=card` at the default `limit` showed 50 of 52, with
        # three cards missing entirely from `/`).  A cap on the disk is not a cap on a
        # query.  `limit` keeps its other job in that mode: the width of the API read.
        cap = check.limit if check.origin != "card" else MAX_LIMIT
        return rows[check.offset:check.offset + cap]

    def build_row(self, kbuild: "Kbuild | None", local: "Local | None",
                  lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """One row's three facts, kept apart: the card, the bytes and the pull record.

        The dict is what the cells read, and its keys say which fact each value came
        from - `in_table`/`node_id`/`act_node_id` are three different answers to "what
        do we know about this build", and `Local.node_id` collapses two of them on
        purpose (`node_id` falls back to the record).  The `card` cell needs to know
        *which* of the two spoke, so both are here.
        """
        card = local.card if local is not None else None
        records = self._state()[1]
        said = [card.created if card is not None else "",
                kbuild.created if kbuild is not None else "",
                str(local.latest.get("at") or "") if local is not None else ""]
        # Which of the three spoke, so the cell can say when the date is the pull's and
        # not the build's: a copy whose card we do not have has no `created` at all, and
        # the newest thing anybody knows about it is when it was pulled.
        when = next((one for one in said if one), "")
        build_id = (kbuild.build_id if kbuild is not None
                    else local.build_id if local is not None else "")
        # `Records.last` once per test, for every row: the ledger is keyed by build id
        # and does not care whether a card, a directory or only the API named this
        # build, so a row the API answered and we do not hold still shows what has been
        # run against that id - which is half of what `/jobs` computes its gap from.
        verdicts = {}
        for test in DEFAULT_TESTS:
            found = records.last(test, build_id)
            verdicts[test] = found.verdict if found is not None else ""
        return {
            "build_id": build_id,
            "describe": (card.describe() if card is not None
                         else kbuild.describe() if kbuild is not None else ""),
            "tree": (card.tree if card is not None
                     else kbuild.tree if kbuild is not None else ""),
            "branch": (card.branch if card is not None
                       else kbuild.branch if kbuild is not None else ""),
            "created": when,
            "created_from_act": bool(when) and not (card.created if card is not None else "")
                                 and not (kbuild.created if kbuild is not None else ""),
            "in_table": card is not None,
            "node_id": local.node_id if local is not None else "",
            "act_node_id": str(local.pull.get("node_id") or "") if local is not None else "",
            "local": local, "remote": kbuild,
            "state": local.state if local is not None else "",
            "present": sorted(local.present) if local is not None else [],
            "size": local.size() if local is not None else 0,
            "acts": len(local.acts) if local is not None else 0,
            "act_at": str(local.latest.get("at") or "") if local is not None else "",
            "act_hosts": local.hosts() if local is not None else [],
            "act_error": str(local.latest.get("error") or "") if local is not None else "",
            # How many artifacts are on disk *right now* (`Local.present` is an
            # `os.path.isfile` read per artifact), which is what a retry message owes the
            # reader: the act's own `entries` count says what that attempt did.
            "here_n": len(local.present) if local is not None else 0,
            "pull_failed": bool(local is not None and local.latest.get("error")),
            "state_text": local.state_text(lang) if local is not None else "",
            "verdicts": verdicts,
        }

    def _tick_box(self, one: dict[str, Any], check: "Filter",
                  lang: str = DEFAULT_LANG) -> str:
        """The tick box of one row - or the reason this row cannot be ticked at all.

        The reason is the cell's `title=` and the cell itself is the word for it
        (`pull.not_tickable`): the imperative that used to be printed here ("no card:
        record the window first") was fourteen characters of instruction in a column
        whose whole job is a checkbox, and the button that fixes it is already on the
        page, one hover away.
        """
        local = one["local"]
        if local is None or local.card is None:
            return (f'<span title="{html.escape(t(lang, "pull.no_card_title"))}">'
                    + t(lang, "pull.not_tickable") + "</span>")
        build_id = str(one["build_id"])
        checked = " checked" if build_id in check.tick else ""
        # **A button per row, and it is not a second interface**: it posts exactly one
        # `selected` to the same action the bar posts many to, so the command it runs is
        # `python3 table.py pull --build <this id>` - the same argv the row's own detail
        # page prints (`_argv_of("pull", …)`).  The operator's ask was 「就是想拉取卡片就轻松
        # 一点」: pulling one card should not require ticking a box, finding the bar, and
        # pressing a button that is also holding somebody else's ticks.
        return (f'<input type="checkbox" form="pull-now" name="selected" '
                f'value="{html.escape(build_id)}"{checked}>'
                f'<button class="btn" form="pull-one" name="selected" '
                f'value="{html.escape(build_id)}" '
                f'title="{html.escape(t(lang, "pull.one_title", build=build_id))}">'
                f'{html.escape(t(lang, "pull.one"))}</button>')

    def _no_card_badge(self, rows: Iterable[dict[str, Any]], lang: str = DEFAULT_LANG) -> str:
        """How many of these rows cannot be ticked, as the number the bar owes the reader."""
        without = sum(1 for one in rows
                      if one["local"] is None or one["local"].card is None)
        if not without:
            return ""
        return " " + _badge(t(lang, "counts.without_card", n=without),
                            t(lang, "pull.no_card_title"))

    def _ledger_numbers(self, table: "Builds", records: Records,
                        lang: str = DEFAULT_LANG) -> str:
        """The ledger's four numbers, with the code that produced each one in its title.

        `Records.tally()`, `re.todo()` and `re.transitions()` used to be a whole column
        of `<code>` cells beside these numbers - the page telling the reader which
        function it called, which is a mechanism and therefore a `title=`
        (`05-i18n-prose.md` §B.1).  The engine still owns every one of them: this
        method counts nothing (`00-BRIEF.md` §2).
        """
        return _number_row([
            _number_chip(t(lang, "label.records_in_ledger"), str(len(records)),
                         title=layout.results()),
            _number_chip(t(lang, "label.verdicts"),
                         ", ".join(f"{one}: {many}"
                                   for one, many in sorted(records.tally().items())) or "-",
                         title="Records.tally()"),
            _number_chip(t(lang, "counts.gap"), str(len(self.todo())),
                         title=t(lang, "label.gap") + " - re.todo()"),
            _number_chip(t(lang, "label.regressions"),
                         ", ".join(f"{test}: {len(re_mod.transitions(records, test))}"
                                   for test in DEFAULT_TESTS),
                         title="re.transitions()"),
        ])

    def _numbers_strip(self, check: "Filter | None", lang: str = DEFAULT_LANG) -> str:
        """The counts line, as seven numbers - every one of them a link to the rows it counts.

        The line it replaces said `27 build(s) in /home/…/builds.json, 7 record(s) in
        /home/…/var/results, 50 activit(ies) in /home/…/var/runs`: three absolute paths
        and a plural rule this catalogue does not have, around numbers two of which
        came from `local_rows(check)` - which slices `[offset:offset+limit]`, so a
        hand-typed `?limit=20` rewrote a number that describes this disk and the page
        printed two inventories of one machine that disagreed
        (`03-structure.md` §A2).  Every number here is read **uncapped** - the whole
        table, the whole download tree, every act, the whole ledger, `re.todo()` over
        the whole table, every activity - and every chip links to the rows it counted,
        with the count carried as the target's `limit` where the target caps rows: a
        number a link reproduces cannot be a cap in disguise.

        Two of the seven count a *file* rather than a set any page lists (`cards` is
        `var/state/builds.json`, `records` is `var/results`), so their link is the page
        that is about those rows and their `title` names the file - which is where the
        three paths of the counts line went.  A path is a fact about a number, and a
        fact about a number is a tooltip.
        """
        table, records = self._state()
        held = self.all_locals()
        local_rows = len(held)
        with_bytes = sum(1 for one in held.values() if one.present)
        acts = len(self.pull_acts())
        gap = len(self.todo())
        runs = len(self.runs())
        # The local chips carry the row count as the target's `limit`: `/` caps how
        # many rows it prints, and a chip that counted 53 copies but linked to a
        # 50-row page would be the same lie in a smaller size.  The remote/API chips
        # do not need it - `/runs` and `/jobs` read no API, and `limit` is capped by
        # `MAX_LIMIT` on the way in anyway.
        here = _url("/", check, lang=lang, origin="local",
                    limit=str(min(max(local_rows, 1), MAX_LIMIT)))
        # `cards` gets its own link and not `here`'s: the two numbers are different
        # sets as soon as one directory has no card (52 cards, 53 directories on this
        # workspace), and a chip that counted one set while linking at the other was
        # the one number on the page a reader could not check (`accept.py`'s S6).
        carded = _url("/", check, lang=lang, origin="card",
                      limit=str(min(max(len(table), 1), MAX_LIMIT)))
        kinds = sorted({one.kind for one in self.runs()})
        return _number_row([
            _number_chip(t(lang, "counts.cards"), str(len(table)), href=carded,
                         title=layout.index()),
            _number_chip(t(lang, "counts.here"), str(local_rows), href=here,
                         title=layout.downloads()),
            # `origin="any"` is not decoration: "has bytes on disk" is true of a
            # directory no card names, so a link that inherited `origin=card` from the
            # page it was drawn on printed **8** rows under a chip reading **9**
            # (`6a986b26e41d7f97d6f470bf` is pulled, has two artifacts and no card).
            # The count is `Local.present` over the whole download tree; the link has to
            # be the same set, which is what `accepts` decides once the origin stops
            # narrowing it.
            _number_chip(t(lang, "counts.bytes"), str(with_bytes),
                         href=_url("/", check, lang=lang, origin="any", evidence="bytes",
                                   limit=str(min(max(local_rows, 1), MAX_LIMIT))),
                         title=t(lang, "counts.title_bytes")),
            _number_chip(t(lang, "counts.acts"), str(acts), href="#acts",
                         title=t(lang, "counts.title_acts",
                                 provenance=layout.provenance("x"))),
            _number_chip(t(lang, "counts.records"),
                         str(min(len(records), MAX_LIMIT)),
                         href=_url("/jobs", check, lang=lang,
                                   limit=str(min(max(len(records), 1), MAX_LIMIT))),
                         title=t(lang, "counts.title_records", n=len(records),
                                 dir=layout.results())),
            _number_chip(t(lang, "counts.gap"), str(gap),
                         href=_url("/jobs", check, lang=lang,
                                   limit=str(min(max(gap, 1), MAX_LIMIT))),
                         title=t(lang, "label.gap") + " - re.todo()"),
            _number_chip(t(lang, "counts.activities"), str(runs),
                         # The kinds are spelled out, because `/runs` folds the `table`
                         # activities by default and this number counts **every**
                         # activity on disk: a link that landed on the folded page would
                         # show fewer rows than the chip says, which is the same lie in
                         # a smaller size.  `kind=<every kind>` is the page's own filter
                         # state (`_runs`), so the target is the unfolded /runs.
                         href=_url("/runs", check, lang=lang, kind=",".join(kinds)) if kinds else "",
                         title=layout.runs()),
        ])

    def _correspondence(self, build_id: str, lang: str = DEFAULT_LANG,
                        api: str = "") -> str:
        """One local copy's page: the card, the bytes, the record, the remote row, the ledger.

        `api` is the request's `?api=` key: this page asks the API for the build's
        remote counterpart, so it reads the one the URL names and nothing else.
        """
        build_id = _token(build_id)
        held = self.all_locals()
        if build_id not in held:
            raise errors.ConfigError(t(lang, "error.no_local_copy", build_id=repr(build_id)))
        local = held[build_id]
        check = Filter(limit=self.rows, origin="any", api=api)
        answer = self.remote_rows(check, held, lang)
        remote = next((one for one in answer if one.build_id == build_id), None)
        records = self._state()[1]
        search = build_id[:12]
        runs = [one for one in self.run_rows() if any(search in part for part in one["argv"])]
        body = [
            _h2(t(lang, 'page.correspondence.card_title'),
                hint=t(lang, 'page.correspondence.card_sub')),
            _table((t(lang, "col.field"), t(lang, "col.value")), [
                _row((_cell(t(lang, "word.build_id"), "id"),
                      _cell(f"<code>{html.escape(build_id)}</code>"))),
                _row((_cell(t(lang, "word.describe")),
                      _cell(html.escape(local.card.describe()) if local.card else "-", "wrap"))),
                _row((_cell(t(lang, "word.node_id")),
                      _cell(f"<code>{html.escape(local.card.node_id)}</code>"
                            if local.card and local.card.node_id
                            else (t(lang, "state.no_node_id") if local.card
                                  else t(lang, "state.not_in_table")), "wrap"))),
                _row((_cell(t(lang, "word.tree_branch")),
                      _cell(html.escape(f"{local.card.tree} / {local.card.branch}")
                            if local.card else "-"))),
                _row((_cell(t(lang, "word.arch_defconfig_compiler")),
                      _cell(html.escape(" / ".join(one for one in (local.card.arch,
                                                                   local.card.defconfig,
                                                                   local.card.compiler) if one))
                            if local.card else "-", "wrap"))),
                _row((_cell(t(lang, "word.created")),
                      _cell(html.escape((local.card.created if local.card else "") or "-")))),
                _row((_cell(t(lang, "label.artifact_urls")),
                      _cell("<br>".join(f"<code>{html.escape(name)}: {html.escape(url)}</code>"
                                        for name, url in (local.card.artifacts.items()
                                                          if local.card else [])) or "-", "wrap"))),
            ], cls="card-fields"),
            _h2(t(lang, 'page.correspondence.bytes_title'),
                hint=t(lang, 'page.correspondence.bytes_sub')),
            _table((t(lang, "col.artifact"), t(lang, "col.file"), t(lang, "col.bytes")), [
                _row((_cell(html.escape(name)), _cell(f"<code>{html.escape(path)}</code>", "wrap"),
                      _cell(f"{os.path.getsize(path)} ({_human(os.path.getsize(path))})"
                            if os.path.isfile(path) else "-", "num")))
                for name, path in sorted(local.present.items())],
                empty=t(lang, "empty.no_bytes", path=html.escape(local.path)), cls="bytes"),
            # The path is a fact about this section, and a fact about a section is a
            # tooltip (`02-dedupe.md` §C.0): a heading whose sub-line is
            # `/home/…/var/downloads/<id>/provenance.json` tells a reader the machine's
            # layout where it should be telling them what the section holds.  The row
            # count is the data, and the file is one hover away.
            _h2(t(lang, "page.correspondence.record_title"),
                t(lang, "count.acts_in_record", n=len(local.acts)),
                hint=layout.provenance(local.build_id)),
            _acts_table(local, empty=t(lang, "empty.no_pull_record"), lang=lang),
            _h2(t(lang, "page.correspondence.remote_title"),
                t(lang, "page.correspondence.remote_sub",
                  query=html.escape(self.remote_query(check, lang)))),
            _remote_detail(local, remote, self.remote_query(check, lang), answer.note, lang),
            # The literal used to be the sub-line.  A function name on screen is not a
            # sentence for a reader (`05-i18n-prose.md` §A.4's `Records / todo() /
            # transitions()` complaint); it is where the numbers come from, which is a
            # tooltip's job.
            _h2(t(lang, "page.correspondence.ledger_title"),
                hint="Records.for_build()"),
            _records_table(sorted(records.for_build(build_id),
                                  key=lambda one: one.timestamp or "", reverse=True),
                           empty=t(lang, "empty.no_ledger_record"), lang=lang),
            _h2(t(lang, 'page.correspondence.activities_title'),
                hint=t(lang, 'page.correspondence.activities_sub')),
            _runs_table(runs, empty=t(lang, "empty.no_activity_match"), lang=lang),
            _action_bar("pull", [("selected", build_id)], t(lang, "btn.pull_recheck"),
                        argv=self._argv_of("pull", {"selected": build_id}, lang),
                        hint=t(lang, "correspondence.pull_hint"), lang=lang),
            _action_bar("run", [("selected", build_id)], t(lang, "btn.run_pending"),
                        argv=self._argv_of("run", {"selected": build_id}, lang, api=api),
                        lang=lang, api=api),
        ]
        return self._shell("local", "".join(body), check, [answer.note], lang,
                           route="/local/" + urllib.parse.quote(build_id))


# 3.5 KB a row, measured: 175 082 bytes for the 50 rows `/remote` keeps
# (`docs/gui-rework/01-perf.md` §D1c).  It is the cap's own cost, so the cap's own
# readout quotes it: the operator asked for a `rows` he can type, and a control that
# does not say what a row costs is a control he cannot price - 1000 rows is 3.5 MB
# over a 20-35 KB/s link, not "more of the same".
ROW_BYTES = 3502


def _coverage(rows: "Remote", check: "Filter", lang: str = DEFAULT_LANG) -> str:
    """What the cap costs and what it hides, as four numbers.

    `rows.total` is the API's own count for this query - quoted, never counted from
    what came back, because what came back is what the cap allowed.  `outside` is the
    part of it no cap can show, `filtered here` is the part this page's own row filter
    dropped after the cap, and the bytes are `3.5 KB x cap`.  Four facts that used to
    be one 45-word sentence under four tables (`filter.rows_note`), which the operator
    read as `这个网页用起来很卡` and `不要这种垃圾文字注释` at once.
    """
    if rows.note:
        return (f'<span class="ofnum" title="{html.escape(rows.note)}"><b>&ndash;</b>'
                f'<span class="sub">{html.escape(t(lang, "filter.no_answer"))}</span></span>')
    if rows.total is None:
        return ""
    kb = ROW_BYTES * max(1, check.limit) // 1024
    cap = (f'<span class="ofnum" title="'
           f'{html.escape(t(lang, "filter.cap_title", bytes=ROW_BYTES, rows=50))}">'
           f'<b>{html.escape(t(lang, "filter.cap_bytes", kb=kb))}</b>'
           f'<span class="sub">{html.escape(t(lang, "filter.cap_rows", n=check.limit))}'
           f'</span></span>')
    total = (f'<span class="ofnum"><b>{rows.total}</b>'
             f'<span class="sub">{html.escape(t(lang, "filter.api_total"))}</span></span>')
    parts = [cap, total]
    if rows.total > check.limit:
        parts.append(f'<span class="gap"><b>{rows.total - check.limit}</b><span class="sub">'
                     f'{html.escape(t(lang, "filter.outside_cap"))}</span></span>')
    here = max(0, min(rows.total, check.limit) - rows.kept)
    if here:
        parts.append(f'<span class="gap"><b>{here}</b><span class="sub">'
                     f'{html.escape(t(lang, "filter.filtered_here"))}</span></span>')
    return "".join(parts)


def _view_presets(route: str, check: "Filter", table: Any, answer: "Remote | None",
                  lang: str = DEFAULT_LANG) -> str:
    """The three sets this list can be, as one pressable number each.

    `origin` is the axis that decides *which* builds a row set is about, and until now
    it was a `<select>` among fourteen other controls - so "the place that holds my
    cards" had no name on the page, and the default view had no way of saying it was
    one of three.  The three numbers are the engine's own (`len(table)`, the API's
    `total`, the union's row count), and each link keeps every other condition, so
    switching the view never changes the filter.

    The middle number is the API's own count and is left out when the API did not
    answer: a window nobody measured has no size, and `-` is the honest word for it.
    """
    links = []
    for value, key, number in (("card", "view.cards", len(table)),
                               ("any", "view.union", _union_size(table, answer)),
                               ("remote", "view.window",
                                answer.total if answer is not None else None)):
        label = t(lang, key, n="-" if number is None else str(number))
        href = _url(route, check, lang=lang, origin=value)
        links.append(f'<a href="{html.escape(href)}"'
                     + (' aria-current="true"' if check.origin == value else "")
                     + f">{html.escape(label)}</a>")
    return '<span class="quick">' + "".join(links) + "</span>"


def _union_size(table: Any, answer: "Remote | None") -> int:
    """How large the union of the API's answer and this disk is - measured, not guessed.

    A card whose build the answer did not carry is a row of the union and of nothing
    else, so the two sets cannot simply be added: the overlap is counted away by id.
    """
    named = {one.build_id for one in answer} if answer is not None else set()
    return len(named) + sum(1 for one in table if one.build_id not in named)


def _remote_line(lead: str, rows: "Remote", check: Filter, extra: str = "",
                 lang: str = DEFAULT_LANG) -> str:
    """The one line that says which API was asked, what it answered, and how much is shown.

    Three counts, kept apart: the rows this page prints, the rows the fetched
    window kept, and the API's own `total` for the query - which is quoted,
    because a page that counted its own rows would be answering its own question.
    An API that did not answer has no counts to print, and says that instead.

    `lead` is the sentence the caller looked up (`remote.asked`): the page owns the
    words, this function owns the counts.  `{query}` is the machine-readable question
    and stays exactly as it is in both languages.

    **The coverage sentence is a tooltip now.**  It used to end this line, and it is
    the only place a reader learns *why* a row is missing - "the API counts 1782 for
    this query, so 1732 older rows are outside the 50-row cap; 7 of the rows inside the
    cap are not in this table - this page's own filter, not the API".  That is a
    limitation of the API's window and of this page's filter, which is a definition and
    therefore a `title=` (`05-i18n-prose.md` §B.1), and it was the sentence the
    operator's own acceptance script greps for as prose (`accept.py`'s W1 list).  The
    counts it is about stay on the line as numbers; pressing the number is how a reader
    sees the rows.
    """
    if rows.note:
        return ('<p class="query">' + html.escape(lead) + ": "
                f'<code>{html.escape(rows.query)}</code> &mdash; '
                + t(lang, "remote.no_answer_line", note=html.escape(rows.note)) + "</p>")
    return ('<p class="query">' + html.escape(lead) + ": "
            f'<code>{html.escape(rows.query)}</code>'
            + (f" &mdash; {html.escape(extra)}; " if extra else " &mdash; ")
            + f'<span title="{html.escape(rows.coverage(lang))}">'
            + t(lang, "remote.line_tail",
                showing=t(lang, "remote.showing", shown=len(rows), kept=rows.kept),
                cap=t(lang, "remote.rows_cap", n=check.limit))
            + "</span></p>")


def _empty_remote(rows: "Remote", lang: str = DEFAULT_LANG) -> str:
    """Why the remote table is empty.

    "The API did not answer" and "the API answered with nothing" are two different
    facts, and a page that prints the second when the first is true is telling its
    reader the API has no such build.
    """
    if rows.note:
        return t(lang, "empty.remote_no_answer", note=html.escape(rows.note))
    return t(lang, "empty.remote_empty", query=html.escape(rows.query))
