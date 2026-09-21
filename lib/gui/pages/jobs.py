# SPDX-License-Identifier: LGPL-2.1-or-later
"""The jobs page (`/jobs`): one row per (build, test) pair, with its verdict.

The page the filter bar was built for: it draws the kbuild axes (`_build_axes`), runs
the query they state, and prints the ledger's own rows (`_records_table`) for each build
it selected - a verdict comes from `judge`, a gap from `todo`, and this page computes
neither.  The run bar under the table is `table.py run` on the rows whose boxes are
ticked, and the box a row does not have says why (`_other_test_tick`)."""

import html

from ...i18n import DEFAULT_LANG, t
from ...tests import DEFAULT_TESTS
from ..cells import _job_tick, _other_test_tick, _tick_all
from ..fields import _quick
from ..models import Filter
from ..schema import RANS, VERDICTS, _day_choices, _labels
from ..tables import _records_table
from ..widgets import (
    _action_bar,
    _badge,
    _cell,
    _filter_bar,
    _h2,
    _number_chip,
    _pill,
    _row,
    _select,
    _table,
)


class JobsMixin:
    # --- /jobs --------------------------------------------------------------

    def _jobs(self, check: Filter, lang: str = DEFAULT_LANG) -> str:
        """The gap: what the table minus the ledger leaves, one row per (build, test).

        **One action bar, not one button per row.**  Fifty-one `run` buttons down the
        last column became one bar that owns this table's tick boxes (`form="run-now"`,
        the association `_pull_form` proved, so the bar works with JavaScript off).
        That is a simplification and not a fix: the shape the operator's bug was made
        of - a row button carrying `selected` *and* `test` while the bar beside it
        carried neither - is gone, but the body reader (`_form_body`) is what makes any
        of these POSTs readable, and it stays (`CHANGELOG.md` §1).

        **The bar carries a `test` select, and the select never offers "any".**  That is
        why the test is a control *inside* the bar rather than a value the filter bar
        hands over: `Gui.command` reads `test` out of the body, and a body with no
        `test` at all makes `table.py run` fall back to all three tests, silently.  With
        `placeholder=False` the box always names one test, so the POST always carries
        one, and the box opens on the test in force in the URL.

        The ticks are per **build** and not per (build, test) row: the bar has one test,
        so two ticks of one build would be one command twice.  A box is drawn on the
        first row of each build and the rest of the group shows a dash; the argv under
        the bar is the argv for the test the box is holding.

        **The bar is `_build_axes`, and it is the same bar as `/`'s.**  This page used
        to draw a hand-rolled subset of it - api, tree, branch, test, ran, verdict,
        limit - so the one page whose rows are *pairs* was the page where a reader could
        not say `arch=`, `defconfig=`, `origin=` or "only the ones with bytes on disk",
        although `Filter.accepts` had always honoured every one of them.  Two of the
        fourteen were genuinely this page's own and stay: `test` (which of the three
        pairs) and `ran`/`verdict` (what the ledger says about it).  The day window is
        drawn here now too, which is what "the same day slider" means - `days` was in
        force and invisible, carried as a hidden field.

        **No `counts=` on this bar**, and that is a decision and not an omission: every
        axis badge is one `/count` against the *API*, and this page's rows come from the
        local table (`job_rows` reads cards and the ledger, never the API).  A badge
        counting 1756 production nodes beside a table of 12 local pairs would be a
        number about a different set, which is the one thing `_axes` may not print -
        "the strip then claims none - it never guesses".
        """
        table, records = self._state()
        rows = self.job_rows(check)
        gap = [one for one in rows if one["gap"]]
        # The rows are capped; the gap is not.  `re.todo()` owns the number and is asked
        # directly, so the page can show how much of the real gap it is showing.
        whole = len(self.todo(check))
        # **The box offers the catalogue, not the answer.**  `rows` is the *filtered*
        # set, so deriving the options from it made the `test` box collapse to the one
        # test in force the moment the reader chose it - the operator's "选了一个
        # test 之后下拉框只剩一个选项" - and the only way back was to clear the field
        # by hand.  The three `DEFAULT_TESTS` are what the box is *for* (the same list
        # the bar's own command falls back to, `_jobs`'s docstring), and a URL carrying
        # a test outside them still lands on its own value through `_select`'s
        # `(current)` fallback.
        #
        # `forms._tests_of` is deliberately **not** widened to match: it is the memo key
        # of `todo()` (`reads.py`) and what keeps the rows and the gap count about the
        # same pairs, and asking `re.todo()` for three tests when one was chosen would
        # print rows nobody asked for and move the number the page reports.
        tests = sorted(set(DEFAULT_TESTS) | {one["test"] for one in rows})
        seen: set[str] = set()
        found = []
        for one in rows:
            first = one["build_id"] not in seen
            seen.add(one["build_id"])
            found.append(_row((
                _cell(f'<code>{html.escape(one["build_id"][:16])}</code>', "id"),
                _cell(html.escape(one["tree"])), _cell(html.escape(one["test"])),
                _cell(html.escape(one["needs"]), "wrap"),
                _cell(html.escape(one["reason"] or t(lang, "state.ready")), "wrap"),
                _cell(str(one["runs"]), "num"),
                _cell(_pill(one["verdict"], "verdict")),
                _cell(html.escape((one["when"] or "-")[:16])),
                _cell(t(lang, "state.yes") if one["gap"]
                      else t(lang, "state.already_recorded")),
                # One box per (build, test) row when the page has chosen a test, and one
                # per build when it has not: with no test chosen the bar runs all three
                # tests for every ticked build, so a box per row would be three boxes
                # for one command (`_first` would silently decide which of the three
                # counted).  The operator's 「test 有些好像有但是不能勾选跑不了」 is exactly
                # this column: rows whose test was not the bar's printed a dash.
                _cell(_job_tick(one["build_id"])
                      if ((one["test"] == check.test) if check.test else first)
                      else _other_test_tick(one, check, lang)))))
        body = [
            # The gap as two numbers, where it used to be one sentence carrying four
            # machine plurals ("{shown} row(s) … {whole} (build, test) pair(s) … {cards}
            # card(s) and {records} record(s)").  The numbers stay - how much of the gap
            # this page is showing is the one thing a reader needs - and the code that
            # produced them (`re.todo()`) is the tooltip.
            ('<p class="query">'
             + _number_chip(t(lang, "counts.gap"), str(whole),
                            title=t(lang, "jobs.gap_title", cards=len(table),
                                    records=len(records), limit=check.limit))
             + " " + _number_chip(t(lang, "counts.shown"), str(len(gap))) + "</p>"),
            _filter_bar("/jobs", [*self._build_axes("/jobs", check, lang=lang),
                                  _select("test", ("", *tests), check.test, t(lang, "word.test"),
                                          lang=lang),
                                  _select("ran", RANS, check.ran, t(lang, "filter.ran"),
                                          placeholder=False,
                                          labels=_labels("ran", lang), lang=lang),
                                  _select("verdict", VERDICTS, check.verdict,
                                          t(lang, "filter.verdict"),
                                          labels=_labels("verdict", lang), lang=lang)],
                        check,
                        # Every control `_build_axes` draws, plus this page's own three.
                        # `rendered` is what stops `_form` writing a *second*, hidden
                        # input for a key the bar already shows - two values under one
                        # name, which `_first()` would then decide between silently.
                        rendered=("api", "tree", "branch", "arch", "defconfig", "compiler",
                                  "state", "result", "origin", "evidence", "missing",
                                  "days", "limit", "test", "ran", "verdict"),
                        lang=lang),
            # The sub-line said what the section *is* ("one command, so one test and any
            # builds"); the true rule is about the control above ("the test chosen there,
            # times every ticked build"), so it is the heading's tooltip and the heading
            # keeps its title.
            _h2(t(lang, 'page.jobs.run_title'), hint=t(lang, 'page.jobs.run_sub')),
            _action_bar("run", [("test", check.test)] if check.test else [],
                        t(lang, "btn.run_ticked"),
                        # Describe, never refuse: the ids do not exist until a box is
                        # ticked, so they are printed as the words that stand for them
                        # (`_argv_of_ticked`) instead of as this bar's own refusal.
                        #
                        # **The bar has no test box of its own any more.**  It used to
                        # carry a `<select name="test">` beside the filter bar's own
                        # `test` box, and the two could disagree: the table was drawn for
                        # one test while the command ran another, and a row for a test the
                        # bar was not holding printed `-` in the tick column - which is
                        # the operator's 「test 有些好像有但是不能勾选跑不了」.  One control now
                        # decides it (the filter's `test`, which is also what filters the
                        # rows), and with no test chosen the command runs all of
                        # `DEFAULT_TESTS` for every ticked build, which is what the bar
                        # says out loud.
                        argv=self._argv_of_ticked("run", {"test": check.test}, lang=lang,
                                                  api=check.api),
                        # A badge, not a sentence (`05-i18n-prose.md` §B.2): what the
                        # command does about the ledger is three words on screen and the
                        # escape hatch is the tooltip.  It replaces a sentence that was
                        # also *false* until `table.py run` learned to skip
                        # (`CHANGELOG.md` §4, `04-actions.md` item 3).
                        note=_badge(t(lang, "jobs.skips_badge"),
                                    title=t(lang, "jobs.run_hint")),
                        form_id="run-now",
                        lang=lang, api=check.api),
            _table((t(lang, "word.build_id"), t(lang, "word.tree"), t(lang, "word.test"),
                    t(lang, "col.needs"), t(lang, "col.ready"), t(lang, "label.runs"),
                    t(lang, "label.last"), t(lang, "col.when"), t(lang, "col.in_gap"),
                    # One box per *build* is drawn, so the select-all counts builds and
                    # not rows: `len({one["build_id"] for one in rows})`.
                    _tick_all("run-now", len({one["build_id"] for one in rows}), lang)),
                   found, empty=t(lang, "empty.no_gap"), cls="jobs"),
            # **The ledger's own rows.**  A gap is a difference between two sets, and
            # this page listed only one of them: the reader could see what is missing
            # and never what is there.  It is also why the numbers strip's `records`
            # chip was the one chip that reproduced nothing - it counted the ledger and
            # pointed here, where no ledger row was drawn (`accept.py`'s S6, added after
            # the merge).  The rows are `Records`' own, newest first, capped by this
            # page's `limit` like every other table; the chip's link carries that same
            # number as `limit`, so the count it prints is the count a reader finds.
            _h2(t(lang, "page.jobs.ledger_title"), hint="Records.load()", id="ledger"),
            _records_table(sorted(records, key=lambda one: one.timestamp or "",
                                  reverse=True)[:check.limit],
                           empty=t(lang, "empty.no_ledger_record"), lang=lang,
                           title=True, api=check.api),
            _h2(t(lang, "page.jobs.day_title"), hint="runday"),
            # **The tree and the branch come from the filter bar**, so the command and
            # the table agree; the literal `riscv` that used to stand here was a second
            # copy of `runday.py`'s own default (`--tree`, default "riscv"), and with no
            # tree chosen the argv now says nothing and `runday.py` decides - exactly how
            # `index` has always emitted it.  `branch` is emitted only when the box holds
            # one, because the flag itself is optional in both entry points.
            _action_bar("runday", [("tree", check.tree), ("branch", check.branch),
                                   ("days", str(check.days)),
                                   ("limit", str(check.limit))],
                        t(lang, "btn.run_day"),
                        argv=self._argv_of("runday", {"tree": check.tree,
                                                      "branch": check.branch,
                                                      "days": str(check.days),
                                                      "limit": str(check.limit)}, lang,
                                           api=check.api),
                        hint=t(lang, "jobs.runday_hint"),
                        # `--tree` is one name in `runday.py`'s own parser, and this
                        # page's tree axis may now name several: the button says which
                        # case it is in (`_one_tree`) instead of starting a command that
                        # would be refused at the argv.
                        blocked=self._one_tree(check, lang),
                        inner=_quick("days", "/jobs", check, str(check.days),
                                     _day_choices(lang), lead=t(lang, "filter.days"),
                                     lang=lang), lang=lang, api=check.api),
            _h2(t(lang, 'page.jobs.elsewhere_title'),
                hint=t(lang, 'page.jobs.elsewhere_sub')),
            _action_bar("fetch", [("tree", check.tree), ("branch", check.branch),
                                  ("test", check.test)],
                        t(lang, "btn.run_newest"),
                        argv=self._argv_of("fetch", {"tree": check.tree,
                                                     "branch": check.branch,
                                                     "test": check.test}, lang, api=check.api),
                        blocked=self._one_tree(check, lang),
                        lang=lang, api=check.api),
            _action_bar("results", [("test", check.test)], t(lang, "btn.ledger_full"),
                        argv=self._argv_of("results", {"test": check.test}, lang),
                        hint=t(lang, "jobs.results_hint"), lang=lang),
        ]
        return self._shell("jobs", "".join(body), check, (), lang, route="/jobs")



