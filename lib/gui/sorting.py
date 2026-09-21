# SPDX-License-Identifier: LGPL-2.1-or-later
"""The order one list is in: the vocabulary, the parser and the sorter.

An order is a *list* of keys, each with its own direction (`_sort_keys`), and it is a
condition and not page state: a row's adjacent delta is defined by the order it is in,
so `sort` is a `Filter` field (every link, chip and command carries it for free) and
is read by `/analysis` alone.  `_sort_spec` and `_sort_refused` are what
`Filter.from_query` reads - a key nobody knows is dropped and reported, never obeyed,
and a round-1 spelling (`same-branch`) is an alias rather than a refusal - while
`_sort_control`/`_sort_label` are the same order as a URL and as words, and
`_sort_rows` is the one place a page's rows are put in order."""

import html
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from .. import errors
from ..i18n import DEFAULT_LANG, t
from .schema import SORT_ALIASES, SORT_KEYS
from .urls import _url

if TYPE_CHECKING:
    from .models import Filter

# The verdicts in the order "by verdict" means: the ones a reader is looking for
# first, and `""` (no record at all) last rather than first - an empty cell is the
# absence of an answer, not a verdict.
_VERDICT_ORDER = ("fail", errors.VERDICT_ERROR, "incomplete", errors.VERDICT_PASS, "")


def _sort_keys(raw: str) -> tuple[tuple[str, str], ...]:
    """An order as `((key, direction), …)`, primary key first - the operator's list.

    One query value, comma-separated, each component `key` or `key:dir`
    (`sort=tree-branch,date:desc`).  One value and not a repeated key because
    `Filter.to_query` returns one pair per key and `_url` collapses the result through a
    dict, so a repeated `sort=` would be silently reduced to its last component by every
    link in this program - the comma-joined list is what `missing`/`has` already do.

    A round-1 spelling (`date-asc`, `same-branch`, `verdict`, `build`, `""`) is an alias
    for a list (`SORT_ALIASES`), so every URL written against the old control still means
    what it meant.  An unknown component is **dropped**, and `Filter.clamps` says so: a
    page that silently reordered itself is the one thing this filter may not do.
    """
    if raw in SORT_ALIASES:
        return SORT_ALIASES[raw]
    found = []
    for part in str(raw or "").split(","):
        name, _, direction = part.strip().partition(":")
        if name not in SORT_KEYS:
            continue
        default = SORT_KEYS[name][0]
        if any(seen == name for seen, _ in found):
            continue
        found.append((name, "asc" if direction == "asc" else
                      "desc" if direction == "desc" else default))
    return tuple(found) or SORT_ALIASES[""]


def _sort_refused(raw: str) -> str:
    """The order a URL asked for when it named a key this page does not have, else `""`.

    Only an *unknown key* is a refusal: `tree-branch,date:desc` and its canonical
    `tree-branch,date` are the same order, and a reader who spells a default out has
    not been refused anything.  `""` and the round-1 spellings are aliases, so they are
    not refusals either.
    """
    if not raw or raw in SORT_ALIASES:
        return ""
    for part in str(raw).split(","):
        if part.strip().partition(":")[0] not in SORT_KEYS:
            return raw
    return ""


def _sort_spec(raw: str) -> str:
    """The canonical spelling of an order: what `Filter.sort` holds and a URL carries.

    Canonical so that one order has one URL - the round-1 spellings are read and then
    written back as the list they mean, and an order whose keys are all invalid becomes
    the default and carries no `sort` key at all.
    """
    keys = _sort_keys(raw)
    if keys == SORT_ALIASES[""]:
        return ""
    return ",".join(name if direction == SORT_KEYS[name][0] else f"{name}:{direction}"
                    for name, direction in keys)


def _sort_label(key: "str | tuple[tuple[str, str], ...]", lang: str = DEFAULT_LANG) -> str:
    """The order's own name, out of the catalogue - the page never spells one in code.

    A list is named key by key with its arrows (`总分支 ↑, 日期 ↓`), which is what the
    axes strip, the sort control and the headings' sub-lines all print.  A bare string
    is a *value a URL carried*: it is read as the round-1 vocabulary first
    (`_sort_keys`), so `same-branch` still prints as the order it means rather than as
    three catalogue misses.
    """
    if isinstance(key, str):
        key = _sort_keys(key)
    return ", ".join(f'{t(lang, "sort.k." + name.replace("-", "_"))} '
                     + t(lang, "sort.dir.asc" if direction == "asc" else "sort.dir.desc")
                     for name, direction in key)


