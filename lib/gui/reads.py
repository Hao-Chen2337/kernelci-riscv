# SPDX-License-Identifier: LGPL-2.1-or-later
"""The reads behind the pages: what the API answered, and what is on this disk.

Every one of these is a *request's* read and none is a cache kept on `Gui`.  The local
files are read per request (`_state`) because the buttons on these pages start the very
commands that write them - a page that read them once at startup kept showing six
records after a seventh was written - and the API's own answers are memoised per
request by `lib/api.py`.  `remote_rows`/`remote_query` are the two halves of one
question (what the page asked, and what came back), `all_locals`/`filtered_locals`/
`local_rows` are the disk side of it, and `todo` is the gap between the two.

`Reads` is the one place a page asks "what do we have"; the pages themselves only
decide what to print."""

from typing import Any

from .. import api as api_mod
from .. import errors, layout
from .. import re as re_mod
from ..build import Build, Builds
from ..i18n import DEFAULT_LANG, t
from ..kbuild import Kbuild, Kbuilds
from ..re import Records
from ..tests import DEFAULT_TESTS
from .forms import _api_query, _axis_pairs, _query_text, _tests_of
from .models import Apis, Filter, Local, Remote
from .schema import API_FILTERS, API_TIMEOUT, FILTER_ORDER, MAX_AXIS_COUNTS, NO_WINDOW
from .server import _request_scratch
from .values import _dirs, _short_state


