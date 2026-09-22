# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reading a request: one query string or form body as the values a page may use.

`_first` and `_numbers` are how a value is read; `_token`, `_named` and `_chosen`
are what may come back, and `_clamp` is the bound a hand-edited URL is held to.  A
name is refused rather than repaired (`error.not_a_name`) and a select box's value
has to be one of its options (`_chosen`, `error.not_an_option`): every one of these
values can reach a command line, which is why the alphabet is checked here and not
at the argv (`_token` owns that check).

`_api_query` is the other half: the key/value pairs one page really sends to the API,
in the order it sends them.  The read itself (`Gui.remote_rows`), the line the page
prints as its question (`Gui.remote_query`) and the per-axis counts (`Gui._axis_counts`)
all come from that one function, so the page can never print a query it did not ask
- the bug that made an operator copy `tree=riscv` out of the page and get **0**."""

import re
import time
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from .. import errors, poller
from ..build import ARTIFACTS
from ..i18n import DEFAULT_LANG, t
from ..kbuild import KBUILD_JOB
from ..tests import DEFAULT_TESTS, TESTS
from .schema import (
    API_FILTERS,
    API_MAX,
    FILTER_ORDER,
    MAX_DAYS,
    MULTI_FIELDS,
    NO_WINDOW,
)

if TYPE_CHECKING:
    from .models import Filter

# ---------------------------------------------------------------------------
# Reading forms and queries
# ---------------------------------------------------------------------------

# What may reach a command line: a name this tree could have offered itself.
# `_named()` and `_token()` both go through it, so a tree, a branch, a test name
# and a build id are held to the same alphabet.
TOKEN = re.compile(r"[A-Za-z0-9._+-]{1,64}")


def _first(form: Mapping[str, list[str]], key: str, default: str = "") -> str:
    """One value of a form or a query string, or the default when it is absent."""
    values = form.get(key) or []
    return values[0] if values and values[0] else default


def _numbers(form: Mapping[str, list[str]], key: str, default: int) -> int:
    """One integer out of a form or a query string, or the default when it is not one.

    The bound is the caller's: `Filter` knows what a window and a row cap may be,
    and `command()` clamps with the same two, so neither has to guess.
    """
    try:
        return int(_first(form, key, str(default)))
    except ValueError:
        return default


def _clamp(value: int, low: int, high: int) -> int:
    """A number inside its bound: a hand-edited URL is a value to fix, not a 500."""
    return min(high, max(low, int(value)))


def _tests_of(check: "Filter") -> tuple[str, ...]:
    """The tests a page's rows are one per: the chosen one, or the catalogue's default set.

    One spelling of the rule, so the rows a page prints and the `re.todo()` count
    it quotes against are about the same pairs.
    """
    return (check.test,) if check.test in TESTS else DEFAULT_TESTS


def _ticks(form: Mapping[str, list[str]]) -> list[str]:
    """The ticked rows as build ids - the only ids a page sends, and they were clicked."""
    return [one for one in (_token(one) for one in (form.get("selected") or [])) if one]


def _token(value: str) -> str:
    """A value that may reach a command line: short, ASCII, and only boring characters.

    The character class is spelled out rather than asked of `str.isalnum()`, which
    is Unicode-aware: it answered True for `树`, so a name that is not ASCII went
    through this check and into an argv.  Nothing here needs a non-ASCII name, and
    `/` stays out, so `../../etc` is refused too.
    """
    value = str(value or "")
    return value if TOKEN.fullmatch(value) else ""


def _chosen(form: Mapping[str, list[str]], key: str, options: Iterable[str], default: str,
            lang: str = DEFAULT_LANG) -> str:
    """A select box's value: one of the options, or the default, never something typed."""
    value = _first(form, key)
    if not value:
        return default
    if value not in options:
        raise errors.ConfigError(t(lang, "error.not_an_option", key=key, value=repr(value),
                                   options=", ".join(one or t(lang, "state.any_paren")
                                                     for one in options)))
    return value


def _offered(form: Mapping[str, list[str]], key: str, options: Iterable[str], default: str,
             lang: str = DEFAULT_LANG) -> str:
    """`_chosen`'s rule for an option list too long to print: the same refusal, without it.

    The rule is identical - a value the box did not offer is refused, never repaired -
    and the only thing that differs is the message.  `_chosen` names every option it
    would have taken, which is right for a box of three tests and wrong for the worker's
    `platform`: its options are the platforms the vendored scheduler config declares
    (131 of them), and the refusal is printed *on the page* - `_argv_of` catches it and
    puts it in `<code class="argv">` under the button that sent it (`action.refused`).
    Naming them there would answer a hand-edited URL with two kilobytes of lab hardware.

    The count stands where the names stood, and it is the same number: the length of
    the list this function just checked the value against.
    """
    value = _first(form, key)
    if not value:
        return default
    options = tuple(options)
    if value not in options:
        raise errors.ConfigError(t(lang, "error.not_an_option_n", key=key, value=repr(value),
                                   n=len(options)))
    return value


