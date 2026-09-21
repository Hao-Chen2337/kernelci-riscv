# SPDX-License-Identifier: LGPL-2.1-or-later
"""The filter bar: the controls that shape a query, and the methods that build them.

`_axes` is the whole bar - every kbuild axis, once, for every page that selects
builds - and `_name_field`, `_num` and `_datalist` are the two shapes it draws: a
free name with its candidates, and a number free to type, bounded in the box and
clamped on the server.  `_quick` is the rail beside a field, where a link per value
is still the right shape.

`Fields` is the same bar as the page's own methods: which API it reads
(`_api_field`), the window and the row cap, and the value axes a page's *own answer*
fills (`_combo`, from what the rows carry, because the API cannot enumerate a
field's values).  A page that selects builds draws this bar and nothing else: `/`,
`/jobs`, `/runs`, `/worker` and `/analysis` differ in what they do with the list,
not in how it is chosen."""

import html
import json
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from ..build import ARTIFACTS
from ..i18n import DEFAULT_LANG, t
from .forms import _names, _token
from .models import Filter
from .schema import (
    ARCH_KNOWN,
    BRANCH_SEEDS,
    DAY_CHOICES,
    DAYS,
    EVIDENCE,
    KBUILD_STATES,
    LIMITS,
    MAX_DAYS,
    MAX_LIMIT,
    NO_WINDOW,
    ORIGINS,
    RESULTS,
    TREES_KNOWN,
    _branches_from_config,
    _labels,
)
from .urls import _url
from .widgets import _select

if TYPE_CHECKING:
    from .models import Remote

