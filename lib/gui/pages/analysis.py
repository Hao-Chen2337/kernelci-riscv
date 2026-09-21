# SPDX-License-Identifier: LGPL-2.1-or-later
"""The analysis pages: the list, one build, and one comparison.

`/analysis` lists the builds its filter chose, in the page's own order, each with the
`±` its neighbours give it (`_build_rows`, `_picks_table`, `_sort_control`) - the orders
are `sorting`'s and the deltas are `pairs`'.  `/analysis/<id>?vs=<id>` is the pair the
lists name: one build's whole record (`_one_build`), the two config edges that led to
it (`_config_edges`, and `_known_builds` for the ones this deployment can name), the
regression half (`trendview`) and the config difference (`driftview`).

Nothing here computes a comparison: `Drift` and `re.transitions()` do, and this module
is the two pages that show them."""

import html
import re
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from ... import errors
from ... import re as re_mod
from ...drift import Drift
from ...i18n import DEFAULT_LANG, t
from ...kbuild import KBUILD_JOB, Kbuild, Kbuilds
from ...tests import DEFAULT_TESTS
from ..driftview import _bar_chart, _config_delta, _drift_block, _pair_doors
from ..fields import _datalist, _name_field, _num
from ..models import Filter
from ..pairs import _build_ref, _chosen_pair, _compare_url, _delta_cell, _other_side
from ..schema import DEFAULT_DELTA, MAX_DELTA
from ..sorting import _sort_control, _sort_keys, _sort_label, _sort_rows
from ..trendview import (
    _local_url,
    _record_block,
    _timeline,
    _trend_edges,
    _trend_lines,
    _trend_rows,
    _trend_table,
    _wave_chart,
    _wave_slots,
)
from ..urls import _link, _url
from ..values import _last_verdict, _short
from ..widgets import _action_bar, _cell, _filter_bar, _h2, _pill, _row, _select, _table

if TYPE_CHECKING:
    from ...re import Records