def _named(form: Mapping[str, list[str]], key: str, lang: str = DEFAULT_LANG) -> str:
    """A free-ish field (a tree, a branch): its value, refused when it is not a plain name."""
    value = _first(form, key)
    if value and not _token(value):
        raise errors.ConfigError(t(lang, "error.not_a_name", key=key, value=repr(value)))
    return value


def _names(value: str) -> tuple[str, ...]:
    """A filter field's value as the names it names: one, several, or none.

    The multi-valued axes (`MULTI_FIELDS`) travel as **one comma-joined value** and
    not as a repeated key, which is the cheap route this codebase already takes
    (`_artifacts`, `_axes`) and the only one `_url` can carry: it collapses a query
    through a dict, so a second `?tree=` would not survive a round trip through any
    link this console writes.  Both spellings are readable (`_named_many` reads the
    repeated key too), and this is the one function that turns either into a list.
    """
    return tuple(one for one in (part.strip() for part in str(value or "").split(","))
                 if one)


def _named_many(form: Mapping[str, list[str]], key: str, lang: str = DEFAULT_LANG) -> str:
    """`_named`'s rule for a field that may name several values: all of them, joined.

    **Every** value the form or query string carried under this key is read - the
    repeated key a tick-box group submits (`?tree=a&tree=b`) and the comma-joined
    value every link carries (`?tree=a,b`) are the same answer - each part is held to
    `_token()`, and the result is the canonical comma-joined spelling `to_query()`
    puts back in a URL.  Duplicates collapse to the first occurrence, so a form that
    submits both spellings of one value cannot make the page ask twice.

    The refusal is `_named`'s, with the whole value quoted: a name that could reach a
    command line is the only thing this alphabet is for, and a part that is not one is
    a refusal rather than a repair.
    """
    parts = [one for value in (form.get(key) or []) for one in _names(str(value))]
    if any(not _token(one) for one in parts):
        raise errors.ConfigError(t(lang, "error.not_a_name", key=key,
                                   value=repr(",".join(parts))))
    return ",".join(dict.fromkeys(parts))


def _artifacts(value: str) -> tuple[str, ...]:
    """A query's artifact list: our artifact names, comma or space separated, unknown ones dropped."""
    return tuple(name for name in (one.strip() for one in (value or "").replace(",", " ").split())
                 if name in ARTIFACTS)


def _flag(name: str, value: str) -> list[str]:
    """`--name value`, or nothing at all when the value is empty."""
    return [name, value] if value else []


def _pairs(name: str, values: Iterable[str]) -> list[str]:
    """`--name v` for every value - how one flag carries a whole selection."""
    return [part for value in values for part in (name, value)]


def _api_url(value: str) -> str:
    """One `?api=` value as an API base URL - `""` when this page refuses it.

    Refused, and why each one is refused rather than repaired:

    * **only `http` and `https`**: a base is an address a client is pointed at, and
      a scheme this page cannot talk is not one.  `file:///etc/passwd`,
      `javascript:alert(1)` and `ftp://x/` all die on the scheme, which is the only
      thing any of them has in common with an API;
    * **a non-empty host**: `http://` alone names nothing, so it is nothing;
    * **at most `API_MAX` characters**, and **printable ASCII only**: an address
      with a newline, a space or a non-ASCII host is not an address an operator
      typed, and this string ends up in an argv (`--api-url`) where a stray
      whitespace is a second argument.

    A refusal is *not* an error page: the caller falls back to the base this
    deployment started on and the page answers 200, because a hand-edited URL is a
    normal way of asking and a page that dies on one tells its reader nothing.  The
    value is also **not** remembered - `Filter.api_raw` carries it only far enough
    for the clamp note to say it was dropped.

    The name form (`local`, `production`, `launch`) is not a URL and never reaches
    here: `Apis.base()` looks a name up first and asks this only about a literal.
    """
    value = str(value or "")
    if not value or len(value) > API_MAX:
        return ""
    if any(one <= " " or one > "~" for one in value):
        return ""
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return value.rstrip("/")


def _iso_days(days: int) -> str:
    """The ISO-8601 timestamp `days` days back (UTC, seconds) - the window's own value.

    The same rule as `lib/kbuild.py::_iso_ago`, written here because this is the file
    that *prints* the query: the page shows `created__gte=<this>`, and a line that
    quotes a window it did not send would be the paraphrase `02-filters.md` §A3 is
    about.  The clamp is the second guard and not decoration: an absurd `days` reaches
    `time.gmtime` as an epoch outside the platform's range and comes back as
    `OSError: [Errno 75]`, which on a page is an HTTP 500.
    """
    days = _clamp(int(days), NO_WINDOW, MAX_DAYS)
    if days <= 0:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400))