class FieldsMixin:
    # --- the controls every page is asked with -----------------------------

    def _api_field(self, check: Filter, lang: str = DEFAULT_LANG) -> str:
        """Which API this page reads: one open box, and its candidates.

        **One control, not two.**  This field used to draw the same three choices twice
        on one line - a `<datalist>` of both spellings and a `_quick` pill per base -
        and the operator said what that is worth: 「api: local production 这个也没必要
        就是又很多东西重复了就是有一个框就行了」.  The pills are gone; the box and its
        list stay, so every value the pills could set is still one keystroke away.

        The same shape the rest of the bar uses for a free value (`_datalist` +
        `_name_field`, like `tree`).  The value stays open because
        the set of KernelCI APIs is not something this deployment gets to decide -
        `http://127.0.0.1:9/` is a base whether or not anybody listed it.

        The box holds the *key* (`production`), not the address, because the key is
        what the URL and every link carry; the address it stands for is printed in the
        page's own query line (`remote_query`), so the short form hides nothing.  The
        candidates offer both spellings, so typing either is one keystroke away.

        An empty box means "the base this process started on", and the placeholder
        says which one that is: "empty" is then a readable answer rather than a
        missing one, and the page's URL stays the one it had before this key existed.
        """
        apis = self.apis
        entries = apis.entries()
        launch = self.launch_base()
        labels = {name: base for name, base in entries}
        labels.update({base: name for name, base in entries})
        # What the box shows as "current": the key itself, or - when the key is empty
        # - the name of the base an empty key stands for, so the value in force is
        # what the box says rather than nothing.
        here = check.api or apis.name(launch) or launch
        # One option per API, whose *value* is the address and whose *label* is the
        # short name, so the list is two rows for two APIs instead of four rows for
        # two APIs.  Neither spelling is lost: `Apis.base()` resolves names first and
        # `Apis.of()` canonicalises both to the same key, so typing or picking either
        # still lands on `?api=production`.
        return (_datalist("apis", tuple(base for _, base in entries), labels)
                + _name_field("api", check.api, t(lang, "filter.api"), "apis", lang,
                              placeholder=here))

    def _build_axes(self, route: str, check: Filter, answer: "Remote | None" = None,
                    rows: Iterable[Any] = (), lang: str = DEFAULT_LANG) -> list[str]:
        """The kbuild filter axes, once, for every page that selects builds.

        `/` built these fourteen controls inline and `/analysis` drew five of the same
        kind, so the page the operator calls 分析 had a *lesser copy* of the filter bar he
        already knew: no `arch`, no `compiler`, no `origin`, no `missing`, and no way to
        say "only the ones with bytes on disk".  He asked for one template
        (「应该有类似统一的分析就是模板」), and the axes are the template - the pages differ
        in what they *do* with the list (compare neighbours, chart a test), not in how the
        list is chosen.

        `answer` is optional: a page that has no API answer to count passes none, and the
        two `_combo` controls fall back to the values they have seen.
        """
        known = () if answer is None else answer
        return [self._api_field(check, lang=lang),
                self._tree_field(check, known, lang=lang),
                self._branch_field(check, known, lang=lang),
                # The rest of the API's vocabulary for a kbuild node, every key verified
                # against a `/count` before it was offered (`API_FILTERS`).  `tree` and
                # `branch` narrow (80 and 44 of 1782); `arch`, `defconfig` and `compiler`
                # are real and nearly never selective (1771 each), which is what the number
                # beside each axis in the strip is for.
                self._combo("arch", check, known, t(lang, "word.arch"), lang),
                self._combo("defconfig", check, known, t(lang, "word.defconfig"), lang),
                self._combo("compiler", check, known, t(lang, "word.compiler"), lang),
                # `state`'s offer list comes from the kind, and it is short on purpose.
                _select("state", ("", *KBUILD_STATES[1:]), check.state,
                        t(lang, "word.state"), lang=lang),
                _select("result", ("", *RESULTS[1:]), check.result,
                        t(lang, "word.result"), lang=lang),
                _select("origin", ORIGINS, check.origin, t(lang, "filter.origin"),
                        placeholder=False, labels=_labels("origin", lang), lang=lang),
                _select("evidence", EVIDENCE, check.evidence, t(lang, "filter.evidence"),
                        placeholder=False, labels=_labels("evidence", lang), lang=lang),
                _select("missing", ("", *ARTIFACTS), ",".join(check.missing),
                        t(lang, "filter.missing"), lang=lang),
                self._days_field(route, check, lang=lang),
                self._limit_field(route, check, lang=lang)]

    def _tree_field(self, check: Filter, rows: Iterable[Any] = (),
                    lang: str = DEFAULT_LANG) -> str:
        """The tree axis and its candidates: a name the API accepts, several at once.

        A select box could only offer the trees this deployment had already seen,
        which is how `/remote` came to offer two names out of the fifty the
        pipeline config knows.

        Several trees are one question (`schema.MULTI_FIELDS`): the row is in when it
        carries *any* of them, and the tick boxes are how the whole set is stated in
        one form.  The candidates are `_vocabulary`'s, and the free box beside the
        boxes is where a tree nobody listed is still typeable.
        """
        return _check_group("tree", _vocabulary("tree", check, rows, self._state()[0]),
                            check.tree, "trees", t(lang, "word.tree"), lang=lang)

    def _branch_field(self, check: Filter, rows: Iterable[Any] = (),
                      lang: str = DEFAULT_LANG) -> str:
        """The branch field: this tree's own branches, plus a free hand.

        The candidates are **per tree**, which is the difference between a suggestion
        and a lie.  `BRANCH_SEEDS` offered six names to every tree at once, so
        `tree=riscv` - whose only two branches are `fixes` and `for-next` - was offered
        `main`, `master` and `linux-6.12.y`, names that live on `net-next`,
        `stable-rc` and `mainline`; the live overview's branch box held 12 names and
        every one of them belonged to another tree (`02-filters.md` §A4).  The API
        cannot enumerate branches, but the vendored pipeline config binds them to a
        tree (`kernelci-pipeline/config/trees/<tree>.yaml`, 126 bindings over 76
        names), and for `riscv` it yields exactly the two the API itself answered with.

        **The branch is a single value and stays one.**  It is not in
        `schema.MULTI_FIELDS`, and the reason is this docstring: a branch is bound to
        the tree it was read from, so a set of branches chosen across several trees
        has no per-tree candidate list behind it - the box would be offering one
        tree's names while another tree's rows were also in force.  With several trees
        on (`_branch_stops`) the candidates are the union of *those trees' own*, which
        is the most a per-tree source can honestly say.

        A rail is offered here and not for `tree`: two stops is precisely what a
        slider is for, and the operator's "滑条式可以给你选，这样你但你可以自己填"
        wants both halves - the two names to slide through and a box that still takes
        one nobody listed.
        """
        stops = _branch_stops(check)
        return (_datalist("branches", _vocabulary("branch", check, rows, self._state()[0]))
                + _name_field("branch", check.branch, t(lang, "word.branch"), "branches",
                              lang, stops=stops,
                              note=(t(lang, "filter.branch_of_tree", tree=check.tree)
                                    if check.tree else "")))

    def _combo(self, name: str, check: Filter, rows: Iterable[Any] = (),
               label: str = "", lang: str = DEFAULT_LANG) -> str:
        """One value axis as tick boxes: `arch`, `defconfig`, `compiler`.

        The shape the rest of the bar already uses (`_check_group`), built from the
        candidates `_vocabulary` merges: a field with a config of its own gets a seed
        list from it (`arch`, `ARCH_KNOWN` - the architectures the vendored
        `jobs*.yaml` declare, which is where the `data.arch` a node carries comes
        from), and a field without one is offered from what has answered here, because
        the API has no endpoint that lists the values a field takes.

        **`defconfig` and `compiler` are deliberately left to the seen values.**  Both
        have a config source of their own (`jobs*.yaml`'s `params.defconfig` and
        `params.compiler`), and reading it would be the "wrong list" `_branch_field`
        describes rather than a longer one: a defconfig belongs to an arch
        (`x86_64_defconfig` beside `arch=riscv`), and `/`'s own answer already carries
        every value this deployment has built - `defconfig=defconfig`,
        `compiler=gcc-14`.

        Small sets get a rail (`arch` is seven names on production); long ones do not
        - a defconfig is `x86_64_defconfig+allnoconfig`, and twenty of those on a
        slider is unreadable, which is why `_rail` takes the set and refuses past
        `RAIL_MAX` on its own.

        **No count beside the label.**  The axes strip already prints, for each axis in
        force, the number of *rows* that axis matched (`_axis_counts`), and a second
        number next to the same name - the size of the suggestion set - would be read
        as the same fact and would often contradict it (`arch` has one suggestion here
        and matched 1771 rows).  The strip's number is the one that means something.
        `branch` is the exception and says so in its own title: its set is per tree and
        two stops is what the rail exists for.
        """
        stops = _vocabulary(name, check, rows, self._state()[0])
        return _check_group(name, stops, str(getattr(check, name, "") or ""),
                            name + "s", label, lang=lang)

    def _one_tree(self, check: Filter, lang: str = DEFAULT_LANG) -> str:
        """Why a one-shot bar cannot be offered here - `""` when this filter names one tree.

        `--tree` is single-valued in every entry point these bars start
        (`run_latest.py`, `runday.py` and `table.py index` each declare one `--tree`,
        none with `action="append"`), and `command()` reads it with `_named`, which
        refuses a comma-joined value as the non-name it is.  So a filter that names two
        trees cannot be handed to a one-shot button honestly, and the button must say
        so rather than be clickable and refuse: that is `_action_bar(blocked=…)`'s
        rule, and the reader's own gesture (unticking a box) is the way out.

        This is the one string in the bar and it is a `title=`, not a paragraph: the
        fact is about this button, and `05-i18n-prose.md` §B.1 puts a fact like that
        where the button is.  The list is spelled out because it is short by
        construction - the reader chose it two controls above.
        """
        named = _names(check.tree)
        if len(named) <= 1:
            return ""
        return t(lang, "filter.one_tree", trees=", ".join(named))

    def _days_field(self, route: str, check: Filter,
                    keep: Iterable[tuple[str, str]] = (), lang: str = DEFAULT_LANG) -> str:
        """The window: a free number of days, its ten presets, and `all` for no window.

        Ten buttons was the wrong shape for ten numbers - the operator asked for
        "有一些可以滑下来的选项，而不是多个直接列出来" - so the set is a hint the rail
        steps through, and the box still takes any number of days he types.
        """
        return (_datalist("days", [str(one) for one in DAYS])
                + _num("days", str(check.days), t(lang, "filter.window"), NO_WINDOW,
                       MAX_DAYS, "days", stops=[str(one) for one in DAY_CHOICES]))

    def _limit_field(self, route: str, check: Filter,
                     keep: Iterable[tuple[str, str]] = (), lang: str = DEFAULT_LANG) -> str:
        """The row cap: how many this page prints - and the one control that costs bytes.

        `01-perf.md` §D1c measured ~3.5 KB per row over a 20-35 KB/s link, so the six
        stops are six costs and `_coverage` prints the one in force beside the box.
        The last of the preset links (`_quick`, six values, each also a datalist
        option beneath it) became these stops.
        """
        return (_datalist("limits", [str(one) for one in LIMITS])
                + _num("limit", str(check.limit), t(lang, "filter.rows"), 1, MAX_LIMIT,
                       "limits", stops=[str(one) for one in LIMITS]))


