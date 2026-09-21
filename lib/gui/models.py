# SPDX-License-Identifier: LGPL-2.1-or-later
"""The three values a page is a view of: the API's answer, this disk, and a filter.

`Filter` is the conditions - immutable per request, clamped on the way in, and every
one of them chosen from something this tree knows - and `apis`/`local_of` are how a
page reads with it.  `Remote` is one API answer with the three counts that must not
be confused (what is shown, what the window kept, what the API says the query's size
is), and `Local` is one copy on disk as three separate facts: the card, the bytes
and the pull record, none derived from the others.  `Apis` resolves `?api=`
(`local`, `production`, `launch`, or a literal `http(s)` URL) to the base a page
reads and back to the key its links carry.

No markup and no page lives here: these are what a page reads, and every renderer in
this package is a function of them."""

import html
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .. import errors, layout
from ..build import ARTIFACTS
from ..i18n import DEFAULT_LANG, t
from ..kbuild import KBUILD_JOB, Kbuild
from ..re import Records
from ..tests import TESTS
from .forms import (
    _api_url,
    _artifacts,
    _clamp,
    _first,
    _named,
    _named_many,
    _names,
    _numbers,
    _token,
)
from .schema import (
    API_LAUNCH,
    API_NAMES,
    DEFAULT_DELTA,
    EVIDENCE,
    FILTER_ORDER,
    MAX_DAYS,
    MAX_DELTA,
    MAX_LIMIT,
    NO_WINDOW,
    ORIGINS,
    RANS,
    SORT_KEYS,
    VERDICTS,
)
from .sorting import _sort_refused, _sort_spec
from .values import _host, _human, _short


@dataclass(frozen=True)
class Apis:
    """The API bases one page can name, and the base this process started on.

    One object because three lookups have to agree: a `?api=` value may be a *name*
    (`local`, `production`, `launch`) or a literal `http(s)` URL; turning either into
    "the base this page reads" and back into "the value its links carry" is one
    question, and a link that answered it differently from the page it points at is
    a link that lies.

    `launch` is `Api.url()`'s answer for this process (`--api-url`, `$KCI_API_URL`,
    else `lib/api.py`'s `LOCAL`), and it is what an *empty* `api` key means - which
    is why `key(launch) == ""`.  A page whose URL carries no `api=` therefore
    renders, link for link, byte for byte what it rendered before this key existed,
    and `?api=local` on a machine that started on the local stack is that same page
    rather than a second one.

    Frozen and built per call: it is a value derived from the process's own startup,
    so nothing may write to it and no request may leave anything in it.
    """

    launch: str = ""
    names: tuple[tuple[str, str], ...] = API_NAMES

    def entries(self) -> tuple[tuple[str, str], ...]:
        """Every base a box may offer, in offer order: the two names, then `launch`.

        `launch` is left out when it is one of the other two, so the same address
        never appears twice under two names - `local` on a machine that started on
        the local stack is the launch base, and that is the whole of it.
        """
        if self.launch and self.launch not in [base for _, base in self.names]:
            return (*self.names, (API_LAUNCH, self.launch))
        return self.names

    def name(self, base: str) -> str:
        """This base's name here, or `""` for a base we have no name for."""
        for name, one in self.entries():
            if one == base:
                return name
        return ""

    def base(self, value: str) -> str:
        """A name or a literal URL as a base URL; `""` when this page knows neither.

        An *empty* value is the base this process started on - that is what an absent
        `api` key means, and it is why `api_base(check)` can be asked about a filter
        that never mentioned an API.  A value that is neither empty nor resolvable is
        a different thing and stays `""`: the caller has to be able to tell "nothing
        asked" from "something refused", or the clamp note cannot say which.

        Names first, so `?api=production` and `?api=https://api.kernelci.org` are the
        same request - which is what lets the page *print* the address and *write*
        the short name without the two ever drifting apart.

        `launch` is answered even on a machine where it is not *offered* (a box that
        listed it beside `local` would be offering one address under two names): a
        reader who guessed the third name meant the base this process started on, and
        that is what they get - the default, not a complaint.
        """
        if not value:
            return self.launch
        if value == API_LAUNCH and self.launch:
            return self.launch
        for name, one in self.entries():
            if name == value:
                return one
        return _api_url(value)

    def key(self, base: str) -> str:
        """A base as the value a URL carries: its name, else the URL itself.

        `""` for the launch base (and for no base at all): the key is left out of a
        URL when it says nothing the URL does not already mean.
        """
        if not base or base == self.launch:
            return ""
        return self.name(base) or base

    def of(self, value: str) -> str:
        """A `?api=` value as the canonical key a page carries - one call, one answer.

        Every spelling of one base comes back the same: `production` and
        `https://api.kernelci.org` both become `production`, `?api=local` on the
        local stack becomes `""`, and a value this page refuses becomes `""` too
        (the fallback is `launch`, and `launch` is what an empty key means).
        """
        return self.key(self.base(value))