def _sort_cell(row: Mapping[str, Any], name: str) -> Any:
    """One sort key's value in one row, as something comparable and never raising.

    A row is a plain dict and different lists carry different keys; a key a list cannot
    answer sorts as the empty string, which is what lets one sorter serve the builds
    half and the runs half without either of them declaring a schema.  Numbers and the
    verdict rank are the two that are not text: `bytes`/`records` compare as ints, and a
    verdict compares by `_VERDICT_ORDER` (worst first), because alphabetical order would
    put `fail` after `error` for no reader's reason.
    """
    if name == "tree-branch":
        return (str(row.get("tree") or ""), str(row.get("branch") or ""))
    if name == "verdict":
        found = row.get("verdict")
        return _VERDICT_ORDER.index(found) if found in _VERDICT_ORDER else len(_VERDICT_ORDER)
    if name == "id":
        return str(row.get("build_id") or "")
    if name == "date":
        return (str(row.get("created") or row.get("timestamp") or ""),
                str(row.get("build_id") or ""))
    return str(row.get(name) or "")


def _sort_control(route: str, check: "Filter", keys: "tuple[tuple[str, str], ...]",
                  keep: Iterable[tuple[str, str]] = (), drop_added: Iterable[str] = (),
                  lang: str = DEFAULT_LANG) -> str:
    """The order, as the list of keys in force plus one link that adds each key.

    The operator asked for two things here and they are one control: **several keys at
    once** and **the order visible enough to change one of them**.  So the keys in force
    are chips numbered by position - each with an arrow that reverses it and an `×` that
    removes it - and every key *not* in force is a `+key` link that appends it at its
    default direction.  「先按总分支排，再按日期排」 is then `+总分支` and `+日期`: two
    presses, and the URL after each one says what the order is (`sort=tree-branch` then
    `sort=tree-branch,date`).

    Every link goes through `_url` and carries `keep` (the page's own state that is not
    a filter: the two chosen builds on `/analysis`), so changing the order never changes
    the question.  No JavaScript: the state is the URL, which is what makes an order
    shareable by copying the address bar - and `filter.sort` stays in the controlling
    form's `rendered=` list, so pressing `apply` keeps it.
    """
    keys = tuple(keys)
    chips = []
    for at, (name, direction) in enumerate(keys):
        label = t(lang, "sort.k." + name.replace("-", "_"))
        arrow = t(lang, "sort.dir.asc" if direction == "asc" else "sort.dir.desc")
        # Reversing one key keeps its position and every other key: the order lives in
        # the URL as text, so it is edited as text and re-parsed by `_sort_keys`.
        flipped = [(other, ("desc" if direction == "asc" else "asc") if other == name
                    else other_dir) for other, other_dir in keys]
        chips.append(
            f'<span class="chip">{at + 1}. {html.escape(label)} '
            f'<a href="{html.escape(_url(route, check, keep=keep, lang=lang, sort=_sort_spec_of(flipped)))}"'
            f' title="{html.escape(t(lang, "sort.flip_title"))}">{html.escape(arrow)}</a>'
            f' <a href="{html.escape(_url(route, check, keep=keep, lang=lang, sort=_sort_spec_of([one for one in keys if one[0] != name])))}"'
            f' title="{html.escape(t(lang, "sort.drop_title"))}">&times;</a></span>')
    added = {name for name, _ in keys}
    appends = "".join(
        f'<a href="{html.escape(_url(route, check, keep=keep, lang=lang, sort=_sort_spec_of([*keys, (name, SORT_KEYS[name][0])])))}"'
        f'>{html.escape(t(lang, "sort.add", key=t(lang, "sort.k." + name.replace("-", "_"))))}</a>'
        for name in SORT_KEYS if name not in added)
    return (f'<span class="quick"><span class="lead">'
            f'{html.escape(t(lang, "filter.sort"))}:</span>'
            + "".join(chips) + appends + "</span>")


def _sort_spec_of(keys: "Iterable[tuple[str, str]]") -> str:
    """The URL spelling of an order built in code: the default direction is left out.

    One spelling of one order, shared with `_sort_spec`'s parse of what a reader typed,
    so a link this control writes and a URL a reader edits mean the same thing.
    """
    return ",".join(name if direction == SORT_KEYS[name][0] else f"{name}:{direction}"
                    for name, direction in keys)


def _sort_rows(rows: list[dict[str, Any]],
               key: "str | tuple[tuple[str, str], ...] | None") -> list[dict[str, Any]]:
    """The one place an `/analysis` list is put in order - and the reason `sort` exists.

    The operator's model in one sentence: *selection decides the content, the order
    decides what is compared with what.*  So both halves of the page come through here -
    the builds the config half compares and the runs the regression half lists - and the
    header, the deltas and the chart all read the same answer.

    **Several keys, each with its own direction** (「先按总分支排，再按日期排」).  Python's
    sort is stable, so the list is composed right to left: the last key sorts first and
    the primary key is applied last, which is the only way to spell "descending inside an
    ascending group" without a hand-rolled comparison.  A bare string is read as the
    round-1 vocabulary (`_sort_keys`), which is what makes every existing caller and
    bookmark keep working.
    """
    keys = _sort_keys(key) if isinstance(key, str) or key is None else tuple(key)
    found = list(rows)
    for name, direction in reversed(keys):
        found.sort(key=lambda row: _sort_cell(row, name), reverse=(direction == "desc"))
    return found