def _field_of(one: Any, name: str) -> str:
    """One value of a card, a row dict or a filter - the three shapes a page mixes."""
    if isinstance(one, Mapping):
        return str(one.get(name) or "")
    return str(getattr(one, name, "") or "")


def _seen_names(kind: str, rows: Iterable[Any], table: Iterable[Any] = ()) -> set[str]:
    """The names a page has actually seen: its own rows, and the local table's cards.

    "Seen" is the honest word for it, and it is what the page says: these are not
    the trees or branches that exist, they are the ones this deployment has met.
    """
    return {one for one in (_field_of(any_one, kind)
                            for any_one in list(rows) + list(table)) if one}


def _vocabulary(kind: str, check: "Filter", rows: Iterable[Any],
                table: Iterable[Any] = ()) -> list[str]:
    """The candidates a name field offers: the fixed list, plus what we have seen.

    Order matters: the fixed list is the floor (the page has to work on a machine
    that has never queried this API), the values the rows carry are the ceiling,
    and the one in force comes last so a list still offers it if it is in neither.
    Everything passes `_token()`: only a name that could reach a command line is
    worth suggesting.

    **Four axes, three different sources, and each one is a file or a fact rather
    than a preference:**

    * `tree` - the names `trees.yaml` lists (`TREES_KNOWN`);
    * `arch` - the architectures `jobs*.yaml` declares as `params.arch`
      (`ARCH_KNOWN`).  This is the axis the operator noticed was stuck on
      `riscv`: it had no seed list at all and derived its candidates from the
      rows, and every row this deployment reads comes from one job name
      (`KBUILD_JOB`), so it offered exactly one value - the "架构目前只填一个
      riscv 的怪状".  The value a node's `data.arch` carries is a copy of that
      job's `params.arch`, so the config is the honest source and not a list
      invented to fill the box;
    * `branch` - *this tree's* own branches, from `trees/<tree>.yaml`.  The six
      seeds are the fallback for a checkout without `config/trees/`, not the set:
      offering `net-next`'s branch names beside `tree=riscv` is not an incomplete
      list, it is a wrong one (`02-filters.md` §A4);
    * `defconfig` and `compiler` - **nothing static, on purpose.**  Both have a
      config of their own (`params.defconfig`, `params.compiler`), and both are
      bound to another axis the way a branch is bound to a tree: a defconfig
      belongs to an arch, so `_combo` offers what this deployment has actually
      built and lets the free box take anything else.
    """
    if kind == "tree":
        seeds: Iterable[str] = TREES_KNOWN
    elif kind == "arch":
        seeds = ARCH_KNOWN
    elif kind == "branch":
        seeds = _branch_stops(check)
    else:
        seeds = ()
    # The one in force, split like any other multi-valued answer: a box that did not
    # offer `riscv,mainline` as its two names would print the pair as one candidate.
    seen = _seen_names(kind, rows, table) | set(_names(_field_of(check, kind)))
    found = [one for one in seeds if _token(one)]
    found += sorted(one for one in seen if one and _token(one) and one not in found)
    return found