@dataclass
class Filter:
    """The tables' filter: every column can be one, and every one of them is chosen."""

    tree: str = ""
    branch: str = ""
    arch: str = ""
    defconfig: str = ""
    compiler: str = ""
    # The node's own two value fields, offered with the offer list their *kind*
    # answers for (`API_FILTERS`, and `docs/gui-rework/02-filters.md` §A2).  They are
    # not in `VERDICTS`/`JOB_STATES`: a kbuild node's `state` and its `result` are the
    # API's own vocabulary, and `state=available` - a value that exists on `kind=job`
    # and answers **0** on `kind=kbuild` - is why one global list was the wrong shape.
    state: str = ""
    result: str = ""
    job: str = ""
    days: int = NO_WINDOW             # 0 = no window: the job's whole history
    origin: str = "any"              # any | local | remote | both
    has: tuple[str, ...] = ()        # artifacts the row must have (of ARTIFACTS)
    missing: tuple[str, ...] = ()    # artifacts the row must be missing
    ran: str = "any"                 # any | never | ever | failing
    test: str = ""                   # narrows ran and verdict to one test
    verdict: str = ""                # the most recent verdict is this one
    evidence: str = "any"            # what the pull record says (EVIDENCE)
    text: str = ""
    limit: int = 50
    offset: int = 0
    # The order `/analysis` puts its rows in, and the reason it is a `Filter` field
    # and not page state like `pick` (see `SORTS`): a row's adjacent delta is defined
    # by the order, so every link that keeps the row has to keep this too.  `""` is
    # the page's own default, decided by the renderer and not by the filter.
    sort: str = ""
    # What the query string asked for, when it asked at all (`None` = it carried
    # no such key).  The clamped `days`/`limit` above are what every reader uses;
    # these two exist so a clamp can be *printed* instead of quietly obeyed.
    asked_days: int | None = None
    asked_limit: int | None = None
    # Which API this page reads, as the value a URL carries: `""` for the base this
    # process started on, else a name (`local`, `production`, `launch`) or a literal
    # `http(s)` URL.  A condition like `tree`, and the first one in `FILTER_ORDER`:
    # it decides which API the other thirteen are asked of.
    api: str = ""
    # The base `api` resolves to here, **default included**: the address this page
    # really reads, which is what the axes strip's `api` axis prints.  `api` is the
    # *key* a URL carries and is empty on the startup base by design (`Apis.key`), so
    # a strip built from the key could not say which API is in force - which is how
    # `?api=production` came to render byte-identically to no `api` key at all when
    # the process started on production (`02-filters.md` §A5).  It never enters a URL:
    # `to_query()` does not read it.
    api_base: str = ""
    # What `?api=` said on the one occasion this page threw it away - a name nobody
    # here has, or a string that is not an address (`_api_url`).  Kept only so the
    # clamp note can say so out loud: a value silently swapped for the default is how
    # a reader ends up looking at another API without being told.
    api_raw: str = ""
    # What `?api=` said *whenever it said anything*, resolvable or not.  `api` is
    # empty for the base this process started on (that is `Apis.key`'s design, and it
    # is right: it keeps today's URLs unchanged), so `?api=production` on a production
    # process and a URL with no `api` key at all are one filter - and the axes strip
    # then printed one page for two different requests.  The reader *did* state which
    # API they meant; this remembers that they did, so the strip can mark the axis as
    # stated and offer to drop it.  It never enters a URL (`to_query()` does not read
    # it) and it is not a condition: the base in force is `api_base`.
    api_given: str = ""
    # The same fact for `?test=`: `one_of` below drops a value that is not one of
    # `TESTS`, and until this field existed it did it in *silence* - `?test=kbuild`
    # rendered as if nothing had been asked for at all, with no banner and the box
    # back on "(any)" (`04-actions.md` §5a, reproduced).  A value the page cannot
    # honour is a fact about the reader's URL, so it is reported, never swallowed.
    test_raw: str = ""
    # The same fact again for `?sort=`: an order is a *list* of keys now (`_sort_keys`),
    # and a component nobody knows is dropped rather than obeyed - so the raw value is
    # kept, to be printed by `clamps`.  A URL that named a round-1 spelling
    # (`same-branch`) is not a refusal: that is an alias and means what it always meant.
    sort_raw: str = ""
    # How many rows of the order may spend a config read on their neighbours.  It was
    # read by the renderer alone (`_clamp(_numbers(query, "delta", DEFAULT_DELTA), 0,
    # MAX_DELTA)`), so it was in no `Filter` and therefore in no link - and the walls
    # between the list and one comparison (`_compare_url`) are built from a `Filter`.
    # A comparison read out of the context it was made in is a different comparison.
    delta: int = 0
    # Page state that is not a filter: the two builds to compare (`/analysis`), and
    # the rows a link asked to pre-tick on the pull page.
    pick: tuple[str, ...] = ()
    tick: tuple[str, ...] = ()

    @classmethod
    def from_query(cls, query: Mapping[str, list[str]], lang: str = DEFAULT_LANG,
                   apis: "Apis | None" = None) -> "Filter":
        """A query string as a filter; unknown keys are ignored, numbers clamped.

        `lang` is here for one reason: a value nothing offered is refused with a
        sentence, and a page that refuses in English while showing Chinese is a page
        that changed language halfway through.  `?lang=` itself is not a filter.

        `apis` is here for the same kind of reason: `?api=` may name a base
        (`production`) or spell it out (`https://api.kernelci.org`), and only this
        deployment knows which names mean which addresses.  Both spellings land on
        the same `api` key, and a value nobody here recognises - or one that is not
        an address at all - is *ignored*: the filter comes back on the startup base,
        with `api_raw` remembering what was dropped so the page can say so instead of
        quietly answering a question nobody asked.
        """
        apis = apis if apis is not None else Apis()
        raw_api = _first(query, "api")
        api_base = apis.base(raw_api)

        def one_of(key: str, options: Iterable[str], default: str) -> str:
            value = _first(query, key)
            return value if value in options else default

        def asked(key: str) -> int | None:
            """The number the query carried, or None when it carried none at all."""
            return _numbers(query, key, 0) if _first(query, key) else None

        # The clamp is what keeps `?days=1000000000000` from reaching
        # `time.gmtime` (an OSError there was an HTTP 500) and `?limit=-1` from
        # reaching `[:limit]` (which cut the *newest* rows off the list).
        raw_days, raw_limit = asked("days"), asked("limit")
        days = _clamp(raw_days if raw_days is not None else NO_WINDOW, NO_WINDOW, MAX_DAYS)
        limit = _clamp(raw_limit if raw_limit is not None else 50, 1, MAX_LIMIT)
        return cls(tree=_named_many(query, "tree", lang),
                   # `branch` is **not** one of the multi-valued axes and keeps
                   # `_named`'s single value: a branch belongs to the tree it was read
                   # from (`_branches_from_config`), so "any of these branches" is not
                   # a question this page can offer candidates for (`schema.MULTI_FIELDS`).
                   branch=_named(query, "branch", lang),
                   arch=_named_many(query, "arch"),
                   defconfig=_named_many(query, "defconfig"),
                   compiler=_named_many(query, "compiler"),
                   state=_named(query, "state"),
                   result=_named(query, "result"),
                   job=_first(query, "job"), days=days,
                   # **The cards are what `/` shows when nothing is asked.**  The
                   # operator's ask this round was 「专门搞一个存卡片的地方，就是默认显示
                   # 全部卡片」, and the page that holds every card is this one with
                   # `origin=card` - so that is the default, and `?origin=any` is how a
                   # reader asks for the union (the API's window and this disk together).
                   # The three union readers that are *not* pages pin it themselves:
                   # `summary`, `remote_query` and every internal `Filter(…, origin="any")`
                   # fallback, so the machine interface keeps its contract and the gap the
                   # strip counts is still counted over everything.
                   origin=one_of("origin", ORIGINS, "card"),
                   has=_artifacts(_first(query, "has")),
                   missing=_artifacts(_first(query, "missing")),
                   ran=one_of("ran", RANS, "any"),
                   test=one_of("test", TESTS, ""),
                   verdict=one_of("verdict", VERDICTS, ""),
                   evidence=one_of("evidence", EVIDENCE, "any"),
                   text=_first(query, "text"), limit=limit,
                   offset=max(0, _numbers(query, "offset", 0)),
                   sort=_sort_spec(_first(query, "sort")),
                   sort_raw=_sort_refused(_first(query, "sort")),
                   delta=_clamp(_numbers(query, "delta", DEFAULT_DELTA), 0, MAX_DELTA),
                   asked_days=raw_days, asked_limit=raw_limit,
                   api=apis.key(api_base), api_base=api_base, api_given=raw_api,
                   api_raw=raw_api if (raw_api and not api_base) else "",
                   test_raw=(_first(query, "test")
                             if _first(query, "test") not in TESTS else ""),
                   pick=tuple(_token(one) for one in (query.get("pick") or []) if _token(one)),
                   # `tick` is a comma list and not a repeated key for the same reason
                   # `missing`/`has` are (`_url` collapses a repeated key through a dict):
                   # "re-tick the rows whose pull failed" is one link, and one link that
                   # carries forty ids has to be one value.
                   tick=tuple(one for value in (query.get("tick") or [])
                              for one in (_token(part) for part in str(value).split(","))
                              if one))

    def clamps(self, lang: str = DEFAULT_LANG) -> list[str]:
        """The values this query asked for and did not get, in words.

        Empty when nothing was clamped.  A page that silently shows 1000 rows
        where 5000 were asked for has changed the operator's question without
        saying so, which is the one thing a filter may never do.  An `?api=` this
        deployment cannot resolve is the same kind of fact: the page reads the base
        it started on, and the reader is told which value was dropped.

        The dropped value is escaped here and not by the caller because it is the one
        entry in this list that is not a number: it is whatever a hand-typed URL said.
        """
        notes = []
        if self.asked_limit is not None and self.asked_limit != self.limit:
            notes.append(t(lang, "filter.capped_rows", limit=self.limit,
                           asked=self.asked_limit))
        if self.asked_days is not None and self.asked_days != self.days:
            notes.append(t(lang, "filter.capped_days", days=self.days,
                           asked=self.asked_days))
        if self.api_raw:
            notes.append(t(lang, "filter.api_refused", value=html.escape(self.api_raw)))
        if self.test_raw:
            notes.append(t(lang, "filter.test_refused", value=html.escape(self.test_raw),
                           options=", ".join(sorted(TESTS))))
            # The one value an operator is most likely to type here is the name of
            # the *build* job every row on these pages comes from, and `kbuild` is not
            # a test at all: `TESTS` is `boot`/`kselftest-riscv`/`kselftest-kvm`, and
            # `KBUILD_JOB` is `kbuild-gcc-14-riscv`.  Saying so is the difference
            # between a reader learning the vocabulary and re-typing the same name
            # (`04-actions.md` §5, "我选的 kbuild 它不给我运行").
            if self.test_raw in ("kbuild", KBUILD_JOB):
                notes.append(t(lang, "filter.test_is_job", value=html.escape(self.test_raw)))
        if self.sort_raw:
            # `?sort=tree-branch,banana` used to be reduced to whatever `one_of` made of
            # it - i.e. to the default - with nothing said, so a page that had been asked
            # for one order rendered another.  The keys that survive are still applied;
            # this names what was dropped.
            notes.append(t(lang, "filter.sort_refused", value=html.escape(self.sort_raw),
                           options=", ".join(SORT_KEYS)))
        return notes

    def to_query(self) -> list[tuple[str, str]]:
        """This filter as a copyable query, defaults left out.

        One place decides the key order and which value is "the default": the
        pages, the links and the commands all read the same answer.  A default is
        left out because `?days=0&limit=50&origin=any` says four times what the
        reader did not ask for, and because a link that spells a default out
        cannot be told apart from a link that asked for it by hand.

        `pick`/`tick` are page state rather than conditions and stay out: the
        ticks of one page must not follow the reader to the next.

        `api` follows the same rule with the one default it has - the base this
        process started on.  A page reading that base carries nothing, which is why
        today's URLs are unchanged; a page reading another API says which one, and
        says it first.
        """
        wanted = (("api", self.api, ""),
                  ("tree", self.tree, ""), ("branch", self.branch, ""),
                  ("arch", self.arch, ""), ("defconfig", self.defconfig, ""),
                  ("compiler", self.compiler, ""),
                  ("state", self.state, ""), ("result", self.result, ""),
                  ("days", str(self.days), str(NO_WINDOW)),
                  ("limit", str(self.limit), "50"),
                  ("test", self.test, ""), ("ran", self.ran, "any"),
                  ("verdict", self.verdict, ""), ("evidence", self.evidence, "any"),
                  ("origin", self.origin, "card"),
                  ("missing", ",".join(self.missing), ""),
                  ("has", ",".join(self.has), ""), ("text", self.text, ""),
                  # `job` is the worker page's own filter - the name of a job node - and
                  # it is a `Filter` field that `FILTER_ORDER` does not list, so it was
                  # dropped here and a `?job=<name>` drill-down could not survive a single
                  # link: the box kept the value and every link out of the page lost it.
                  # (`ROUTE_KEYS["/worker"]` names the key, so `_url` was willing to carry
                  # it - there was simply nothing to carry.)  It rides in the tail beside
                  # `delta`, for the same reason: a key the order does not know about is
                  # still a key the URL has to keep.
                  ("job", self.job, ""),
                  ("sort", self.sort, ""),
                  # The comparison cap travels with the order for the same reason the
                  # order does: a row's `±` is defined by *both*, so a link into one
                  # comparison has to carry both or it opens a differently-built page.
                  # It is a `Filter` field and not a `FILTER_ORDER` axis, so it is
                  # returned here in `FILTER_ORDER`'s tail position (`FILTER_ORDER` has
                  # no `delta`; the extra keys come after it in dict order).
                  ("delta", str(self.delta), str(DEFAULT_DELTA)))
        found = {key: value for key, value, default in wanted if value != default}
        # A key `FILTER_ORDER` does not list still belongs in the URL - `delta` (the
        # comparison cap) and `job` (the worker page's job node) both do - so they are
        # emitted after the ordered ones, in the order they are declared above.  This is
        # the one place that decides how a page's question is spelled.
        tail = [key for key, _value, _default in wanted if key not in FILTER_ORDER]
        return ([(key, found[key]) for key in FILTER_ORDER if key in found]
                + [(key, found[key]) for key in tail if key in found])

    def accepts(self, kbuild: Kbuild | None, records: Records, local: "Local | None",
                test: str = "") -> bool:
        """Is this row in?  A value nobody knows is permissive, never a silent drop.

        **A value axis is a membership test**, and not an equality one: `tree` and the
        other three multi-valued axes (`schema.MULTI_FIELDS`) may name several values,
        and a row is in when it carries *any* of them.  The one-value case is the same
        test - `_names("riscv")` is `("riscv",)` - so nothing about a single-value URL
        changed.  This predicate is the **authoritative** one for those axes: it runs
        after the fetch, on the rows the page really has, and it is what makes a
        multi-valued filter correct even where the query's own form could not be
        (`_axis_pairs` is the wire half, and it is verified against the API).

        `kbuild` is a card this machine holds and not necessarily a row the API
        answered, so those two halves are not the same set and this one is the one
        the page prints.

        `test` narrows the two record checks to one test, which is what a row of
        the jobs table is about; without it they are about the build as a whole.
        """
        wanted_fields = (("tree", self.tree), ("branch", self.branch),
                         ("arch", self.arch), ("defconfig", self.defconfig),
                         ("compiler", self.compiler), ("state", self.state),
                         ("result", self.result))
        if kbuild is None:
            # A row with no card has no tree to compare: a value filter EXCLUDES it.
            # Showing it is how "I filtered by tree=x" looks like nothing happened.
            if any(wanted for _, wanted in wanted_fields) or self.text:
                return False
        else:
            for field_name, wanted in wanted_fields:
                if wanted and getattr(kbuild, field_name) not in _names(wanted):
                    return False
            if self.text:
                haystack = " ".join(str(getattr(kbuild, name, "") or "") for name in
                                    ("build_id", "tree", "branch", "describe", "node_id")).lower()
                commit = str((kbuild.revision or {}).get("commit") or "")
                if self.text.lower() not in f"{haystack} {commit.lower()}":
                    return False
        if self.origin != "any":
            here, remote = bool(local and (local.present or local.card)), kbuild is not None
            if self.origin == "local" and not here:
                return False
            if self.origin == "remote" and not remote:
                return False
            if self.origin == "both" and not (here and remote):
                return False
            # `carded`: this machine has a card for it, which is neither "local" (a
            # card *or* bytes) nor "remote".  It exists because it is the one set the
            # numbers strip's `cards` chip counts, and a chip whose link cannot
            # reproduce its number is a number the reader cannot check - the 52 cards
            # and the 53 directories differ by exactly the copies no card names
            # (`_numbers_strip`, and `accept.py`'s S6).
            if self.origin == "card" and not (local is not None and local.card is not None):
                return False
        if self.has or self.missing:
            held = set(local.present) if local is not None else {
                name for name in ARTIFACTS if kbuild is not None and kbuild.artifact(name)}
            if any(name not in held for name in self.has) or any(name in held for name in self.missing):
                return False
        if self.evidence == "bytes":
            # Not a `Local.state`: "the artifacts are on disk" is a fact about the
            # download tree, and the two states around it need the record or the
            # absence of it.  The numbers strip's `with bytes` chip is this value.
            if local is None or not local.present:
                return False
        elif self.evidence != "any" and local is not None and local.state != self.evidence:
            return False
        if kbuild is None:
            return True
        if self.ran != "any" or self.verdict:
            found = records.for_test(test or self.test) if (test or self.test) else records
            verdicts = [one.verdict for one in found.for_build(kbuild.build_id)]
            if self.ran == "never" and verdicts:
                return False
            if self.ran == "ever" and not verdicts:
                return False
            if self.ran == "failing" and errors.VERDICT_FAIL not in verdicts:
                return False
            if self.verdict and (not verdicts or verdicts[-1] != self.verdict):
                return False
        return True