def _iso_stamp(value: str) -> str:
    """One timestamp as the stamp the poller reads, or `""` for anything it cannot.

    `--since` is handed to `poller.iso_ago()`, so which stamps can be read at all is
    `poller.parse_iso`'s to say, and this asks it rather than restating the list - the
    page and the worker disagreeing about the shape is the failure being guarded
    against, and two copies of the answer would be a way to have it.  What is left
    here is the refusal.  A stamp `parse_iso` cannot read is not an error the worker
    reports: it is *silently* replaced by a 15-minute window, which is precisely the
    window `?since=2026-09-20 08:20` was passed to widen.  So a value this page cannot
    honour is refused (`error.not_a_stamp`), never printed into an argv the child
    would ignore.

    The value is re-spelled in the canonical shape rather than echoed back, so what
    the page prints is one shape whichever shape was pasted - and a shape the reader
    is likelier to recognise.  The pasted shape is rarely the canonical one: `/worker`'s
    `created` column prints `created[:16]` (`2026-09-20T08:20`), and the API's own node
    timestamps carry microseconds and no `Z`.
    """
    parsed = poller.parse_iso(value)
    if parsed is None:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(parsed))


def _axis_pairs(name: str, path: str, value: str) -> list[tuple[str, str]]:
    """One filter axis as the pairs the API is really asked: `__in` for several values.

    **Established by execution against the production API, not read off a call site.**
    `kernelci-api`'s `Node.translate_fields` splits a `key__op` into `(key, op)` and
    maps `op` through `OPERATOR_MAP`, and `in` is `$in` - so the operator form is
    `data.<field>__in=<comma list>`.  Four `kind=kbuild` counts on `api.kernelci.org`
    are what say so, and the second and third are the ones that matter:

        data.kernel_revision.tree=riscv                  -> 79
        data.kernel_revision.tree=mainline               -> 441
        data.kernel_revision.tree__in=riscv,mainline     -> 520   (= 79 + 441, a union)
        data.kernel_revision.tree__in=mainline,riscv     -> 520   (order is irrelevant)
        data.kernel_revision.tree=riscv,mainline         -> None  (no OR, and 38 s)

    The plain comma-joined value is **not** an "any of these": it answered nothing at
    all, which is the failure mode a filter may never have (`02-filters.md` §A1.3's
    silent `0`).  A repeated key is not a way out either - `get_nodes` does
    `dict(request.query_params)`, so `?a=1&a=2` arrives as `a=2` and the first value is
    lost in the web framework, before any query is built.

    One value is sent as the **plain** key, byte for byte what every single-value URL
    sent before this function existed: `__in` with one value is equivalent
    (`data.arch__in=riscv` counted 1756, the same as `data.arch=riscv`), and there is no
    reason to re-spell a query that already works.
    """
    if name in MULTI_FIELDS:
        parts = _names(value)
        if len(parts) > 1:
            return [(f"{path}__in", ",".join(parts))]
    return [(path, value)]


def _api_query(check: "Filter", kind: str = "kbuild") -> list[tuple[str, str]]:
    """The key/value pairs this page really sends, in the order it sends them.

    One function, three readers: the read itself (`Gui.remote_rows`, which hands these
    pairs to `Kbuilds.getdays(extra=…)`), the line the page
    prints as its question (`Gui.remote_query`), and the per-axis counts the axes strip
    badges (`Gui._axis_counts`).  They used to be a paraphrase plus a read: the line
    said `job=` where the key is `name=`, `tree=` where it is
    `data.kernel_revision.tree=`, and `no window (all)` where the query simply had no
    `created__gte` - and an operator who copied `tree=riscv` out of it got **0**,
    because `tree` is not a key the API has (`02-filters.md` §A3).  This line is the
    query an operator copies into a command, so it prints the wire's own spelling.

    Only keys in `API_FILTERS` for this `kind` are emitted, in `FILTER_ORDER`, so a
    value this deployment has no verified path for is never sent and never printed:
    the API's silent `0` is the failure mode a whitelist exists to prevent.
    """
    pairs: list[tuple[str, str]] = [("kind", kind), ("name", KBUILD_JOB)]
    window = _iso_days(check.days)
    if window:
        pairs.append(("created__gte", window))
    for name in FILTER_ORDER:
        path = API_FILTERS.get(name, {}).get(kind, "")
        value = str(getattr(check, name, "") or "")
        if path and value:
            pairs.extend(_axis_pairs(name, path, value))
    return pairs


def _query_text(pairs: Iterable[tuple[str, str]]) -> str:
    """`_api_query`'s pairs as the one line a reader can paste into a command."""
    return " ".join(f"{key}={value}" for key, value in pairs)