def _branch_stops(check: "Filter") -> list[str]:
    """The branches the trees in force bind to, in the order the config lists them.

    One tree is the ordinary case (`_branches_from_config(tree)`).  `tree` is a
    multi-valued axis now, and with several trees on, the branches in force could be
    any of theirs - so the candidates are the union of those trees' own, which is the
    most a per-tree source can say honestly (`_vocabulary`'s third bullet).

    No tree at all keeps its old answer: `_branches_from_config("")` is every branch
    name the vendored trees declare (76 of them), and `BRANCH_SEEDS` is the floor for
    a checkout without them.  The empty result of a checkout that has the directory
    but no matching file falls back the same way, because a box with no candidates and
    no rail is a box the reader has to guess at.
    """
    trees = _names(check.tree)
    if not trees:
        found = list(_branches_from_config(""))
    else:
        found = []
        for tree in trees:
            for one in _branches_from_config(tree):
                if one not in found:
                    found.append(one)
    return found or list(BRANCH_SEEDS)


def _check_group(name: str, stops: Iterable[str], current: str, list_id: str,
                 label: str, lang: str = DEFAULT_LANG) -> str:
    """One value axis as tick boxes: several values of one axis, stated in one form.

    The shape the multi-valued axes are asked with (`schema.MULTI_FIELDS`).  What is
    in force is what is ticked, which is the one thing a comma-joined text box cannot
    show, and the boxes carry the field's own `name` - so the form submits
    `?tree=riscv&tree=mainline`, a repeated key that `filter.Filter.from_query` reads
    with `_named_many` while every link this console writes canonicalises the same
    answer to `?tree=riscv,mainline` (`_names`).

    **Ticking a box does not submit the bar**, and that is the one line `_JS` spends
    on this shape (`data-multi`): one tick is not a decision when the gesture is
    "tick these three", and a bar that reloaded on each of them would be three page
    loads and three API reads for one question.  The `apply` button beside them is
    the gesture, and with the script off it is the only one - which is the same
    promise every other control in this bar keeps.

    **A name nobody listed is still typeable.**  The last control is `_name_field`'s
    free box - the one the axis had before it grew boxes - carrying whatever `current`
    names that `stops` does not offer, and the page's own `_named_many` joins the two
    on the way back in.  That is why a tick and a typed value are one answer and not
    two controls for one condition.

    No rail and no count badge: eleven boxes do not need a slider to step through,
    and a number beside the label would be read as the number the axes strip prints
    for the same axis, which is a different and a meaningful one (`_combo`).
    """
    stops = [str(one) for one in stops]
    named = _names(current)
    offered = set(stops)
    boxes = "".join(
        f'<label class="check"><input type="checkbox" data-multi="1" '
        f'name="{html.escape(name)}" value="{html.escape(one)}"'
        + (" checked" if one in named else "")
        + f"><span>{html.escape(one)}</span></label>"
        for one in stops)
    return (_datalist(list_id, stops)
            + f'<fieldset class="field w-checks" data-checks="{html.escape(name)}">'
            + f"<legend>{html.escape(label)}</legend>"
            + f'<div class="checks">{boxes}</div>'
            + _name_field(name, ",".join(one for one in named if one not in offered),
                          t(lang, "filter.type_one"), list_id, lang)
            + "</fieldset>")