class AnalysisMixin:
    # --- /analysis ----------------------------------------------------------

    def _analysis(self, check: Filter, older: str = "", newer: str = "",
                  lang: str = DEFAULT_LANG, point: str = "",
                  delta: int = DEFAULT_DELTA) -> str:
        """One model for both halves: select, sort, list with a `±`, chart.

        The operator's own design, and the whole page follows it:

        > 首先我通过筛选构建…下面是一个列表…还有就是一个排序…筛选决定了下面的构建是哪些，
        > 排序决定了这个构件以什么样的方式排序…排序决定了它以前一个序和后一个序进行一个比
        > 较…旁边可以写成那种加减…还可以画出一个图…回归分析也应该是类似一样搞

        **Selection decides the content; the order decides the comparison.**  The
        filter bar chooses the rows (`Filter.accepts`, plus `older`/`newer`/`test`),
        `sort` decides their order (a `Filter` field, so every link carries it), the
        list is in that order with an adjacent `±` against the row before *and* the row
        after, and a horizontal chart is drawn in the same order underneath.  The
        regression half is the same shape with the `test` chosen first.

        Costs, because this page has two expensive things and one of them is new:

        * the two builds the drift block names are read through `var/configs/`
          (`lib/drift.py`): the first look at a pair downloads two ~194 KB configs and
          every look after that is a file read (measured 15.92 s cold, 0.01 s warm,
          0 HTTP - `CHANGELOG.md` §2).  The comparison is eager, and *not* gated behind
          `?drift=1` as `06-analysis.md` §B4 proposed: with the cache in place the
          second load of this page costs nothing for it, a gate would put the only
          answer a reader came for behind a click (§D3's "hidden click"), and
          `accept.py`'s X2 asks a named pair for its detail *without* any such key -
          the check is right to, because the capability is what the operator asked for.
        * the `±` column reads **at most `delta` rows'** configs (`?delta=`, 0..6,
          default 3), one read per build, all of them from the cache after the first
          time.  `06-analysis.md` §D2 prices a pair at 7.5-12.5 s and ~194 KB cold,
          which is why the cap exists, why it is clamped here and not in the URL, and
          why the number in force is printed on the page.

        The trend half costs nothing: the ledger is on disk and read once per request.
        """
        records = self._state()[1]
        held = self.all_locals()
        # One read, two uses: the ids are the list the page can name, the `Kbuild`s are
        # what `Drift` needs - it must not scan the window for ids this page is showing.
        known, builds = self._known_builds(check.api, check.limit)
        catalogue = Kbuilds(self._client(self.api_base(check)), items=builds)
        rows = _build_rows(known, builds, check, records, held, lang)
        # The order, once: the list, the deltas and the chart all read this one answer.
        ordered = _sort_rows(rows, check.sort)[:check.limit]
        # The pair: what the URL named, else the page's own choice (`_chosen_pair`),
        # made against the *date* order - "the newest" is a fact about time, not about
        # the view the reader happens to have chosen.
        older, newer = _chosen_pair(_sort_rows(rows, "date"), older, newer)
        # **An id this page did not read is refused, never looked up.**  `older`/`newer`
        # are free text now, and `Drift.between` finds a build it was not handed by
        # asking the API for it - and the API can only be asked by *scanning* the newest
        # `SCAN` nodes, once per id: measured at 116.8 s and 137.9 s on production, and
        # it fails outright when one page of that scan comes back truncated
        # (`06-analysis.md` §A7.1, §D3).  A GET may not start that.  So the pair is
        # checked against the builds `_known_builds` already read (cards plus the rows
        # the API just answered), the refusal names the id, and `run drift.py` - an
        # activity, with its cost printed beside it - stays the way to go and look.
        unread = [one for one in (older, newer) if one and one not in set(known)]
        if unread:
            report = {"error": t(lang, "analysis.not_read", build=unread[0]),
                      "older": older, "newer": newer}
        elif older and newer:
            report = self.drift(older, newer, lang, check.api, catalogue=catalogue)
        else:
            report = {}
        # The compared head of the order, and its comparisons: `delta` rows at most, so
        # `delta`-1 adjacent pairs, and the ends of *that* are the ends the list prints.
        head = ordered[:max(0, int(delta))]
        edges = (self._config_edges(head, catalogue, check, lang) if len(head) > 1 else [])
        # Which configs this render read at all: the pair's two, plus the ones the
        # `±` column needed.  A number, not a sentence about caching - and the one a
        # reader weighing a reload or a bigger `delta` is looking for.
        edge_builds = {older, newer} | {row["build_id"] for row in head if row["config"]}
        page_keys = [("older", older), ("newer", newer), ("point", point),
                     ("delta", str(delta))]
        test = check.test or DEFAULT_TESTS[0]
        trends = {one: self.trend(one, check.limit)["points"] for one in DEFAULT_TESTS}
        trend_rows = _sort_rows(_trend_rows(trends[test], held, lang), check.sort)
        trend_edges = _trend_edges(trend_rows)
        # The chart's slots, once: one ledger lookup per position of the page's order.
        wave = _wave_slots(ordered, records, test)
        selected = next((one["point"] for one in trend_rows
                         if point and one["build_id"] == point), None)
        order_label = _sort_label(_sort_keys(check.sort), lang)
        body = [
            _filter_bar("/analysis", [
                # **The same axes the builds page has** - one template, as asked
                # (`像前面学习就是应该有类似统一的分析就是模板`).  The page's own three controls
                # follow: which test, the order, and how many rows may spend a config
                # read on their neighbours.
                *self._build_axes("/analysis", check, lang=lang),
                _select("test", DEFAULT_TESTS, test, t(lang, "word.test"), lang=lang),
                # The control is `limit`, which is the field `trend()` reads and the one
                # `Filter` has always had.  The page used to offer `scope`, which nothing
                # read: `?scope=10` did nothing while `?limit=10` worked.
                # (`/api/analysis/trend` keeps `scope` - that is its own contract,
                # GUI.md §4, and it is not this control.)  On this page it caps both
                # lists, which is what its label says it does.
                self._limit_field("/analysis", check, keep=page_keys, lang=lang),
                _sort_control("/analysis", check, _sort_keys(check.sort), keep=page_keys,
                              lang=lang),
                _datalist("deltas", [str(one) for one in range(MAX_DELTA + 1)]),
                _num("delta", str(delta), t(lang, "delta.cap"), 0, MAX_DELTA, "deltas",
                     stops=[str(one) for one in range(MAX_DELTA + 1)]),
                # The free hand: one input per key, and a candidate list that suggests
                # without constraining.  A typed id this page did not read is refused
                # (`drift()` hands `Drift` the catalogue, and an id outside it would be
                # a 1 000-node scan *inside a GET* - §D3), which the datalist is here to
                # make unnecessary: pasting the id of a row on this page always works.
                _datalist("builds", [row["build_id"] for row in ordered],
                          {row["build_id"]: row["ref"] for row in ordered}),
                _name_field("older", older, t(lang, "filter.older"), "builds", lang),
                _name_field("newer", newer, t(lang, "filter.newer"), "builds", lang)],
                check,
                # `sort` is deliberately **not** in `rendered`: its control is a row of
                # *links* (`_quick`), and a link is not a form field - so `_form` has to
                # carry it as a hidden input, or pressing `apply` after typing an id
                # would silently drop the order and compare neighbours the reader never
                # chose.  The six names here are the six real inputs/selects above.
                rendered=("api", "test", "limit", "delta", "older", "newer"),
                keep=page_keys, lang=lang),
            _h2(t(lang, "page.analysis.picks_title"),
                t(lang, "page.analysis.picks_sub", shown=len(ordered), pool=len(rows),
                  order=order_label)),
            _picks_table(ordered, check, older, newer, page_keys, len(head), edges, lang),
            (_h2(t(lang, "chart.title"), t(lang, "chart.sub", n=len(edges), order=order_label))
             + _bar_chart(edges, lang)) if edges else "",
            _h2(t(lang, "page.analysis.drift_title"),
                self._pair_line(report, older, newer, edge_builds, lang)),
            # **The full diff is not printed here.**  It was 265 KB of the page's 394 KB
            # (67 %), i.e. hundreds of `CONFIG_` names under a page whose question is
            # *which builds* - and the operator said what to do with it: 「就不用列一大串了」.
            # The badge above carries the arithmetic, the two raw `.config` links open the
            # files themselves, and the detail route prints the whole comparison for the
            # pair the reader actually wants to read.
            (_pair_doors(report, older, newer, check, lang) if report else
             "<p>" + t(lang, "analysis.choose_two",
                       link=_link("/local", Filter(api=check.api), (), "/local", lang)) + "</p>"),
            _action_bar("drift", [("older", older), ("newer", newer)],
                        t(lang, "btn.run_drift"),
                        argv=self._argv_of("drift", {"older": older, "newer": newer}, lang,
                                           api=check.api),
                        hint=t(lang, "analysis.drift_hint"), lang=lang, api=check.api),
            _h2(t(lang, "page.analysis.trend_title"),
                t(lang, "page.analysis.trend_sub", test=html.escape(test),
                  n=len(trends[test]), order=order_label)),
            _table((t(lang, "word.test"), t(lang, "label.runs"), t(lang, "label.last"),
                    t(lang, "label.regressions"), t(lang, "col.timeline")), [
                _row((_cell(html.escape(one)),
                      _cell(str(len(records.series(one))), "num"),
                      _cell(_pill(_last_verdict(records, one), "verdict")),
                      _cell(str(len(re_mod.transitions(records, one))), "num"),
                      _cell(_timeline(trends[one], check, page_keys, point, one, lang),
                            "wrap")))
                for one in DEFAULT_TESTS], cls="timeline-rows"),
            _h2(t(lang, "page.analysis.runs_title", test=html.escape(test)),
                t(lang, "page.analysis.runs_sub", n=len(trend_rows), cap=check.limit)),
            _trend_table(trend_rows, check, page_keys, point, test, len(trend_rows),
                         trend_edges, lang),
            # **The chart** (the operator's own ask: 回归分析还要加一个图，坐标就是排序的
            # 坐标).  It is drawn over the page's whole order - every row the list can name,
            # gaps included - because a chart that quietly dropped the positions with no
            # record would hide the one thing a reader looks for: a test that stopped.
            # The two numbers on its heading are counted from the same slots the chart
            # drew (`_wave_slots`), so the sentence and the picture cannot disagree.
            #
            # Two pictures of one order, and they are not alternatives: `_trend_lines`
            # draws the shape (one line per verdict, cumulative, errors emphasised) and
            # `_wave_chart` prints the numbers behind it position by position.  The
            # table is not a fallback - it is where `_trend_lines`'s shape is checked,
            # and the line chart is not a decoration of the table - it is the one
            # reading a strip of 50 identical cells cannot give (which verdict is
            # climbing).  Both read the same `wave` list, so one read serves both, and
            # each has its own caption because each has its own axes: the line chart's
            # `y` is a running count and its `x` is a position, and a caption that
            # named only one of them would leave the other to be guessed.
            (_h2(t(lang, "chart.lines_title"), t(lang, "chart.lines_sub"))
             + _trend_lines(wave, check, page_keys, point, test, lang)
             + _h2(t(lang, "chart.band_title", test=html.escape(test), order=order_label),
                   t(lang, "chart.band_sub", n=len(wave),
                     ran=sum(1 for one in wave if not one["gap"]),
                     gap=sum(1 for one in wave if one["gap"])), id="wave")
             + _wave_chart(wave, check, page_keys, point, test, lang)) if wave else "",
            _record_block(selected, held, next((row["ref"] for row in rows
                                                if row["build_id"] == point), ""),
                          lang) if selected else
            # A `point` the chosen test's list does not hold (a hand-made URL, or a
            # `point` left over from another test): the heading and its hint, rather
            # than silence.  A page that says nothing about a key it was given is the
            # silent no-op this whole rework is against.
            (_h2(t(lang, "page.analysis.point_title"), t(lang, "page.analysis.point_sub"))
             if point else ""),
        ]
        return self._shell("analysis", "".join(body), check, (), lang, route="/analysis",
                           lang_keep=tuple(page_keys))

    def _one_build(self, build_id: str, check: Filter, versus: str = "",
                   lang: str = DEFAULT_LANG) -> str:
        """One build, and — when `?vs=` names another — the whole comparison between them.

        This is the route the operator asked for twice: the single view (「单个那种也可能
        还要专门开发一个」) and the place the differences actually live (「点击会看到它那个
        比较…就不用列一大串了」).  A list of five hundred builds cannot print five hundred
        diffs; it can print five hundred numbers, and every one of those numbers is a
        door to here.

        The neighbours are recomputed rather than trusted from the URL: the filter and
        the order ride in the link (`_compare_url`), so this page runs the same
        `_known_builds` → `_build_rows` → `_sort_rows` pipeline the list ran and finds
        this build's position in it.  That is what makes "its neighbours" mean the
        neighbours *in the order the reader was looking at* - which is the operator's
        whole model: 排序决定了它以前一个序和后一个序进行一个比较.

        Nothing is fetched that the page did not already need: the same one API read,
        the same local table, the same ledger.  The comparison itself is the pair's two
        configs, and its cost is printed beside it (`page.analysis.drift_sub`).
        """
        records, held = self._state()[1], self.all_locals()
        known, builds = self._known_builds(check.api, check.limit)
        catalogue = Kbuilds(self._client(self.api_base(check)), items=builds)
        rows = _sort_rows(_build_rows(known, builds, check, records, held, lang),
                          _sort_keys(check.sort))
        here = next((at for at, row in enumerate(rows) if row["build_id"] == build_id), None)
        row = rows[here] if here is not None else next(
            (one for one in _build_rows(known, builds, check, records, held, lang)
             if one["build_id"] == build_id), None)
        order_label = _sort_label(_sort_keys(check.sort), lang)
        body = [_h2(t(lang, "page.one.title"),
                    t(lang, "page.one.sub", build=html.escape(_short(build_id, 16))))]
        if row is None:
            body.append("<p>" + t(lang, "one.no_neighbours") + "</p>")
        else:
            body.append(f'<p class="query">{row["line"]}<br>{row["marks"]}</p>')
        # The two neighbour comparisons of the order this build was clicked from.
        if here is not None:
            doors = []
            for at, name in ((here - 1, "delta.before"), (here + 1, "delta.after")):
                if 0 <= at < len(rows):
                    other = str(rows[at].get("build_id") or "")
                    doors.append(f'<a href="{html.escape(_compare_url(build_id, other, check, lang))}">'
                                 f'{html.escape(t(lang, name))} {html.escape(other[:12])}</a>')
            body.append(_h2(t(lang, "one.neighbours"),
                            t(lang, "page.analysis.picks_sub", shown=len(rows),
                              pool=len(known), order=order_label))
                        + ('<p class="query">' + " &middot; ".join(doors) + "</p>" if doors
                           else ""))
        # The comparison itself: the pair the URL names, or the one the operator picked.
        pair_older, pair_newer = (build_id, versus) if versus else ("", "")
        if pair_older and pair_newer:
            unread = [one for one in (pair_older, pair_newer) if one not in set(known)]
            report = ({"error": t(lang, "analysis.not_read", build=unread[0])}
                      if unread else
                      self.drift(pair_older, pair_newer, lang, check.api,
                                 catalogue=catalogue))
            configs = {one for one in (pair_older, pair_newer) if one}
            body.append(_h2(t(lang, "one.compare_title"),
                            self._pair_line(report, pair_older, pair_newer, configs, lang),
                            id="drift")
                        + _drift_block(report, lang)
                        + _action_bar("drift", [("older", pair_older), ("newer", pair_newer)],
                                      t(lang, "btn.run_drift"),
                                      argv=self._argv_of("drift",
                                                         {"older": pair_older,
                                                          "newer": pair_newer},
                                                         lang, api=check.api),
                                      hint=t(lang, "analysis.drift_hint"), lang=lang,
                                      api=check.api))
        else:
            body.append(_h2(t(lang, "one.compare_title"),
                            t(lang, "one.compare_line", older=html.escape(build_id[:12]),
                              newer="&mdash;")))
            # The chooser is the same page with `?vs=` filled in: the reader types the
            # other id into the one form above (which carries `vs` through `lang_keep`),
            # so this only has to name the key.  A link that guessed a build would be
            # comparing something nobody asked for.
            body.append("<p>" + t(lang, "one.vs_choose",
                                  link='<code>?vs=&lt;build_id&gt;</code>') + "</p>")
        body.append('<p class="query"><a href="'
                    + html.escape(_url("/analysis", check, "older", "newer", lang=lang))
                    + '">' + t(lang, "one.back") + "</a></p>")
        return self._shell("analysis", "".join(body), check, (), lang,
                           route="/analysis/" + urllib.parse.quote(build_id),
                           lang_keep=(("vs", versus),) if versus else ())

    def _pair_line(self, report: dict[str, Any], older: str, newer: str,
                   configs: "set[str]", lang: str = DEFAULT_LANG) -> str:
        """The pair's own line: which two builds, what kind of pair, how much drift, what it cost.

        The **badge** this page was missing.  Asked for two builds that differ by
        hundreds of options it renders hundreds of `CONFIG_` names; asked for nothing in
        particular it used to render one, because the default pair differed by a single
        option - honest, and read as `显示太少了` (`08-PLAN.md`, step 6's own finding).
        So the pair is named, the numbers are printed *before* the detail, and a pair
        that moved nothing says `+0 −0 ~0` here rather than leaving the reader to
        conclude the comparison is broken.

        The kind word is not decoration either: the engine refuses nothing on tree or
        branch, so 616/618/99 across two trees is a real number that must not be read as
        one kernel moving (`06-analysis.md` §D1).  The last number is `page.analysis.drift_sub`:
        how many builds' configs this render actually read, which is the fact that makes
        a reload cheap or expensive.
        """
        if not (older and newer):
            return ""
        same = report.get("same")
        kind = (t(lang, "drift.same_branch") if same else
                t(lang, "drift.cross_tree") if same is False else "")
        counts = (t(lang, "drift.badge", added=report["summary"]["added"],
                    removed=report["summary"]["removed"],
                    changed=report["summary"]["changed"])
                  if report and not report.get("error") else
                  t(lang, "delta.cannot") if report.get("error") else "")
        refs = " &rarr; ".join(html.escape(one) for one in
                               (report.get("older_ref") or older[:12],
                                report.get("newer_ref") or newer[:12]))
        cost = t(lang, "page.analysis.drift_sub", n=len([one for one in configs if one]))
        return " · ".join(part for part in (refs, kind, counts, cost) if part)

    def _config_edges(self, rows: list[dict[str, Any]], catalogue: Kbuilds,
                      check: Filter, lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
        """The comparisons between consecutive rows of the page's own order.

        One `Drift.series` call per **contiguous run of comparable rows**, so each
        build's config is read once and the six-millisecond difference is not the point -
        *one read per build, N-1 comparisons* is a sentence a reader can check
        (`lib/drift.py`).  Every read goes through `var/configs/`, so the first look at
        a pair downloads it and every look after that is a file read; nothing here
        fetches in a loop beyond the cap the reader set.

        A row with no card (`var/downloads/<id>/` and nothing in the table) has no
        `Kbuild` at all, so it cannot be a side of a comparison and it breaks the run:
        the two edges around it are recorded as refusals rather than skipped, because a
        list whose adjacency silently jumped a row would compare the wrong two builds
        (`这个为什么比不了` has to be answerable *per row*).

        A refused pair keeps its place and carries the engine's own words.
        """
        client = self._client(self.api_base(check))
        edges: list[dict[str, Any]] = []
        at = 0
        while at < len(rows) - 1:
            if rows[at]["kbuild"] is None or rows[at + 1]["kbuild"] is None:
                edges.append({"older": rows[at]["kbuild"], "newer": rows[at + 1]["kbuild"],
                              "report": None,
                              "error": t(lang, "state.no_card_in_table"),
                              "why": t(lang, "state.no_card_in_table")})
                at += 1
                continue
            run = [rows[at]]
            while at + 1 < len(rows) and rows[at + 1]["kbuild"] is not None:
                run.append(rows[at + 1])
                at += 1
            found = Drift.series(client, [row["kbuild"] for row in run],
                                 job=KBUILD_JOB, catalogue=catalogue)
            for older, newer, outcome in found:
                if isinstance(outcome, errors.KciError):
                    edges.append({"older": older, "newer": newer, "report": None,
                                  "error": str(outcome), "why": ""})
                else:
                    edges.append({"older": older, "newer": newer, "report": outcome,
                                  "error": "", "why": ""})
        return edges

    def _known_builds(self, api: str = "", rows: int = 0) -> tuple[list[str], list[Kbuild]]:
        """The builds a page can name: their ids, and the builds themselves.

        Two sources, and both are reads this page was going to make anyway:

        * **what we hold** (`all_locals()`): the table's cards, plus the directories
          under `var/downloads/` that no card names - a directory is still bytes, and
          its id may still be worth offering.  A card carries its own `Kbuild`
          (`Build.kbuild`, the row the API answered when it was registered), and that
          is the object to hand on: it is the row the artifacts were pulled from.
        * **what the API just answered** (`remote_rows`, capped like every read of a
          page).  Its rows are `Kbuild` objects already.

        The ids come out in one stable order - what we hold first, then the API's
        answers - deduplicated: the same list the page has always offered, from the same
        two reads (step 6 draws it as a table of links rather than as two `<select>`es,
        and sorts it for display; this is the *pool*, so a row that is off the end of a
        sort is still an id the page can name and compare).  The objects are what
        `/analysis` hands to `Drift` - it needs both builds' artifacts, and it must not
        scan the window again for ids this page is looking at right now (`drift()`, and
        `lib/kbuild.py: SCAN` for what that scan costs).

        `api` is the page's key: which API the box offers ids from is the same
        decision as which one the page reads - a box built from the local stack while
        the page asks production would offer two ids nobody there has heard of.

        `rows` is how many the API read may return, and it is the *reader's* `rows`
        and not a constant.  It used to be a hard `200`, and on this page that was
        the single most expensive line in the whole program: `/analysis` renders
        about 190 ids whether the reader asked for 50 rows or 500, and the API's
        cost is per row, not per query (`06-analysis.md` §A0 measured a 189-row
        read at 687 565 B and 31.14s where the same offset at `limit=50` answered
        the *identical page* in 153 651 B and 2.01s).  So the cap here is the one
        the reader chose, and a reader who wants a long chooser asks for more rows -
        which is exactly the control `rows` is.
        """
        ids: list[str] = []
        items: list[Kbuild] = []
        for build_id, local in self.all_locals().items():
            ids.append(build_id)
            if local.card is not None:
                items.append(local.card)
        for kbuild in self.remote_rows(Filter(limit=rows or self.rows, origin="any", api=api)):
            if kbuild.build_id not in ids:
                ids.append(kbuild.build_id)
                items.append(kbuild)
        return ids, items


def _build_rows(known: list[str], builds: list[Kbuild], check: Filter, records: "Records",
                held: Mapping[str, Any], lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
    """The builds this page can name, as rows: what it read, what it holds, what the ledger says.

    **The filter decides which builds are in this list.**  `tree`, `branch`, `arch`,
    `defconfig`, `compiler`, `state`, `result`, `text`, `origin`, `has`, `missing`,
    `evidence`, `ran` and `verdict` go through `Filter.accepts` - the same predicates
    every other table in this program uses - so the bar above the list means what it
    means everywhere else and the renderer computes nothing (`00-BRIEF.md` rule 2).

    Nothing here is fetched: the `Kbuild` comes from `_known_builds` (one read the page
    was making anyway), the local copy from `all_locals()` and the record count from
    `_state()`, both cached for this request.  The API cannot be asked for a build *by
    id* (`lib/kbuild.py: SCAN`, 116.8-137.9 s measured), so a chooser that wanted more
    detail per row would pay a hundred-second scan for it; everything a reader needs to
    tell two builds apart is in the row the page already has (`06-analysis.md` §A3).

    `known` is every id the page can name - including the directories under
    `var/downloads/` that no card names, which have no `Kbuild` at all.  They are rows
    too (the id, and what is on disk), they are simply not comparable: no card means no
    `_config` artifact, which is one of the three refusals §A7 measured.
    """
    cards = {build.build_id: build for build in builds}
    rows = []
    for build_id in known:
        kbuild = cards.get(build_id)
        local = held.get(build_id)
        if not check.accepts(kbuild, records, local):
            continue
        found = records.for_build(build_id)
        revision = (kbuild.revision or {}) if kbuild is not None else {}
        config = kbuild.artifact("_config") if kbuild is not None else ""
        rows.append({
            "build_id": build_id, "kbuild": kbuild,
            "created": str(kbuild.created or "") if kbuild is not None else "",
            "tree": str(kbuild.tree or "") if kbuild is not None else "",
            "branch": str(kbuild.branch or "") if kbuild is not None else "",
            "series": _series_of(revision.get("describe")),
            "verdict": found.items[-1].verdict if found.items else "",
            "config": bool(config), "config_url": config,
            "records": len(found),
            "held": bool(local is not None and local.present),
            "ref": _build_ref(kbuild),
            "line": _build_line(kbuild, revision, build_id),
            "marks": _build_marks(config, local, len(found), lang),
        })
    return rows


def _series_of(describe: Any) -> str:
    """The kernel series a build belongs to, out of its `describe` (`v6.12.108-2861-…` -> `v6.12`).

    The one signal this page has for "these are two different kernels" without reading a
    config.  It is searched for rather than anchored, because this deployment's newer
    builds carry a topic prefix (`asoc-fix-v7.3-rc3-803-g9f1c440f92830`) and an anchored
    pattern would call all of them series-less.  A describe string with no `v<major>.<minor>`
    (`next-20260915`) yields `''`, which `_chosen_pair` treats as *unknown* and never as
    a series of its own - the alternative would make two unknown builds "different".
    """
    found = re.search(r"\bv(\d+\.\d+)", str(describe or ""))
    return f"v{found.group(1)}" if found else ""


def _build_line(kbuild: "Kbuild | None", revision: Mapping[str, Any], build_id: str) -> str:
    """The two lines the operator asked for: what the build *is*, then its details.

    A native `<option>` cannot wrap to two lines - its content model is text, browsers
    render one line and ignore child elements (`06-analysis.md` §A4) - which is why the
    chooser is a table of links rather than a select box.  Line one is the fact that
    tells two builds apart, line two the fields a reader checks next.  The commit is
    shortened to twelve characters because the full forty are in the record's own
    `title` and on the correspondence page.
    """
    if kbuild is None:
        return (f'<code title="{html.escape(build_id)}">{html.escape(build_id)}</code>'
                '<br><span class="sub">-</span>')
    named = _build_ref(kbuild)
    detail = " · ".join(part for part in (str(kbuild.created or ""),
                                          str(kbuild.compiler or ""),
                                          str(kbuild.arch or ""),
                                          str(kbuild.defconfig or ""),
                                          str(revision.get("commit") or "")[:12]) if part)
    return (f'<b>{html.escape(named) or html.escape(build_id)}</b>'
            f'<br><span class="sub">{html.escape(detail)}</span>')


def _build_marks(config: str, local: Any, records: int, lang: str = DEFAULT_LANG) -> str:
    """Three marks per row: can this build be compared, is there a copy here, has it run.

    They are the facts that decide the questions a reader is about to ask, and two of
    them are what makes a doomed pair visible **before** it is picked: `config -` is a
    build no comparison can use (`06-analysis.md` §A7), and the artifact URL is in the
    `title=` for the reader who wants the raw file.
    """
    def mark(word: str, yes: bool, title: str = "") -> str:
        attr = f' title="{html.escape(title)}"' if title else ""
        return (f'<span class="{"yes" if yes else "no"}"{attr}>'
                f'{html.escape(word)} {"&#10003;" if yes else "&mdash;"}</span>')

    held = bool(local is not None and local.present)
    return ('<span class="marks">'
            + mark(t(lang, "word.config"), bool(config), config) + " "
            + mark(t(lang, "col.bytes"), held) + " "
            + f'<span>{t(lang, "mark.records")} {records}</span></span>')


def _picks_table(rows: list[dict[str, Any]], check: Filter, older: str, newer: str,
                 keep: Iterable[tuple[str, str]], compared: int, edges: list[dict[str, Any]],
                 lang: str = DEFAULT_LANG) -> str:
    """The list: the builds the filter chose, in the sort order, each with its neighbours' delta.

    **One list, three jobs** - which builds, in what order, and what changed between the
    neighbours in that order - because that is one question, and it is the operator's own
    design: "首先我通过筛选构建…下面是一个列表…还有就是一个排序…排序决定了它以前一个序和
    后一个序进行一个比较…旁边可以写成那种加减".

    The two left-hand cells are the *selection*, as links (`[older]` / `[newer]`) carrying
    the whole query, because two controls for one key is the failure mode this design has
    to avoid: a `<select name="older">` beside an `<input name="older">` and `_first()`
    would silently pick one.  So the rows are links and the only *inputs* are the two
    text boxes in the page's one GET form (`_filter_bar`), which is also where a pasted
    id goes - refused when it names a build this page did not read, because that path is
    a 116.8-137.9 s scan inside a GET (`06-analysis.md` §D3).
    """
    head = (t(lang, "col.n"), t(lang, "filter.older"), t(lang, "filter.newer"),
            t(lang, "word.build"),
            f'{t(lang, "col.delta")} <span class="sub">{t(lang, "col.delta_sub")}</span>')
    body = []
    for at, row in enumerate(rows):
        build_id = row["build_id"]
        picks = []
        for key, current, label in (("older", older, t(lang, "filter.older")),
                                    ("newer", newer, t(lang, "filter.newer"))):
            here = ' aria-current="true"' if build_id and build_id == current else ""
            # Both keys of the condition, because a pair needs two builds: the other
            # side is the page's own choice, or a swap when this row already holds it.
            href = _url("/analysis", check, keep=keep, lang=lang,
                        **{key: build_id,
                           ("newer" if key == "older" else "older"):
                               _other_side(key, build_id, older, newer)})
            picks.append(_cell(f'<a href="{html.escape(href)}"{here}>'
                               + label + "</a>", "act"))
        shown = (f'<a href="{html.escape(_local_url(build_id, lang))}">{row["line"]}</a>'
                 if row["held"] else row["line"])
        # The group break of `sort=same-branch`: a rule above the row where the
        # tree/branch changes, so the order the sort *means* is visible without a
        # caption row (which would be a row the chart and the deltas then have to skip).
        group = (_sort_keys(check.sort)[0][0] == "tree-branch" and at > 0
                 and (rows[at - 1]["tree"], rows[at - 1]["branch"])
                 != (row["tree"], row["branch"]))
        body.append(_row((_cell(str(at + 1), "num"), *picks,
                          _cell(shown + "<br>" + row["marks"], "wrap"),
                          _cell(_delta_cell(at, len(rows), compared, edges,
                                            lambda edge: _config_delta(edge, lang), lang,
                                            rows=rows, check=check),
                                "delta")),
                         cls=" ".join(part for part in ("group" if group else "",
                                                        "" if row["config"] else "nocfg")
                                      if part)))
    return _table(head, body, t(lang, "empty.no_builds"), cls="picks")