class ReadsMixin:
    # --- the reads behind the pages ----------------------------------------

    def _state(self) -> tuple[Builds, Records]:
        """The two local reads: the table and the ledger, read once per request.

        Read *per request* and not once at startup: the buttons on these pages start
        subprocesses (`table.py index`, `pull`, `run`, `runday`, `worker`) that write
        the table and the ledger, and a page whose reads were taken at startup kept
        showing six records after a seventh was written - the operator's "I ran boot
        and nothing changed", with the run's own `boot.json` on disk.  A restart is
        not a refresh (the page may state what it read, so it has to read).

        Once per request, and not once per caller: `/local` asks for 200 rows and
        `local_row()` wants the ledger for each of them, so this is where one parse
        of `var/results` per page load comes from.  The scratch space is the
        handler's, cleared at the start of every request (`_request_scratch`).

        `self.builds` / `self.records` are test overrides, not a cache: when one is
        set it is that object and never the disk.  The entry point passes neither.
        """
        held = _request_scratch()
        if "table" not in held:
            held["table"] = (self.builds if self.builds is not None else Builds.load(),
                             self.records if self.records is not None else Records.load())
        return held["table"]

    def launch_base(self) -> str:
        """The API this process started on: `--api-url`, `$KCI_API_URL`, else `LOCAL`.

        Asked of the client the entry point built when there is one - it is the one
        that carries whatever `config.client()` decided - and of `lib/api.py`'s own
        `Api.url()` otherwise, which is the very call `Api.__init__` makes to fill in
        `base`.  One answer either way, so "the startup value" is never a guess.
        """
        if self.api is not None:
            return str(getattr(self.api, "base", "") or "")
        return api_mod.Api.url(self.api_url or None).rstrip("/")

    @property
    def apis(self) -> Apis:
        """The base names this page can offer, built from the one startup value.

        A property and not a field: a field would be one more thing a request could
        set, and this round exists because a request's API must live in its URL and
        nowhere else.  `launch_base()` cannot change while the process runs, so there
        is nothing here to keep in step.
        """
        return Apis(launch=self.launch_base())

    def _client(self, base: str = "") -> api_mod.Api:
        """The API client one read goes through, for the base *this* request chose.

        The base is an argument and never a field of `Gui`.  The server is threaded,
        so a base kept on the instance would be the `self.note` race over again: a
        page asking production and a page asking the local stack, rendered at the same
        moment, would each read whichever base was written last.  Passing it means
        every read of one request builds its client from the same string, and no
        request can see another's.

        The client the entry point built is reused for the base it was built for
        (same session, same timeout, whatever token it carries); a switch to another
        base builds a fresh `Api`, which is a `requests.Session` and three attributes.
        """
        base = base or self.launch_base()
        if self.api is not None and base == self.launch_base():
            return self.api
        return api_mod.Api(base or None, timeout=API_TIMEOUT)

    def api_base(self, check: "Filter | None" = None) -> str:
        """The base one page reads - what its queries go to and what its `--api-url`
        carries.  One function for both, so a page's command line and its reads can
        never name two different APIs."""
        return self.apis.base(check.api if check is not None else "")

    def remote_query(self, check: "Filter | None" = None, lang: str = DEFAULT_LANG) -> str:
        """The question this page really asked, in the API's own spelling.

        It opens with the API it was put to and not with the flags: "showing 2 of 2"
        reads very differently once the line says the page asked the local stack, and
        this is the one place a page states the address it actually used.  The name a
        URL carries (`api=production`) is deliberately *not* what is printed here -
        the address is - so the short form in the address bar hides nothing.

        **The keys are the wire's keys, not ours.**  The line used to read
        `kind=kbuild job=kbuild-gcc-14-riscv tree=riscv branch=any no window (all)`,
        which is a paraphrase in three places at once: the key is `name=`, the tree is
        `data.kernel_revision.tree=`, and "no window" is the *absence* of
        `created__gte`.  `remote_query`'s own docstring has always promised that the
        flags and values "stay as they are in both languages: this line is a query an
        operator copies into a command" - and an operator who copied `tree=riscv` into
        `curl` got **0**, because the API has no `tree` field
        (`docs/gui-rework/02-filters.md` §A3).  So it is built by `_api_query`, the
        same function `remote_rows` sends, and the two cannot drift.

        Only the opening "asked &lt;base&gt;:" is a sentence, and only it is translated.
        Which axes are in force, *including the ones at their default*, is the axes
        strip's job (`_axes`) and not this line's: a query elides its defaults, and
        "window is all" is exactly the kind of fact a key/value strip can carry and a
        query line cannot.
        """
        check = check or Filter(limit=self.rows, origin="any")
        return t(lang, "remote.query_from", api=self.api_base(check),
                 query=_query_text(_api_query(check, "kbuild")))

    def _axis_counts(self, check: Filter, total: "int | None" = None,
                     kind: str = "kbuild") -> dict[str, int]:
        """What each axis in force matched **on its own**, as the axes strip's badge.

        A filter that removed 11 rows of 1782 has to *look* like one that removed 11
        rows: `arch=riscv`, `compiler=gcc-14` and `defconfig=defconfig` each match 1771
        of the 1782 nodes this page's query holds, and offered as ordinary controls
        they read as filters that worked (`02-filters.md` §A1, §B4).  The number is the
        API's own count for `kind`+`name`+window **plus this one axis**, and `_total` is
        the same query with no value axis at all - the denominator the strip greys a
        badge against.

        Two things keep this from being a licence to spend: only axes **in force** get a
        count (never the offers, never prefetched), and past `MAX_AXIS_COUNTS` axes the
        strip prints no number at all rather than a guess.  Each count is one `/count`,
        which the request's TTL answers from cache on a reload - and on a page nobody
        has filtered, this makes **no call at all**: the strip then shows values with no
        badges, which is exactly right, because nothing is being claimed about them.

        `total` is the read's own `Remote.total` and is quoted, not used: the count for
        the *whole* question is the number the axes strip compares against nothing.
        """
        axes = [name for name in FILTER_ORDER
                if API_FILTERS.get(name, {}).get(kind)
                and str(getattr(check, name, "") or "")]
        if not axes or len(axes) > MAX_AXIS_COUNTS:
            return {}
        client = self._client(self.api_base(check))
        base = dict(_api_query(Filter(days=check.days), kind))
        found: dict[str, int] = {}
        for name in [*axes, "_total"]:
            filters = dict(base)
            if name != "_total":
                # The axis's own pair(s), from the same function `_api_query` uses:
                # a multi-valued axis is `data.…__in=a,b` on the wire, and a count
                # asked with the comma-joined *plain* key answered `None` after 38 s
                # (`_axis_pairs` is where that was measured).  The badge and the read
                # cannot disagree, which is what one builder buys.
                for path, value in _axis_pairs(name, API_FILTERS[name][kind],
                                               str(getattr(check, name))):
                    filters[path] = value
            counted = client.count(kind=kind, filters=filters)
            if counted is None:
                # No `/count` (or a budget that ran out) means no number: the strip
                # prints fewer badges, never an invented one.
                return {}
            found[name] = int(counted)
        return found

    def remote_rows(self, check: "Filter | None" = None, held: dict | None = None,
                    lang: str = DEFAULT_LANG) -> Remote:
        """What the API answers for this filter: the newest rows, and the counts.

        The read is capped at `check.limit` (the API has no sort parameter, so the
        newest rows are its tail - one count plus one page instead of the whole
        window), which is exactly why the answer carries three counts instead of
        one.  A failure is kept in `note` and shown on the page: an empty remote
        table and "the API did not answer" are different answers, and the page
        must not let one look like the other.

        **The whole question is built once, by `_api_query`.**  The tree, the window
        and the branch used to be `getdays()`'s three arguments and every other value
        key was applied afterwards; now `getdays()` is asked for the job's rows and
        `extra=` carries *the same pairs the page prints* into the read, so the line
        under the table and the request behind it cannot disagree - which is what
        `02-filters.md` §A3 found them doing.

        `held` is the local copies the `origin`/`evidence` filters judge; without
        it the page's own `{build_id: Local}` is read here.  It must be the real
        one: `accepts()` reads `local=None` as "we hold nothing", so
        `origin=local` matched no row at all - which is how /pull reported zero
        candidates while /local listed four copies.

        The failure reason travels in the returned `Remote.note`, never on `Gui`:
        the server is threaded, so a note kept on the instance would be printed on
        whichever page happened to be rendered at the same moment.
        """
        check = check or Filter(limit=self.rows, origin="any")
        # The question, once, as the pairs `_api_query` built: the line printed under
        # the table and the keys the read is handed are the same object, which is what
        # `02-filters.md` §A3 found them not being (`job=` on the page, `name=` on the
        # wire).  `extra=` is how a read that takes three arguments carries eighteen
        # keys: applying the difference *after* the row cap made `arch=riscv` a sample
        # of 50 rows instead of an answer (`02-filters.md` §P7), and wrapping the whole
        # client to avoid it (`_Narrowed`) was the wrong seam.
        pairs = _api_query(check, "kbuild")
        catalogue = Kbuilds(self._client(self.api_base(check)))
        try:
            found = catalogue.getdays("", NO_WINDOW, None, limit=check.limit,
                                      extra=dict(pairs))
        except errors.KciError as exc:
            return Remote(query=t(lang, "remote.query_from", api=self.api_base(check),
                                  query=_query_text(pairs)),
                          limit=check.limit, note=str(exc))
        records = self._state()[1]
        held = self.all_locals() if held is None else held
        kept = [one for one in found if check.accepts(one, records, held.get(one.build_id))]
        return Remote(query=t(lang, "remote.query_from", api=self.api_base(check),
                              query=_query_text(pairs)),
                      shown=tuple(kept[:check.limit]),
                      kept=len(kept), total=catalogue.total, limit=check.limit)

    def local_of(self, build_id: str, card: Kbuild | None = None) -> "Local":
        """The facts about one local copy, read from disk: the bytes and the pull record."""
        local = Local(build_id=build_id, card=card)
        disk = Build(path=local.path)
        local.present = disk.present()
        local.pull = disk.provenance()
        return local

    def all_locals(self) -> dict[str, Local]:
        """Every local copy by build_id: the table's cards plus whatever is under var/downloads/.

        The union is the honest local side: a directory that no card names is still
        bytes we hold (a fetch or a worker left it there), and a card with no
        directory is still something we registered.

        Cached for this request like the ledger (`_state`), because walking the
        download tree reads one `provenance.json` and `os.path.isfile` per artifact;
        a page asks for it once per table *and* once per filter, and the answer
        cannot change between those while one request is being rendered (nothing
        this process does writes them - the writes come from the subprocesses a
        button starts, and the next request sees those).
        """
        held = _request_scratch()
        if "locals" not in held:
            table = self._state()[0]
            found = {build.build_id: self.local_of(build.build_id, build.kbuild)
                     for build in table}
            for name in _dirs(layout.downloads()):
                # Not `found.setdefault(name, self.local_of(name))`: that evaluates
                # its argument whether or not the key is there, so every directory
                # that already had a card was read a second time - `provenance.json`
                # parsed and every artifact stat'ed again, 31 reads of 27 copies on
                # this machine (`06-analysis.md` §A0's instrumented render).  The two
                # sets overlap by design (a pulled build has both a card and a
                # directory), so the old line was always going to re-read the
                # majority of them.
                if name not in found:
                    found[name] = self.local_of(name)
            held["locals"] = found
        return held["locals"]

    def filtered_locals(self, check: "Filter | None" = None) -> list[Local]:
        """Every local copy this filter keeps, newest first, **uncapped**.

        Kept apart from `local_rows` because the merged builds page has to cap the
        union once, after the two halves are merged: a page that capped the local half
        at `limit` rows and *then* merged it with the API's `limit` rows would print
        twice what it promised, and one that capped before sorting would drop the
        newest rows.  The numbers strip reads this too - a number a link reproduces
        cannot be a slice.

        The order is the newest thing anybody knows about the copy: its card's
        `created`, else its newest pull act.  A directory no card names has no
        `created` at all, and sorting those last is how a build that was pulled and
        run fell off the end of the row cap and became invisible on the one page that
        lists local copies.
        """
        check = check or Filter(limit=self.rows, origin="any")
        records = self._state()[1]
        kept = [one for one in self.all_locals().values()
                if check.accepts(one.card, records, one)]
        kept.sort(key=lambda one: (self.when_of(one), one.build_id), reverse=True)
        return kept

    @staticmethod
    def when_of(local: Local) -> str:
        """When a local copy became known: its card's `created`, else the newest act's `at`."""
        if local.card is not None and local.card.created:
            return local.card.created
        return str(local.latest.get("at") or "")

    def local_rows(self, check: "Filter | None" = None) -> list[Local]:
        """The local table's rows: every copy, filtered, newest first, capped."""
        check = check or Filter(limit=self.rows, origin="any")
        return self.filtered_locals(check)[check.offset:check.offset + check.limit]

    def local_row(self, local: Local, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """One local row as data: the card, the bytes and the record, kept apart."""
        card = local.card
        records = self._state()[1]
        return {"build_id": local.build_id,
                "describe": card.describe() if card is not None else local.build_id,
                "tree": card.tree if card is not None else "",
                "branch": card.branch if card is not None else "",
                "arch": card.arch if card is not None else "",
                "defconfig": card.defconfig if card is not None else "",
                "compiler": card.compiler if card is not None else "",
                "created": card.created if card is not None else "",
                "in_table": card is not None, "node_id": local.node_id,
                "state": local.state, "state_text": local.state_text(lang),
                "present": sorted(local.present), "size": local.size(),
                "acts": len(local.acts), "pulled_at": str(local.latest.get("at") or ""),
                "hosts": local.hosts(), "path": local.path,
                "verdicts": {test: (records.last(test, local.build_id).verdict
                                    if records.last(test, local.build_id) else "")
                             for test in DEFAULT_TESTS}}

    def remote_row(self, kbuild: Kbuild, local: Local | None,
                   lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """One remote row as data: what the API says, and what we hold under that id."""
        return {"build_id": kbuild.build_id, "tree": kbuild.tree, "branch": kbuild.branch,
                "arch": kbuild.arch, "defconfig": kbuild.defconfig,
                "compiler": kbuild.compiler, "created": kbuild.created,
                "state": kbuild.state, "result": kbuild.result, "node_id": kbuild.node_id,
                "describe": kbuild.describe(), "artifacts": dict(kbuild.artifacts),
                "here": local.state if local is not None else "",
                "here_text": (local.state_text(lang) if local is not None
                              else t(lang, "state.not_held_here")),
                "here_short": (_short_state(local.state, lang) if local is not None
                               else t(lang, "state.not_here"))}

    def todo(self, check: "Filter | None" = None) -> list[Any]:
        """`re.todo()` for this request, walked once per set of tests.

        **Carry-over C1, measured.**  `08-PLAN.md` handed this step "`job_rows`
        computes `build.missing(test)` inside its double loop, so `/jobs` makes 579
        `os.path.isfile` calls for ~10 distinct artifacts; one dict before the loop is
        enough".  Instrumented on this revision, the shape is different and the fix is
        therefore a different one: `/jobs` made **603 `Build.missing()` calls**, and
        only **156** of them (52 cards x 3 tests, one per pair) came from `job_rows` -
        the other **447** came from `re.todo()`, which asks the same 156 pairs and was
        walked **three times in one render**: once by `job_rows` for the gap set, once
        by `_jobs` for the `whole` count, once by `_numbers_strip`.  `/` walked it
        twice.  A dict inside `job_rows` cannot touch those 447, because `job_rows`
        already computes each pair exactly once.

        So the memo is `re.todo()` itself, keyed by the set of tests - the same
        technique `_state()`, `all_locals()` and `runs()` already use, and safe for the
        same reason: nothing this process does writes the ledger during a render (the
        writers are the subprocesses a button starts), so two answers to one question
        inside one request could only differ by a bug.

        The engine still owns the rule - `re.todo()` is `Records` + `Build.missing()`,
        and this method counts nothing (`00-BRIEF.md` §2).
        """
        check = check or Filter(limit=self.rows, origin="any")
        tests = _tests_of(check)
        held = _request_scratch()
        key = ("todo", tests)
        if key not in held:
            table, records = self._state()
            held[key] = re_mod.todo(table, tests, records)
        return held[key]