def _datalist(list_id: str, values: Iterable[str],
              labels: Mapping[str, str] | None = None) -> str:
    """The candidate list for an open text field (a tree, a branch, an API).

    A `<datalist>` suggests without constraining: the API takes any name, and a
    tree that appeared after this page was written must still be typeable.  The
    value is checked on the server (`_named`) whatever the list offered.

    `labels` is optional text for a candidate - the API box offers `local` and
    `http://127.0.0.1:8001`, and each one is shown under the other's name, so a
    reader who does not know the shorthand can see what it stands for.  The value is
    what a browser submits either way; only the text beside it changes.
    """
    labels = labels or {}
    return (f'<datalist id="{html.escape(list_id)}">'
            + "".join(f'<option value="{html.escape(str(one))}">'
                      f'{html.escape(str(labels.get(one, "")))}</option>' for one in values)
            + "</datalist>")


def _stops_attr(stops: Iterable[str]) -> str:
    """The suggestion set as a `data-stops` attribute, or `""` when there is none.

    Data, not markup: with the script off nothing reads it, and the field is the plain
    box it has always been.  It is packed as JSON because that is what the script can
    read back with `JSON.parse`, and escaped for an attribute because a tree or a
    defconfig name may contain a quote (`x86_64_defconfig+allnoconfig`).
    """
    packed = [str(one) for one in stops]
    if not packed:
        return ""
    return f' data-stops="{html.escape(json.dumps(packed), quote=True)}"'