# ---------------------------------------------------------------------------
# One local copy, and what the record does (not) say about it
# ---------------------------------------------------------------------------

@dataclass
class Local:
    """One local copy as three separate facts: the card, the bytes, and the pull record.

    None of the three is derived from the others, and none of them is derived from
    a build id: that is the whole point.  A directory named like a remote build is
    a directory named like a remote build - `state()` says what can be claimed.
    """

    build_id: str
    card: Kbuild | None = None
    present: dict[str, str] = field(default_factory=dict)
    pull: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> str:
        """`var/downloads/<build-id>/` - where this copy's bytes (and its record) live."""
        return layout.downloads(self.build_id)

    @property
    def acts(self) -> list[dict]:
        """The recorded pull acts, newest first - `Build.provenance()`'s shape."""
        found = self.pull.get("acts")
        if not isinstance(found, list):
            return []
        return [one for one in found if isinstance(one, dict)]

    @property
    def latest(self) -> dict:
        """The newest recorded act, or `{}` - the one that describes the copy as it is."""
        return self.acts[0] if self.acts else {}

    @property
    def entries(self) -> list[dict]:
        """The artifact entries of the newest act: what that pull actually did."""
        found = self.latest.get("entries")
        if not isinstance(found, list):
            return []
        return [one for one in found if isinstance(one, dict)]

    @property
    def state(self) -> str:
        """What the facts allow: pulled | unrecorded | registered | made-here | empty.

        A `file://` artifact is this deployment's own `var/serve/`: an act that
        fetched one proves the bytes and says nothing about a remote build, so it is
        the one act that means `made-here` rather than `pulled`.  Without this,
        `made-here` was unreachable for the single copy it was written for
        (`deadbeef1234`, published from `var/serve/Image`): it read `pulled … from
        file:///home/hao/kernelci-riscv/var/serve/Image`, and `?evidence=made-here`
        selected nothing on any machine, ever (`03-structure.md` §A3.3).
        """
        if self.entries:
            local_only = all(str(one.get("url") or "").startswith("file:")
                             for one in self.entries)
            return "made-here" if local_only else "pulled"
        if self.present:
            return "unrecorded"
        if self.card is None:
            return "empty"
        return "registered" if self.card.node_id else "made-here"

    @property
    def node_id(self) -> str:
        """The remote node this copy is tied to: the card's, or the one the pull recorded."""
        return (self.card.node_id if self.card is not None else "") or str(self.pull.get("node_id") or "")

    def size(self) -> int:
        """How many bytes of artifacts are on disk here."""
        total = 0
        for path in self.present.values():
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
        return total

    def hosts(self) -> list[str]:
        """The hosts the recorded pull fetched from, in the order the entries name them."""
        found = []
        for entry in self.entries:
            host = _host(str(entry.get("url") or ""))
            if host and host not in found:
                found.append(host)
        return found

    def state_text(self, lang: str = DEFAULT_LANG) -> str:
        """One sentence, saying what the record does say and what it does not."""
        if self.state == "pulled":
            moved = sum(1 for entry in self.entries if entry.get("transferred"))
            said = t(lang, "evidence.pulled_text", n=len(self.entries),
                     hosts=", ".join(self.hosts()) or "?",
                     size=_human(self.pulled_bytes()), at=self.latest.get("at") or "?",
                     moved=moved, whole=len(self.entries) - moved)
            failed = str(self.latest.get("error") or "")
            return t(lang, "evidence.failed", said=said, error=failed) if failed else said
        if self.state == "unrecorded":
            where = (t(lang, "evidence.card_in_table") if self.card is not None
                     else t(lang, "state.no_card_in_table"))
            return t(lang, "evidence.unrecorded_text", where=where)
        if self.state == "registered":
            return t(lang, "evidence.registered_text", node=_short(self.card.node_id))
        if self.state == "made-here":
            return t(lang, "evidence.made_here_text")
        return t(lang, "evidence.empty_text")

    def pulled_bytes(self) -> int:
        """The bytes the newest recorded pull proved."""
        return sum(int(entry.get("bytes") or 0) for entry in self.entries)


