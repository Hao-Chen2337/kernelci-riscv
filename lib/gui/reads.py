# SPDX-License-Identifier: LGPL-2.1-or-later
"""The reads behind the pages: what the API answered, and what is on this disk.

Every one of these is a *request's* read and none is a cache kept on `Gui`.  The local
files are read per request (`_state`) because the buttons on these pages start the very
commands that write them - a page that read them once at startup kept showing six
records after a seventh was written - and the API's own answers are memoised per
request by `lib/api.py`.  `remote_rows`/`remote_query` are the two halves of one
question (what the page asked, and what came back), `all_locals`/`filtered_locals`/
`local_rows` are the disk side of it, and `todo` is the gap between the two.

The three that turn those answers into the rows a screen draws are here too, for the
same reason: `build_rows`/`build_row` merge the API's window with this disk into one row
per build id, `_known_builds` is the pool a comparison page can name (both reads it was
going to make anyway, handed on as `Kbuild` objects so `Drift` need not scan for ids the
page is already holding), and `_config_edges` is the comparisons between *adjacent rows
of one order* - one `Drift.series` per contiguous run of comparable rows, so each config
is read once.  They moved here from the retired page modules: a read belongs with the
reads, and a page that computed its own rows would be a second answer to "what do we
have".

`Reads` is the one place a page asks "what do we have"; the pages themselves only
decide what to print."""

from typing import Any

from .. import api as api_mod
from .. import errors, layout
from .. import re as re_mod
from ..build import Build, Builds
from ..drift import Drift
from ..i18n import DEFAULT_LANG, t
from ..kbuild import KBUILD_JOB, Kbuild, Kbuilds
from ..re import Records
from ..tests import DEFAULT_TESTS
from .forms import _api_query, _axis_pairs, _query_text, _tests_of
from .models import Apis, Filter, Local, Remote
from .schema import (
    API_FILTERS,
    API_TIMEOUT,
    FILTER_ORDER,
    MAX_AXIS_COUNTS,
    MAX_LIMIT,
    NO_WINDOW,
)
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

    def build_of(self, build_id: str) -> "Build | None":
        """One card of the local table by its build id, or `None` - the engine's own `Build`.

        A page draws most of its cells out of a row dict (`data.rows`), and the two
        facts a *row* cannot carry are the engine's own answers about the artifacts:
        `/jobs`' 构件 column draws which of the three states each artifact it needs is
        in (`Build.lacking`), and a row dict built for the design's markup has no room
        for a `Build` object.  Reading the whole table again per row is the other way,
        and it is a walk of 68 cards per row for an answer that is already in memory -
        so the index is built once per request, like every other read here.

        `lacking` could be answered here too (`self.local_of(...)` has the bytes and
        the card), and it is not, on purpose: the rule that decides whether a pair can
        run is the engine's (`Build._why`), and a second one written in this layer is
        how the page and `table.py run` would come to disagree about which pairs run.
        """
        held = _request_scratch()
        if "builds" not in held:
            held["builds"] = {build.build_id: build for build in self._state()[0]}
        return held["builds"].get(build_id)

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