def _name_field(name: str, value: str, label: str, list_id: str,
                lang: str = DEFAULT_LANG, placeholder: str = "",
                stops: Iterable[str] = (), note: str = "") -> str:
    """A text field with a candidate list: a name nothing can enumerate.

    `placeholder` is what an empty box means.  `(any)` is right for a name that
    filters nothing, and wrong for a box whose empty value is a real address: there
    the placeholder says *which* base empty stands for.

    `stops` is the suggestion set the page's script builds a rail from (`_rail`), and
    `note` is a small number the label carries beside itself - how many stops the set
    has, which is the one fact a reader needs to know the rail is worth using.  Both
    are optional and both degrade to nothing.
    """
    stops = [str(one) for one in stops]
    badge = (f' <span class="n" title="{html.escape(note)}">{len(stops)}</span>'
             if stops and note else "")
    return (f'<div class="field w-name"><label for="f-{html.escape(name)}">'
            f'{html.escape(label)}{badge}</label>'
            f'<input id="f-{html.escape(name)}" name="{html.escape(name)}" '
            f'list="{html.escape(list_id)}" value="{html.escape(value)}" '
            f'placeholder="{html.escape(placeholder or t(lang, "state.any_paren"))}" '
            f'autocomplete="off"{_stops_attr(stops)}></div>')


def _num(name: str, value: str, label: str, low: int, high: int,
         list_id: str = "", stops: Iterable[str] = ()) -> str:
    """A number field: free to type, bounded in the box, clamped on the server.

    `min`/`max` let the browser refuse an absurd number in the reader's own
    language, which is free.  The server clamps anyway (`Filter.from_query`),
    because a URL is hand-editable and a typo deserves a note, not a 500.

    `stops` is the suggestion set, handed to the page's script in `data-stops` so it
    can build the rail.  It is *data*, not markup: with the script off nothing reads
    it, and the field is the plain number box it has always been.  `days` and `rows`
    are the two that need it most: the operator asked for "有一些可以滑下来的选项"
    instead of a row of ten buttons, and `rows` is also the page's latency lever, so
    its stops are its six costs (`_coverage`).
    """
    return (f'<div class="field w-num"><label for="f-{html.escape(name)}">'
            f'{html.escape(label)}</label>'
            f'<input id="f-{html.escape(name)}" name="{html.escape(name)}" type="number" '
            f'min="{int(low)}" max="{int(high)}" step="1" value="{html.escape(str(value))}"'
            + (f' list="{html.escape(list_id)}"' if list_id else "")
            + _stops_attr(stops) + "></div>")


def _quick(name: str, route: str, check: "Filter", current: str,
           choices: Iterable[tuple[str, str]], lead: str = "",
           keep: Iterable[tuple[str, str]] = (), lang: str = DEFAULT_LANG,
           off: Mapping[str, str] | None = None) -> str:
    """The presets beside a field: one click each, and the URL stays the state.

    A datalist is only a suggestion in some browsers (Firefox opens it on the down
    arrow), so the same values are repeated as links.  The one in force is marked,
    which is also how a reader sees the value a free number box is holding.

    `keep` is the page's own state that is not a filter field (the worker's mode
    and claim filters, the analysis page's two builds): a preset that dropped it
    would answer a different question than the page the reader is standing on.

    `off` is the values this page must **not** offer as a link, as `value -> why`.
    A blocked value is printed where it was, in the same pill slot and under its own
    name, and it is a `<span>` and not an `<a>`: the reason is in its `title=` and
    the `aria-disabled` says so to a screen reader.  This is `_tick_box`'s shape for
    a row that cannot be ticked, and the same argument: a value a reader can click
    and cannot have is worse than one that says why not.  A page uses it when a value
    it *shows* is one the button behind it would refuse - the worker's `platform`
    filter names every platform the lab config declares, and the worker on this host
    can only boot one of them - so the row and the button are read off one list and
    cannot disagree.
    """
    pairs = dict(keep)
    # A `value -> ""` entry is no reason at all, so it is not a block: the mapping is
    # the reasons, and a caller that passes every value it looked at (with the allowed
    # ones empty) means the same thing as one that left them out.
    blocked = {value: why for value, why in (off or {}).items() if why}
    links = "".join(
        (f'<span class="off" aria-disabled="true" '
         f'title="{html.escape(blocked[value])}">{html.escape(label)}</span>')
        if value in blocked else
        (f'<a href="{html.escape(_url(route, check, lang=lang, **{**pairs, name: value}))}"'
         + (' aria-current="true"' if value == current else "")
         + f'>{html.escape(label)}</a>')
        for label, value in choices)
    return (f'<span class="quick"><span class="lead">{html.escape(lead or name)}:</span>'
            f"{links}</span>")