# ---------------------------------------------------------------------------
# One API answer, and the three counts that must not be confused
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Remote:
    """What one API query answered, and how much of it this page is showing.

    Three different numbers live in one answer and they are not interchangeable:
    what the page prints (`shown`, capped by the row limit), what the window plus
    this filter kept (`kept`), and what the API itself says the query's size is
    (`total` - quoted, never counted here).  A page that printed one number for
    all three is how "2 rows" came to look like "the API has 2 builds".
    """

    query: str = ""
    shown: tuple[Kbuild, ...] = ()
    kept: int = 0                    # rows the fetched window kept, before the display cap
    total: int | None = None         # the API's own count for the query, when it says
    limit: int = 0                   # the row cap that was asked for
    note: str = ""                   # why there are no rows, when the API did not answer

    def __iter__(self):
        return iter(self.shown)

    def __len__(self) -> int:
        return len(self.shown)

    def coverage(self, lang: str = DEFAULT_LANG) -> str:
        """How complete this answer is, in words - a cap that hides rows says so.

        Two different things can keep a row out of the table and they are named
        separately: the API's own size against the cap this page asked for, and
        this page's filter over the rows the cap did return.
        """
        if self.total is None:
            return t(lang, "remote.coverage_unknown")
        said = t(lang, "remote.coverage_base", total=self.total)
        if self.total <= self.limit:
            said += t(lang, "remote.coverage_all")
        else:
            said += t(lang, "remote.coverage_capped", n=self.total - self.limit,
                       limit=self.limit)
        dropped = min(self.total, self.limit) - self.kept
        if dropped > 0:
            said += t(lang, "remote.coverage_filtered", n=dropped)
        return said
